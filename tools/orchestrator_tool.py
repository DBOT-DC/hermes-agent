#!/usr/bin/env python3
"""
Orchestrator Tool -- AI-powered task planning and multi-subagent orchestration.

Provides five actions:
  - plan:     Break down a goal into subtask plans using an LLM
  - execute:  Execute a planned subtask via subagent delegation
  - status:   Check the status of active subtasks
  - results:  Retrieve and aggregate results from completed subtasks
  - cancel:   Mark a task/subtask as cancelled (sets status to failed)

This tool is ALWAYS AVAILABLE (check_delegate_requirements always returns True).
It delegates actual subtask execution to the existing delegate_task mechanism,
so the full subagent architecture (threading, heartbeats, credential inheritance)
is reused.

The orchestrator operates in two phases:
  1. PLAN:  Agent calls plan() to get a structured SubtaskPlan list.
  2. EXECUTE: Agent calls execute() for each subtask (subtasks with no
     dependencies can be run in parallel via multiple execute() calls).

The orchestrator tracks all tasks in a TaskHierarchyManager instance
stored on the parent agent, so the agent's conversation history shows
only the plan/subtask calls, never the internal delegation details.
"""

import json
import logging
import threading
import time
from typing import Any, Dict, List, Optional

from tools.registry import registry, tool_error

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Availability check (always available)
# ---------------------------------------------------------------------------

def check_orchestrator_requirements() -> bool:
    """Orchestrator has no external requirements -- always available."""
    return True


# ---------------------------------------------------------------------------
# Orchestrator singleton on parent_agent
# ---------------------------------------------------------------------------

def _get_orchestrator(parent_agent) -> "OrchestratorEngine":
    """Get or create the OrchestratorEngine on the parent agent."""
    if parent_agent is None:
        raise RuntimeError("orchestrator_tool requires a parent agent context")

    if not hasattr(parent_agent, "_orchestrator"):
        from agent.orchestrator import OrchestratorEngine
        parent_agent._orchestrator = OrchestratorEngine(parent_agent=parent_agent)

    return parent_agent._orchestrator


def _get_hierarchy(parent_agent):
    """Get or create the TaskHierarchyManager on the parent agent."""
    if parent_agent is None:
        raise RuntimeError("orchestrator_tool requires a parent agent context")

    if not hasattr(parent_agent, "_task_hierarchy"):
        from agent.task_hierarchy import TaskHierarchyManager
        parent_agent._task_hierarchy = TaskHierarchyManager()

    return parent_agent._task_hierarchy


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------

def _plan_action(args: dict, parent_agent=None) -> str:
    """Break down a goal into a list of subtask plans (JSON)."""
    if parent_agent is None:
        return tool_error("orchestrator plan requires a parent agent context.")

    goal = args.get("goal", "").strip()
    if not goal:
        return tool_error("The 'goal' field is required for plan.")

    orchestrator = _get_orchestrator(parent_agent)
    plans = orchestrator.break_down_task(goal)

    if not plans:
        return tool_error("Planning failed or returned no subtasks. Try a more specific goal.")

    # Serialize plans to a JSON-serializable format
    plans_data = [
        {
            "description": p.description,
            "suggested_mode": p.suggested_mode,
            "dependencies": p.dependencies,
            "priority": p.priority,
        }
        for p in plans
    ]

    # Create a root task node for this orchestrator run
    hierarchy = _get_hierarchy(parent_agent)
    root_node = hierarchy.create_task(description=goal, mode="orchestrator")

    # Store the plan in the root node result for later reference
    hierarchy.complete_task(
        root_node.task_id,
        json.dumps({"plans": plans_data}, ensure_ascii=False),
    )

    return json.dumps({
        "root_task_id": root_node.task_id,
        "plans": plans_data,
        "message": (
            f"Plan created with {len(plans)} subtask(s). "
            "Use execute() for each subtask, starting with those that have no dependencies. "
            "You can run independent subtasks in parallel."
        ),
    }, ensure_ascii=False)


