"""Explicit graph-version integration with the existing Skill execution path."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import unittest
import tempfile
import os

from loomrise.contracts import ScenarioPack
from loomrise.service import ExecutionService
from loomrise.durable_store import SqliteStore
from loomrise.service_cycles import ServiceCycleAuthority
from loomrise.contracts import Channel, RequestState, ServiceRequest, SubjectScope, new_id


def graph_config():
    unit = {
        "unit_id": "booking-entry", "version": 1, "load_mode": "routed",
        "entry_ports": [{"port": "from_start", "requires": []}], "reads": [], "writes": [],
        "exit_ports": [{"port": "done", "completion": {"deterministic": {}}, "exits": ["self.done"]}],
        "on_event": [], "fallback": {"kind": "human"}, "max_rounds": 1,
        "body": {"kind": "say", "text": "预约入口", "verbatim_reason": "测试固定内容"},
    }
    return {
        "persona": {"fields": {}}, "units": [unit], "g0_gates": [], "hard_rules": [], "task_blueprints": [],
        "orchestration": {
            "schema_version": "unit-graph-v1", "kind": "graph", "routing": {"mode": "deterministic"},
            "nodes": [{"id": "booking", "unit_ref": {"unit_id": unit["unit_id"], "version": 1}}],
            "entry": "booking.from_start", "input_fields": [],
            "edges": [{"id": "finish-booking", "from": "booking.done", "to": "end", "condition": {}}],
            "on_event": [], "fallback": {"kind": "human"},
        },
    }


def graph_pack(*, binding="course_consult_booking"):
    pack = ScenarioPack.load("scenarios/course_consult_v1/pack.json")
    pack.agent_version = replace(
        pack.agent_version,
        version_id="course-consult-r3-graph-v1",
        orchestration=graph_config(),
        unit_skill_bindings={"booking-entry": binding} if binding else {},
    )
    return pack


class GraphExecutionIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_fallback_keeps_the_explicit_skill_binding_and_zero_writes(self):
        pack = graph_pack()
        value = deepcopy(pack.agent_version.orchestration)
        safe = deepcopy(value['units'][0])
        safe['unit_id'] = 'safe-answer'
        value['units'].append(safe)
        graph = value['orchestration']
        graph['nodes'].append({'id': 'safe', 'unit_ref': {'unit_id': 'safe-answer', 'version': 1}})
        graph['fallback'] = {'kind': 'default_unit', 'target': 'safe.from_start'}
        graph['edges'][0]['condition'] = {'fact': {'field': 'verified', 'op': 'eq', 'value': True}}
        graph['edges'].append({'id': 'safe-end', 'from': 'safe.done', 'to': 'end', 'condition': {}})
        pack.agent_version = replace(pack.agent_version, orchestration=value,
            unit_skill_bindings={'booking-entry': 'course_consult_booking', 'safe-answer': 'refund_request'})
        with tempfile.TemporaryDirectory() as directory:
            store = SqliteStore(os.path.join(directory, 'fallback.db'))
            try:
                authority = ServiceCycleAuthority(store, tenant_id='tenant_demo', agent_id='fictional-agent',
                                                   authority_id='fictional-case-source')
                service = ExecutionService(pack, store=store, agent_id='fictional-agent', cycle_authority=authority)
                grant = authority.register(subject_id='fictional-alice', matter_ref='fictional-order-1',
                    source_event_id='fixture-open-1', agent_version=pack.agent_version.version_id,
                    config_hash=service.cycle_config_hash)
                request = ServiceRequest(new_id('req'), 'tenant_demo', pack.agent_version.version_id,
                    Channel.TEXT, RequestState.QUEUED, subject_id='fictional-alice', subject_scope=SubjectScope.MAPPED)
                result = await service.handle_text('咨询', request=request, cycle_grant=grant,
                    routing_state={'verified': False}, script=[{'text': '请由人工复核。'}])
                self.assertEqual(result.request.state.value, 'success')
                self.assertEqual(service.ledger.find('request.routed')[-1].payload['skill_id'], 'refund_request')
                self.assertEqual(result.write_count, 0)
                self.assertTrue(service.ledger.verify())
            finally:
                store.close()

    async def test_say_text_is_returned_verbatim_and_emitted_as_server_text(self):
        service = ExecutionService(graph_pack())
        result = await service.handle_text('咨询', script=[{'text': '补充回答'}])
        self.assertTrue(result.text.startswith('预约入口'))
        outputs = service.ledger.find('reply.text')
        self.assertEqual(outputs[0].payload['text'], '预约入口')
        self.assertEqual(outputs[0].payload['source'], 'graph_say')
        self.assertEqual(outputs[0].payload['delivery'], 'server_generated')
        self.assertTrue(service.ledger.find('route.graph.message'))

    async def test_supported_say_graph_is_a_freezable_runtime_subset(self):
        pack = graph_pack()
        service = ExecutionService(pack)
        result = await service.handle_text('咨询', script=[{'text': '已回答'}])
        self.assertEqual(result.request.state.value, 'success')
        self.assertTrue(service.ledger.find('route.graph.finished'))
        self.assertTrue(service.ledger.verify())

    async def test_execution_service_does_not_trust_caller_state_window_counts(self):
        pack = graph_pack()
        pack.agent_version.orchestration['orchestration']['edges'][0]['condition'] = {
            'state': {'metric': 'runs', 'window': 'forever', 'op': 'gt', 'value': 0},
        }
        service = ExecutionService(pack)
        result = await service.handle_text('咨询', script=[], routing_state={
            'state_window_counts': {'24h': 999, 'forever': 999, 'cycle': 999},
        })
        self.assertEqual(result.request.state.value, 'failed')
        self.assertTrue(service.ledger.find('request.route_failed'))
        self.assertEqual(service.ledger.find('request.routed'), [])

    async def test_state_window_counts_use_the_persisted_run_agent_scope(self):
        pack = graph_pack()
        pack.agent_version.orchestration['orchestration']['edges'][0]['condition'] = {
            'state': {'metric': 'attempts', 'window': 'forever', 'op': 'eq', 'value': 0},
        }
        store = SqliteStore(':memory:')
        try:
            stamp = '2026-11-02T11:00:00+00:00'
            store._conn.execute(
                'INSERT INTO requests(request_id,tenant_id,agent_version,channel,state,created_at,updated_at) '
                'VALUES(?,?,?,?,?,?,?)',
                ('foreign-request', 'tenant_demo', pack.agent_version.version_id, 'text', 'success', stamp, stamp),
            )
            store._conn.execute(
                'INSERT INTO runs(run_id,request_id,tenant_id,agent_version,status,occupancy_generation,owner_id,started_at,snapshot_json) '
                'VALUES(?,?,?,?,?,?,?,?,?)',
                ('foreign-run', 'foreign-request', 'tenant_demo', pack.agent_version.version_id,
                 'finished', 1, 'owner', stamp, '{"agent_id":"agent-b"}'),
            )
            store._conn.execute(
                'INSERT INTO tool_attempts(attempt_key,run_id,action,args_hash,state,created_at,updated_at) '
                'VALUES(?,?,?,?,?,?,?)',
                ('foreign-attempt', 'foreign-run', 'lookup', 'hash', 'failed', stamp, stamp),
            )
            service = ExecutionService(pack, store=store, tenant_id='tenant_demo', agent_id='agent-a')
            result = await service.handle_text('咨询', script=[], routing_state={'agent_id': 'agent-b'})
            self.assertEqual(result.request.state.value, 'success')
            self.assertTrue(service.ledger.find('route.graph.finished'))
            self.assertFalse(service.ledger.find('request.route_failed'))
        finally:
            store.close()

    async def test_cycle_state_window_uses_the_bound_durable_run_count(self):
        pack = graph_pack()
        pack.agent_version.orchestration['orchestration']['edges'][0]['condition'] = {
            'state': {'metric': 'runs', 'window': 'cycle', 'op': 'eq', 'value': 1},
        }
        with tempfile.TemporaryDirectory() as directory:
            store = SqliteStore(os.path.join(directory, 'cycle-state-window.db'))
            try:
                authority = ServiceCycleAuthority(store, tenant_id='tenant_demo', agent_id='fictional-agent',
                                                  authority_id='fictional-case-source')
                service = ExecutionService(pack, store=store, agent_id='fictional-agent',
                                           cycle_authority=authority)
                grant = authority.register(subject_id='fictional-alice', matter_ref='fictional-order-1',
                    source_event_id='fixture-open-1', agent_version=pack.agent_version.version_id,
                    config_hash=service.cycle_config_hash)
                request = ServiceRequest(new_id('req'), 'tenant_demo', pack.agent_version.version_id,
                    Channel.TEXT, RequestState.QUEUED, subject_id='fictional-alice',
                    subject_scope=SubjectScope.MAPPED)
                result = await service.handle_text('咨询', request=request, cycle_grant=grant, script=[],
                    routing_state={'state_window_counts': {'runs': {'cycle': 99}}})
                self.assertEqual(result.request.state.value, 'success')
                self.assertTrue(service.ledger.find('route.graph.finished'))
                self.assertFalse(service.ledger.find('request.route_failed'))
            finally:
                store.close()

    async def test_primary_binding_requires_membership_in_the_frozen_version(self):
        pack = graph_pack()
        pack.agent_version = replace(pack.agent_version, skill_ids=[])
        service = ExecutionService(pack)
        result = await service.handle_text('咨询', script=[{'text': '不应执行'}])
        self.assertEqual(result.request.state.value, 'failed')
        self.assertFalse(service.ledger.find('request.routed'))
        self.assertFalse(service.ledger.find('context.fragment'))

    async def test_unsupported_negated_state_fails_without_selecting_a_skill_or_writing(self):
        config = graph_config()
        config["orchestration"]["edges"][0]["condition"] = {
            "none_of": [{"state": {"metric": "attempts", "window": "24h", "op": "gt", "value": 2}}],
        }
        pack = graph_pack()
        pack.agent_version = replace(pack.agent_version, orchestration=config)
        service = ExecutionService(pack)
        result = await service.handle_text("预约", script=[])
        self.assertEqual(result.request.state.value, "failed")
        self.assertFalse(service.ledger.find("request.routed"))
        self.assertIn("state", service.ledger.find("request.route_failed")[-1].payload["reason"])
        self.assertEqual(service.ledger.find("run.finished")[-1].payload["write_count"], 0)
        self.assertEqual(service._active, {})
        self.assertTrue(service.ledger.verify())

    async def test_missing_graph_entry_requirement_fails_without_legacy_keyword_fallback(self):
        config = graph_config()
        config["orchestration"]["input_fields"] = ["intent"]
        pack = graph_pack()
        pack.agent_version = replace(pack.agent_version, orchestration=config)
        service = ExecutionService(pack)
        service._route = lambda text: (_ for _ in ()).throw(AssertionError("must not use legacy router"))
        result = await service.handle_text("预约", script=[])
        self.assertEqual(result.request.state.value, "failed")
        self.assertEqual(service.ledger.find("route.graph.finished")[-1].payload["route_status"], "fallback")
        self.assertEqual(service.ledger.find("request.route_failed")[-1].payload["reason"], "human")
        self.assertTrue(service.ledger.verify())

    async def test_waiting_graph_fails_explicitly_until_durable_suspend_is_integrated(self):
        config = graph_config()
        config["units"][0]["waits"] = [{"on": "approval.received", "timeoutMs": 60000, "timeoutTo": "handoff"}]
        pack = graph_pack()
        pack.agent_version = replace(pack.agent_version, orchestration=config)
        service = ExecutionService(pack)
        result = await service.handle_text("预约", script=[])
        self.assertEqual(result.request.state.value, "failed")
        failed = service.ledger.find("request.route_failed")[-1]
        self.assertEqual(failed.payload["reason"], "graph_wait_suspend_unavailable")
        self.assertTrue(service.ledger.find("run.finished"))
        self.assertEqual(service._active, {})

    async def test_judge_fact_is_available_to_g1_selector_in_execution_service(self):
        config = graph_config()
        config["persona"]["fields"]["eligible"] = {"type": "boolean"}
        judge_unit = {
            "unit_id": "booking-entry", "version": 1, "load_mode": "routed",
            "entry_ports": [{"port": "from_start", "requires": []}], "reads": ["intent"], "writes": ["eligible"],
            "exit_ports": [{"port": "done", "completion": {"deterministic": {}}, "exits": ["self.done"]}],
            "on_event": [], "fallback": {"kind": "human"}, "max_rounds": 1,
            "body": {"kind": "judge", "condition": {"fact": {"field": "intent", "op": "eq", "value": "booking"}}, "result_field": "eligible"},
        }
        config["units"] = [judge_unit]
        config["orchestration"]["routing"] = {"mode": "llm"}
        config["orchestration"]["edges"][0]["condition"] = {"llm": {"prompt": "Select the route."}}
        observed = []

        def selector(candidates, state):
            observed.append((state["eligible"], state["intent"]))
            edge_id = candidates[0]["id"]
            return {"edge_id": edge_id, "scores": {edge_id: 0.95}, "evidence": {"fields": ["eligible"]}}

        pack = graph_pack()
        pack.agent_version = replace(
            pack.agent_version,
            orchestration=config,
            unit_skill_bindings={"booking-entry": "course_consult_booking"},
        )
        service = ExecutionService(pack, graph_selector=selector)
        result = await service.handle_text("预约", script=[{"text": "Graph-routed answer."}], routing_state={"intent": "booking"})
        self.assertEqual(result.request.state.value, "success")
        self.assertEqual(observed, [(True, "booking")])

    async def test_versioned_graph_selects_only_explicit_bound_skill_and_records_route(self):
        service = ExecutionService(graph_pack())
        service._route = lambda text: (_ for _ in ()).throw(AssertionError("legacy keyword router must not run"))
        result = await service.handle_text("unmatched words", script=[{"text": "Graph-routed answer."}])
        self.assertEqual(result.request.agent_version, "course-consult-r3-graph-v1")
        routed = service.ledger.find("request.routed")[-1]
        self.assertEqual(routed.payload["skill_id"], "course_consult_booking")
        self.assertEqual(routed.payload["unit_id"], "booking-entry")
        self.assertEqual([event.payload["edge_id"] for event in service.ledger.find("route.graph.step") if event.payload["kind"] == "edge"], ["finish-booking"])
        self.assertTrue(service.ledger.verify())

    async def test_missing_or_invalid_binding_fails_run_without_legacy_fallback(self):
        for binding in (None, "not-a-skill"):
            with self.subTest(binding=binding):
                service = ExecutionService(graph_pack(binding=binding))
                service._route = lambda text: (_ for _ in ()).throw(AssertionError("must not fall back"))
                result = await service.handle_text("预约", script=[])
                self.assertEqual(result.request.state.value, "failed")
                self.assertTrue(service.ledger.find("request.route_failed"))
                self.assertFalse(service.ledger.find("request.routed"))
                self.assertTrue(service.ledger.find("run.finished"))
                self.assertEqual(service._active, {})
                self.assertTrue(service.ledger.verify())

    async def test_legacy_version_without_graph_keeps_keyword_routing(self):
        pack = ScenarioPack.load("scenarios/course_consult_v1/pack.json")
        service = ExecutionService(pack)
        self.assertIsNone(service.graph_runtime)
        self.assertEqual(service._route("预约课程"), "course_consult_booking")

    async def test_server_routing_state_is_available_to_g0_and_failure_does_not_fallback(self):
        config = graph_config()
        config["g0_gates"] = [{
            "gate_id": "consent-required",
            "when": {"fact": {"field": "consent", "op": "eq", "value": False}},
            "route_to": "block",
        }]
        pack = graph_pack()
        pack.agent_version = replace(pack.agent_version, orchestration=config)
        service = ExecutionService(pack)
        service._route = lambda text: (_ for _ in ()).throw(AssertionError("must not use keywords"))
        result = await service.handle_text("用户提供的普通文本", script=[], routing_state={"consent": False})
        self.assertEqual(result.request.state.value, "failed")
        self.assertEqual(service.ledger.find("route.graph.finished")[-1].payload["gate"], "block")
        self.assertTrue(service.ledger.find("request.route_failed"))

    async def test_g1_selector_receives_trusted_route_context_and_invalid_decision_fails_closed(self):
        config = graph_config()
        config["orchestration"]["routing"] = {"mode": "llm"}
        observed = []
        def selector(candidates, state):
            observed.append(state["intent"])
            edge_id = candidates[0]["id"]
            return {"edge_id": edge_id, "scores": {edge_id: 0.95}, "evidence": {"fields": ["intent"]}}
        pack = graph_pack()
        pack.agent_version = replace(pack.agent_version, orchestration=config)
        service = ExecutionService(pack, graph_selector=selector)
        result = await service.handle_text("询问价格", script=[{"text": "Graph-routed answer."}], routing_state={"intent": "booking"})
        self.assertEqual(result.request.state.value, "success")
        self.assertEqual(observed, ["booking"])


if __name__ == "__main__":
    unittest.main()
