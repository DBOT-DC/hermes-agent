#!/usr/bin/env python3
"""
Tests for the Roo Code port — Mode System, Tool Gating, Task Hierarchy,
Orchestrator, HermesIgnore, Context Sliding Window.
"""

import json
import os
import sys
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ============================================================================
# Mode System Tests
# ============================================================================

class TestModes:
    """Tests for agent/modes.py"""

    def test_builtin_modes_loaded(self):
        from agent.modes import get_all_modes
        modes = get_all_modes()
        slugs = {m.slug for m in modes}
        assert "code" in slugs
        assert "architect" in slugs
        assert "ask" in slugs
        assert "debug" in slugs
        assert "orchestrator" in slugs

    def test_mode_dataclass_fields(self):
        from agent.modes import get_mode
        code = get_mode("code")
        assert code.slug == "code"
        assert code.name == "Code"
        assert code.role_definition
        assert code.when_to_use
        assert "read" in code.tool_groups
        assert "edit" in code.tool_groups
        assert code.source == "hermes"

    def test_set_active_mode(self):
        from agent.modes import set_active_mode, get_active_mode
        mode = set_active_mode("code")
        assert mode.slug == "code"
        assert get_active_mode().slug == "code"

    def test_set_active_mode_invalid(self):
        from agent.modes import set_active_mode
        with pytest.raises(ValueError, match="Unknown mode"):
            set_active_mode("nonexistent_mode")

    def test_set_active_mode_clear(self):
        from agent.modes import set_active_mode, get_active_mode
        set_active_mode("code")
        assert get_active_mode() is not None
        set_active_mode("")
        assert get_active_mode() is None

    def test_list_modes(self):
        from agent.modes import list_modes
        modes = list_modes()
        assert isinstance(modes, dict)
        assert len(modes) >= 5

    def test_orchestrator_has_full_tool_access(self):
        from agent.modes import get_mode
        orch = get_mode("orchestrator")
        # Orchestrator has full access — it switches modes to gate tools per phase
        assert "read" in orch.tool_groups
        assert "edit" in orch.tool_groups
        assert "command" in orch.tool_groups
        assert "mcp" in orch.tool_groups

    def test_ask_no_edit_command(self):
        from agent.modes import get_mode
        ask = get_mode("ask")
        assert "edit" not in ask.tool_groups
        assert "command" not in ask.tool_groups
        assert "read" in ask.tool_groups

    def test_architect_file_constraint(self):
        from agent.modes import get_mode
        arch = get_mode("architect")
        assert arch.has_file_constraint()
        assert arch.constraints.get("file_regex")

    def test_is_tool_allowed_code_mode(self):
        from agent.modes import get_mode
        code = get_mode("code")
        assert code.is_tool_allowed("read_file")
        assert code.is_tool_allowed("write_file")
        assert code.is_tool_allowed("terminal")
        assert code.is_tool_allowed("switch_mode")

    def test_is_tool_allowed_ask_mode(self):
        from agent.modes import get_mode
        ask = get_mode("ask")
        assert ask.is_tool_allowed("read_file")
        assert not ask.is_tool_allowed("write_file")
        assert not ask.is_tool_allowed("terminal")
        assert ask.is_tool_allowed("switch_mode")

    def test_is_tool_allowed_orchestrator_mode(self):
        from agent.modes import get_mode
        orch = get_mode("orchestrator")
        # Orchestrator has full access — switches modes to gate per phase
        assert orch.is_tool_allowed("read_file")
        assert orch.is_tool_allowed("write_file")
        assert orch.is_tool_allowed("terminal")
        assert orch.is_tool_allowed("switch_mode")
        assert orch.is_tool_allowed("delegate_task")

    def test_always_available_tools_bypass_gating(self):
        from agent.modes import get_mode
        orch = get_mode("orchestrator")
        for tool in ["switch_mode", "delegate_task", "todo", "memory", "clarify"]:
            assert orch.is_tool_allowed(tool), f"{tool} should be always available"

    def test_get_allowed_tools(self):
        from agent.modes import get_mode
        code = get_mode("code")
        allowed = code.get_allowed_tools()
        assert "read_file" in allowed
        assert "write_file" in allowed
        assert "switch_mode" in allowed

    def test_reload_modes(self):
        from agent.modes import reload_modes, list_modes
        reload_modes()
        modes = list_modes()
        assert len(modes) >= 5

    def test_bundled_modes_loaded(self):
        from agent.modes import get_all_modes
        modes = get_all_modes()
        slugs = {m.slug for m in modes}
        # At least some bundled modes should load
        assert len(slugs) >= 10  # 5 built-in + bundled

    def test_reasoning_effort(self):
        from agent.modes import get_mode
        assert get_mode("ask").reasoning_effort == "none"
        assert get_mode("code").reasoning_effort == "standard"
        assert get_mode("architect").reasoning_effort == "heavy"
        assert get_mode("debug").reasoning_effort == "heavy"
        assert get_mode("orchestrator").reasoning_effort == "heavy"

    def test_reasoning_directives(self):
        from agent.modes import get_mode
        assert get_mode("debug").reasoning_directives
        assert get_mode("orchestrator").reasoning_directives


