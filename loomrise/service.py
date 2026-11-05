# -*- coding: utf-8 -*-
"""ExecutionService：S1 的统一执行内核。

文字与语音共用同一个 `ServiceRequest`、同一个 `AgentVersion`、同一套权限判断
和同一个业务结果。渠道/媒体只负责把输入搬进来，不持有业务状态。
"""

from __future__ import annotations

import asyncio
import inspect
import json
import sqlite3
import threading
from dataclasses import dataclass, field, replace
from collections.abc import Mapping
from typing import Any, Callable

from pydantic import BaseModel, Field

from .contracts import (
    Channel,
    RequestState,
    Run,
    RunAdmission,
    RunEvent,
    RunStatus,
    ScenarioPack,
    ServiceRequest,
    ServiceCycleBinding,
    SubjectScope,
    ToolOutcome,
    new_id,
    now_iso,
)
from .context import CompactionPolicy, ContextLedger
from .concurrent_loading import select_concurrent_skills
from .durable_adapter import DurableRunAdapter, action_key
from .durable_store import RecoveryReport, SqliteStore
from .ledger import EventLedger
from .rules import DecisionPolicy
from .tools import Sandbox, ToolResult
from .graph_runtime import GraphRuntime, GraphRuntimeError
from .service_cycles import ServiceCycleAuthority, cycle_config_hash
from .adapters.agentscope_runtime import (
    ConfirmLedger,
    ContextGuardMiddleware,
    PolicyMiddleware,
    build_agent,
    build_model,
    build_toolkit,
    drive_reply,
    to_tool_response,
    wrap_tool,
)
from agentscope.message import Msg, TextBlock

OUTPUT_CONTRACT = """输出合同（必须遵守）：
1. 只依据已加载上下文与工具返回的资料回答，不得补造事实。
2. 涉及业务写入时必须调用工具；人工确认由系统在工具调用前收集，不要改用提问代替执行。
3. 用户已提供课程、学员姓名与时段并明确要求报名时，直接调用 create_booking，
   不得再询问"是否确认"——确认由系统弹给人工处理。
4. 无法确认的信息要说明缺失，不得猜测。"""


class SearchKnowledgeInput(BaseModel):
    query: str = Field(description="检索关键词，例如课程名、价格、开班时间")
    limit: int = Field(default=3, description="最多返回条数")


class CreateBookingInput(BaseModel):
    course_id: str = Field(description="课程标识")
    learner_name: str = Field(description="学员姓名")
    slot: str = Field(description="期望上课时段")
    idempotency_key: str = Field(description="幂等键，同一业务请求复用同一个键")


@dataclass
class RunResult:
    request: ServiceRequest
    run_id: str
    text: str = ""
    written_result_ids: list[str] = field(default_factory=list)
    context_audit: dict[str, Any] = field(default_factory=dict)
    outcomes: list[str] = field(default_factory=list)
    admission_status: str = "created"
    run_status: RunStatus | None = None

    @property
    def write_count(self) -> int:
        return len(self.written_result_ids)


