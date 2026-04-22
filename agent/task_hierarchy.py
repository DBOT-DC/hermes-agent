#!/usr/bin/env python3
"""
Task Hierarchy Manager for Hermes Agent.

Tracks parent/child/root task relationships for delegate_task,
enabling orchestrator mode to coordinate subtask execution.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class TaskNode:
    """A single task in the hierarchy."""

    task_id: str
    description: str
    status: str = "pending"  # pending|in_progress|completed|failed|cancelled
    parent_task_id: Optional[str] = None
    children: List[str] = field(default_factory=list)
    result: Optional[str] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)


class TaskHierarchyManager:
    """Manages a tree of tasks with parent-child relationships."""

    def __init__(self):
        self._tasks: Dict[str, TaskNode] = {}
        self._root_task_id: Optional[str] = None

    def create_task(self, description: str, parent_task_id: Optional[str] = None) -> str:
        """Create a new task and return its ID."""
        task_id = str(uuid.uuid4())[:8]
        node = TaskNode(
            task_id=task_id,
            description=description,
            parent_task_id=parent_task_id,
        )
        self._tasks[task_id] = node

        if parent_task_id:
            parent = self._tasks.get(parent_task_id)
            if parent:
                parent.children.append(task_id)
        elif self._root_task_id is None:
            self._root_task_id = task_id

        return task_id

    def get_task(self, task_id: str) -> Optional[TaskNode]:
        """Get a task by ID."""
        return self._tasks.get(task_id)

    def update_status(
        self,
        task_id: str,
        status: str,
        result: Optional[str] = None,
        error: Optional[str] = None,
    ):
        """Update a task's status."""
        node = self._tasks.get(task_id)
        if node:
            node.status = status
            if result is not None:
                node.result = result
            if error is not None:
                node.error = error

    def add_child(self, parent_id: str, child_id: str):
        """Add a child task to a parent."""
        parent = self._tasks.get(parent_id)
        if parent and child_id not in parent.children:
            parent.children.append(child_id)
        child = self._tasks.get(child_id)
        if child:
            child.parent_task_id = parent_id

    def get_children(self, task_id: str) -> List[TaskNode]:
        """Get all direct children of a task."""
        node = self._tasks.get(task_id)
        if not node:
            return []
        return [self._tasks[cid] for cid in node.children if cid in self._tasks]

    def get_root_task(self) -> Optional[TaskNode]:
        """Get the root task."""
        if self._root_task_id:
            return self._tasks.get(self._root_task_id)
        return None

    def get_subtree(self, task_id: str) -> List[TaskNode]:
        """Get all descendants of a task (BFS)."""
        result = []
        queue = [task_id]
        visited = set()
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            node = self._tasks.get(current)
            if node:
                result.append(node)
                queue.extend(node.children)
        return result

    def get_subtask_statuses(self, task_id: str) -> Dict[str, str]:
        """Get status of all subtasks under a task."""
        subtree = self.get_subtree(task_id)
        return {n.task_id: n.status for n in subtree}

    def aggregate_result(self, task_id: str) -> Dict[str, Any]:
        """Aggregate results from all subtasks."""
        subtree = self.get_subtree(task_id)
        if not subtree:
            return {"status": "unknown", "completed": 0, "total": 0, "results": [], "errors": []}

        completed = [n for n in subtree if n.status == "completed"]
        failed = [n for n in subtree if n.status == "failed"]
        total = len(subtree)

        # Determine overall status
        if all(n.status == "completed" for n in subtree):
            overall = "completed"
        elif any(n.status == "failed" for n in subtree):
            overall = "failed"
        elif any(n.status == "in_progress" for n in subtree):
            overall = "in_progress"
        else:
            overall = "pending"

        return {
            "status": overall,
            "completed": len(completed),
            "total": total,
            "results": [n.result for n in completed if n.result],
            "errors": [n.error for n in failed if n.error],
        }

    def clear(self):
        """Clear all tasks."""
        self._tasks.clear()
        self._root_task_id = None


# Module-level singleton
_manager: Optional[TaskHierarchyManager] = None


def get_manager() -> TaskHierarchyManager:
    """Get the global task hierarchy manager."""
    global _manager
    if _manager is None:
        _manager = TaskHierarchyManager()
    return _manager


def reset_manager():
    """Reset the global task hierarchy manager."""
    global _manager
    _manager = TaskHierarchyManager()
