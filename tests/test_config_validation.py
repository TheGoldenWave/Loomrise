from __future__ import annotations

from copy import deepcopy
import unittest

from loomrise.config_validation import validate_configuration


def valid_unit(**overrides):
    unit = {
        "unit_id": "collect-contact",
        "version": 1,
        "load_mode": "routed",
        "entry_ports": [{"port": "from_start", "requires": []}],
        "reads": ["customer.name"],
        "writes": ["customer.phone"],
        "exit_ports": [
            {
                "port": "done",
                "completion": {"deterministic": {"fact": {"field": "customer.phone", "op": "exists"}}},
                "exits": ["collect-contact"],
            }
        ],
        "on_event": [],
        "fallback": {"kind": "clarify"},
        "max_rounds": 3,
        "body": {},
    }
    unit.update(overrides)
    return unit


def valid_spec(*, units=None, **overrides):
    spec = {
        "persona": {
            "fields": {
                "customer.name": {"type": "string"},
                "customer.phone": {"type": "string"},
                "customer.verified": {"type": "boolean"},
            },
            "entry_unit_ids": ["collect-contact"],
        },
        "units": units or [valid_unit()],
        "g0_gates": [],
        "hard_rules": [],
        "task_blueprints": [],
    }
    spec.update(overrides)
    return spec


def errors(spec, *, submitting=False):
    return validate_configuration(spec, submitting=submitting)


def paths(issues):
    return [issue.path for issue in issues]


def test_complete_r1_manifest_passes_without_executable_body():
    assert errors(valid_spec()) == []


def test_draft_save_allows_incomplete_unit_but_freeze_reports_json_paths():
    spec = valid_spec(units=[{"unit_id": "unfinished", "body": {}}])

    draft_issues = errors(spec)
    assert "$.units[0].version" in paths(draft_issues)
    assert all(issue.code != "isolated_routed_unit" for issue in draft_issues)
    issues = errors(spec, submitting=True)

    assert "$.units[0].version" in paths(issues)
    assert "$.units[0].entry_ports" in paths(issues)
    assert all(issue.path.startswith("$.units[0].") for issue in issues)


def test_unit_contract_rejects_nonempty_body_and_invalid_mode():
    unit = valid_unit(body={"nodes": []}, load_mode="both")
    unit["exit_ports"][0]["exits"] = ["self.done"]
    spec = valid_spec(units=[unit])

    issues = errors(spec, submitting=True)

    assert [(issue.path, issue.code) for issue in issues] == [
        ("$.units[0].load_mode", "invalid_load_mode"),
        ("$.units[0].body", "body_not_empty"),
    ]


def test_reads_must_be_declared_upstream_system_or_self_written():
    unit = valid_unit(reads=["customer.name", "customer.unknown"])
    spec = valid_spec(units=[unit])

    issues = errors(spec, submitting=True)

    assert [(issue.path, issue.code) for issue in issues] == [
        ("$.units[0].reads[1]", "undeclared_read"),
    ]


def test_unit_ports_and_interface_honesty_are_validated():
    unit = valid_unit(
        entry_ports=[{"port": "from_start"}],
        exit_ports=[
            {
                "port": "done",
                "completion": {"deterministic": {"fact": {"field": "customer.verified", "op": "eq", "value": True}}},
                "exits": ["missing-unit"],
            }
        ],
    )
    spec = valid_spec(units=[unit])

    issues = errors(spec, submitting=True)

    assert [(issue.path, issue.code) for issue in issues] == [
        ("$.units[0].entry_ports[0].requires", "missing_port_requires"),
        ("$.units[0].exit_ports[0].completion.deterministic.fact.field", "undeclared_completion_field"),
        ("$.units[0].exit_ports[0].exits[0]", "unknown_unit_reference"),
    ]


def test_unit_round_limit_and_event_scope_are_checked():
    unit = valid_unit(
        max_rounds=0,
        on_event=[{"event": "timeout", "goto": "elsewhere", "scope": "global"}],
    )
    spec = valid_spec(units=[unit])

    issues = errors(spec, submitting=True)

    assert [(issue.path, issue.code) for issue in issues] == [
        ("$.units[0].on_event[0].scope", "invalid_event_scope"),
        ("$.units[0].on_event[0].goto", "invalid_event_target"),
        ("$.units[0].max_rounds", "invalid_max_rounds"),
    ]


