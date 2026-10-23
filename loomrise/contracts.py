# -*- coding: utf-8 -*-
"""Loomrise S1 领域合同 v1（权威合同，不引用上游私有类型）。

命名边界（本文件即判定结果，详见 docs/NAMING.md）：
- `ServiceRequest`：跨多轮、跨端、带副作用与结果证据的业务请求。
  它不是"一件工作"，可包含多次 `Run`。上游 AgentScope 的 `state.Task`
  只是计划/待办条目，仅在适配器内部以 `RuntimeTask` 称呼，不进入本合同。
- `Run`：一次执行尝试；`RunEvent`：执行事实（业务事实源，OTel/AG-UI 皆为其投影）。
- `SkillManifest`：策略合同。上游 Markdown 目录式 `Skill` 只是一种载体，
  仅在适配器内部以 `MarkdownSkill`/`SkillDirectory` 称呼。
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

CONTRACT_VERSION = "s1.0"
# 自持版本钉：不跟随上游"最新版"
SEMCONV_PIN = "0.66b0"
AGUI_SPEC_VERSION = "1.0"
LANGFUSE_INGESTION_VERSION = "4"


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def estimate_tokens(text: str) -> int:
    """粗略 token 估算：中文按 1 字≈1 token，西文按 4 字符≈1 token。

    ponytail: 故意不用真实 tokenizer（会引入重型依赖）。S1 只用于预算记账，
    精度上限是 ±30%；需要精确计费时换成 tiktoken/供应商计数。
    """
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    rest = max(0, len(text) - cjk)
    return max(1, cjk + rest // 4)


# --------------------------------------------------------------------------
# 枚举
# --------------------------------------------------------------------------


class RequestState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_CONFIRM = "waiting_confirm"
    CANCELLING = "cancelling"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Channel(StrEnum):
    TEXT = "text"
    VOICE = "voice"


class ToolOutcome(StrEnum):
    """业务结果语义。S1 自建 `UNKNOWN`：上游 ToolResultState 缺该态。"""

    SUCCESS = "success"
    ERROR = "error"
    INTERRUPTED = "interrupted"
    DENIED = "denied"
    UNKNOWN = "unknown"


class PlaybackState(StrEnum):
    """语音播放状态。上游只有"已发出/缓冲结束"边界，无设备级回执。"""

    GENERATED = "generated"
    SENT = "sent"
    CONFIRMED = "confirmed"
    UNKNOWN = "unknown"


class LoadStatus(StrEnum):
    LOADED = "loaded"
    SKIPPED = "skipped"
    EXPIRED = "expired"
    BUDGET_CAPPED = "budget_capped"


class ContextScope(StrEnum):
    GLOBAL = "global"
    TASK = "task"
    SKILL = "skill"
    EVIDENCE = "evidence"


class Verdict(StrEnum):
    """硬规则裁决的四种结果。

    **没有 `allow`，这是刻意的。** 一条规则能做的事只有"拦、要确认、停、去重"；
    "这个工具能不能用"由 `ToolPolicy` 的登记表达，不由规则声明。
    把两者混在一个枚举里，会出现"没有规则 = 不能用"和"有 allow 规则 = 能用"
    两种放行来源，审计时说不清到底谁批准的。
    """

    DENY = "deny"
    REQUIRE = "require"
    STOP = "stop"
    DEDUPE = "dedupe"


class GateOutcome(StrEnum):
    """确定性闸门之后"去哪"。

    与 `Verdict` **并列，不是从属**：`Verdict` 说"这个动作能不能做"，
    `GateOutcome` 说"这一轮往哪走"。一个 deny 可能导向 `block`，
    也可能导向 `route_to(人工)`；两者不能互相推导。
    """

    ROUTE_TO = "route_to"
    BLOCK = "block"
    SUSPEND = "suspend"


class SubjectScope(StrEnum):
    """记忆主体的作用域。

    `MAPPED` 的主体由业务侧映射后传入，可落库可跨轮；
    `EPHEMERAL` 只活在本次会话内，**不落库**。
    """

    MAPPED = "mapped"
    EPHEMERAL = "ephemeral"


class StateWindow(StrEnum):
    """状态计数窗口。本轮只落枚举与校验，**不实现计数器**。"""

    CYCLE = "cycle"
    H24 = "24h"
    FOREVER = "forever"
    SESSION = "session"


@dataclass
class AuthorizationResult:
    """授权查询结果。**不产 `Verdict`**——它不是裁决，是"这个工具是否登记在案"。

    登记即允许；未登记直接拒绝。这条查询必须发生在裁决之前，
    否则"未登记"会被伪装成一条 deny 规则，规则表就会变成一个权限系统。
    """

    allowed: bool
    tool_id: str = ""
    reason: str = ""
    side_effect_level: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------
# 事实对象
# --------------------------------------------------------------------------


@dataclass
class ServiceRequest:
    request_id: str
    tenant_id: str
    agent_version: str
    channel: Channel
    state: RequestState
    trigger_kind: str = "inbound_message"
    trigger_ref: str | None = None
    # 记忆主体的查询键：由业务侧映射后传入，**不是外键**，也不做身份合并。
    # 没有主体就只能落 ephemeral，且不落库——"空值即默认主体"会让不同访客的记忆串在一起。
    subject_id: str | None = None
    subject_scope: SubjectScope = SubjectScope.EPHEMERAL
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    outcome: dict[str, Any] | None = None
    result_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.subject_scope, SubjectScope):
            self.subject_scope = SubjectScope(self.subject_scope)
        if self.subject_scope is SubjectScope.MAPPED and not (self.subject_id or "").strip():
            raise ValueError(
                "subject_scope=mapped 必须提供 subject_id；没有主体只能用 ephemeral（且不落库）",
            )

    @property
    def persistent_subject(self) -> str | None:
        """可落库的主体。ephemeral 一律返回 None，调用方不得自行回退。"""
        return self.subject_id if self.subject_scope is SubjectScope.MAPPED else None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


GENESIS_HASH = "0" * 64


@dataclass
class RunEvent:
    """业务事实。追加写入、带哈希链，不依赖采样 Trace。"""

    seq: int
    event_type: str
    request_id: str
    run_id: str
    tenant_id: str
    agent_version: str
    channel: str
    ts: str = field(default_factory=now_iso)
    media_session_id: str | None = None
    trace_id: str | None = None
    idempotency_key: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    prev_hash: str = ""
    hash: str = ""

    def seal(self, prev_hash: str) -> "RunEvent":
        self.prev_hash = prev_hash
        body = json.dumps(
            {k: v for k, v in asdict(self).items() if k not in ("hash",)},
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        )
        self.hash = sha256(body)
        return self

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RunStatus(StrEnum):
    """运行生命周期。`interrupted` 是**旧代中断**，不是失败重试的同义词。

    只有 Loomrise 能决定把中断记成 `interrupted` 还是 `failed`；Adapter 无权改写。
    """

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    CANCELLED = "cancelled"


@dataclass
class Run:
    """一次执行尝试（`Run@v1` 的最小实现）。

    与 `ServiceRequest` 分开：请求是业务聚合，可跨多轮多端；`Run` 只代表一次
    冻结版本下的执行。`occupancy_generation` 是**无 Task 时的唯一放行依据**；
    有 `TaskAttempt` 时改用其 `generation`，本字段只作审计（见 ARCHITECTURE §代次）。
    """

    run_id: str
    request_id: str
    tenant_id: str
    agent_version: str
    owner_id: str = "local"
    status: RunStatus = RunStatus.RUNNING
    occupancy_generation: int = 1
    attempt_id: str | None = None
    lineage_parent: str | None = None
    started_at: str = field(default_factory=now_iso)
    ended_at: str | None = None
    snapshot: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = str(self.status)
        return d


# --------------------------------------------------------------------------
# 配置对象（来自冻结的 ScenarioPack / AgentVersion）
# --------------------------------------------------------------------------


@dataclass
class HardRule:
    rule_id: str
    scope: str  # global | task | skill
    verdict: Verdict
    reason: str
    tool: str | None = None
    requires_confirm: bool = False
    idempotent: bool = False
    when_arg_equals: dict[str, Any] = field(default_factory=dict)
    note: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "HardRule":
        # 旧键必须显式失败：`from_dict` 会过滤未知字段，静默丢弃 `behavior`
        # 会让 verdict 落到默认值，规则看上去还在、其实已不生效。
        if "behavior" in d and "verdict" not in d:
            raise ValueError(
                f"HardRule {d.get('rule_id')!r}: 字段 `behavior` 已废弃，改用 `verdict`"
                "（allow 已删除：放行由 ToolPolicy 登记表达）",
            )
        data = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        # 在边界处归一成枚举：下游用 `is` 比较，字符串会让匹配静默失败。
        if "verdict" in data and not isinstance(data["verdict"], Verdict):
            data["verdict"] = Verdict(data["verdict"])
        return cls(**data)


@dataclass
class SkillManifest:
    skill_id: str
    version: str
    title: str
    applies_when: str
    goal: str
    exit_when: str
    knowledge_ids: list[str] = field(default_factory=list)
    tool_ids: list[str] = field(default_factory=list)
    escalate_when: str = ""
    source_ref: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SkillManifest":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class ToolManifest:
    tool_id: str
    version: str
    business_meaning: str
    side_effect_level: str  # none | read_only | mock_write | real_write
    idempotent: bool
    requires_confirm: bool
    timeout_ms: int
    result_id_required: bool

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ToolManifest":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class ContextFragment:
    """上下文片段声明。S1 三段式加载的最小合同。"""

    fragment_id: str
    scope: ContextScope
    title: str
    content: str
    source_ref: str
    source_version: str
    activation_reason: str = ""
    applies_to: str = ""  # skill_id，scope=task/skill 时有效
    priority: int = 0
    sensitivity: str = "internal"
    valid_until: str | None = None
    token_estimate: int = 0

    def __post_init__(self) -> None:
        if not self.token_estimate:
            self.token_estimate = estimate_tokens(self.content)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ContextFragment":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class AgentVersion:
    version_id: str
    scenario_pack_id: str
    model: str
    model_version: str
    contract_version: str = CONTRACT_VERSION
    skill_ids: list[str] = field(default_factory=list)
    tool_ids: list[str] = field(default_factory=list)
    rule_ids: list[str] = field(default_factory=list)
    context_budget_tokens: int = 4000
    frozen_at: str = field(default_factory=now_iso)
    fingerprints: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AgentVersion":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class ScenarioPack:
    """冻结的场景包：资料 + 配置 + 案例，可导出到干净目录恢复。"""

    pack_id: str
    title: str
    agent_version: AgentVersion
    skills: list[SkillManifest]
    tools: list[ToolManifest]
    rules: list[HardRule]
    fragments: list[ContextFragment]
    routing: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str) -> "ScenarioPack":
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return cls(
            pack_id=d["pack_id"],
            title=d["title"],
            agent_version=AgentVersion.from_dict(d["agent_version"]),
            skills=[SkillManifest.from_dict(x) for x in d["skills"]],
            tools=[ToolManifest.from_dict(x) for x in d["tools"]],
            rules=[HardRule.from_dict(x) for x in d["rules"]],
            fragments=[ContextFragment.from_dict(x) for x in d["fragments"]],
            routing=d.get("routing", {}),
        )

    def skill(self, skill_id: str) -> SkillManifest:
        return next(s for s in self.skills if s.skill_id == skill_id)


@dataclass
class Case:
    """人工审定案例。ground truth 描述业务状态与预期副作用，不是"文字像不像"。"""

    case_id: str
    title: str
    channel: Channel
    turns: list[dict[str, Any]]
    expected_state: RequestState
    expected_write_count: int = 0
    expected_outcome_contains: str = ""
    forbidden: list[str] = field(default_factory=list)
    confirm_responses: list[bool] = field(default_factory=list)
    cancel_on_confirm: bool = False
    tool_failure_mode: str = "none"  # none | error | timeout_unknown
    context_budget_tokens: int = 0  # 覆盖 AgentVersion 预算，用于验证 budget_capped
    script: list[dict[str, Any]] = field(default_factory=list)
    notes: str = ""

    @classmethod
    def load(cls, path: str) -> "Case":
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        d["channel"] = Channel(d["channel"])
        d["expected_state"] = RequestState(d["expected_state"])
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