def _execute_action(args: dict, parent_agent=None) -> str:
    """Execute a single subtask plan via delegate_task."""
    if parent_agent is None:
        return tool_error("orchestrator execute requires a parent agent context.")

    description = args.get("description", "").strip()
    suggested_mode = args.get("suggested_mode", "general").strip()
    dependencies = args.get("dependencies", [])
    parent_task_id = args.get("parent_task_id")

    if not description:
        return tool_error("The 'description' field is required for execute.")

    orchestrator = _get_orchestrator(parent_agent)

    # Build a SubtaskPlan
    from agent.orchestrator import SubtaskPlan
    plan = SubtaskPlan(
        description=description,
        suggested_mode=suggested_mode or "general",
        dependencies=dependencies if isinstance(dependencies, list) else [],
    )

    result = orchestrator.execute_subtask(plan, parent_task_id=parent_task_id)

    return json.dumps({
        "task_id": plan.task_id,
        "result": result,
        "status": "completed" if not result.startswith("FAILED:") else "failed",
    }, ensure_ascii=False)


def _status_action(args: dict, parent_agent=None) -> str:
    """Return status for tasks in a tree (or a specific task)."""
    if parent_agent is None:
        return tool_error("orchestrator status requires a parent agent context.")

    task_id = args.get("task_id")
    root_task_id = args.get("root_task_id")

    hierarchy = _get_hierarchy(parent_agent)

    if task_id:
        node = hierarchy.get_task(task_id)
        if node is None:
            return tool_error(f"Task not found: {task_id}")
        return json.dumps({
            "task_id": node.task_id,
            "status": node.status,
            "mode": node.mode,
            "description": node.description,
        }, ensure_ascii=False)

    if root_task_id:
        statuses = hierarchy.get_subtask_statuses(root_task_id)
        summary = hierarchy.task_summary(root_task_id)
        return json.dumps({
            "root_task_id": root_task_id,
            "statuses": statuses,
            "summary": summary,
        }, ensure_ascii=False)

    return tool_error("Provide either 'task_id' or 'root_task_id'.")


def _results_action(args: dict, parent_agent=None) -> str:
    """Retrieve and aggregate results from a task tree."""
    if parent_agent is None:
        return tool_error("orchestrator results requires a parent agent context.")

    root_task_id = args.get("root_task_id")
    if not root_task_id:
        return tool_error("The 'root_task_id' field is required for results.")

    hierarchy = _get_hierarchy(parent_agent)
    root = hierarchy.get_root_task(root_task_id)
    if root is None:
        return tool_error(f"Root task not found: {root_task_id}")

    aggregate = hierarchy.aggregate_results(root_task_id)
    summary = hierarchy.task_summary(root_task_id)

    return json.dumps({
        "root_task_id": root_task_id,
        "aggregate": aggregate,
        "summary": summary,
    }, ensure_ascii=False)


