"""Tests for agent.modes — Mode switching, tool gating, file regex constraints."""

import pytest
from unittest.mock import patch, MagicMock

from agent.modes import (
    Mode,
    TOOL_GROUPS,
    ALWAYS_AVAILABLE_TOOLS,
    set_active_mode,
    get_active_mode,
    list_modes,
    get_mode,
    get_mode_tool_groups,
    is_tool_allowed_by_mode,
    reload_modes,
)


# ── Mode dataclass ──────────────────────────────────────────────────


class TestModeDataclass:
    def test_default_fields(self):
        m = Mode(slug="test", name="Test Mode", role_definition="A test role.", when_to_use="Testing.")
        assert m.slug == "test"
        assert m.name == "Test Mode"
        assert m.role_definition == "A test role."
        assert m.tool_groups == []
        assert m.constraints is None

    def test_allowed_tools_empty_groups(self):
        m = Mode(slug="test", name="Test", role_definition="", when_to_use="", tool_groups=[])
        tools = m.allowed_tools
        # With no tool_groups, allowed_tools is empty (ALWAYS_AVAILABLE_TOOLS checked separately)
        assert tools == set()

    def test_allowed_tools_with_group(self):
        m = Mode(slug="test", name="Test", role_definition="", when_to_use="", tool_groups=["read"])
        tools = m.allowed_tools
        for t in TOOL_GROUPS.get("read", []):
            assert t in tools

    def test_is_tool_allowed_always_available(self):
        m = Mode(slug="test", name="Test", role_definition="", when_to_use="", tool_groups=[])
        for t in ALWAYS_AVAILABLE_TOOLS:
            assert m.is_tool_allowed(t, mcp_tools=set()) is True

    def test_is_tool_allowed_grouped_tool(self):
        m = Mode(slug="test", name="Test", role_definition="", when_to_use="", tool_groups=["read"])
        read_tools = TOOL_GROUPS.get("read", [])
        if read_tools:
            assert m.is_tool_allowed(read_tools[0], mcp_tools=set()) is True

    def test_is_tool_allowed_restricted_tool(self):
        m = Mode(slug="test", name="Test", role_definition="", when_to_use="", tool_groups=["read"])
        # write_file should NOT be in read-only mode
        assert m.is_tool_allowed("write_file", mcp_tools=set()) is False

    def test_check_file_regex_no_constraint(self):
        m = Mode(slug="test", name="Test", role_definition="", when_to_use="")
        assert m.check_file_regex("write_file", "/some/file.py") is True

    def test_check_file_regex_with_match(self):
        m = Mode(slug="test", name="Test", role_definition="", when_to_use="", constraints={"file_regex": r"\.md$"})
        assert m.check_file_regex("write_file", "docs/README.md") is True

    def test_check_file_regex_with_mismatch(self):
        m = Mode(slug="test", name="Test", role_definition="", when_to_use="", constraints={"file_regex": r"\.md$"})
        assert m.check_file_regex("write_file", "src/main.py") is False

    def test_check_file_regex_non_edit_tool(self):
        """file_regex only applies to edit-group tools."""
        m = Mode(slug="test", name="Test", role_definition="", when_to_use="", constraints={"file_regex": r"\.md$"})
        # read_file is not in the edit group — should always be allowed
        assert m.check_file_regex("read_file", "src/main.py") is True


# ── Built-in modes ──────────────────────────────────────────────────


class TestBuiltinModes:
    def setup_method(self):
        reload_modes()

    def test_list_modes_returns_strings(self):
        modes = list_modes()
        assert isinstance(modes, list)
        assert all(isinstance(m, str) for m in modes)

    def test_list_modes_includes_code(self):
        modes = list_modes()
        assert "code" in modes

    def test_get_mode_code(self):
        m = get_mode("code")
        assert m is not None
        assert m.slug == "code"

    def test_get_mode_unknown(self):
        assert get_mode("nonexistent_mode_xyz") is None

    def test_set_active_mode_valid(self):
        m = set_active_mode("code")
        assert m.slug == "code"
        assert get_active_mode().slug == "code"

    def test_set_active_mode_invalid(self):
        with pytest.raises(ValueError):
            set_active_mode("nonexistent_mode_xyz")

    def test_get_mode_tool_groups_code(self):
        groups = get_mode_tool_groups("code")
        assert isinstance(groups, list)
        assert len(groups) > 0

    def test_get_mode_tool_groups_unknown(self):
        assert get_mode_tool_groups("nonexistent") == []

    def test_architect_restricts_write(self):
        """Architect mode should restrict write_file/patch to .md files."""
        architect = get_mode("architect")
        with patch("agent.modes.get_mcp_tool_names", return_value=set()):
            allowed = is_tool_allowed_by_mode("write_file", mode=architect, file_path="src/main.py")
            assert allowed is False

    def test_architect_allows_md_write(self):
        architect = get_mode("architect")
        with patch("agent.modes.get_mcp_tool_names", return_value=set()):
            allowed = is_tool_allowed_by_mode("write_file", mode=architect, file_path="docs/plan.md")
            assert allowed is True

    def test_code_allows_all_tools(self):
        """Code mode should allow write_file to any file."""
        code = get_mode("code")
        with patch("agent.modes.get_mcp_tool_names", return_value=set()):
            allowed = is_tool_allowed_by_mode("write_file", mode=code, file_path="src/main.py")
            assert allowed is True

    def test_orchestrator_no_direct_tools(self):
        """Orchestrator mode has empty tool_groups — no direct tool access."""
        m = get_mode("orchestrator")
        if m:
            assert m.tool_groups == []

    def teardown_method(self):
        # Reset to code mode
        try:
            set_active_mode("code")
        except ValueError:
            pass
