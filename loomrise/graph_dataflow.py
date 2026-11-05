"""Definite field availability for versioned Unit graphs.

At a join, only the intersection of predecessor facts is available. Unit
``writes`` declarations are never taken as proof of assignment: summaries
come from supported atom bodies and reachable child paths, per entry/exit.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from typing import Any

from .config_validation import _is_system_field, _string_list


def validate_graph_dataflow(v: Any) -> None:
    from .graph_validation import _ports, _resolve

    units = v.unit_by_id
    pending = dict(units)
    summaries: dict[str, dict[tuple[str, str], set[str]]] = {}
    while pending:
        progressed = False
        for uid, (index, unit) in list(pending.items()):
            body = unit.get("body")
            if not isinstance(body, Mapping):
                summaries[uid] = {}
            elif body.get("kind") != "graph":
                generated = set()
                if body.get("kind") == "judge" and isinstance(body.get("result_field"), str):
                    generated.add(body["result_field"])
                summaries[uid] = {
                    (entry, exit_port): generated
                    for entry in _ports(unit, "entry_ports")
                    for exit_port in _ports(unit, "exit_ports")
                }
            else:
                children = [_resolve(v, node.get("unit_ref")) for node in _array(body.get("nodes")) if isinstance(node, Mapping)]
                if any(child is not None and child["unit_id"] not in summaries for child in children):
                    continue
                summary = {}
                for entry, port in _ports(unit, "entry_ports").items():
                    outputs = _analyse(
                        v, body, unit, f"$.units[{index}].body", port.get("goto"),
                        set(_string_list(port.get("requires"))), summaries,
                    )
                    summary.update({(entry, target[5:]): fields for target, fields in outputs.items() if target.startswith("self.")})
                summaries[uid] = summary
            del pending[uid]
            progressed = True
        if not progressed:
            # Composition-cycle diagnostics belong to the structural checker.
            # Do not invent summaries or recurse forever on invalid drafts.
            return
    root = v.spec["orchestration"]
    _analyse(v, root, None, "$.orchestration", root.get("entry"), set(_string_list(root.get("input_fields"))), summaries)


def _analyse(v, graph, owner, path, start, inputs, summaries):
    from .graph_validation import _ports, _resolve, _source, _target

    nodes = {}
    for node in _array(graph.get("nodes")):
        if isinstance(node, Mapping) and isinstance(node.get("id"), str):
            child = _resolve(v, node.get("unit_ref"))
            if child is not None:
                nodes[node["id"]] = child
    if not _target(start, nodes, owner, entry=True):
        return {}
    outgoing = {}
    for i, edge in enumerate(_array(graph.get("edges"))):
        if isinstance(edge, Mapping) and _source(edge.get("from"), nodes):
            outgoing.setdefault(edge["from"], []).append((i, edge))
    states: dict[str, set[str]] = {}
    outputs: dict[str, set[str]] = {}
    queue = deque()
    reported = set()

    def merge(target, fields):
        if not _target(target, nodes, owner):
            return
        terminal = target == "end" or target.startswith("self.")
        table = outputs if terminal else states
        updated = fields if target not in table else table[target] & fields
        if target not in table or updated != table[target]:
            table[target] = set(updated)
            if not terminal:
                queue.append(target)
            elif owner is not None:
                # A graph Unit waits after its body reaches its own exit. A
                # timeout continuation inherits only facts proven on that path.
                for wait in _array(owner.get("waits")):
                    if isinstance(wait, Mapping):
                        merge(wait.get("timeoutTo"), updated)

    def require(fields, needed, location, description):
        for field in sorted(needed - fields):
            if _is_system_field(field):
                continue
            identity = (location, field)
            if identity not in reported:
                reported.add(identity)
                v.add(location, "path_missing_field", f"{description}: field {field} is not available on every incoming path")

    merge(start, inputs)
    while queue:
        location = queue.popleft()
        before = states[location]
        node_id, entry = location.split(".")
        child = nodes[node_id]
        require(before, set(_string_list(_ports(child, "entry_ports").get(entry, {}).get("requires"))), path, f"entry {location}")
        body = child.get("body")
        if isinstance(body, Mapping) and body.get("kind") == "judge":
            require(before, _value_reads(body.get("condition")), path, f"judge {location}")
        for exit_port in _ports(child, "exit_ports"):
            guaranteed = summaries.get(child["unit_id"], {}).get((entry, exit_port))
            if guaranteed is None:
                continue  # This child exit has no reachable completion path.
            after = before | guaranteed
            for i, edge in outgoing.get(f"{node_id}.{exit_port}", []):
                edge_path = f"{path}.edges[{i}]"
                condition = edge.get("condition")
                require(after, _value_reads(condition), edge_path, "edge condition")
                routed = after | _positive_fields(condition)
                merge(edge.get("to"), routed)
                if "max_rounds" in edge:
                    # The limit path must satisfy its destination independently
                    # of the normal edge condition and before its counter write.
                    merge(edge.get("exit"), after)
        # Boundary events may fire before the active child writes anything.
        handlers = owner.get("on_event") if owner is not None else graph.get("on_event")
        for i, handler in enumerate(_array(handlers)):
            if isinstance(handler, Mapping):
                require(before, _value_reads(handler.get("when")), f"{path}.on_event[{i}]", "event condition")
                merge(handler.get("goto"), before | _positive_fields(handler.get("when")))
        fallback = owner.get("fallback") if owner is not None else graph.get("fallback")
        if isinstance(fallback, Mapping) and fallback.get("kind") == "default_unit":
            merge(fallback.get("target"), before)
    return outputs


def _positive_fields(condition: Any) -> set[str]:
    """Presence proofs from a true condition; an LLM leaf proves no field."""
    if not isinstance(condition, Mapping):
        return set()
    for key in ("all_of", "all", "any_of", "any"):
        if key in condition:
            children = [_positive_fields(child) for child in _array(condition[key])]
            if key in ("all", "all_of"):
                return set().union(*children)
            return set.intersection(*children) if children else set()
    fact = condition.get("fact", condition)
    if isinstance(fact, Mapping) and fact.get("op") in ("exists", "is_set") and isinstance(fact.get("field"), str):
        return {fact["field"]}
    return set()


def _value_reads(condition: Any) -> set[str]:
    if not isinstance(condition, Mapping):
        return set()
    for key in ("all_of", "all", "any_of", "any", "none_of", "not"):
        if key in condition:
            children = condition[key] if isinstance(condition[key], list) else [condition[key]]
            return set().union(*(_value_reads(child) for child in children))
    fact = condition.get("fact", condition)
    if isinstance(fact, Mapping) and fact.get("op") not in ("exists", "is_set", "is_unset") and isinstance(fact.get("field"), str):
        return {fact["field"]}
    return set()


def _array(value):
    return value if isinstance(value, list) else []
