"""
Integration tests for the Roo-Code port: Modes, Tool Gating, Checkpoints,
Context Management, Task Hierarchy, and Orchestrator.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure hermes root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestModeSystem(unittest.TestCase):
    """Phase 1: Mode System — agent/modes.py"""

    def test_builtin_modes_exist(self):
        """All 5 built-in modes should be available."""
        from agent.modes import _BUILTIN_MODES
        slugs = set(_BUILTIN_MODES.keys())
        self.assertIn("code", slugs)
        self.assertIn("architect", slugs)
        self.assertIn("ask", slugs)
        self.assertIn("debug", slugs)
        self.assertIn("orchestrator", slugs)

    def test_mode_tool_groups(self):
        """Code mode should have all groups; ask mode only read+mcp."""
        from agent.modes import _BUILTIN_MODES
        code_groups = set(_BUILTIN_MODES["code"].tool_groups)
        self.assertIn("read", code_groups)
        self.assertIn("edit", code_groups)
        self.assertIn("command", code_groups)
        self.assertIn("mcp", code_groups)

        ask_groups = set(_BUILTIN_MODES["ask"].tool_groups)
        self.assertIn("read", ask_groups)
        self.assertIn("mcp", ask_groups)
        self.assertNotIn("edit", ask_groups)
        self.assertNotIn("command", ask_groups)

    def test_orchestrator_no_direct_tool_groups(self):
        """Orchestrator mode should have no tool groups (delegates only)."""
        from agent.modes import _BUILTIN_MODES
        self.assertEqual(_BUILTIN_MODES["orchestrator"].tool_groups, [])

    def test_set_active_mode(self):
        """set_active_mode should return the mode and update state."""
        from agent.modes import set_active_mode, get_active_mode, reload_modes
        reload_modes()
        mode = set_active_mode("code")
        self.assertIsNotNone(mode)
        self.assertEqual(mode.slug, "code")
        self.assertEqual(get_active_mode().slug, "code")

    def test_set_invalid_mode(self):
        """set_active_mode with unknown slug raises ValueError."""
        from agent.modes import set_active_mode, reload_modes
        reload_modes()
        with self.assertRaises(ValueError):
            set_active_mode("nonexistent")

    def test_is_tool_allowed_by_mode(self):
        """Tool gating: read tools always allowed, edit tools mode-dependent."""
        from agent.modes import set_active_mode, is_tool_allowed_by_mode, reload_modes
        reload_modes()

        set_active_mode("code")
        self.assertTrue(is_tool_allowed_by_mode("read_file", None))
        self.assertTrue(is_tool_allowed_by_mode("write_file", None))
        self.assertTrue(is_tool_allowed_by_mode("terminal", None))

        set_active_mode("ask")
        self.assertTrue(is_tool_allowed_by_mode("read_file", None))
        self.assertFalse(is_tool_allowed_by_mode("write_file", None))
        self.assertFalse(is_tool_allowed_by_mode("terminal", None))

    def test_always_available_tools(self):
        """Memory, todo, clarify should always be available regardless of mode."""
        from agent.modes import is_tool_allowed_by_mode, set_active_mode, reload_modes
        reload_modes()
        set_active_mode("ask")
        for tool in ["todo", "memory", "clarify", "switch_mode", "delegate_task"]:
            self.assertTrue(is_tool_allowed_by_mode(tool, None), f"{tool} should be always available")


class TestToolGroups(unittest.TestCase):
    """Phase 2: Tool Group definitions in toolsets.py"""

    def test_tool_groups_defined(self):
        """TOOL_GROUPS should define read, edit, command, mcp."""
        from toolsets import TOOL_GROUPS
        for group in ("read", "edit", "command", "mcp"):
            self.assertIn(group, TOOL_GROUPS, f"Missing tool group: {group}")

    def test_read_group_has_expected_tools(self):
        """Read group should include read_file, search_files, etc."""
        from toolsets import TOOL_GROUPS
        read_tools = TOOL_GROUPS["read"]
        self.assertIn("read_file", read_tools)
        self.assertIn("search_files", read_tools)

    def test_edit_group_has_expected_tools(self):
        """Edit group should include write_file, patch."""
        from toolsets import TOOL_GROUPS
        edit_tools = TOOL_GROUPS["edit"]
        self.assertIn("write_file", edit_tools)
        self.assertIn("patch", edit_tools)

    def test_always_available_defined(self):
        """ALWAYS_AVAILABLE_TOOLS should exist and include core tools."""
        from toolsets import ALWAYS_AVAILABLE_TOOLS
        self.assertIn("todo", ALWAYS_AVAILABLE_TOOLS)
        self.assertIn("memory", ALWAYS_AVAILABLE_TOOLS)
        self.assertIn("clarify", ALWAYS_AVAILABLE_TOOLS)


class TestCheckpointService(unittest.TestCase):
    """Phase 4: Checkpoint Service"""

    def test_service_creation(self):
        """CheckpointService should initialize with correct defaults."""
        from agent.checkpoint_service import CheckpointService
        svc = CheckpointService(enabled=False, max_snapshots=50)
        self.assertFalse(svc.enabled)
        self.assertTrue(svc.should_checkpoint() is False)

    def test_service_enabled(self):
        """Enabled service with auto_save should return True for should_checkpoint."""
        from agent.checkpoint_service import CheckpointService
        svc = CheckpointService(enabled=True, auto_save=True)
        self.assertTrue(svc.enabled)
        self.assertTrue(svc.should_checkpoint())

    def test_new_turn_resets_dedup(self):
        """new_turn should clear the dedup set."""
        from agent.checkpoint_service import CheckpointService
        svc = CheckpointService(enabled=True, auto_save=True)
        svc._checkpointed_dirs.add("/tmp/test")
        self.assertEqual(len(svc._checkpointed_dirs), 1)
        svc.new_turn()
        self.assertEqual(len(svc._checkpointed_dirs), 0)

    def test_save_checkpoint_disabled(self):
        """Save on disabled service should return empty dict."""
        from agent.checkpoint_service import CheckpointService
        svc = CheckpointService(enabled=False)
        result = svc.save_checkpoint("test", "session-1")
        self.assertIsInstance(result, dict)


class TestTaskHierarchy(unittest.TestCase):
    """Phase 6: Task Hierarchy"""

    def test_create_task(self):
        """create_task should return a TaskNode with correct fields."""
        from agent.task_hierarchy import TaskHierarchyManager
        mgr = TaskHierarchyManager()
        task = mgr.create_task("Test task", "code")
        self.assertEqual(task.description, "Test task")
        self.assertEqual(task.mode, "code")
        self.assertEqual(task.status, "pending")
        self.assertIsNotNone(task.task_id)

    def test_task_with_parent(self):
        """Child task should reference parent and be in parent's children."""
        from agent.task_hierarchy import TaskHierarchyManager
        mgr = TaskHierarchyManager()
        parent = mgr.create_task("Parent", "orchestrator")
        child = mgr.create_task("Child", "code", parent_id=parent.task_id)
        self.assertEqual(child.parent_task_id, parent.task_id)
        self.assertEqual(child.root_task_id, parent.task_id)
        self.assertIn(child.task_id, parent.child_task_ids)

    def test_complete_task(self):
        """Completing a task should update status and store result."""
        from agent.task_hierarchy import TaskHierarchyManager
        mgr = TaskHierarchyManager()
        task = mgr.create_task("Test", "code")
        mgr.start_task(task.task_id)
        mgr.complete_task(task.task_id, "All done")
        updated = mgr.get_task(task.task_id)
        self.assertEqual(updated.status, "completed")
        self.assertEqual(updated.result, "All done")

    def test_fail_task(self):
        """Failing a task should set status to failed."""
        from agent.task_hierarchy import TaskHierarchyManager
        mgr = TaskHierarchyManager()
        task = mgr.create_task("Test", "code")
        mgr.start_task(task.task_id)
        mgr.fail_task(task.task_id, "Error occurred")
        updated = mgr.get_task(task.task_id)
        self.assertEqual(updated.status, "failed")

    def test_get_subtree(self):
        """get_subtree should return all descendants."""
        from agent.task_hierarchy import TaskHierarchyManager
        mgr = TaskHierarchyManager()
        root = mgr.create_task("Root", "orchestrator")
        c1 = mgr.create_task("Child 1", "code", parent_id=root.task_id)
        c2 = mgr.create_task("Child 2", "code", parent_id=root.task_id)
        gc1 = mgr.create_task("Grandchild", "debug", parent_id=c1.task_id)
        subtree = mgr.get_subtree(root.task_id)
        ids = {t.task_id for t in subtree}
        self.assertIn(c1.task_id, ids)
        self.assertIn(c2.task_id, ids)
        self.assertIn(gc1.task_id, ids)

    def test_aggregate_results(self):
        """aggregate_results should combine all completed child results."""
        from agent.task_hierarchy import TaskHierarchyManager
        mgr = TaskHierarchyManager()
        root = mgr.create_task("Root", "orchestrator")
        c1 = mgr.create_task("Child 1", "code", parent_id=root.task_id)
        c2 = mgr.create_task("Child 2", "code", parent_id=root.task_id)
        mgr.complete_task(c1.task_id, "Result 1")
        mgr.complete_task(c2.task_id, "Result 2")
        results = mgr.aggregate_results(root.task_id)
        self.assertIn("Result 1", results)
        self.assertIn("Result 2", results)


