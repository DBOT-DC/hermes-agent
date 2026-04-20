"""Tests for batch edit mode in the patch tool."""

import pytest
from types import SimpleNamespace
from unittest.mock import patch as mock_patch, MagicMock

from tools.file_tools import patch_tool


class FakeFileOps:
    """Fake ShellFileOperations for testing."""

    def __init__(self, files=None):
        self.files = files or {}
        self.written = {}
        self.patch_calls = []

    def read_file_raw(self, path):
        content = self.files.get(path)
        if content is None:
            return SimpleNamespace(content=None, error=f"File not found: {path}")
        return SimpleNamespace(content=content, error=None)

    def patch_replace(self, path, old_string, new_string, replace_all):
        self.patch_calls.append({
            "path": path, "old_string": old_string,
            "new_string": new_string, "replace_all": replace_all,
        })
        content = self.files.get(path, "")
        if old_string not in content:
            return SimpleNamespace(
                success=False, diff="", error=f"Could not find old_string in {path}",
                to_dict=lambda: {"success": False, "diff": "", "error": f"Could not find old_string in {path}"}
            )
        new_content = content.replace(old_string, new_string) if replace_all \
            else content.replace(old_string, new_string, 1)
        self.files[path] = new_content
        # Build a minimal unified diff
        old_lines = content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)
        import difflib
        diff_lines = list(difflib.unified_diff(
            old_lines, new_lines, fromfile=path, tofile=path, lineterm=""
        ))
        diff_str = "".join(diff_lines)
        return SimpleNamespace(
            success=True,
            diff=diff_str,
            error=None,
            to_dict=lambda: {"success": True, "diff": diff_str, "error": None},
        )


class TestBatchModeValidation:
    """Pre-flight validation must reject bad changes before any file is written."""

    def test_empty_changes_list_returns_error(self):
        """An empty changes list should return an error."""
        result = patch_tool(mode="batch", changes=[])
        import json
        # tool_error wraps the message differently from batch's standard response
        data = json.loads(result)
        # The tool_error path returns {"error": ...} directly
        assert "error" in data or data.get("success") is False
        assert data.get("applied", []) == []

    def test_missing_path_in_change_returns_error(self):
        """A change without a path should fail validation."""
        fake = FakeFileOps()
        with mock_patch("tools.file_tools._get_file_ops", return_value=fake):
            result = patch_tool(mode="batch", changes=[
                {"old_string": "foo", "new_string": "bar"}
            ])
        import json
        data = json.loads(result)
        assert data["success"] is False
        assert "path and old_string are required" in data["failed"][0]["error"]

    def test_missing_old_string_in_change_returns_error(self):
        """A change without old_string should fail validation."""
        fake = FakeFileOps()
        with mock_patch("tools.file_tools._get_file_ops", return_value=fake):
            result = patch_tool(mode="batch", changes=[
                {"path": "f.py"}
            ])
        import json
        data = json.loads(result)
        assert data["success"] is False

    def test_old_string_not_found_returns_validation_error(self):
        """If old_string doesn't exist in the file, validation should catch it."""
        fake = FakeFileOps({"f.py": "actual content"})
        with mock_patch("tools.file_tools._get_file_ops", return_value=fake):
            result = patch_tool(mode="batch", changes=[
                {"path": "f.py", "old_string": "not present", "new_string": "replaced"}
            ])
        import json
        data = json.loads(result)
        assert data["success"] is False
        assert "old_string not found" in data["failed"][0]["error"]

    def test_file_not_found_returns_validation_error(self):
        """If the file doesn't exist, validation should catch it."""
        fake = FakeFileOps({})
        with mock_patch("tools.file_tools._get_file_ops", return_value=fake):
            result = patch_tool(mode="batch", changes=[
                {"path": "nonexistent.py", "old_string": "foo", "new_string": "bar"}
            ])
        import json
        data = json.loads(result)
        assert data["success"] is False
        assert "File not found" in data["failed"][0]["error"]

    def test_validation_failure_writes_nothing(self):
        """If validation fails, no patch_replace calls should be made."""
        fake = FakeFileOps({"f.py": "content"})
        with mock_patch("tools.file_tools._get_file_ops", return_value=fake):
            patch_tool(mode="batch", changes=[
                {"path": "f.py", "old_string": "not found", "new_string": "bar"}
            ])
        assert fake.patch_calls == [], "No files should have been patched"

    def test_multiple_validation_errors_all_reported(self):
        """All validation errors should be collected, not just the first."""
        fake = FakeFileOps({"a.py": "content a", "b.py": "content b"})
        with mock_patch("tools.file_tools._get_file_ops", return_value=fake):
            result = patch_tool(mode="batch", changes=[
                {"path": "a.py", "old_string": "not found", "new_string": "x"},
                {"path": "b.py", "old_string": "not found", "new_string": "y"},
            ])
        import json
        data = json.loads(result)
        assert data["success"] is False
        assert len(data["failed"]) == 2


