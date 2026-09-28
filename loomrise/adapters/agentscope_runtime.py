# -*- coding: utf-8 -*-
"""AgentScope 运行适配（S1）。

复用而非重写：Agent / Toolkit / FunctionTool / MiddlewareBase / 事件流全部用上游能力，
Loomrise 只做三件事——
1. `ContextGuardMiddleware`：拦截 SDK 侧未登记的上下文改写（压缩/截断）；
2. `PolicyMiddleware`：把权限裁决收回到 Loomrise 硬规则（模型外、确定性）；
3. 事件投影：把供应商事件归一化为带 request/run/channel 标识的 `RunEvent`。

明确不采用上游 `app/` 服务层（含飞书/钉钉/Discord channel 与 ag-ui-protocol 中间件）：
S1 不引 IM、不建第二控制面。
"""

from __future__ import annotations

import json
import os
import inspect
from typing import Any, AsyncGenerator, Callable

from agentscope.agent import Agent, ContextConfig, InjectionConfig, ReActConfig
from agentscope.event import (
    ConfirmResult,
    ExceedMaxItersEvent,
    ModelCallEndEvent,
    ReplyEndEvent,
    ReplyStartEvent,
    RequireUserConfirmEvent,
    TextBlockEndEvent,
    ToolCallStartEvent,
    ToolResultEndEvent,
    UserConfirmResultEvent,
    UserInterruptEvent,
)
from agentscope.middleware import MiddlewareBase
from agentscope.model import ChatModelBase, ChatResponse, ChatUsage
from agentscope.permission import PermissionBehavior, PermissionDecision
from agentscope.state import AgentState
from agentscope.message import Msg, TextBlock, ToolCallBlock, ToolResultState
from agentscope.tool import FunctionTool, Toolkit, ToolResponse

from ..contracts import (
    Behavior,
    Channel,
    ToolOutcome,
    estimate_tokens,
    new_id,
)
from ..context import CompactionPolicy

# Loomrise 行为 → 上游权限行为
_BEHAVIOR_MAP = {
    Behavior.ALLOW: PermissionBehavior.ALLOW,
    Behavior.DENY: PermissionBehavior.DENY,
    Behavior.ASK: PermissionBehavior.ASK,
}

# Loomrise 结果语义 → 上游工具结果态。UNKNOWN 上游没有，落 ERROR 并保留 Loomrise 语义。
_STATE_MAP = {
    ToolOutcome.SUCCESS: ToolResultState.SUCCESS,
    ToolOutcome.ERROR: ToolResultState.ERROR,
    ToolOutcome.DENIED: ToolResultState.DENIED,
    ToolOutcome.INTERRUPTED: ToolResultState.INTERRUPTED,
    ToolOutcome.UNKNOWN: ToolResultState.ERROR,
}


# --------------------------------------------------------------------------
# 确定性脚本模型（回放用）
# --------------------------------------------------------------------------


class _ScriptedFormatter:
    """脚本模型不需要真实协议格式化；只需满足 Agent 对输入媒体的查询。

    ponytail: 空媒体类型集合 = 只接受纯文本输入，S1 本来就没有多模态输入。
    """

    supported_input_media_types: set[str] = set()

    async def format(self, messages: list[Msg]) -> list[Msg]:
        return messages


class ScriptedChatModel(ChatModelBase):
    """按脚本返回响应的假模型：回放可复现，不依赖外部 API 与密钥。

    ponytail: 不实现真实协议，只实现 `_call_api`。真实模型由
    `build_model()` 在检测到环境变量时切换到 OpenAI 兼容实现。
    """

    def __init__(
        self,
        model_name: str = "scripted-s1",
        script: list[dict[str, Any]] | None = None,
        context_size: int = 128_000,
    ) -> None:
        super().__init__(
            credential=None,
            model=model_name,
            parameters=ChatModelBase.Parameters(),
            stream=False,
            max_retries=0,
            context_size=context_size,
        )
        self.script = list(script or [])
        self.cursor = 0
        self.calls: list[dict[str, Any]] = []
        self.formatter = _ScriptedFormatter()

    async def _call_api(
        self,
        model_name: str,
        messages: list[Msg],
        tools: list[dict] | None = None,
        tool_choice: Any = None,
        **kwargs: Any,
    ) -> ChatResponse:
        idx = self.cursor
        self.cursor += 1
        step = (
            self.script[idx]
            if idx < len(self.script)
            else {"text": "（脚本结束）我暂时无法继续，请补充信息。"}
        )
        self.calls.append({"index": idx, "step": step})
        content: list[Any] = []
        if "text" in step:
            content = [TextBlock(text=step["text"])]
        elif "tool" in step:
            content = [
                ToolCallBlock(
                    id=new_id("call"),
                    name=step["tool"],
                    input=json.dumps(step.get("args", {}), ensure_ascii=False),
                ),
            ]
        return ChatResponse(
            content=content,
            is_last=True,
            usage=ChatUsage(
                input_tokens=estimate_tokens(str(messages)),
                output_tokens=64,
                time=0.0,
            ),
        )


