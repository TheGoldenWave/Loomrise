"""R3 graph drafts must never silently execute through the R1 path."""
from copy import deepcopy
import unittest

from loomrise.config_validation import validate_configuration
from loomrise.configuration import ConfigurationValidationError
from loomrise.graph_runtime import GraphRuntime, GraphRuntimeError
from tests.test_configuration_service import ConfigurationServiceCase


def say_unit(uid="greeting"):
    return {
        "unit_id": uid, "version": 1, "load_mode": "routed",
        "entry_ports": [{"port": "from_start", "requires": []}],
        "reads": [], "writes": [],
        "exit_ports": [{"port": "done", "completion": {"deterministic": {}}, "exits": ["self.done"]}],
        "on_event": [], "fallback": {"kind": "clarify"}, "max_rounds": 3,
        "body": {"kind": "say", "text": "本服务不提供紧急救助。", "verbatim_reason": "服务范围披露须逐字展示"},
    }


def edge(eid, source, target, **extra):
    return {"id": eid, "from": source, "to": target, "condition": {}, **extra}


def node(nid, uid):
    return {"id": nid, "unit_ref": {"unit_id": uid, "version": 1}}


def graph_spec():
    parent = say_unit("disclosure")
    parent["entry_ports"][0]["goto"] = "intro.from_start"
    parent["body"] = {
        "kind": "graph", "routing": {"mode": "deterministic"},
        "nodes": [node("intro", "greeting")],
        "edges": [edge("finish-intro", "intro.done", "self.done")],
    }
    return {
        "persona": {"fields": {"verified": {"type": "boolean"}, "attempt_count": {"type": "integer"}}},
        "units": [parent, say_unit()], "g0_gates": [], "hard_rules": [], "task_blueprints": [],
        "orchestration": {
            "schema_version": "unit-graph-v1", "kind": "graph",
            "routing": {"mode": "deterministic"},
            "nodes": [node("package", "disclosure")],
            "entry": "package.from_start", "input_fields": [],
            "edges": [edge("finish", "package.done", "end")],
            "on_event": [], "fallback": {"kind": "human"},
        },
    }


def branch_spec():
    spec = graph_spec()
    parent = spec["units"][0]
    requiring = say_unit("requires-verification")
    requiring["entry_ports"][0]["requires"] = ["verified"]
    spec["units"].append(requiring)
    parent["body"]["nodes"].append(node("review", "requires-verification"))
    parent["body"]["edges"] = [
        edge("finish-intro", "intro.done", "self.done"),
        edge("present", "intro.done", "review.from_start", condition={"fact": {"field": "verified", "op": "exists"}}),
        edge("finish-review", "review.done", "self.done"),
    ]
    return spec


def codes(spec, submitting=False):
    return [issue.code for issue in validate_configuration(spec, submitting=submitting)]


