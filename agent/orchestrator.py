#!/usr/bin/env python3
"""
Orchestrator Engine -- AI-powered task decomposition and subagent delegation.

The Orchestrator breaks a high-level goal into a plan of subtasks (each with
a suggested mode, dependencies, and priority), then executes them via the
existing delegate_task mechanism.

This module is completely standalone: it does NOT import or depend on the
Mode System (agent/modes.py).  It uses delegate_task directly.

Key concepts:
  - SubtaskPlan: a named subtask with suggested mode, dependencies, priority
  - OrchestratorEngine: break_down_task() -> execute_subtask() -> aggregate_results()
  - All delegation goes through delegate_task, so the existing subagent
    architecture (threading, heartbeats, credential inheritance) is reused.
"""

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from agent.task_hierarchy import TaskHierarchyManager, TaskNode

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SubtaskPlan
# ---------------------------------------------------------------------------

@dataclass
class SubtaskPlan:
    """
    A single step in an orchestrator plan.

    Attributes:
        description: What this subtask does.
        suggested_mode: Recommended agent mode (e.g. "research", "coder").
        dependencies: List of other SubtaskPlan descriptions this waits on.
        priority: 1 (highest) to 5 (lowest).
        task_id: Set by OrchestratorEngine once the task is created.
    """
    description: str
    suggested_mode: str = "general"
    dependencies: List[str] = field(default_factory=list)
    priority: int = 3
    task_id: Optional[str] = None


# ---------------------------------------------------------------------------
# OrchestratorEngine
# ---------------------------------------------------------------------------