def _cancel_action(args: dict, parent_agent=None) -> str:
    """Cancel a task by marking it failed with a cancellation message."""
    if parent_agent is None:
        return tool_error("orchestrator cancel requires a parent agent context.")

    task_id = args.get("task_id")
    if not task_id:
        return tool_error("The 'task_id' field is required for cancel.")

    hierarchy = _get_hierarchy(parent_agent)
    node = hierarchy.get_task(task_id)
    if node is None:
        return tool_error(f"Task not found: {task_id}")

    hierarchy.fail_task(task_id, "Cancelled by orchestrator")

    return json.dumps({
        "task_id": task_id,
        "status": "cancelled",
        "message": f"Task {task_id} has been cancelled.",
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tool handler dispatcher
# ---------------------------------------------------------------------------

def orchestrate(args: dict, parent_agent=None) -> str:
    """
    Orchestrator tool entry point.

    Actions:
      - plan:     Break down a goal into subtask plans
      - execute:  Execute a single subtask plan via delegate_task
      - status:   Check status of a task or task tree
      - results:  Aggregate and return results from a task tree
      - cancel:   Cancel a task

    The orchestrator is always available. It requires a parent_agent to
    access delegate_task and store task hierarchy state.
    """
    if parent_agent is None:
        return tool_error("orchestrator requires a parent agent context.")

    action = args.get("action", "plan").strip().lower()

    if action == "plan":
        return _plan_action(args, parent_agent)
    elif action == "execute":
        return _execute_action(args, parent_agent)
    elif action == "status":
        return _status_action(args, parent_agent)
    elif action == "results":
        return _results_action(args, parent_agent)
    elif action == "cancel":
        return _cancel_action(args, parent_agent)
    else:
        return tool_error(
            f"Unknown action '{action}'. "
            "Valid actions: plan, execute, status, results, cancel."
        )


# ---------------------------------------------------------------------------
# OpenAI Function-Calling Schema
# ---------------------------------------------------------------------------

ORCHESTRATOR_SCHEMA = {
    "name": "orchestrate",
    "description": (
        "AI-powered task orchestrator: break down complex goals into subtask plans,\n"
        "then execute each subtask via specialized subagents.\n\n"
        "TWO-PHASE USAGE:\n"
        "1. PLAN: Call with action='plan' and your high-level goal.\n"
        "   Returns a list of SubtaskPlans (description, suggested_mode, dependencies, priority).\n"
        "2. EXECUTE: Call with action='execute' for each subtask.\n"
        "   Subtasks with no dependencies can run in parallel.\n"
        "   Results are tracked in the task hierarchy and retrieved via results.\n\n"
        "FIVE ACTIONS:\n"
        "- plan:    Break down a goal into an ordered subtask plan (uses LLM).\n"
        "- execute: Run a single subtask via a subagent (delegate_task).\n"
        "- status:  Check current status of a task or full task tree.\n"
        "- results: Retrieve and aggregate all results from a completed task tree.\n"
        "- cancel:  Cancel a running task (marks it failed).\n\n"
        "WHEN TO USE orchestrate:\n"
        "- Complex multi-step tasks that benefit from decomposition\n"
        "- Tasks where different subtasks suit different modes (research vs. coding)\n"
        "- Parallel independent workstreams (run multiple execute calls concurrently)\n\n"
        "WHEN NOT TO USE (use these instead):\n"
        "- Single independent subtask -> delegate_task directly\n"
        "- Mechanical linear steps -> execute_code\n"
        "- User-facing interactions -> clarify tool\n\n"
        "IMPORTANT:\n"
        "- Always start with a 'plan' call to get the structured subtask list.\n"
        "- Save the root_task_id from the plan response for status/results calls.\n"
        "- Independent subtasks (no dependencies) can be executed in parallel.\n"
        "- The orchestrator tracks all tasks in the parent agent's hierarchy.\n"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["plan", "execute", "status", "results", "cancel"],
                "description": "The orchestrator action to perform.",
            },
            "goal": {
                "type": "string",
                "description": (
                    "The high-level goal to break down into subtasks. "
                    "Required for action='plan'. Be specific and include "
                    "relevant context (file paths, constraints, etc.)."
                ),
            },
            "description": {
                "type": "string",
                "description": (
                    "Description of the subtask to execute. "
                    "Required for action='execute'. This should match one of "
                    "the descriptions returned by the plan action."
                ),
            },
            "suggested_mode": {
                "type": "string",
                "description": (
                    "The suggested mode for this subtask. "
                    "Required for action='execute'. "
                    "Examples: 'research', 'coder', 'general'."
                ),
            },
            "dependencies": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "List of subtask descriptions this subtask depends on. "
                    "Required for action='execute' when the plan specifies dependencies. "
                    "The execute call will wait until all dependent subtasks complete."
                ),
            },
            "parent_task_id": {
                "type": "string",
                "description": (
                    "The parent task ID to attach this subtask to. "
                    "Use the root_task_id from the plan response as the parent "
                    "for top-level subtasks, or a subtask's task_id for nested tasks."
                ),
            },
            "task_id": {
                "type": "string",
                "description": (
                    "A task ID. Required for action='status' (single task) "
                    "and action='cancel'. Also used by 'status' with 'root_task_id' "
                    "to identify the specific task to query."
                ),
            },
            "root_task_id": {
                "type": "string",
                "description": (
                    "The root task ID of an orchestrator run. "
                    "Returned by the plan action. "
                    "Required for action='status' (tree view) and action='results'. "
                    "Use to retrieve the full aggregated output."
                ),
            },
        },
        "required": [],
    },
}


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

registry.register(
    name="orchestrate",
    toolset="agent",
    schema=ORCHESTRATOR_SCHEMA,
    handler=lambda args, **kw: orchestrate(
        action=args.get("action"),
        goal=args.get("goal"),
        description=args.get("description"),
        suggested_mode=args.get("suggested_mode"),
        dependencies=args.get("dependencies"),
        parent_task_id=args.get("parent_task_id"),
        task_id=args.get("task_id"),
        root_task_id=args.get("root_task_id"),
        parent_agent=kw.get("parent_agent"),
    ),
    check_fn=check_orchestrator_requirements,
    emoji="🎯",
)
