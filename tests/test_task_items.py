from __future__ import annotations

import os
import tempfile
import unittest

from loomrise.durable_store import SqliteStore


class TaskItemRecoveryTests(unittest.TestCase):
    def test_cancelled_task_is_not_reactivated_or_recoverable_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "loomrise.db")
            store = SqliteStore(path, owner_id="before-restart")
            store.create_task_item(
                task_id="task-1",
                tenant_id="tenant-1",
                agent_id="agent-1",
                subject_id="subject-1",
                service_cycle_id="cycle-1",
                purpose="follow_up",
                source_agent_version="agent-v1",
            )
            store.cancel_task_item("task-1")
            store.close()

            recovered = SqliteStore(path, owner_id="after-restart")
            recovered.recover(owner_id="after-restart")

            task = recovered.task_item("task-1")
            self.assertIsNotNone(task)
            self.assertEqual(task["state"], "cancelled")
            self.assertEqual(task["revision"], 2)
            self.assertEqual(recovered.recoverable_task_items(), [])
            recovered.close()

    def test_v4_database_migrates_task_items(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "loomrise.db")
            store = SqliteStore(path)
            store._conn.execute("DROP INDEX idx_task_items_recovery")
            store._conn.execute("DROP TABLE task_items")
            store._conn.execute("UPDATE meta SET value='4' WHERE key='schema_version'")
            store.close()

            migrated = SqliteStore(path)
            self.assertIsNotNone(migrated._conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='task_items'",
            ).fetchone())
            self.assertEqual(
                migrated._conn.execute(
                    "SELECT value FROM meta WHERE key='schema_version'",
                ).fetchone()["value"],
                "6",
            )
            migrated.close()

    def test_repeated_cancel_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SqliteStore(os.path.join(directory, "loomrise.db"))
            store.create_task_item(
                task_id="task-1",
                tenant_id="tenant-1",
                agent_id="agent-1",
                subject_id="subject-1",
                service_cycle_id="cycle-1",
                purpose="follow_up",
                source_agent_version="agent-v1",
            )
            cancelled = store.cancel_task_item("task-1")
            repeated = store.cancel_task_item("task-1")
            self.assertEqual(cancelled["revision"], 2)
            self.assertEqual(repeated["revision"], 2)
            store.close()


if __name__ == "__main__":
    unittest.main()
