"""Tests for agent/prompt_builder.py Roo Code prompt sections.

Tests the following functions (all stateless, no side effects):
  1. build_markdown_rules_section()        -> str
  2. build_tool_use_section()             -> str
  3. build_tool_use_guidelines_section()  -> str
  4. build_capabilities_section(cwd)       -> str
  5. build_modes_section()                -> str
  6. build_system_info_section()           -> str
  7. build_objective_section()             -> str
  8. build_rules_section(cwd)              -> str
  9. build_mode_filtered_skills_section()  -> str
  10. build_mode_prompt(cwd)             -> str (may not exist yet)
  11. _load_project_instructions(cwd)      -> str (may not exist yet)
"""

import os
import sys
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Helper: import all builders at module level for use in class methods
# ---------------------------------------------------------------------------

from agent.prompt_builder import (
    build_markdown_rules_section,
    build_tool_use_section,
    build_tool_use_guidelines_section,
    build_capabilities_section,
    build_modes_section,
    build_system_info_section,
    build_objective_section,
    build_rules_section,
    build_mode_filtered_skills_section,
)
from agent import prompt_builder as pb_module


def _has_build_mode_prompt():
    return hasattr(pb_module, "build_mode_prompt")


def _has_load_project_instructions():
    return hasattr(pb_module, "_load_project_instructions")


# ---------------------------------------------------------------------------
# Import verification
# ---------------------------------------------------------------------------

def test_all_primary_section_functions_are_importable():
    """Verify every section builder is importable from agent.prompt_builder."""
    # These must all exist and be importable
    from agent.prompt_builder import (
        build_markdown_rules_section,
        build_tool_use_section,
        build_tool_use_guidelines_section,
        build_capabilities_section,
        build_modes_section,
        build_system_info_section,
        build_objective_section,
        build_rules_section,
        build_mode_filtered_skills_section,
    )
    # build_mode_prompt and _load_project_instructions may not exist yet
    # We check them separately


def test_build_mode_prompt_importable_if_present():
    """build_mode_prompt is importable only if it exists."""
    if _has_build_mode_prompt():
        from agent.prompt_builder import build_mode_prompt
        assert callable(build_mode_prompt)


def test_load_project_instructions_importable_if_present():
    """_load_project_instructions is importable only if it exists."""
    if _has_load_project_instructions():
        from agent.prompt_builder import _load_project_instructions
        assert callable(_load_project_instructions)


# ---------------------------------------------------------------------------
# 1. build_markdown_rules_section
# ---------------------------------------------------------------------------

class TestBuildMarkdownRulesSection:
    def test_returns_non_empty_string(self):
        result = build_markdown_rules_section()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_contains_markdown_rules_header(self):
        result = build_markdown_rules_section()
        assert "MARKDOWN RULES" in result

    def test_mentions_backtick_filenames(self):
        result = build_markdown_rules_section()
        # Should mention backtick-wrapped filenames like `filename.ext`
        assert "`" in result

    def test_mentions_line_numbers(self):
        result = build_markdown_rules_section()
        # Should reference line numbers in file references like `filename.ext:42`
        assert ":42" in result


# ---------------------------------------------------------------------------
# 2. build_tool_use_section
# ---------------------------------------------------------------------------

class TestBuildToolUseSection:
    def test_returns_non_empty_string(self):
        result = build_tool_use_section()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_contains_tool_use_header(self):
        result = build_tool_use_section()
        assert "TOOL USE" in result

    def test_mentions_tool_calling_mechanism(self):
        result = build_tool_use_section()
        assert "tool-calling mechanism" in result


# ---------------------------------------------------------------------------
# 3. build_tool_use_guidelines_section
# ---------------------------------------------------------------------------

class TestBuildToolUseGuidelinesSection:
    def test_returns_non_empty_string(self):
        result = build_tool_use_guidelines_section()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_contains_tool_use_guidelines_header(self):
        result = build_tool_use_guidelines_section()
        assert "TOOL USE GUIDELINES" in result

    def test_has_three_numbered_items(self):
        result = build_tool_use_guidelines_section()
        # Should contain "1.", "2.", and "3." (with actual newlines, not literal \n)
        assert "1." in result
        assert "2." in result
        assert "3." in result

    def test_numbered_items_sequential(self):
        result = build_tool_use_guidelines_section()
        # The guidelines should appear in order 1, 2, 3
        idx1 = result.index("1.")
        idx2 = result.index("2.")
        idx3 = result.index("3.")
        assert idx1 < idx2 < idx3


# ---------------------------------------------------------------------------
# 4. build_capabilities_section
# ---------------------------------------------------------------------------

