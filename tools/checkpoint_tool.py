"""
Checkpoint tool — exposes filesystem checkpoint operations to the LLM.

Registered via ``tools.registry.register()`` at module level.
The agent can call these tools directly; they are also available as
slash commands: /checkpoint save, /checkpoint restore, /checkpoint diff,
/checkpoint list, /checkpoint clear.

The underlying CheckpointService is injected at registration time via
a module-level setter so the tool can be stateless (no global singleton).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Callable, Dict, List, Optional

# ------------------------------------------------------------------ #
# Tool schema
# ------------------------------------------------------------------ #

CHECKPOINT_TOOL_NAME = "checkpoint"

CHECKPOINT_TOOL_SCHEMA = {
    "name": CHECKPOINT_TOOL_NAME,
    "description": (
        "Save a named filesystem checkpoint, list existing checkpoints, "
        "restore the working directory (or a single file) to a previous checkpoint, "
        "show what changed since a checkpoint, or clear all checkpoints. "
        "Checkpoints are git-based snapshots stored outside the project directory. "
        "Use 'save' before making risky changes, then 'restore' to undo them."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["save", "restore", "diff", "list", "delete", "clear"],
                "description": "The checkpoint action to perform.",
            },
            "checkpoint_id": {
                "type": "string",
                "description": (
                    "Checkpoint ID (required for restore, diff, and delete actions). "
                    "Use the short hash shown in /checkpoint list output, "
                    "or the full hash for precision."
                ),
            },
            "message": {
                "type": "string",
                "description": (
                    "Commit message for the 'save' action. "
                    "Describe what you're about to do so the checkpoint is easy to identify later. "
                    "Example: 'backup before refactoring auth module'"
                ),
            },
            "file_path": {
                "type": "string",
                "description": (
                    "For 'restore' action only: optionally restore a single file "
                    "(relative path within the working directory) instead of the entire directory."
                ),
            },
            "mode": {
                "type": "string",
                "enum": ["checkpoint", "from-init", "to-current", "full"],
                "default": "checkpoint",
                "description": (
                    "For 'diff' action only. "
                    "'checkpoint' (default): show changes between the checkpoint and current state. "
                    "'full': show the full diff of what changed in the checkpoint itself. "
                    "'from-init' and 'to-current' are aliases for 'checkpoint'."
                ),
            },
        },
        "required": ["action"],
        "additionalProperties": False,
    },
}

# ------------------------------------------------------------------ #
# Module-level CheckpointService injection
# ------------------------------------------------------------------ #

_checkpoint_service: Optional[Any] = None


def set_checkpoint_service(service: Any) -> None:
    """Inject the CheckpointService instance from the owning AIAgent."""
    global _checkpoint_service
    _checkpoint_service = service


# ------------------------------------------------------------------ #
# Tool handler
# ------------------------------------------------------------------ #

logger = logging.getLogger(__name__)


def _checkpoint_tool(
    action: str,
    checkpoint_id: Optional[str] = None,
    message: Optional[str] = None,
    file_path: Optional[str] = None,
    mode: str = "checkpoint",
    session_id: Optional[str] = None,
    working_dir: Optional[str] = None,
    **kwargs,
) -> str:
    """Handle checkpoint tool calls from the LLM.

    All arguments come from the tool schema above.  ``session_id`` and
    ``working_dir`` are injected by the tool dispatch layer when available.
    """
    if _checkpoint_service is None:
        return "Checkpoint service not initialized. Checkpoints are disabled."

    # Normalize mode aliases
    if mode in ("from-init", "to-current"):
        mode = "checkpoint"

    # Build context kwargs
    ctx: Dict[str, Any] = {}
    if working_dir:
        ctx["working_dir"] = working_dir

    if action == "save":
        if not message:
            message = f"manual checkpoint {uuid.uuid4().hex[:8]}"
        result = _checkpoint_service.save_checkpoint(
            message=message,
            session_id=session_id,
            **ctx,
        )
        if result.get("success"):
            short = result.get("short_hash", checkpoint_id or "?")
            return f"✅ Checkpoint saved: `{short}` — {message}"
        return f"❌ Checkpoint not saved: {result.get('error', 'unknown error')}"

    if action == "restore":
        if not checkpoint_id:
            return "❌ restore action requires a checkpoint_id"
        result = _checkpoint_service.restore_checkpoint(
            checkpoint_id=checkpoint_id,
            file_path=file_path,
            **ctx,
        )
        if result.get("success"):
            file_note = f" (file: {file_path})" if file_path else ""
            return f"✅ Restored to checkpoint `{result['restored_to']}`{file_note}: {result.get('reason', '')}"
        return f"❌ Restore failed: {result.get('error', 'unknown error')}"

    if action == "diff":
        if not checkpoint_id:
            # If no checkpoint_id provided, use the most recent
            checkpoints = _checkpoint_service.list_checkpoints(**ctx)
            if checkpoints:
                checkpoint_id = checkpoints[0]["hash"]
            else:
                return "❌ No checkpoints found to diff"
        result = _checkpoint_service.diff_checkpoint(
            checkpoint_id=checkpoint_id,
            mode=mode,
            **ctx,
        )
        if result.get("success"):
            diff_text = result.get("diff", "")
            stat_text = result.get("stat", "")
            output = f"📊 Diff for checkpoint `{checkpoint_id[:8]}`:\n"
            if stat_text:
                output += f"{stat_text}\n"
            if diff_text:
                # Cap diff output to avoid token limits
                MAX_DIFF_LINES = 200
                lines = diff_text.splitlines()
                if len(lines) > MAX_DIFF_LINES:
                    diff_text = "\n".join(lines[:MAX_DIFF_LINES]) + f"\n... ({len(lines) - MAX_DIFF_LINES} more lines)"
                output += f"\n{diff_text}"
            else:
                output += "(no changes)"
            return output
        return f"❌ Diff failed: {result.get('error', 'unknown error')}"

    if action == "list":
        checkpoints = _checkpoint_service.list_checkpoints(**ctx)
        if not checkpoints:
            return "📋 No checkpoints found for this directory.\n\nTake a checkpoint with: /checkpoint save <description>"
        lines = [f"📋 Checkpoints ({len(checkpoints)} total):\n"]
        for i, cp in enumerate(checkpoints, 1):
            ts = cp.get("timestamp", "")
            if "T" in ts:
                date_part, time_part = ts.split("T", 1)
                time_short = time_part.split("+")[0].split("-")[0][:5]
                ts = f"{date_part} {time_short}"
            short = cp.get("short_hash", "?")
            reason = cp.get("reason", "")
            files = cp.get("files_changed", 0)
            ins = cp.get("insertions", 0)
            dele = cp.get("deletions", 0)
            stat = f" ({files} files, +{ins}/-{dele})" if files else ""
            lines.append(f"  {i}. `{short}`  {ts}  {reason}{stat}")
        lines.append("\nTo restore: /checkpoint restore <number or hash>")
        lines.append("To diff:    /checkpoint diff <number or hash>")
        return "\n".join(lines)

    if action == "delete":
        if not checkpoint_id:
            return "❌ delete action requires a checkpoint_id"
        result = _checkpoint_service.delete_checkpoint(
            checkpoint_id=checkpoint_id,
            **ctx,
        )
        if result.get("success"):
            return f"✅ Deleted checkpoint {checkpoint_id[:8]}"
        return f"❌ Delete failed: {result.get('error', 'unknown error')}"

    if action == "clear":
        result = _checkpoint_service.clear_checkpoints(**ctx)
        if result.get("success"):
            return "✅ All checkpoints cleared for this directory"
        return f"❌ Clear failed: {result.get('error', 'unknown error')}"

    return f"❌ Unknown checkpoint action: {action}"


# ------------------------------------------------------------------ #
# Tool registration
# ------------------------------------------------------------------ #

def _check_fn() -> bool:
    """Always available — the CheckpointService itself gates enabled/disabled."""
    return True


from tools.registry import registry

registry.register(
    name=CHECKPOINT_TOOL_NAME,
    toolset="agent",
    schema=CHECKPOINT_TOOL_SCHEMA,
    handler=_checkpoint_tool,
    check_fn=_check_fn,
    description="Save/restore/list filesystem snapshots before making changes",
    emoji="📸",
)
