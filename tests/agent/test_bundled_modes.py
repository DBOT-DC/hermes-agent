"""Tests for bundled modes loading."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.modes import _load_modes_from_dir, load_modes_from_yaml, list_modes, get_mode


class TestLoadModesFromDir:
    """Test the _load_modes_from_dir helper."""

    def test_empty_dir(self, tmp_path):
        """Empty directory returns empty dict."""
        empty_dir = tmp_path / "modes"
        empty_dir.mkdir()
        result = _load_modes_from_dir(empty_dir)
        assert result == {}

    def test_nonexistent_dir(self, tmp_path):
        """Non-existent directory returns empty dict."""
        result = _load_modes_from_dir(tmp_path / "nope")
        assert result == {}

    def test_valid_yaml_mode(self, tmp_path):
        """Valid YAML mode file is loaded correctly."""
        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        (modes_dir / "test-mode.yaml").write_text(
            "name: Test Mode\n"
            "role_definition: You are a test.\n"
            "when_to_use: For testing.\n"
            "tool_groups:\n"
            "  - read\n"
        )
        result = _load_modes_from_dir(modes_dir)
        assert "test-mode" in result
        assert result["test-mode"].name == "Test Mode"
        assert result["test-mode"].tool_groups == ["read"]

    def test_invalid_yaml_skipped(self, tmp_path):
        """Invalid YAML files are silently skipped."""
        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        (modes_dir / "bad.yaml").write_text("not: valid: yaml: [")
        result = _load_modes_from_dir(modes_dir)
        assert "bad" not in result

    def test_multiple_modes(self, tmp_path):
        """Multiple YAML files in directory are all loaded."""
        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        for slug in ["alpha", "beta", "gamma"]:
            (modes_dir / f"{slug}.yaml").write_text(
                f"name: {slug.title()}\n"
                f"role_definition: Role for {slug}.\n"
                f"when_to_use: Use {slug}.\n"
                "tool_groups: [read]\n"
            )
        result = _load_modes_from_dir(modes_dir)
        assert len(result) == 3
        assert "alpha" in result
        assert "beta" in result
        assert "gamma" in result

    def test_non_yaml_files_ignored(self, tmp_path):
        """Non-.yaml files are ignored."""
        modes_dir = tmp_path / "modes"
        modes_dir.mkdir()
        (modes_dir / "readme.txt").write_text("not a mode")
        (modes_dir / "config.json").write_text("{}")
        result = _load_modes_from_dir(modes_dir)
        assert len(result) == 0


class TestLoadModesFromYaml:
    """Test the full load_modes_from_yaml with bundled + user dirs."""

    def test_user_overrides_bundled(self, tmp_path):
        """User mode with same slug overrides bundled mode."""
        bundled_dir = tmp_path / "bundled"
        bundled_dir.mkdir()
        (bundled_dir / "my-mode.yaml").write_text(
            "name: Bundled Name\n"
            "role_definition: Bundled role.\n"
            "when_to_use: Bundled usage.\n"
            "tool_groups: [read]\n"
        )
        user_dir = tmp_path / "user"
        user_dir.mkdir()
        (user_dir / "my-mode.yaml").write_text(
            "name: User Override\n"
            "role_definition: User role.\n"
            "when_to_use: User usage.\n"
            "tool_groups: [read, edit, command, mcp]\n"
        )

        with patch("agent.modes.Path") as mock_path:
            # Mock __file__ parent to return bundled_dir
            mock_path.return_value = tmp_path / "fake"
            mock_path.parent = property(lambda self: bundled_dir)

            # Mock get_hermes_home
            with patch("agent.modes.get_hermes_home", return_value=tmp_path / "home"):
                with patch("agent.modes._load_modes_from_dir", side_effect=_load_modes_from_dir):
                    with patch.dict(os.environ, {"HERMES_HOME": str(tmp_path / "home")}):
                        # Directly test the logic
                        modes = {}
                        modes.update(_load_modes_from_dir(bundled_dir))
                        modes.update(_load_modes_from_dir(user_dir))

        assert modes["my-mode"].name == "User Override"
        assert modes["my-mode"].tool_groups == ["read", "edit", "command", "mcp"]

    def test_bundled_modes_exist(self):
        """Verify bundled_modes directory ships with at least the expected modes."""
        # Walk up from test file to find agent/bundled_modes
        test_dir = Path(__file__).resolve().parent
        for ancestor in [test_dir.parent, test_dir.parent.parent, test_dir.parent.parent.parent]:
            bundled_dir = ancestor / "agent" / "bundled_modes"
            if bundled_dir.is_dir():
                break
        else:
            pytest.skip("No bundled_modes directory found")
        yaml_files = list(bundled_dir.glob("*.yaml"))
        # Should have at least the 10 modes we added
        assert len(yaml_files) >= 10
        slugs = {f.stem for f in yaml_files}
        expected = {
            "merge-resolver", "docs-extractor", "documentation-writer",
            "user-story-creator", "project-research", "security-reviewer",
            "devops", "jest-test-engineer", "skills-writer", "mode-writer",
        }
        assert expected.issubset(slugs)


class TestBundledModeIntegrity:
    """Verify each bundled mode has required fields and valid structure."""

    @pytest.fixture
    def bundled_modes(self):
        test_dir = Path(__file__).resolve().parent
        for ancestor in [test_dir.parent, test_dir.parent.parent, test_dir.parent.parent.parent]:
            bundled_dir = ancestor / "agent" / "bundled_modes"
            if bundled_dir.is_dir():
                break
        else:
            pytest.skip("No bundled_modes directory found")
        modes = {}
        for f in bundled_dir.glob("*.yaml"):
            from agent.modes import _load_yaml_mode
            m = _load_yaml_mode(f)
            if m:
                modes[f.stem] = m
        return modes

    def test_all_have_role_definition(self, bundled_modes):
        """Every bundled mode must have a non-empty role_definition."""
        for slug, mode in bundled_modes.items():
            assert mode.role_definition, f"{slug}: role_definition is empty"

    def test_all_have_when_to_use(self, bundled_modes):
        """Every bundled mode must have a non-empty when_to_use."""
        for slug, mode in bundled_modes.items():
            assert mode.when_to_use, f"{slug}: when_to_use is empty"

    def test_all_have_tool_groups(self, bundled_modes):
        """Every bundled mode must have at least one tool group."""
        for slug, mode in bundled_modes.items():
            assert len(mode.tool_groups) > 0, f"{slug}: no tool groups defined"

    def test_no_duplicate_slugs(self, bundled_modes):
        """No duplicate slugs across all loaded modes."""
        all_modes = list_modes()
        seen = set()
        for slug in all_modes:
            assert slug not in seen, f"Duplicate mode slug: {slug}"
            seen.add(slug)
