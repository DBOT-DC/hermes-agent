"""Tests for agent.checkpoint_service — CheckpointService lifecycle and dedup."""

import pytest
from unittest.mock import patch, MagicMock

from agent.checkpoint_service import CheckpointService


class TestCheckpointServiceDisabled:
    """When disabled, all operations should return error dicts or be no-ops."""

    def test_enabled_false(self):
        svc = CheckpointService(enabled=False)
        assert svc.enabled is False

    def test_should_checkpoint_false(self):
        svc = CheckpointService(enabled=False, auto_save=True)
        assert svc.should_checkpoint() is False

    def test_should_checkpoint_disabled_auto(self):
        svc = CheckpointService(enabled=True, auto_save=False)
        assert svc.should_checkpoint() is False

    def test_ensure_checkpoint_disabled(self):
        svc = CheckpointService(enabled=False)
        result = svc.ensure_checkpoint("/tmp", "test")
        assert result is False

    def test_save_checkpoint_disabled(self):
        svc = CheckpointService(enabled=False)
        result = svc.save_checkpoint("test")
        assert result["success"] is False

    def test_restore_checkpoint_disabled(self):
        svc = CheckpointService(enabled=False)
        result = svc.restore_checkpoint("abc123")
        assert result["success"] is False

    def test_list_checkpoints_disabled(self):
        svc = CheckpointService(enabled=False)
        result = svc.list_checkpoints()
        assert result == []

    def test_delete_checkpoint_disabled(self):
        svc = CheckpointService(enabled=False)
        result = svc.delete_checkpoint("abc123")
        assert result["success"] is False

    def test_clear_checkpoints_disabled(self):
        svc = CheckpointService(enabled=False)
        result = svc.clear_checkpoints()
        assert result["success"] is False

    def test_diff_checkpoint_disabled(self):
        svc = CheckpointService(enabled=False)
        result = svc.diff_checkpoint("abc123")
        assert result["success"] is False


class TestCheckpointServiceDedup:
    """Per-turn deduplication for ensure_checkpoint."""

    def test_dedup_same_dir(self):
        svc = CheckpointService(enabled=True, auto_save=True)
        # Mock the internal manager to avoid needing a real git repo
        svc._manager = MagicMock()
        svc._manager.ensure_checkpoint.return_value = True
        svc._manager.get_working_dir_for_path.return_value = "/tmp"

        assert svc.ensure_checkpoint("/tmp", "first") is True
        assert svc.ensure_checkpoint("/tmp", "second") is False  # deduped

    def test_dedup_different_dirs(self):
        svc = CheckpointService(enabled=True, auto_save=True)
        svc._manager = MagicMock()
        svc._manager.ensure_checkpoint.return_value = True
        svc._manager.get_working_dir_for_path.return_value = "/tmp"

        assert svc.ensure_checkpoint("/tmp/a", "first") is True
        assert svc.ensure_checkpoint("/tmp/b", "second") is True  # different dir

    def test_new_turn_clears_dedup(self):
        svc = CheckpointService(enabled=True, auto_save=True)
        svc._manager = MagicMock()
        svc._manager.ensure_checkpoint.return_value = True
        svc._manager.get_working_dir_for_path.return_value = "/tmp"

        assert svc.ensure_checkpoint("/tmp", "first") is True
        assert svc.ensure_checkpoint("/tmp", "second") is False
        svc.new_turn()
        assert svc.ensure_checkpoint("/tmp", "third") is True


class TestCheckpointServiceEnabled:
    """Basic enabled-service tests with mocked git operations."""

    def setup_method(self):
        self.svc = CheckpointService(enabled=True, auto_save=True)
        self.svc._manager = MagicMock()

    def test_working_dir_property(self):
        wd = self.svc.working_dir
        assert wd  # non-empty string

    def test_set_working_dir(self):
        self.svc.set_working_dir("/new/dir")
        assert self.svc.working_dir == "/new/dir"

    def test_get_working_dir_for_path(self):
        self.svc._manager.get_working_dir_for_path.return_value = "/project"
        assert self.svc.get_working_dir_for_path("/project/src/file.py") == "/project"

    def test_save_checkpoint(self):
        self.svc._manager.ensure_checkpoint.return_value = True
        self.svc._manager.list_checkpoints.return_value = [
            {"hash": "abc123", "short_hash": "abc1234", "timestamp": "2026-01-01T00:00:00", "reason": "test"}
        ]
        result = self.svc.save_checkpoint("test message")
        assert result["success"] is True
        assert result["checkpoint_id"] == "abc123"
        self.svc._manager.ensure_checkpoint.assert_called_once()

    def test_list_checkpoints(self):
        self.svc._manager.list_checkpoints.return_value = [
            {"hash": "abc123", "short_hash": "abc1234", "timestamp": "2026-01-01T00:00:00", "reason": "test"}
        ]
        result = self.svc.list_checkpoints()
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["hash"] == "abc123"

    def test_restore_checkpoint(self):
        self.svc._manager.restore.return_value = {"success": True, "restored_to": "abc123"}
        result = self.svc.restore_checkpoint("abc123")
        assert result["success"] is True

    def test_diff_checkpoint(self):
        self.svc._manager.diff.return_value = {"success": True, "diff": "diff --git a/file b/file\n..."}
        result = self.svc.diff_checkpoint("abc123", mode="checkpoint")
        assert result["success"] is True
        assert "diff" in result

    def test_delete_checkpoint(self):
        with patch("tools.checkpoint_manager._run_git") as mock_git:
            mock_git.return_value = (True, "abc123 parent\n", "")
            self.svc._manager.delete_checkpoint.return_value = {"success": True, "restored_to": "parent"}
            result = self.svc.delete_checkpoint("abc123")
            assert result["success"] is True

    def test_clear_checkpoints(self):
        with patch("agent.checkpoint_service._shadow_repo_path") as mock_shadow, \
             patch("agent.checkpoint_service._normalize_path") as mock_norm, \
             patch("shutil.rmtree"):
            mock_norm.return_value = MagicMock()
            mock_shadow.return_value = MagicMock()
            mock_shadow.return_value.exists.return_value = True
            result = self.svc.clear_checkpoints()
            assert result["success"] is True
