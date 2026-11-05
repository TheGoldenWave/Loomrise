from __future__ import annotations

from datetime import datetime, timedelta
import os
import tempfile
import unittest

from loomrise.configuration import ConfigurationApplication, ConfigurationPrincipal, ConfigurationService
from loomrise.contracts import Channel, RequestState, Run, RunEvent, ServiceRequest
from loomrise.durable_store import SqliteStore
from loomrise.graph_runtime import GraphRuntime


def config() -> dict:
    return {
        "persona": {"fields": {}, "entry_unit_ids": ["start"]},
        "units": [], "g0_gates": [], "hard_rules": [], "task_blueprints": [],
    }


def nested_config() -> dict:
    def unit(uid: str, body: dict) -> dict:
        return {
            "unit_id": uid, "version": 1, "load_mode": "routed",
            "entry_ports": [{"port": "in", "requires": []}], "reads": [], "writes": [],
            "exit_ports": [{"port": "done", "completion": {"deterministic": {}}}],
            "on_event": [], "fallback": {"kind": "human"}, "max_rounds": 2, "body": body,
        }

    leaf = unit("leaf", {"kind": "say", "text": "fictional greeting", "verbatim_reason": "fixed"})
    parent = unit("parent", {
        "kind": "graph", "routing": {"mode": "deterministic"},
        "nodes": [{"id": "same", "unit_ref": {"unit_id": "leaf", "version": 1}}],
        "edges": [{"id": "finish", "from": "same.done", "to": "self.done", "condition": {}}],
    })
    parent["entry_ports"][0]["goto"] = "same.in"
    return {
        **config(), "units": [parent, leaf],
        "orchestration": {
            "schema_version": "unit-graph-v1", "kind": "graph", "routing": {"mode": "deterministic"},
            "entry": "same.in", "nodes": [{"id": "same", "unit_ref": {"unit_id": "parent", "version": 1}}],
            "edges": [{"id": "finish", "from": "same.done", "to": "end", "condition": {}}],
            "on_event": [], "fallback": {"kind": "human"},
        },
    }


class RunOverlayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = SqliteStore(os.path.join(self.tmp.name, "overlay.db"))
        self.configuration = ConfigurationService(self.store)
        self.configuration.register_stable_version(
            tenant_id="tenant-a", agent_id="expert-a", version_id="v1", config=config(),
        )
        self.principal = ConfigurationPrincipal(
            tenant_id="tenant-a", actor_id="owner", role="owner", agent_ids=("expert-a",),
        )
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.store.close)

    def _run(self, run_id: str, *, channel: str = "text", tenant: str = "tenant-a",
             agent: str | None = "expert-a", version: str = "v1") -> None:
        request = ServiceRequest(
            request_id=f"request-{run_id}", tenant_id=tenant, agent_version=version,
            channel=Channel(channel), state=RequestState.RUNNING,
        )
        run = Run(
            run_id=run_id, request_id=request.request_id, tenant_id=tenant,
            agent_version=version, owner_id="owner", snapshot={"agent_id": agent} if agent else {},
        )
        self.store.begin_run(request, run, [])

    def _event(self, run_id: str, event_type: str, payload: object, *,
               ts: str = "2026-10-31T00:00:00+00:00", **identity: str) -> None:
        row = self.store.run_row(run_id)
        request = self.store.request_row(row["request_id"])
        event = RunEvent(
            seq=self.store.next_seq(run_id), event_type=event_type,
            request_id=identity.get("request_id", row["request_id"]), run_id=run_id,
            tenant_id=identity.get("tenant_id", row["tenant_id"]),
            agent_version=identity.get("agent_version", row["agent_version"]),
            channel=identity.get("channel", request["channel"]), ts=ts, payload=payload,
        ).seal("0" * 64)
        self.store.append_events([event])

    def _start(self, run_id: str, **kwargs) -> None:
        self._event(run_id, "route.graph.started", {"schema_version": "unit-graph-v1"}, **kwargs)

    def _step(self, run_id: str, index: int, *, kind: str = "enter", target: str = "welcome.in",
              layer: list[str] | None = None, edge: str | None = None, **kwargs) -> None:
        self._event(run_id, "route.graph.step", {
            "step_index": index, "kind": kind, "target": target,
            "layer": layer or [], "edge_id": edge,
        }, **kwargs)

    def _finish(self, run_id: str, status: str = "completed", **kwargs) -> None:
        self._event(run_id, "route.graph.finished", {"route_status": status}, **kwargs)

    def _overlay(self, **kwargs) -> dict:
        return self.store.read_graph_overlay(**{
            "tenant_id": "tenant-a", "agent_id": "expert-a", "version_id": "v1",
            "from_ts": "2026-10-31T00:00:00+00:00", "to_ts": "2026-11-01T00:00:00+00:00",
            **kwargs,
        })

    def test_empty_projection_has_versioned_contract_and_unknown_durations(self):
        overlay = self._overlay()
        self.assertEqual(overlay["schema_version"], "run-overlay-v1")
        self.assertEqual(overlay["sample_count"], 0)
        self.assertEqual(overlay["nodes"], {})
        self.assertEqual(overlay["edges"], {})
        self.assertIsNone(overlay["average_duration_ms"])
        self.assertIsNone(overlay["termination_targets"])
        self.assertEqual(overlay["coverage"]["duration"]["measured_count"], 0)

    def test_actual_runtime_events_keep_nested_identity_and_emit_explicit_dwell(self):
        self._run("real-trace")
        tick = datetime.fromisoformat("2026-10-31T00:00:00+00:00")

        def emit(event_type: str, **payload) -> None:
            nonlocal tick
            self._event("real-trace", event_type, payload, ts=tick.isoformat())
            tick += timedelta(seconds=10)

        routed = GraphRuntime(nested_config()).route_and_emit({}, emit)
        self.assertEqual(routed.status, "completed")
        overlay = self._overlay()
        self.assertEqual(overlay["sample_count"], 1)
        self.assertEqual(overlay["route_count"], 1)
        for key, layer in (('["same"]', []), ('["same","same"]', ["same"])):
            self.assertEqual(overlay["nodes"][key]["entered"], 1)
            self.assertEqual(overlay["nodes"][key]["layer"], layer)
            self.assertEqual(overlay["nodes"][key]["node_id"], "same")
            self.assertIsInstance(overlay["nodes"][key]["dwell_ms"], int)
            self.assertEqual(overlay["nodes"][key]["dwell_sample_count"], 1)
            self.assertLess(overlay["nodes"][key]["dwell_ms"], 10_000)
            self.assertIsNone(overlay["nodes"][key]["percentage"])
        self.assertEqual(overlay["edges"]['["finish"]']["traversed"], 1)
        self.assertEqual(overlay["edges"]['["same","finish"]']["traversed"], 1)
        self.assertEqual(overlay["terminations"], {"completed": 1})
        self.assertEqual(overlay["termination_targets"], {'["same"]': 1})
        self.assertIsInstance(overlay["average_duration_ms"], int)
        self.assertEqual(overlay["coverage"]["duration"]["reason"], "route_execution_duration")
        self.assertEqual(overlay["coverage"]["node_dwell"]["measured_count"], 2)
        self.assertEqual(overlay["coverage"]["node_termination"]["measured_count"], 1)

    def test_dwell_and_terminal_evidence_must_match_entered_layered_nodes(self):
        self._run("evidence-valid")
        self._start("evidence-valid")
        self._step("evidence-valid", 0, target="same.in", layer=["parent"])
        self._event("evidence-valid", "route.graph.step", {
            "step_index": 1, "kind": "edge", "target": "end", "reason": "finished",
            "edge_id": "finish", "layer": ["parent"], "source": "same.done", "unit_id": "leaf",
        })
        self._event("evidence-valid", "route.graph.finished", {
            "route_status": "completed",
            "telemetry_schema_version": "graph-telemetry-v1",
            "node_dwell_samples": [
                {"node_id": "same", "layer": ["parent"], "dwell_ms": 12},
                {"node_id": "ghost", "layer": ["parent"], "dwell_ms": 99},
                {"node_id": "same", "layer": ["parent"], "dwell_ms": True},
                {"node_id": "same", "layer": ["parent"], "dwell_ms": 13},
            ],
            "terminal_node": {
                "node_id": "same", "unit_id": "leaf", "exit_port": "done", "layer": ["parent"],
                "evidence_kind": "edge", "step_index": 1, "edge_id": "finish",
            },
        })

        self._run("evidence-invalid")
        self._start("evidence-invalid")
        self._step("evidence-invalid", 0, target="same.in")
        self._event("evidence-invalid", "route.graph.finished", {
            "route_status": "completed",
            "telemetry_schema_version": "graph-telemetry-v1",
            "node_dwell_samples": {"node_id": "same", "layer": [], "dwell_ms": 50},
            "terminal_node": {
                "node_id": "same", "unit_id": "parent", "exit_port": "done", "layer": ["ghost"],
                "evidence_kind": "edge", "step_index": 0, "edge_id": "fake",
            },
        })

        self._run("evidence-fabricated")
        self._start("evidence-fabricated")
        self._step("evidence-fabricated", 0, target="same.in", layer=["parent"])
        self._event("evidence-fabricated", "route.graph.finished", {
            "route_status": "completed",
            "telemetry_schema_version": "graph-telemetry-v1",
            "terminal_node": {
                "node_id": "same", "unit_id": "leaf", "exit_port": "done", "layer": ["parent"],
                "evidence_kind": "edge", "step_index": 0, "edge_id": "fake",
            },
        })

        self._run("evidence-mismatched")
        self._start("evidence-mismatched")
        self._step("evidence-mismatched", 0, target="same.in", layer=["parent"])
        self._event("evidence-mismatched", "route.graph.step", {
            "step_index": 1, "kind": "edge", "target": "end", "reason": "finished",
            "edge_id": "finish", "layer": ["parent"], "source": "same.done", "unit_id": "leaf",
        })
        self._event("evidence-mismatched", "route.graph.finished", {
            "route_status": "completed",
            "telemetry_schema_version": "graph-telemetry-v1",
            "terminal_node": {
                "node_id": "same", "unit_id": "parent", "exit_port": "other", "layer": ["parent"],
                "evidence_kind": "edge", "step_index": 1, "edge_id": "finish",
            },
        })

        overlay = self._overlay()
        self.assertEqual(overlay["nodes"]['["parent","same"]']["dwell_ms"], 12)
        self.assertEqual(overlay["nodes"]['["parent","same"]']["dwell_sample_count"], 1)
        self.assertIsNone(overlay["nodes"]['["same"]']["dwell_ms"])
        self.assertEqual(overlay["termination_targets"], {'["parent","same"]': 1})
        self.assertEqual(overlay["coverage"]["node_dwell"]["measured_count"], 1)
        self.assertEqual(overlay["coverage"]["node_dwell"]["unmeasured_route_count"], 3)
        self.assertEqual(overlay["coverage"]["node_termination"]["measured_count"], 1)
        self.assertEqual(overlay["coverage"]["node_termination"]["unmeasured_route_count"], 3)

    def test_terminal_evidence_must_follow_entry_and_be_the_final_route_step(self):
        self._run("terminal-before-entry")
        self._start("terminal-before-entry")
        self._event("terminal-before-entry", "route.graph.step", {
            "step_index": 0, "kind": "edge", "target": "end", "edge_id": "finish",
            "layer": [], "source": "same.done", "unit_id": "leaf",
        })
        self._step("terminal-before-entry", 1, target="same.in")
        self._event("terminal-before-entry", "route.graph.finished", {
            "route_status": "completed", "telemetry_schema_version": "graph-telemetry-v1",
            "terminal_node": {
                "node_id": "same", "unit_id": "leaf", "exit_port": "done", "layer": [],
                "evidence_kind": "edge", "step_index": 0, "edge_id": "finish",
            },
        })

        self._run("terminal-not-final")
        self._start("terminal-not-final")
        self._step("terminal-not-final", 0, target="same.in")
        self._event("terminal-not-final", "route.graph.step", {
            "step_index": 1, "kind": "edge", "target": "end", "edge_id": "finish",
            "layer": [], "source": "same.done", "unit_id": "leaf",
        })
        self._step("terminal-not-final", 2, target="other.in")
        self._event("terminal-not-final", "route.graph.finished", {
            "route_status": "completed", "telemetry_schema_version": "graph-telemetry-v1",
            "terminal_node": {
                "node_id": "same", "unit_id": "leaf", "exit_port": "done", "layer": [],
                "evidence_kind": "edge", "step_index": 1, "edge_id": "finish",
            },
        })

        overlay = self._overlay()
        self.assertIsNone(overlay["termination_targets"])
        self.assertEqual(overlay["coverage"]["node_termination"]["measured_count"], 0)
        self.assertEqual(overlay["coverage"]["node_termination"]["unmeasured_route_count"], 2)

    def test_route_duration_accepts_only_nonnegative_integers_not_booleans(self):
        for run_id, duration in (("bool-duration", True), ("negative-duration", -5),
                                 ("valid-duration", 40)):
            self._run(run_id)
            self._start(run_id)
            self._step(run_id, 0)
            self._event(run_id, "route.graph.finished", {
                "route_status": "completed", "duration_ms": duration,
            })

        overlay = self._overlay()
        self.assertEqual(overlay["average_duration_ms"], 40)
        self.assertEqual(overlay["coverage"]["duration"]["measured_count"], 1)

    def test_agent_version_collisions_and_unattributed_runs_cannot_leak(self):
        self.configuration.register_stable_version(
            tenant_id="tenant-a", agent_id="expert-b", version_id="v1", config=config(),
        )
        for name, agent, tenant, version in (
            ("mine", "expert-a", "tenant-a", "v1"),
            ("other-agent", "expert-b", "tenant-a", "v1"),
            ("unattributed", None, "tenant-a", "v1"),
            ("other-tenant", "expert-a", "tenant-b", "v1"),
            ("other-version", "expert-a", "tenant-a", "v2"),
        ):
            self._run(name, agent=agent, tenant=tenant, version=version)
            self._start(name)
            self._step(name, 0, target=f"{name}.in")
            self._finish(name)
        overlay = self._overlay()
        self.assertEqual(overlay["sample_count"], 1)
        self.assertEqual(set(overlay["nodes"]), {'["mine"]'})

    def test_window_compares_instants_and_includes_whole_selected_route(self):
        for run_id, ts in (
            ("included-offset", "2026-10-31T08:00:00+08:00"),
            ("excluded-before", "2026-10-31T00:00:00+08:00"),
            ("excluded-end", "2026-11-01T08:00:00+08:00"),
        ):
            self._run(run_id)
            self._start(run_id, ts=ts)
            self._step(run_id, 0, ts="2026-11-01T01:00:00+00:00")
            self._finish(run_id, ts="2026-11-01T01:00:01+00:00")
        overlay = self._overlay()
        self.assertEqual(overlay["sample_count"], 1)
        self.assertEqual(overlay["nodes"]['["welcome"]']["entered"], 1)
        self.assertEqual(overlay["terminations"], {"completed": 1})
        self.assertEqual(overlay["time_window_basis"], "route.graph.started")

    def test_per_node_entrant_threshold_and_cycles_do_not_inflate_percentages(self):
        for index in range(30):
            run_id = f"sample-{index}"
            self._run(run_id)
            self._start(run_id)
            self._step(run_id, 0)
            self._step(run_id, 1, kind="edge", edge="loop", target="welcome.in")
            self._step(run_id, 2)
            self._step(run_id, 3, kind="edge", edge="loop", target="welcome.in")
            if index == 0:
                self._step(run_id, 4, target="rare.in")
            self._finish(run_id)
        overlay = self._overlay()
        welcome = overlay["nodes"]['["welcome"]']
        self.assertEqual(welcome["entered"], 60)
        self.assertEqual(welcome["entrant_count"], 30)
        self.assertEqual(welcome["percentage"], 100.0)
        self.assertEqual(welcome["percentage_denominator"], 30)
        rare = overlay["nodes"]['["rare"]']
        self.assertEqual(rare["entrant_count"], 1)
        self.assertTrue(rare["low_sample"])
        self.assertIsNone(rare["percentage"])
        loop = overlay["edges"]['["loop"]']
        self.assertEqual(loop["traversed"], 60)
        self.assertEqual(loop["entrant_count"], 30)
        self.assertEqual(loop["percentage"], 100.0)

    def test_repeated_routes_in_one_run_are_counts_not_independent_samples(self):
        self._run("repeated")
        for _ in range(30):
            self._start("repeated")
            self._step("repeated", 0)
            self._finish("repeated")
        overlay = self._overlay()
        self.assertEqual(overlay["sample_count"], 1)
        self.assertEqual(overlay["route_count"], 30)
        self.assertEqual(overlay["terminations"], {"completed": 30})
        self.assertEqual(overlay["nodes"]['["welcome"]']["entered"], 30)
        self.assertEqual(overlay["nodes"]['["welcome"]']["entrant_count"], 1)
        self.assertIsNone(overlay["nodes"]['["welcome"]']["percentage"])

    def test_cycle_limit_is_not_a_traversal_of_the_original_cycle_edge(self):
        self._run("cycle")
        self._start("cycle")
        self._step("cycle", 0)
        self._step("cycle", 1, kind="cycle_limit", edge="loop", target="end")
        self._finish("cycle")
        edge = self._overlay()["edges"]['["loop"]']
        self.assertEqual(edge["traversed"], 0)
        self.assertEqual(edge["cycle_limit_count"], 1)
        self.assertIsNone(edge["percentage"])

    def test_malformed_payloads_and_duplicate_step_indices_do_not_become_metrics(self):
        self._run("malformed")
        self._start("malformed")
        for payload in ([], None, "not-an-object", {"kind": "enter", "target": "ghost.in"},
                        {"kind": "enter", "target": "ghost.in", "layer": "root", "step_index": 0},
                        {"kind": "enter", "target": "ghost.in", "layer": [1], "step_index": 0}):
            self._event("malformed", "route.graph.step", payload)
        self._step("malformed", 0)
        self._step("malformed", 0)
        self._event("malformed", "route.graph.finished", {"route_status": []})
        overlay = self._overlay()
        self.assertEqual(overlay["sample_count"], 1)
        self.assertEqual(overlay["nodes"]['["welcome"]']["entered"], 1)
        self.assertEqual(overlay["terminations"], {})
        self.assertEqual(overlay["coverage"]["ignored_event_count"], 8)
        self.assertEqual(overlay["coverage"]["unfinished_route_count"], 1)

    def test_orphans_unknown_schemas_and_event_identity_mismatches_are_excluded(self):
        self._run("orphan")
        self._step("orphan", 0)
        self._finish("orphan")
        self._run("unknown-schema")
        self._event("unknown-schema", "route.graph.started", {"schema_version": "future-graph"})
        self._step("unknown-schema", 0)
        self._finish("unknown-schema")
        self._run("wrong-envelope")
        self._start("wrong-envelope", tenant_id="tenant-b")
        self._step("wrong-envelope", 0, tenant_id="tenant-b")
        self._finish("wrong-envelope", tenant_id="tenant-b")
        overlay = self._overlay()
        self.assertEqual(overlay["sample_count"], 0)
        self.assertEqual(overlay["nodes"], {})
        self.assertEqual(overlay["terminations"], {})

    def test_invalid_json_is_skipped_without_breaking_authorized_projection(self):
        self._run("corrupt")
        self._start("corrupt")
        self._step("corrupt", 0)
        self._finish("corrupt")
        self.store._conn.execute("UPDATE events SET event_json='invalid JSON' WHERE run_id='corrupt' AND seq=1")
        overlay = self._overlay()
        self.assertEqual(overlay["nodes"], {})
        self.assertEqual(overlay["coverage"]["ignored_event_count"], 1)

    def test_corrupt_invocation_boundaries_do_not_attribute_later_steps_to_previous_route(self):
        for boundary in ("route.graph.started", "route.graph.finished"):
            with self.subTest(boundary=boundary):
                run_id = boundary
                self._run(run_id)
                self._start(run_id)
                self._step(run_id, 0)
                self._event(run_id, boundary, {})
                self.store._conn.execute(
                    "UPDATE events SET event_json='invalid JSON' WHERE run_id=? AND seq=2", (run_id,),
                )
                self._step(run_id, 1, target="ghost.in")
        overlay = self._overlay()
        self.assertNotIn('["ghost"]', overlay["nodes"])
        self.assertEqual(overlay["nodes"]['["welcome"]']["entered"], 2)
        self.assertEqual(overlay["coverage"]["unfinished_route_count"], 2)

    def test_channel_filter_and_application_authorization_are_preserved(self):
        for channel in ("text", "voice"):
            self._run(channel, channel=channel)
            self._start(channel)
            self._step(channel, 0)
            self._finish(channel, "fallback" if channel == "text" else "completed")
        app = ConfigurationApplication(self.configuration)
        payload = {"agent_id": "expert-a", "version_id": "v1", "from": "2026-10-31T00:00:00Z",
                   "to": "2026-11-01T00:00:00Z", "channel": "voice"}
        response = app.execute(principal=self.principal, action="run.overlay", payload=payload)
        self.assertTrue(response["ok"])
        self.assertEqual(response["result"]["sample_count"], 1)
        self.assertEqual(response["result"]["channels"], {"voice": 1})
        self.assertEqual(response["result"]["terminations"], {"completed": 1})
        outsider = ConfigurationPrincipal(tenant_id="tenant-a", actor_id="other", role="owner", agent_ids=("expert-b",))
        self.assertFalse(app.execute(principal=outsider, action="run.overlay", payload=payload)["ok"])

    def test_invalid_time_windows_and_channels_are_rejected_at_store_boundary(self):
        for values in ({"from_ts": "2026-10-31"}, {"to_ts": "2026-10-31T00:00:00Z"},
                       {"from_ts": "not-time"}, {"channel": []}, {"channel": "email"}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                self._overlay(**values)


if __name__ == "__main__":
    unittest.main()
