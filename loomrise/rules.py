# -*- coding: utf-8 -*-
"""硬规则裁决：在模型外执行，确定性，可复述。

模型可以提出解释与下一步，但不能绕过 HardRule。规则按
global / task / skill 作用域管理，每条有稳定 rule_id；裁决结果与命中的规则写入 RunEvent。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .contracts import Behavior, HardRule


@dataclass
class Decision:
    behavior: Behavior
    rule_ids: list[str] = field(default_factory=list)
    reason: str = ""
    idempotency_key: str | None = None
    known_result_id: str | None = None


class DecisionPolicy:
    def __init__(
        self,
        rules: list[HardRule],
        emit=None,
        writes: dict[str, str] | None = None,
    ) -> None:
        self.rules = rules
        self.emit = emit or (lambda *a, **k: None)
        # 写入账本挂在 ExecutionService 上，跨轮次/跨渠道共享，保证只写一次
        self._writes: dict[str, str] = writes if writes is not None else {}

    # -- 裁决 --------------------------------------------------------------
    def check(
        self,
        tool_name: str,
        args: dict[str, Any],
        *,
        skill_id: str = "",
    ) -> Decision:
        hits = [
            r
            for r in self.rules
            if r.tool in (None, tool_name)
            and all(args.get(k) == v for k, v in (r.when_arg_equals or {}).items())
        ]
        if not hits:
            return Decision(Behavior.DENY, reason=f"工具 {tool_name} 未在 ToolPolicy 中登记")

        # 幂等：同一键已成功写过就直接拒绝，不产生第二次业务写入
        key = args.get("idempotency_key")
        if key and key in self._writes:
            return Decision(
                Behavior.DENY,
                rule_ids=["dedupe.no_duplicate_write"],
                reason=f"重复写入被拦截：幂等键 {key} 已产生 result_id={self._writes[key]}",
                idempotency_key=key,
                known_result_id=self._writes[key],
            )

        # 优先级：deny > require_confirm > allow
        for behavior in (Behavior.DENY, Behavior.ASK, Behavior.ALLOW):
            matched = [r for r in hits if r.behavior == behavior]
            if matched:
                rule_ids = [r.rule_id for r in matched]
                reason = "；".join(f"{r.rule_id}: {r.reason}" for r in matched)
                return Decision(behavior, rule_ids, reason, idempotency_key=key)

        return Decision(
            Behavior.DENY,
            rule_ids=[r.rule_id for r in hits],
            reason="规则命中但无明确放行",
            idempotency_key=key,
        )

    def enforce_deny(self, tool_name: str, args: dict[str, Any]) -> "Decision | None":
        """工具执行前的最后一道闸：只做"必须拒绝"的判断。

        确认已经在 ExecutionService 权限层收集过，工具内部不再二次询问。
        """
        key = args.get("idempotency_key")
        if key and key in self._writes:
            return Decision(
                Behavior.DENY,
                rule_ids=["dedupe.no_duplicate_write"],
                reason=f"重复写入被拦截：幂等键 {key} 已产生 result_id={self._writes[key]}",
                idempotency_key=key,
                known_result_id=self._writes[key],
            )
        denies = [
            r
            for r in self.rules
            if r.tool in (None, tool_name)
            and r.behavior is Behavior.DENY
            and all(args.get(k) == v for k, v in (r.when_arg_equals or {}).items())
        ]
        if denies:
            return Decision(
                Behavior.DENY,
                rule_ids=[r.rule_id for r in denies],
                reason="；".join(f"{r.rule_id}: {r.reason}" for r in denies),
                idempotency_key=key,
            )
        return None

    # -- 写入账本 ----------------------------------------------------------
    def remember_write(self, idempotency_key: str, result_id: str) -> None:
        self._writes[idempotency_key] = result_id

    def known_write(self, idempotency_key: str) -> str | None:
        return self._writes.get(idempotency_key)

    @property
    def writes(self) -> dict[str, str]:
        return dict(self._writes)


__all__ = ["Decision", "DecisionPolicy"]