def test_routed_isolation_is_submission_only_and_concurrent_is_not_submittable():
    isolated = valid_unit()
    entry = valid_unit(unit_id="confirm-contact")
    entry["exit_ports"][0]["exits"] = ["self.done"]
    spec = valid_spec(
        units=[isolated, entry],
        persona={"fields": {}, "entry_unit_ids": ["confirm-contact"]},
    )

    assert not any(issue.code == "isolated_routed_unit" for issue in errors(spec))
    assert any(issue.code == "isolated_routed_unit" for issue in errors(spec, submitting=True))

    spec = valid_spec(units=[valid_unit(load_mode="concurrent")])
    assert any(issue.code == "unsupported_concurrent" for issue in errors(spec, submitting=True))
    assert not any(issue.code == "unsupported_concurrent" for issue in errors(spec))


def test_hard_rule_v02_schema_checks_when_verdict_and_enforce():
    rule = {
        "rule_id": "require-confirmation",
        "when": {"fact": {"field": "customer.verified", "op": "eq", "value": False}},
        "verdict": {"type": "require", "reason": "确认身份", "target": "customer.verified"},
        "enforce": {
            "scope": "task",
            "priority": 10,
            "reason": "身份确认前不办理",
            "customer_facing": False,
            "severity": "normal",
        },
    }
    spec = valid_spec(hard_rules=[rule])
    assert errors(spec, submitting=True) == []

    invalid = deepcopy(rule)
    invalid["when"] = {"llm": {"prompt": "用户是否在犹豫"}}
    invalid["verdict"] = {"type": "allow"}
    invalid["enforce"]["scope"] = "global-ish"
    spec = valid_spec(hard_rules=[invalid])

    assert [(issue.path, issue.code) for issue in errors(spec, submitting=True)] == [
        ("$.hard_rules[0].when", "nondeterministic_condition"),
        ("$.hard_rules[0].verdict.type", "invalid_verdict"),
        ("$.hard_rules[0].verdict.reason", "missing_verdict_reason"),
        ("$.hard_rules[0].enforce.scope", "invalid_rule_scope"),
    ]


def test_condition_depth_is_shared_for_hard_rules_and_unit_conditions():
    condition = {
        "all_of": [
            {"fact": {"field": "customer.verified", "op": "eq", "value": True}},
            {
                "any_of": [
                    {"event": {"event": "input_matched", "pattern": "yes"}},
                    {"none_of": [{"fact": {"field": "customer.name", "op": "is_set"}}]},
                ]
            },
        ]
    }
    rule = {
        "rule_id": "deep",
        "when": condition,
        "verdict": {"type": "stop", "stop_reason": "halt"},
        "enforce": {"scope": "task", "priority": 10, "reason": "halt", "severity": "normal", "customer_facing": False},
    }
    spec = valid_spec(hard_rules=[rule])

    issues = errors(spec, submitting=True)

    assert [(issue.path, issue.code) for issue in issues] == [
        ("$.hard_rules[0].when", "condition_too_deep"),
    ]


def test_condition_operator_compatibility_uses_persona_field_types():
    rule = {
        "rule_id": "numeric-name-check",
        "when": {"fact": {"field": "customer.name", "op": "between", "value": [1, 2]}},
        "verdict": {"type": "stop", "stop_reason": "invalid"},
        "enforce": {
            "scope": "task",
            "priority": 10,
            "reason": "invalid",
            "customer_facing": False,
            "severity": "normal",
        },
    }

    issues = errors(valid_spec(hard_rules=[rule]), submitting=True)

    assert [(issue.path, issue.code) for issue in issues] == [
        ("$.hard_rules[0].when.fact.op", "incompatible_condition_operator"),
    ]


def test_g0_gate_is_deterministic_and_separate_from_hard_rule_verdict():
    gate = {
        "gate_id": "consent-stop",
        "when": {"fact": {"field": "customer.verified", "op": "eq", "value": False}},
        "route_to": "block",
    }
    spec = valid_spec(g0_gates=[gate])
    assert errors(spec, submitting=True) == []

    invalid = deepcopy(gate)
    invalid["verdict"] = "deny"
    invalid["when"] = {"llm": {"prompt": "semantic"}}
    spec = valid_spec(g0_gates=[invalid])

    assert [(issue.path, issue.code) for issue in errors(spec, submitting=True)] == [
        ("$.g0_gates[0].verdict", "g0_verdict_not_allowed"),
        ("$.g0_gates[0].when", "nondeterministic_condition"),
    ]


def test_duplicate_identifiers_and_unfrozen_unit_references_are_reported_stably():
    first = valid_unit()
    second = valid_unit(unit_id="collect-contact", version=0)
    spec = valid_spec(units=[first, second])

    issues = errors(spec, submitting=True)

    assert [(issue.path, issue.code) for issue in issues] == [
        ("$.units[1].unit_id", "duplicate_unit_id"),
        ("$.units[1].version", "invalid_version"),
    ]


