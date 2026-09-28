# -*- coding: utf-8 -*-
"""ExecutionService：S1 的统一执行内核。

文字与语音共用同一个 `ServiceRequest`、同一个 `AgentVersion`、同一套权限判断
和同一个业务结果。渠道/媒体只负责把输入搬进来，不持有业务状态。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel, Field

from .contracts import (
    Behavior,
    Channel,
    RequestState,
    ScenarioPack,
    ServiceRequest,
    ToolOutcome,
    new_id,
    now_iso,
)
from .context import CompactionPolicy, ContextLedger
from .ledger import EventLedger
from .rules import DecisionPolicy
from .tools import Sandbox, ToolResult
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
        ask_confirm: Callable[[list[Any]], list[bool]] | None = None,
        failure_mode: str = "none",
        compaction_mode: str = "deny",
    ) -> None:
        self.pack = pack
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

    # -- 对外入口 ----------------------------------------------------------
    async def handle_text(
        self,
        text: str,
        *,
        request: ServiceRequest | None = None,
        script: list[dict[str, Any]] | None = None,
        ask_confirm: Callable[[list[Any]], list[bool]] | None = None,
        failure_mode: str | None = None,
    ) -> RunResult:
        return await self._handle(
            text,
            channel=Channel.TEXT,
            request=request,
            script=script,
            ask_confirm=ask_confirm,
            failure_mode=failure_mode,
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
        )

    def cancel(self, request_id: str, *, run_id: str, reason: str = "user_cancel") -> bool:
        """取消请求已发送 ≠ 业务动作已撤销：两件事分别记账。"""
        started = next((e for e in self.ledger.find("run.started") if e.run_id == run_id and e.request_id == request_id), None)
        if started is None:
            return False
        self.ledger.emit(
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
            self.ledger.emit(
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
    ) -> RunResult:
        av = self.pack.agent_version
        req = request or self._new_request(channel, text)
        self.requests[req.request_id] = req
        run_id = new_id("run")
        req.state = RequestState.RUNNING
        self._active[run_id] = asyncio.current_task()

        def emit(event_type: str, **payload: Any):
            return self.ledger.emit(
                event_type,
                request_id=req.request_id,
                run_id=run_id,
                tenant_id=self.tenant_id,
                agent_version=av.version_id,
                channel=channel.value,
                media_session_id=media_session_id,
                **payload,
            )

        emit("run.started", trigger_kind=req.trigger_kind, input=text)

        # 1) 路由（确定性，不交给模型）
        skill_id = self._route(text)
        emit("request.routed", skill_id=skill_id, reason=f"关键词命中 {skill_id}")

        # 2) 上下文：常驻基线 + 当前 Skill（第三段按需证据由工具触发）
        ctx = ContextLedger(
            emit=emit,
            run_id=run_id,
            request_id=req.request_id,
            budget_tokens=av.context_budget_tokens,
        )
        ctx.register_many(self.pack.fragments)
        ctx.stage_baseline()
        ctx.stage_task(skill_id)

        # 3) 策略与沙盒
        policy = DecisionPolicy(self.pack.rules, emit=emit, writes=self._writes)
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
            r: ToolResult = await sandbox.create_booking(
                course_id, learner_name, slot, idempotency_key,
            )
            emit(
                "tool.outcome",
                tool="create_booking",
                outcome=r.outcome.value,
                result_id=r.result_id,
                duration_ms=r.duration_ms,
            )
            outcomes.append(r.outcome.value)
            if r.result_id:
                written.append(r.result_id)
            return to_tool_response(r)

        toolkit = await build_toolkit([
            wrap_tool(
                _search,
                name="search_knowledge",
                description="只读检索已授权课程资料，返回带来源与版本的片段",
                input_model=SearchKnowledgeInput,
                read_only=True,
            ),
            wrap_tool(
                _book,
                name="create_booking",
                description="模拟写入：创建一条课程预约，返回 result_id",
                input_model=CreateBookingInput,
                read_only=False,
                ask_permission=True,
            ),
        ])

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

        # 5) 驱动一次 reply（含人工确认恢复）
        final_text = ""

        def finish_cancel() -> RunResult:
            req.state = RequestState.SUCCESS if written else RequestState.CANCELLED
            req.updated_at = now_iso()
            if written:
                req.result_id = written[0]
                req.outcome = {"result_ids": written, "bookings": sandbox.bookings}
            emit("run.cancel_confirmed", write_prevented=not written, business_action_revoked=False, result_ids=written)
            emit("run.finished", request_state=req.state.value, write_count=len(written), result_ids=written)
            return RunResult(req, run_id, written_result_ids=written, context_audit=ctx.audit_answer(), outcomes=outcomes)

        try:
            async for etype, evt in drive_reply(
                agent,
                emit,
                first_input=Msg(name="user", role="user", content=[TextBlock(text=text)]),
                ask_confirm=ask_confirm or self.ask_confirm,
                confirms=confirms,
                is_cancelled=lambda: req.state is RequestState.CANCELLING,
            ):
                if etype == "reply.text":
                    final_text = evt.text or final_text
                elif etype == "reply.final":
                    final_text = _msg_text(evt) or final_text
                elif etype == "tool.result":
                    supplier_states.append(str(getattr(evt, "state", "")))
        except asyncio.CancelledError:
            return finish_cancel()
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
        return RunResult(
            request=req,
            run_id=run_id,
            text=final_text,
            written_result_ids=written,
            context_audit=ctx.audit_answer(),
            outcomes=outcomes,
        )

    # -- 辅助 --------------------------------------------------------------
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


__all__ = ["ExecutionService", "RunResult", "Behavior"]