class TestBatchModeApply:
    """Successfully validated changes are applied sequentially."""

    def test_single_change_applied(self):
        """A single valid change should be applied and returned in 'applied'."""
        fake = FakeFileOps({"f.py": "hello world"})
        with mock_patch("tools.file_tools._get_file_ops", return_value=fake):
            result = patch_tool(mode="batch", changes=[
                {"path": "f.py", "old_string": "world", "new_string": "hermes"}
            ])
        import json
        data = json.loads(result)
        assert data["success"] is True
        assert data["mode"] == "batch"
        assert len(data["applied"]) == 1
        assert data["applied"][0]["path"] == "f.py"
        assert data["failed"] == []
        assert fake.files["f.py"] == "hello hermes"

    def test_multiple_changes_applied(self):
        """Multiple changes across different files should all be applied."""
        fake = FakeFileOps({"a.py": "foo bar", "b.py": "baz qux"})
        with mock_patch("tools.file_tools._get_file_ops", return_value=fake):
            result = patch_tool(mode="batch", changes=[
                {"path": "a.py", "old_string": "foo", "new_string": "FOO"},
                {"path": "b.py", "old_string": "baz", "new_string": "BAZ"},
            ])
        import json
        data = json.loads(result)
        assert data["success"] is True
        assert len(data["applied"]) == 2
        assert fake.files["a.py"] == "FOO bar"
        assert fake.files["b.py"] == "BAZ qux"

    def test_partial_failure_reports_both_applied_and_failed(self):
        """If one change fails during apply, the successful ones are still applied.

        Note: Pre-flight validation runs first. If it finds any invalid old_string,
        the entire batch is rejected before any file is written. So for this test
        we use valid old_strings but one fails at apply-time (e.g. race condition
        or content changed). We simulate by having both changes pass validation
        but one fail during patch_replace.
        """
        call_count = [0]
        original_patch_replace = FakeFileOps.patch_replace

        def failing_patch_replace(self, path, old_string, new_string, replace_all):
            call_count[0] += 1
            if path == "bad.py":
                return SimpleNamespace(
                    success=False, diff="", error="Simulated failure",
                    to_dict=lambda: {"success": False, "diff": "", "error": "Simulated failure"}
                )
            return original_patch_replace(self, path, old_string, new_string, replace_all)

        fake = FakeFileOps({"good.py": "hello", "bad.py": "world"})
        with mock_patch.object(FakeFileOps, 'patch_replace', failing_patch_replace):
            with mock_patch('tools.file_tools._get_file_ops', return_value=fake):
                result = patch_tool(mode="batch", changes=[
                    {"path": "good.py", "old_string": "hello", "new_string": "hi"},
                    {"path": "bad.py", "old_string": "world", "new_string": "replaced"},
                ])
        import json
        data = json.loads(result)
        assert data["success"] is False
        assert len(data["applied"]) == 1
        assert data["applied"][0]["path"] == "good.py"
        assert len(data["failed"]) == 1
        assert data["failed"][0]["path"] == "bad.py"
        # The good file was still written
        assert fake.files["good.py"] == "hi"

    def test_combined_diff_returned(self):
        """The result should contain a combined diff of all successful changes."""
        fake = FakeFileOps({"a.py": "line1\nline2\n", "b.py": "line3\n"})
        with mock_patch("tools.file_tools._get_file_ops", return_value=fake):
            result = patch_tool(mode="batch", changes=[
                {"path": "a.py", "old_string": "line2", "new_string": "LINE2"},
                {"path": "b.py", "old_string": "line3", "new_string": "LINE3"},
            ])
        import json
        data = json.loads(result)
        assert data["success"] is True
        assert "a.py" in data["diff"]
        assert "b.py" in data["diff"]

    def test_replace_all_option(self):
        """The replace_all option in individual changes should be respected."""
        fake = FakeFileOps({"f.py": "aaa bbb aaa"})
        with mock_patch("tools.file_tools._get_file_ops", return_value=fake):
            result = patch_tool(mode="batch", changes=[
                {"path": "f.py", "old_string": "aaa", "new_string": "XXX", "replace_all": True}
            ])
        import json
        data = json.loads(result)
        assert data["success"] is True
        assert fake.files["f.py"] == "XXX bbb XXX"

    def test_new_string_optional_defaults_to_empty(self):
        """If new_string is omitted, it defaults to empty (deletion)."""
        fake = FakeFileOps({"f.py": "hello world"})
        with mock_patch("tools.file_tools._get_file_ops", return_value=fake):
            result = patch_tool(mode="batch", changes=[
                {"path": "f.py", "old_string": " world"}
            ])
        import json
        data = json.loads(result)
        assert data["success"] is True
        assert fake.files["f.py"] == "hello"


class TestBatchModeSensitivePaths:
    """Sensitive path checking applies to all batch changes."""

    def test_sensitive_path_in_batch_returns_error(self):
        """If any change targets a sensitive path, the whole batch is rejected."""
        with mock_patch("tools.file_tools._check_sensitive_path", return_value="Sensitive!"):
            result = patch_tool(mode="batch", changes=[
                {"path": "/etc/passwd", "old_string": "root", "new_string": "hacked"}
            ])
        import json
        data = json.loads(result)
        assert data.get("error") or "error" in str(data).lower()


class TestBatchModeUnknownMode:
    """Unknown modes should still return appropriate errors."""

    def test_unknown_mode_returns_error(self):
        """An unknown mode should return an error via the replace/patch handler."""
        fake = FakeFileOps()
        with mock_patch("tools.file_tools._get_file_ops", return_value=fake):
            result = patch_tool(mode="unknown_mode", path="f.py", old_string="a", new_string="b")
        import json
        data = json.loads(result)
        assert "Unknown mode" in data["error"]