def build_model(script: list[dict[str, Any]] | None = None) -> ChatModelBase:
    """Explicit script replay, or local Coding Plan Responses API credential."""
    if script is not None:
        return ScriptedChatModel(script=script)
    from ..local_config import load_config

    config = load_config()
    if config:
        from agentscope.credential import OpenAICredential
        from agentscope.model import OpenAIResponseModel

        return OpenAIResponseModel(
            credential=OpenAICredential(api_key=config["key"], base_url=config["base_url"]),
            model=config["model"],
            stream=True,
            max_retries=0,
        )
    if os.environ.get("LOOMRISE_LIVE_MODEL"):
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError("LOOMRISE_LIVE_MODEL requires OPENAI_API_KEY")
        from agentscope.model import OpenAIChatModel

        return OpenAIChatModel(
            model=os.environ["LOOMRISE_LIVE_MODEL"],
            api_key=os.environ["OPENAI_API_KEY"],
            stream=False,
        )
    return ScriptedChatModel(script=script)


# --------------------------------------------------------------------------
# 中间件
# --------------------------------------------------------------------------


class ContextGuardMiddleware(MiddlewareBase):
    """拦截 SDK 侧压缩/截断：不调用 next_handler，原生改写即不生效。

    冲突本身不是 S1 特有，是长期结构性冲突；S1 的 deny 只是止血。
    """

    def __init__(self, policy: CompactionPolicy, emit: Callable[..., Any]) -> None:
        self.policy = policy
        self.emit = emit

    async def on_compress_context(
        self,
        agent: "Agent",
        input_kwargs: dict,
        next_handler: Callable[..., Any],
    ) -> None:
        cfg = input_kwargs.get("context_config") or agent.context_config
        used = _context_tokens(agent)
        threshold = int(
            getattr(agent.model, "context_size", 32768) * float(cfg.trigger_ratio),
        )
        self.policy.intercept(
            emit=self.emit,
            trigger="agent.compress_context",
            context_config=cfg,
            would_trigger=used >= threshold,
            extra={
                "estimated_used_tokens": used,
                "estimated_threshold_tokens": threshold,
            },
        )
        # intercept 恒返回 False → 不调用 next_handler → 原生压缩/截断不生效


class ConfirmLedger:
    """人工确认只在模型外收集一次；之后同一 tool_call 不再重复询问。

    上游在"确认后执行"时会再次走权限检查，若不记住结果就会陷入反复确认。
    """

    def __init__(self) -> None:
        self.confirmed: set[str] = set()
        self.denied: set[str] = set()


class PolicyMiddleware(MiddlewareBase):
    """把权限裁决收回到 Loomrise 硬规则。不调用 next_handler，绕过上游引擎。"""

    def __init__(
        self,
        policy,
        emit: Callable[..., Any],
        *,
        skill_id: str = "",
        confirms: ConfirmLedger | None = None,
    ) -> None:
        self.policy = policy
        self.emit = emit
        self.skill_id = skill_id
        self.confirms = confirms or ConfirmLedger()

    async def on_check_permission(
        self,
        agent: "Agent",
        input_kwargs: dict,
        next_handler: Callable[..., Any],
    ) -> PermissionDecision:
        tool_call = input_kwargs.get("tool_call")
        tool_input = input_kwargs.get("tool_input") or {}
        name = getattr(tool_call, "name", "")
        call_id = getattr(tool_call, "id", "")
        args = dict(tool_input)
        try:
            args = json.loads(getattr(tool_call, "input", "{}") or "{}")
        except Exception:
            pass
        if call_id in self.confirms.confirmed:
            self.emit(
                "permission.decision",
                tool=name,
                behavior="allow",
                rule_ids=["confirm.already_collected"],
                reason="该工具调用已取得人工确认，不再重复询问",
            )
            return PermissionDecision(
                behavior=PermissionBehavior.ALLOW,
                message="已确认",
            )
        if call_id in self.confirms.denied:
            return PermissionDecision(
                behavior=PermissionBehavior.DENY,
                message="该工具调用已被人工拒绝",
            )
        decision = self.policy.check(name, args, skill_id=self.skill_id)
        self.emit(
            "permission.decision",
            tool=name,
            behavior=decision.behavior.value,
            rule_ids=decision.rule_ids,
            reason=decision.reason,
        )
        return PermissionDecision(
            behavior=_BEHAVIOR_MAP[decision.behavior],
            message=f"{name}: {decision.behavior.value}",
            decision_reason=decision.reason,
        )


