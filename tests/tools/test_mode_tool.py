"""Tests for tools.mode_tool — switch_mode tool handler."""

import json
import pytest
from unittest.mock import patch

from tools.mode_tool import switch_mode_tool, check_switch_mode_requirements


class TestSwitchModeTool:
    def test_requirements_always_true(self):
        assert check_switch_mode_requirements() is True

    def test_missing_mode_arg(self):
        result = json.loads(switch_mode_tool({"mode": ""}))
        assert "error" in result

    def test_unknown_mode(self):
        result = json.loads(switch_mode_tool({"mode": "nonexistent_xyz"}))
        assert "error" in result
        assert "Unknown mode" in result["error"]

    @patch("agent.modes.set_active_mode")
    @patch("agent.modes.get_mode")
    def test_valid_switch(self, mock_get, mock_set):
        mock_mode = type("Mode", (), {"slug": "code", "name": "Code", "role_definition": "You are a coder.",
                                      "tool_groups": ["read", "edit", "command", "mcp", "modes"],
                                      "when_to_use": "For coding tasks", "allowed_tools": lambda m: set()})
        mock_set.return_value = mock_mode
        mock_get.return_value = mock_mode

        result = json.loads(switch_mode_tool({"mode": "code"}))
        assert result["success"] is True
        assert result["slug"] == "code"