def test_task_blueprints_keep_only_the_confirmed_stable_key_contract():
    blueprint = {"blueprint_key": "follow-up", "definition": {"future_shape": "preserved"}}
    assert errors(valid_spec(task_blueprints=[blueprint]), submitting=True) == []

    issues = errors(valid_spec(task_blueprints=[blueprint, deepcopy(blueprint)]), submitting=True)
    assert [(issue.path, issue.code) for issue in issues] == [
        ("$.task_blueprints[1].blueprint_key", "duplicate_blueprint_key"),
    ]

    incomplete = {"definition": {"draft": True}}
    assert errors(valid_spec(task_blueprints=[incomplete])) == []
    assert [(issue.path, issue.code) for issue in errors(
        valid_spec(task_blueprints=[incomplete]), submitting=True,
    )] == [("$.task_blueprints[0].blueprint_key", "missing_blueprint_key")]


def test_hard_rule_time_requires_rfc3339_timezone_and_order():
    rule = {
        "rule_id": "time-window",
        "when": {},
        "verdict": {"type": "stop", "stop_reason": "expired"},
        "enforce": {
            "scope": "global", "priority": 1, "reason": "window",
            "severity": "normal", "customer_facing": False,
            "valid_from": "2030-01-01T00:00:00Z",
            "valid_until": "2030-01-02T00:00:00+08:00",
        },
    }
    assert errors(valid_spec(hard_rules=[rule]), submitting=True) == []

    invalid = deepcopy(rule)
    invalid["enforce"]["valid_from"] = "2030-01-01T00:00:00"
    invalid["enforce"]["valid_until"] = "2030-1-2T00:00:00+00:00"
    issues = errors(valid_spec(hard_rules=[invalid]), submitting=True)
    assert [(issue.path, issue.code) for issue in issues] == [
        ("$.hard_rules[0].enforce.valid_from", "invalid_rule_time"),
        ("$.hard_rules[0].enforce.valid_until", "invalid_rule_time"),
    ]

    reversed_range = deepcopy(rule)
    reversed_range["enforce"]["valid_from"] = "2030-01-02T00:00:00Z"
    reversed_range["enforce"]["valid_until"] = "2030-01-01T00:00:00Z"
    assert [(issue.path, issue.code) for issue in errors(
        valid_spec(hard_rules=[reversed_range]), submitting=True,
    )] == [("$.hard_rules[0].enforce.valid_until", "invalid_rule_time_order")]


class ConfigurationValidationTests(unittest.TestCase):
    def test_complete_r1_manifest_passes_without_executable_body(self):
        test_complete_r1_manifest_passes_without_executable_body()

    def test_draft_save_allows_incomplete_unit_but_freeze_reports_json_paths(self):
        test_draft_save_allows_incomplete_unit_but_freeze_reports_json_paths()

    def test_unit_contract_rejects_nonempty_body_and_invalid_mode(self):
        test_unit_contract_rejects_nonempty_body_and_invalid_mode()

    def test_reads_must_be_declared_upstream_system_or_self_written(self):
        test_reads_must_be_declared_upstream_system_or_self_written()

    def test_unit_ports_and_interface_honesty_are_validated(self):
        test_unit_ports_and_interface_honesty_are_validated()

    def test_unit_round_limit_and_event_scope_are_checked(self):
        test_unit_round_limit_and_event_scope_are_checked()

    def test_routed_isolation_is_submission_only_and_concurrent_is_not_submittable(self):
        test_routed_isolation_is_submission_only_and_concurrent_is_not_submittable()

    def test_hard_rule_v02_schema_checks_when_verdict_and_enforce(self):
        test_hard_rule_v02_schema_checks_when_verdict_and_enforce()

    def test_condition_depth_is_shared_for_hard_rules_and_unit_conditions(self):
        test_condition_depth_is_shared_for_hard_rules_and_unit_conditions()

    def test_g0_gate_is_deterministic_and_separate_from_hard_rule_verdict(self):
        test_g0_gate_is_deterministic_and_separate_from_hard_rule_verdict()

    def test_condition_operator_compatibility_uses_persona_field_types(self):
        test_condition_operator_compatibility_uses_persona_field_types()

    def test_duplicate_identifiers_and_unfrozen_unit_references_are_reported_stably(self):
        test_duplicate_identifiers_and_unfrozen_unit_references_are_reported_stably()

    def test_task_blueprints_keep_only_the_confirmed_stable_key_contract(self):
        test_task_blueprints_keep_only_the_confirmed_stable_key_contract()

    def test_hard_rule_time_requires_rfc3339_timezone_and_order(self):
        test_hard_rule_time_requires_rfc3339_timezone_and_order()


if __name__ == "__main__":
    unittest.main()

