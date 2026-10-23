# -*- coding: utf-8 -*-
"""业务工具（S1）：一个只读知识检索 + 一个模拟业务写入。

工具本身不含框架依赖；AgentScope 侧包装在 adapters/agentscope_runtime.py 完成。
结果语义使用 Loomrise 的 ToolOutcome，其中 `unknown` 是 S1 自建态
（上游 ToolResultState 只有 success/error/interrupted/denied/running）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .contracts import ContextFragment, ContextScope, ToolOutcome, new_id
from .rules import DecisionPolicy


@dataclass
class ToolResult:
    outcome: ToolOutcome
    message: str
    payload: dict[str, Any] = field(default_factory=dict)
    result_id: str | None = None
    duration_ms: int = 0


class Sandbox:
    """模拟沙盒：知识片段 + 模拟写入账本。真实外部写入不出现在 S1。"""

    def __init__(
        self,
        fragments: list[ContextFragment],
        policy: DecisionPolicy,
        ctx_ledger,
        failure_mode: str = "none",
        latency_ms: int = 0,
    ) -> None:
        self.fragments = fragments
        self.policy = policy
        self.ctx = ctx_ledger
        self.failure_mode = failure_mode
        self.latency_ms = latency_ms
        self.bookings: list[dict[str, Any]] = []
        self.write_attempts: list[dict[str, Any]] = []

    # -- 只读：知识检索 ----------------------------------------------------
    async def search_knowledge(self, query: str, limit: int = 3) -> ToolResult:
        t0 = time.time()
        tokens = [t for t in _tokenize(query) if len(t) > 1]
        scored = []
        for f in self.fragments:
            if f.scope != ContextScope.EVIDENCE:
                continue
            hay = f"{f.title} {f.content} {' '.join(_tokenize(f.title))}"
            score = sum(1 for t in tokens if t in hay)
            if score:
                scored.append((score, f))
        scored.sort(key=lambda x: (-x[0], x[1].priority, x[1].fragment_id))
        picked = [f for _, f in scored[:limit]]

        # 按需证据阶段：加载/跳过/过期/预算截断都会留证
        loaded = self.ctx.stage_evidence(
            [f.fragment_id for f in picked],
            trigger=f"知识检索：{query}",
        )
        audit = self.ctx.audit_answer()
        return ToolResult(
            outcome=ToolOutcome.SUCCESS,
            message=_render_knowledge(loaded, audit),
            payload={
                "query": query,
                "hit_ids": [f.fragment_id for f in picked],
                "loaded_ids": [f.fragment_id for f in loaded],
                "expired": audit["expired"],
                "budget_capped": audit["budget_capped"],
                "no_result": not picked,
            },
            duration_ms=int((time.time() - t0) * 1000),
        )

    # -- 模拟写入 ----------------------------------------------------------
    async def create_booking(
        self,
        course_id: str,
        learner_name: str,
        slot: str,
        idempotency_key: str,
    ) -> ToolResult:
        t0 = time.time()
        args = {
            "course_id": course_id,
            "learner_name": learner_name,
            "slot": slot,
            "idempotency_key": idempotency_key,
        }
        # 确认已由 ExecutionService 权限层收集；这里只拦"必须拒绝"的情况
        denied = self.policy.enforce_deny("create_booking", args)
        self.write_attempts.append(
            {"args": args, "decision": "deny" if denied else "allow"},
        )
        if denied is not None:
            return ToolResult(
                outcome=ToolOutcome.DENIED,
                message=f"写入被硬规则拒绝：{denied.reason}",
                payload={"rule_ids": denied.rule_ids},
                result_id=denied.known_result_id,
                duration_ms=int((time.time() - t0) * 1000),
            )
        if self.failure_mode == "error":
            return ToolResult(
                outcome=ToolOutcome.ERROR,
                message="模拟写入失败：预约服务返回 500",
                payload={"args": args},
                duration_ms=int((time.time() - t0) * 1000),
            )

        if self.failure_mode == "timeout_unknown":
            if self.latency_ms:
                time.sleep(self.latency_ms / 1000)
            # 超时后回执未知：既不是成功也不是失败，必须由 Loomrise 显式建模
            return ToolResult(
                outcome=ToolOutcome.UNKNOWN,
                message="模拟写入超时：未取得回执，结果未知（不得记为成功）",
                payload={"args": args, "timeout_ms": 3000},
                duration_ms=int((time.time() - t0) * 1000),
            )

        result_id = new_id("res")
        record = {**args, "result_id": result_id, "created_at": _ts()}
        self.bookings.append(record)
        self.policy.remember_write(idempotency_key, result_id)
        return ToolResult(
            outcome=ToolOutcome.SUCCESS,
            message=f"模拟预约已写入：result_id={result_id}",
            payload={"booking": record},
            result_id=result_id,
            duration_ms=int((time.time() - t0) * 1000),
        )

    @property
    def write_count(self) -> int:
        return len(self.bookings)


def _tokenize(text: str) -> list[str]:
    out, buf = [], ""
    for ch in text.lower():
        if ch.isalnum():
            buf += ch
        else:
            if buf:
                out.append(buf)
            buf = ""
    if buf:
        out.append(buf)
    # 中文按二元组切，避免整句无法匹配
    cjk = [ch for ch in text if "\u4e00" <= ch <= "\u9fff"]
    out += [text[i : i + 2] for i in range(len(cjk) - 1)] if len(cjk) > 1 else cjk
    return out


def _render_knowledge(loaded: list[ContextFragment], audit: dict[str, Any]) -> str:
    if not loaded:
        if audit["budget_capped"]:
            return "检索有命中，但被 token 预算截断，未能加载（已记录 budget_capped）。"
        if audit["expired"]:
            return "检索有命中，但来源已过期，未加载（已记录 expired）。"
        return "检索无结果：知识库中没有对应资料（不得由模型补造）。"
    parts = []
    for f in loaded:
        parts.append(
            f"[{f.fragment_id}] {f.title}（来源 {f.source_ref}@{f.source_version}）\n{f.content}",
        )
    return "\n\n".join(parts)


def _ts() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


__all__ = ["Sandbox", "ToolResult"]