# ============================================================================
# Tool Gating Tests
# ============================================================================

class TestToolGating:
    """Tests for mode-based tool filtering in model_tools.py"""

    def test_code_mode_includes_terminal(self):
        from model_tools import get_tool_definitions
        from agent.modes import get_mode
        code = get_mode("code")
        tools = get_tool_definitions(quiet_mode=True, active_mode=code)
        names = {t["function"]["name"] for t in tools}
        assert "terminal" in names
        assert "write_file" in names
        assert "read_file" in names

    def test_ask_mode_excludes_terminal(self):
        from model_tools import get_tool_definitions
        from agent.modes import get_mode
        ask = get_mode("ask")
        tools = get_tool_definitions(quiet_mode=True, active_mode=ask)
        names = {t["function"]["name"] for t in tools}
        assert "terminal" not in names
        assert "write_file" not in names
        assert "read_file" in names
        assert "switch_mode" in names

    def test_orchestrator_mode_full_tools(self):
        from model_tools import get_tool_definitions
        from agent.modes import get_mode
        orch = get_mode("orchestrator")
        tools = get_tool_definitions(quiet_mode=True, active_mode=orch)
        names = {t["function"]["name"] for t in tools}
        # Orchestrator has full tool access (switches modes to gate per phase)
        assert "terminal" in names
        assert "write_file" in names
        assert "read_file" in names
        assert "switch_mode" in names
        assert "delegate_task" in names
        assert "todo" in names

    def test_no_mode_returns_all_tools(self):
        from model_tools import get_tool_definitions
        all_tools = get_tool_definitions(quiet_mode=True, active_mode=None)
        code_tools = get_tool_definitions(
            quiet_mode=True,
            active_mode=__import__("agent.modes", fromlist=["get_mode"]).get_mode("code"),
        )
        # No mode should return >= tools as code mode
        assert len(all_tools) >= len(code_tools)

    def test_switch_mode_registered(self):
        from model_tools import get_tool_definitions
        tools = get_tool_definitions(quiet_mode=True)
        names = {t["function"]["name"] for t in tools}
        assert "switch_mode" in names


# ============================================================================
# Switch Mode Tool Tests
# ============================================================================

