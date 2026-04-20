"""Tests for agent.orchestrator — OrchestratorEngine planning and execution."""

import pytest
from unittest.mock import patch, MagicMock, PropertyMock

from agent.orchestrator import OrchestratorEngine, SubtaskPlan
from agent.task_hierarchy import TaskHierarchyManager


class TestSubtaskPlan:
    def test_defaults(self):
        p = SubtaskPlan(description="Do thing")
        assert p.description == "Do thing"
        assert p.suggested_mode == "general"
        assert p.dependencies == []
        assert p.priority == 3
        assert p.task_id is None


class TestOrchestratorEngineNoAgent:
    """Methods that gracefully handle missing parent_agent."""

    def setup_method(self):
        self.engine = OrchestratorEngine(parent_agent=None)

    def test_break_down_task_no_agent(self):
        result = self.engine.break_down_task("Build a thing")
        assert result == []

    def test_execute_plan_empty(self):
        result = self.engine.execute_plan([])
        assert result["results_by_task_id"] == {}


class TestOrchestratorEngineWithAgent:
    """Methods with a mocked parent_agent."""

    def setup_method(self):
        self.mock_agent = MagicMock()
        self.mock_agent._orchestrator = None
        self.mock_agent._task_hierarchy = None
        self.engine = OrchestratorEngine(parent_agent=self.mock_agent)

    def test_break_down_task_calls_llm(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = (
            '[{"description": "Step 1", "suggested_mode": "code"}, '
            '{"description": "Step 2", "suggested_mode": "code"}]'
        )
        mock_client.chat.completions.create.return_value = mock_response

        with patch.object(self.engine, "_build_planning_client", return_value=mock_client):
            plans = self.engine.break_down_task("Build a thing")

        assert len(plans) == 2
        assert plans[0].description == "Step 1"

    def test_break_down_task_strips_code_fences(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = (
            '```json\n[{"description": "Step 1"}]\n```'
        )
        mock_client.chat.completions.create.return_value = mock_response

        with patch.object(self.engine, "_build_planning_client", return_value=mock_client):
            plans = self.engine.break_down_task("Task")

        assert len(plans) == 1

    def test_break_down_task_llm_failure(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("API down")

        with patch.object(self.engine, "_build_planning_client", return_value=mock_client):
            plans = self.engine.break_down_task("Task")

        assert plans == []

    def test_execute_subtask_delegates(self):
        plan = SubtaskPlan(description="Do thing", suggested_mode="code")
        with patch("tools.delegate_tool.delegate_task") as mock_delegate:
            mock_delegate.return_value = '{"results": [{"status": "completed", "summary": "done"}]}'
            result = self.engine.execute_subtask(plan, parent_task_id=None)
            assert "done" in result
            mock_delegate.assert_called_once()

    def test_execute_subtask_creates_hierarchy(self):
        plan = SubtaskPlan(description="Do thing")
        with patch("tools.delegate_tool.delegate_task") as mock_delegate:
            mock_delegate.return_value = '{"results": [{"status": "completed", "summary": "done"}]}'
            self.engine.execute_subtask(plan, parent_task_id=None)
            # Should have created a task in the hierarchy
            task = self.engine.get_task(plan.task_id)
            assert task is not None
            assert task.status == "completed"

    def test_execute_plan_multiple(self):
        p1 = SubtaskPlan(description="Step 1", suggested_mode="code")
        p2 = SubtaskPlan(description="Step 2", suggested_mode="code")
        with patch("tools.delegate_tool.delegate_task") as mock_delegate:
            mock_delegate.return_value = '{"results": [{"status": "completed", "summary": "done"}]}'
            result = self.engine.execute_plan([p1, p2], root_task_id=None)
            assert len(result["executed"]) == 2
            assert all(result["executed"])

    def test_monitor_subtasks(self):
        root = self.engine._hierarchy.create_task("Root")
        c1 = self.engine._hierarchy.create_task("Child 1", parent_id=root.task_id)
        self.engine._hierarchy.start_task(c1.task_id)

        status = self.engine.monitor_subtasks([c1.task_id, "nonexistent"])
        assert status[c1.task_id] == "running"
        assert status["nonexistent"] == "not_found"
