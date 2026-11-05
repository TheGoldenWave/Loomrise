"""R3 graph draft checks. Supported deterministic graph subsets may be frozen;
unsupported side-effect atoms remain blocked at their own paths.

No layout or vendor state belongs here. Exact Unit references, local ports,
composition DAGs, bounded execution cycles and boundary events are checked by
the same service used by HTTP, CLI and MCP.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
import math
import re
from typing import Any

from .config_validation import (
    CHANGED_TO_BLOCKED_REASON, _condition_fields, _is_system_field, _string_list,
)

SCHEMA_VERSION = "unit-graph-v1"

# The graph interpreter currently has a deliberately small durable state
# provider.  Keep the freeze contract aligned with that runtime subset rather
# than allowing a draft to freeze and fail only when its first request runs.
_RUNTIME_STATE_WINDOWS = frozenset({"cycle", "24h", "forever"})
_RUNTIME_STATE_METRICS = frozenset({"attempts", "runs"})
_RUNTIME_STATE_OPERATORS = frozenset({"gt", "gte", "lt", "lte", "eq", "ne"})
_RUNTIME_FACT_OPERATORS = frozenset({
    "eq", "ne", "exists", "is_set", "is_unset", "in", "not_in", "gt", "gte", "lt", "lte", "between",
    "matches",
})
_MATCHES_MAX_PATTERN_LENGTH = 128
_MATCHES_MAX_VALUE_LENGTH = 1024


def _safe_matches_pattern(pattern: Any) -> bool:
    if not isinstance(pattern, str) or not pattern or len(pattern) > _MATCHES_MAX_PATTERN_LENGTH:
        return False
    in_class = False
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "\\":
            if index + 1 == len(pattern):
                return False
            escaped = pattern[index + 1]
            if escaped.isdigit() or (escaped.isalpha() and escaped not in "dDsSwWAbBZ"):
                return False
            index += 2
            continue
        if in_class:
            if char == "]":
                in_class = False
            index += 1
            continue
        if char == "[":
            in_class = True
        elif char in "()|*+?":
            return False
        elif char == "{":
            count = re.match(r"\{([0-9]{1,2})\}", pattern[index:])
            if count is None or int(count.group(1)) > 64:
                return False
            index += len(count.group(0))
            continue
        elif char == "}":
            return False
        index += 1
    if in_class:
        return False
    try:
        re.compile(pattern)
    except re.error:
        return False
    return True


def validate_graph_configuration(v: Any) -> None:
    root = v.spec.get("orchestration")
    if not isinstance(root, Mapping):
        v.add("$.orchestration", "invalid_orchestration", "orchestration must be an object")
        return
    if root.get("schema_version") != SCHEMA_VERSION:
        v.add("$.orchestration.schema_version", "unsupported_graph_schema", f"schema_version must be {SCHEMA_VERSION}")
        return
    if v.submitting:
        # The graph is hashed and persisted as JSON when a candidate freezes.
        # Reject values that Python can keep in memory but JSON cannot represent
        # deterministically (notably NaN/Infinity and tuple/set-like objects).
        _validate_json_shape(v, root, "$.orchestration")
        for index, unit in enumerate(v.units):
            if isinstance(unit, Mapping) and "body" in unit:
                _validate_json_shape(v, unit.get("body"), f"$.units[{index}].body")
    if v.submitting:
        # GraphRuntime also evaluates version-level G0 gates.  Keep their
        # freeze contract aligned with the same durable state-window provider.
        _reject_runtime_unsupported_states(
            v, v.spec.get("g0_gates", []), "$.g0_gates", include_units=False,
        )
    # R3 supports deterministic routing, say/judge atoms, waits and event
    # boundaries. Unsupported side-effect atoms keep their own precise issue;
    # a supported graph must not be blocked by a blanket graph-wide refusal.
    bindings = v.spec.get("unit_skill_bindings", {})
    if bindings and not isinstance(bindings, Mapping):
        v.add("$.unit_skill_bindings", "invalid_unit_skill_bindings", "unit_skill_bindings must be an object")
    elif isinstance(bindings, Mapping):
        for unit_id, skill_id in bindings.items():
            if unit_id not in v.unit_by_id:
                v.add(f"$.unit_skill_bindings.{unit_id}", "unknown_binding_unit", "binding must reference a declared Unit")
            if not isinstance(skill_id, str) or not skill_id.strip():
                v.add(f"$.unit_skill_bindings.{unit_id}", "invalid_binding_skill", "binding target must be a non-empty Skill id")
    composition: dict[str, set[str]] = {}
    _graph(v, root, "$.orchestration", None)
    _reject_runtime_unsupported_states(v, root, "$.orchestration")
    for uid, (index, unit) in v.unit_by_id.items():
        path = f"$.units[{index}]"
        body = unit.get("body")
        for name in ("reads", "writes"):
            for offset, field in enumerate(_string_list(unit.get(name))):
                if field not in v.fields and not _is_system_field(field):
                    v.add(f"{path}.{name}[{offset}]", "undeclared_graph_field", "graph fields must be declared in persona.fields")
        if not isinstance(body, Mapping):
            v.add(f"{path}.body", "invalid_graph_body", "Unit body must be an object")
            continue
        body_nodes = body.get("nodes") if isinstance(body.get("nodes"), list) else []
        wait_nodes = {
            node.get("id"): _resolve(v, node.get("unit_ref"))
            for node in body_nodes
            if isinstance(node, Mapping) and isinstance(node.get("id"), str)
            and _resolve(v, node.get("unit_ref")) is not None
        } if body.get("kind") == "graph" else {}
        _waits(v, unit.get("waits"), f"{path}.waits", wait_nodes, unit)
        if v.submitting:
            exit_ports = unit.get("exit_ports") if isinstance(unit.get("exit_ports"), list) else []
            for offset, port in enumerate(exit_ports):
                completion = port.get("completion") if isinstance(port, Mapping) else None
                if isinstance(completion, Mapping) and "llm" in completion and (
                        not isinstance(completion['llm'], str) or not completion['llm'].strip()):
                    v.add(f"{path}.exit_ports[{offset}].completion.llm", "unsupported_runtime_completion",
                          "model completion requires a resolved, non-empty text criterion")
        if body.get("kind") == "graph":
            composition[uid] = _graph(v, body, f"{path}.body", unit)
        else:
            _atom(v, body, f"{path}.body", unit)
            if len(_ports(unit, "entry_ports")) != 1 or len(_ports(unit, "exit_ports")) != 1:
                v.add(path, "invalid_atom_ports", "atoms require exactly one entry and one exit port")
            _events(v, unit.get("on_event"), f"{path}.on_event", {}, unit)
            _fallback(v, unit.get("fallback"), f"{path}.fallback", {}, unit)
        for name in ("entry_ports", "exit_ports"):
            for port in _ports(unit, name):
                if not _local_id(port):
                    v.add(f"{path}.{name}", "invalid_graph_port_id", "port ids must be local and contain no dots")
    if _has_cycle(composition):
        v.add("$.units", "composition_cycle", "Unit composition must be a DAG")
    else:
        from .graph_dataflow import validate_graph_dataflow
        validate_graph_dataflow(v)


def _reject_runtime_unsupported_states(
    v: Any, root: Mapping[str, Any], path: str, *, include_units: bool = True,
) -> None:
    """Block graph state predicates the current interpreter cannot evaluate.

    ``config_validation`` intentionally accepts the broader domain condition
    vocabulary for drafts.  A graph candidate, however, must not advertise a
    runtime path that ``GraphRuntime`` will reject later.  Walk the root graph
    and every declared Unit once so nested graph bodies and unit-level event or
    completion conditions receive the same freeze-time guard.
    """

    if not v.submitting:
        return

    def walk(value: Any, value_path: str) -> None:
        if isinstance(value, Mapping):
            predicate = value.get("state")
            if isinstance(predicate, Mapping):
                for key in [name for name in predicate if name not in {'metric', 'window', 'op', 'value'}]:
                    v.add(f'{value_path}.state.{key}', 'unsupported_runtime_state_field',
                          'field is not part of the graph state predicate')
                window = predicate.get("window")
                metric = predicate.get("metric")
                operator = predicate.get("op")
                if not isinstance(window, str) or window not in _RUNTIME_STATE_WINDOWS:
                    v.add(
                        f"{value_path}.state.window",
                        "unsupported_runtime_state_window",
                        "graph runtime supports service-cycle, 24h and forever state windows",
                    )
                if not isinstance(metric, str) or metric not in _RUNTIME_STATE_METRICS:
                    v.add(
                        f"{value_path}.state.metric",
                        "unsupported_runtime_state_metric",
                        "graph runtime supports only attempts and runs state metrics",
                    )
                if not isinstance(operator, str) or operator not in _RUNTIME_STATE_OPERATORS:
                    v.add(
                        f"{value_path}.state.op",
                        "unsupported_runtime_state_operator",
                        "graph runtime supports only gt/gte/lt/lte/eq/ne state operators",
                    )
                value_number = predicate.get("value")
                if (
                    not isinstance(value_number, (int, float))
                    or isinstance(value_number, bool)
                    or not math.isfinite(value_number)
                ):
                    v.add(
                        f"{value_path}.state.value",
                        "unsupported_runtime_state_value",
                        "graph runtime state comparisons require a finite numeric value",
                    )
            fact = value.get("fact")
            if isinstance(fact, Mapping):
                for key in [name for name in fact if name not in {'field', 'op', 'value'}]:
                    v.add(f'{value_path}.fact.{key}', 'unsupported_runtime_fact_field',
                          'field is not part of the graph fact predicate')
            fact_operator = fact.get("op", "eq") if isinstance(fact, Mapping) else None
            if isinstance(fact, Mapping) and (
                not isinstance(fact_operator, str) or fact_operator not in _RUNTIME_FACT_OPERATORS
            ):
                message = "graph runtime does not integrate this fact operator"
                if fact_operator == "changed_to":
                    # 明确诊断：不是「暂未接入」，而是缺少可信前值来源，禁止仅凭表达式启用。
                    message = CHANGED_TO_BLOCKED_REASON
                v.add(
                    f"{value_path}.fact.op",
                    "unsupported_runtime_fact_operator",
                    message,
                )
            if isinstance(fact, Mapping) and fact_operator == "between":
                bounds = fact.get("value")
                if (
                    not isinstance(bounds, list) or len(bounds) != 2
                    or any(not isinstance(item, (int, float)) or isinstance(item, bool)
                           or not math.isfinite(item) for item in bounds)
                    or bounds[0] > bounds[1]
                    or v.field_types.get(fact.get("field")) not in {None, "number", "integer", "int", "float"}
                ):
                    v.add(
                        f"{value_path}.fact.value", "unsupported_runtime_fact_value",
                        "graph between comparisons require an ordered pair of finite numeric bounds",
                    )
            if isinstance(fact, Mapping) and fact_operator == "matches" and not _safe_matches_pattern(fact.get("value")):
                v.add(
                    f"{value_path}.fact.value", "unsupported_runtime_fact_value",
                    "graph matches requires a safe string regex of at most 128 characters",
                )
            event = value.get("event")
            if isinstance(event, Mapping) and (
                set(event) - {"event", "attributes"}
                or ("attributes" in event and not isinstance(event.get("attributes"), Mapping))
            ):
                v.add(
                    f"{value_path}.event",
                    "unsupported_runtime_event_attributes",
                    "graph runtime supports event names and attributes only",
                )
            if any(isinstance(value.get(kind), Mapping) for kind in ('state', 'fact', 'event')):
                return
            for key, child in value.items():
                walk(child, f"{value_path}.{key}")
            return
        if isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{value_path}[{index}]")

    walk(root, path)
    if include_units:
        for index, unit in enumerate(v.units):
            if isinstance(unit, Mapping):
                walk(unit, f"$.units[{index}]")


def _graph(v: Any, graph: Mapping[str, Any], path: str, owner: Mapping[str, Any] | None) -> set[str]:
    allowed = {"kind", "routing", "nodes", "edges"}
    if owner is None:
        allowed |= {"schema_version", "entry", "input_fields", "on_event", "fallback"}
    _keys(v, graph, allowed, path)
    if graph.get("kind") != "graph":
        v.add(f"{path}.kind", "invalid_graph_kind", "graph kind must be graph")
    routing = graph.get("routing")
    if not isinstance(routing, Mapping) or routing.get("mode") not in ("deterministic", "llm", "hybrid") or set(routing) != {"mode"}:
        v.add(f"{path}.routing", "invalid_routing_mode", "each graph requires routing: {mode: deterministic|llm|hybrid}")
    allow_positive_llm = isinstance(routing, Mapping) and routing.get("mode") in ("llm", "hybrid")
    nodes, edges = graph.get("nodes"), graph.get("edges")
    if not isinstance(nodes, list):
        v.add(f"{path}.nodes", "invalid_graph_nodes", "nodes must be an array")
        nodes = []
    if not isinstance(edges, list):
        v.add(f"{path}.edges", "invalid_graph_edges", "edges must be an array")
        edges = []
    resolved: dict[str, Mapping[str, Any]] = {}
    ids: set[str] = set()
    refs: set[str] = set()
    for i, node in enumerate(nodes):
        p = f"{path}.nodes[{i}]"
        if not isinstance(node, Mapping):
            v.add(p, "invalid_graph_node", "node must be an object")
            continue
        _keys(v, node, {"id", "unit_ref"}, p)
        node_id = node.get("id")
        if not _local_id(node_id) or node_id in ids:
            v.add(f"{p}.id", "invalid_graph_node_id", "node ids must be unique local ids without dots")
            continue
        ids.add(node_id)
        child = _resolve(v, node.get("unit_ref"))
        if child is None:
            v.add(f"{p}.unit_ref", "unfrozen_unit_reference", "reference must match an exact declared unit_id and positive integer version")
        elif child.get("load_mode") != "routed":
            v.add(f"{p}.unit_ref", "concurrent_unit_in_graph", "concurrent Units cannot participate in routed graphs")
        else:
            resolved[node_id] = child
            refs.add(child["unit_id"])

    starts: list[str] = []
    if owner is None:
        inputs = graph.get("input_fields", [])
        if not isinstance(inputs, list) or any(not isinstance(f, str) or f not in v.fields for f in inputs):
            v.add(f"{path}.input_fields", "invalid_graph_inputs", "input_fields must list declared persona fields")
        entries = [(f"{path}.entry", graph.get("entry"))]
    else:
        entries = [(f"{path.removesuffix('.body')}.entry_ports[{i}].goto", port.get("goto")) for i, port in enumerate(_ports(owner, "entry_ports").values())]
    for p, entry in entries:
        if not _target(entry, resolved, owner, entry=True):
            v.add(p, "invalid_entry_mapping", "entry must name a local node entry port")
        else:
            starts.append(entry.split(".")[0])
    fallback = (owner or graph).get('fallback')
    if isinstance(fallback, Mapping) and fallback.get('kind') == 'default_unit':
        if _target(fallback.get('target'), resolved, owner, entry=True):
            starts.append(fallback['target'].split('.')[0])
    if owner is not None:
        waits = owner.get("waits") if isinstance(owner.get("waits"), list) else []
        for wait in waits:
            target = wait.get("timeoutTo") if isinstance(wait, Mapping) else None
            if _target(target, resolved, owner, entry=True):
                starts.append(target.split(".")[0])

    if owner is None:
        event_targets = _events(v, graph.get("on_event", []), f"{path}.on_event", resolved, None)
    else:
        event_targets = _events(v, owner.get("on_event"), f"{path.removesuffix('.body')}.on_event", resolved, owner)

    adjacency: dict[str, set[str]] = defaultdict(set)
    unbounded: dict[str, set[str]] = defaultdict(set)
    sources: set[str] = set()
    exit_hits: set[str] = set()
    for target in event_targets:
        if target.startswith("self."):
            exit_hits.add(target[5:])
        elif target != "end":
            starts.append(target.split(".")[0])
    edge_ids: set[str] = set()
    loop_writes: set[str] = set()
    for i, edge in enumerate(edges):
        p = f"{path}.edges[{i}]"
        if not isinstance(edge, Mapping):
            v.add(p, "invalid_graph_edge", "edge must be an object")
            continue
        _keys(v, edge, {"id", "from", "to", "condition", "max_rounds", "exit", "counter", "window"}, p)
        if not _local_id(edge.get("id")) or edge["id"] in edge_ids:
            v.add(f"{p}.id", "invalid_edge_id", "edge ids must be unique local ids")
        else:
            edge_ids.add(edge["id"])
        source, target = edge.get("from"), edge.get("to")
        source_ok = _source(source, resolved)
        target_ok = _target(target, resolved, owner)
        if not source_ok:
            v.add(f"{p}.from", "unknown_edge_source", "from must name a local node exit port")
        if not target_ok:
            v.add(f"{p}.to", "invalid_edge_target", "to must name a local entry port or own self exit; only root permits end")
        if "condition" not in edge:
            v.add(f"{p}.condition", "missing_edge_condition", "condition is required; {} means unconditional")
        else:
            v._validate_condition(
                edge["condition"],
                f"{p}.condition",
                deterministic_only=False,
                allow_positive_llm=allow_positive_llm,
            )
        bounded = any(key in edge for key in ("max_rounds", "exit", "counter", "window"))
        if bounded:
            count, counter = edge.get("max_rounds"), edge.get("counter")
            if not isinstance(count, int) or isinstance(count, bool) or count < 1:
                v.add(f"{p}.max_rounds", "invalid_loop_limit", "loop requires positive integer max_rounds")
            if not _target(edge.get("exit"), resolved, owner) or edge.get("exit") == target:
                v.add(f"{p}.exit", "invalid_loop_exit", "loop exit must be a valid different destination")
            if not isinstance(counter, str) or owner is None or counter not in _string_list(owner.get("writes")) or v.field_types.get(counter) not in ("integer", "int"):
                v.add(f"{p}.counter", "undeclared_loop_counter", "loop counter must be integer and declared in owning Unit writes")
            else:
                loop_writes.add(counter)
            if edge.get("window") != "cycle":
                v.add(f"{p}.window", "invalid_loop_window", "loop window must explicitly be cycle")
        if not source_ok or not target_ok:
            continue
        sources.add(source)
        if target.startswith("self."):
            exit_hits.add(target[5:])
        elif target != "end":
            adjacency[source.split(".")[0]].add(target.split(".")[0])
            if not bounded:
                unbounded[source.split(".")[0]].add(target.split(".")[0])
        if bounded and _target(edge.get("exit"), resolved, owner):
            if edge["exit"].startswith("self."):
                exit_hits.add(edge["exit"][5:])
            elif edge["exit"] != "end":
                adjacency[source.split(".")[0]].add(edge["exit"].split(".")[0])
    if _has_cycle(unbounded):
        v.add(f"{path}.edges", "unbounded_execution_cycle", "removing bounded edges must leave a DAG")
    reachable: set[str] = set()
    todo = starts[:]
    while todo:
        current = todo.pop()
        if current not in reachable:
            reachable.add(current)
            todo.extend(adjacency.get(current, set()))
    for i, node in enumerate(nodes):
        if isinstance(node, Mapping) and _local_id(node.get("id")) and node["id"] not in reachable:
            v.add(f"{path}.nodes[{i}].id", "unreachable_graph_node", "node is unreachable from all entries")
    for node_id, child in resolved.items():
        for port in _ports(child, "exit_ports"):
            if f"{node_id}.{port}" not in sources:
                v.add(f"{path}.edges", "unconnected_exit_port", f"{node_id}.{port} needs an outgoing edge")
    if owner is not None:
        for port in _ports(owner, "exit_ports"):
            if port not in exit_hits:
                v.add(f"{path}.edges", "unconnected_owner_exit", f"self.{port} needs an incoming edge")
        reads = set().union(*(set(_string_list(child.get("reads"))) for child in resolved.values()))
        writes = loop_writes | set().union(*(set(_string_list(child.get("writes"))) for child in resolved.values()))
        for edge in edges:
            if isinstance(edge, Mapping):
                reads.update(field for _, field in _condition_fields(edge.get("condition"), path))
        _interface(v, owner, reads, writes, path)
        _fallback(v, owner.get("fallback"), f"{path.removesuffix('.body')}.fallback", resolved, owner)
    else:
        _fallback(v, graph.get("fallback"), f"{path}.fallback", resolved, None)
    return refs


def _atom(v: Any, body: Mapping[str, Any], path: str, unit: Mapping[str, Any]) -> None:
    kind = body.get("kind")
    reads: set[str] = set()
    writes: set[str] = set()
    if kind == "say":
        _keys(v, body, {"kind", "text", "verbatim_reason"}, path)
        for key in ("text", "verbatim_reason"):
            if not isinstance(body.get(key), str) or not body[key].strip():
                v.add(f"{path}.{key}", f"missing_{key}", f"say requires {key}")
    elif kind == "judge":
        _keys(v, body, {"kind", "condition", "result_field"}, path)
        v._validate_condition(body.get("condition"), f"{path}.condition", deterministic_only=True)
        reads.update(field for _, field in _condition_fields(body.get("condition"), path))
        field = body.get("result_field")
        if not isinstance(field, str) or v.field_types.get(field) != "boolean":
            v.add(f"{path}.result_field", "invalid_judge_result", "judge requires a declared boolean result_field")
        else:
            writes.add(field)
    elif kind == "tool":
        _keys(v, body, {"kind", "tool_ref", "arguments"}, path)
        reference = body.get("tool_ref")
        manifests = v.spec.get("tools")
        if not isinstance(manifests, list):
            manifests = []
        valid_reference = (
            isinstance(reference, Mapping) and set(reference) == {"tool_id", "version"}
            and all(isinstance(reference.get(key), str) and reference[key].strip()
                    for key in ("tool_id", "version"))
        )
        matches = [item for item in manifests if isinstance(item, Mapping)
                   and valid_reference and item.get("tool_id") == reference["tool_id"]]
        if not valid_reference or len(matches) != 1 or matches[0].get("version") != reference["version"]:
            v.add(f"{path}.tool_ref", "unfrozen_tool_reference", "tool_ref must match one declared ToolManifest by exact tool_id and version")
        if "arguments" in body and not isinstance(body["arguments"], Mapping):
            v.add(f"{path}.arguments", "invalid_tool_arguments", "tool arguments must be an object")
        v.add(path, "unsupported_graph_atom", "tool execution and argument schema resolution are not integrated yet")
    elif kind == "speak":
        v.add(path, "unsupported_graph_atom", "speak frozen prompt/model resolution is not integrated yet")
        return
    else:
        v.add(f"{path}.kind", "invalid_body_kind", "body kind must be graph, tool, judge, speak, or say")
        return
    _interface(v, unit, reads, writes, path)


def _interface(v: Any, unit: Mapping[str, Any], reads: set[str], writes: set[str], path: str) -> None:
    for field in sorted(reads - set(_string_list(unit.get("reads")))):
        if not _is_system_field(field):
            v.add(path, "hidden_body_read", f"body reads undeclared field {field}")
    for field in sorted(writes - set(_string_list(unit.get("writes")))):
        v.add(path, "hidden_body_write", f"body writes undeclared field {field}")
    for field in sorted(set(_string_list(unit.get("writes"))) - writes):
        v.add(path, "unassigned_write", f"body never assigns declared field {field}")


def _events(v: Any, events: Any, path: str, nodes: Mapping[str, Any], owner: Mapping[str, Any] | None) -> list[str]:
    if not isinstance(events, list):
        v.add(path, "invalid_events", "on_event must be an array")
        return []
    targets = []
    for i, event in enumerate(events):
        p = f"{path}[{i}]"
        if not isinstance(event, Mapping):
            v.add(p, "invalid_event", "event must be an object")
            continue
        _keys(v, event, {"event", "scope", "goto", "when"}, p)
        if event.get("event") not in ("user_hangup", "side_effect_unknown", "timeout", "handoff"):
            v.add(f"{p}.event", "invalid_event_name", "unsupported boundary event")
        if event.get("scope") not in (("global",) if owner is None else ("self", "subtree")):
            v.add(f"{p}.scope", "invalid_event_scope", "global events belong only at version level")
        target = event.get("goto")
        if not _target(target, nodes, owner):
            v.add(f"{p}.goto", "invalid_event_target", "event may only target its local graph or own exit")
        else:
            targets.append(target)
        if "when" in event:
            v._validate_condition(event["when"], f"{p}.when", deterministic_only=True)
    return targets


def _waits(v: Any, waits: Any, path: str, nodes: Mapping[str, Any], owner: Mapping[str, Any]) -> None:
    if waits is None:
        return
    if not isinstance(waits, list):
        v.add(path, "invalid_waits", "waits must be an array when present")
        return
    seen = set()
    for i, wait in enumerate(waits):
        p = f"{path}[{i}]"
        if not isinstance(wait, Mapping):
            v.add(p, "invalid_wait", "wait declaration must be an object")
            continue
        _keys(v, wait, {"on", "timeoutMs", "timeoutTo"}, p)
        event = wait.get("on")
        if not isinstance(event, str) or not event.strip():
            v.add(f"{p}.on", "invalid_wait_event", "wait requires a non-empty event name")
        elif event in seen:
            v.add(f"{p}.on", "duplicate_wait_event", "wait event must be unique within a Unit")
        else:
            seen.add(event)
        if "timeoutMs" in wait and (
            not isinstance(wait["timeoutMs"], int)
            or isinstance(wait["timeoutMs"], bool)
            or wait["timeoutMs"] < 1
        ):
            v.add(f"{p}.timeoutMs", "invalid_wait_timeout", "timeoutMs must be a positive integer")
        if "timeoutTo" in wait and not _target(wait["timeoutTo"], nodes, owner):
            v.add(f"{p}.timeoutTo", "invalid_wait_timeout_target", "timeoutTo must name a local child entry or the owning Unit's exit")
        if "timeoutTo" in wait and "timeoutMs" not in wait:
            v.add(f"{p}.timeoutTo", "timeout_target_without_timeout", "timeoutTo requires timeoutMs")
        if "timeoutMs" in wait and "timeoutTo" not in wait:
            v.add(f"{p}.timeoutMs", "timeout_without_target", "timeoutMs requires an executable timeoutTo")


def _fallback(v: Any, fallback: Any, path: str, nodes: Mapping[str, Any], owner: Mapping[str, Any] | None) -> None:
    if not isinstance(fallback, Mapping) or fallback.get("kind") not in ("clarify", "human", "default_unit"):
        v.add(path, "invalid_fallback", "fallback must declare clarify, human, or default_unit")
    elif fallback.get("kind") == "default_unit" and not _target(fallback.get("target"), nodes, owner, entry=True):
        v.add(f"{path}.target", "invalid_fallback_target", "fallback must target a local entry port")


def _resolve(v: Any, ref: Any) -> Mapping[str, Any] | None:
    if not isinstance(ref, Mapping) or set(ref) != {"unit_id", "version"}:
        return None
    uid, version = ref.get("unit_id"), ref.get("version")
    if not isinstance(uid, str) or not isinstance(version, int) or isinstance(version, bool) or version < 1:
        return None
    found = v.unit_by_id.get(uid)
    return found[1] if found is not None and found[1].get("version") == version else None


def _ports(unit: Mapping[str, Any], key: str) -> dict[str, Mapping[str, Any]]:
    raw = unit.get(key)
    return {p["port"]: p for p in raw if isinstance(p, Mapping) and isinstance(p.get("port"), str)} if isinstance(raw, list) else {}


def _target(value: Any, nodes: Mapping[str, Any], owner: Mapping[str, Any] | None, *, entry: bool = False) -> bool:
    if not isinstance(value, str):
        return False
    if value == "end":
        return owner is None and not entry
    parts = value.split(".")
    if len(parts) != 2:
        return False
    node, port = parts
    if node == "self":
        return owner is not None and not entry and port in _ports(owner, "exit_ports")
    return node in nodes and port in _ports(nodes[node], "entry_ports")


def _source(value: Any, nodes: Mapping[str, Any]) -> bool:
    if not isinstance(value, str):
        return False
    parts = value.split(".")
    return len(parts) == 2 and parts[0] in nodes and parts[1] in _ports(nodes[parts[0]], "exit_ports")


def _local_id(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and "." not in value and value not in ("self", "end")


def _keys(v: Any, value: Mapping[str, Any], allowed: set[str], path: str) -> None:
    for key in value:
        if key not in allowed:
            v.add(f"{path}.{key}", "unsupported_graph_field", "field is not part of unit-graph-v1")


def _validate_json_shape(v: Any, value: Any, path: str) -> None:
    """Reject non-canonical values before graph freeze/hash/persistence.

    Configuration arrives as JSON over the public adapters, but callers can
    still construct Python manifests directly.  Keeping that path strict
    avoids accepting a graph that only fails later in ``json.dumps`` or gets a
    platform-dependent hash for non-finite floats.
    """
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            v.add(path, "non_json_graph_value", "graph values must use finite JSON numbers")
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _validate_json_shape(v, child, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                v.add(path, "non_json_graph_value", "graph object keys must be strings")
                continue
            _validate_json_shape(v, child, f"{path}.{key}")
        return
    v.add(path, "non_json_graph_value", "graph values must be JSON-compatible objects, arrays, strings, booleans, numbers, or null")


def _has_cycle(graph: Mapping[str, set[str]]) -> bool:
    degrees: dict[str, int] = defaultdict(int)
    for node, children in graph.items():
        degrees.setdefault(node, 0)
        for child in children:
            degrees[child] += 1
    todo = [node for node, degree in degrees.items() if degree == 0]
    count = 0
    while todo:
        node = todo.pop()
        count += 1
        for child in graph.get(node, set()):
            degrees[child] -= 1
            if degrees[child] == 0:
                todo.append(child)
    return count != len(degrees)