class ExecutionService:
    def __init__(
        self,
        pack: ScenarioPack,
        ledger: EventLedger | None = None,
        *,
        tenant_id: str = "tenant_demo",
        agent_id: str | None = None,
        ask_confirm: Callable[[list[Any]], list[bool]] | None = None,
        failure_mode: str = "none",
        compaction_mode: str = "deny",
        store: SqliteStore | None = None,
        owner_id: str | None = None,
        graph_selector: Callable[[list[Mapping[str, Any]], Mapping[str, Any]], Mapping[str, Any] | None] | None = None,
        concurrent_selector: Callable[..., Any] | None = None,
        completion_evaluator: Callable[..., Any] | None = None,
        model_provider: Any = None,
        cycle_authority: ServiceCycleAuthority | None = None,
    ) -> None:
        if agent_id is not None and (not isinstance(agent_id, str) or not agent_id.strip()):
            raise ValueError("agent_id 必须为非空专家标识，或 None")
        self.agent_id = agent_id
        if cycle_authority is not None and (
            not isinstance(cycle_authority, ServiceCycleAuthority) or cycle_authority.store is not store
            or cycle_authority.tenant_id != tenant_id or cycle_authority.agent_id != agent_id
        ):
            raise ValueError('cycle authority must be explicitly scoped to this store/tenant/agent')
        self.cycle_authority = cycle_authority
        self._event_lock = threading.RLock()
        self.concurrent_selector = concurrent_selector
        self.model_provider = model_provider
        self.pack = pack
        version_graph = pack.agent_version.orchestration or pack.orchestration
        # A graph snapshot is the full immutable config envelope, not only the
        # nested ``orchestration`` object; Unit references must resolve against
        # the same snapshot's ``units`` registry.
        self.graph_config = (
            dict(version_graph)
            if isinstance(version_graph, Mapping) and isinstance(version_graph.get("orchestration"), Mapping)
            else None
        )
        self.unit_skill_bindings = dict(
            pack.agent_version.unit_skill_bindings
            or pack.unit_skill_bindings
            or (self.graph_config or {}).get("unit_skill_bindings", {})
        )
        self.cycle_config_hash = cycle_config_hash(
            self.graph_config, self.unit_skill_bindings if self.graph_config is not None else {})
        self.graph_runtime = GraphRuntime(self.graph_config, selector=graph_selector,
            completion_evaluator=completion_evaluator) if self.graph_config is not None else None
        self.ledger = ledger or EventLedger()
        self.tenant_id = tenant_id
        self.ask_confirm = ask_confirm or (lambda calls: [False] * len(calls))
        self.failure_mode = failure_mode
        self.compaction = CompactionPolicy(compaction_mode)
        self.requests: dict[str, ServiceRequest] = {}
        self._active: dict[str, asyncio.Task[Any]] = {}
        # 幂等写入账本：跨轮次、跨渠道共享（文字发起、语音确认也只写一次）
        self._writes: dict[str, str] = {}
        # 对话状态按业务请求复用：同一请求换渠道/换轮次时模型仍看得到前文
        self._states: dict[str, Any] = {}
        # 耐久层是可选下游：不传 store 时行为与 S1 完全一致，不改变任何既有验收。
        self.durable: DurableRunAdapter | None = None
        self.recovery: RecoveryReport | None = None
        if store is not None:
            self.durable = DurableRunAdapter(
                store,
                owner_id=owner_id or f"local-{new_id('owner')}",
                tenant_id=tenant_id,
            )
            # 先恢复再挂 sink：恢复阶段要写"中断"事件，不能与业务写入抢同一路径。
            self.recovery = self.durable.recover()
            if self.recovery.idempotent_keys:
                # 跨重启的幂等索引：不恢复它，重启后同一键会被再写一次。
                self._writes.update(self.recovery.idempotent_keys)
            self.ledger.sink = self.durable.persist

    def _record_durable_event(self, event: RunEvent) -> None:
        """每Run持久seq与进程投影seq各自分配；投影封链和追加共用短锁。"""
        with self._event_lock:
            self.ledger.record(replace(event, seq=len(self.ledger.events)), persist=False)

    def _emit_event(self, event_type: str, **kwargs: Any) -> RunEvent:
        with self._event_lock:
            return self.ledger.emit(event_type, **kwargs)

    # -- 对外入口 ----------------------------------------------------------
    async def handle_text(
        self,
        text: str,
        *,
        request: ServiceRequest | None = None,
        script: list[dict[str, Any]] | None = None,
        ask_confirm: Callable[[list[Any]], list[bool]] | None = None,
        failure_mode: str | None = None,
        trigger_event_id: str | None = None,
        trigger_kind: str | None = None,
        routing_state: Mapping[str, Any] | None = None,
        cycle_grant: object | None = None,
    ) -> RunResult:
        return await self._handle(
            text,
            channel=Channel.TEXT,
            request=request,
            script=script,
            ask_confirm=ask_confirm,
            failure_mode=failure_mode,
            trigger_event_id=trigger_event_id,
            trigger_kind=trigger_kind,
            routing_state=routing_state,
            cycle_grant=cycle_grant,
        )

    async def handle_utterance(
        self,
        text: str,
        *,
        media_session_id: str,
        request: ServiceRequest | None = None,
        script: list[dict[str, Any]] | None = None,
        ask_confirm: Callable[[list[Any]], list[bool]] | None = None,
        failure_mode: str | None = None,
        trigger_event_id: str | None = None,
        trigger_kind: str | None = None,
        routing_state: Mapping[str, Any] | None = None,
        cycle_grant: object | None = None,
    ) -> RunResult:
        """语音入口：与文字共用同一业务请求、权限与结果。"""
        return await self._handle(
            text,
            channel=Channel.VOICE,
            media_session_id=media_session_id,
            request=request,
            script=script,
            ask_confirm=ask_confirm,
            failure_mode=failure_mode,
            trigger_event_id=trigger_event_id,
            trigger_kind=trigger_kind,
            routing_state=routing_state,
            cycle_grant=cycle_grant,
        )

    async def resume_recoverable_request(
        self,
        request_id: str,
        *,
        script: list[dict[str, Any]] | None = None,
        ask_confirm: Callable[[list[Any]], list[bool]] | None = None,
    ) -> RunResult:
        """Explicitly start a new Run for a safely recoverable queued request.

        A recovered confirmation is asked again in this R1 path. R2's durable
        suspend/wake keeps the original pending confirmation instead.
        """
        if self.durable is None:
            raise RuntimeError("恢复请求需要持久 store")
        row = self.durable.store.request_row(request_id)
        if row is None or row["tenant_id"] != self.tenant_id:
            raise KeyError("未知请求")
        if row["state"] not in (RequestState.QUEUED.value, RequestState.WAITING_CONFIRM.value):
            raise RuntimeError("请求当前不可恢复")
        if row["latest_run_status"] != RunStatus.FAILED.value:
            raise RuntimeError("请求没有已中断的旧运行")
        previous_run_id = row["latest_run_id"]
        previous_run = self.durable.store.run_row(previous_run_id)
        if previous_run is None or previous_run["finish_reason"] not in {"restart_interrupted", "wake_superseded"}:
            raise RuntimeError("请求不是由重启中断")
        if row["agent_version"] != self.pack.agent_version.version_id:
            raise RuntimeError("配置版本已变化，请按新版本重新发起请求")
        if not self._matches_run_snapshot(previous_run):
            raise RuntimeError("恢复的专家、版本或冻结配置不匹配")
        events = self.durable.store.load_events(previous_run_id)
        if any(
            event.event_type == "permission.confirm_answered"
            or (event.event_type == "tool.outcome" and event.payload.get("tool") != "search_knowledge")
            for event in events
        ) or self.durable.store.request_has_committed_write(request_id):
            raise RuntimeError("请求已有副作用或确认事实，须先人工核对，不能自动恢复")
        if previous_run["finish_reason"] == "wake_superseded":
            parked = self.durable.wait_row(previous_run_id)
            wake = (parked or {}).get("metadata", {}).get("wake", {})
            wake_state = wake.get("routing_state")
            if (not parked or parked["state"] != "woken" or not isinstance(wake_state, Mapping)
                    or not any(event.event_type == "run.wait_woken" for event in events)):
                raise RuntimeError("唤醒证据缺失，不能恢复")
            return await self._resume_with_routing(request_id, wake_state, script=script, ask_confirm=ask_confirm)
        start = next((event for event in events if event.event_type == "run.started"), None)
        text = start.payload.get("input") if start is not None else None
        if not isinstance(text, str) or not text:
            raise RuntimeError("原始请求输入缺失，不能恢复")
        request = ServiceRequest(
            request_id=request_id,
            tenant_id=row["tenant_id"],
            agent_version=row["agent_version"],
            channel=Channel(row["channel"]),
            state=RequestState(row["state"]),
            trigger_kind=row.get("trigger_kind") or "inbound_message",
            trigger_ref=row.get("trigger_ref"),
            subject_id=row.get("subject_id") if row.get("subject_scope") == SubjectScope.MAPPED.value else None,
            subject_scope=SubjectScope.MAPPED if row.get("subject_scope") == SubjectScope.MAPPED.value else SubjectScope.EPHEMERAL,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            result_id=row.get("result_id"),
            service_cycle=json.loads(row.get('service_cycle_json') or 'null'),
        )
        return await self._handle(
            text,
            channel=request.channel,
            request=request,
            script=script,
            ask_confirm=ask_confirm,
            resume_lineage_parent=previous_run_id,
            resume_generation=int(row["latest_generation"] or 0) + 1,
            resume_expected_request_state=row["state"],
            routing_state=json.loads(previous_run["snapshot_json"]).get("routing_state"),
        )

    def _matches_run_snapshot(self, row: Mapping[str, Any]) -> bool:
        snapshot = json.loads(row["snapshot_json"])
        binding = snapshot.get('service_cycle')
        if binding is not None:
            request = self.durable.store.request_row(row['request_id']) if self.durable else None
            if (request is None or json.loads(request.get('service_cycle_json') or 'null') != binding
                    or binding.get('config_hash') != self.cycle_config_hash
                    or binding.get('tenant_id') != self.tenant_id or binding.get('agent_id') != self.agent_id
                    or binding.get('subject_id') != request.get('subject_id')
                    or binding.get('agent_version') != self.pack.agent_version.version_id):
                return False
        return (row["tenant_id"] == self.tenant_id
                and row["agent_version"] == self.pack.agent_version.version_id
                and snapshot.get("agent_id") == self.agent_id
                and snapshot.get("orchestration") == self.graph_config
                and snapshot.get("unit_skill_bindings", {}) == (self.unit_skill_bindings if self.graph_runtime else {}))

    async def wake_waiting_request(
        self,
        run_id: str,
        *,
        wake_kind: str = "event",
        event: str | None = None,
        script: list[dict[str, Any]] | None = None,
        ask_confirm: Callable[[list[Any]], list[bool]] | None = None,
    ) -> RunResult:
        """Consume a durable graph wait, then start a fenced successor run."""
        if self.durable is None:
            raise RuntimeError("唤醒请求需要持久 store")
        parked = self.durable.wait_row(run_id)
        if parked is None:
            raise KeyError("未知 waiting run")
        row = self.durable.store.run_row(run_id)
        if row is None or row['tenant_id'] != self.tenant_id:
            raise KeyError('未知 waiting run')
        if not self._matches_run_snapshot(row):
            raise RuntimeError('等待的专家、版本或冻结配置不匹配')
        if wake_kind not in ('event', 'timeout'):
            raise ValueError('wake_kind 必须为 event 或 timeout')
        if wake_kind == 'event' and event != parked['waiting_on']:
            raise ValueError('唤醒事件必须匹配等待事件')
        if wake_kind == 'timeout' and (event is not None or not parked.get('timeout_to')):
            raise RuntimeError('超时唤醒需要明确 timeoutTo，且不能同时提供事件')
        metadata = dict(parked.get("metadata") or {})
        routing_state = dict(metadata.get("routing_state") or {})
        routing_state["cycle_counters"] = dict(metadata.get("cycle_counters") or {})
        routing_state["__graph_continuation"] = dict(metadata.get("continuation") or {})
        routing_state["__wait_resume_path"] = list(metadata.get("waiting_path") or [])
        routing_state.pop("event", None)
        routing_state.pop("__wait_timeout_to", None)
        if event is not None:
            routing_state["event"] = event
        elif wake_kind == "timeout":
            if not parked.get("timeout_to"):
                raise RuntimeError("等待没有 timeoutTo，不能按超时唤醒")
            routing_state["__wait_timeout_to"] = parked["timeout_to"]
        wake_result = self.durable.wake_wait(run_id, wake_kind=wake_kind,
                                            agent_version=self.pack.agent_version.version_id,
                                            wake_state=routing_state)
        wake_event = wake_result.get('wake_event')
        if wake_event is not None:
            self._record_durable_event(wake_event)
        return await self._resume_with_routing(
            row["request_id"], routing_state, script=script, ask_confirm=ask_confirm,
        )

    async def wake_due_waits(self, *, limit: int | None = None,
                             script: list[dict[str, Any]] | None = None) -> list[RunResult]:
        """Process due waits once; scheduling remains owned by the caller."""
        if self.durable is None:
            raise RuntimeError("超时等待需要持久 store")
        due = self.durable.due_waits()
        if limit is not None:
            due = due[:max(0, int(limit))]
        results: list[RunResult] = []
        for item in due:
            try:
                results.append(await self.wake_waiting_request(
                    item["run_id"], wake_kind="timeout", script=script,
                ))
            except RuntimeError as exc:
                # Another scheduler may have consumed the same due row after
                # the read snapshot. The durable transition is the authority;
                # stale claims are safely skipped and can be audited by caller.
                if "已被唤醒" not in str(exc) and "不属于当前租户" not in str(exc):
                    raise
        return results

    async def _resume_with_routing(self, request_id: str, routing_state: Mapping[str, Any], *,
                                   script=None, ask_confirm=None) -> RunResult:
        row = self.durable.store.request_row(request_id) if self.durable else None
        if row is None:
            raise KeyError("未知请求")
        events = self.durable.store.load_events(row["latest_run_id"])
        start = next((event for event in events if event.event_type == "run.started"), None)
        if start is None or not isinstance(start.payload.get("input"), str):
            raise RuntimeError("原始请求输入缺失，不能恢复")
        request = ServiceRequest(request_id=request_id, tenant_id=row["tenant_id"],
            agent_version=row["agent_version"], channel=Channel(row["channel"]),
            state=RequestState(row["state"]), trigger_kind=row.get("trigger_kind") or "inbound_message",
            trigger_ref=row.get('trigger_ref'),
            subject_id=row.get('subject_id') if row.get('subject_scope') == SubjectScope.MAPPED.value else None,
            subject_scope=SubjectScope.MAPPED if row.get('subject_scope') == SubjectScope.MAPPED.value else SubjectScope.EPHEMERAL,
            service_cycle=json.loads(row.get('service_cycle_json') or 'null'),
            created_at=row["created_at"], updated_at=row["updated_at"])
        return await self._handle(start.payload["input"], channel=request.channel, request=request,
            script=script, ask_confirm=ask_confirm, routing_state=routing_state,
            resume_lineage_parent=row["latest_run_id"], resume_generation=int(row["latest_generation"] or 0) + 1,
            resume_expected_request_state=row["state"])

    def cancel(self, request_id: str, *, run_id: str, reason: str = "user_cancel") -> bool:
        """取消请求已发送 ≠ 业务动作已撤销：两件事分别记账。"""
        started = next((e for e in self.ledger.find("run.started") if e.run_id == run_id and e.request_id == request_id), None)
        if started is None and self.durable is not None:
            durable_events = self.durable.store.load_events(run_id)
            started = next((e for e in durable_events if e.event_type == "run.started" and e.request_id == request_id), None)
        if started is None:
            return False
        if self.durable is not None:
            parked = self.durable.wait_row(run_id)
            if parked is not None and parked["state"] == "waiting":
                row = self.durable.store.run_row(run_id)
                if row is None or row["request_id"] != request_id or not self._matches_run_snapshot(row):
                    return False
                import json
                waiting_run = Run(
                    run_id=row["run_id"], request_id=row["request_id"], tenant_id=row["tenant_id"],
                    agent_version=row["agent_version"], owner_id=row["owner_id"],
                    status=RunStatus(row["status"]), occupancy_generation=int(row["occupancy_generation"]),
                    attempt_id=row["attempt_id"], lineage_parent=row["lineage_parent"],
                    started_at=row["started_at"], ended_at=row["ended_at"],
                    snapshot=json.loads(row["snapshot_json"]),
                )
                events = self.durable.cancel_wait(waiting_run, reason=reason)
                for event in events:
                    self._record_durable_event(event)
                return True
        self._emit_event(
            "run.cancel_requested",
            request_id=request_id,
            run_id=run_id,
            tenant_id=self.tenant_id,
            agent_version=self.pack.agent_version.version_id,
            channel=started.channel,
            reason=reason,
        )
        task = self._active.get(run_id)
        if task is None or task.done():
            self._emit_event(
                "run.cancel_not_revoked", request_id=request_id, run_id=run_id,
                tenant_id=self.tenant_id, agent_version=self.pack.agent_version.version_id,
                channel=started.channel, reason="run_already_finished",
            )
            return False
        self.requests[request_id].state = RequestState.CANCELLING
        task.cancel()
        return True

    # -- 执行 --------------------------------------------------------------
    async def _handle(
        self,
        text: str,
        *,
        channel: Channel,
        request: ServiceRequest | None = None,
        script: list[dict[str, Any]] | None = None,
        ask_confirm: Callable[[list[Any]], list[bool]] | None = None,
        failure_mode: str | None = None,
        media_session_id: str | None = None,
        trigger_event_id: str | None = None,
        trigger_kind: str | None = None,
        resume_lineage_parent: str | None = None,
        resume_generation: int = 1,
        resume_expected_request_state: str | None = None,
        routing_state: Mapping[str, Any] | None = None,
        cycle_grant: object | None = None,
    ) -> RunResult:
        av = self.pack.agent_version
        req = request or self._new_request(channel, text)
        if req.tenant_id != self.tenant_id:
            raise ValueError("请求租户与执行服务不一致")
        binding = None
        if cycle_grant is not None:
            if self.cycle_authority is None:
                raise ValueError('cycle grant requires an injected server-side authority')
            binding = self.cycle_authority.resolve(cycle_grant)
            if (req.persistent_subject != binding.subject_id or binding.tenant_id != self.tenant_id
                    or binding.agent_id != self.agent_id or binding.agent_version != av.version_id
                    or binding.config_hash != self.cycle_config_hash):
                raise ValueError('cycle grant scope/version/config does not match mapped 主体')
            if req.service_cycle is not None and req.service_cycle != binding:
                raise ValueError('request service cycle binding is immutable')
        elif req.service_cycle is not None:
            if resume_lineage_parent is None or self.durable is None:
                raise ValueError('caller cycle binding requires a trusted grant 授权')
            original = self.durable.store.request_row(req.request_id)
            if original is None or json.loads(original.get('service_cycle_json') or 'null') != req.service_cycle.to_dict():
                raise ValueError('restored service cycle binding mismatch')
            binding = req.service_cycle
        if binding is not None and resume_lineage_parent is None:
            routing_state = {key: value for key, value in (routing_state or {}).items()
                             if isinstance(key, str) and not key.startswith('__') and key != 'cycle_counters'}
        # 事件身份属于本轮输入，不能从上一轮可变请求继承。
        candidate = replace(req, channel=channel, agent_version=av.version_id,
                            state=RequestState.RUNNING,
                            trigger_event_id=trigger_event_id,
                            trigger_kind=req.trigger_kind if trigger_kind is None else trigger_kind,
                            service_cycle=binding)
        if trigger_event_id is not None and self.durable is None:
            raise ValueError("事件级幂等需要持久 store")
        run: Run | None = None
        admission: RunAdmission | None = None
        if self.durable is not None:
            admission = self.durable.begin(
                candidate,
                agent_version=av.version_id,
                snapshot={"agent_id": self.agent_id,
                          "skill_routing": self.pack.routing,
                          "context_budget": av.context_budget_tokens,
                          "orchestration": self.graph_config,
                          "unit_skill_bindings": self.unit_skill_bindings if self.graph_runtime else {},
                          "service_cycle": binding.to_dict() if binding else None,
                          "cycle_config_hash": self.cycle_config_hash if binding else None,
                          "routing_state": dict(routing_state or {}) if self.graph_runtime else {}},
                scenario_pack_id=av.scenario_pack_id,
                input_text=text,
                event_seq=len(self.ledger.events),
                media_session_id=media_session_id,
                lineage_parent=resume_lineage_parent,
                generation=resume_generation,
                recovery_previous_run_id=resume_lineage_parent,
                recovery_expected_request_state=resume_expected_request_state,
            )
            run = admission.run
            if admission.status != "created":
                return RunResult(admission.request, run.run_id,
                                 admission_status=admission.status, run_status=run.status)
            run_id = run.run_id
        else:
            run_id = new_id("run")
        req.service_cycle = binding
        req.trigger_event_id = trigger_event_id
        req.trigger_kind = candidate.trigger_kind
        self.requests[req.request_id] = req
        req.state = RequestState.RUNNING
        self._active[run_id] = asyncio.current_task()

        def emit(event_type: str, **payload: Any):
            return self._emit_event(
                event_type,
                request_id=req.request_id,
                run_id=run_id,
                tenant_id=self.tenant_id,
                agent_version=av.version_id,
                channel=channel.value,
                media_session_id=media_session_id,
                **payload,
            )

        if admission is not None and admission.first_event is not None:
            self._record_durable_event(admission.first_event)
        else:
            emit("run.started", trigger_kind=candidate.trigger_kind, input=text,
                 event_deduplication=False)

        graph_text = ""
        concurrent_selector = self.concurrent_selector
        # 1) 路由：显式 R3 图模式是唯一来源；没有图时保留 R1 关键词路由。
        if self.graph_runtime is not None:
            provider = self.model_provider
            provider_error = False
            if provider is None and script is None:
                from .model_provider import LocalModelProvider
                try:
                    provider = LocalModelProvider.from_local_config()
                except (OSError, ValueError, RuntimeError, KeyError):
                    provider_error = True
            if provider is not None and hasattr(provider, 'for_run'):
                provider = provider.for_run()
            runtime = self.graph_runtime
            cancelled = threading.Event()
            def guarded(callback):
                def call(*args):
                    if cancelled.is_set():
                        raise GraphRuntimeError('graph provider call cancelled')
                    value = callback(*args)
                    if cancelled.is_set():
                        raise GraphRuntimeError('graph provider result cancelled')
                    return value
                return call
            if provider is not None:
                runtime = GraphRuntime(self.graph_config,
                    selector=guarded(runtime.selector or provider.route),
                    completion_evaluator=guarded(runtime.completion_evaluator or provider.completion))
                concurrent_selector = concurrent_selector or provider.recall
            graph_state = {**dict(routing_state or {}), "input": text, "recent_turns": [text]}
            # State-window statistics are a durable projection, never caller input.
            graph_state.pop('state_window_counts', None)
            continuation = graph_state.pop("__graph_continuation", None)
            authoritative_counters = None
            if binding is not None and self.durable is not None:
                # Only persisted wait/recovery code may supply a checkpoint.
                if resume_lineage_parent is None:
                    continuation = None
                    for key in tuple(graph_state):
                        if key.startswith('__'):
                            graph_state.pop(key)
                authoritative_counters = {}
                for key, count in self.durable.store.service_cycle_counts(binding.cycle_id).items():
                    parts = json.loads(key)
                    if parts[0] == 'loop':
                        authoritative_counters[json.dumps(parts[1:], ensure_ascii=False, separators=(',', ':'))] = count
                        _, counter_field = runtime.cycle_budget('loop', tuple(parts[1:-1]), parts[-1])
                        graph_state[counter_field] = count
                graph_state['cycle_counters'] = authoritative_counters
            try:
                if self.durable is not None:
                    persisted_agent_id = (run.snapshot.get('agent_id')
                                          if run is not None and isinstance(run.snapshot, Mapping) else None)
                    if isinstance(persisted_agent_id, str) and persisted_agent_id.strip():
                        try:
                            graph_state['state_window_counts'] = self.durable.store.state_window_counts(
                                tenant_id=self.tenant_id, agent_id=persisted_agent_id,
                                agent_version=av.version_id,
                                cycle_id=binding.cycle_id if binding is not None else None)
                        except (ValueError, sqlite3.Error) as exc:
                            raise GraphRuntimeError(f'state-window counts unavailable: {exc}') from exc
                if runtime.requires_service_cycle() and (binding is None or self.durable is None):
                    raise GraphRuntimeError('graph requires a trusted service cycle with durable reservations')
                if provider_error:
                    raise GraphRuntimeError('local model connection configuration is invalid')
                if provider is not None and getattr(provider, 'model', None) != av.model:
                    raise GraphRuntimeError('graph model provider does not match the frozen AgentVersion')
                buffered = []
                reserve_cycle = None
                if binding is not None and self.durable is not None and run is not None:
                    emit('route.graph.started', schema_version='unit-graph-v1')
                    def reserve_cycle(**budget):
                        with self._event_lock:
                            if cancelled.is_set():
                                raise GraphRuntimeError('cancelled run cannot reserve service cycle')
                            event = RunEvent(seq=len(self.ledger.events), event_type='route.graph.cycle',
                                request_id=req.request_id, run_id=run_id, tenant_id=self.tenant_id,
                                agent_version=av.version_id, channel=channel.value,
                                media_session_id=media_session_id, payload={'counter': budget.pop('counter', None)})
                            try:
                                reservation = self.durable.store.reserve_service_cycle(
                                    run_id, generation=run.occupancy_generation, binding=binding, event=event, **budget)
                            except (ValueError, RuntimeError, sqlite3.Error) as exc:
                                raise GraphRuntimeError(f'service cycle reservation failed: {exc}') from exc
                            self._record_durable_event(event)
                            return reservation
                route = await asyncio.to_thread(runtime.route_and_emit,
                    {**graph_state,
                     **({"event": trigger_kind} if trigger_kind in {"user_hangup", "side_effect_unknown", "timeout", "handoff"} else {})},
                    lambda event_type, **payload: buffered.append((event_type, payload)),
                    cycle_counters=(authoritative_counters if binding is not None else (routing_state or {}).get("cycle_counters")),
                    continuation=continuation,
                    reserve_cycle=reserve_cycle,
                )
                for event_type, payload in buffered:
                    if reserve_cycle is not None and event_type == 'route.graph.started':
                        continue
                    emit(event_type, **payload)
            except asyncio.CancelledError:
                cancelled.set()
                req.state = RequestState.CANCELLED
                emit('run.cancel_confirmed', write_prevented=True, business_action_revoked=False, result_ids=[])
                emit('run.finished', request_state=req.state.value, write_count=0, result_ids=[])
                if self.durable is not None and run is not None:
                    self.durable.finish(run, request_state=req.state.value, status=RunStatus.CANCELLED)
                self._active.pop(run_id, None)
                return RunResult(req, run_id, run_status=run.status if run else None)
            except GraphRuntimeError as exc:
                emit("request.route_failed", reason=str(exc), source="unit_graph")
                req.state = RequestState.FAILED
                emit("run.finished", request_state=req.state.value, write_count=0, result_ids=[])
                if self.durable is not None and run is not None:
                    self.durable.finish(run, request_state=req.state.value)
                self._active.pop(run_id, None)
                return RunResult(req, run_id, run_status=run.status if run else None)
            if self.durable is not None and run is not None:
                self.durable.store.update_run_snapshot(run_id, {
                    'routing_state': {**dict(routing_state or {}), 'cycle_counters': dict(route.cycle_counters),
                                      '__graph_continuation': route.continuation},
                    'route_status': route.status,
                    'route_terminal_unit_id': route.terminal_unit_id,
                })
            if route.status != "completed" or not route.terminal_unit_id:
                if route.status == "waiting" and self.durable is not None and run is not None:
                    req.state = RequestState.WAITING
                    emit("request.route_waiting", waiting_on=route.waiting_on,
                         timeout_ms=route.wait_timeout_ms, timeout_to=route.wait_timeout_to,
                         source="unit_graph")
                    messages = route.messages[route.message_cursor:]
                    graph_text = "\n".join(message["text"] for message in messages)
                    message_events = []
                    for event_type, payload in self._graph_message_payloads(messages):
                        message_events.append(RunEvent(
                            seq=len(self.ledger.events) + len(message_events), event_type=event_type,
                            request_id=req.request_id, run_id=run_id, tenant_id=self.tenant_id,
                            agent_version=av.version_id, channel=channel.value,
                            media_session_id=media_session_id, payload=payload,
                        ))
                    route.continuation["message_cursor"] = len(route.messages)
                    self.durable.suspend_wait(
                        run,
                        waiting_on=str(route.waiting_on),
                        timeout_ms=route.wait_timeout_ms,
                        timeout_to=route.wait_timeout_to,
                        metadata={"routing_state": dict(routing_state or {}),
                                  "cycle_counters": dict(route.cycle_counters),
                                  "continuation": route.continuation,
                                  "waiting_path": list(route.waiting_path)},
                        events=message_events,
                    )
                    for event in message_events:
                        self._record_durable_event(event)
                    self._active.pop(run_id, None)
                    return RunResult(req, run_id, text=graph_text, run_status=run.status)
                reason = (
                    "graph_wait_suspend_unavailable"
                    if route.status == "waiting"
                    else route.fallback or route.status
                )
                emit("request.route_failed", reason=reason, source="unit_graph")
                req.state = RequestState.FAILED
                emit("run.finished", request_state=req.state.value, write_count=0, result_ids=[])
                if self.durable is not None and run is not None:
                    self.durable.finish(run, request_state=req.state.value)
                self._active.pop(run_id, None)
                return RunResult(req, run_id, run_status=run.status if run else None)
            skill_id = self._graph_skill(route.terminal_unit_id)
            if skill_id is None:
                emit("request.route_failed", reason="terminal Unit has no valid Skill binding", source="unit_graph")
                req.state = RequestState.FAILED
                emit("run.finished", request_state=req.state.value, write_count=0, result_ids=[])
                if self.durable is not None and run is not None:
                    self.durable.finish(run, request_state=req.state.value)
                self._active.pop(run_id, None)
                return RunResult(req, run_id, run_status=run.status if run else None)
            emit("request.routed", skill_id=skill_id, unit_id=route.terminal_unit_id, reason="versioned Unit graph")
            messages = route.messages[route.message_cursor:]
            graph_text = "\n".join(message["text"] for message in messages)
            for event_type, payload in self._graph_message_payloads(messages):
                emit(event_type, **payload)
        else:
            skill_id = self._route(text)
            emit("request.routed", skill_id=skill_id, reason=f"关键词命中 {skill_id}")

        # 2) 上下文：常驻基线 + 当前 Skill（第三段按需证据由工具触发）
        ctx = ContextLedger(
            emit=emit,
            run_id=run_id,
            request_id=req.request_id,
            budget_tokens=av.context_budget_tokens,
            subject_id=req.subject_id,
            subject_scope=req.subject_scope,
        )
        ctx.register_many(self.pack.fragments)
        ctx.stage_baseline()
        ctx.stage_task(skill_id)
        if self.graph_runtime is not None:
            try:
                recalled_skills = await select_concurrent_skills(
                    self.graph_config, self.pack, self.unit_skill_bindings, route,
                    text=text, available_skills=ctx.available_skill_ids(),
                    selector=concurrent_selector, emit=emit,
                )
            except asyncio.CancelledError:
                req.state = RequestState.CANCELLED
                req.updated_at = now_iso()
                emit('run.cancel_confirmed', write_prevented=True, business_action_revoked=False, result_ids=[])
                emit('run.finished', request_state=req.state.value, write_count=0, result_ids=[])
                if self.durable is not None and run is not None:
                    self.durable.finish(run, request_state=req.state.value, status=RunStatus.CANCELLED)
                self._active.pop(run_id, None)
                return RunResult(req, run_id, context_audit=ctx.audit_answer(), run_status=run.status if run else None)
            ctx.stage_concurrent(recalled_skills)

        # 3) 策略与沙盒。授权来源是 ToolPolicy 登记，不是规则表——两件事分开传。
        authorized_tools = self.pack.tools
        if self.graph_runtime is not None:
            allowed_tool_ids = set(av.tool_ids) & set(self.pack.skill(skill_id).tool_ids)
            authorized_tools = [tool for tool in self.pack.tools if tool.tool_id in allowed_tool_ids]
        policy = DecisionPolicy(
            self.pack.rules,
            emit=emit,
            writes=self._writes,
            tools=authorized_tools,
        )
        sandbox = Sandbox(
            self.pack.fragments,
            policy,
            ctx,
            failure_mode=failure_mode or self.failure_mode,
        )
        outcomes: list[str] = []
        supplier_states: list[str] = []
        written: list[str] = []

        async def _search(query: str, limit: int = 3):
            r: ToolResult = await sandbox.search_knowledge(query, limit)
            emit(
                "tool.outcome",
                tool="search_knowledge",
                outcome=r.outcome.value,
                duration_ms=r.duration_ms,
                no_result=r.payload.get("no_result", False),
            )
            return to_tool_response(r)

        async def _book(course_id: str, learner_name: str, slot: str, idempotency_key: str):
            if req.state is RequestState.CANCELLING:
                raise asyncio.CancelledError()
            attempt_key = action_key("create_booking", idempotency_key)
            if self.durable is not None:
                attempt = self.durable.store.begin_tool_attempt(
                    run_id=run_id,
                    attempt_key=attempt_key,
                    action="create_booking",
                    arguments={
                        "course_id": course_id,
                        "learner_name": learner_name,
                        "slot": slot,
                    },
                )
                if not attempt["created"]:
                    raise RuntimeError("该业务操作已有结果，拒绝再次执行")
            r: ToolResult = await sandbox.create_booking(
                course_id, learner_name, slot, idempotency_key,
            )
            if self.durable is not None:
                if r.outcome is ToolOutcome.UNKNOWN:
                    self.durable.store.mark_tool_attempt_unknown(
                        attempt_key, run_id=run_id,
                    )
                elif r.outcome is not ToolOutcome.SUCCESS:
                    self.durable.store.mark_tool_attempt_failed(
                        attempt_key, run_id=run_id,
                    )
            emit(
                "tool.outcome",
                tool="create_booking",
                outcome=r.outcome.value,
                result_id=r.result_id,
                duration_ms=r.duration_ms,
                # 幂等键必须进事件本身：耐久层靠它把"写入事实"与
                # 幂等记录/outbox 放进同一事务，而不是另开一张表再对账。
                idempotency_key=idempotency_key,
            )
            outcomes.append(r.outcome.value)
            if r.result_id:
                written.append(r.result_id)
            return to_tool_response(r)

        tool_definitions = {
            'search_knowledge': wrap_tool(
                _search,
                name="search_knowledge",
                description="只读检索已授权课程资料，返回带来源与版本的片段",
                input_model=SearchKnowledgeInput,
                read_only=True,
            ),
            'create_booking': wrap_tool(
                _book,
                name="create_booking",
                description="模拟写入：创建一条课程预约，返回 result_id",
                input_model=CreateBookingInput,
                read_only=False,
                ask_permission=True,
            ),
        }
        toolkit = await build_toolkit([tool for name, tool in tool_definitions.items()
                                      if self.graph_runtime is None or name in allowed_tool_ids])

        # 4) 组装 Agent（SDK 只做执行器）
        model = build_model(script)
        confirms = ConfirmLedger()
        guard = ContextGuardMiddleware(self.compaction, emit)
        policy_mw = PolicyMiddleware(policy, emit, skill_id=skill_id, confirms=confirms)
        skill = self.pack.skill(skill_id)
        system_prompt = _build_system_prompt(skill, ctx.render())
        agent = build_agent(
            name="course_consult_agent",
            system_prompt=system_prompt,
            model=model,
            toolkit=toolkit,
            middlewares=[guard, policy_mw],
            state=self._states.get(req.request_id),
        )
        self._states[req.request_id] = agent.state

        async def persisted_ask_confirm(calls: list[Any]) -> list[bool]:
            if self.durable is not None:
                req.state = RequestState.WAITING_CONFIRM
                req.updated_at = now_iso()
                self.durable.update_request_state(req.request_id, req.state.value)
            try:
                answers = (ask_confirm or self.ask_confirm)(calls)
                if inspect.isawaitable(answers):
                    answers = await answers
                return answers
            finally:
                if self.durable is not None and req.state is RequestState.WAITING_CONFIRM:
                    req.state = RequestState.RUNNING
                    req.updated_at = now_iso()
                    self.durable.update_request_state(req.request_id, req.state.value)

        # 5) 驱动一次 reply（含人工确认恢复）
        final_text = ""
        text_emitted = False  # 是否已产出过 reply.text（AG-UI 的文本来源）

        def close_run() -> None:
            """收尾：运行状态与 `run.finished` 事件同一事务提交。

            没有耐久层时是空操作；有的话必须调，否则恢复会把这轮误判成中断。
            """
            if self.durable is None or run is None:
                return
            self.durable.finish(
                run,
                request_state=req.state.value,
                result_id=req.result_id,
                status=(
                    RunStatus.CANCELLED
                    if req.state is RequestState.CANCELLED
                    else None
                ),
            )

        def finish_cancel() -> RunResult:
            req.state = RequestState.SUCCESS if written else RequestState.CANCELLED
            req.updated_at = now_iso()
            if written:
                req.result_id = written[0]
                req.outcome = {"result_ids": written, "bookings": sandbox.bookings}
            emit("run.cancel_confirmed", write_prevented=not written, business_action_revoked=False, result_ids=written)
            emit("run.finished", request_state=req.state.value, write_count=len(written), result_ids=written)
            close_run()
            return RunResult(req, run_id, written_result_ids=written, context_audit=ctx.audit_answer(),
                             outcomes=outcomes, run_status=run.status if run else None)

        try:
            async for etype, evt in drive_reply(
                agent,
                emit,
                first_input=Msg(name="user", role="user", content=[TextBlock(text=text)]),
                ask_confirm=persisted_ask_confirm,
                confirms=confirms,
                is_cancelled=lambda: req.state is RequestState.CANCELLING,
            ):
                if etype == "reply.text":
                    # 只有真拿到文本才算"已产出文本事件"：空文本事件不构成流式输出。
                    if evt.text:
                        final_text = evt.text
                        text_emitted = True
                elif etype == "reply.final":
                    msg_text = _msg_text(evt)
                    final_text = msg_text or final_text
                    if msg_text and not text_emitted:
                        # 真实模型只给最终 Msg，不给 TextBlockEndEvent。不补这一条，
                        # AG-UI 投影里就一条文本事件都没有，前端只剩 summary 兜底
                        # ——"能跑通"和"有流式消费"是两件事，这里补的是后者。
                        emit("reply.text", text=msg_text, block_id=new_id("blk"))
                        text_emitted = True
                elif etype == "tool.result":
                    supplier_states.append(str(getattr(evt, "state", "")))
        except asyncio.CancelledError:
            return finish_cancel()
        except sqlite3.Error:
            raise
        except Exception as exc:
            # Provider/agent failures are execution facts, not a reason to leave
            # the durable run running. Never persist supplier exception text.
            result_preserved = bool(req.result_id or written)
            req.state = RequestState.SUCCESS if result_preserved else RequestState.FAILED
            req.updated_at = now_iso()
            if written:
                req.result_id = req.result_id or written[0]
                if req.outcome is None:
                    req.outcome = {"result_ids": list(written), "bookings": sandbox.bookings}
            emit(
                "run.execution_failed",
                stage="reply_generation",
                failure_code="reply_generation_failed",
                exception_type=type(exc).__name__,
                business_result_preserved=result_preserved,
            )
            emit(
                "run.finished",
                request_state=req.state.value,
                write_count=len(written),
                result_ids=list(written),
            )
            close_run()
            return RunResult(
                request=req,
                run_id=run_id,
                text=graph_text,
                written_result_ids=list(written),
                context_audit=ctx.audit_answer(),
                outcomes=outcomes,
                run_status=run.status if run else None,
            )
        finally:
            self._active.pop(run_id, None)

        if req.state is RequestState.CANCELLING:
            return finish_cancel()

        # 6) 终态：模型说"完成"不算完成，必须有持久化的业务结果
        state = self._final_state(outcomes + supplier_states, written)
        # 已有持久化结果后，重复提交被拦截不应把成功终态改判为失败
        if (
            req.result_id
            and state is RequestState.FAILED
            and not written
            and not any(
                o in (ToolOutcome.ERROR.value, ToolOutcome.UNKNOWN.value)
                for o in outcomes
            )
        ):
            state = RequestState.SUCCESS
        req.state = state
        req.updated_at = now_iso()
        if written:
            req.result_id = written[0]
            req.outcome = {"result_ids": written, "bookings": sandbox.bookings}
        emit(
            "run.finished",
            request_state=state.value,
            write_count=len(written),
            result_ids=written,
            unknown_outcomes=[o for o in outcomes if o == ToolOutcome.UNKNOWN.value],
        )
        close_run()
        return RunResult(
            request=req,
            run_id=run_id,
            text="\n".join(part for part in (graph_text, final_text) if part),
            written_result_ids=written,
            context_audit=ctx.audit_answer(),
            outcomes=outcomes,
            run_status=run.status if run else None,
        )

    # -- 辅助 --------------------------------------------------------------
    @staticmethod
    def _graph_message_payloads(messages: list[dict[str, Any]]):
        for message in messages:
            yield "route.graph.message", {**message, "delivery": "server_generated"}
            yield "reply.text", {"text": message["text"], "block_id": new_id("blk"),
                                 "source": "graph_say", "unit_id": message["unit_id"],
                                 "delivery": "server_generated"}

    def _new_request(self, channel: Channel, text: str) -> ServiceRequest:
        return ServiceRequest(
            request_id=new_id("req"),
            tenant_id=self.tenant_id,
            agent_version=self.pack.agent_version.version_id,
            channel=channel,
            state=RequestState.QUEUED,
            trigger_ref=text[:120],
        )

    def _route(self, text: str) -> str:
        routing = getattr(self.pack, "routing", None) or {}
        for skill_id, keywords in routing.items():
            if any(k in text for k in keywords):
                return skill_id
        return self.pack.skills[0].skill_id

    def _graph_skill(self, unit_id: str) -> str | None:
        # The binding is version-local and exact; never infer a Skill from a
        # naming convention or silently choose the first Skill.
        skill_id = self.unit_skill_bindings.get(unit_id)
        if not isinstance(skill_id, str) or not skill_id.strip() or skill_id not in self.pack.agent_version.skill_ids:
            return None
        return skill_id if sum(skill.skill_id == skill_id for skill in self.pack.skills) == 1 else None

    def _final_state(self, outcomes: list[str], written: list[str]) -> RequestState:
        """终态只看持久化证据：写入成功才算成功；拒绝/失败/未知一律不记为成功。"""
        if written:
            return RequestState.SUCCESS
        for bad in (
            ToolOutcome.DENIED.value,
            ToolOutcome.UNKNOWN.value,
            ToolOutcome.ERROR.value,
        ):
            if bad in outcomes:
                return RequestState.FAILED
        return RequestState.SUCCESS  # 纯咨询也算履约成功（无副作用）


def _msg_text(msg: Any) -> str:
    parts = []
    for b in getattr(msg, "content", []) or []:
        t = getattr(b, "text", None)
        if isinstance(t, str):
            parts.append(t)
    return "".join(parts)


def _build_system_prompt(skill, rendered_context: str) -> str:
    return "\n".join([
        f"你是 Loomrise S1 演示用的课程咨询 Agent。",
        "",
        "## 当前 Skill/SOP（策略，不授予权限）",
        f"- id: {skill.skill_id}@{skill.version}",
        f"- 目标: {skill.goal}",
        f"- 适用: {skill.applies_when}",
        f"- 退出: {skill.exit_when}",
        f"- 转人工: {skill.escalate_when}",
        "",
        "## 已加载上下文（每段都带来源与版本）",
        rendered_context or "(无)",
        "",
        OUTPUT_CONTRACT,
    ])


__all__ = ["ExecutionService", "RunResult"]