class OrchestratorEngine:
    """
    Plans and executes complex multi-step tasks by decomposing them into
    subtasks and delegating each to a subagent.

    The engine:
      1. Uses an LLM to break_down_task() a goal into ordered SubtaskPlans.
      2. Executes subtasks in dependency order (subtasks with no dependencies
         run first; dependent subtasks wait for their prerequisites).
      3. Tracks status in TaskHierarchyManager.
      4. Aggregates results via aggregate_results().

    Thread-safety: The engine itself is stateless and re-entrant; each
    run_conversation() call gets its own task hierarchy.  The
    TaskHierarchyManager methods are all thread-safe.
    """

    # Prompt fragment used to ask the LLM to produce a plan.
    _PLANNING_PROMPT = """
You are an orchestrator planning assistant. Break down the following task
into clear, independent subtasks that can be executed in parallel where
possible.

Return a JSON array of subtask objects with these fields:
  - description: A clear, self-contained description of what this subtask does.
  - suggested_mode: One of "research", "coder", "general" (default: "general").
  - dependencies: List of descriptions this subtask depends on (empty if none).
  - priority: 1 (highest) to 5 (lowest). Default: 3.

Important constraints:
- Each subtask should be independently meaningful (not just "do X then do Y").
- Subtasks that can run concurrently should have no dependencies on each other.
- A subtask that must run after another should list that other in dependencies.
- Keep subtasks focused: one clear goal per subtask.
- Do NOT include orchestrator, delegate_task, clarify, or memory tools in any subtask.

TASK:
{task_description}

Return ONLY valid JSON (no markdown, no explanation), an array like:
[{{"description": "...", "suggested_mode": "...", "dependencies": [], "priority": 3}}, ...]
""".strip()

    def __init__(self, parent_agent=None):
        """
        Initialize the orchestrator.

        Args:
            parent_agent: The AIAgent instance running the orchestrator.
                          Used for delegate_task calls and credential access.
        """
        self.parent_agent = parent_agent
        self._hierarchy = TaskHierarchyManager()

    # ------------------------------------------------------------------
    # Planning
    # ------------------------------------------------------------------

    def break_down_task(self, description: str) -> List[SubtaskPlan]:
        """
        Ask the LLM to decompose *description* into an ordered list of SubtaskPlans.

        Returns a list of SubtaskPlan objects.  The caller should present
        the plan to the user or agent for confirmation before executing.

        The planning call itself is silent (no tool traces, no messages
        added to the parent conversation).

        Returns [] if planning fails or returns unparseable output.
        """
        if not self.parent_agent:
            logger.warning("OrchestratorEngine has no parent_agent; cannot plan.")
            return []

        planning_prompt = self._PLANNING_PROMPT.format(
            task_description=description,
        )

        try:
            # Use the parent's client directly for a silent planning call.
            # We bypass run_conversation to avoid polluting the session history.
            client = self._build_planning_client()
            messages = [
                {"role": "user", "content": planning_prompt},
            ]
            response = client.chat.completions.create(
                model=self.parent_agent.model,
                messages=messages,
                temperature=0.3,
                max_tokens=2000,
            )
            raw = response.choices[0].message.content or ""
            # Strip markdown code fences if present
            raw = raw.strip()
            if raw.startswith("```"):
                lines = raw.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                raw = "\n".join(lines).strip()

            parsed = json.loads(raw)
            if not isinstance(parsed, list):
                logger.warning("Planning response was not a JSON array: %s", raw[:200])
                return []

            plans = []
            for item in parsed:
                if not isinstance(item, dict):
                    continue
                plans.append(SubtaskPlan(
                    description=str(item.get("description", "")),
                    suggested_mode=str(item.get("suggested_mode", "general")),
                    dependencies=list(item.get("dependencies") or []),
                    priority=int(item.get("priority", 3)),
                ))
            return plans

        except Exception as exc:
            logger.exception("break_down_task failed: %s", exc)
            return []

    def _build_planning_client(self):
        """Build a minimal OpenAI-compatible client for silent planning calls."""
        from openai import OpenAI

        client_kwargs: Dict[str, Any] = {
            "api_key": getattr(self.parent_agent, "api_key", None),
            "base_url": getattr(self.parent_agent, "base_url", None),
        }
        # Remove None values so the SDK can apply its own defaults
        client_kwargs = {k: v for k, v in client_kwargs.items() if v is not None}
        return OpenAI(**client_kwargs)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute_subtask(
        self,
        subtask_plan: SubtaskPlan,
        parent_task_id: Optional[str] = None,
    ) -> str:
        """
        Execute a single SubtaskPlan via delegate_task.

        Creates a task node under *parent_task_id* (or as a root if None),
        marks it running, delegates to a subagent, then marks it completed
        or failed with the result.

        Returns the subagent's summary result string.
        """
        # Create the task node
        task_node = self._hierarchy.create_task(
            description=subtask_plan.description,
            mode=subtask_plan.suggested_mode,
            parent_id=parent_task_id,
        )
        subtask_plan.task_id = task_node.task_id
        self._hierarchy.start_task(task_node.task_id)

        # Build context: pass mode to subagent
        context_parts = [
            f"Mode: {subtask_plan.suggested_mode}",
            f"Task: {subtask_plan.description}",
        ]
        context = "\n".join(context_parts)

        try:
            # Call delegate_task
            if self.parent_agent is None:
                raise RuntimeError("OrchestratorEngine has no parent_agent")

            from tools.delegate_tool import delegate_task
            result_json = delegate_task(
                goal=subtask_plan.description,
                context=context,
                toolsets=[subtask_plan.suggested_mode],
                parent_agent=self.parent_agent,
            )
            result = json.loads(result_json)

            if "error" in result:
                error_msg = result.get("error", "Unknown delegate error")
                self._hierarchy.fail_task(task_node.task_id, error_msg)
                return f"FAILED: {error_msg}"

            # Extract the summary from the first (and typically only) result
            results_list = result.get("results", [])
            if results_list:
                entry = results_list[0]
                status = entry.get("status", "unknown")
                summary = entry.get("summary") or ""
                if status == "completed":
                    self._hierarchy.complete_task(task_node.task_id, summary)
                    return summary
                else:
                    error_text = entry.get("error") or f"status={status}"
                    self._hierarchy.fail_task(task_node.task_id, error_text)
                    return f"FAILED: {error_text}"

            self._hierarchy.fail_task(task_node.task_id, "No results returned")
            return "FAILED: No results returned"

        except Exception as exc:
            logger.exception("execute_subtask failed for %s", subtask_plan.description)
            self._hierarchy.fail_task(task_node.task_id, str(exc))
            return f"FAILED: {exc}"

    def execute_plan(
        self,
        plans: List[SubtaskPlan],
        root_task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Execute a list of SubtaskPlans in dependency order.

        - Subtasks with no dependencies run first (potentially in parallel).
        - A subtask with dependencies waits for all its dependencies to complete
          before starting.
        - *root_task_id* is the orchestrator's root task (may be None for
          standalone execution).

        Returns a dict with keys: root_task_id, results_by_task_id, aggregate.
        """
        if not plans:
            return {"root_task_id": None, "results_by_task_id": {}, "aggregate": ""}

        # Build a map: description -> plan index (for dependency resolution)
        desc_to_idx: Dict[str, int] = {}
        for i, plan in enumerate(plans):
            desc_to_idx[plan.description] = i

        # Track which plans have been executed
        executed: List[bool] = [False] * len(plans)
        results: List[Optional[str]] = [None] * len(plans)

        def can_run(plan: SubtaskPlan) -> bool:
            if not plan.dependencies:
                return True
            for dep_desc in plan.dependencies:
                dep_idx = desc_to_idx.get(dep_desc)
                if dep_idx is None:
                    # Unknown dependency -- assume it passed (defensive)
                    continue
                if not executed[dep_idx]:
                    return False
            return True

        max_iterations = 100  # safety valve
        iteration = 0
        pending = list(range(len(plans)))

        while pending and iteration < max_iterations:
            iteration += 1
            to_run = [i for i in pending if can_run(plans[i])]
            if not to_run:
                # Deadlock: no runnable tasks but some haven't run
                logger.warning(
                    "Orchestrator deadlock: unexecutable tasks remain: %s",
                    [plans[i].description for i in pending],
                )
                break

            for idx in to_run:
                plan = plans[idx]
                result = self.execute_subtask(plan, parent_task_id=root_task_id)
                results[idx] = result
                executed[idx] = True
                pending.remove(idx)

        # Build results dict keyed by task_id
        results_by_task_id: Dict[str, str] = {}
        for i, plan in enumerate(plans):
            if plan.task_id:
                results_by_task_id[plan.task_id] = results[i] or ""

        return {
            "results_by_task_id": results_by_task_id,
            "executed": executed,
        }

    # ------------------------------------------------------------------
    # Monitoring / Aggregation
    # ------------------------------------------------------------------

    def monitor_subtasks(self, task_ids: List[str]) -> Dict[str, str]:
        """
        Return current status for the given task IDs.

        Returns {task_id: status_string}.
        """
        statuses = {}
        for tid in task_ids:
            node = self._hierarchy.get_task(tid)
            if node is None:
                statuses[tid] = "not_found"
            else:
                statuses[tid] = node.status
        return statuses

    def aggregate_results(self, root_task_id: str) -> str:
        """
        Return a formatted string summarizing all results in a task tree.

        Calls TaskHierarchyManager.aggregate_results internally.
        """
        return self._hierarchy.aggregate_results(root_task_id)

    def get_task(self, task_id: str) -> Optional[TaskNode]:
        """Return a task node by ID, or None."""
        return self._hierarchy.get_task(task_id)

    def get_subtree(self, root_task_id: str) -> List[TaskNode]:
        """Return all nodes in the subtree."""
        return self._hierarchy.get_subtree(root_task_id)

    def task_summary(self, root_task_id: str) -> Dict[str, Any]:
        """Return a summary dict for the root task."""
        return self._hierarchy.task_summary(root_task_id)
