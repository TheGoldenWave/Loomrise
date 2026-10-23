# -*- coding: utf-8 -*-
"""硬规则裁决：在模型外执行，确定性，可复述。

模型可以提出解释与下一步，但不能绕过 HardRule。规则按
global / task / skill 作用域管理，每条有稳定 rule_id；裁决结果与命中的规则写入 RunEvent。

**四层分开，不许揉在一起**（这是 R0 合同对齐的核心）：

1. **授权查询**（`authorize`）：工具登记在 `ToolPolicy` 里就能用，没登记就不能用。
   它返回 `AuthorizationResult`，**不是裁决**。登记即允许，所以规则表里没有 `allow`。
2. **裁决**（`check`）：返回 `Verdict` 的四个值之一，或 `None` 表示"没有规则要拦"。
3. **路由去向**（`GateOutcome`）：在 `contracts.py`，与本模块并列，不由规则产生。
4. **事项状态**：在 `service.py`，不由规则产生。

把 1 混进 2 的后果是："未登记"会伪装成一条 deny 规则，规则表就变成了权限系统，
审计时分不清某个拒绝是"策略要求"还是"根本没配置"。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .contracts import AuthorizationResult, HardRule, ToolManifest, Verdict

#: 冲突时的固定优先级。顺序本身是合同，改它等于改语义。
VERDICT_PRECEDENCE: tuple[Verdict, ...] = (
    Verdict.DENY,
    Verdict.STOP,
    Verdict.REQUIRE,
    Verdict.DEDUPE,
)


@dataclass
class Decision:
    """一次裁决。

    `verdict is None` 是**放行**：没有规则命中，工具已登记。这不是"允许"这个第五种裁决，
    而是"没有裁决"——所以没有 `Verdict.ALLOW` 这个东西。
    """

    verdict: Verdict | None
    rule_ids: list[str] = field(default_factory=list)
    reason: str = ""
    authorization: AuthorizationResult | None = None
    idempotency_key: str | None = None
    known_result_id: str | None = None

    @property
    def allowed(self) -> bool:
        return self.verdict is None

    @property
    def verdict_name(self) -> str:
        return self.verdict.value if self.verdict is not None else "pass"


class DecisionPolicy:
    def __init__(
        self,
        rules: list[HardRule],
        emit=None,
        writes: dict[str, str] | None = None,
        tools: list[ToolManifest] | None = None,
    ) -> None:
        self.rules = rules
        self.emit = emit or (lambda *a, **k: None)
        # 写入账本挂在 ExecutionService 上，跨轮次/跨渠道共享，保证只写一次
        self._writes: dict[str, str] = writes if writes is not None else {}
        # 授权来源：ToolPolicy 登记。空列表 = 没有任何工具被授权。
        self.tools: dict[str, ToolManifest] = {t.tool_id: t for t in (tools or [])}

    # -- 第 1 层：授权查询（不产 Verdict） --------------------------------
    def authorize(self, tool_name: str) -> AuthorizationResult:
        tool = self.tools.get(tool_name)
        if tool is None:
            return AuthorizationResult(
                allowed=False,
                tool_id=tool_name,
                reason=f"工具 {tool_name} 未在 ToolPolicy 中登记",
            )
        return AuthorizationResult(
            allowed=True,
            tool_id=tool_name,
            reason=f"已登记（副作用等级 {tool.side_effect_level}）",
            side_effect_level=tool.side_effect_level,
        )

    # -- 第 2 层：规则裁决 ------------------------------------------------
    def check(
        self,
        tool_name: str,
        args: dict[str, Any],
        *,
        skill_id: str = "",
    ) -> Decision:
        auth = self.authorize(tool_name)
        if not auth.allowed:
            return Decision(Verdict.DENY, reason=auth.reason, authorization=auth)

        key = args.get("idempotency_key")
        # 幂等先判：同一键已成功写过，这次不是"又一次写入"，是"同一个写入"。
        if key and key in self._writes:
            return Decision(
                Verdict.DEDUPE,
                rule_ids=["dedupe.no_duplicate_write"],
                reason=f"重复写入被拦截：幂等键 {key} 已产生 result_id={self._writes[key]}",
                authorization=auth,
                idempotency_key=key,
                known_result_id=self._writes[key],
            )

        hits = [
            r
            for r in self.rules
            if r.tool in (None, tool_name)
            and all(args.get(k) == v for k, v in (r.when_arg_equals or {}).items())
        ]
        if not hits:
            # 登记即放行。这里不能返回 DENY——那会让"没写规则"等于"禁止"。
            return Decision(
                None,
                reason="无规则命中；工具已登记，按登记放行",
                authorization=auth,
                idempotency_key=key,
            )

        for verdict in VERDICT_PRECEDENCE:
            matched = [r for r in hits if r.verdict is verdict]
            if matched:
                return Decision(
                    verdict,
                    rule_ids=[r.rule_id for r in matched],
                    reason="；".join(f"{r.rule_id}: {r.reason}" for r in matched),
                    authorization=auth,
                    idempotency_key=key,
                )

        # 命中规则但没有任何已知裁决值：数据坏了，按拒绝处理并留下线索。
        return Decision(
            Verdict.DENY,
            rule_ids=[r.rule_id for r in hits],
            reason="规则命中但裁决值无效",
            authorization=auth,
            idempotency_key=key,
        )

    def enforce_deny(self, tool_name: str, args: dict[str, Any]) -> "Decision | None":
        """工具执行前的最后一道闸：只做"必须拒绝"的判断。

        确认已经在 ExecutionService 权限层收集过，工具内部不再二次询问。
        """
        key = args.get("idempotency_key")
        if key and key in self._writes:
            return Decision(
                Verdict.DEDUPE,
                rule_ids=["dedupe.no_duplicate_write"],
                reason=f"重复写入被拦截：幂等键 {key} 已产生 result_id={self._writes[key]}",
                idempotency_key=key,
                known_result_id=self._writes[key],
            )
        denies = [
            r
            for r in self.rules
            if r.tool in (None, tool_name)
            and r.verdict is Verdict.DENY
            and all(args.get(k) == v for k, v in (r.when_arg_equals or {}).items())
        ]
        if denies:
            return Decision(
                Verdict.DENY,
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


__all__ = ["Decision", "DecisionPolicy", "VERDICT_PRECEDENCE"]
