import unittest

from loomrise.graph_runtime import GraphRuntime, GraphRuntimeError
from loomrise.ledger import EventLedger


def unit(uid, *, body=None, completion=None):
    return {
        "unit_id": uid, "version": 1, "load_mode": "routed",
        "entry_ports": [{"port": "from_start", "requires": []}], "reads": [], "writes": [],
        "exit_ports": [{"port": "done", "completion": {"deterministic": completion or {}}, "exits": ["self.done"]}],
        "on_event": [], "fallback": {"kind": "human"}, "max_rounds": 2,
        "body": body or {"kind": "say", "text": "ok", "verbatim_reason": "fixed"},
    }


def config():
    child = unit("child")
    parent = unit("parent", body={
        "kind": "graph", "routing": {"mode": "deterministic"},
        "nodes": [{"id": "child", "unit_ref": {"unit_id": "child", "version": 1}}],
        "edges": [{"id": "child-done", "from": "child.done", "to": "self.done", "condition": {}}],
    })
    parent["entry_ports"][0]["goto"] = "child.from_start"
    return {
        "persona": {"fields": {"verified": {"type": "boolean"}}},
        "units": [parent, child], "g0_gates": [], "hard_rules": [], "task_blueprints": [],
        "orchestration": {
            "schema_version": "unit-graph-v1", "kind": "graph", "routing": {"mode": "deterministic"},
            "nodes": [{"id": "parent", "unit_ref": {"unit_id": "parent", "version": 1}}],
            "entry": "parent.from_start", "edges": [{"id": "finish", "from": "parent.done", "to": "end", "condition": {}}],
            "on_event": [], "fallback": {"kind": "human"},
        },
    }


