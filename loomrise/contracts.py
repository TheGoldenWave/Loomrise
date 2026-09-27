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


class Behavior(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "require_confirm"


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
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    outcome: dict[str, Any] | None = None
    result_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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


# --------------------------------------------------------------------------
# 配置对象（来自冻结的 ScenarioPack / AgentVersion）
# --------------------------------------------------------------------------


@dataclass
class HardRule:
    rule_id: str
    scope: str  # global | task | skill
    behavior: Behavior
    reason: str
    tool: str | None = None
    requires_confirm: bool = False
    idempotent: bool = False
    when_arg_equals: dict[str, Any] = field(default_factory=dict)
    note: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "HardRule":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


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
