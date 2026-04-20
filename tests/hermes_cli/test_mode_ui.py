"""Tests for mode indicator in CLI status line and mode change notifications."""
import pytest
from unittest.mock import patch, MagicMock
from io import StringIO


def _make_cli(model="anthropic/claude-opus-4.6", **kwargs):
    """Create a HermesCLI with minimal mocking for mode UI tests."""
    import cli as _cli_mod
    from cli import HermesCLI

    _clean_config = {
        "model": {
            "default": "anthropic/claude-opus-4.6",
            "base_url": "https://openrouter.ai/api/v1",
            "provider": "auto",
        },
        "display": {"compact": False, "tool_progress": "all", "resume_display": "full"},
        "agent": {},
        "terminal": {"env_type": "local"},
    }
    clean_env = {"LLM_MODEL": "", "HERMES_MAX_ITERATIONS": ""}
    with (
        patch("cli.get_tool_definitions", return_value=[]),
        patch.dict("os.environ", clean_env, clear=False),
        patch.dict(_cli_mod.__dict__, {"CLI_CONFIG": _clean_config}),
    ):
        cli = HermesCLI(model=model, **kwargs)
    return cli


class TestModeIndicatorInStatusLine:
    """Tests that _show_status includes the active mode name."""

    def test_status_line_includes_active_mode_name(self, monkeypatch):
        """When a mode is active, status line shows the mode slug."""
        mock_mode = MagicMock()
        mock_mode.slug = "code"

        # Mock get_active_mode to return our mock mode
        monkeypatch.setattr("agent.modes.get_active_mode", lambda: mock_mode)

        cli = _make_cli()
        cli.api_key = "test-key"

        # Capture console output
        output_buffer = StringIO()
        mock_console = MagicMock()
        mock_console.print = lambda text: output_buffer.write(str(text))

        # Patch console on the cli instance
        with patch.object(cli, "console", mock_console):
            cli._show_status()

        result = output_buffer.getvalue()
        assert "code" in result, f"Expected 'code' mode in status line, got: {result}"

    def test_status_line_shows_no_mode_when_inactive(self, monkeypatch):
        """When no mode is active, status line shows 'no mode'."""
        monkeypatch.setattr("agent.modes.get_active_mode", lambda: None)

        cli = _make_cli()
        cli.api_key = "test-key"

        output_buffer = StringIO()
        mock_console = MagicMock()
        mock_console.print = lambda text: output_buffer.write(str(text))

        with patch.object(cli, "console", mock_console):
            cli._show_status()

        result = output_buffer.getvalue()
        assert "no mode" in result.lower(), f"Expected 'no mode' in status line, got: {result}"

    def test_status_line_includes_mode_between_model_and_tools(self, monkeypatch):
        """Mode name appears between model name and tool count."""
        mock_mode = MagicMock()
        mock_mode.slug = "architect"

        monkeypatch.setattr("agent.modes.get_active_mode", lambda: mock_mode)

        cli = _make_cli(model="anthropic/claude-opus-4.6")
        cli.api_key = "test-key"

        output_buffer = StringIO()
        mock_console = MagicMock()
        mock_console.print = lambda text: output_buffer.write(str(text))

        with patch.object(cli, "console", mock_console):
            cli._show_status()

        result = output_buffer.getvalue()
        # Should have model, then mode, then tool count
        assert "claude-opus" in result
        assert "architect" in result
        assert "tools" in result


class TestModeChangeNotification:
    """Tests that _handle_mode_switch prints mode and tool count on switch."""

    def test_mode_switch_shows_tool_count(self, monkeypatch):
        """When switching mode, notification includes tool count and groups."""
        # Mock the mode that will be returned
        mock_mode = MagicMock()
        mock_mode.slug = "code"
        mock_mode.name = "Code Mode"
        mock_mode.role_definition = "You are a coding assistant."
        mock_mode.tool_groups = ["edit", "bash"]

        monkeypatch.setattr("agent.modes.set_active_mode", lambda slug: mock_mode)
        monkeypatch.setattr("agent.modes.get_active_mode", lambda: mock_mode)
        monkeypatch.setattr("agent.modes.list_modes", lambda: ["code", "architect", "general"])

        # Mock get_tool_definitions to return a known count
        mock_tools = [MagicMock() for _ in range(42)]
        monkeypatch.setattr("cli.get_tool_definitions", lambda **kw: mock_tools)

        cli = _make_cli()
        cli.api_key = "test-key"

        output_buffer = StringIO()

        def mock_cprint(text):
            output_buffer.write(str(text))

        with patch("cli._cprint", mock_cprint):
            cli._handle_mode_switch("/mode code")

        result = output_buffer.getvalue()
        assert "code" in result.lower()
        assert "tools available" in result, f"Expected tool count in output, got: {result}"
        assert "edit" in result and "bash" in result

    def test_mode_switch_shows_delegates_only_when_no_groups(self, monkeypatch):
        """When mode has no tool groups, shows 'delegates only'."""
        mock_mode = MagicMock()
        mock_mode.slug = "general"
        mock_mode.name = "General Mode"
        mock_mode.role_definition = "You are a helpful assistant."
        mock_mode.tool_groups = []

        monkeypatch.setattr("agent.modes.set_active_mode", lambda slug: mock_mode)
        monkeypatch.setattr("agent.modes.list_modes", lambda: ["code", "general"])

        mock_tools = [MagicMock() for _ in range(10)]
        monkeypatch.setattr("cli.get_tool_definitions", lambda **kw: mock_tools)

        cli = _make_cli()
        cli.api_key = "test-key"

        output_buffer = StringIO()

        def mock_cprint(text):
            output_buffer.write(str(text))

        with patch("cli._cprint", mock_cprint):
            cli._handle_mode_switch("/mode general")

        result = output_buffer.getvalue()
        assert "delegates only" in result.lower(), f"Expected 'delegates only' in output, got: {result}"
