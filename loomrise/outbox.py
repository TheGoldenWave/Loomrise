# -*- coding: utf-8 -*-
"""At-least-once delivery for persisted outbox intents.

Consumers must deduplicate side effects using the supplied outbox ID. A crash
after a consumer side effect but before `mark_outbox` can cause that record to
be delivered again; this module does not provide external exactly-once effects.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .durable_store import SqliteStore

OutboxHandler = Callable[[dict[str, Any], str], None]


def dispatch_pending(store: SqliteStore, handler: OutboxHandler) -> list[str]:
    """Dispatch current pending records and return IDs marked delivered.

    The second handler argument is the stable outbox ID and must be used as
    the consumer-side idempotency key. A raised handler error propagates and
    leaves that record pending for a later at-least-once retry.
    """
    delivered: list[str] = []
    for record in store.pending_outbox():
        outbox_id = record["id"]
        if not store.note_outbox_attempt(outbox_id):
            continue
        attempted = {**record, "attempts": record["attempts"] + 1}
        handler(attempted, outbox_id)
        store.mark_outbox(outbox_id)
        delivered.append(outbox_id)
    return delivered


__all__ = ["OutboxHandler", "dispatch_pending"]
