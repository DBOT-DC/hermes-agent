"""Tests for agent.task_hierarchy — TaskNode CRUD, tree operations, aggregation."""

import pytest
from agent.task_hierarchy import TaskNode, TaskHierarchyManager


# ── TaskNode ────────────────────────────────────────────────────────


class TestTaskNode:
    def test_to_dict(self):
        import time
        node = TaskNode(task_id="t1", root_task_id="t1", parent_task_id=None,
                        child_task_ids=[], task_number=0, mode="general",
                        status="pending", description="", result=None,
                        created_at=time.time(), completed_at=None)
        d = node.to_dict()
        assert d["task_id"] == "t1"
        assert d["root_task_id"] == "t1"
        assert d["status"] == "pending"

    def test_default_fields(self):
        import time
        node = TaskNode(task_id="t1", root_task_id="t1", parent_task_id=None,
                        child_task_ids=[], task_number=0, mode="general",
                        status="pending", description="", result=None,
                        created_at=time.time(), completed_at=None)
        assert node.child_task_ids == []
        assert node.task_number == 0
        assert node.status == "pending"
        assert node.description == ""
        assert node.result is None


# ── TaskHierarchyManager CRUD ──────────────────────────────────────


class TestHierarchyCRUD:
    def setup_method(self):
        self.mgr = TaskHierarchyManager()

    def test_create_root_task(self):
        t = self.mgr.create_task("Root task")
        assert t.task_id
        assert t.root_task_id == t.task_id
        assert t.parent_task_id is None
        assert t.status == "pending"

    def test_create_child_task(self):
        root = self.mgr.create_task("Root")
        child = self.mgr.create_task("Child", parent_id=root.task_id)
        assert child.parent_task_id == root.task_id
        assert child.root_task_id == root.task_id
        assert child.task_number == 0

    def test_create_multiple_children_numbering(self):
        root = self.mgr.create_task("Root")
        c1 = self.mgr.create_task("Child 1", parent_id=root.task_id)
        c2 = self.mgr.create_task("Child 2", parent_id=root.task_id)
        assert c1.task_number == 0
        assert c2.task_number == 1

    def test_create_child_invalid_parent(self):
        with pytest.raises(ValueError):
            self.mgr.create_task("Orphan", parent_id="nonexistent")

    def test_start_task(self):
        t = self.mgr.create_task("Task")
        self.mgr.start_task(t.task_id)
        assert self.mgr.get_task(t.task_id).status == "running"

    def test_start_task_not_found(self):
        with pytest.raises(ValueError):
            self.mgr.start_task("nonexistent")

    def test_complete_task(self):
        t = self.mgr.create_task("Task")
        self.mgr.start_task(t.task_id)
        self.mgr.complete_task(t.task_id, "Done!")
        updated = self.mgr.get_task(t.task_id)
        assert updated.status == "completed"
        assert updated.result == "Done!"
        assert updated.completed_at is not None

    def test_complete_task_not_found(self):
        with pytest.raises(ValueError):
            self.mgr.complete_task("nonexistent", "result")

    def test_fail_task(self):
        t = self.mgr.create_task("Task")
        self.mgr.start_task(t.task_id)
        self.mgr.fail_task(t.task_id, "Boom!")
        updated = self.mgr.get_task(t.task_id)
        assert updated.status == "failed"
        assert "Boom!" in updated.result

    def test_fail_task_not_found(self):
        with pytest.raises(ValueError):
            self.mgr.fail_task("nonexistent", "error")

    def test_get_task_not_found(self):
        assert self.mgr.get_task("nonexistent") is None


# ── Tree traversal ─────────────────────────────────────────────────


class TestHierarchyTraversal:
    def setup_method(self):
        self.mgr = TaskHierarchyManager()
        self.root = self.mgr.create_task("Root")
        self.c1 = self.mgr.create_task("Child 1", parent_id=self.root.task_id)
        self.c2 = self.mgr.create_task("Child 2", parent_id=self.root.task_id)
        self.gc1 = self.mgr.create_task("Grandchild", parent_id=self.c1.task_id)

    def test_get_children(self):
        children = self.mgr.get_children(self.root.task_id)
        assert len(children) == 2
        # Should be sorted by task_number
        assert children[0].task_id == self.c1.task_id
        assert children[1].task_id == self.c2.task_id

    def test_get_children_leaf(self):
        children = self.mgr.get_children(self.gc1.task_id)
        assert children == []

    def test_get_children_not_found(self):
        assert self.mgr.get_children("nonexistent") == []

    def test_get_root_task(self):
        assert self.mgr.get_root_task(self.gc1.task_id).task_id == self.root.task_id
        assert self.mgr.get_root_task(self.root.task_id).task_id == self.root.task_id

    def test_get_subtree(self):
        subtree = self.mgr.get_subtree(self.root.task_id)
        ids = {n.task_id for n in subtree}
        assert ids == {self.root.task_id, self.c1.task_id, self.c2.task_id, self.gc1.task_id}

    def test_get_subtree_not_found(self):
        assert self.mgr.get_subtree("nonexistent") == []

    def test_get_active_path(self):
        path = self.mgr.get_active_path(self.gc1.task_id)
        ids = [n.task_id for n in path]
        assert ids == [self.root.task_id, self.c1.task_id, self.gc1.task_id]

    def test_get_subtask_statuses(self):
        self.mgr.start_task(self.c1.task_id)
        self.mgr.complete_task(self.c1.task_id, "ok")
        statuses = self.mgr.get_subtask_statuses(self.root.task_id)
        assert statuses[self.c1.task_id] == "completed"
        assert statuses[self.c2.task_id] == "pending"
        assert statuses[self.gc1.task_id] == "pending"


# ── Aggregation ────────────────────────────────────────────────────


class TestHierarchyAggregation:
    def setup_method(self):
        self.mgr = TaskHierarchyManager()
        self.root = self.mgr.create_task("Root")
        self.c1 = self.mgr.create_task("Child 1", parent_id=self.root.task_id)
        self.c2 = self.mgr.create_task("Child 2", parent_id=self.root.task_id)
        self.mgr.complete_task(self.c1.task_id, "Result 1")
        self.mgr.fail_task(self.c2.task_id, "Error")

    def test_aggregate_results(self):
        text = self.mgr.aggregate_results(self.root.task_id)
        assert "[OK]" in text
        assert "[FAIL]" in text
        assert "Result 1" in text

    def test_task_summary(self):
        summary = self.mgr.task_summary(self.root.task_id)
        assert summary["root_task_id"] == self.root.task_id
        assert summary["statuses"]["completed"] == 1
        assert summary["statuses"]["failed"] == 1
