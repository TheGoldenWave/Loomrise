# -*- coding: utf-8 -*-
"""`DurableRunAdapter`：把执行进度落进结构化存储，但**不持有业务真相**。

边界（ARCHITECTURE「Adapter 内部机制与业务边界」）：

- Adapter 只记「这次运行到哪一步了」；业务终态仍由 `Outcome` + 外部 `result_id` 决定。
- `commit_write` 的原子性覆盖 幂等记录 + 事件 + outbox 意图；写成功不等于业务成功。
- 旧代（run 已结束 / 被恢复判为中断）**一律拒绝写入**，不靠调用方自觉。
"""

from __future__ import annotations

from typing import Any

from .contracts import (
    GENESIS_HASH,
    Run,
    RunEvent,
    RunStatus,
    ServiceRequest,
    new_id,
)
from .durable_store import RecoveryReport, SqliteStore


def action_key(action: str, idempotency_key: str) -> str:
    """幂等键绑定**具体业务操作**（`M-A-06`）。

    同一个模型给的键用在两个工具上，必须算两次不同的动作；只在同一个
    `(action, key)` 上才允许复用 `result_id`。
    """
    return f"{action}::{idempotency_key}"


class DurableRunAdapter:
    def __init__(
        self,
        store: SqliteStore,
        *,
        owner_id: str,
        tenant_id: str = "tenant_demo",
    ) -> None:
        self.store = store
        self.owner_id = owner_id
        self.tenant_id = tenant_id
        # `run.finished` 要和服务状态同一事务提交，不能提前单独落库：
        # 否则崩溃可能留下"事件说完成、运行仍 running"，恢复时被判成中断。
        self._pending_finish: dict[str, RunEvent] = {}

    # -- 生命周期 ----------------------------------------------------------
    def recover(self) -> RecoveryReport:
        return self.store.recover(owner_id=self.owner_id)

    def begin(
        self,
        request: ServiceRequest,
        *,
        agent_version: str,
        snapshot: dict[str, Any] | None = None,
        lineage_parent: str | None = None,
        generation: int = 1,
        attempt_id: str | None = None,
    ) -> Run:
        run = Run(
            run_id=new_id("run"),
            request_id=request.request_id,
            tenant_id=self.tenant_id,
            agent_version=agent_version,
            owner_id=self.owner_id,
            occupancy_generation=generation,
            attempt_id=attempt_id,
            lineage_parent=lineage_parent,
            snapshot=dict(snapshot or {}),
        )
        self.store.begin_run(request, run, [])
        return run

    def persist(self, evt: RunEvent) -> None:
        """事件落库入口（挂在 `EventLedger.sink` 上，逐条调用）。

        三种情形分开处理：
        1. `run.finished`：暂存，等 `finish()` 与运行状态同事务提交；
        2. 业务写入结果（带 `idempotency_key` + `result_id`）：走 `commit_write`，
           幂等记录 / 事件 / outbox 要么一起可见，要么都不可见；
        3. 其余事件：链式追加。
        """
        if evt.event_type == "run.finished":
            self._pending_finish[evt.run_id] = evt
            return

        result_id = evt.payload.get("result_id")
        key = evt.idempotency_key
        if evt.event_type == "tool.outcome" and result_id and key:
            created, known = self.store.commit_write(
                evt.run_id,
                key=action_key(str(evt.payload.get("tool", "unknown")), key),
                bare_key=key,
                action=str(evt.payload.get("tool", "unknown")),
                result_id=str(result_id),
                event=evt,
                outbox_payload={"tool": evt.payload.get("tool"), "result_id": str(result_id)},
            )
            if not created:
                # 走到这里说明前置幂等检查被绕过（并发或重启竞态）。
                # 不静默放过：宁可让本次运行失败，也不能产生第二次业务写入。
                raise RuntimeError(
                    f"幂等键 {key} 已有 result_id={known}，拒绝重复写入"
                    f"（run {evt.run_id}）",
                )
            return

        # 旧代写入必须拒绝：运行已结束或已被恢复判为中断。
        if not self.store.is_running(evt.run_id):
            raise RuntimeError(f"run {evt.run_id} 已不在运行，旧代不得继续写入事件")
        self.store.append_events([evt])

    def finish(
        self,
        run: Run,
        *,
        request_state: str,
        status: RunStatus | None = None,
        reason: str | None = None,
        result_id: str | None = None,
    ) -> None:
        evt = self._pending_finish.pop(run.run_id, None)
        if evt is None:
            tail = self.store.last_event(run.run_id)
            evt = RunEvent(
                seq=self.store.next_seq(run.run_id),
                event_type="run.finished",
                request_id=run.request_id,
                run_id=run.run_id,
                tenant_id=run.tenant_id,
                agent_version=run.agent_version,
                channel="",
                payload={"request_state": request_state, "synthetic": True},
            ).seal(tail.hash if tail else GENESIS_HASH)
        final = status or (
            RunStatus.SUCCEEDED if request_state == "success" else RunStatus.FAILED
        )
        self.store.finish_run(
            run.run_id,
            status=str(final),
            request_state=request_state,
            event=evt,
            result_id=result_id,
            reason=reason,
        )
        run.status = final

    # -- 查询 --------------------------------------------------------------
    def is_running(self, run_id: str) -> bool:
        return self.store.is_running(run_id)

    def run_row(self, run_id: str) -> dict[str, Any] | None:
        return self.store.run_row(run_id)


__all__ = ["DurableRunAdapter", "action_key"]