class TestSwitchModeTool:
    """Tests for tools/mode_tool.py"""

    def test_switch_to_code(self):
        from tools.mode_tool import switch_mode_handler
        result = json.loads(switch_mode_handler({"mode": "code"}))
        assert result["success"] is True
        assert result["slug"] == "code"
        assert result["mode"] == "Code"
        assert "available_tools" in result

    def test_switch_to_invalid_mode(self):
        from tools.mode_tool import switch_mode_handler
        result = json.loads(switch_mode_handler({"mode": "nonexistent"}))
        assert result["success"] is False
        assert "error" in result

    def test_switch_no_mode(self):
        from tools.mode_tool import switch_mode_handler
        result = json.loads(switch_mode_handler({"mode": ""}))
        assert result["success"] is False
        assert "error" in result


# ============================================================================
# Task Hierarchy Tests
# ============================================================================

class TestTaskHierarchy:
    """Tests for agent/task_hierarchy.py"""

    def test_create_task(self):
        from agent.task_hierarchy import TaskHierarchyManager
        mgr = TaskHierarchyManager()
        task_id = mgr.create_task("Build feature")
        assert task_id
        task = mgr.get_task(task_id)
        assert task.description == "Build feature"
        assert task.status == "pending"

    def test_create_child_task(self):
        from agent.task_hierarchy import TaskHierarchyManager
        mgr = TaskHierarchyManager()
        root = mgr.create_task("Root task")
        child = mgr.create_task("Child task", parent_task_id=root)
        assert root in mgr.get_task(child).parent_task_id or mgr.get_task(root).children == [child]

    def test_update_status(self):
        from agent.task_hierarchy import TaskHierarchyManager
        mgr = TaskHierarchyManager()
        task_id = mgr.create_task("Task")
        mgr.update_status(task_id, "completed", result="Done!")
        task = mgr.get_task(task_id)
        assert task.status == "completed"
        assert task.result == "Done!"

    def test_aggregate_result(self):
        from agent.task_hierarchy import TaskHierarchyManager
        mgr = TaskHierarchyManager()
        root = mgr.create_task("Root")
        c1 = mgr.create_task("Child 1", parent_task_id=root)
        c2 = mgr.create_task("Child 2", parent_task_id=root)
        mgr.update_status(c1, "completed", result="Result 1")
        mgr.update_status(c2, "failed", error="Error 2")
        agg = mgr.aggregate_result(root)
        assert agg["status"] == "failed"
        assert agg["completed"] == 1
        assert agg["total"] == 3  # root + 2 children
        assert "Result 1" in agg["results"]
        assert "Error 2" in agg["errors"]

    def test_get_children(self):
        from agent.task_hierarchy import TaskHierarchyManager
        mgr = TaskHierarchyManager()
        root = mgr.create_task("Root")
        c1 = mgr.create_task("C1", parent_task_id=root)
        c2 = mgr.create_task("C2", parent_task_id=root)
        children = mgr.get_children(root)
        assert len(children) == 2

    def test_clear(self):
        from agent.task_hierarchy import TaskHierarchyManager
        mgr = TaskHierarchyManager()
        mgr.create_task("Task")
        mgr.clear()
        assert mgr.get_root_task() is None

    def test_get_subtree(self):
        from agent.task_hierarchy import TaskHierarchyManager
        mgr = TaskHierarchyManager()
        root = mgr.create_task("Root")
        c1 = mgr.create_task("C1", parent_task_id=root)
        c2 = mgr.create_task("C2", parent_task_id=root)
        gc = mgr.create_task("GC", parent_task_id=c1)
        subtree = mgr.get_subtree(root)
        assert len(subtree) == 4

    def test_singleton_manager(self):
        from agent.task_hierarchy import get_manager, reset_manager
        reset_manager()
        mgr1 = get_manager()
        mgr2 = get_manager()
        assert mgr1 is mgr2
        reset_manager()


# ============================================================================
# Orchestrator Tests
# ============================================================================

