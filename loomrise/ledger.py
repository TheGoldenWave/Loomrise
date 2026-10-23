# -*- coding: utf-8 -*-
"""RunEvent 账本：业务事实源，追加写入 + 哈希链。

OTel / AG-UI / Langfuse 都是本账本的投影；账本损坏或导出失败时业务事实不变。
"""

from __future__ import annotations

import json
import os
from typing import Any, Iterator

from .contracts import GENESIS_HASH, Channel, RunEvent, new_id

GENESIS = GENESIS_HASH


class EventLedger:
    def __init__(self, path: str | None = None) -> None:
        self.path = path
        self._events: list[RunEvent] = []
        self._tail = GENESIS
        # 结构化存储的落库钩子。账本仍是业务事实源，sink 只是持久化下游；
        # sink 抛错必须冒泡——事件没落库却继续执行，等于承认"记不下来也算做过"。
        self.sink: Any = None

    # -- 写 ---------------------------------------------------------------
    def emit(
        self,
        event_type: str,
        *,
        request_id: str,
        run_id: str,
        tenant_id: str,
        agent_version: str,
        channel: Channel | str,
        media_session_id: str | None = None,
        trace_id: str | None = None,
        idempotency_key: str | None = None,
        **payload: Any,
    ) -> RunEvent:
        evt = RunEvent(
            seq=len(self._events),
            event_type=event_type,
            request_id=request_id,
            run_id=run_id,
            tenant_id=tenant_id,
            agent_version=agent_version,
            channel=str(channel),
            media_session_id=media_session_id,
            trace_id=trace_id,
            idempotency_key=idempotency_key,
            payload=payload,
        ).seal(self._tail)
        self._events.append(evt)
        self._tail = evt.hash
        if self.sink is not None:
            self.sink(evt)
        if self.path:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(evt.to_dict(), ensure_ascii=False) + "\n")
        return evt

    # -- 读 ---------------------------------------------------------------
    @property
    def events(self) -> list[RunEvent]:
        return list(self._events)

    def where(self, **filters: Any) -> list[RunEvent]:
        out = []
        for e in self._events:
            d = e.to_dict()
            if all(d.get(k) == v for k, v in filters.items()):
                out.append(e)
        return out

    def find(self, event_type: str, **payload_filters: Any) -> list[RunEvent]:
        return [
            e
            for e in self._events
            if e.event_type == event_type
            and all(e.payload.get(k) == v for k, v in payload_filters.items())
        ]

    def one(self, event_type: str, **payload_filters: Any) -> RunEvent | None:
        found = self.find(event_type, **payload_filters)
        return found[-1] if found else None

    def types(self) -> list[str]:
        return [e.event_type for e in self._events]

    def iter_lines(self) -> Iterator[dict[str, Any]]:
        if not self.path or not os.path.exists(self.path):
            return
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    yield json.loads(line)

    # -- 完整性 ------------------------------------------------------------
    def verify(self) -> bool:
        """校验哈希链未被篡改。"""
        prev = GENESIS
        for e in self._events:
            if e.prev_hash != prev:
                return False
            if e.seal(prev).hash != e.hash:
                return False
            prev = e.hash
        return True


def load_ledger(path: str) -> EventLedger:
    led = EventLedger(path)
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            payload = d.pop("payload", {})
            evt = RunEvent(**d, payload=payload)
            led._events.append(evt)
            led._tail = evt.hash
    return led


__all__ = ["EventLedger", "load_ledger", "new_id"]
