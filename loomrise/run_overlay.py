"""Versioned read projection of graph routing evidence, never business outcomes.

``run-overlay-v1`` selects graph invocations whose persisted ``started`` instant
is in [from, to), then reads their entire trace in ledger sequence order. A Run
can contain several invocations: visit/termination counts include each, while
``sample_count`` and reach percentages use distinct Run IDs. Re-entering a node
or traversing a cycle therefore cannot produce a reach percentage above 100%.
Each node/edge independently needs 30 distinct observed Runs before showing a
percentage. This is an observation threshold, not statistical significance.

Map keys are compact JSON arrays ``[*layer, local_id]``; root ``same`` and nested
``same`` are respectively '["same"]' and '["parent","same"]'. Node entries merge
ports on the same local node. Counts cover valid observed events only: missing
nodes/edges are absent, not measured zeroes. Cycle-limit exits are counted apart
from actual traversals of the original cycle edge.

GraphRuntime.route_and_emit runs the route before emitting its entire trace.
It supplies explicit monotonic node-body duration samples and a layer-qualified
terminal node on the finished event. Ledger timestamp deltas remain irrelevant
to dwell. The projection accepts those measurements only when they match node
entries in the same invocation; malformed or missing evidence is not inferred.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from typing import Any, Iterable, Mapping


_STEP_KINDS = frozenset({
    "enter", "edge", "cycle_limit", "g0", "event", "wait_timeout", "wait",
    "requires_failed", "completion_failed", "judge", "fallback", "tool_rejected",
    "fallback_route", "fallback_limit",
})
_ROUTE_STATUSES = frozenset({"completed", "fallback", "gated", "waiting", "cycle_limit", "routed"})


def timestamp(raw: object) -> datetime | None:
    """Parse aware instants only; SQLite text ordering is unsafe for UTC offsets."""
    if not isinstance(raw, str):
        return None
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return value.astimezone(timezone.utc) if value.tzinfo is not None else None
    except (ValueError, OverflowError):
        return None


@dataclass
class _Observation:
    local_id: str
    layer: list[str]
    count: int = 0
    runs: set[str] = field(default_factory=set)
    cycle_limit_count: int = 0
    dwell_total_ms: int = 0
    dwell_sample_count: int = 0

    def reach(self, sample_count: int) -> dict[str, Any]:
        entrants = len(self.runs)
        return {
            "layer": self.layer,
            "entrant_count": entrants,
            "low_sample": entrants < 30,
            "percentage_denominator": sample_count,
            "percentage": round(entrants / sample_count * 100, 1) if entrants >= 30 else None,
        }


@dataclass
class _Invocation:
    selected: bool
    channel: str
    started_at: datetime
    last_step_index: int = -1
    node_entries: dict[tuple[str, ...], int] = field(default_factory=dict)
    node_entry_steps: dict[tuple[str, ...], list[int]] = field(default_factory=dict)
    steps: dict[int, dict[str, Any]] = field(default_factory=dict)


def _valid_step(payload: dict[str, Any], invocation: _Invocation) -> bool:
    index, kind = payload.get("step_index"), payload.get("kind")
    layer, target = payload.get("layer"), payload.get("target")
    if (type(index) is not int or index <= invocation.last_step_index
            or not isinstance(kind, str) or kind not in _STEP_KINDS
            or not isinstance(target, str) or not target.strip()
            or not isinstance(layer, list)
            or any(not isinstance(part, str) or not part.strip() for part in layer)):
        return False
    if kind == "enter":
        parts = target.split(".")
        if len(parts) != 2 or any(not part.strip() for part in parts) or parts[0] == "self":
            return False
    if kind in {"edge", "cycle_limit"}:
        if not isinstance(payload.get("edge_id"), str) or not payload["edge_id"].strip():
            return False
    if payload.get("source") is not None and (not isinstance(payload["source"], str) or not payload["source"].strip()):
        return False
    if payload.get("unit_id") is not None and (not isinstance(payload["unit_id"], str) or not payload["unit_id"].strip()):
        return False
    return True


def aggregate_graph_events(
    rows: Iterable[Mapping[str, Any]], *, tenant_id: str, agent_id: str,
    version_id: str, start: datetime, end: datetime, channel: str | None,
) -> dict[str, Any]:
    """Consume rows already authorized by the persisted Run's agent association.

    The caller orders rows by run_id, seq. Event envelopes must agree with the
    authoritative Run and ledger columns; malformed payloads and orphan records
    cannot manufacture samples, completion, or durations. Raw payloads and IDs of
    individual Runs are never returned to the workbench.
    """
    nodes: dict[str, _Observation] = {}
    edges: dict[str, _Observation] = {}
    runs: set[str] = set()
    channels: dict[str, set[str]] = {}
    terminations: dict[str, int] = {}
    termination_targets: dict[str, int] = {}
    route_count = finished_count = ignored_count = 0
    durations: list[int] = []
    node_dwell_count = node_dwell_missing_routes = 0
    node_termination_count = node_termination_missing_routes = 0
    current_run: str | None = None
    invocation: _Invocation | None = None

    for row in rows:
        if row["run_id"] != current_run:
            current_run, invocation = row["run_id"], None
        instant = timestamp(row["ts"])
        in_window = instant is not None and start <= instant < end
        selected_before = invocation is not None and invocation.selected
        event_type = row["event_type"]
        # Ledger boundaries fence attribution even when their JSON is corrupt.
        if event_type == "route.graph.started":
            invocation = None
        try:
            event = json.loads(row["event_json"])
        except (TypeError, ValueError):
            ignored_count += int(selected_before or in_window)
            if event_type == "route.graph.finished":
                invocation = None
            continue
        valid_envelope = isinstance(event, dict) and all((
            event.get("tenant_id") == tenant_id,
            event.get("agent_version") == version_id,
            event.get("run_id") == row["run_id"],
            event.get("request_id") == row["run_request_id"],
            row["event_request_id"] == row["run_request_id"],
            type(event.get("seq")) is int and event.get("seq") == row["seq"],
            event.get("event_type") == event_type,
            event.get("ts") == row["ts"],
            event.get("channel") in ("text", "voice"),
            instant is not None,
        ))
        if not valid_envelope:
            ignored_count += int(selected_before or in_window)
            if event_type == "route.graph.finished":
                invocation = None
            continue
        event_channel = event["channel"]
        payload = event.get("payload")
        if not isinstance(payload, dict):
            ignored_count += int(selected_before or (in_window and channel in (None, event_channel)))
            if event_type == "route.graph.finished":
                invocation = None
            continue
        if event_type == "route.graph.started":
            if payload.get("schema_version") != "unit-graph-v1":
                ignored_count += int(in_window and channel in (None, event_channel))
                continue
            selected = in_window and channel in (None, event_channel)
            invocation = _Invocation(selected, event_channel, instant)
            if selected:
                route_count += 1
                runs.add(current_run)
                channels.setdefault(event_channel, set()).add(current_run)
            continue
        if invocation is None:
            ignored_count += int(in_window and channel in (None, event_channel))
            continue
        if not invocation.selected:
            if event_type == "route.graph.finished":
                invocation = None
            continue
        if event_channel != invocation.channel or instant < invocation.started_at:
            ignored_count += 1
            if event_type == "route.graph.finished":
                invocation = None
            continue
        if event_type == "route.graph.finished":
            status = payload.get("route_status")
            if isinstance(status, str) and status in _ROUTE_STATUSES:
                terminations[status] = terminations.get(status, 0) + 1
                finished_count += 1
                if type(payload.get('duration_ms')) is int and payload['duration_ms'] >= 0:
                    durations.append(payload['duration_ms'])

                route_has_dwell = False
                telemetry_version = payload.get("telemetry_schema_version")
                raw_dwell_samples = payload.get("node_dwell_samples")
                if telemetry_version == "graph-telemetry-v1" and isinstance(raw_dwell_samples, list):
                    used: dict[tuple[str, ...], int] = {}
                    for sample in raw_dwell_samples:
                        if not isinstance(sample, dict):
                            ignored_count += 1
                            continue
                        node_id = sample.get("node_id")
                        layer = sample.get("layer")
                        dwell_ms = sample.get("dwell_ms")
                        if (not isinstance(node_id, str) or not node_id.strip()
                                or not isinstance(layer, list)
                                or any(not isinstance(part, str) or not part.strip() for part in layer)
                                or type(dwell_ms) is not int or dwell_ms < 0):
                            ignored_count += 1
                            continue
                        identity = tuple([*layer, node_id])
                        used[identity] = used.get(identity, 0) + 1
                        if used[identity] > invocation.node_entries.get(identity, 0):
                            ignored_count += 1
                            continue
                        key = json.dumps(list(identity), ensure_ascii=False, separators=(",", ":"))
                        stat = nodes.get(key)
                        if stat is None:
                            ignored_count += 1
                            continue
                        stat.dwell_total_ms += dwell_ms
                        stat.dwell_sample_count += 1
                        node_dwell_count += 1
                        route_has_dwell = True
                elif telemetry_version is not None or "node_dwell_samples" in payload:
                    ignored_count += 1
                if invocation.node_entries and not route_has_dwell:
                    node_dwell_missing_routes += 1

                terminal = payload.get("terminal_node")
                terminal_valid = False
                if terminal is not None:
                    if (telemetry_version != "graph-telemetry-v1" or status != "completed" or not isinstance(terminal, dict)
                            or not isinstance(terminal.get("node_id"), str)
                            or not terminal["node_id"].strip()
                            or not isinstance(terminal.get("unit_id"), str)
                            or not terminal["unit_id"].strip()
                            or not isinstance(terminal.get("exit_port"), str)
                            or not terminal["exit_port"].strip()
                            or not isinstance(terminal.get("layer"), list)
                            or any(not isinstance(part, str) or not part.strip() for part in terminal["layer"])
                            or terminal.get("evidence_kind") not in {"edge", "cycle_limit", "wait_timeout"}
                            or type(terminal.get("step_index")) is not int):
                        ignored_count += 1
                    else:
                        identity = tuple([*terminal["layer"], terminal["node_id"]])
                        evidence = invocation.steps.get(terminal["step_index"])
                        expected_source = f"{terminal['node_id']}.{terminal['exit_port']}"
                        valid_evidence = (
                            isinstance(evidence, dict)
                            and terminal["step_index"] == invocation.last_step_index
                            and evidence.get("kind") == terminal["evidence_kind"]
                            and evidence.get("target") == "end"
                            and evidence.get("layer") == terminal["layer"]
                            and evidence.get("source") == expected_source
                            and evidence.get("unit_id") == terminal["unit_id"]
                            and (terminal["evidence_kind"] == "wait_timeout"
                                 or evidence.get("edge_id") == terminal.get("edge_id"))
                            and (terminal["evidence_kind"] != "wait_timeout" or terminal.get("edge_id") is None)
                        )
                        entered_before_evidence = any(
                            step_index < terminal["step_index"]
                            for step_index in invocation.node_entry_steps.get(identity, [])
                        )
                        if not entered_before_evidence or not valid_evidence:
                            ignored_count += 1
                        else:
                            key = json.dumps(list(identity), ensure_ascii=False, separators=(",", ":"))
                            termination_targets[key] = termination_targets.get(key, 0) + 1
                            node_termination_count += 1
                            terminal_valid = True
                if status == "completed" and invocation.node_entries and not terminal_valid:
                    node_termination_missing_routes += 1
            else:
                ignored_count += 1
            invocation = None
            continue
        if not _valid_step(payload, invocation):
            ignored_count += 1
            continue
        invocation.last_step_index = payload["step_index"]
        invocation.steps[payload["step_index"]] = payload
        kind, layer = payload["kind"], payload["layer"]
        if kind == "enter":
            node_id = payload["target"].split(".")[0]
            key = json.dumps([*layer, node_id], ensure_ascii=False, separators=(",", ":"))
            stat = nodes.setdefault(key, _Observation(node_id, layer))
            stat.count += 1
            stat.runs.add(current_run)
            identity = tuple([*layer, node_id])
            invocation.node_entries[identity] = invocation.node_entries.get(identity, 0) + 1
            invocation.node_entry_steps.setdefault(identity, []).append(payload["step_index"])
        elif kind in {"edge", "cycle_limit"}:
            edge_id = payload["edge_id"]
            key = json.dumps([*layer, edge_id], ensure_ascii=False, separators=(",", ":"))
            stat = edges.setdefault(key, _Observation(edge_id, layer))
            if kind == "cycle_limit":
                stat.cycle_limit_count += 1
            else:
                stat.count += 1
                stat.runs.add(current_run)

    sample_count = len(runs)
    return {
        "schema_version": "run-overlay-v1",
        "agent_id": agent_id,
        "version_id": version_id,
        "time_window": {"from": start.isoformat(), "to": end.isoformat()},
        "time_window_basis": "route.graph.started",
        "channel": channel,
        "sample_count": sample_count,
        "route_count": route_count,
        "low_sample": sample_count < 30,
        "percentage_basis": "distinct_observed_runs / sample_count",
        "channels": {key: len(value) for key, value in sorted(channels.items())},
        "average_duration_ms": round(sum(durations) / len(durations)) if durations else None,
        "nodes": {key: {
            "node_id": stat.local_id, "entered": stat.count,
            "dwell_ms": round(stat.dwell_total_ms / stat.dwell_sample_count) if stat.dwell_sample_count else None,
            "dwell_sample_count": stat.dwell_sample_count,
            **stat.reach(sample_count),
        } for key, stat in sorted(nodes.items())},
        "edges": {key: {
            "edge_id": stat.local_id, "traversed": stat.count,
            "cycle_limit_count": stat.cycle_limit_count, **stat.reach(sample_count),
        } for key, stat in sorted(edges.items())},
        "terminations": dict(sorted(terminations.items())),
        "termination_targets": dict(sorted(termination_targets.items())) if termination_targets else None,
        "coverage": {
            "agent_scope": "run.snapshot.agent_id",
            "unattributed_runs": "excluded",
            "ignored_event_count": ignored_count,
            "finished_route_count": finished_count,
            "unfinished_route_count": route_count - finished_count,
            "duration": {"measured_count": len(durations), "reason": "route_execution_duration" if durations else "route_events_missing_duration"},
            "node_dwell": {
                "measured_count": node_dwell_count,
                "unmeasured_route_count": node_dwell_missing_routes,
                "reason": "explicit_interpreter_node_body_duration" if node_dwell_count else "no_valid_node_dwell_samples",
            },
            "node_termination": {
                "measured_count": node_termination_count,
                "unmeasured_route_count": node_termination_missing_routes,
                "reason": "layer_qualified_terminal_node" if node_termination_count else "no_valid_layer_qualified_terminal_node",
            },
        },
    }
