#!/usr/bin/env python3
"""
Task Hierarchy -- Tree of tasks with parent/child relationships.

Provides an in-memory task tree with thread-safe operations, used by the
Orchestrator Mode to track subtasks, their status, and aggregate results.

Each task node tracks:
  - task_id, root_task_id, parent_task_id, child_task_ids
  - task_number (order within parent)
  - mode (e.g. "research", "coder", "general")
  - status: pending / running / completed / failed
  - description, result
  - created_at, completed_at
"""

import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class TaskNode:
    """A single node in the task hierarchy tree."""
    task_id: str
    root_task_id: str
    parent_task_id: Optional[str]
    child_task_ids: List[str]
    task_number: int
    mode: str
    status: str  # pending | running | completed | failed
    description: str
    result: Optional[str]
    created_at: float
    completed_at: Optional[float]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "root_task_id": self.root_task_id,
            "parent_task_id": self.parent_task_id,
            "child_task_ids": list(self.child_task_ids),
            "task_number": self.task_number,
            "mode": self.mode,
            "status": self.status,
            "description": self.description,
            "result": self.result,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }


# ---------------------------------------------------------------------------
# TaskHierarchyManager
# ---------------------------------------------------------------------------

class TaskHierarchyManager:
    """
    Thread-safe in-memory task hierarchy.

    The hierarchy is a tree where each node knows its parent and children.
    The root is the top-level task submitted to the orchestrator; leaves
    are atomic subtasks executed by subagents.
    """

    def __init__(self):
        self._lock = threading.RLock()
        # task_id -> TaskNode
        self._nodes: Dict[str, TaskNode] = {}
        # root_task_id -> set of all descendant task_ids (excluding root)
        self._subtree_index: Dict[str, set] = {}

    # ------------------------------------------------------------------
    # Mutation API (all thread-safe)
    # ------------------------------------------------------------------

    def create_task(
        self,
        description: str,
        mode: str = "general",
        parent_id: Optional[str] = None,
    ) -> TaskNode:
        """
        Create a new task node.

        If *parent_id* is None, the task is a root task (no parent).
        Child task numbers auto-increment within the parent.

        Returns the new TaskNode.
        """
        with self._lock:
            now = time.time()
            task_id = str(uuid.uuid4())

            if parent_id is None:
                root_id = task_id
                task_number = 0
            else:
                parent = self._nodes.get(parent_id)
                if parent is None:
                    raise ValueError(f"Parent task not found: {parent_id}")
                root_id = parent.root_task_id
                # Count existing children to assign next task_number
                task_number = len(parent.child_task_ids)

            node = TaskNode(
                task_id=task_id,
                root_task_id=root_id,
                parent_task_id=parent_id,
                child_task_ids=[],
                task_number=task_number,
                mode=mode,
                status="pending",
                description=description,
                result=None,
                created_at=now,
                completed_at=None,
            )
            self._nodes[task_id] = node

            # Register as child of parent
            if parent_id is not None:
                self._nodes[parent_id].child_task_ids.append(task_id)

            # Index in subtree for fast lookups
            if root_id not in self._subtree_index:
                self._subtree_index[root_id] = set()
            self._subtree_index[root_id].add(task_id)

            return node

    def start_task(self, task_id: str) -> None:
        """Mark a task as running."""
        with self._lock:
            node = self._nodes.get(task_id)
            if node is None:
                raise ValueError(f"Task not found: {task_id}")
            node.status = "running"

    def complete_task(self, task_id: str, result: str) -> None:
        """Mark a task as completed with its result text."""
        with self._lock:
            node = self._nodes.get(task_id)
            if node is None:
                raise ValueError(f"Task not found: {task_id}")
            node.status = "completed"
            node.result = result
            node.completed_at = time.time()

    def fail_task(self, task_id: str, error: str) -> None:
        """Mark a task as failed with an error message."""
        with self._lock:
            node = self._nodes.get(task_id)
            if node is None:
                raise ValueError(f"Task not found: {task_id}")
            node.status = "failed"
            node.result = error
            node.completed_at = time.time()

    # ------------------------------------------------------------------
    # Query API (all thread-safe)
    # ------------------------------------------------------------------

    def get_task(self, task_id: str) -> Optional[TaskNode]:
        """Return the task node, or None if not found."""
        with self._lock:
            return self._nodes.get(task_id)

    def get_root_task(self, task_id: str) -> Optional[TaskNode]:
        """Return the root ancestor of a task (or the task itself if it is root)."""
        with self._lock:
            node = self._nodes.get(task_id)
            if node is None:
                return None
            return self._nodes.get(node.root_task_id)

    def get_children(self, task_id: str) -> List[TaskNode]:
        """Return direct children of a task, in task_number order."""
        with self._lock:
            node = self._nodes.get(task_id)
            if node is None:
                return []
            return sorted(
                [self._nodes[cid] for cid in node.child_task_ids if cid in self._nodes],
                key=lambda n: n.task_number,
            )

    def get_subtree(self, root_task_id: str) -> List[TaskNode]:
        """Return all tasks in a subtree (including root), depth-first order."""
        with self._lock:
            descendant_ids = self._subtree_index.get(root_task_id, set())
            result = []
            stack = [root_task_id]
            while stack:
                tid = stack.pop()
                node = self._nodes.get(tid)
                if node is None:
                    continue
                result.append(node)
                # Push children in reverse task_number order so smallest comes first
                children = sorted(
                    [self._nodes[cid] for cid in node.child_task_ids if cid in self._nodes],
                    key=lambda n: n.task_number,
                    reverse=True,
                )
                for child in children:
                    stack.append(child.task_id)
            return result

    def get_active_path(self, task_id: str) -> List[TaskNode]:
        """Return the path from root to the given task (leaf-to-root order)."""
        with self._lock:
            path = []
            current = self._nodes.get(task_id)
            while current is not None:
                path.append(current)
                current = self._nodes.get(current.parent_task_id) if current.parent_task_id else None
            return list(reversed(path))

    def get_subtask_statuses(self, root_task_id: str) -> Dict[str, str]:
        """Return {task_id: status} for all tasks in the subtree."""
        with self._lock:
            descendant_ids = self._subtree_index.get(root_task_id, set())
            return {
                tid: self._nodes[tid].status
                for tid in descendant_ids
                if tid in self._nodes
            }

    def aggregate_results(self, root_task_id: str) -> str:
        """
        Walk the entire subtree and concatenate results.

        Tasks are processed depth-first; each task's result is prefixed
        with its task_number for ordering.  Failed tasks show the error.
        """
        with self._lock:
            nodes = self.get_subtree(root_task_id)
            if not nodes:
                return ""

            lines = []
            for node in nodes:
                status_marker = {
                    "pending": "[PENDING]",
                    "running": "[RUNNING]",
                    "completed": "[OK]",
                    "failed": "[FAIL]",
                }.get(node.status, "[?]")

                prefix = f"Task {node.task_number} {status_marker}"
                if node.child_task_ids:
                    lines.append(f"{prefix} {node.description} (has {len(node.child_task_ids)} subtasks)")
                elif node.result:
                    lines.append(f"{prefix} {node.description}")
                    lines.append(f"  -> {node.result}")
                else:
                    lines.append(f"{prefix} {node.description} (no result)")

            return "\n".join(lines)

    def task_summary(self, root_task_id: str) -> Dict[str, Any]:
        """Return a summary dict for a root task: counts by status, total duration."""
        with self._lock:
            descendant_ids = self._subtree_index.get(root_task_id, set())
            statuses: Dict[str, int] = {}
            total_duration = 0.0
            for tid in descendant_ids:
                node = self._nodes.get(tid)
                if node is None:
                    continue
                statuses[node.status] = statuses.get(node.status, 0) + 1
                if node.completed_at is not None:
                    total_duration += node.completed_at - node.created_at
            return {
                "root_task_id": root_task_id,
                "statuses": statuses,
                "total_duration_seconds": round(total_duration, 2),
            }