# --------------------------------------------------------------------------
# Agent 组装
# --------------------------------------------------------------------------


def build_agent(
    *,
    name: str,
    system_prompt: str,
    model: ChatModelBase,
    toolkit: Toolkit,
    middlewares: list[MiddlewareBase],
    max_iters: int = 10,
    state: "AgentState | None" = None,
) -> Agent:
    return Agent(
        name=name,
        system_prompt=system_prompt,
        model=model,
        toolkit=toolkit,
        middlewares=middlewares,
        # 传入同一业务请求的既有 state：跨渠道/跨轮次续接对话历史
        state=state or AgentState(),
        # 关闭运行时注入（时间/任务/上下文/工具错误四维，见 _agent.py:1407）
        injection_config=InjectionConfig(inject_runtime_state=False),
        # 压缩由 ContextGuardMiddleware 拦截；图片卸载在 S1 无输入，显式归零
        context_config=ContextConfig(max_image_num=0, compression_tool_enabled=False),
        react_config=ReActConfig(max_iters=max_iters),
    )


async def build_toolkit(tools: list[FunctionTool]) -> Toolkit:
    tk = Toolkit()
    await tk.add_tool(tools)
    return tk


def wrap_tool(
    fn: Callable[..., Any],
    *,
    name: str,
    description: str,
    input_model: Any,
    read_only: bool,
    ask_permission: bool = False,
) -> FunctionTool:
    return FunctionTool(
        fn,
        name=name,
        description=description,
        input_schema=input_model,
        is_read_only=read_only,
        permission=(
            PermissionDecision(
                behavior=PermissionBehavior.ASK,
                message="业务写入需人工确认（最终以 Loomrise 硬规则裁决为准）",
            )
            if ask_permission
            else None
        ),
    )


# --------------------------------------------------------------------------
# 事件投影
# --------------------------------------------------------------------------


def project_event(evt: Any, emit: Callable[..., Any]) -> str:
    """供应商事件 → Loomrise RunEvent。返回事件类型名。"""
    if isinstance(evt, ReplyStartEvent):
        emit("run.reply_started", supplier_reply_id=evt.reply_id)
        return "run.reply_started"
    if isinstance(evt, ReplyEndEvent):
        emit(
            "run.reply_finished",
            supplier_reply_id=evt.reply_id,
            finished_reason=str(evt.finished_reason),
            error=str(evt.error) if evt.error else None,
        )
        return "run.reply_finished"
    if isinstance(evt, TextBlockEndEvent):
        emit("reply.text", block_id=evt.block_id, text=evt.text)
        return "reply.text"
    if isinstance(evt, ToolCallStartEvent):
        emit(
            "tool.call_start",
            tool_call_id=evt.tool_call_id,
            tool=evt.tool_call_name,
        )
        return "tool.call_start"
    if isinstance(evt, ToolResultEndEvent):
        emit(
            "tool.result",
            tool_call_id=evt.tool_call_id,
            supplier_state=str(evt.state),
        )
        return "tool.result"
    if isinstance(evt, ModelCallEndEvent):
        emit(
            "model.call_end",
            model=getattr(evt, "model_name", None),
            input_tokens=evt.input_tokens,
            output_tokens=evt.output_tokens,
            finished_reason=str(evt.finished_reason),
        )
        return "model.call_end"
    if isinstance(evt, RequireUserConfirmEvent):
        def arguments(call: Any) -> dict[str, Any]:
            try:
                value = json.loads(getattr(call, "input", "{}") or "{}")
                return value if isinstance(value, dict) else {}
            except (ValueError, TypeError):
                return {}

        emit(
            "permission.confirm_required",
            supplier_reply_id=evt.reply_id,
            tools=[getattr(t, "name", None) for t in evt.tool_calls],
            tool_calls=[
                {"name": getattr(t, "name", ""), "arguments": arguments(t)}
                for t in evt.tool_calls
            ],
        )
        return "permission.confirm_required"
    if isinstance(evt, UserConfirmResultEvent):
        emit(
            "permission.confirm_result",
            supplier_reply_id=evt.reply_id,
            confirmed=[
                getattr(c, "confirmed", None) for c in evt.confirm_results
            ],
        )
        return "permission.confirm_result"
    if isinstance(evt, UserInterruptEvent):
        emit("run.interrupt_requested", supplier_reply_id=evt.reply_id)
        return "run.interrupt_requested"
    if isinstance(evt, ExceedMaxItersEvent):
        emit("run.exceed_max_iters", name=getattr(evt, "name", None))
        return "run.exceed_max_iters"
    return ""


