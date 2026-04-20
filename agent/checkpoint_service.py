"""
CheckpointService — Agent-owned checkpoint orchestration layer.

Wraps CheckpointManager with per-turn deduplication, auto-save hooks,
and session-level lifecycle so the LLM never directly interacts with
the shadow git repos.

Thread-safe: all public methods acquire the service lock before
dispatching to the underlying CheckpointManager.
"""

from __future__ import annotations

import logging
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from hermes_cli.config import get_hermes_home
from tools.checkpoint_manager import (
    CheckpointManager,
    _normalize_path,
    _shadow_repo_path,
)

logger = logging.getLogger(__name__)

# Placeholder content inserted when middle messages are truncated non-destructively
_TRUNCATION_PLACEHOLDER = (
    "[CONTEXT TRUNCATED — %d earlier turns were removed here to free context space. "
    "A parent reference is preserved so the truncation can be traced back.]"
)


class CheckpointService:
    """Thread-safe checkpoint orchestration for the agent.

    Owned by ``AIAgent``; instantiated when ``checkpoints_enabled=True``.
    All public methods are safe to call from any thread.
    """

    def __init__(
        self,
        enabled: bool = False,
        max_snapshots: int = 50,
        auto_save: bool = True,
        working_dir: Optional[str] = None,
    ):
        self._enabled = enabled
        self._auto_save = auto_save
        self._working_dir = working_dir or str(Path.cwd())
        self._manager = CheckpointManager(enabled=enabled, max_snapshots=max_snapshots)
        self._lock = threading.RLock()
        # Per-turn dedup set — cleared on new_turn()
        self._checkpointed_dirs: set[str] = set()

    # ------------------------------------------------------------------ #
    # Passthrough properties (for backward compat with run_agent.py)
    # ------------------------------------------------------------------ #

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value
        self._manager.enabled = value

    def get_working_dir_for_path(self, file_path: str) -> str:
        """Resolve working directory for a file path."""
        return self._manager.get_working_dir_for_path(file_path)

    def ensure_checkpoint(self, working_dir: str, reason: str = "auto") -> bool:
        """Ensure a checkpoint exists for the given working directory (deduped per turn)."""
        with self._lock:
            if working_dir in self._checkpointed_dirs:
                return False
            result = self._manager.ensure_checkpoint(working_dir, reason)
            if result:
                self._checkpointed_dirs.add(working_dir)
            return result

    def should_checkpoint(self) -> bool:
        """Check if auto-checkpoint is enabled for this turn."""
        return self._enabled and self._auto_save

    # ------------------------------------------------------------------ #
    # Turn lifecycle
    # ------------------------------------------------------------------ #

    def new_turn(self) -> None:
        """Reset per-turn state. Call at the start of each agent iteration."""
        with self._lock:
            self._checkpointed_dirs.clear()
        # Also reset the underlying manager's per-turn state
        self._manager.new_turn()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def save_checkpoint(
        self,
        message: str,
        session_id: Optional[str] = None,
        working_dir: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Take a named checkpoint.

        Args:
            message: Commit message describing this checkpoint.
            session_id: Optional session ID (used in commit subject line only).
            working_dir: Directory to snapshot (default: agent's working dir).

        Returns:
            Dict with success bool, checkpoint id (hash), and optional error.
        """
        if not self._enabled:
            return {"success": False, "error": "Checkpoints are disabled"}

        wd = working_dir or self._working_dir
        with self._lock:
            abs_dir = str(_normalize_path(wd))
            reason = f"[session:{session_id or 'unknown'}] {message}" if session_id else message
            ok = self._manager.ensure_checkpoint(abs_dir, reason)
            if not ok:
                return {"success": False, "error": "Checkpoint was not taken (no changes, already done this turn, or skipped)"}

            # Find the hash of the commit just created
            checkpoints = self._manager.list_checkpoints(abs_dir)
            if checkpoints:
                latest = checkpoints[0]
                return {
                    "success": True,
                    "checkpoint_id": latest["hash"],
                    "short_hash": latest["short_hash"],
                    "timestamp": latest["timestamp"],
                    "reason": latest["reason"],
                }
            return {"success": False, "error": "Checkpoint committed but could not be listed"}

    def restore_checkpoint(
        self,
        checkpoint_id: str,
        working_dir: Optional[str] = None,
        file_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Restore files to a checkpoint state.

        Args:
            checkpoint_id: Full or short commit hash.
            working_dir: Directory to restore (default: agent's working dir).
            file_path: Optional single file to restore (relative path).

        Returns:
            Dict with success bool, restored_to short hash, reason, and optional error.
        """
        if not self._enabled:
            return {"success": False, "error": "Checkpoints are disabled"}

        wd = working_dir or self._working_dir
        with self._lock:
            return self._manager.restore(wd, checkpoint_id, file_path)

    def diff_checkpoint(
        self,
        checkpoint_id: str,
        mode: str = "checkpoint",
        working_dir: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Show diff for a checkpoint.

        Args:
            checkpoint_id: Full or short commit hash.
            mode: One of:
                - "checkpoint" (default): diff between checkpoint and current working tree
                - "from-init": diff from first checkpoint in session
                - "to-current": alias for "checkpoint"
                - "full": full diff of the checkpoint commit itself
            working_dir: Directory to diff (default: agent's working dir).

        Returns:
            Dict with success bool, diff text, stat summary, and optional error.
        """
        if not self._enabled:
            return {"success": False, "error": "Checkpoints are disabled"}

        wd = working_dir or self._working_dir
        with self._lock:
            if mode == "full":
                # Show the actual commit diff (what changed in this checkpoint)
                abs_dir = str(_normalize_path(wd))
                shadow = _shadow_repo_path(abs_dir)
                from tools.checkpoint_manager import _run_git
                ok, diff_out, _ = _run_git(
                    ["show", "--no-color", "--format=", checkpoint_id],
                    shadow, abs_dir,
                )
                return {"success": ok, "diff": diff_out if ok else ""}
            else:
                return self._manager.diff(wd, checkpoint_id)

    def list_checkpoints(
        self,
        working_dir: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List available checkpoints for the working directory.

        Returns a list of dicts with keys: hash, short_hash, timestamp, reason,
        files_changed, insertions, deletions.  Most recent first.
        """
        if not self._enabled:
            return []

        wd = working_dir or self._working_dir
        with self._lock:
            return self._manager.list_checkpoints(wd)

    def delete_checkpoint(
        self,
        checkpoint_id: str,
        working_dir: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Delete a specific checkpoint by dropping the commit.

        Uses ``git reset --hard <parent>`` to remove the commit while
        preserving later checkpoints.

        Returns dict with success bool and error string if any.
        """
        if not self._enabled:
            return {"success": False, "error": "Checkpoints are disabled"}

        from tools.checkpoint_manager import _run_git, _validate_commit_hash

        hash_err = _validate_commit_hash(checkpoint_id)
        if hash_err:
            return {"success": False, "error": hash_err}

        wd = working_dir or self._working_dir
        with self._lock:
            abs_dir = str(_normalize_path(wd))
            shadow = _shadow_repo_path(abs_dir)

            # Verify the commit exists and get its parent
            ok, stdout, err = _run_git(
                ["log", "--format=%H %P", "-1", checkpoint_id],
                shadow, abs_dir,
            )
            if not ok:
                return {"success": False, "error": f"Checkpoint '{checkpoint_id}' not found"}

            parts = stdout.strip().split()
            if len(parts) < 2:
                return {"success": False, "error": "Cannot delete the initial checkpoint (no parent)"}

            parent = parts[1]

            # Reset to parent (this drops the commit but keeps later ones intact)
            ok2, _, err2 = _run_git(
                ["reset", "--hard", parent],
                shadow, abs_dir,
            )
            if not ok2:
                return {"success": False, "error": f"Delete failed: {err2}"}

            return {"success": True, "restored_to": parent[:8]}

    def clear_checkpoints(
        self,
        working_dir: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Delete all checkpoints for a directory by removing the shadow repo.

        Returns dict with success bool and error string if any.
        """
        if not self._enabled:
            return {"success": False, "error": "Checkpoints are disabled"}

        wd = working_dir or self._working_dir
        with self._lock:
            abs_dir = str(_normalize_path(wd))
            shadow = _shadow_repo_path(abs_dir)
            try:
                if shadow.exists():
                    import shutil
                    shutil.rmtree(shadow)
                    logger.info("Cleared all checkpoints for %s", abs_dir)
                    return {"success": True}
                return {"success": False, "error": "No checkpoint repository found"}
            except Exception as e:
                return {"success": False, "error": str(e)}

    def auto_save_before_edit(
        self,
        file_path: str,
        session_id: Optional[str] = None,
    ) -> bool:
        """Take an automatic checkpoint before a file-mutating operation.

        Called by the agent's tool execution layer before write_file, patch,
        or any file mutation.  Deduplicates so at most one checkpoint is
        taken per directory per turn.

        Args:
            file_path: Path to the file about to be modified.
            session_id: Optional session ID for the commit message.

        Returns:
            True if a checkpoint was taken, False otherwise.
        """
        if not (self._enabled and self._auto_save):
            return False

        with self._lock:
            wd = self._manager.get_working_dir_for_path(file_path)
            abs_dir = str(_normalize_path(wd))

            # Per-turn dedup
            if abs_dir in self._checkpointed_dirs:
                return False
            self._checkpointed_dirs.add(abs_dir)

            reason = f"[session:{session_id or 'unknown'}] auto-save before edit"
            try:
                return self._manager.ensure_checkpoint(abs_dir, reason)
            except Exception as e:
                logger.debug("Auto-save checkpoint failed (non-fatal): %s", e)
                return False

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    @property
    def working_dir(self) -> str:
        return self._working_dir

    def set_working_dir(self, wd: str) -> None:
        """Update the working directory (e.g., when the agent changes cwd)."""
        with self._lock:
            self._working_dir = str(Path(wd).expanduser().resolve())