class TestBuildCapabilitiesSection:
    def test_returns_non_empty_string(self):
        result = build_capabilities_section()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_contains_capabilities_header(self):
        result = build_capabilities_section()
        assert "CAPABILITIES" in result

    def test_mentions_terminal(self):
        result = build_capabilities_section()
        assert "terminal" in result

    def test_mentions_read_write_files(self):
        result = build_capabilities_section()
        content_lower = result.lower()
        # Should mention ability to read/write files
        assert "read" in content_lower or "write" in content_lower

    def test_mentions_web_search(self):
        result = build_capabilities_section()
        content_lower = result.lower()
        assert "web" in content_lower and "search" in content_lower

    def test_mentions_delegate_task(self):
        result = build_capabilities_section()
        assert "delegate_task" in result

    def test_mentions_memory(self):
        result = build_capabilities_section()
        assert "memory" in result

    def test_with_explicit_cwd_includes_cwd(self):
        """When cwd is provided it should appear in the output."""
        fake_cwd = "/fake/project/root"
        result = build_capabilities_section(cwd=fake_cwd)
        assert fake_cwd in result

    def test_with_none_cwd_defaults_to_os_getcwd(self):
        """When cwd is None it should default to os.getcwd()."""
        with patch("agent.prompt_builder.os.getcwd", return_value="/default/cwd"):
            result = build_capabilities_section(cwd=None)
            assert "/default/cwd" in result


# ---------------------------------------------------------------------------
# 5. build_modes_section
# ---------------------------------------------------------------------------

class TestBuildModesSection:
    def test_modes_module_not_importable_returns_empty_string(self):
        """When agent.modes cannot be imported, should return empty string."""
        # The function catches Exception and returns ""
        # We simulate by patching sys.modules to remove agent.modes
        original_modules = sys.modules.copy()
        try:
            # Remove agent.modes from sys.modules so the import fails
            sys.modules.pop("agent.modes", None)
            # Also need to reload prompt_builder to clear its cached import
            import importlib
            importlib.reload(pb_module)
            result = pb_module.build_modes_section()
            assert result == ""
        finally:
            # Restore original modules
            sys.modules.clear()
            sys.modules.update(original_modules)
            importlib.reload(pb_module)

    def test_modes_module_returns_empty_when_list_modes_is_empty(self):
        """When modes module is importable but list_modes() returns [], return ''."""
        mock_modes_module = MagicMock()
        mock_modes_module.list_modes.return_value = []

        original_modules = sys.modules.copy()
        try:
            sys.modules["agent.modes"] = mock_modes_module
            import importlib
            importlib.reload(pb_module)
            result = pb_module.build_modes_section()
            assert result == ""
        finally:
            sys.modules.clear()
            sys.modules.update(original_modules)
            importlib.reload(pb_module)

    def test_modes_module_available_with_modes_returns_non_empty(self):
        """When modes module is importable and has modes, return non-empty with MODES."""
        mock_mode = MagicMock()
        mock_mode.name = "Test Mode"
        mock_mode.slug = "test-mode"
        mock_mode.role_definition = "You are a test agent."

        mock_modes_module = MagicMock()
        mock_modes_module.list_modes.return_value = [mock_mode]

        original_modules = sys.modules.copy()
        try:
            sys.modules["agent.modes"] = mock_modes_module
            import importlib
            importlib.reload(pb_module)
            result = pb_module.build_modes_section()
            assert isinstance(result, str)
            assert len(result) > 0
            assert "MODES" in result
        finally:
            sys.modules.clear()
            sys.modules.update(original_modules)
            importlib.reload(pb_module)


# ---------------------------------------------------------------------------
# 6. build_system_info_section
# ---------------------------------------------------------------------------

class TestBuildSystemInfoSection:
    def test_returns_non_empty_string(self):
        result = build_system_info_section()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_contains_system_information_header(self):
        result = build_system_info_section()
        assert "SYSTEM INFORMATION" in result

    def test_has_operating_system(self):
        result = build_system_info_section()
        assert "Operating System:" in result

    def test_has_default_shell(self):
        result = build_system_info_section()
        assert "Default Shell:" in result

    def test_has_home_directory(self):
        result = build_system_info_section()
        assert "Home Directory:" in result

    def test_has_current_workspace_directory(self):
        result = build_system_info_section()
        assert "Current Workspace Directory:" in result


# ---------------------------------------------------------------------------
# 7. build_objective_section
# ---------------------------------------------------------------------------

