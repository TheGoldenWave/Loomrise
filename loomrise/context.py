# -*- coding: utf-8 -*-
"""渐进式上下文加载 + 压缩边界。

边界来源（S1-VALIDATION A9）：
- AgentScope `ContextConfig` 的自动压缩/截断与 `InjectionConfig` 的运行时注入会在
  不产生 Loomrise 证据的前提下改写有效上下文 → 与"能回答本轮加载/跳过/原因"冲突。
- 该冲突**不是 S1 特有**，是长期结构性冲突：只要产品要回答"模型实际看到了什么"，
  未留证的隐式改写就不被允许。
- S1 的处理是临时止血：`injection_config.inject_runtime_state=False` + 中间件拦截
  `on_compress_context`（fail-closed，不调用 next_handler）。
- 长期不禁止压缩，而是**收编**：由 `ContextCompactionService` 编排并记录
  输入快照 / 摘要或截断算法 / 来源覆盖 / 输入输出哈希 / token 变化 / 成功失败事件。
  上游 SDK 只做执行器，不做上下文事实源。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .contracts import (
    ContextFragment,
    ContextScope,
    LoadStatus,
    estimate_tokens,
)


# --------------------------------------------------------------------------
# 压缩边界
# --------------------------------------------------------------------------


class CompactionBlocked(RuntimeError):
    """S1：未登记的原生压缩/截断被拦截。"""


class CompactionPolicy:
    """压缩策略。S1 = deny（fail-closed）；长期 = loomrise（由本产品编排）。"""

    def __init__(self, mode: str = "deny") -> None:
        if mode not in ("deny", "loomrise"):
            raise ValueError(f"unknown compaction mode: {mode}")
        self.mode = mode

    def intercept(
        self,
        *,
        emit,
        trigger: str,
        context_config: Any = None,
        would_trigger: bool = True,
        extra: dict[str, Any] | None = None,
    ) -> bool:
        """被适配器在 `on_compress_context` 中调用，返回"是否放行"。

        - deny：不放行。适配器据此不调用上游 next_handler，原生压缩/截断不生效；
          真正的 fail-closed 表现是上下文超限时在模型边界显式失败，而不是静默改写。
        - loomrise：S1 未实现编排器，直接报错，避免"假装压缩过"。

        只在"上游确实要压缩"时落事件，避免每个推理轮产生噪声。
        """
        if self.mode == "loomrise":
            raise CompactionBlocked(
                "ContextCompactionService 未实现：S2 起由 Loomrise 编排压缩并留证，"
                "在此之前不得把上游压缩包装成 Loomrise 压缩。",
            )
        if would_trigger:
            emit(
                "context.compaction_blocked",
                trigger=trigger,
                policy="deny",
                note=(
                    "S1 关闭未经登记的上下文改写（不调用上游 next_handler）。"
                    "长期由 ContextCompactionService 编排并记录输入快照/算法/"
                    "来源覆盖/哈希/token 变化。"
                ),
                upstream_context_config=_safe_config(context_config),
                **(extra or {}),
            )
        return False


def _safe_config(cfg: Any) -> dict[str, Any]:
    if cfg is None:
        return {}
    try:
        return cfg.model_dump()
    except Exception:  # ponytail: 配置对象形状随上游版本变化，取不到就记空
        return {"repr": repr(cfg)}


# --------------------------------------------------------------------------
# 三段式加载
# --------------------------------------------------------------------------


@dataclass
class LoadDecision:
    fragment_id: str
    status: LoadStatus
    scope: ContextScope
    activation_reason: str
    source_ref: str
    source_version: str
    token_estimate: int
    skip_reason: str = ""
    stage: str = ""


@dataclass
class ContextLedger:
    """登记候选片段 → 分三段选择 → 每次加载/跳过都落 RunEvent。"""

    emit: Any
    run_id: str
    request_id: str
    budget_tokens: int = 4000
    fragments: dict[str, ContextFragment] = field(default_factory=dict)
    used_tokens: int = 0
    decisions: list[LoadDecision] = field(default_factory=list)

    def register(self, frag: ContextFragment) -> None:
        self.fragments[frag.fragment_id] = frag

    def register_many(self, frags: list[ContextFragment]) -> None:
        for f in frags:
            self.register(f)

    # -- 三段式 ------------------------------------------------------------
    def stage_baseline(self) -> list[ContextFragment]:
        return self._select(
            stage="baseline",
            candidates=[f for f in self.fragments.values() if f.scope == ContextScope.GLOBAL],
            default_reason="常驻基线：身份、输出合同、全局安全与确认要求",
        )

    def stage_task(self, skill_id: str) -> list[ContextFragment]:
        """第二段：只加载当前业务请求命中的一个 Skill/SOP，其余显式跳过。"""
        picked, skipped = [], []
        for f in self.fragments.values():
            if f.scope not in (ContextScope.TASK, ContextScope.SKILL):
                continue
            (picked if f.applies_to in ("", skill_id) else skipped).append(f)
        for f in skipped:
            self._record(
                f,
                LoadStatus.SKIPPED,
                stage="task_local",
                activation_reason=f"当前主请求命中的 Skill 为 {skill_id}",
                skip_reason=f"片段属于 Skill {f.applies_to or '(未绑定)'}，本轮未命中",
            )
        return self._select(
            stage="task_local",
            candidates=picked,
            default_reason=f"路由命中 Skill {skill_id}",
        )

    def stage_evidence(
        self,
        fragment_ids: list[str],
        *,
        trigger: str,
    ) -> list[ContextFragment]:
        """第三段：按需证据（检索结果、字段说明、工具结果）。"""
        cands = []
        for fid in fragment_ids:
            f = self.fragments.get(fid)
            if f is None:
                # 检索无结果也是事实，不能被模型补造
                self._record_raw(
                    fragment_id=fid,
                    scope=ContextScope.EVIDENCE,
                    status=LoadStatus.SKIPPED,
                    stage="on_demand",
                    activation_reason=trigger,
                    source_ref="(missing)",
                    source_version="(missing)",
                    token_estimate=0,
                    skip_reason="知识库中不存在该片段",
                )
                continue
            cands.append(f)
        return self._select(
            stage="on_demand",
            candidates=cands,
            default_reason=trigger,
        )

    # -- 内部 --------------------------------------------------------------
    def _select(
        self,
        *,
        stage: str,
        candidates: list[ContextFragment],
        default_reason: str,
    ) -> list[ContextFragment]:
        loaded: list[ContextFragment] = []
        for f in sorted(candidates, key=lambda x: (-x.priority, x.fragment_id)):
            if f.valid_until and _expired(f.valid_until):
                self._record(
                    f,
                    LoadStatus.EXPIRED,
                    stage=stage,
                    activation_reason=default_reason,
                    skip_reason=f"来源已过期（valid_until={f.valid_until}）",
                )
                continue
            if self.used_tokens + f.token_estimate > self.budget_tokens:
                self._record(
                    f,
                    LoadStatus.BUDGET_CAPPED,
                    stage=stage,
                    activation_reason=default_reason,
                    skip_reason=(
                        f"token 预算不足：已用 {self.used_tokens} + 需要 "
                        f"{f.token_estimate} > 预算 {self.budget_tokens}"
                    ),
                )
                continue
            loaded.append(f)
            self.used_tokens += f.token_estimate
            self._record(
                f,
                LoadStatus.LOADED,
                stage=stage,
                activation_reason=default_reason,
            )
        return loaded

    def _record(
        self,
        f: ContextFragment,
        status: LoadStatus,
        *,
        stage: str,
        activation_reason: str,
        skip_reason: str = "",
    ) -> None:
        self._record_raw(
            fragment_id=f.fragment_id,
            scope=f.scope,
            status=status,
            stage=stage,
            activation_reason=activation_reason,
            source_ref=f.source_ref,
            source_version=f.source_version,
            token_estimate=f.token_estimate,
            skip_reason=skip_reason,
        )

    def _record_raw(self, **kw: Any) -> None:
        d = LoadDecision(**kw)
        self.decisions.append(d)
        self.emit(
            "context.fragment",
            fragment_id=d.fragment_id,
            scope=str(d.scope),
            stage=d.stage,
            load_status=str(d.status),
            activation_reason=d.activation_reason,
            skip_reason=d.skip_reason,
            source_ref=d.source_ref,
            source_version=d.source_version,
            token_estimate=d.token_estimate,
        )

    # -- 输出 --------------------------------------------------------------
    def loaded_ids(self) -> list[str]:
        return [d.fragment_id for d in self.decisions if d.status == LoadStatus.LOADED]

    def render(self) -> str:
        parts = []
        for d in self.decisions:
            if d.status != LoadStatus.LOADED:
                continue
            f = self.fragments.get(d.fragment_id)
            if f is None:
                continue
            parts.append(
                f"<context-fragment id=\"{f.fragment_id}\" scope=\"{f.scope}\" "
                f"source=\"{f.source_ref}@{f.source_version}\">\n{f.content}\n"
                "</context-fragment>",
            )
        return "\n\n".join(parts)

    def audit_answer(self) -> dict[str, Any]:
        """Gate 要求：能回答本轮加载了什么、跳过什么、为什么、是否预算截断。"""
        return {
            "budget_tokens": self.budget_tokens,
            "used_tokens": self.used_tokens,
            "loaded": [
                d.__dict__ for d in self.decisions if d.status == LoadStatus.LOADED
            ],
            "skipped": [
                d.__dict__ for d in self.decisions if d.status != LoadStatus.LOADED
            ],
            "budget_capped": [
                d.fragment_id
                for d in self.decisions
                if d.status == LoadStatus.BUDGET_CAPPED
            ],
            "expired": [
                d.fragment_id for d in self.decisions if d.status == LoadStatus.EXPIRED
            ],
        }


def _expired(valid_until: str) -> bool:
    try:
        return datetime.fromisoformat(valid_until) < datetime.now(timezone.utc)
    except ValueError:
        return False


__all__ = [
    "CompactionPolicy",
    "CompactionBlocked",
    "ContextLedger",
    "LoadDecision",
    "estimate_tokens",
]
