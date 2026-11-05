import json
import unittest

from loomrise.durable_store import SqliteStore
from loomrise.state_window import evaluate_state_window


class StateWindowEvaluationTests(unittest.TestCase):
    def test_metric_and_window_are_required_in_the_persisted_count_snapshot(self):
        with self.assertRaisesRegex(ValueError, "metric"):
            evaluate_state_window(metric="runs", window="forever", op="gt", value=0,
                                  counts={"forever": 1})
        with self.assertRaisesRegex(ValueError, "count"):
            evaluate_state_window(metric="runs", window="cycle", op="gt", value=0,
                                  counts={"runs": {"forever": 1}})

    def test_cycle_and_session_windows_are_distinct(self):
        counts = {"runs": {"cycle": 2, "24h": 4, "forever": 8}}
        self.assertTrue(evaluate_state_window(metric="runs", window="cycle", op="eq", value=2,
                                              counts=counts))
        with self.assertRaisesRegex(ValueError, "window"):
            evaluate_state_window(metric="runs", window="session", op="gt", value=0,
                                  counts=counts)


class StateWindowStoreTests(unittest.TestCase):
    def test_state_windows_are_scoped_to_persisted_agent_identity(self):
        store = SqliteStore(":memory:")
        try:
            now = "2026-11-02T12:00:00+00:00"
            recent = "2026-11-02T11:00:00+00:00"
            old = "2026-11-01T11:00:00+00:00"

            def add_run(run_id, agent_id, stamp, tool_attempts, snapshot_json=None):
                snapshot = snapshot_json or ("{}" if agent_id is None else json.dumps({"agent_id": agent_id}))
                store._conn.execute(
                    "INSERT INTO requests(request_id,tenant_id,agent_version,channel,state,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (run_id, "tenant", "v1", "text", "success", stamp, stamp),
                )
                store._conn.execute(
                    "INSERT INTO runs(run_id,request_id,tenant_id,agent_version,status,occupancy_generation,owner_id,started_at,snapshot_json) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    (run_id, run_id, "tenant", "v1", "finished", 1, "owner", stamp, snapshot),
                )
                for index in range(tool_attempts):
                    key = f"{run_id}-tool-{index}"
                    store._conn.execute(
                        "INSERT INTO tool_attempts(attempt_key,run_id,action,args_hash,state,created_at,updated_at) "
                        "VALUES(?,?,?,?,?,?,?)",
                        (key, run_id, "lookup", "hash", "failed", stamp, stamp),
                    )

            add_run("run-agent-a", "agent-a", recent, 2)
            add_run("run-agent-b", "agent-b", recent, 7)
            add_run("run-legacy", None, recent, 11)
            add_run("run-invalid-snapshot", None, recent, 5, snapshot_json="not-json")
            store._conn.execute(
                "INSERT INTO requests(request_id,tenant_id,agent_version,channel,state,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?)",
                ("run-agent-a-v2", "tenant", "v2", "text", "success", recent, recent),
            )
            store._conn.execute(
                "INSERT INTO runs(run_id,request_id,tenant_id,agent_version,status,occupancy_generation,owner_id,started_at,snapshot_json) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                ("run-agent-a-v2", "run-agent-a-v2", "tenant", "v2", "finished", 1, "owner", recent,
                 json.dumps({"agent_id": "agent-a"})),
            )
            store._conn.execute(
                "INSERT INTO tool_attempts(attempt_key,run_id,action,args_hash,state,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?)",
                ("run-agent-a-v2-tool", "run-agent-a-v2", "lookup", "hash", "failed", recent, recent),
            )

            self.assertEqual(
                store.state_window_counts(tenant_id="tenant", agent_id="agent-a", agent_version="v1", now=now),
                {"attempts": {"24h": 2, "forever": 2}, "runs": {"24h": 1, "forever": 1}},
            )
            self.assertEqual(
                store.state_window_counts(tenant_id="tenant", agent_id="agent-b", agent_version="v1", now=now),
                {"attempts": {"24h": 7, "forever": 7}, "runs": {"24h": 1, "forever": 1}},
            )
        finally:
            store.close()

    def test_state_windows_count_tool_attempts_runs_and_bound_cycle_separately(self):
        store = SqliteStore(":memory:")
        try:
            binding = store.register_service_cycle(
                tenant_id="tenant", agent_id="agent", authority_id="authority",
                subject_id="subject", matter_ref="matter", source_event_id="source",
                agent_version="version", config_hash="hash",
            )
            other_binding = store.register_service_cycle(
                tenant_id="tenant", agent_id="agent", authority_id="authority",
                subject_id="subject", matter_ref="other-matter", source_event_id="other-source",
                agent_version="version", config_hash="hash",
            )
            foreign_agent_binding = store.register_service_cycle(
                tenant_id="tenant", agent_id="other-agent", authority_id="authority",
                subject_id="subject", matter_ref="foreign-matter", source_event_id="foreign-source",
                agent_version="version", config_hash="hash",
            )
            foreign_version_binding = store.register_service_cycle(
                tenant_id="tenant", agent_id="agent", authority_id="authority",
                subject_id="subject", matter_ref="foreign-version-matter", source_event_id="foreign-version-source",
                agent_version="other-version", config_hash="hash",
            )
            now = "2026-11-02T12:00:00+00:00"
            recent = "2026-11-02T11:00:00+00:00"
            old = "2026-11-01T11:00:00+00:00"
            future = "2026-11-02T13:00:00+00:00"

            def add_request(request_id, cycle, stamp):
                store._conn.execute(
                    "INSERT INTO requests(request_id,tenant_id,agent_version,channel,state,created_at,updated_at,service_cycle_json) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (request_id, "tenant", "version", "text", "success", stamp, stamp,
                     json.dumps(cycle.to_dict(), sort_keys=True, separators=(",", ":"))),
                )

            def add_run(run_id, request_id, stamp, tool_attempts):
                store._conn.execute(
                    "INSERT INTO runs(run_id,request_id,tenant_id,agent_version,status,occupancy_generation,owner_id,started_at,snapshot_json) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    (run_id, request_id, "tenant", "version", "finished", 1, "owner", stamp,
                     json.dumps({"agent_id": "agent"})),
                )
                for index in range(tool_attempts):
                    key = f"{run_id}-tool-{index}"
                    store._conn.execute(
                        "INSERT INTO tool_attempts(attempt_key,run_id,action,args_hash,state,created_at,updated_at) "
                        "VALUES(?,?,?,?,?,?,?)",
                        (key, run_id, "lookup", "hash", "failed", stamp, stamp),
                    )

            add_request("request-a", binding, recent)
            add_request("request-b", binding, old)
            add_request("request-other", other_binding, recent)
            add_request("request-future", binding, future)
            add_run("run-a1", "request-a", recent, 2)
            add_run("run-a2", "request-a", recent, 1)
            add_run("run-b1", "request-b", old, 2)
            add_run("run-other", "request-other", recent, 9)
            add_run("run-future", "request-future", future, 1)

            self.assertEqual(
                store.state_window_counts(
                    tenant_id="tenant", agent_id="agent", agent_version="version",
                    cycle_id=binding.cycle_id, now=now,
                ),
                {
                    "attempts": {"24h": 3, "forever": 6, "cycle": 6},
                    "runs": {"24h": 2, "forever": 4, "cycle": 4},
                },
            )
            self.assertEqual(
                store.state_window_counts(tenant_id="tenant", agent_id="agent", agent_version="version", now=now),
                {"attempts": {"24h": 12, "forever": 15}, "runs": {"24h": 3, "forever": 5}},
            )
            with self.assertRaisesRegex(ValueError, "service cycle"):
                store.state_window_counts(tenant_id="other-tenant", agent_id="agent", agent_version="version",
                                          cycle_id=binding.cycle_id, now=now)
            with self.assertRaisesRegex(ValueError, "service cycle"):
                store.state_window_counts(tenant_id="tenant", agent_id="agent", agent_version="version",
                                          cycle_id=foreign_agent_binding.cycle_id, now=now)
            with self.assertRaisesRegex(ValueError, "service cycle"):
                store.state_window_counts(tenant_id="tenant", agent_id="agent", agent_version="version",
                                          cycle_id=foreign_version_binding.cycle_id, now=now)
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
