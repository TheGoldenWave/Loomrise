from __future__ import annotations

from copy import deepcopy
import unittest

from loomrise.config_validation import validate_configuration


def route_unit(unit_id: str, *, body: dict | None = None):
    return {
        "unit_id": unit_id,
        "version": 1,
        "load_mode": "routed",
        "entry_ports": [{"port": "from_start", "requires": []}],
        "reads": [],
        "writes": [],
        "exit_ports": [{"port": "done", "completion": {"deterministic": {}}, "exits": ["self.done"]}],
        "on_event": [],
        "fallback": {"kind": "clarify"},
        "max_rounds": 1,
        "body": body or {"kind": "say", "text": "完成", "verbatim_reason": "测试"},
    }


def concurrent_unit(unit_id: str = "faq"):
    return {
        **route_unit(unit_id),
        "load_mode": "concurrent",
    }


def graph_spec(*units):
    parent = route_unit("root", body={"kind": "graph", "routing": {"mode": "deterministic"},
                                       "nodes": [{"id": "step", "unit_ref": {"unit_id": "step", "version": 1}}],
                                       "edges": [{"id": "finish", "from": "step.done", "to": "self.done", "condition": {}}]})
    step = route_unit("step")
    parent["entry_ports"][0]["goto"] = "step.from_start"
    return {
        "persona": {"fields": {}, "entry_unit_ids": ["root"]},
        "units": [parent, step, *units],
        "orchestration": {
            "schema_version": "unit-graph-v1",
            "kind": "graph",
            "routing": {"mode": "deterministic"},
            "nodes": [{"id": "root", "unit_ref": {"unit_id": "root", "version": 1}}],
            "entry": "root.from_start",
            "input_fields": [],
            "edges": [{"id": "finish-root", "from": "root.done", "to": "end", "condition": {}}],
            "on_event": [],
            "fallback": {"kind": "human"},
        },
        "g0_gates": [],
        "hard_rules": [],
        "task_blueprints": [],
    }


def codes(spec, *, submitting=False):
    return [(issue.path, issue.code) for issue in validate_configuration(spec, submitting=submitting)]


class ConcurrentUnitValidationTests(unittest.TestCase):
  def test_concurrent_graph_requires_positive_group_limit_but_draft_and_graph_submission_keep_separate_gates(self):
    spec = graph_spec(concurrent_unit())

    draft = codes(spec)
    assert ("$.concurrent_config.max_units", "missing_concurrent_limit") in draft
    assert ("$.orchestration", "graph_runtime_unavailable") not in draft

    frozen = codes(spec, submitting=True)
    assert ("$.concurrent_config.max_units", "missing_concurrent_limit") in frozen
    assert ("$.orchestration", "graph_runtime_unavailable") not in frozen

    spec["concurrent_config"] = {"max_units": 1}
    assert ("$.concurrent_config.max_units", "missing_concurrent_limit") not in codes(spec)


  def test_concurrent_scope_defaults_to_pool_and_accepts_only_routed_step_ids(self):
    spec = graph_spec(concurrent_unit())
    spec["concurrent_config"] = {"max_units": 2, "future_group_metadata": {"keep": True}}
    spec["units"][2]["load_scope"] = {"after": "step", "exclude": ["root"]}

    issues = codes(spec)
    assert ("$.concurrent_config.future_group_metadata", "unsupported_concurrent_config_field") in issues
    assert not any(code.startswith("invalid_load_scope") or code.startswith("unknown_load_scope") for _, code in issues)

    omitted = deepcopy(spec)
    omitted["units"][2].pop("load_scope")
    omitted["concurrent_config"].pop("future_group_metadata")
    assert codes(omitted) == []


  def test_concurrent_scope_reports_malformed_missing_and_out_of_range_values_without_touching_unknown_fields(self):
    spec = graph_spec(concurrent_unit())
    spec["concurrent_config"] = {"max_units": 0, "unknown": "retain"}
    spec["units"][2]["load_scope"] = {
        "after": "missing-step",
        "exclude": ["root", "faq", "root", 3],
        "unknown": True,
    }

    issues = codes(spec)
    assert ("$.concurrent_config.max_units", "invalid_concurrent_limit") in issues
    assert ("$.concurrent_config.unknown", "unsupported_concurrent_config_field") in issues
    assert ("$.units[2].load_scope.unknown", "unsupported_load_scope_field") in issues
    assert ("$.units[2].load_scope.after", "unknown_load_scope_after") in issues
    assert ("$.units[2].load_scope.exclude[1]", "unknown_load_scope_exclude") in issues
    assert ("$.units[2].load_scope.exclude[2]", "duplicate_load_scope_exclude") in issues
    assert ("$.units[2].load_scope.exclude[3]", "invalid_load_scope_exclude_item") in issues

    spec["units"][2]["load_scope"] = []
    assert ("$.units[2].load_scope", "invalid_load_scope") in codes(spec)


  def test_concurrent_units_do_not_enter_explicit_graph_even_when_scope_is_present(self):
    spec = graph_spec(concurrent_unit())
    spec["concurrent_config"] = {"max_units": 1}
    spec["units"][2]["load_scope"] = {"exclude": ["step"]}
    assert not any(code == "concurrent_unit_in_graph" for _, code in codes(spec))


if __name__ == "__main__":
    unittest.main()