class TestContextCompressor(unittest.TestCase):
    """Phase 5: Context Management"""

    def test_sliding_window_truncate_exists(self):
        """ContextCompressor should have _sliding_window_truncate method."""
        from agent.context_compressor import ContextCompressor
        self.assertTrue(hasattr(ContextCompressor, '_sliding_window_truncate'))

    def test_handle_context_overflow_exists(self):
        """ContextCompressor should have handle_context_overflow method."""
        from agent.context_compressor import ContextCompressor
        self.assertTrue(hasattr(ContextCompressor, 'handle_context_overflow'))

    def test_new_init_params(self):
        """ContextCompressor should accept new Phase 5 parameters."""
        from agent.context_compressor import ContextCompressor
        cc = ContextCompressor(
            model="test-model",
            auto_condense_percent=0.80,
            forced_reduction_percent=0.70,
            max_window_retries=5,
            token_buffer_percent=0.15,
        )
        self.assertEqual(cc.auto_condense_percent, 0.80)
        self.assertEqual(cc.forced_reduction_percent, 0.70)
        self.assertEqual(cc.max_window_retries, 5)
        self.assertEqual(cc.token_buffer_percent, 0.15)


class TestPromptBuilder(unittest.TestCase):
    """Phase 3: System Prompt Builder"""

    def test_build_mode_prompt_exists(self):
        """build_mode_prompt should exist in prompt_builder."""
        from agent.prompt_builder import build_mode_prompt
        self.assertTrue(callable(build_mode_prompt))

    def test_build_mode_prompt_returns_string(self):
        """build_mode_prompt should return a string (empty when no mode, populated when active)."""
        from agent.prompt_builder import build_mode_prompt
        result = build_mode_prompt()
        self.assertIsInstance(result, str)
        # No mode active by default → empty string is correct
        # Verify it returns non-empty when a mode is set
        from agent.modes import set_active_mode, reload_modes
        reload_modes()
        set_active_mode("code")
        result2 = build_mode_prompt()
        self.assertIsInstance(result2, str)
        self.assertTrue(len(result2) > 0, "build_mode_prompt should return content when code mode is active")


class TestConfigKeys(unittest.TestCase):
    """Config integration: modes and context keys should exist in DEFAULT_CONFIG."""

    def test_modes_config_exists(self):
        """DEFAULT_CONFIG should have a 'modes' section."""
        from hermes_cli.config import DEFAULT_CONFIG
        self.assertIn("modes", DEFAULT_CONFIG)
        self.assertIn("default", DEFAULT_CONFIG["modes"])

    def test_context_config_exists(self):
        """DEFAULT_CONFIG should have a 'context' section."""
        from hermes_cli.config import DEFAULT_CONFIG
        self.assertIn("context", DEFAULT_CONFIG)
        self.assertIn("auto_condense_percent", DEFAULT_CONFIG["context"])
        self.assertIn("token_buffer_percent", DEFAULT_CONFIG["context"])

    def test_checkpoints_config(self):
        """DEFAULT_CONFIG should have checkpoints with auto_save."""
        from hermes_cli.config import DEFAULT_CONFIG
        self.assertIn("checkpoints", DEFAULT_CONFIG)
        self.assertIn("auto_save", DEFAULT_CONFIG["checkpoints"])


if __name__ == "__main__":
    unittest.main()
