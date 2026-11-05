"""Pure projections for retained customer-reception facts.

The store supplies already scoped flat rows. This module validates the
server-owned identities again before aggregating, so malformed JSON or a row
with a conflicting envelope cannot create a request, latency sample, or usage
record. It deliberately does not infer delivery or human handoff history.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import json
import math
from typing import Any, Iterable, Mapping

from .run_overlay import timestamp


_SUPPORTED_CHANNELS = ("text",)
_CHANNELS = {"text", "voice"}
_EVENT_TYPES = {
    "customer.reception.started",
    "customer.reception.generated",
    "customer.reception.published",
    "customer.reception.finished",
    "customer.handoff.claimed",
    "customer.handoff.replied",
    "customer.handoff.released",
}
_LATENCY_STATUSES = {
    "answered", "handoff", "disabled", "outside_schedule", "human_requested",
    "not_configured", "model_changed", "knowledge_unavailable", "provider_error",
    "invalid_response",
}


def _nonempty(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} 必须是非空字符串")
    return value


def _parse_scope_instant(value: Any, name: str) -> datetime:
    parsed = timestamp(value)
    if parsed is None:
        raise ValueError(f"{name} 必须是带时区的 ISO 时间")
    return parsed


def _json_object(value: Any) -> dict[str, Any] | None:
    if isinstance(value, Mapping):
        return dict(value)
    if not isinstance(value, str):
        return None
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return None
    return dict(parsed) if isinstance(parsed, Mapping) else None


def _strict_count(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _row_scope(row: Mapping[str, Any], *, tenant_id: str, agent_id: str) -> tuple[dict[str, Any], str] | None:
    required = (
        "scope_tenant_id", "scope_agent_id", "conversation_id", "entry_id", "release_version",
        "turn_input_sequence", "turn_request_id", "turn_run_id", "turn_version_id",
        "run_request_id", "run_tenant_id", "run_version_id", "request_tenant_id", "request_version_id",
        "run_snapshot_json",
    )
    if any(row.get(key) is None for key in required):
        return None
    if row.get("scope_tenant_id") != tenant_id or row.get("scope_agent_id") != agent_id:
        return None
    identifiers = (
        "conversation_id", "entry_id", "release_version", "turn_request_id", "turn_run_id",
        "turn_version_id", "run_request_id", "run_tenant_id", "run_version_id",
        "request_tenant_id", "request_version_id",
    )
    if any(not isinstance(row.get(key), str) or not row[key].strip() for key in identifiers):
        return None
    if row["run_tenant_id"] != tenant_id or row["request_tenant_id"] != tenant_id:
        return None
    if (row["turn_request_id"] != row["run_request_id"]
            or row["turn_request_id"] != row.get("request_id")
            or row["turn_run_id"] != row.get("run_id")
            or row["turn_version_id"] != row["release_version"]
            or row["run_version_id"] != row["release_version"]
            or row["request_version_id"] != row["release_version"]):
        return None
    if type(row["turn_input_sequence"]) is not int or row["turn_input_sequence"] < 1:
        return None
    snapshot = _json_object(row.get("run_snapshot_json"))
    if (snapshot is None or snapshot.get("kind") != "customer_reception"
            or snapshot.get("agent_id") != agent_id
            or snapshot.get("conversation_id") != row["conversation_id"]
            or snapshot.get("input_sequence") != row["turn_input_sequence"]):
        return None
    return dict(row), row["turn_run_id"]


def _event(row: Mapping[str, Any], *, tenant_id: str, run_id: str, version_id: str,
           meta: Mapping[str, Any]) -> dict[str, Any] | None:
    event_type = row.get("event_type")
    if not isinstance(event_type, str) or event_type not in _EVENT_TYPES:
        return None
    raw = _json_object(row.get("event_json"))
    payload = _json_object(row.get("payload_json"))
    instant = timestamp(row.get("ts"))
    if raw is None or payload is None or instant is None:
        return None
    if (raw.get("run_id") != run_id or raw.get("request_id") != meta.get("turn_request_id")
            or raw.get("tenant_id") != tenant_id or raw.get("agent_version") != version_id
            or raw.get("event_type") != event_type or raw.get("ts") != row.get("ts")
            or raw.get("payload") != payload or raw.get("channel") not in _CHANNELS
            or type(raw.get("seq")) is not int or raw.get("seq") < 1 or raw.get("seq") != row.get("seq")
            or type(row.get("rid")) is not int or row.get("rid") < 1):
        return None
    if row.get("run_id") != run_id or row.get("request_id") != raw.get("request_id"):
        return None
    expected_sequence = meta["turn_input_sequence"]
    if event_type == "customer.reception.started":
        if payload.get("conversation_id") != meta["conversation_id"] or payload.get("input_sequence") != expected_sequence:
            return None
    elif event_type in {"customer.reception.published", "customer.reception.finished"}:
        if payload.get("input_sequence") != expected_sequence:
            return None
        if event_type == "customer.reception.published" and payload.get("conversation_id") != meta["conversation_id"]:
            return None
    elif event_type.startswith("customer.handoff."):
        generation = payload.get("occupancy_generation")
        actor_id = payload.get("actor_id")
        if (payload.get("conversation_id") != meta["conversation_id"]
                or not isinstance(actor_id, str) or not actor_id.strip()
                or type(generation) is not int or generation < 1):
            return None
        if event_type == "customer.handoff.replied":
            message_sequence = payload.get("message_sequence")
            if type(message_sequence) is not int or message_sequence < 1:
                return None
    return {"type": event_type, "ts": instant, "channel": raw["channel"], "payload": payload,
            "seq": raw["seq"], "identity": (run_id, raw["seq"], event_type, row.get("event_json"))}


def _empty_scope(*, tenant_id: str, agent_id: str, from_value: str | None, to_value: str | None,
                 channel: str | None, version_id: str | None, as_of: datetime) -> dict[str, Any]:
    return {
        "agent_id": agent_id, "from": from_value, "to": to_value, "channel": channel,
        "version_id": version_id, "basis": "customer.reception.started", "as_of": as_of.isoformat(),
    }


def aggregate_reception_statistics(
    rows: Iterable[Mapping[str, Any]], *, tenant_id: str, agent_id: str,
    from_ts: str | None = None, to_ts: str | None = None, channel: str | None = None,
    version_id: str | None = None, as_of: str | None = None,
) -> dict[str, Any]:
    """Aggregate a server-authorized customer-reception row stream.

    Cohort membership is decided by exactly one valid ``started`` event in the
    half-open window. Events after the window are observed until ``as_of``;
    this prevents a slow selected run from disappearing when it finishes later.
    """
    tenant_id = _nonempty(tenant_id, "tenant_id")
    agent_id = _nonempty(agent_id, "agent_id")
    if (from_ts is None) != (to_ts is None):
        raise ValueError("from 与 to 必须同时提供")
    start = _parse_scope_instant(from_ts, "from") if from_ts is not None else None
    end = _parse_scope_instant(to_ts, "to") if to_ts is not None else None
    if start is not None and end is not None and end <= start:
        raise ValueError("to 必须晚于 from")
    if channel is not None and channel not in _CHANNELS:
        raise ValueError("channel 必须是 text、voice 或省略")
    if version_id is not None:
        version_id = _nonempty(version_id, "version_id")
    observed = _parse_scope_instant(as_of, "as_of") if as_of is not None else datetime.now(timezone.utc)
    if start is not None and observed < start:
        raise ValueError("as_of 不能早于 from")

    grouped: dict[str, dict[str, Any]] = {}
    ignored = 0
    for source in rows:
        scoped = _row_scope(source, tenant_id=tenant_id, agent_id=agent_id)
        if scoped is None:
            ignored += 1
            continue
        row, run_id = scoped
        entry = grouped.setdefault(run_id, {"meta": row, "events": {}, "conflicting": set(), "bad_scope": False})
        meta = entry["meta"]
        if any(meta.get(key) != row.get(key) for key in (
                "conversation_id", "entry_id", "release_version", "turn_input_sequence",
                "turn_request_id", "turn_run_id", "turn_version_id", "run_request_id",
                "run_tenant_id", "run_version_id", "request_tenant_id", "request_version_id",
                "run_snapshot_json")):
            entry["bad_scope"] = True
            ignored += 1
            continue
        event = _event(row, tenant_id=tenant_id, run_id=run_id, version_id=meta["release_version"], meta=meta)
        if event is None:
            if row.get("event_type") is not None:
                ignored += 1
            continue
        key = (event["seq"], event["type"])
        prior = entry["events"].get(key)
        if prior is not None:
            if prior["identity"] != event["identity"]:
                entry["conflicting"].add(key)
            continue
        entry["events"][key] = event

    runs: list[dict[str, Any]] = []
    missing_start = ambiguous_start = 0
    for run_id, entry in grouped.items():
        if entry["bad_scope"] or entry["conflicting"]:
            ignored += 1
            continue
        events_by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for event in entry["events"].values():
            events_by_type[event["type"]].append(event)
        starts = [event for event in events_by_type["customer.reception.started"]
                  if event["ts"] <= observed and event["channel"] in _SUPPORTED_CHANNELS]
        if version_id is not None and entry["meta"]["release_version"] != version_id:
            continue
        if channel is not None and channel not in _SUPPORTED_CHANNELS:
            continue
        if len(starts) > 1:
            ambiguous_start += 1
            ignored += 1
            continue
        if not starts:
            if not starts:
                missing_start += 1
            continue
        selected_start = starts[0]
        if channel is not None and selected_start["channel"] != channel:
            continue
        runs.append({"id": run_id, "entry": entry, "start": selected_start,
                     "starts": [selected_start], "events": events_by_type})
    if start is not None:
        runs = [run for run in runs if start <= run["start"]["ts"] < end]

    request_ids = {run["entry"]["meta"]["turn_request_id"] for run in runs}
    entries: dict[str, set[str]] = defaultdict(set)
    versions: dict[str, set[str]] = defaultdict(set)
    outcomes: dict[str, int] = defaultdict(int)
    latencies: list[float] = []
    latency_missing = 0
    generated_count = published_count = 0
    usage_rows: list[tuple[str | None, dict[str, int]]] = []
    runs_without_usage = 0
    handoff_request_facts: dict[str, set[bool]] = defaultdict(set)
    handoff_claim_requests: set[str] = set()
    handoff_tracking_requests: set[str] = set()
    for run in runs:
        meta = run["entry"]["meta"]
        request_id = meta["turn_request_id"]
        entries[meta["entry_id"]].add(request_id)
        versions[meta["release_version"]].add(request_id)
        event_map = run["events"]
        generated = [event for event in event_map["customer.reception.generated"] if event["ts"] <= observed]
        published = [event for event in event_map["customer.reception.published"] if event["ts"] <= observed]
        finished = [event for event in event_map["customer.reception.finished"] if event["ts"] <= observed]
        if len(finished) == 1 and type(finished[0]["payload"].get("handoff_requested")) is bool:
            handoff_request_facts[request_id].add(finished[0]["payload"]["handoff_requested"])
        if (len(finished) == 1
                and type(finished[0]["payload"].get("handoff_tracking_version")) is int
                and finished[0]["payload"].get("handoff_tracking_version") == 1):
            handoff_tracking_requests.add(request_id)
        if any(event["ts"] <= observed for event in event_map["customer.handoff.claimed"]):
            handoff_claim_requests.add(request_id)
        generated_count += len(generated)
        published_count += len(published)
        if len(finished) == 1:
            status = finished[0]["payload"].get("status")
            if isinstance(status, str) and status.strip():
                outcomes[status] += 1
        elif len(finished) > 1:
            ignored += len(finished) - 1
        valid_finished = [event for event in finished
                          if event["payload"].get("status") in _LATENCY_STATUSES]
        if len(run["starts"]) != 1 or len(valid_finished) != 1:
            latency_missing += 1
        else:
            delta = (valid_finished[0]["ts"] - run["starts"][0]["ts"]).total_seconds() * 1000
            if math.isfinite(delta) and delta >= 0:
                latencies.append(delta)
            else:
                latency_missing += 1
        usage = []
        for event in generated:
            provider = event["payload"].get("provider")
            if not isinstance(provider, Mapping):
                continue
            provider_usage = provider.get("usage")
            if not isinstance(provider_usage, Mapping):
                continue
            counts = {key: value for key in ("input_tokens", "output_tokens")
                      if (value := _strict_count(provider_usage.get(key))) is not None}
            if counts:
                model = provider.get("model") if isinstance(provider.get("model"), str) and provider["model"].strip() else None
                usage.append((model, counts, run["id"]))
        if usage:
            usage_rows.extend(usage)
        else:
            runs_without_usage += 1

    input_values = [counts["input_tokens"] for _, counts, _ in usage_rows if "input_tokens" in counts]
    output_values = [counts["output_tokens"] for _, counts, _ in usage_rows if "output_tokens" in counts]
    input_runs = {run_id for _, counts, run_id in usage_rows if "input_tokens" in counts}
    output_runs = {run_id for _, counts, run_id in usage_rows if "output_tokens" in counts}
    sampled_handoff_requests = {request_id for request_id, facts in handoff_request_facts.items()
                                if len(facts) == 1}
    requested_count = (sum(handoff_request_facts[request_id] == {True}
                           for request_id in sampled_handoff_requests)
                       if sampled_handoff_requests else None)
    claim_sample_requests = handoff_tracking_requests | handoff_claim_requests
    claimed_count = len(handoff_claim_requests) if claim_sample_requests else None
    handoff_request_missing = len(request_ids) - len(sampled_handoff_requests)
    handoff_claim_missing = len(request_ids) - len(claim_sample_requests)
    by_model: dict[str | None, dict[str, Any]] = {}
    model_runs: dict[str | None, set[str]] = defaultdict(set)
    for model, counts, run_id in usage_rows:
        key = model
        bucket = by_model.setdefault(key, {"model": key, "run_count": 0, "input_tokens": None,
                                           "output_tokens": None, "input_sample_count": 0, "output_sample_count": 0})
        model_runs[key].add(run_id)
        for field in ("input_tokens", "output_tokens"):
            if field in counts:
                bucket[field] = (bucket[field] or 0) + counts[field]
    for model, run_ids in model_runs.items():
        by_model[model]["run_count"] = len(run_ids)
        for field in ("input_tokens", "output_tokens"):
            by_model[model][f"{field[:-7]}sample_count"] = len({run_id for candidate, counts, run_id in usage_rows
                                                                  if candidate == model and field in counts})
    mean_latency = round(sum(latencies) / len(latencies), 3) if latencies else None
    from_value = start.isoformat() if start is not None else None
    to_value = end.isoformat() if end is not None else None
    requested_supported = channel is None or channel in _SUPPORTED_CHANNELS
    return {
        "schema_version": "customer-statistics-window-v1",
        "scope": _empty_scope(tenant_id=tenant_id, agent_id=agent_id, from_value=from_value, to_value=to_value,
                               channel=channel, version_id=version_id, as_of=observed),
        "request_count": len(request_ids), "run_count": len(runs),
        "entries": {key: len(value) for key, value in sorted(entries.items())},
        "versions": {key: len(value) for key, value in sorted(versions.items())},
        "reception_outcomes": dict(sorted(outcomes.items())),
        "generated_count": generated_count, "published_count": published_count,
        "handoff": {
            "requested_count": requested_count,
            "request_sample_count": len(sampled_handoff_requests),
            "request_missing_count": handoff_request_missing,
            "claimed_count": claimed_count,
            "claim_sample_count": len(claim_sample_requests),
            "claim_missing_count": handoff_claim_missing,
            "reason": ("historical_transition_events_not_recorded"
                       if handoff_request_missing or handoff_claim_missing else None),
        },
        "processing_latency": {
            "mean_ms": mean_latency, "sample_count": len(latencies), "missing_count": latency_missing,
            "boundary": "customer.reception.started -> customer.reception.finished",
            "clock": "server_event_wall_clock",
        },
        "model_usage": {
            "by_model": [by_model[key] for key in sorted(by_model, key=lambda value: value or "")],
            "input_tokens": sum(input_values) if input_values else None,
            "output_tokens": sum(output_values) if output_values else None,
            "input_sample_count": len(input_runs), "output_sample_count": len(output_runs),
            "input_missing_count": len(runs) - len(input_runs),
            "output_missing_count": len(runs) - len(output_runs),
            "runs_without_usage": runs_without_usage,
            "basis": "validated customer.reception.generated provider usage only",
        },
        "visitor_latency_ms": None, "delivery": "unknown",
        "coverage": {
            "source": "retained customer reception records", "supported_channels": list(_SUPPORTED_CHANNELS),
            "requested_channel_supported": requested_supported, "ignored_record_count": ignored,
            "missing_start_run_count": missing_start, "ambiguous_start_run_count": ambiguous_start,
        },
    }
