"""Deterministic R1 configuration checks for draft/frozen manifests.

This module validates declarative configuration only. R1 keeps Unit ``body``
empty; it does not parse or execute a graph, compose units, or run concurrent
loads. Use ``submitting=True`` for freeze/check validation. Draft validation is
permissive so incomplete editor state can be retained.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .temporal import parse_rfc3339_utc
from .validation import MAX_CONDITION_DEPTH, validate_condition_depth

UNIT_FIELDS = (
    "unit_id", "version", "load_mode", "entry_ports", "reads", "writes",
    "exit_ports", "on_event", "fallback", "max_rounds", "body",
)
LOAD_MODES = {"routed", "concurrent"}
RULE_SCOPES = {"global", "task", "skill"}
RULE_VERDICTS = {"deny", "require", "stop", "dedupe"}
RULE_SEVERITIES = {"normal", "redline"}
FACT_OPERATORS = {
    "eq", "ne", "in", "not_in", "gt", "gte", "lt", "lte", "between",
    "matches", "exists", "is_set", "is_unset", "changed_to",
}
STATE_WINDOWS = {"cycle", "24h", "forever", "session"}
SYSTEM_FIELDS = {
    "system.channel", "system.attempts", "system.request_id", "system.run_id",
    "channel", "attempts",
}
KNOWN_EVENTS = {
    "tool_call", "route_step", "recall_hit", "input_matched", "channel",
    "attempts", "user_hangup", "timeout", "side_effect_unknown", "human_takeover",
}
ROUTE_EVENTS = {"user_hangup", "side_effect_unknown", "timeout", "handoff"}


@dataclass(frozen=True)
class ValidationIssue:
    """One deterministic validation result with an input JSON path."""

    path: str
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "code": self.code, "message": self.message}


def validate_configuration(
    spec: Mapping[str, Any], *, submitting: bool = False
) -> list[ValidationIssue]:
    """Validate an R1 manifest in stable input order.

    Draft saves intentionally retain incomplete intermediate states. Full
    deterministic checks run when freezing/submitting.
    """
    if not isinstance(spec, Mapping):
        return [ValidationIssue("$", "invalid_configuration", "configuration must be an object")]
    validator = _Validator(spec, submitting=submitting)
    validator.validate()
    return validator.issues


class _Validator:
    def __init__(self, spec: Mapping[str, Any], *, submitting: bool) -> None:
        self.spec = spec
        self.submitting = submitting
        self.issues: list[ValidationIssue] = []
        persona = spec.get("persona")
        self.persona = persona if isinstance(persona, Mapping) else {}
        self.fields = _declared_fields(self.persona)
        self.field_types = _declared_field_types(self.persona)
        units = spec.get("units")
        self.units = units if isinstance(units, list) else []
        self.unit_by_id: dict[str, tuple[int, Mapping[str, Any]]] = {}
        self._incoming: set[str] = set()

    def add(self, path: str, code: str, message: str) -> None:
        self.issues.append(ValidationIssue(path, code, message))

    def validate(self) -> None:
        self._validate_root()
        self._index_units()
        for index, unit in enumerate(self.units):
            if isinstance(unit, Mapping):
                self._validate_unit(index, unit)
        self._validate_g0()
        self._validate_hard_rules()
        self._validate_task_blueprints()
        self._validate_isolation()

    def _validate_root(self) -> None:
        if not isinstance(self.spec.get("persona"), Mapping):
            self.add("$.persona", "invalid_persona", "persona must be an object")
        if not isinstance(self.spec.get("units"), list):
            self.add("$.units", "invalid_units", "units must be an array")
        for name in ("g0_gates", "hard_rules", "task_blueprints"):
            if name in self.spec and not isinstance(self.spec[name], list):
                self.add(f"$.{name}", "invalid_collection", f"{name} must be an array")
        for index, unit in enumerate(self.units):
            if not isinstance(unit, Mapping):
                self.add(f"$.units[{index}]", "invalid_unit", "unit must be an object")

    def _index_units(self) -> None:
        for index, unit in enumerate(self.units):
            if not isinstance(unit, Mapping):
                continue
            unit_id = unit.get("unit_id")
            if not isinstance(unit_id, str) or not unit_id.strip():
                continue
            if unit_id in self.unit_by_id:
                self.add(f"$.units[{index}].unit_id", "duplicate_unit_id", f"unit_id {unit_id!r} must be unique")
                continue
            self.unit_by_id[unit_id] = (index, unit)

    def _validate_unit(self, index: int, unit: Mapping[str, Any]) -> None:
        base = f"$.units[{index}]"
        for name in UNIT_FIELDS:
            if name not in unit:
                self.add(f"{base}.{name}", "missing_field", f"{name} is required")
        for name in unit:
            if name not in UNIT_FIELDS:
                self.add(f"{base}.{name}", "unsupported_unit_field", f"{name} is not part of the R1 Unit contract")

        unit_id = unit.get("unit_id")
        if not isinstance(unit_id, str) or not unit_id.strip():
            self.add(f"{base}.unit_id", "invalid_unit_id", "unit_id must be a non-empty string")
        version = unit.get("version")
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            self.add(f"{base}.version", "invalid_version", "version must be a positive frozen integer")
        mode = unit.get("load_mode")
        if not isinstance(mode, str) or mode not in LOAD_MODES:
            self.add(f"{base}.load_mode", "invalid_load_mode", "load_mode must be routed or concurrent")
        elif mode == "concurrent" and self.submitting:
            self.add(f"{base}.load_mode", "unsupported_concurrent", "concurrent loading is declared but not submittable in R1")

        reads = _string_list(unit.get("reads"))
        writes = _string_list(unit.get("writes"))
        self._validate_field_list(index, "reads", unit.get("reads"))
        self._validate_field_list(index, "writes", unit.get("writes"))
        if not isinstance(unit.get("reads"), list):
            self.add(f"{base}.reads", "invalid_field_list", "reads must be an array of field names")
        if not isinstance(unit.get("writes"), list):
            self.add(f"{base}.writes", "invalid_field_list", "writes must be an array of field names")
        self._validate_reads(index, unit, reads, writes)

        entry_ports = unit.get("entry_ports")
        if not isinstance(entry_ports, list):
            self.add(f"{base}.entry_ports", "invalid_entry_ports", "entry_ports must be an array")
            entry_ports = []
        elif not entry_ports:
            self.add(f"{base}.entry_ports", "missing_entry_port", "unit must declare at least one entry port")
        exit_ports = unit.get("exit_ports")
        if not isinstance(exit_ports, list):
            self.add(f"{base}.exit_ports", "invalid_exit_ports", "exit_ports must be an array")
            exit_ports = []
        elif not exit_ports:
            self.add(f"{base}.exit_ports", "missing_exit_port", "unit must declare at least one exit port")
        self._validate_ports(index, unit, entry_ports, exit_ports, reads, writes)
        self._validate_events(index, unit)
        self._validate_fallback(index, unit)
        rounds = unit.get("max_rounds")
        if not isinstance(rounds, int) or isinstance(rounds, bool) or rounds < 1:
            self.add(f"{base}.max_rounds", "invalid_max_rounds", "max_rounds must be a positive integer")
        if unit.get("body") != {}:
            self.add(f"{base}.body", "body_not_empty", "R1 reserves body as an empty object")

    def _validate_field_list(self, index: int, name: str, values: Any) -> None:
        if not isinstance(values, list):
            return
        for offset, field_name in enumerate(values):
            if not isinstance(field_name, str) or not field_name.strip():
                self.add(f"$.units[{index}].{name}[{offset}]", "invalid_field_name", "field name must not be empty")

    def _validate_reads(self, index: int, unit: Mapping[str, Any], reads: list[str], writes: list[str]) -> None:
        earlier_writes: set[str] = set()
        for other_id, (other_index, other) in self.unit_by_id.items():
            if other_index < index and other_id != unit.get("unit_id"):
                earlier_writes.update(_string_list(other.get("writes")))
        available = self.fields | earlier_writes | set(writes) | SYSTEM_FIELDS
        for offset, field_name in enumerate(reads):
            if not _is_system_field(field_name) and field_name not in available:
                self.add(
                    f"$.units[{index}].reads[{offset}]", "undeclared_read",
                    "read field must be declared, system-provided, previously written, or written by this unit",
                )

    def _validate_ports(
        self, index: int, unit: Mapping[str, Any], entry_ports: list[Any],
        exit_ports: list[Any], reads: list[str], writes: list[str],
    ) -> None:
        base = f"$.units[{index}]"
        entry_ids: set[str] = set()
        exit_ids: set[str] = set()
        for offset, port in enumerate(entry_ports):
            path = f"{base}.entry_ports[{offset}]"
            if not isinstance(port, Mapping):
                self.add(path, "invalid_entry_port", "entry port must be an object")
                continue
            port_id = port.get("port")
            if not isinstance(port_id, str) or not port_id.strip():
                self.add(f"{path}.port", "invalid_port_id", "port must be a non-empty string")
            elif port_id in entry_ids:
                self.add(f"{path}.port", "duplicate_port_id", "entry port names must be unique")
            else:
                entry_ids.add(port_id)
            if "requires" not in port:
                self.add(f"{path}.requires", "missing_port_requires", "entry port must declare requires")
                continue
            if not isinstance(port.get("requires"), list):
                self.add(f"{path}.requires", "invalid_port_requires", "requires must be an array of field names")
                continue
            for req_index, field_name in enumerate(port["requires"]):
                if not isinstance(field_name, str):
                    self.add(f"{path}.requires[{req_index}]", "invalid_field_name", "requirement must be a field name")
                    continue
                if field_name not in reads and not _is_system_field(field_name):
                    self.add(
                        f"{path}.requires[{req_index}]", "requirement_not_read",
                        "entry requirements must be declared in reads or be system fields",
                    )

        for offset, port in enumerate(exit_ports):
            path = f"{base}.exit_ports[{offset}]"
            if not isinstance(port, Mapping):
                self.add(path, "invalid_exit_port", "exit port must be an object")
                continue
            port_id = port.get("port")
            if not isinstance(port_id, str) or not port_id.strip():
                self.add(f"{path}.port", "invalid_port_id", "port must be a non-empty string")
            elif port_id in exit_ids:
                self.add(f"{path}.port", "duplicate_port_id", "exit port names must be unique")
            else:
                exit_ids.add(port_id)
            completion = port.get("completion")
            if not isinstance(completion, Mapping):
                self.add(f"{path}.completion", "missing_completion", "exit port must declare a completion object")
            else:
                if not any(key in completion for key in ("deterministic", "llm")):
                    self.add(f"{path}.completion", "missing_completion_condition", "completion must contain deterministic and/or llm criteria")
                if "deterministic" in completion:
                    condition = completion["deterministic"]
                    self._validate_condition(
                        condition,
                        f"{path}.completion.deterministic",
                        deterministic_only=False,
                        allow_legacy=True,
                    )
                    for field_path, field_name in _condition_fields(condition, f"{path}.completion.deterministic"):
                        if field_name not in writes and not _is_system_field(field_name):
                            self.add(field_path, "undeclared_completion_field", "completion fields must be written by this unit or provided by the system")
                llm_completion = completion.get("llm")
                if llm_completion is not None and not isinstance(llm_completion, (str, Mapping)):
                    self.add(f"{path}.completion.llm", "invalid_llm_completion", "llm completion must be text or an object")
            exits = port.get("exits")
            if not isinstance(exits, list):
                self.add(f"{path}.exits", "invalid_exits", "exits must be an array of target unit or self.port ids")
                continue
            if not exits:
                self.add(f"{path}.exits", "empty_exits", "each exit port must have at least one candidate destination")
            for exit_index, target in enumerate(exits):
                target_path = f"{path}.exits[{exit_index}]"
                target_id = self._unit_target(target, unit, exit_ids)
                if target_id is None:
                    self.add(target_path, "unknown_unit_reference", "exit target must be a known routed unit or self.<exit_port>")
                elif target_id != unit.get("unit_id"):
                    self._incoming.add(target_id)

    def _validate_events(self, index: int, unit: Mapping[str, Any]) -> None:
        events = unit.get("on_event")
        base = f"$.units[{index}].on_event"
        if not isinstance(events, list):
            self.add(base, "invalid_events", "on_event must be an array")
            return
        for offset, event in enumerate(events):
            path = f"{base}[{offset}]"
            if not isinstance(event, Mapping):
                self.add(path, "invalid_event", "event handler must be an object")
                continue
            event_name = event.get("event")
            if not isinstance(event_name, str) or event_name not in ROUTE_EVENTS:
                self.add(f"{path}.event", "invalid_event_name", "event must be a supported boundary event")
            scope = event.get("scope")
            if scope not in {"self", "subtree"}:
                self.add(f"{path}.scope", "invalid_event_scope", "unit event scope must be self or subtree; global belongs to the version")
            if "goto" not in event:
                self.add(f"{path}.goto", "missing_event_target", "event handler must declare goto")
            elif self._unit_target(event.get("goto"), unit, _exit_port_ids(unit)) is None:
                self.add(f"{path}.goto", "invalid_event_target", "event target must be a known routed unit or this unit's exit port")
            if "when" in event:
                self._validate_condition(event["when"], f"{path}.when", deterministic_only=True)

    def _validate_fallback(self, index: int, unit: Mapping[str, Any]) -> None:
        fallback = unit.get("fallback")
        path = f"$.units[{index}].fallback"
        if not isinstance(fallback, (str, Mapping)) or not fallback:
            self.add(path, "missing_fallback", "fallback must declare clarify, a default unit, or human handoff")
            return
        if isinstance(fallback, str):
            kind, target = fallback, None
        else:
            kind = fallback.get("kind")
            target = fallback.get("unit_id", fallback.get("target"))
        if not isinstance(kind, str) or kind not in {"clarify", "default_unit", "human", "handoff"}:
            self.add(f"{path}.kind", "invalid_fallback", "fallback kind must be clarify, default_unit, or human")
        if kind == "default_unit":
            if not isinstance(target, str) or target not in self.unit_by_id or self.unit_by_id[target][1].get("load_mode") != "routed":
                self.add(f"{path}.unit_id", "invalid_fallback_target", "default_unit fallback must reference a known routed unit")
            elif target != unit.get("unit_id"):
                self._incoming.add(target)

    def _validate_condition(
        self,
        condition: Any,
        path: str,
        *,
        deterministic_only: bool,
        allow_legacy: bool = False,
    ) -> None:
        malformed = False
        nondeterministic = False
        unknown_fields: list[tuple[str, str]] = []
        unknown_ops: list[tuple[str, str]] = []

        def walk(node: Any, node_path: str) -> Any:
            nonlocal malformed, nondeterministic
            if not isinstance(node, Mapping):
                malformed = True
                return {"arg": "invalid"}
            if not node:
                return {}
            if "llm" in node or "llm_judge" in node:
                nondeterministic = True
                return {"llm": node.get("llm", node.get("llm_judge"))}
            combinators = {
                "all_of": ("all", True), "any_of": ("any", True), "none_of": ("not", False),
                "all": ("all", True), "any": ("any", True), "not": ("not", False),
            }
            found = [key for key in combinators if key in node]
            if found:
                if len(found) != 1 or len(node) != 1:
                    malformed = True
                key = found[0]
                normalized, list_required = combinators[key]
                children = node[key]
                if list_required and (not isinstance(children, list) or not children):
                    malformed = True
                    children = []
                elif not list_required and (not isinstance(children, list) or len(children) != 1):
                    malformed = True
                    children = children if isinstance(children, list) else [children]
                return {normalized: [walk(item, f"{node_path}.{key}[{i}]") for i, item in enumerate(children)]}
            atom_types = [key for key in ("fact", "event", "state") if key in node]
            if atom_types:
                if len(atom_types) != 1 or len(node) != 1:
                    malformed = True
                kind = atom_types[0]
                atom = node[kind]
                if not isinstance(atom, Mapping):
                    malformed = True
                    return {"arg": "invalid"}
                if kind == "fact":
                    field_name, op = atom.get("field"), atom.get("op")
                    if not isinstance(field_name, str) or not field_name:
                        malformed = True
                    elif field_name not in self.fields and not _is_system_field(field_name):
                        unknown_fields.append((f"{node_path}.fact.field", field_name))
                    if not isinstance(op, str) or op not in FACT_OPERATORS:
                        unknown_ops.append((f"{node_path}.fact.op", str(op)))
                    self._validate_operator_value(atom, field_name, op, f"{node_path}.fact")
                    return {"arg": field_name or "invalid", "op": op}
                if kind == "event":
                    name = atom.get("event")
                    if not isinstance(name, str) or name not in KNOWN_EVENTS:
                        malformed = True
                    return {"arg": f"event.{name or 'invalid'}"}
                metric, window, op = atom.get("metric"), atom.get("window", "cycle"), atom.get("op")
                if not isinstance(metric, str) or not metric or not isinstance(window, str) or window not in STATE_WINDOWS:
                    malformed = True
                if not isinstance(op, str) or op not in FACT_OPERATORS:
                    unknown_ops.append((f"{node_path}.state.op", str(op)))
                self._validate_operator_value(atom, metric, op, f"{node_path}.state")
                return {"arg": f"state.{metric or 'invalid'}"}
            if allow_legacy:
                legacy_field = node.get("field", node.get("arg", node.get("path")))
                if isinstance(legacy_field, str) and legacy_field:
                    op = node.get("op", "eq")
                    if not isinstance(op, str) or op not in FACT_OPERATORS:
                        unknown_ops.append((f"{node_path}.op", str(op)))
                    if legacy_field not in self.fields and not _is_system_field(legacy_field):
                        unknown_fields.append((f"{node_path}.field", legacy_field))
                    return {"arg": legacy_field, "op": op}
            malformed = True
            return {"arg": "invalid"}

        normalized = walk(condition, path)
        if nondeterministic:
            message = "this condition surface must be deterministic" if deterministic_only else "HardRule v0.2 conditions must be deterministic"
            self.add(path, "nondeterministic_condition", message)
            return
        if malformed:
            self.add(path, "invalid_condition", "condition must use fact/event/state atoms and supported combinators")
            return
        for field_path, field_name in unknown_fields:
            self.add(field_path, "undeclared_condition_field", f"condition field {field_name!r} is not declared")
        for op_path, operator in unknown_ops:
            self.add(op_path, "invalid_condition_operator", f"operator {operator!r} is not supported")
        if validate_condition_depth([(path, normalized)], max_depth=MAX_CONDITION_DEPTH):
            self.add(path, "condition_too_deep", f"condition nesting exceeds {MAX_CONDITION_DEPTH} levels")

    def _validate_g0(self) -> None:
        gates = self.spec.get("g0_gates", [])
        if not isinstance(gates, list):
            return
        for index, gate in enumerate(gates):
            path = f"$.g0_gates[{index}]"
            if not isinstance(gate, Mapping):
                self.add(path, "invalid_g0_gate", "G0 gate must be an object")
                continue
            if "verdict" in gate:
                self.add(f"{path}.verdict", "g0_verdict_not_allowed", "G0 declares route outcome, not a HardRule verdict")
            if not isinstance(gate.get("gate_id"), str) or not gate.get("gate_id", "").strip():
                self.add(f"{path}.gate_id", "invalid_gate_id", "gate_id must be a non-empty string")
            if "when" not in gate:
                self.add(f"{path}.when", "missing_g0_condition", "G0 gate must declare a deterministic when condition")
            else:
                self._validate_condition(gate["when"], f"{path}.when", deterministic_only=True)
            target = gate.get("route_to")
            if isinstance(target, str) and target in {"block", "suspend"}:
                continue
            if not isinstance(target, str) or target not in self.unit_by_id:
                self.add(f"{path}.route_to", "invalid_g0_target", "route_to must be block, suspend, or a known routed unit")
                continue
            if self.unit_by_id[target][1].get("load_mode") != "routed":
                self.add(f"{path}.route_to", "invalid_g0_target", "G0 may route only to a routed unit")
            else:
                self._incoming.add(target)

    def _validate_hard_rules(self) -> None:
        rules = self.spec.get("hard_rules", [])
        if not isinstance(rules, list):
            return
        for index, rule in enumerate(rules):
            path = f"$.hard_rules[{index}]"
            if not isinstance(rule, Mapping):
                self.add(path, "invalid_hard_rule", "HardRule must be an object")
                continue
            if not isinstance(rule.get("rule_id"), str) or not rule.get("rule_id", "").strip():
                self.add(f"{path}.rule_id", "invalid_rule_id", "rule_id must be a non-empty string")
            if "when" not in rule:
                self.add(f"{path}.when", "missing_rule_condition", "HardRule v0.2 must declare when; use {} for unconditional rules")
            else:
                self._validate_condition(rule["when"], f"{path}.when", deterministic_only=True)

            verdict = rule.get("verdict")
            if not isinstance(verdict, Mapping):
                self.add(f"{path}.verdict", "invalid_verdict", "verdict must be an object")
                verdict = {}
            kind = verdict.get("type")
            if not isinstance(kind, str) or kind not in RULE_VERDICTS:
                self.add(f"{path}.verdict.type", "invalid_verdict", "verdict type must be deny, require, stop, or dedupe")
                if not isinstance(verdict.get("reason"), str) or not verdict.get("reason", "").strip():
                    self.add(f"{path}.verdict.reason", "missing_verdict_reason", "deny/require verdicts need a reason")
            elif kind == "deny":
                self._required_text(verdict, "reason", f"{path}.verdict", "missing_verdict_reason")
                self._required_text(verdict, "fallback", f"{path}.verdict", "missing_verdict_fallback")
            elif kind == "require":
                self._required_text(verdict, "reason", f"{path}.verdict", "missing_verdict_reason")
                self._required_text(verdict, "target", f"{path}.verdict", "missing_verdict_target")
            elif kind == "stop":
                self._required_text(verdict, "stop_reason", f"{path}.verdict", "missing_stop_reason")
            else:
                self._required_text(verdict, "idempotency_key", f"{path}.verdict", "missing_idempotency_key")

            enforce = rule.get("enforce")
            if not isinstance(enforce, Mapping):
                self.add(f"{path}.enforce", "invalid_enforce", "enforce must be an object")
                continue
            scope = enforce.get("scope")
            if not isinstance(scope, str) or scope not in RULE_SCOPES:
                self.add(f"{path}.enforce.scope", "invalid_rule_scope", "scope must be global, task, or skill")
            self._required_text(enforce, "reason", f"{path}.enforce", "missing_enforce_reason")
            priority = enforce.get("priority")
            if not isinstance(priority, (int, float)) or isinstance(priority, bool):
                self.add(f"{path}.enforce.priority", "invalid_priority", "priority must be numeric")
            if not isinstance(enforce.get("customer_facing"), bool):
                self.add(f"{path}.enforce.customer_facing", "invalid_customer_facing", "customer_facing must be boolean")
            severity = enforce.get("severity")
            if not isinstance(severity, str) or severity not in RULE_SEVERITIES:
                self.add(f"{path}.enforce.severity", "invalid_severity", "severity must be normal or redline")
            self._validate_rule_validity(enforce, f"{path}.enforce")

    def _validate_rule_validity(self, enforce: Mapping[str, Any], path: str) -> None:
        parsed = {}
        for key in ("valid_from", "valid_until"):
            value = enforce.get(key)
            if value is None:
                continue
            timestamp = parse_rfc3339_utc(value)
            if timestamp is None:
                self.add(
                    f"{path}.{key}", "invalid_rule_time",
                    f"{key} must be an RFC 3339 timestamp with a timezone",
                )
                continue
            parsed[key] = timestamp
        if (
            "valid_from" in parsed and "valid_until" in parsed
            and parsed["valid_until"] <= parsed["valid_from"]
        ):
            self.add(
                f"{path}.valid_until", "invalid_rule_time_order",
                "valid_until must be later than valid_from",
            )

    def _validate_task_blueprints(self) -> None:
        blueprints = self.spec.get("task_blueprints", [])
        if not isinstance(blueprints, list):
            return
        seen: set[str] = set()
        for index, blueprint in enumerate(blueprints):
            path = f"$.task_blueprints[{index}]"
            if not isinstance(blueprint, Mapping):
                self.add(path, "invalid_task_blueprint", "task blueprint must be an object")
                continue
            key = blueprint.get("blueprint_key")
            if not isinstance(key, str) or not key.strip():
                if self.submitting:
                    self.add(
                        f"{path}.blueprint_key", "missing_blueprint_key",
                        "a frozen task blueprint requires a stable blueprint_key",
                    )
                continue
            if key in seen:
                self.add(
                    f"{path}.blueprint_key", "duplicate_blueprint_key",
                    f"blueprint_key {key!r} must be unique within this expert",
                )
            seen.add(key)

    def _validate_operator_value(
        self, atom: Mapping[str, Any], field_name: Any, operator: Any, path: str
    ) -> None:
        if not isinstance(operator, str) or operator not in FACT_OPERATORS:
            return
        if operator not in {"exists", "is_set", "is_unset"} and "value" not in atom:
            self.add(f"{path}.value", "missing_condition_value", f"operator {operator!r} requires a value")
            return
        value = atom.get("value")
        if operator in {"in", "not_in"} and not isinstance(value, list):
            self.add(f"{path}.value", "invalid_condition_value", f"operator {operator!r} requires an array value")
        if operator == "between" and (not isinstance(value, list) or len(value) != 2):
            self.add(f"{path}.value", "invalid_condition_value", "operator 'between' requires a two-item array")
        field_type = self.field_types.get(field_name) if isinstance(field_name, str) else None
        if operator == "matches" and field_type not in {None, "string", "text"}:
            self.add(f"{path}.op", "incompatible_condition_operator", "matches requires a string field")
        if operator in {"gt", "gte", "lt", "lte", "between"} and field_type not in {
            None, "number", "integer", "int", "float", "date", "datetime",
        }:
            self.add(f"{path}.op", "incompatible_condition_operator", f"{operator} requires a numeric or date field")

    def _required_text(self, obj: Mapping[str, Any], key: str, path: str, code: str) -> None:
        value = obj.get(key)
        if not isinstance(value, str) or not value.strip():
            self.add(f"{path}.{key}", code, f"{key} is required")

    def _validate_isolation(self) -> None:
        if not self.submitting:
            return
        entries = set(_string_list(self.persona.get("entry_unit_ids", [])))
        for unit_id, (index, unit) in self.unit_by_id.items():
            if unit.get("load_mode") == "routed" and unit_id not in entries and unit_id not in self._incoming:
                self.add(f"$.units[{index}].unit_id", "isolated_routed_unit", "routed unit is not an entry and has no incoming manifest reference")

    def _unit_target(self, target: Any, unit: Mapping[str, Any], own_exit_ports: set[str]) -> str | None:
        if not isinstance(target, str):
            return None
        if target.startswith("self."):
            return unit.get("unit_id") if target[5:] in own_exit_ports else None
        indexed = self.unit_by_id.get(target)
        if indexed is None or indexed[1].get("load_mode") != "routed":
            return None
        return target


def _declared_fields(persona: Mapping[str, Any]) -> set[str]:
    raw = persona.get("fields", {})
    if isinstance(raw, Mapping):
        return {str(name) for name in raw}
    if isinstance(raw, list):
        names: set[str] = set()
        for field in raw:
            if isinstance(field, Mapping):
                name = field.get("field", field.get("field_id", field.get("name", field.get("id"))))
                if isinstance(name, str) and name:
                    names.add(name)
        return names
    return set()


def _declared_field_types(persona: Mapping[str, Any]) -> dict[str, str]:
    raw = persona.get("fields", {})
    declarations: list[tuple[str, Any]] = []
    if isinstance(raw, Mapping):
        declarations = [(str(name), value) for name, value in raw.items()]
    elif isinstance(raw, list):
        for field in raw:
            if not isinstance(field, Mapping):
                continue
            name = field.get("field", field.get("field_id", field.get("name", field.get("id"))))
            if isinstance(name, str):
                declarations.append((name, field))
    types: dict[str, str] = {}
    for name, declaration in declarations:
        if isinstance(declaration, Mapping) and isinstance(declaration.get("type"), str):
            types[name] = declaration["type"].lower()
    return types


def _string_list(value: Any) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _is_system_field(name: str) -> bool:
    return name in SYSTEM_FIELDS or name.startswith("system.")


def _exit_port_ids(unit: Mapping[str, Any]) -> set[str]:
    ports = unit.get("exit_ports")
    if not isinstance(ports, list):
        return set()
    return {port["port"] for port in ports if isinstance(port, Mapping) and isinstance(port.get("port"), str)}


def _condition_fields(node: Any, path: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if not isinstance(node, Mapping):
        return out
    if "fact" in node and isinstance(node["fact"], Mapping):
        name = node["fact"].get("field")
        if isinstance(name, str):
            out.append((f"{path}.fact.field", name))
        return out
    for key in ("field", "arg", "path"):
        name = node.get(key)
        if isinstance(name, str):
            out.append((f"{path}.{key}", name))
            return out
    for key in ("all_of", "any_of", "none_of", "all", "any", "not"):
        children = node.get(key)
        if isinstance(children, list):
            for index, child in enumerate(children):
                out.extend(_condition_fields(child, f"{path}.{key}[{index}]"))
    return out


__all__ = ["ValidationIssue", "validate_configuration"]
