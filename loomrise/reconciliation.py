"""Read-only provider lookup and late-receipt routing for durable tool intents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from .durable_store import SqliteStore

ReconciliationOutcome = Literal["applied", "not_applied", "unknown"]


@dataclass(frozen=True)
class ProviderOperationResult:
    outcome: ReconciliationOutcome
    result_id: str | None = None


class ToolOperationProvider(Protocol):
    def lookup_operation(
        self, *, attempt_key: str, action: str,
    ) -> ProviderOperationResult: ...


class DurableToolReconciliation:
    """Settle durable intents from provider reads; never repeats the operation."""

    def __init__(self, store: SqliteStore) -> None:
        self.store = store

    def reconcile_pending(self, provider: ToolOperationProvider) -> list[dict[str, object]]:
        settled = []
        for attempt in self.store.reconciling_tool_attempts():
            try:
                result = provider.lookup_operation(
                    attempt_key=attempt["attempt_key"], action=attempt["action"],
                )
            except Exception:
                # A failed lookup is not evidence that the side effect did not happen.
                result = ProviderOperationResult("unknown")
            settled.append(self.store.reconcile_tool_attempt(
                attempt["attempt_key"], outcome=result.outcome, result_id=result.result_id,
            ))
        return settled

    def accept_late_receipt(
        self, *, attempt_key: str, result_id: str,
    ) -> dict[str, object]:
        """Apply a provider receipt through the same atomic reconciliation path."""
        return self.store.reconcile_tool_attempt(
            attempt_key, outcome="applied", result_id=result_id,
        )