class TestBuildObjectiveSection:
    def test_returns_non_empty_string(self):
        result = build_objective_section()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_contains_objective_header(self):
        result = build_objective_section()
        assert "OBJECTIVE" in result

    def test_mentions_iterative(self):
        result = build_objective_section()
        assert "iteratively" in result.lower() or "iterative" in result.lower()

    def test_mentions_tools(self):
        result = build_objective_section()
        assert "tools" in result.lower()

    def test_mentions_goals(self):
        result = build_objective_section()
        assert "goal" in result.lower()


# ---------------------------------------------------------------------------
# 8. build_rules_section
# ---------------------------------------------------------------------------

class TestBuildRulesSection:
    def test_returns_non_empty_string(self):
        result = build_rules_section()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_contains_rules_header(self):
        result = build_rules_section()
        assert "RULES" in result

    def test_mentions_file_paths(self):
        result = build_rules_section()
        content_lower = result.lower()
        assert "file" in content_lower and "path" in content_lower

    def test_mentions_trash(self):
        result = build_rules_section()
        assert "trash" in result.lower()

    def test_mentions_git(self):
        result = build_rules_section()
        assert "git" in result.lower()

    def test_with_explicit_cwd_includes_cwd(self):
        """When cwd is provided it should appear in the output."""
        fake_cwd = "/my/custom/cwd"
        result = build_rules_section(cwd=fake_cwd)
        assert fake_cwd in result

    def test_with_none_cwd_defaults_to_os_getcwd(self):
        """When cwd is None it should default to os.getcwd()."""
        with patch("agent.prompt_builder.os.getcwd", return_value="/fallback/cwd"):
            result = build_rules_section(cwd=None)
            assert "/fallback/cwd" in result


# ---------------------------------------------------------------------------
# 9. build_mode_filtered_skills_section
# ---------------------------------------------------------------------------

class TestBuildModeFilteredSkillsSection:
    def test_no_active_mode_returns_empty_string(self):
        """When get_active_mode raises an exception, should return empty string."""
        # First put a mock agent.modes module in sys.modules, then patch get_active_mode on it
        mock_modes_module = MagicMock()
        mock_modes_module.get_active_mode.side_effect = Exception("no mode active")

        original_modes = sys.modules.get("agent.modes")
        try:
            sys.modules["agent.modes"] = mock_modes_module
            import importlib
            importlib.reload(pb_module)
            result = pb_module.build_mode_filtered_skills_section()
            assert result == ""
        finally:
            if original_modes is not None:
                sys.modules["agent.modes"] = original_modes
            elif "agent.modes" in sys.modules:
                del sys.modules["agent.modes"]
            importlib.reload(pb_module)

    def test_active_mode_with_skills_returns_non_empty_containing_mode_name(self):
        """When mode is active AND skills exist, result contains mode name."""
        mock_mode = MagicMock()
        mock_mode.name = "Architect"
        mock_mode.slug = "architect"
        mock_mode.role_definition = "You are an architect."

        mock_modes_module = MagicMock()
        mock_modes_module.get_active_mode.return_value = mock_mode

        original_modes = sys.modules.get("agent.modes")
        try:
            sys.modules["agent.modes"] = mock_modes_module
            import importlib
            importlib.reload(pb_module)
            with patch.object(pb_module, "build_skills_system_prompt",
                             return_value="## Skills\n- test_skill: a test skill"):
                result = pb_module.build_mode_filtered_skills_section()
                assert len(result) > 0
                assert "Architect" in result
        finally:
            if original_modes is not None:
                sys.modules["agent.modes"] = original_modes
            elif "agent.modes" in sys.modules:
                del sys.modules["agent.modes"]
            importlib.reload(pb_module)

    def test_active_mode_no_skills_returns_empty(self):
        """When mode is active but build_skills_system_prompt returns '', return ''."""
        mock_mode = MagicMock()
        mock_mode.name = "Architect"
        mock_mode.slug = "architect"
        mock_mode.role_definition = "You are an architect."

        mock_modes_module = MagicMock()
        mock_modes_module.get_active_mode.return_value = mock_mode

        original_modes = sys.modules.get("agent.modes")
        try:
            sys.modules["agent.modes"] = mock_modes_module
            import importlib
            importlib.reload(pb_module)
            with patch.object(pb_module, "build_skills_system_prompt", return_value=""):
                result = pb_module.build_mode_filtered_skills_section()
                assert result == ""
        finally:
            if original_modes is not None:
                sys.modules["agent.modes"] = original_modes
            elif "agent.modes" in sys.modules:
                del sys.modules["agent.modes"]
            importlib.reload(pb_module)


# ---------------------------------------------------------------------------
# 10. build_mode_prompt
# ---------------------------------------------------------------------------

