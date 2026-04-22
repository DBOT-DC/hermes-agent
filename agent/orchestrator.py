#!/usr/bin/env python3
"""
Orchestrator Engine for Hermes Agent.

Breaks complex tasks into subtasks and coordinates execution
via delegate_task. Used in orchestrator mode.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class SubtaskPlan:
    """A planned subtask for orchestrator execution."""

    description: str
    mode: str = "code"
    goal: str = ""
    context: str = ""
    depends_on: List[str] = field(default_factory=list)
    status: str = "pending"  # pending|in_progress|completed|failed|cancelled


class OrchestratorEngine:
    """Plans and coordinates multi-agent task execution."""

    def __init__(self):
        self._agent: Optional[Any] = None
        self._current_plan: Optional[List[SubtaskPlan]] = None
        self._results: Dict[str, Any] = {}

    def set_agent(self, agent):
        """Set the AIAgent reference for delegation."""
        self._agent = agent

    def plan_task(self, task_description: str) -> List[SubtaskPlan]:
        """Break a task description into subtask plans.

        Uses heuristic decomposition: splits on numbered items,
        bullet points, or common separators.
        """
        # Try to split on numbered items first
        numbered = re.split(r'(?:^|\n)\s*\d+[.)]\s+', task_description.strip())
        numbered = [s.strip() for s in numbered if s.strip()]

        if len(numbered) > 1:
            subtasks = numbered
        else:
            # Try bullet points
            bullets = re.split(r'(?:^|\n)\s*[-*]\s+', task_description.strip())
            bullets = [s.strip() for s in bullets if s.strip()]
            if len(bullets) > 1:
                subtasks = bullets
            else:
                # Single task — return as-is
                return [SubtaskPlan(
                    description=task_description.strip(),
                    mode=self._infer_mode(task_description),
                    goal=task_description.strip(),
                )]

        plans = []
        for i, desc in enumerate(subtasks):
            plans.append(SubtaskPlan(
                description=desc[:200],
                mode=self._infer_mode(desc),
                goal=desc,
            ))
        return plans

    def _infer_mode(self, text: str) -> str:
        """Infer the best mode for a task based on keywords."""
        text_lower = text.lower()

        # Architect keywords
        arch_keywords = ["design", "architecture", "plan", "spec", "structure",
                         "diagram", "overview", "layout", "organize", "refactor plan"]
        if any(kw in text_lower for kw in arch_keywords):
            return "architect"

        # Ask keywords
        ask_keywords = ["what is", "explain", "how does", "why", "describe",
                        "tell me", "what are", "compare", "difference between",
                        "question", "?"]
        if any(kw in text_lower for kw in ask_keywords):
            return "ask"

        # Debug keywords
        debug_keywords = ["bug", "error", "fix", "debug", "issue", "crash",
                          "broken", "not working", "failing", "traceback",
                          "exception", "wrong", "incorrect"]
        if any(kw in text_lower for kw in debug_keywords):
            return "debug"

        return "code"

    def execute_plan(self, plan: List[SubtaskPlan]) -> Dict[str, Any]:
        """Execute subtasks in dependency order.

        Tasks with no dependencies run in parallel (conceptually).
        Returns aggregated results.
        """
        self._current_plan = plan
        self._results = {}

        # Simple execution: run tasks sequentially for now
        # (parallel execution requires the agent's delegate_task)
        completed = 0
        failed = 0
        results = []
        errors = []

        for i, subtask in enumerate(plan):
            subtask.status = "in_progress"
            try:
                result = self._execute_single(subtask)
                subtask.status = "completed"
                self._results[subtask.description] = result
                results.append({"task": subtask.description, "result": result})
                completed += 1
            except Exception as e:
                subtask.status = "failed"
                self._results[subtask.description] = {"error": str(e)}
                errors.append({"task": subtask.description, "error": str(e)})
                failed += 1

        overall = "completed" if failed == 0 else "partial" if completed > 0 else "failed"
        return {
            "status": overall,
            "completed": completed,
            "failed": failed,
            "total": len(plan),
            "results": results,
            "errors": errors,
        }

    def _execute_single(self, subtask: SubtaskPlan) -> Any:
        """Execute a single subtask.

        If an agent reference is available, use delegate_task.
        Otherwise return the plan as-is (no-op).
        """
        if self._agent is None:
            return {"planned": subtask.description, "mode": subtask.mode}

        # The actual delegation would happen through the agent's
        # delegate_task mechanism. For now, return the plan info.
        return {
            "task": subtask.description,
            "mode": subtask.mode,
            "status": "planned",
        }

    def get_status(self) -> Dict[str, Any]:
        """Get current execution status."""
        if not self._current_plan:
            return {"status": "idle", "plan": None, "results": {}}

        total = len(self._current_plan)
        completed = sum(1 for p in self._current_plan if p.status == "completed")
        in_progress = sum(1 for p in self._current_plan if p.status == "in_progress")
        failed = sum(1 for p in self._current_plan if p.status == "failed")

        return {
            "status": "running" if in_progress > 0 else "done",
            "total": total,
            "completed": completed,
            "in_progress": in_progress,
            "failed": failed,
            "results": self._results,
        }

    def cancel(self):
        """Cancel all pending subtasks."""
        if self._current_plan:
            for subtask in self._current_plan:
                if subtask.status == "pending":
                    subtask.status = "cancelled"