class TestOrchestrator:
    """Tests for agent/orchestrator.py"""

    def test_plan_single_task(self):
        from agent.orchestrator import OrchestratorEngine
        engine = OrchestratorEngine()
        plan = engine.plan_task("Fix the login bug")
        assert len(plan) == 1
        assert plan[0].mode == "debug"

    def test_plan_numbered_list(self):
        from agent.orchestrator import OrchestratorEngine
        engine = OrchestratorEngine()
        plan = engine.plan_task("1. Design the API\n2. Implement the API\n3. Write tests")
        assert len(plan) == 3
        assert plan[0].mode == "architect"  # "Design" → architect
        assert plan[1].mode == "code"  # "Implement" → code
        assert plan[2].mode == "code"  # "Write tests" → code

    def test_plan_bullet_list(self):
        from agent.orchestrator import OrchestratorEngine
        engine = OrchestratorEngine()
        plan = engine.plan_task("- Research the topic\n- Write summary\n- Send to team")
        assert len(plan) == 3

    def test_infer_mode_keywords(self):
        from agent.orchestrator import OrchestratorEngine
        engine = OrchestratorEngine()
        assert engine._infer_mode("Design the architecture") == "architect"
        assert engine._infer_mode("What is the meaning of life?") == "ask"
        assert engine._infer_mode("Fix the crash in production") == "debug"
        assert engine._infer_mode("Add a new endpoint") == "code"

    def test_execute_plan(self):
        from agent.orchestrator import OrchestratorEngine
        engine = OrchestratorEngine()
        plan = engine.plan_task("1. Design API\n2. Implement API")
        result = engine.execute_plan(plan)
        assert result["status"] == "completed"
        assert result["completed"] == 2
        assert result["failed"] == 0

    def test_cancel(self):
        from agent.orchestrator import OrchestratorEngine
        engine = OrchestratorEngine()
        plan = engine.plan_task("1. Task A\n2. Task B\n3. Task C")
        plan[1].status = "in_progress"
        engine._current_plan = plan
        engine.cancel()
        assert plan[0].status == "cancelled"
        assert plan[1].status == "in_progress"  # Not cancelled — already in progress
        assert plan[2].status == "cancelled"

    def test_get_status(self):
        from agent.orchestrator import OrchestratorEngine
        engine = OrchestratorEngine()
        status = engine.get_status()
        assert status["status"] == "idle"


# ============================================================================
# HermesIgnore Tests
# ============================================================================

class TestHermesIgnore:
    """Tests for agent/hermesignore.py"""

    def test_parse_line_comment(self):
        from agent.hermesignore import HermesIgnore
        assert HermesIgnore.parse_line("# comment") is None
        # parse_line doesn't strip whitespace — that's load_from_file's job
        assert HermesIgnore.parse_line("  # indented comment") is not None

    def test_parse_line_blank(self):
        from agent.hermesignore import HermesIgnore
        assert HermesIgnore.parse_line("") is None
        assert HermesIgnore.parse_line("   ") is None

    def test_parse_line_normal(self):
        from agent.hermesignore import HermesIgnore
        result = HermesIgnore.parse_line("*.log")
        assert result == (False, "*.log")

    def test_parse_line_negation(self):
        from agent.hermesignore import HermesIgnore
        result = HermesIgnore.parse_line("!important.log")
        assert result == (True, "important.log")

    def test_ignore_patterns(self):
        from agent.hermesignore import HermesIgnore
        with tempfile.NamedTemporaryFile(mode="w", suffix=".hermesignore", delete=False) as f:
            f.write("*.log\nbuild/\n!important.log\n")
            tmp = f.name
        try:
            ignore = HermesIgnore()
            ignore.load_from_file(Path(tmp))
            assert ignore.is_ignored(Path("app/test.log"))
            assert ignore.is_ignored(Path("build/output.js"))
            assert not ignore.is_ignored(Path("app/important.log"))
            assert not ignore.is_ignored(Path("src/main.py"))
        finally:
            os.unlink(tmp)

    def test_glob_to_regex_star(self):
        from agent.hermesignore import HermesIgnore
        import re
        pattern = HermesIgnore._glob_to_regex("*.log")
        pat = re.compile(pattern)
        assert pat.search("test.log")
        assert pat.search("app/test.log")
        assert not pat.search("test.txt")

    def test_glob_to_regex_doublestar(self):
        from agent.hermesignore import HermesIgnore
        import re
        pattern = HermesIgnore._glob_to_regex("**/test")
        pat = re.compile(pattern)
        assert pat.search("test")
        assert pat.search("a/test")
        assert pat.search("a/b/test")

    def test_glob_to_regex_directory(self):
        from agent.hermesignore import HermesIgnore
        import re
        pattern = HermesIgnore._glob_to_regex("build/")
        pat = re.compile(pattern)
        assert pat.search("build/output.js")
        assert pat.search("src/build/app.js")
        assert not pat.search("buildfile.txt")