class TestBuildModePrompt:
    def test_function_exists(self):
        """build_mode_prompt should exist in prompt_builder."""
        if not _has_build_mode_prompt():
            pytest.skip("build_mode_prompt not yet implemented in prompt_builder.py")
        from agent.prompt_builder import build_mode_prompt
        assert callable(build_mode_prompt)

    def test_modes_module_not_importable_returns_empty_string(self):
        """When agent.modes cannot be imported, return empty string."""
        if not _has_build_mode_prompt():
            pytest.skip("build_mode_prompt not yet implemented")
        original_modules = sys.modules.copy()
        try:
            sys.modules.pop("agent.modes", None)
            import importlib
            importlib.reload(pb_module)
            result = pb_module.build_mode_prompt(cwd=None)
            assert result == ""
        finally:
            sys.modules.clear()
            sys.modules.update(original_modules)
            importlib.reload(pb_module)

    def test_no_active_mode_returns_empty_string(self):
        """When get_active_mode returns None, return empty string."""
        if not _has_build_mode_prompt():
            pytest.skip("build_mode_prompt not yet implemented")
        # Create a fake agent.modes module with get_active_mode returning None
        import types
        fake_modes = types.ModuleType("agent.modes")
        fake_modes.get_active_mode = lambda: None
        import sys
        sys.modules["agent.modes"] = fake_modes
        try:
            import importlib
            importlib.reload(pb_module)
            result = pb_module.build_mode_prompt(cwd=None)
            assert result == ""
        finally:
            sys.modules.pop("agent.modes", None)
            importlib.reload(pb_module)

    def test_active_mode_returns_string_containing_mode_header(self):
        """When mode is active, result starts with '# Mode:' and contains role_definition."""
        if not _has_build_mode_prompt():
            pytest.skip("build_mode_prompt not yet implemented")
        import types
        mock_mode = MagicMock()
        mock_mode.name = "Orchestrator"
        mock_mode.slug = "orchestrator"
        mock_mode.role_definition = "You are an orchestrator agent."
        mock_mode.custom_instructions = None
        fake_modes = types.ModuleType("agent.modes")
        fake_modes.get_active_mode = lambda: mock_mode
        import sys
        sys.modules["agent.modes"] = fake_modes
        try:
            import importlib
            importlib.reload(pb_module)
            result = pb_module.build_mode_prompt(cwd=None)
            assert isinstance(result, str)
            assert "Orchestrator" in result
            assert "# Mode:" in result
        finally:
            sys.modules.pop("agent.modes", None)
            importlib.reload(pb_module)

    def test_active_orchestrator_mode_includes_delegation_reminder(self):
        """For orchestrator mode, the result should include delegation keyword."""
        if not _has_build_mode_prompt():
            pytest.skip("build_mode_prompt not yet implemented")
        import types
        mock_mode = MagicMock()
        mock_mode.name = "Orchestrator"
        mock_mode.slug = "orchestrator"
        mock_mode.role_definition = "You are an orchestrator agent."
        mock_mode.custom_instructions = None
        fake_modes = types.ModuleType("agent.modes")
        fake_modes.get_active_mode = lambda: mock_mode
        import sys
        sys.modules["agent.modes"] = fake_modes
        try:
            import importlib
            importlib.reload(pb_module)
            result = pb_module.build_mode_prompt(cwd=None)
            assert "delegate" in result.lower()
        finally:
            sys.modules.pop("agent.modes", None)
            importlib.reload(pb_module)


# ---------------------------------------------------------------------------
# 11. _load_project_instructions
# ---------------------------------------------------------------------------

class TestLoadProjectInstructions:
    def test_function_exists(self):
        """_load_project_instructions should exist in prompt_builder."""
        if not _has_load_project_instructions():
            pytest.skip("_load_project_instructions not yet implemented in prompt_builder.py")

    def test_no_instructions_file_returns_empty_string(self, tmp_path):
        """When .hermes/instructions.md does not exist, return empty string."""
        if not _has_load_project_instructions():
            pytest.skip("_load_project_instructions not yet implemented")
        result = pb_module._load_project_instructions(str(tmp_path))
        assert result == ""

    def test_instructions_file_exists_returns_content(self, tmp_path):
        """When .hermes/instructions.md exists, return its content."""
        if not _has_load_project_instructions():
            pytest.skip("_load_project_instructions not yet implemented")
        # Create .hermes/instructions.md
        hermes_dir = tmp_path / ".hermes"
        hermes_dir.mkdir()
        instructions_file = hermes_dir / "instructions.md"
        instructions_file.write_text("# Project Instructions\n\nThese are test instructions.")

        result = pb_module._load_project_instructions(str(tmp_path))

        assert isinstance(result, str)
        assert len(result) > 0
        assert "Project Instructions" in result or "test instructions" in result
