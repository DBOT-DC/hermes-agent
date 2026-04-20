"""Tests for tools.checkpoint_tool — checkpoint tool handler."""

import pytest
from unittest.mock import patch, MagicMock

from tools.checkpoint_tool import _checkpoint_tool, set_checkpoint_service, _check_fn


class TestCheckpointTool:
    def test_check_fn_always_true(self):
        assert _check_fn() is True

    def test_no_service_initialized(self):
        set_checkpoint_service(None)
        result = _checkpoint_tool("save")
        assert "not initialized" in result

    def test_save_action(self, tmp_path):
        svc = MagicMock()
        svc.save_checkpoint.return_value = {
            "success": True,
            "checkpoint_id": "abc123",
            "short_hash": "abc1234",
            "timestamp": "2026-01-01T00:00:00",
            "reason": "before edit",
        }
        set_checkpoint_service(svc)

        result = _checkpoint_tool("save", message="before edit")
        assert "✅" in result
        assert "abc1234" in result
        svc.save_checkpoint.assert_called_once()

    def test_save_auto_message(self, tmp_path):
        svc = MagicMock()
        svc.save_checkpoint.return_value = {
            "success": True, "checkpoint_id": "abc", "short_hash": "abc1234",
            "timestamp": "2026-01-01T00:00:00", "reason": "auto",
        }
        set_checkpoint_service(svc)

        result = _checkpoint_tool("save")  # no message
        svc.save_checkpoint.assert_called_once()
        call_kwargs = svc.save_checkpoint.call_args
        # Should auto-generate a message
        assert call_kwargs is not None

    def test_restore_action(self, tmp_path):
        svc = MagicMock()
        svc.restore_checkpoint.return_value = {"success": True, "restored_to": "abc123", "reason": "manual"}
        set_checkpoint_service(svc)

        result = _checkpoint_tool("restore", checkpoint_id="abc123")
        assert "✅" in result
        svc.restore_checkpoint.assert_called_once_with(checkpoint_id="abc123", file_path=None)

    def test_restore_missing_id(self, tmp_path):
        svc = MagicMock()
        set_checkpoint_service(svc)

        result = _checkpoint_tool("restore")
        assert "checkpoint_id" in result.lower() or "required" in result.lower()

    def test_list_action(self, tmp_path):
        svc = MagicMock()
        svc.list_checkpoints.return_value = [
            {"short_hash": "abc1234", "timestamp": "2026-01-01T00:00:00",
             "reason": "test", "files_changed": 1, "insertions": 5, "deletions": 2}
        ]
        set_checkpoint_service(svc)

        result = _checkpoint_tool("list")
        assert "abc1234" in result

    def test_diff_action(self, tmp_path):
        svc = MagicMock()
        svc.diff_checkpoint.return_value = {"success": True, "diff": "diff --git a/file b/file\n+new\n-old\n"}
        set_checkpoint_service(svc)

        result = _checkpoint_tool("diff", checkpoint_id="abc123")
        assert "📊" in result

    def test_delete_action(self, tmp_path):
        svc = MagicMock()
        svc.delete_checkpoint.return_value = {"success": True, "restored_to": "parent"}
        set_checkpoint_service(svc)

        result = _checkpoint_tool("delete", checkpoint_id="abc123")
        assert "✅" in result

    def test_clear_action(self, tmp_path):
        svc = MagicMock()
        svc.clear_checkpoints.return_value = {"success": True}
        set_checkpoint_service(svc)

        result = _checkpoint_tool("clear")
        assert "✅" in result

    def test_unknown_action(self, tmp_path):
        svc = MagicMock()
        set_checkpoint_service(svc)

        result = _checkpoint_tool("fly_to_moon")
        assert "Unknown" in result or "unknown" in result

    def teardown_method(self):
        set_checkpoint_service(None)