# ============================================================================
# Context Sliding Window Tests
# ============================================================================

class TestSlidingWindow:
    """Tests for context_compressor.py sliding window truncation"""

    @pytest.fixture
    def compressor(self):
        from agent.context_compressor import ContextCompressor
        # ContextCompressor requires a model name; pass dummy args
        return ContextCompressor(model="test-model")

    def test_sliding_window_truncate(self, compressor):
        messages = [
            {"role": "system", "content": "You are helpful."},
        ] + [
            {"role": "user", "content": f"Message {i}"} for i in range(20)
        ]
        result = compressor.sliding_window_truncate(messages, target_percent=50)
        # System + half the user messages
        assert len(result) < len(messages)
        assert result[0]["role"] == "system"

    def test_sliding_window_preserves_system(self, compressor):
        messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
        ]
        result = compressor.sliding_window_truncate(messages, target_percent=50)
        assert any(m["role"] == "system" for m in result)

    def test_sliding_window_small_input(self, compressor):
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
        ]
        result = compressor.sliding_window_truncate(messages, target_percent=75)
        assert len(result) == len(messages)  # No truncation needed


# ============================================================================
# Toolsets Integration Tests
# ============================================================================

class TestToolsetsIntegration:
    """Tests for toolsets.py additions"""

    def test_always_available_tools_set(self):
        from toolsets import ALWAYS_AVAILABLE_TOOLS
        assert "switch_mode" in ALWAYS_AVAILABLE_TOOLS
        assert "delegate_task" in ALWAYS_AVAILABLE_TOOLS
        assert "todo" in ALWAYS_AVAILABLE_TOOLS
        assert "memory" in ALWAYS_AVAILABLE_TOOLS

    def test_tool_groups_defined(self):
        from toolsets import TOOL_GROUPS
        assert "read" in TOOL_GROUPS
        assert "edit" in TOOL_GROUPS
        assert "command" in TOOL_GROUPS
        assert "mcp" in TOOL_GROUPS
        assert "read_file" in TOOL_GROUPS["read"]
        assert "terminal" in TOOL_GROUPS["command"]
        assert "write_file" in TOOL_GROUPS["edit"]

    def test_mode_tools_in_core(self):
        from toolsets import _HERMES_CORE_TOOLS
        assert "switch_mode" in _HERMES_CORE_TOOLS


# ============================================================================
# Config Tests
# ============================================================================

class TestConfig:
    """Tests for config additions"""

    def test_default_mode_key(self):
        from hermes_cli.config import DEFAULT_CONFIG
        assert "default_mode" in DEFAULT_CONFIG.get("agent", {})

    def test_modes_section(self):
        from hermes_cli.config import DEFAULT_CONFIG
        assert "modes" in DEFAULT_CONFIG
        assert DEFAULT_CONFIG["modes"]["auto_load"] is True

    def test_context_section(self):
        from hermes_cli.config import DEFAULT_CONFIG
        assert "context" in DEFAULT_CONFIG
        # The context section exists (may have been merged with existing keys)
        assert isinstance(DEFAULT_CONFIG["context"], dict)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short", "-o", "addopts="])