async def drive_reply(
    agent: Agent,
    emit: Callable[..., Any],
    *,
    first_input: Any,
    ask_confirm: Callable[[list[Any]], list[bool]],
    confirms: ConfirmLedger | None = None,
    is_cancelled: Callable[[], bool] = lambda: False,
    max_confirm_rounds: int = 3,
) -> AsyncGenerator[tuple[str, Any], None]:
    """驱动一次 reply，处理人工确认与恢复。

    上游语义：取消请求（UserInterruptEvent）与业务动作已撤销是两件事，
    Loomrise 分别记账，不依赖上游表达。
    """
    pending = first_input
    confirms = confirms or ConfirmLedger()
    rounds = 0
    while True:
        need_confirm: RequireUserConfirmEvent | None = None
        async for evt in agent.reply_stream(pending, yield_final_msg=True):
            if is_cancelled():
                return
            if isinstance(evt, Msg):
                yield "reply.final", evt
                continue
            etype = project_event(evt, emit)
            if isinstance(evt, RequireUserConfirmEvent):
                need_confirm = evt
                break
            yield etype, evt
        if need_confirm is None:
            return
        rounds += 1
        if rounds > max_confirm_rounds:
            emit("run.confirm_rounds_exhausted", rounds=rounds)
            return
        answers = ask_confirm(list(need_confirm.tool_calls))
        if inspect.isawaitable(answers):
            answers = await answers
        if is_cancelled():
            emit("permission.confirm_aborted", reason="run_cancelled")
            return
        emit(
            "permission.confirm_answered",
            answers=answers,
            tools=[getattr(t, "name", None) for t in need_confirm.tool_calls],
        )
        for a, tc in zip(answers, need_confirm.tool_calls):
            cid = getattr(tc, "id", "")
            if cid:
                (confirms.confirmed if a else confirms.denied).add(cid)
            # SDK 拒绝后不再回权限钩子，账本在这里留人工裁决证据
            emit(
                "permission.decision",
                tool=getattr(tc, "name", ""),
                behavior="allow" if a else "deny",
                rule_ids=["confirm.human_allow" if a else "confirm.human_deny"],
                reason="人工确认允许该工具调用" if a else "人工拒绝该工具调用",
                tool_call_id=cid,
            )
        pending = UserConfirmResultEvent(
            reply_id=need_confirm.reply_id,
            confirm_results=[
                ConfirmResult(confirmed=bool(a), tool_call=tc)
                for a, tc in zip(answers, need_confirm.tool_calls)
            ],
        )


# --------------------------------------------------------------------------
# 工具包装：Loomrise ToolResult → 上游 ToolResponse
# --------------------------------------------------------------------------


def to_tool_response(result: Any) -> ToolResponse:
    return ToolResponse(
        content=[TextBlock(text=result.message)],
        state=_STATE_MAP[result.outcome],
        metadata={
            "loomrise_outcome": result.outcome.value,
            "result_id": result.result_id,
            "duration_ms": result.duration_ms,
            **result.payload,
        },
    )


def _context_tokens(agent: Any) -> int:
    total = 0
    for m in getattr(getattr(agent, "state", None), "context", []) or []:
        for b in getattr(m, "content", []) or []:
            for attr in ("text", "thinking", "input", "output"):
                v = getattr(b, attr, None)
                if isinstance(v, str):
                    total += estimate_tokens(v)
    return total


def _cfg_dump(cfg: Any) -> dict[str, Any]:
    try:
        return cfg.model_dump()
    except Exception:
        return {"repr": repr(cfg)}


__all__ = [
    "ScriptedChatModel",
    "build_model",
    "build_agent",
    "build_toolkit",
    "wrap_tool",
    "ContextGuardMiddleware",
    "PolicyMiddleware",
    "project_event",
    "drive_reply",
    "to_tool_response",
    "Channel",
]
