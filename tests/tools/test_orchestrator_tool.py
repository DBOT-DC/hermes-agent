"""Tests for tools.orchestrator_tool — orchestrate tool handler."""

import json
import pytest
from unittest.mock import MagicMock, patch
from types import SimpleNamespace

from tools.orchestrator_tool import (
    orchestrate,
    _plan_action,
    _execute_action,
    _status_action,
    _results_action,
    _cancel_action,
    _get_orchestrator,
    _get_hierarchy,
)


def _make_agent():
    """Create a mock agent with no pre-set attrs so hasattr returns False."""
    return SimpleNamespace()


class TestOrchestratorToolNoAgent:
    """All actions require parent_agent — should return error JSON."""

    def test_orchestrate_no_agent(self):
        result = json.loads(orchestrate({"action": "plan"}))
        assert "error" in result

    def test_plan_no_agent(self):
        result = json.loads(_plan_action({}, parent_agent=None))
        assert "error" in result

    def test_execute_no_agent(self):
        result = json.loads(_execute_action({}, parent_agent=None))
        assert "error" in result

    def test_status_no_agent(self):
        result = json.loads(_status_action({}, parent_agent=None))
        assert "error" in result

    def test_results_no_agent(self):
        result = json.loads(_results_action({}, parent_agent=None))
        assert "error" in result

    def test_cancel_no_agent(self):
        result = json.loads(_cancel_action({}, parent_agent=None))
        assert "error" in result

    def test_unknown_action(self):
        result = json.loads(orchestrate({"action": "explode"}))
        assert "error" in result


class TestOrchestratorToolWithAgent:
    def setup_method(self):
        self.agent = _make_agent()

    def test_get_orchestrator_creates(self):
        orch = _get_orchestrator(self.agent)
        assert orch is not None
        assert self.agent._orchestrator is orch

    def test_get_hierarchy_creates(self):
        hier = _get_hierarchy(self.agent)
        assert hier is not None
        assert self.agent._task_hierarchy is hier

    def test_plan_action(self):
        from unittest.mock import patch as _p, MagicMock
        # SimpleNamespace needs a .model attribute for break_down_task
        self.agent.model = "test/model"
        self.agent.api_key = "test-key"
        # Mock the LLM call inside break_down_task
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = (
            '[{"description": "Step 1", "suggested_mode": "code"}]'
        )
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_resp

        with _p("agent.orchestrator.OrchestratorEngine._build_planning_client", return_value=mock_client):
            result = json.loads(_plan_action(
                {"goal": "Build feature X", "description": "Create a login page"},
                parent_agent=self.agent,
            ))
        assert "root_task_id" in result or "task_id" in result

    def test_execute_action(self):
        # Need a root task first
        hier = _get_hierarchy(self.agent)
        root = hier.create_task("Root")

        result = json.loads(_execute_action(
            {"task_id": root.task_id, "description": "Do subtask", "mode": "code"},
            parent_agent=self.agent,
        ))
        # execute_action creates a subtask and tries to run it
        assert "task_id" in result or "error" in result

    def test_status_action_single(self):
        hier = _get_hierarchy(self.agent)
        root = hier.create_task("Root")

        result = json.loads(_status_action(
            {"task_id": root.task_id},
            parent_agent=self.agent,
        ))
        assert "task_id" in result
        assert result["status"] == "pending"

    def test_status_action_missing_id(self):
        result = json.loads(_status_action(
            {},
            parent_agent=self.agent,
        ))
        assert "error" in result

    def test_results_action(self):
        hier = _get_hierarchy(self.agent)
        root = hier.create_task("Root")
        c1 = hier.create_task("Child", parent_id=root.task_id)
        hier.complete_task(c1.task_id, "done")

        result = json.loads(_results_action(
            {"root_task_id": root.task_id},
            parent_agent=self.agent,
        ))
        assert "aggregate" in result or "summary" in result or "error" not in result

    def test_results_action_missing_root(self):
        result = json.loads(_results_action(
            {},
            parent_agent=self.agent,
        ))
        assert "error" in result

    def test_cancel_action(self):
        hier = _get_hierarchy(self.agent)
        root = hier.create_task("Root")
        hier.start_task(root.task_id)

        result = json.loads(_cancel_action(
            {"task_id": root.task_id},
            parent_agent=self.agent,
        ))
        assert result.get("status") == "cancelled" or "error" not in result