class GraphValidationTests(unittest.TestCase):
    def test_unknown_fields_inside_condition_atoms_cannot_freeze(self):
        for condition in ({'fact': {'field': 'verified', 'op': 'exists', 'future': True}},
                          {'state': {'metric': 'runs', 'window': '24h', 'op': 'eq', 'value': 1, 'future': True}}):
            with self.subTest(condition=condition):
                value = graph_spec()
                value['orchestration']['edges'][0]['condition'] = condition
                self.assertTrue(any(issue.code.startswith('unsupported_runtime_') for issue in validate_configuration(value, submitting=True)))

    def test_graph_freeze_rejects_values_that_are_not_deterministic_json(self):
        for value in (float('nan'), float('inf'), float('-inf'), {"nested"}, ("tuple",)):
            with self.subTest(value=repr(value)):
                spec = graph_spec()
                spec['orchestration']['edges'][0]['condition'] = {
                    'fact': {'field': 'verified', 'op': 'eq', 'value': value},
                }
                issues = validate_configuration(spec, submitting=True)
                self.assertIn('non_json_graph_value', [issue.code for issue in issues])

    def test_graph_freeze_rejects_non_string_object_keys(self):
        spec = graph_spec()
        spec['units'][0]['body'] = {
            'kind': 'say', 'text': '固定内容', 'verbatim_reason': '测试',
            1: 'not-json-object-key',
        }
        issues = validate_configuration(spec, submitting=True)
        self.assertIn('non_json_graph_value', [issue.code for issue in issues])

    def test_event_payload_fields_are_data_not_nested_condition_expressions(self):
        spec = graph_spec()
        spec['orchestration']['edges'][0]['condition'] = {'event': {'event': 'timeout',
            'attributes': {'state': {'phase': 'open'}, 'fact': {'field': 'provider'}}}}
        self.assertEqual(codes(spec, submitting=True), [])

    def test_unresolved_model_completion_cannot_freeze(self):
        for index in (0, 1):
            spec = graph_spec()
            spec["units"][index]["exit_ports"][0]["completion"] = {"llm": {'prompt_ref': 'latest'}}
            self.assertIn("unsupported_runtime_completion", codes(spec, submitting=True))
        spec = graph_spec()
        spec["orchestration"]["fallback"] = {"kind": "default_unit", "target": "package.from_start"}
        self.assertEqual(codes(spec, submitting=True), [])

    def test_default_fallback_only_node_is_reachable_but_must_satisfy_field_requirements(self):
        spec = graph_spec()
        spec['units'].append(say_unit('safe'))
        graph = spec['orchestration']
        graph['nodes'].append(node('safe', 'safe'))
        graph['edges'].append(edge('safe-end', 'safe.done', 'end'))
        graph['fallback'] = {'kind': 'default_unit', 'target': 'safe.from_start'}
        self.assertEqual(codes(spec, submitting=True), [])
        spec['units'][-1]['entry_ports'][0]['requires'] = ['verified']
        self.assertIn('path_missing_field', codes(spec, submitting=True))

    def test_wait_timeout_target_must_resolve_inside_the_owning_unit(self):
        for target in ("missing.from_start", "package.from_start", "end"):
            spec = graph_spec()
            spec["units"][0]["waits"] = [{"on": "approval.received", "timeoutMs": 100, "timeoutTo": target}]
            self.assertIn("invalid_wait_timeout_target", codes(spec, submitting=True))
        spec = graph_spec()
        spec["units"][0]["waits"] = [{"on": "approval.received", "timeoutMs": 100, "timeoutTo": "intro.from_start"}]
        self.assertEqual(codes(spec, submitting=True), [])

    def test_timeout_only_child_is_a_reachable_local_branch(self):
        spec = graph_spec()
        parent = spec['units'][0]
        notice = say_unit('notice')
        spec['units'].append(notice)
        parent['body']['nodes'].append(node('notice', 'notice'))
        parent['body']['edges'].append(edge('notice-done', 'notice.done', 'self.done'))
        parent['waits'] = [{'on': 'approval.received', 'timeoutMs': 100, 'timeoutTo': 'notice.from_start'}]
        self.assertEqual(codes(spec, submitting=True), [])
        notice['entry_ports'][0]['requires'] = ['verified']
        notice['reads'] = ['verified']
        self.assertIn('path_missing_field', codes(spec, submitting=True))

    def test_malformed_wait_and_node_containers_return_validation_issues(self):
        for key, value in (('waits', 42), ('exit_ports', None)):
            spec = graph_spec()
            spec['units'][0][key] = value
            self.assertTrue(codes(spec, submitting=True))
        spec = graph_spec()
        spec['units'][0]['body']['nodes'] = None
        self.assertIn('invalid_graph_nodes', codes(spec, submitting=True))

    def test_timed_wait_requires_an_executable_timeout_target(self):
        spec = graph_spec()
        spec['units'][1]['waits'] = [{'on': 'approval.received', 'timeoutMs': 1}]
        self.assertIn('timeout_without_target', codes(spec, submitting=True))

    def test_nested_draft_is_pure_and_submission_fails_closed(self):
        spec = graph_spec()
        before = deepcopy(spec)
        self.assertEqual(codes(spec), [])
        self.assertEqual(codes(spec, submitting=True), [])
        self.assertEqual(spec, before)

    def test_version_discriminator_is_explicit_and_unknown_versions_fail(self):
        spec = graph_spec()
        del spec["orchestration"]
        self.assertIn("body_not_empty", codes(spec))
        spec["orchestration"] = {"schema_version": "unit-graph-v99"}
        self.assertIn("unsupported_graph_schema", codes(spec))
        self.assertIn("body_not_empty", codes(spec))

    def test_references_do_not_follow_latest_or_accept_boolean_versions(self):
        for version in (2, "latest", True, None):
            with self.subTest(version=version):
                spec = graph_spec()
                spec["units"][0]["body"]["nodes"][0]["unit_ref"]["version"] = version
                self.assertIn("unfrozen_unit_reference", codes(spec))

    def test_bare_cross_layer_edges_and_entry_mappings_are_rejected(self):
        for target in ("package.intro.from_start", "greeting.from_start", "self.missing"):
            spec = graph_spec()
            spec["orchestration"]["edges"][0]["to"] = target
            self.assertIn("invalid_edge_target", codes(spec))
        spec = graph_spec()
        spec["units"][0]["entry_ports"][0]["goto"] = "greeting.from_start"
        self.assertIn("invalid_entry_mapping", codes(spec))

    def test_composition_cycle_is_distinct_from_execution_cycle(self):
        spec = graph_spec()
        parent = spec["units"][0]
        parent["body"]["nodes"][0]["unit_ref"]["unit_id"] = "disclosure"
        self.assertIn("composition_cycle", codes(spec))

    def test_execution_cycles_are_checked_independently_of_edge_order(self):
        spec = graph_spec()
        parent = spec["units"][0]
        parent["body"]["nodes"].append(node("repeat", "greeting"))
        links = [edge("forward", "intro.done", "repeat.from_start"), edge("back", "repeat.done", "intro.from_start"), edge("done", "repeat.done", "self.done")]
        for ordered in (links, list(reversed(links))):
            parent["body"]["edges"] = ordered
            self.assertIn("unbounded_execution_cycle", codes(spec))
        parent["writes"] = ["attempt_count"]
        links[1].update(max_rounds=2, exit="self.done", counter="attempt_count", window="cycle")
        self.assertEqual(codes(spec), [])
        links[1]["window"] = "session"
        self.assertIn("invalid_loop_window", codes(spec))

    def test_disconnected_cycles_are_unreachable_even_with_incoming_edges(self):
        spec = graph_spec()
        graph = spec["units"][0]["body"]
        graph["nodes"].extend([node("a", "greeting"), node("b", "greeting")])
        graph["edges"].extend([edge("ab", "a.done", "b.from_start"), edge("ba", "b.done", "a.from_start")])
        self.assertEqual(codes(spec).count("unreachable_graph_node"), 2)

    def test_events_cannot_escape_their_declared_layer(self):
        spec = graph_spec()
        spec["orchestration"]["on_event"] = [{"event": "timeout", "scope": "global", "goto": "package.intro.from_start"}]
        spec["units"][0]["on_event"] = [{"event": "handoff", "scope": "global", "goto": "self.done"}]
        self.assertIn("invalid_event_target", codes(spec))
        self.assertIn("invalid_event_scope", codes(spec))
        spec["orchestration"]["on_event"][0]["goto"] = "package.from_start"
        spec["units"][0]["on_event"][0]["scope"] = "subtree"
        self.assertEqual(codes(spec), [])

    def test_root_event_target_is_a_reachable_graph_entry(self):
        spec = graph_spec()
        event_unit = say_unit("event-only")
        spec["units"].append(event_unit)
        graph = spec["orchestration"]
        graph["nodes"].append(node("event", "event-only"))
        graph["edges"].append(edge("event-end", "event.done", "end"))
        graph["on_event"] = [{"event": "timeout", "scope": "global", "goto": "event.from_start"}]

        self.assertNotIn("unreachable_graph_node", codes(spec, submitting=True))
        self.assertEqual(codes(spec, submitting=True), [])

    def test_subtree_event_target_is_a_reachable_local_graph_entry(self):
        spec = graph_spec()
        parent = spec["units"][0]
        event_unit = say_unit("event-only")
        spec["units"].append(event_unit)
        parent["body"]["nodes"].append(node("event", "event-only"))
        parent["body"]["edges"].append(edge("event-end", "event.done", "self.done"))
        parent["on_event"] = [{"event": "handoff", "scope": "subtree", "goto": "event.from_start"}]

        self.assertNotIn("unreachable_graph_node", codes(spec, submitting=True))
        self.assertEqual(codes(spec, submitting=True), [])

    def test_subtree_event_target_counts_as_an_owner_exit(self):
        spec = graph_spec()
        parent = spec["units"][0]
        parent["exit_ports"].append({
            "port": "other", "completion": {"deterministic": {}}, "exits": ["self.other"],
        })
        parent["body"]["edges"] = [edge("ordinary-exit", "intro.done", "self.other")]
        parent["on_event"] = [{"event": "handoff", "scope": "subtree", "goto": "self.done"}]
        spec["orchestration"]["edges"].append(edge("finish-other", "package.other", "end"))

        self.assertNotIn("unconnected_owner_exit", codes(spec, submitting=True))
        self.assertEqual(codes(spec, submitting=True), [])

    def test_atom_interface_is_checked_from_executable_body(self):
        spec = graph_spec()
        atom = spec["units"][1]
        atom["body"] = {"kind": "judge", "condition": {"fact": {"field": "verified", "op": "exists"}}, "result_field": "verified"}
        self.assertIn("hidden_body_read", codes(spec))
        self.assertIn("hidden_body_write", codes(spec))
        atom["reads"] = atom["writes"] = ["verified"]
        spec["units"][0]["reads"] = spec["units"][0]["writes"] = ["verified"]
        self.assertEqual(codes(spec), [])
        atom["writes"].append("attempt_count")
        self.assertIn("unassigned_write", codes(spec))

    def test_say_requires_reason_and_unresolved_resources_are_not_accepted(self):
        spec = graph_spec()
        del spec["units"][1]["body"]["verbatim_reason"]
        self.assertIn("missing_verbatim_reason", codes(spec))
        for kind in ("tool", "speak"):
            spec["units"][1]["body"] = {"kind": kind, "ref": "latest"}
            self.assertIn("unsupported_graph_atom", codes(spec))

    def test_routing_conditions_share_depth_and_deterministic_event_rules(self):
        spec = graph_spec()
        condition = {"all_of": [{"all_of": [{"all_of": [{"fact": {"field": "verified", "op": "exists"}}]}]}]}
        spec["orchestration"]["edges"][0]["condition"] = condition
        self.assertIn("condition_too_deep", codes(spec))
        spec["orchestration"]["on_event"] = [{"event": "timeout", "scope": "global", "goto": "end", "when": {"llm": "choose"}}]
        self.assertIn("nondeterministic_condition", codes(spec))

    def test_cycle_state_window_is_freezable_but_session_is_not(self):
        spec = graph_spec()
        spec["orchestration"]["edges"][0]["condition"] = {
            "state": {"metric": "attempts", "window": "cycle", "op": "gt", "value": 2},
        }
        self.assertNotIn("unsupported_runtime_state_window", codes(spec, submitting=True))

        spec["orchestration"]["edges"][0]["condition"]["state"]["window"] = "session"
        self.assertIn("unsupported_runtime_state_window", codes(spec, submitting=True))

        spec = graph_spec()
        spec["orchestration"]["edges"][0]["condition"] = {
            "state": {"metric": "attempts", "window": "24h", "op": "between", "value": [1, 2]},
        }
        self.assertIn("unsupported_runtime_state_operator", codes(spec, submitting=True))

    def test_runtime_state_guard_reports_malformed_members_without_raising(self):
        for member in ("window", "metric", "op"):
            with self.subTest(member=member):
                spec = graph_spec()
                predicate = {"metric": "attempts", "window": "24h", "op": "gt", "value": 2}
                predicate[member] = []
                spec["orchestration"]["edges"][0]["condition"] = {"state": predicate}
                self.assertTrue(codes(spec, submitting=True))

    def test_supported_event_attributes_can_be_frozen(self):
        spec = graph_spec()
        spec["orchestration"]["edges"][0]["condition"] = {
            "event": {"event": "timeout", "attributes": {"source": "provider"}},
        }
        self.assertEqual(codes(spec, submitting=True), [])
        for value in ("2", True, None, float("inf")):
            with self.subTest(value=value):
                spec = graph_spec()
                spec["orchestration"]["edges"][0]["condition"] = {
                    "state": {"metric": "attempts", "window": "24h", "op": "gt", "value": value},
                }
                self.assertIn("unsupported_runtime_state_value", codes(spec, submitting=True))

    def test_event_attributes_not_supported_by_graph_runtime_are_not_freezable(self):
        spec = graph_spec()
        spec["orchestration"]["edges"][0]["condition"] = {
            "event": {"event": "timeout", "source": "provider"},
        }
        self.assertIn("unsupported_runtime_event_attributes", codes(spec, submitting=True))

    def test_handoff_is_a_supported_boundary_event_condition(self):
        spec = graph_spec()
        spec["orchestration"]["edges"][0]["condition"] = {
            "event": {"event": "handoff"},
        }
        self.assertNotIn("invalid_condition", codes(spec, submitting=True))
        self.assertNotIn("unsupported_runtime_event_attributes", codes(spec, submitting=True))

    def test_fact_operators_not_supported_by_graph_runtime_are_not_freezable(self):
        spec = graph_spec()
        spec["orchestration"]["edges"][0]["condition"] = {
            "fact": {"field": "verified", "op": "changed_to", "value": True},
        }
        self.assertIn("unsupported_runtime_fact_operator", codes(spec, submitting=True))

    def test_string_matches_with_bounded_regex_is_freezable(self):
        spec = graph_spec()
        spec["persona"]["fields"]["order_code"] = {"type": "string"}
        spec["units"][0]["reads"] = ["order_code"]
        spec["orchestration"]["input_fields"] = ["order_code"]
        spec["orchestration"]["edges"][0]["condition"] = {
            "fact": {"field": "order_code", "op": "matches", "value": "^ORD-[0-9]{8}$"},
        }
        self.assertEqual(codes(spec, submitting=True), [])

    def test_matches_rejects_non_string_unsafe_and_unbounded_patterns(self):
        for pattern in (1, "", "a*", "(a|aa)+", "x" * 129, "[broken"):
            with self.subTest(pattern=pattern):
                spec = graph_spec()
                spec["orchestration"]["edges"][0]["condition"] = {
                    "fact": {"field": "verified", "op": "matches", "value": pattern},
                }
                self.assertIn("unsupported_runtime_fact_value", codes(spec, submitting=True))

    def test_inclusive_numeric_between_predicate_is_freezable(self):
        spec = graph_spec()
        spec["persona"]["fields"]["score"] = {"type": "number"}
        spec["units"][0]["reads"] = ["score"]
        spec["orchestration"]["input_fields"] = ["score"]
        spec["orchestration"]["edges"][0]["condition"] = {
            "fact": {"field": "score", "op": "between", "value": [1, 3]},
        }
        self.assertEqual(codes(spec, submitting=True), [])

    def test_between_requires_two_finite_ordered_numeric_bounds(self):
        for bounds in ([1], [True, 2], [2, 1], [1, float("inf")], [1, "2"]):
            with self.subTest(bounds=bounds):
                spec = graph_spec()
                spec["persona"]["fields"]["score"] = {"type": "number"}
                spec["units"][0]["reads"] = ["score"]
                spec["orchestration"]["input_fields"] = ["score"]
                spec["orchestration"]["edges"][0]["condition"] = {
                    "fact": {"field": "score", "op": "between", "value": bounds},
                }
                self.assertTrue(codes(spec, submitting=True))

    def test_unknown_fields_and_malformed_json_shapes_produce_issues(self):
        for key, value in (("nodes", None), ("edges", {}), ("routing", []), ("entry", {})):
            spec = graph_spec()
            spec["orchestration"][key] = value
            self.assertTrue(codes(spec))
        for key, value in (("id", {}), ("from", []), ("to", {})):
            spec = graph_spec()
            spec["orchestration"]["edges"][0][key] = value
            self.assertTrue(codes(spec))
        spec = graph_spec()
        spec["orchestration"]["nodes"][0]["position"] = {"x": 1, "y": 1}
        self.assertIn("unsupported_graph_field", codes(spec))

    def test_entry_requires_must_be_ready_on_every_incoming_path(self):
        spec = branch_spec()
        self.assertNotIn("path_missing_field", codes(spec))
        spec["units"][0]["body"]["edges"].append(edge("unguarded", "intro.done", "review.from_start"))
        self.assertIn("path_missing_field", codes(spec))

    def test_join_uses_intersection_not_union_of_branch_fields(self):
        spec = branch_spec()
        edges = spec["units"][0]["body"]["edges"]
        edges.append(edge("unguarded", "intro.done", "review.from_start"))
        edges.reverse()
        self.assertIn("path_missing_field", codes(spec))
        edges.reverse()
        self.assertIn("path_missing_field", codes(spec))

    def test_llm_selection_and_negative_presence_do_not_prove_fields(self):
        spec = branch_spec()
        edges = spec["units"][0]["body"]["edges"]
        edges[1]["condition"] = {"llm": {"prompt": "是否已核验"}}
        self.assertIn("path_missing_field", codes(spec))
        edges[1]["condition"] = {"fact": {"field": "verified", "op": "is_unset"}}
        self.assertIn("path_missing_field", codes(spec))

    def test_positive_model_edge_leaf_freezes_only_for_llm_routed_graphs(self):
        for mode in ("llm", "hybrid"):
            with self.subTest(mode=mode):
                spec = graph_spec()
                spec["orchestration"]["routing"]["mode"] = mode
                spec["orchestration"]["input_fields"] = ["verified"]
                spec["orchestration"]["edges"][0]["condition"] = {
                    "all_of": [
                        {"fact": {"field": "verified", "op": "eq", "value": True}},
                        {"llm": {"prompt": "用户是否确认"}},
                    ],
                }
                self.assertEqual(codes(spec, submitting=True), [])

                spec = graph_spec()
                spec["units"][0]["body"]["routing"]["mode"] = mode
                spec["units"][0]["body"]["edges"][0]["condition"] = {"llm": {"prompt": "用户是否确认"}}
                self.assertEqual(codes(spec, submitting=True), [])

        spec = graph_spec()
        spec["orchestration"]["routing"]["mode"] = "deterministic"
        spec["orchestration"]["edges"][0]["condition"] = {"llm": {"prompt": "用户是否确认"}}
        self.assertIn("nondeterministic_condition", codes(spec, submitting=True))

        spec = graph_spec()
        spec["orchestration"]["routing"]["mode"] = "hybrid"
        spec["orchestration"]["edges"][0]["condition"] = {"none_of": [{"llm": {"prompt": "用户是否确认"}}]}
        self.assertIn("nondeterministic_condition", codes(spec, submitting=True))

        spec = graph_spec()
        spec["hard_rules"] = [{"when": {"llm": {"prompt": "语义条件"}}}]
        self.assertIn("nondeterministic_condition", codes(spec, submitting=True))

    def test_model_and_empty_leaves_do_not_discount_combination_nesting(self):
        for leaf in ({"llm": {"prompt": "用户是否确认"}}, {}):
            for scope in ("root", "nested"):
                for layers in (2, 3):
                    with self.subTest(leaf=leaf, scope=scope, layers=layers):
                        spec = graph_spec()
                        graph = spec["orchestration"] if scope == "root" else spec["units"][0]["body"]
                        graph["routing"]["mode"] = "hybrid"
                        condition = deepcopy(leaf)
                        for _ in range(layers):
                            condition = {"all_of": [condition]}
                        graph["edges"][0]["condition"] = condition
                        if layers == 3:
                            self.assertIn("condition_too_deep", codes(spec, submitting=True))
                            with self.assertRaises(GraphRuntimeError):
                                GraphRuntime(spec).route({})
                        else:
                            self.assertEqual(codes(spec, submitting=True), [])
                            # No selector is required to establish structural acceptance;
                            # a missing model decision can still produce a safe fallback.
                            GraphRuntime(spec).route({})

    def test_model_edge_leaf_requires_a_resolved_prompt_and_no_sibling_predicates(self):
        for payload in (None, True, 42, [], "", {}, {"prompt": " "},
                        {"prompt_ref": "latest"}, {"prompt": "选择", "future": True}):
            with self.subTest(payload=payload):
                spec = graph_spec()
                spec["orchestration"]["routing"]["mode"] = "hybrid"
                spec["orchestration"]["edges"][0]["condition"] = {"llm": payload}
                self.assertIn("invalid_condition", codes(spec, submitting=True))

        spec = graph_spec()
        spec["orchestration"]["routing"]["mode"] = "hybrid"
        spec["orchestration"]["edges"][0]["condition"] = {
            "llm": {"prompt": "选择"}, "fact": {"field": "verified", "op": "exists"},
        }
        self.assertIn("invalid_condition", codes(spec, submitting=True))

    def test_waits_contract_accepts_timeout_and_rejects_malformed_declarations(self):
        spec = graph_spec()
        spec["units"][1]["waits"] = [{"on": "approval.received", "timeoutMs": 120000, "timeoutTo": "self.done"}]
        self.assertEqual(codes(spec), [])
        invalid = [
            {"on": "", "timeoutMs": 10},
            {"on": "approval.received", "timeoutMs": True},
            {"on": "approval.received", "timeoutTo": "timeout-handoff"},
            {"on": "approval.received", "unknown": 1},
        ]
        for wait in invalid:
            with self.subTest(wait=wait):
                spec["units"][1]["waits"] = [wait]
                self.assertTrue(codes(spec))
        spec["units"][1]["waits"] = [
            {"on": "approval.received"}, {"on": "approval.received"},
        ]
        self.assertIn("duplicate_wait_event", codes(spec))

    def test_tool_atom_requires_exact_frozen_tool_manifest(self):
        spec = graph_spec()
        spec["tools"] = [{"tool_id": "lookup", "version": "1", "side_effect_level": "read_only"}]
        spec["units"][1]["body"] = {"kind": "tool", "tool_ref": {"tool_id": "lookup", "version": "1"}, "arguments": {}}
        self.assertNotIn("unfrozen_tool_reference", codes(spec))
        self.assertIn("unsupported_graph_atom", codes(spec))
        spec["units"][1]["body"]["tool_ref"]["tool_id"] = "missing"
        self.assertIn("unfrozen_tool_reference", codes(spec))

    def test_tool_reference_rejects_version_drift_ambiguity_and_malformed_registry(self):
        spec = graph_spec()
        manifest = {"tool_id": "lookup", "version": "1"}
        spec["units"][1]["body"] = {"kind": "tool", "tool_ref": manifest.copy(), "arguments": {}}
        for registry in (None, True, {"lookup": manifest}, [manifest, manifest],
                         [{"tool_id": "lookup", "version": "2"}]):
            with self.subTest(registry=registry):
                spec["tools"] = registry
                self.assertIn("unfrozen_tool_reference", codes(spec))
        spec["tools"] = [manifest]
        for reference in ({"tool_id": "lookup"}, {"tool_id": "lookup", "version": True},
                          {"tool_id": "lookup", "version": "1", "latest": True}):
            with self.subTest(reference=reference):
                spec["units"][1]["body"]["tool_ref"] = reference
                self.assertIn("unfrozen_tool_reference", codes(spec))


