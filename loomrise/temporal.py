"""Strict timestamp parsing for governed configuration and context data."""

from __future__ import annotations

from datetime import datetime, timezone
import re

_RFC3339 = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$",
)


def parse_rfc3339_utc(value: object) -> datetime | None:
    if not isinstance(value, str) or not _RFC3339.fullmatch(value):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


__all__ = ["parse_rfc3339_utc"]
