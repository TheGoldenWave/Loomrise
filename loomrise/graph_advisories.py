"""Server-side identity and closed-set calculation for graph advisories."""

from __future__ import annotations

import json
from typing import Any


def closed_set_advisory(config: dict[str, Any], layer_path: list[str]) -> dict[str, Any] | None:
    orchestration = config.get("orchestration")
    if not isinstance(orchestration, dict) or orchestration.get("schema_version") != "unit-graph-v1":
        return None
    units = config.get("units")
    if not isinstance(units, list):
        return None
    unit_index: dict[str, dict[str, Any] | None] = {}
    for unit in units:
        unit_id = unit.get("unit_id") if isinstance(unit, dict) else None
        if not isinstance(unit_id, str):
            continue
        if unit_id in unit_index:
            unit_index[unit_id] = None
            continue
        unit_index[unit_id] = unit

    def resolve(graph: dict[str, Any], node_id: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
        nodes = graph.get("nodes")
        if not isinstance(nodes, list) or not isinstance(node_id, str) or not node_id or "." in node_id:
            return None
        matches = [node for node in nodes if isinstance(node, dict) and node.get("id") == node_id]
        if len(matches) != 1:
            return None
        reference = matches[0].get("unit_ref")
        unit = unit_index.get(reference.get("unit_id")) if isinstance(reference, dict) else None
        if (not isinstance(unit, dict) or unit.get("version") != reference.get("version")
                or unit.get("load_mode") != "routed"):
            return None
        return matches[0], unit

    def ports(unit: dict[str, Any], key: str) -> list[Any]:
        values = unit.get(key)
        return values if isinstance(values, list) else []

    graph = orchestration
    owner = None
    visited: set[str] = set()
    for node_id in layer_path:
        found = resolve(graph, node_id)
        unit = found[1] if found else None
        body = unit.get("body") if isinstance(unit, dict) else None
        if (not isinstance(body, dict) or body.get("kind") != "graph"
                or not isinstance(body.get("nodes"), list) or unit["unit_id"] in visited):
            return None
        visited.add(unit["unit_id"])
        owner, graph = unit, body
    if not isinstance(graph.get("nodes"), list) or not isinstance(graph.get("edges"), list):
        return None

    targets: set[tuple[str, str]] = set()
    for edge in graph["edges"]:
        if not isinstance(edge, dict):
            continue
        source_parts = edge.get("from", "").split(".") if isinstance(edge.get("from"), str) else []
        target = edge.get("to")
        target_parts = target.split(".") if isinstance(target, str) else []
        if len(source_parts) != 2 or (target != "end" and len(target_parts) != 2):
            continue
        source = resolve(graph, source_parts[0])
        if not source or not any(port.get("port") == source_parts[1]
                                 for port in ports(source[1], "exit_ports") if isinstance(port, dict)):
            continue
        if target == "end" and owner is None:
            targets.add(("terminal", target))
            continue
        if target.startswith("self.") and owner is not None and len(target_parts) == 2:
            if any(port.get("port") == target_parts[1]
                   for port in ports(owner, "exit_ports") if isinstance(port, dict)):
                targets.add(("terminal", target))
            continue
        destination = resolve(graph, target_parts[0])
        if destination and any(port.get("port") == target_parts[1]
                               for port in ports(destination[1], "entry_ports") if isinstance(port, dict)):
            targets.add(("node", target_parts[0]))

    mode = graph.get("routing", {}).get("mode") if isinstance(graph.get("routing"), dict) else None
    closed_set_size = len(targets)
    threshold = 8 if mode == "deterministic" else 5
    if mode not in {"deterministic", "llm", "hybrid"} or closed_set_size <= threshold:
        return None
    layer_json = json.dumps(layer_path, ensure_ascii=False, separators=(",", ":"))
    return {
        "advisory_key": f"closed-set:{layer_json}",
        "layer_path": list(layer_path),
        "closed_set_size": closed_set_size,
    }