class GraphDraftPersistenceTests(ConfigurationServiceCase):
    def test_draft_retains_session_state_window_until_freeze(self):
        draft = self.seed()
        for window in ("session",):
            with self.subTest(window=window):
                spec = graph_spec()
                spec["orchestration"]["edges"][0]["condition"] = {
                    "state": {"metric": "attempts", "window": window, "op": "gt", "value": 2},
                }
                saved = self.service.save_draft(
                    tenant_id="tenant-a", agent_id="expert-a",
                    expected_revision=draft["revision"], config=spec,
                )
                self.assertEqual(saved["config"], spec)
                self.assertNotIn("unsupported_runtime_state_window", codes(spec))
                with self.assertRaises(ConfigurationValidationError) as caught:
                    self.service.freeze_candidate(
                        tenant_id="tenant-a", agent_id="expert-a",
                        expected_revision=saved["revision"], idempotency_key=f"unsupported-{window}",
                    )
                self.assertIn(
                    "unsupported_runtime_state_window",
                    [issue["code"] for issue in caught.exception.issues],
                )
                draft = saved
        self.assertEqual(self.service.list_candidates(tenant_id="tenant-a", agent_id="expert-a"), [])

    def test_supported_graph_draft_survives_restart_and_can_be_frozen(self):
        draft = self.seed()
        spec = graph_spec()
        saved = self.service.save_draft(tenant_id="tenant-a", agent_id="expert-a", expected_revision=draft["revision"], config=spec)
        candidate = self.service.freeze_candidate(tenant_id="tenant-a", agent_id="expert-a", expected_revision=saved["revision"], idempotency_key="r3-executable")
        self.assertEqual(candidate["status"], "frozen")
        self.store.close()
        from loomrise.durable_store import SqliteStore
        from loomrise.configuration import ConfigurationService
        self.store = SqliteStore(self.path)
        self.addCleanup(self.store.close)
        reopened = ConfigurationService(self.store).get_draft(tenant_id="tenant-a", agent_id="expert-a")
        self.assertEqual(reopened["config"], spec)
        self.assertEqual(reopened["revision"], saved["revision"])


if __name__ == "__main__":
    unittest.main()
