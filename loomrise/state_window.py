"""Small durable state-window provider for deterministic graph conditions."""
from collections import Counter
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any


def event_window_counts(events: list[Any], *, now: datetime | None = None) -> dict[str, int]:
    current = now or datetime.now(timezone.utc)
    result = Counter()
    for event in events:
        stamp = getattr(event, 'ts', None)
        try: value = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
        except (AttributeError, ValueError): continue
        if value.tzinfo is None: continue
        age = current - value.astimezone(timezone.utc)
        if timedelta(0) <= age < timedelta(hours=24): result['24h'] += 1
        result['forever'] += 1
    return dict(result)


def evaluate_state_window(*, metric: str, window: str, op: str, value: Any,
                          counts: dict[str, dict[str, int]]) -> bool:
    if window not in {'cycle', '24h', 'forever'} or metric not in {'attempts', 'runs'}:
        raise ValueError('unsupported state window')
    metric_counts = counts.get(metric) if isinstance(counts, Mapping) else None
    if not isinstance(metric_counts, Mapping):
        raise ValueError('state window counts require metric-specific persisted counts')
    actual = metric_counts.get(window)
    if type(actual) is not int or actual < 0:
        raise ValueError('service cycle state count is unavailable or invalid' if window == 'cycle'
                          else 'state window count is unavailable or invalid')
    if op == 'gt': return actual > value
    if op == 'gte': return actual >= value
    if op == 'lt': return actual < value
    if op == 'lte': return actual <= value
    if op == 'eq': return actual == value
    if op == 'ne': return actual != value
    raise ValueError('unsupported state window operator')