class GraphRuntimeTests(unittest.TestCase):
    def test_llm_selector_cannot_select_an_edge_whose_deterministic_guard_failed(self):
        value = config()
        graph = value['orchestration']
        graph['routing']['mode'] = 'llm'
        graph['edges'][0]['condition'] = {'fact': {'field': 'verified', 'op': 'eq', 'value': True}}
        observed = []
        def selector(candidates, state):
            observed.extend(candidates)
            return {'edge_id': 'finish', 'scores': {'finish': 0.9}, 'evidence': {'fields': ['verified']}}
        result = GraphRuntime(value, selector=selector).route({'verified': False})
        self.assertEqual(observed, [])
        self.assertEqual(result.status, 'fallback')

    def test_model_completion_never_passes_as_an_unconditional_exit(self):
        for index in (0, 1):
            for completion in ({"llm": "user confirmed"}, {"deterministic": {}, "llm": "user confirmed"}):
                with self.subTest(index=index, completion=completion):
                    value = config()
                    value["units"][index]["exit_ports"][0]["completion"] = completion
                    with self.assertRaisesRegex(GraphRuntimeError, "completion"):
                        GraphRuntime(value).route({})

    def test_default_fallback_cannot_bypass_root_input_requirements(self):
        value = config()
        value["orchestration"]["fallback"] = {"kind": "default_unit", "target": "parent.from_start"}
        value["orchestration"]["input_fields"] = ["missing"]
        route = GraphRuntime(value).route({})
        self.assertEqual((route.status, route.fallback), ('fallback', 'human'))
        self.assertEqual(route.messages, [])

    def test_default_fallback_selects_a_local_unit_and_is_bounded(self):
        value = config()
        value['units'].append(unit('safe'))
        graph = value['orchestration']
        graph['nodes'].append({'id': 'safe', 'unit_ref': {'unit_id': 'safe', 'version': 1}})
        graph['fallback'] = {'kind': 'default_unit', 'target': 'safe.from_start'}
        graph['edges'][0]['condition'] = {'fact': {'field': 'verified', 'op': 'eq', 'value': True}}
        graph['edges'].append({'id': 'safe-end', 'from': 'safe.done', 'to': 'end', 'condition': {}})
        route = GraphRuntime(value).route({'verified': False})
        self.assertEqual(route.status, 'completed')
        self.assertEqual(route.terminal_unit_id, 'safe')
        self.assertTrue(any(step.kind == 'fallback_route' and step.target == 'safe.from_start' for step in route.steps))
        graph['edges'][-1]['condition'] = graph['edges'][0]['condition']
        route = GraphRuntime(value).route({'verified': False})
        self.assertEqual((route.status, route.fallback), ('fallback', 'human'))
        self.assertEqual(sum(step.kind == 'fallback_route' for step in route.steps), 2)

    def test_nested_default_fallback_runs_inside_its_own_layer(self):
        value = config()
        value['units'].append(unit('safe'))
        graph = value['units'][0]['body']
        graph['nodes'].append({'id': 'safe', 'unit_ref': {'unit_id': 'safe', 'version': 1}})
        graph['edges'][0]['condition'] = {'fact': {'field': 'verified', 'op': 'eq', 'value': True}}
        graph['edges'].append({'id': 'safe-exit', 'from': 'safe.done', 'to': 'self.done', 'condition': {}})
        value['units'][0]['fallback'] = {'kind': 'default_unit', 'target': 'safe.from_start'}
        route = GraphRuntime(value).route({'verified': False})
        self.assertEqual(route.status, 'completed')
        self.assertIn('safe-exit', route.selected_edges)
        self.assertTrue(any(step.kind == 'fallback_route' and step.layer == ('parent',) for step in route.steps))

    def test_nested_default_fallback_exhaustion_does_not_loop_forever(self):
        value = config()
        value['units'][0]['fallback'] = {'kind': 'default_unit', 'target': 'child.from_start'}
        value['units'][0]['body']['edges'][0]['condition'] = {'fact': {'field': 'verified', 'op': 'eq', 'value': True}}
        route = GraphRuntime(value).route({'verified': False})
        self.assertEqual((route.status, route.fallback), ('fallback', 'human'))
        self.assertEqual(sum(step.kind == 'fallback_route' for step in route.steps), 1)

    def test_default_fallback_budget_survives_wait_continuation(self):
        value = config()
        value['units'][1]['waits'] = [{'on': 'approval.received'}]
        value['units'][0]['fallback'] = {'kind': 'default_unit', 'target': 'child.from_start'}
        value['units'][0]['body']['edges'][0]['condition'] = {'fact': {'field': 'verified', 'op': 'eq', 'value': True}}
        runtime = GraphRuntime(value)
        first = runtime.route({'verified': False})
        second = runtime.route({'event': 'approval.received'}, continuation=first.continuation)
        self.assertEqual(second.status, 'waiting')
        self.assertEqual(len(second.messages), 2)
        completed = runtime.route({'event': 'approval.received'}, continuation=second.continuation)
        self.assertEqual((completed.status, completed.fallback), ('fallback', 'human'))
        self.assertEqual(len(completed.messages), 2)

    def test_parent_graph_waits_before_completing(self):
        value = config()
        value["units"][0]["waits"] = [{"on": "approval.received", "timeoutMs": 1000, "timeoutTo": "self.done"}]
        route = GraphRuntime(value).route({})
        self.assertEqual(route.status, "waiting")
        self.assertEqual(route.waiting_on, "approval.received")
        self.assertEqual(GraphRuntime(value).route({"event": "approval.received"}).status, "completed")

    def test_deep_graph_waits_are_not_skipped(self):
        value = self.recursive_graph_config()
        value["units"][1]["waits"] = [{"on": "approval.received"}]
        self.assertEqual(GraphRuntime(value).route({}).status, "waiting")

    def test_graph_timeout_may_select_only_a_local_entry(self):
        value = config()
        parent = value["units"][0]
        parent["waits"] = [{"on": "approval.received", "timeoutMs": 1000, "timeoutTo": "notice.from_start"}]
        notice = unit("notice")
        value["units"].append(notice)
        parent["body"]["nodes"].append({"id": "notice", "unit_ref": {"unit_id": "notice", "version": 1}})
        parent["body"]["edges"].append({"id": "notice-done", "from": "notice.done", "to": "self.done", "condition": {}})
        route = GraphRuntime(value).route({"__wait_timeout_to": "notice.from_start"})
        self.assertEqual(route.status, "completed")
        self.assertIn("notice-done", route.selected_edges)

    def test_say_returns_the_exact_authored_text(self):
        value = config()
        value["units"][1]["body"]["text"] = "逐字披露，不得改写。"
        route = GraphRuntime(value).route({})
        self.assertEqual([item["text"] for item in route.messages], ["逐字披露，不得改写。"])

    def test_resume_parent_wait_keeps_prior_messages_and_cycle_counts_without_replaying(self):
        value = config()
        parent = value['units'][0]
        parent['body']['edges'][0].update(to='child.from_start', max_rounds=1,
                                         exit='self.done', counter='attempt_count', window='cycle')
        parent['waits'] = [{'on': 'approval.received'}]
        runtime = GraphRuntime(value)
        parked = runtime.route({})
        self.assertEqual(parked.status, 'waiting')
        self.assertEqual(len(parked.messages), 2)
        continued = runtime.route({'event': 'approval.received'}, continuation=parked.continuation)
        self.assertEqual(continued.status, 'completed')
        self.assertEqual(continued.cycle_counters, parked.cycle_counters)
        self.assertEqual(continued.selected_edges, ['finish'])
        self.assertEqual(continued.messages, parked.messages)

    def test_sequential_waits_resume_at_the_same_atom_without_repeating_say(self):
        value = config()
        value['units'][1]['waits'] = [{'on': 'approval.received'}, {'on': 'shipping.ready'}]
        runtime = GraphRuntime(value)
        parked = runtime.route({})
        approval = runtime.route({'event': 'approval.received'}, continuation=parked.continuation)
        self.assertEqual(approval.status, 'waiting')
        self.assertEqual(approval.waiting_on, 'shipping.ready')
        completed = runtime.route({'event': 'shipping.ready'}, continuation=approval.continuation)
        self.assertEqual(completed.status, 'completed')
        self.assertEqual([item['text'] for item in completed.messages], ['ok'])

    def test_each_loop_visit_requires_a_new_wake_and_executes_its_atom_once(self):
        value = config()
        value['units'][1]['waits'] = [{'on': 'approval.received'}]
        value['units'][0]['body']['edges'][0].update(
            to='child.from_start', max_rounds=1, exit='self.done', counter='attempt_count', window='cycle')
        runtime = GraphRuntime(value)
        first = runtime.route({})
        second = runtime.route({'event': 'approval.received'}, continuation=first.continuation)
        self.assertEqual(second.status, 'waiting')
        self.assertEqual(second.cycle_counters['["parent","child-done"]'], 1)
        self.assertEqual(len(second.messages), 2)
        completed = runtime.route({'event': 'approval.received'}, continuation=second.continuation)
        self.assertEqual(completed.status, 'completed')
        self.assertEqual(len(completed.messages), 2)

    def test_timeout_continuation_does_not_reuse_a_previous_event(self):
        value = config()
        value['units'][1]['waits'] = [{'on': 'approval.received'}, {'on': 'shipping.ready', 'timeoutMs': 1, 'timeoutTo': 'self.done'}]
        value['orchestration']['edges'][0]['condition'] = {'fact': {'field': 'event', 'op': 'eq', 'value': 'approval.received'}}
        runtime = GraphRuntime(value)
        parked = runtime.route({'event': 'handoff'})
        approved = runtime.route({'event': 'approval.received'}, continuation=parked.continuation)
        timed_out = runtime.route({'__wait_timeout_to': 'self.done'}, continuation=approved.continuation)
        self.assertEqual(timed_out.status, 'fallback')

    def test_runtime_rejects_an_unroutable_timeout_before_parking(self):
        value = config()
        value['units'][1]['waits'] = [{'on': 'approval.received', 'timeoutMs': 1}]
        with self.assertRaisesRegex(GraphRuntimeError, 'timeout'):
            GraphRuntime(value).route({})

    def test_list_negation_matches_shared_validation_in_edges_and_judge(self):
        for operator in ("not", "none_of"):
            for verified in (True, False):
                with self.subTest(operator=operator, verified=verified):
                    value = config()
                    value["orchestration"]["edges"][0]["condition"] = {
                        operator: [{"fact": {"field": "verified", "op": "eq", "value": True}}],
                    }
                    result = GraphRuntime(value).route({"verified": verified})
                    self.assertEqual(result.status, "fallback" if verified else "completed")
                    judge = self.judge_config()
                    judge["units"][-1]["body"]["condition"] = value["orchestration"]["edges"][0]["condition"]
                    result = GraphRuntime(judge).route({"verified": verified})
                    self.assertEqual(result.selected_edges, ["no" if verified else "yes"])

    def test_unsupported_predicates_cannot_become_true_through_negation_or_disjunction(self):
        unsupported = [
            {'state': {'metric': 'runs', 'window': '24h', 'op': 'eq', 'value': 1, 'future': True}},
            {"event": {"event": "tool_call", "tool": "approved_tool"}},
            {"fact": {"field": "verified", "op": "changed_to", "value": True}},
            {"fact": {"field": "verified", "op": "in", "value": "not-a-list"}},
            {"fact": {"field": "verified", "op": "gt", "value": True}},
            {"future_predicate": True}, None,
        ]
        for predicate in unsupported:
            for wrapped in (predicate, {"none_of": [predicate]}, {"any_of": [{}, predicate]}):
                with self.subTest(condition=wrapped):
                    value = config()
                    value["orchestration"]["edges"][0]["condition"] = wrapped
                    with self.assertRaises(GraphRuntimeError):
                        GraphRuntime(value).route({"verified": True, "event": "tool_call"})

    def test_model_predicates_require_selection_and_cannot_be_negated_as_booleans(self):
        for condition in ({"llm": {"prompt": "choose"}}, {"none_of": [{"llm": {"prompt": "choose"}}]}):
            value = config()
            value["orchestration"]["edges"][0]["condition"] = condition
            with self.assertRaises(GraphRuntimeError):
                GraphRuntime(value).route({})
        value["orchestration"]["routing"]["mode"] = "hybrid"
        with self.assertRaises(GraphRuntimeError):
            GraphRuntime(value).route({})

    def test_invalid_model_edge_leaves_fail_before_selector_runs(self):
        for payload in (None, True, 42, [], "", {}, {"prompt": " "},
                        {"prompt_ref": "latest"}, {"prompt": "choose", "future": True}):
            with self.subTest(payload=payload):
                value = config()
                value["orchestration"]["routing"]["mode"] = "hybrid"
                value["orchestration"]["edges"][0]["condition"] = {"llm": payload}
                observed = []
                with self.assertRaisesRegex(GraphRuntimeError, "model condition"):
                    GraphRuntime(value, selector=lambda *args: observed.append(args)).route({})
                self.assertEqual(observed, [])

    def test_event_name_predicates_match_only_current_route_event(self):
        for name in ("timeout", "tool_call", "human_takeover"):
            value = config()
            value["orchestration"]["edges"][0]["condition"] = {
                "all_of": [{"event": {"event": name}}, {"not": [{"fact": {"field": "blocked", "op": "exists"}}]}],
            }
            self.assertEqual(GraphRuntime(value).route({"event": name}).status, "completed")
            self.assertEqual(GraphRuntime(value).route({"event": "different"}).status, "fallback")
            self.assertEqual(GraphRuntime(value).route({"event": name, "blocked": True}).status, "fallback")

    def test_event_attribute_predicates_match_the_declared_event_envelope(self):
        value = config()
        value["orchestration"]["edges"][0]["condition"] = {
            "event": {"event": "tool_call", "attributes": {"tool_id": "lookup"}},
        }
        self.assertEqual(GraphRuntime(value).route({"event": "tool_call", "event_attributes": {"tool_id": "lookup"}}).status, "completed")
        self.assertEqual(GraphRuntime(value).route({"event": "tool_call", "event_attributes": {"tool_id": "other"}}).status, "fallback")

    def test_missing_event_attribute_is_not_an_explicit_null_and_malformed_envelope_fails(self):
        value = config()
        value['orchestration']['edges'][0]['condition'] = {'event': {'event': 'timeout', 'attributes': {'reason': None}}}
        self.assertEqual(GraphRuntime(value).route({'event': 'timeout'}).status, 'fallback')
        self.assertEqual(GraphRuntime(value).route({'event': 'timeout', 'event_attributes': {'reason': None}}).status, 'completed')
        with self.assertRaises(GraphRuntimeError):
            GraphRuntime(value).route({'event': 'timeout', 'event_attributes': None})

    def test_unsupported_conditions_stop_gates_events_and_completion_without_becoming_booleans(self):
        predicate = {"none_of": [{"state": {"metric": "attempts", "window": "invalid", "op": "gt", "value": 2}}]}
        for surface in ("gate", "event", "completion"):
            with self.subTest(surface=surface):
                value = config()
                if surface == "gate":
                    value["g0_gates"] = [{"gate_id": "blocked", "when": predicate, "route_to": "block"}]
                elif surface == "event":
                    value["orchestration"]["on_event"] = [{"event": "timeout", "goto": "parent", "scope": "global", "when": predicate}]
                else:
                    value["units"][0]["exit_ports"][0]["completion"]["deterministic"] = predicate
                with self.assertRaises(GraphRuntimeError):
                    GraphRuntime(value).route({"event": "timeout"})

    def test_between_fact_condition_uses_an_inclusive_numeric_range(self):
        value = config()
        value["orchestration"]["edges"][0]["condition"] = {
            "fact": {"field": "score", "op": "between", "value": [1, 3]},
        }
        self.assertEqual(GraphRuntime(value).route({"score": 1}).status, "completed")
        self.assertEqual(GraphRuntime(value).route({"score": 3}).status, "completed")
        self.assertEqual(GraphRuntime(value).route({"score": 0}).status, "fallback")
        self.assertEqual(GraphRuntime(value).route({"score": True}).status, "fallback")
        for bounds in ([1], [True, 2], [2, 1], [1, float("inf")], [1, "2"]):
            with self.subTest(bounds=bounds):
                value["orchestration"]["edges"][0]["condition"]["fact"]["value"] = bounds
                with self.assertRaises(GraphRuntimeError):
                    GraphRuntime(value).route({"score": 2})

    def test_matches_fact_condition_uses_bounded_string_regex_search(self):
        value = config()
        value['orchestration']['edges'][0]['condition'] = {
            'fact': {'field': 'order_code', 'op': 'matches', 'value': '^ORD-[0-9]{8}$'},
        }
        self.assertEqual(GraphRuntime(value).route({'order_code': 'ORD-12345678'}).status, 'completed')
        self.assertEqual(GraphRuntime(value).route({'order_code': 'xORD-12345678'}).status, 'fallback')
        self.assertEqual(GraphRuntime(value).route({'order_code': 12345678}).status, 'fallback')
        self.assertEqual(GraphRuntime(value).route({'order_code': 'x' * 1025}).status, 'fallback')
        value['orchestration']['edges'][0]['condition']['fact']['value'] = 'refund'
        self.assertEqual(GraphRuntime(value).route({'order_code': 'Please refund the order'}).status, 'completed')

    def test_matches_rejects_unsafe_regex_before_running(self):
        value = config()
        value['orchestration']['edges'][0]['condition'] = {
            'fact': {'field': 'order_code', 'op': 'matches', 'value': '(a|aa)+'},
        }
        with self.assertRaisesRegex(GraphRuntimeError, 'matches'):
            GraphRuntime(value).route({'order_code': 'a' * 1024})

    def test_durable_state_window_predicate_uses_metric_specific_counts(self):
        value = config()
        value['orchestration']['edges'][0]['condition'] = {'state': {'metric': 'attempts', 'window': '24h', 'op': 'gt', 'value': 2}}
        counts = {'attempts': {'24h': 3, 'forever': 4}, 'runs': {'24h': 1, 'forever': 2}}
        self.assertEqual(GraphRuntime(value).route({'state_window_counts': counts}).status, 'completed')
        self.assertEqual(GraphRuntime(value).route({'state_window_counts': {**counts, 'attempts': {'24h': 2}}}).status, 'fallback')

    def test_cycle_state_window_requires_a_service_cycle_and_fails_closed_without_it(self):
        value = config()
        value['orchestration']['edges'][0]['condition'] = {
            'state': {'metric': 'runs', 'window': 'cycle', 'op': 'eq', 'value': 2},
        }
        runtime = GraphRuntime(value)
        self.assertTrue(runtime.requires_service_cycle())
        with self.assertRaisesRegex(GraphRuntimeError, 'cycle'):
            runtime.route({'state_window_counts': {'runs': {'24h': 2, 'forever': 2}}})
        result = runtime.route({'state_window_counts': {'runs': {'cycle': 2}}})
        self.assertEqual(result.status, 'completed')

    def test_cycle_window_dependency_is_limited_to_executable_condition_surfaces(self):
        value = config()
        value['units'][0]['exit_ports'][0]['completion']['deterministic'] = {
            'state': {'metric': 'runs', 'window': 'cycle', 'op': 'gt', 'value': 0},
        }
        self.assertTrue(GraphRuntime(value).requires_service_cycle())

        value['units'][0]['exit_ports'][0]['completion']['deterministic'] = {}
        value['task_blueprints'] = [{'notes': {'state': {'window': 'cycle'}}}]
        self.assertFalse(GraphRuntime(value).requires_service_cycle())

    def recursive_graph_config(self):
        value = config()
        child = value["units"][1]
        leaf = unit("leaf")
        child["body"] = {
            "kind": "graph", "routing": {"mode": "deterministic"},
            "nodes": [{"id": "leaf", "unit_ref": {"unit_id": "leaf", "version": 1}}],
            "edges": [{"id": "leaf-done", "from": "leaf.done", "to": "self.done", "condition": {}}],
        }
        child["entry_ports"][0]["goto"] = "leaf.from_start"
        value["units"].append(leaf)
        return value

    def judge_config(self):
        value = config()
        value["persona"]["fields"]["eligible"] = {"type": "boolean"}
        value["units"].append(unit("judge", body={
            "kind": "judge",
            "condition": {"fact": {"field": "verified", "op": "eq", "value": True}},
            "result_field": "eligible",
        }))
        value["units"][-1]["writes"] = ["eligible"]
        value["orchestration"].update({
            "nodes": [{"id": "check", "unit_ref": {"unit_id": "judge", "version": 1}}],
            "entry": "check.from_start",
            "edges": [
                {"id": "yes", "from": "check.done", "to": "end", "condition": {"fact": {"field": "eligible", "op": "eq", "value": True}}},
                {"id": "no", "from": "check.done", "to": "end", "condition": {"fact": {"field": "eligible", "op": "eq", "value": False}}},
            ],
        })
        return value

    def test_judge_writes_declared_boolean_for_downstream_edge_conditions(self):
        value = self.judge_config()
        source = {"verified": True}
        result = GraphRuntime(value).route(source)
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.selected_edges, ["yes"])
        self.assertEqual(result.steps[1].kind, "judge")
        self.assertEqual(result.steps[1].target, "eligible=true")
        self.assertEqual(source, {"verified": True})

        result = GraphRuntime(value).route({"verified": False})
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.selected_edges, ["no"])
        self.assertEqual(result.steps[1].target, "eligible=false")

    def test_judge_fails_closed_when_result_field_is_not_declared_for_write(self):
        value = self.judge_config()
        value["units"][-1]["writes"] = []
        result = GraphRuntime(value).route({"verified": True})
        self.assertEqual(result.status, "fallback")
        self.assertEqual(result.fallback, "human")
        self.assertFalse(any(step.kind == "judge" for step in result.steps))

    def test_judge_fails_closed_for_non_deterministic_condition_even_if_validation_was_bypassed(self):
        value = self.judge_config()
        value["units"][-1]["body"]["condition"] = {"llm": {"prompt": "decide"}}
        result = GraphRuntime(value).route({"verified": True})
        self.assertEqual(result.status, "fallback")
        self.assertFalse(any(step.kind == "judge" for step in result.steps))

    def test_nested_judge_fact_is_available_after_returning_to_parent_graph(self):
        value = self.judge_config()
        judge_unit = value["units"][-1]
        parent = value["units"][0]
        parent["body"] = {
            "kind": "graph", "routing": {"mode": "deterministic"},
            "nodes": [{"id": "check", "unit_ref": {"unit_id": "judge", "version": 1}}],
            "edges": [
                {"id": "nested-yes", "from": "check.done", "to": "self.done", "condition": {"fact": {"field": "eligible", "op": "eq", "value": True}}},
                {"id": "nested-no", "from": "check.done", "to": "self.done", "condition": {"fact": {"field": "eligible", "op": "eq", "value": False}}},
            ],
        }
        parent["entry_ports"][0]["goto"] = "check.from_start"
        value["orchestration"]["nodes"] = [{"id": "parent", "unit_ref": {"unit_id": "parent", "version": 1}}]
        value["orchestration"]["entry"] = "parent.from_start"
        value["orchestration"]["edges"] = [
            {"id": "parent-yes", "from": "parent.done", "to": "end", "condition": {"fact": {"field": "eligible", "op": "eq", "value": True}}},
            {"id": "parent-no", "from": "parent.done", "to": "end", "condition": {"fact": {"field": "eligible", "op": "eq", "value": False}}},
        ]
        result = GraphRuntime(value).route({"verified": True})
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.selected_edges, ["nested-yes", "parent-yes"])
        self.assertTrue(any(step.kind == "judge" and step.layer == ("parent",) for step in result.steps))

    def test_judge_does_not_replace_unrelated_state_fields(self):
        value = self.judge_config()
        source = {"verified": True, "eligible": "untrusted", "other": 12}
        result = GraphRuntime(value).route(source)
        self.assertEqual(result.selected_edges, ["yes"])
        self.assertEqual(source, {"verified": True, "eligible": "untrusted", "other": 12})

    def test_wait_returns_without_claiming_completion_until_event_arrives(self):
        value = config()
        value["units"][1]["waits"] = [{"on": "approval.received", "timeoutMs": 120000, "timeoutTo": "handoff"}]
        waiting = GraphRuntime(value).route({})
        self.assertEqual(waiting.status, "waiting")
        self.assertEqual(waiting.waiting_on, "approval.received")
        self.assertEqual(waiting.wait_timeout_ms, 120000)
        self.assertIsNone(waiting.terminal_target)

        resumed = GraphRuntime(value).route({"event": "approval.received"})
        self.assertEqual(resumed.status, "completed")
        self.assertIsNone(resumed.waiting_on)

    def test_wait_timeout_branch_is_explicit_and_can_complete(self):
        value = config()
        value["units"][1]["waits"] = [{"on": "approval.received", "timeoutMs": 0, "timeoutTo": "self.done"}]
        timed = GraphRuntime(value).route({"__wait_timeout_to": "self.done"})
        self.assertEqual(timed.status, "completed")
        self.assertEqual(timed.terminal_target, "parent.done")
        self.assertTrue(any(step.kind == "wait_timeout" for step in timed.steps))

    def test_say_atom_requires_verbatim_reason(self):
        value = config()
        value["units"][1]["body"] = {"kind": "say", "text": "固定话术"}
        self.assertEqual(GraphRuntime(value).route({}).status, "fallback")

    def test_bounded_cycle_exposes_stable_counter_and_accepts_previous_snapshot(self):
        value = config()
        value["persona"]["fields"]["attempt_count"] = {"type": "integer"}
        value["units"][0]["writes"] = ["attempt_count"]
        value["orchestration"]["edges"] = [
            {"id": "retry", "from": "parent.done", "to": "parent.from_start", "condition": {},
             "max_rounds": 2, "exit": "end", "counter": "attempt_count", "window": "cycle"},
        ]
        first = GraphRuntime(value).route({})
        self.assertEqual(first.status, "completed")
        self.assertEqual(first.cycle_counters['["retry"]'], 3)
        self.assertEqual(first.cycle_events[-1]["count"], 3)
        resumed = GraphRuntime(value).route({}, cycle_counters=first.cycle_counters)
        self.assertEqual(resumed.status, "completed")
        self.assertEqual(resumed.cycle_counters['["retry"]'], 4)

    def test_invalid_cycle_counter_snapshot_fails_closed(self):
        with self.assertRaises(GraphRuntimeError):
            GraphRuntime(config()).route({}, cycle_counters={"bad": -1})

    def test_root_input_fields_and_entry_requires_are_enforced_at_runtime(self):
        value = config()
        value["orchestration"]["input_fields"] = ["verified"]
        self.assertEqual(GraphRuntime(value).route({}).status, "fallback")
        self.assertEqual(GraphRuntime(value).route({"verified": None}).status, "fallback")
        result = GraphRuntime(value).route({"verified": False})
        self.assertEqual(result.status, "completed")

        value["orchestration"]["input_fields"] = []
        value["units"][1]["entry_ports"][0]["requires"] = ["verified"]
        self.assertEqual(GraphRuntime(value).route({}).status, "fallback")
        self.assertEqual(GraphRuntime(value).route({"verified": True}).status, "completed")

    def test_nested_entry_requires_are_enforced_and_audited(self):
        value = config()
        value["units"][1]["entry_ports"][0]["requires"] = ["verified"]
        missing = GraphRuntime(value).route({})
        self.assertEqual(missing.status, "fallback")
        self.assertTrue(any(step.kind == "requires_failed" for step in missing.steps))
        ready = GraphRuntime(value).route({"verified": False})
        self.assertEqual(ready.status, "completed")

    def test_nested_route_returns_auditable_trace_without_side_effect_claim(self):
        result = GraphRuntime(config()).route({})
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.selected_edges, ["child-done", "finish"])
        self.assertEqual([step.kind for step in result.steps], ["enter", "enter", "edge", "edge"])
        self.assertNotIn("business_completed", result.warnings)

    def test_g0_precedes_graph_edges(self):
        value = config()
        value["g0_gates"] = [{"gate_id": "stop", "when": {"fact": {"field": "verified", "op": "eq", "value": False}}, "route_to": "human"}]
        result = GraphRuntime(value).route({"verified": False})
        self.assertEqual(result.status, "gated")
        self.assertEqual(result.gate, "human")
        self.assertEqual(result.selected_edges, [])

    def test_boundary_event_precedes_edges_but_g0_still_wins(self):
        value = config()
        value["orchestration"]["on_event"] = [{"event": "handoff", "scope": "global", "goto": "parent"}]
        result = GraphRuntime(value).route({"event": "handoff"})
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.steps[0].kind, "event")
        value["g0_gates"] = [{"gate_id": "deny", "when": {"fact": {"field": "blocked", "op": "exists"}}, "route_to": "human"}]
        gated = GraphRuntime(value).route({"event": "handoff", "blocked": True})
        self.assertEqual(gated.steps[0].kind, "g0")

    def test_unit_self_event_short_circuits_atom_and_selects_declared_exit(self):
        value = config()
        child = value["units"][1]
        child["waits"] = [{"on": "approval.received"}]
        child["on_event"] = [{"event": "handoff", "scope": "self", "goto": "self.done"}]
        value["orchestration"].update({
            "nodes": [{"id": "child", "unit_ref": {"unit_id": "child", "version": 1}}],
            "entry": "child.from_start",
            "edges": [{"id": "child-finish", "from": "child.done", "to": "end", "condition": {}}],
        })

        result = GraphRuntime(value).route({"event": "handoff"})

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.selected_edges, ["child-finish"])
        event_step = next(step for step in result.steps if step.kind == "event")
        self.assertEqual(event_step.target, "self.done")
        self.assertEqual(event_step.layer, ())
        self.assertIsNone(result.waiting_on)

    def test_unit_self_event_when_false_does_not_interrupt_atom(self):
        value = config()
        child = value["units"][1]
        child["waits"] = [{"on": "approval.received"}]
        child["on_event"] = [{
            "event": "handoff", "scope": "self", "goto": "self.done",
            "when": {"fact": {"field": "approved", "op": "eq", "value": True}},
        }]
        value["orchestration"].update({
            "nodes": [{"id": "child", "unit_ref": {"unit_id": "child", "version": 1}}],
            "entry": "child.from_start",
            "edges": [{"id": "child-finish", "from": "child.done", "to": "end", "condition": {}}],
        })

        result = GraphRuntime(value).route({"event": "handoff", "approved": False})

        self.assertEqual(result.status, "waiting")
        self.assertEqual(result.waiting_on, "approval.received")
        self.assertFalse(any(step.kind == "event" for step in result.steps))

    def test_global_event_precedes_unit_self_event(self):
        value = config()
        child = value["units"][1]
        child["on_event"] = [{"event": "handoff", "scope": "self", "goto": "self.done"}]
        alternate = unit("alternate")
        value["units"].append(alternate)
        value["orchestration"].update({
            "on_event": [{"event": "handoff", "scope": "global", "goto": "alternate"}],
            "nodes": [
                {"id": "parent", "unit_ref": {"unit_id": "parent", "version": 1}},
                {"id": "alternate", "unit_ref": {"unit_id": "alternate", "version": 1}},
            ],
            "edges": [{"id": "alternate-finish", "from": "alternate.done", "to": "end", "condition": {}}],
        })

        result = GraphRuntime(value).route({"event": "handoff"})

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.selected_edges, ["alternate-finish"])
        self.assertEqual(result.steps[0].target, "alternate")

    def test_nested_unit_self_event_is_traced_at_its_layer(self):
        value = config()
        child = value["units"][1]
        child["waits"] = [{"on": "approval.received"}]
        child["on_event"] = [{"event": "handoff", "scope": "self", "goto": "self.done"}]

        result = GraphRuntime(value).route({"event": "handoff"})

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.selected_edges, ["child-done", "finish"])
        event_step = next(step for step in result.steps if step.kind == "event")
        self.assertEqual(event_step.layer, ("parent",))
        self.assertIsNone(result.waiting_on)

    def test_nested_graph_units_execute_recursively(self):
        result = GraphRuntime(self.recursive_graph_config()).route({})

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.selected_edges, ["leaf-done", "child-done", "finish"])
        self.assertTrue(any(step.target == "leaf.from_start" and step.layer == ("parent", "child")
                            for step in result.steps))

    def test_subtree_event_interrupts_at_descendant_unit_boundary(self):
        value = self.recursive_graph_config()
        parent = value["units"][0]
        leaf = value["units"][2]
        leaf["waits"] = [{"on": "approval.received"}]
        parent["on_event"] = [{"event": "handoff", "scope": "subtree", "goto": "self.done"}]

        result = GraphRuntime(value).route({"event": "handoff"})

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.selected_edges, ["finish"])
        event_step = next(step for step in result.steps if step.kind == "event")
        self.assertEqual(event_step.reason, "Unit subtree boundary event matched")
        self.assertEqual(event_step.layer, ("parent",))
        self.assertFalse(any(step.target == "leaf.from_start" for step in result.steps))

    def test_nested_subtree_event_interrupts_deep_atom_and_preserves_layer(self):
        value = self.recursive_graph_config()
        child = value["units"][1]
        leaf = value["units"][2]
        leaf["waits"] = [{"on": "approval.received"}]
        child["on_event"] = [{"event": "handoff", "scope": "subtree", "goto": "self.done"}]

        result = GraphRuntime(value).route({"event": "handoff"})

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.selected_edges, ["child-done", "finish"])
        event_step = next(step for step in result.steps if step.kind == "event")
        self.assertEqual(event_step.layer, ("parent", "child"))
        self.assertIsNone(result.waiting_on)

    def test_subtree_event_can_reroute_to_a_sibling_in_its_declaring_graph(self):
        value = self.recursive_graph_config()
        parent = value["units"][0]
        sibling = unit("sibling")
        value["units"].append(sibling)
        parent["on_event"] = [{"event": "handoff", "scope": "subtree", "goto": "sibling.from_start"}]
        parent["body"]["nodes"].append({"id": "sibling", "unit_ref": {"unit_id": "sibling", "version": 1}})
        parent["body"]["edges"].append({
            "id": "sibling-done", "from": "sibling.done", "to": "self.done", "condition": {},
        })

        result = GraphRuntime(value).route({"event": "handoff"})

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.selected_edges, ["sibling-done", "finish"])
        self.assertFalse(any(step.target == "leaf.from_start" for step in result.steps))

    def test_subtree_event_is_rechecked_after_deep_state_changes_and_bubbles_to_owner(self):
        value = self.recursive_graph_config()
        parent, child, leaf = value["units"]
        sibling = unit("sibling")
        pause = unit("pause")
        pause["waits"] = [{"on": "approval.received"}]
        value["units"].extend([sibling, pause])
        value["persona"]["fields"].update({
            "trigger": {"type": "boolean"}, "ready": {"type": "boolean"},
        })
        leaf["reads"] = ["trigger"]
        leaf["writes"] = ["ready"]
        leaf["body"] = {
            "kind": "judge", "condition": {"fact": {"field": "trigger", "op": "eq", "value": True}},
            "result_field": "ready",
        }
        child["body"]["nodes"].append({"id": "pause", "unit_ref": {"unit_id": "pause", "version": 1}})
        child["body"]["edges"] = [
            {"id": "leaf-next", "from": "leaf.done", "to": "pause.from_start", "condition": {}},
            {"id": "pause-done", "from": "pause.done", "to": "self.done", "condition": {}},
        ]
        parent["on_event"] = [{
            "event": "handoff", "scope": "subtree", "goto": "sibling.from_start",
            "when": {"fact": {"field": "ready", "op": "eq", "value": True}},
        }]
        parent["body"]["nodes"].append({"id": "sibling", "unit_ref": {"unit_id": "sibling", "version": 1}})
        parent["body"]["edges"].append({
            "id": "sibling-done", "from": "sibling.done", "to": "self.done", "condition": {},
        })

        result = GraphRuntime(value).route({"event": "handoff", "trigger": True})

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.selected_edges, ["leaf-next", "sibling-done", "finish"])
        event_step = next(step for step in result.steps if step.kind == "event")
        self.assertEqual(event_step.target, "sibling.from_start")
        self.assertEqual(event_step.layer, ("parent", "child"))

    def test_nested_graph_exit_requires_its_declared_completion(self):
        value = self.recursive_graph_config()
        child = value["units"][1]
        child["exit_ports"][0]["completion"]["deterministic"] = {
            "fact": {"field": "ready", "op": "eq", "value": True},
        }

        result = GraphRuntime(value).route({})

        self.assertEqual(result.status, "fallback")
        self.assertTrue(any(step.kind == "completion_failed" and step.target == "child.done"
                            for step in result.steps))

    def test_unit_self_event_cannot_bypass_exit_completion(self):
        value = config()
        child = value["units"][1]
        child["on_event"] = [{"event": "handoff", "scope": "self", "goto": "self.done"}]
        child["exit_ports"][0]["completion"]["deterministic"] = {
            "fact": {"field": "ready", "op": "eq", "value": True},
        }

        result = GraphRuntime(value).route({"event": "handoff"})

        self.assertEqual(result.status, "fallback")
        self.assertTrue(any(step.kind == "completion_failed" and step.target == "child.done"
                            for step in result.steps))

    def test_llm_selector_is_closed_set_and_unknown_conditions_fallback(self):
        value = config()
        value["orchestration"]["routing"] = {"mode": "hybrid"}
        value["orchestration"]["edges"][0]["condition"] = {"llm": {"prompt": "choose"}}
        decision = lambda candidates, state: {"edge_id": candidates[0]["id"], "scores": {candidates[0]["id"]: 0.9}, "evidence": {"utterance": "退款"}}
        result = GraphRuntime(value, selector=decision).route({"recent_turns": ["我要申请退款"]})
        self.assertEqual(result.status, "completed")
        self.assertTrue(any("validated margin and evidence" in warning for warning in result.warnings))
        no_selector = GraphRuntime(value).route({})
        self.assertEqual(no_selector.status, "fallback")

    def test_g1_rejects_low_margin_missing_evidence_and_out_of_set_choices(self):
        value = config()
        value["orchestration"]["routing"] = {"mode": "llm"}
        value["orchestration"]["edges"].append({"id": "other", "from": "parent.done", "to": "end", "condition": {}})
        cases = [
            {"edge_id": "finish", "scores": {"finish": 0.55, "other": 0.45}, "evidence": {"utterance": "退款"}},
            {"edge_id": "finish", "scores": {"finish": 0.9, "other": 0.1}},
            {"edge_id": "outside", "scores": {"finish": 0.9, "other": 0.1}, "evidence": {"utterance": "退款"}},
        ]
        for decision in cases:
            result = GraphRuntime(value, selector=lambda candidates, state, d=decision: d).route({"recent_turns": ["我要申请退款"]})
            self.assertEqual(result.status, "fallback")
            self.assertTrue(any("G1 rejected" in warning for warning in result.warnings))

    def test_exact_unit_version_is_required(self):
        value = config()
        value["orchestration"]["nodes"][0]["unit_ref"]["version"] = 2
        result = GraphRuntime(value).route({})
        self.assertEqual(result.status, "fallback")
        with self.assertRaises(GraphRuntimeError):
            GraphRuntime({})

    def test_route_trace_uses_run_scoped_event_emitter_and_hash_chain(self):
        ledger = EventLedger()
        def emit(event_type, **payload):
            return ledger.emit(event_type, request_id="request-a", run_id="run-a", tenant_id="tenant-a",
                               agent_version="v-r3", channel="text", **payload)
        result = GraphRuntime(config()).route_and_emit({}, emit)
        self.assertEqual(result.status, "completed")
        events = [event for event in ledger.find("route.graph.step") if event.payload["kind"] == "edge"]
        self.assertEqual([event.payload["edge_id"] for event in events], ["child-done", "finish"])
        self.assertEqual(ledger.events[0].event_type, "route.graph.started")
        self.assertEqual(ledger.events[-1].event_type, "route.graph.finished")
        finished = ledger.find("route.graph.finished")[-1].payload
        terminal = finished["terminal_node"]
        terminal_step = ledger.find("route.graph.step")[terminal["step_index"]].payload
        self.assertEqual(finished["telemetry_schema_version"], "graph-telemetry-v1")
        self.assertEqual(terminal["layer"], [])
        self.assertEqual(terminal_step["kind"], terminal["evidence_kind"])
        self.assertEqual(terminal_step["target"], "end")
        self.assertEqual(terminal_step["source"], f"{terminal['node_id']}.{terminal['exit_port']}")
        self.assertEqual(terminal_step["unit_id"], terminal["unit_id"])
        self.assertTrue(finished["node_dwell_samples"])
        self.assertTrue(ledger.verify())
        self.assertNotIn("result_id", ledger.events[-1].payload)

    def test_tool_atom_fails_closed_with_explicit_r4_boundary_diagnostic(self):
        value = config()
        value["tools"] = [{
            "tool_id": "create_booking",
            "version": "1.0.0",
            "business_meaning": "创建一条模拟预约",
            "side_effect_level": "mock_write",
            "idempotent": True,
            "requires_confirm": True,
            "timeout_ms": 3000,
            "result_id_required": True,
        }]
        value["units"][1]["body"] = {
            "kind": "tool",
            "tool_ref": {"tool_id": "create_booking", "version": "1.0.0"},
            "arguments": {
                "course_id": "data-analysis-101",
                "idempotency_key": "booking-1",
            },
        }

        result = GraphRuntime(value).route({})

        self.assertEqual(result.status, "fallback")
        rejected = [step for step in result.steps if step.kind == "tool_rejected"]
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0].target, "create_booking@1.0.0")
        self.assertEqual(rejected[0].reason, "tool_atom_runtime_unavailable")
        self.assertEqual(len(result.diagnostics), 1)
        self.assertEqual(result.diagnostics[0]["code"], "tool_atom_runtime_unavailable")
        self.assertEqual(
            result.diagnostics[0]["blocked_capabilities"],
            [
                "tool_policy",
                "argument_schema",
                "confirmation",
                "idempotency",
                "unknown_result_reconciliation",
            ],
        )

    def test_tool_atom_boundary_diagnostic_is_emitted_without_business_result(self):
        value = config()
        value["tools"] = [{
            "tool_id": "lookup",
            "version": "2.0.0",
            "business_meaning": "读取受限业务资料",
            "side_effect_level": "read_only",
            "idempotent": True,
            "requires_confirm": False,
            "timeout_ms": 1000,
            "result_id_required": False,
        }]
        value["units"][1]["body"] = {
            "kind": "tool",
            "tool_ref": {"tool_id": "lookup", "version": "2.0.0"},
            "arguments": {"query": "退款"},
        }
        ledger = EventLedger()

        def emit(event_type, **payload):
            return ledger.emit(
                event_type,
                request_id="request-tool",
                run_id="run-tool",
                tenant_id="tenant-a",
                agent_version="v-r3",
                channel="text",
                **payload,
            )

        result = GraphRuntime(value).route_and_emit({}, emit)

        self.assertEqual(result.status, "fallback")
        diagnostics = ledger.find("route.graph.diagnostic")
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(diagnostics[0].payload["code"], "tool_atom_runtime_unavailable")
        self.assertEqual(diagnostics[0].payload["tool_id"], "lookup")
        self.assertNotIn("result_id", diagnostics[0].payload)
        self.assertNotIn("result_id", ledger.find("route.graph.finished")[-1].payload)
        self.assertTrue(ledger.verify())

    def test_tool_atom_rejects_malformed_manifest_before_r4_runtime_diagnostic(self):
        value = config()
        value["tools"] = [{
            "tool_id": "lookup",
            "version": "2.0.0",
            # Missing required ToolManifest fields is a malformed registry
            # entry even when tool_ref itself is exact.
        }]
        value["units"][1]["body"] = {
            "kind": "tool",
            "tool_ref": {"tool_id": "lookup", "version": "2.0.0"},
            "arguments": {"query": "退款"},
        }

        result = GraphRuntime(value).route({})

        self.assertEqual(result.status, "fallback")
        self.assertEqual(result.diagnostics[0]["code"], "tool_atom_invalid_manifest")
        self.assertIn("requires_confirm", result.diagnostics[0]["reason"])

    def test_tool_atom_rejects_non_object_arguments_before_r4_runtime_diagnostic(self):
        value = config()
        value["tools"] = [{
            "tool_id": "lookup",
            "version": "2.0.0",
            "business_meaning": "读取受限业务资料",
            "side_effect_level": "read_only",
            "idempotent": True,
            "requires_confirm": False,
            "timeout_ms": 1000,
            "result_id_required": False,
        }]
        value["units"][1]["body"] = {
            "kind": "tool",
            "tool_ref": {"tool_id": "lookup", "version": "2.0.0"},
            "arguments": ["not", "an", "object"],
        }

        result = GraphRuntime(value).route({})

        self.assertEqual(result.status, "fallback")
        self.assertEqual(result.diagnostics[0]["code"], "tool_atom_invalid_arguments")

    def test_cycle_counter_transitions_are_run_events(self):
        value = config()
        value["persona"]["fields"]["attempt_count"] = {"type": "integer"}
        value["units"][0]["writes"] = ["attempt_count"]
        value["orchestration"]["edges"] = [
            {"id": "retry", "from": "parent.done", "to": "parent.from_start", "condition": {},
             "max_rounds": 1, "exit": "end", "counter": "attempt_count", "window": "cycle"},
        ]
        ledger = EventLedger()
        def emit(event_type, **payload):
            return ledger.emit(event_type, request_id="request-a", run_id="run-cycle", tenant_id="tenant-a",
                               agent_version="v-r3", channel="text", **payload)
        result = GraphRuntime(value).route_and_emit({}, emit)
        transitions = ledger.find("route.graph.cycle")
        self.assertEqual([event.payload["cycle_count"] for event in transitions], [1, 2])
        self.assertEqual(result.cycle_counters['["retry"]'], 2)
        finished = ledger.find("route.graph.finished")[-1].payload
        self.assertEqual(finished["cycle_counters"], result.cycle_counters)
        self.assertEqual(finished["terminal_node"]["evidence_kind"], "cycle_limit")
        terminal_step = ledger.find("route.graph.step")[finished["terminal_node"]["step_index"]].payload
        self.assertEqual(terminal_step["kind"], "cycle_limit")
        self.assertEqual(terminal_step["target"], "end")
        self.assertTrue(ledger.verify())


if __name__ == "__main__":
    unittest.main()
