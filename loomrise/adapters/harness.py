"""Bounded AgentScope harness for proposal-only diagnosis jobs."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import inspect
import json
import math
import time
from typing import Any, AsyncGenerator, Callable, Mapping
from urllib.parse import urlsplit

from agentscope.agent import (
    Agent,
    ContextConfig,
    InjectionConfig,
    ModelConfig,
    ReActConfig,
)
from agentscope.credential import OpenAICredential
from agentscope.event import ModelCallEndEvent, ReplyEndEvent, ReplyFinishedReason
from agentscope.message import Msg, TextBlock
from agentscope.middleware import MiddlewareBase
from agentscope.model import ChatModelBase, OpenAIChatModel
from agentscope.permission import PermissionBehavior, PermissionDecision
from agentscope.state import AgentState
from agentscope.tool import FunctionTool, Toolkit
from jsonschema import ValidationError, validate

from ..contracts import estimate_tokens
from ..diagnostics import (
    MAX_REPORT_BYTES,
    MAX_SNAPSHOT_BYTES,
    REPORT_JSON_SCHEMA,
    DiagnosticsService,
    PROVIDER_CONTRACT_HASH,
    PROVIDER_VERSIONS,
    PROVIDER_KIND_OFFLINE_SCRIPTED,
    PROVIDER_KIND_REAL_HARNESS,
)


_TOOL_NAME = "diagnosis_evidence"


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _reject_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _parse_json(text: str) -> Any:
    return json.loads(
        text,
        parse_constant=_reject_constant,
        object_pairs_hook=_unique_object,
    )


def _positive_int(value: Any, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


class _DiagnosisMiddleware(MiddlewareBase):
    """Recheck the frozen authorization at every model and tool boundary."""

    def __init__(
        self,
        *,
        snapshot_json: str,
        read_evidence: Callable[[], Any],
        token_budget: int,
        deadline: float,
    ) -> None:
        self.snapshot_json = snapshot_json
        self.read_evidence = read_evidence
        self.token_budget = token_budget
        self.deadline = deadline
        self.model_calls = 0
        self.tool_checks = 0
        self.tool_executions = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self._tool_evidence: dict[str, Any] | None = None

    def _check_deadline(self) -> None:
        if time.monotonic() >= self.deadline:
            raise TimeoutError("diagnosis provider deadline exceeded")

    async def _reauthorize(self) -> dict[str, Any]:
        self._check_deadline()
        value = self.read_evidence()
        if inspect.isawaitable(value):
            value = await value
        try:
            if not isinstance(value, dict) or _canonical(value) != self.snapshot_json:
                raise PermissionError("authorized diagnosis evidence changed")
        except (TypeError, ValueError, RecursionError):
            raise PermissionError("authorized diagnosis evidence changed") from None
        return value

    async def on_model_call(self, agent, input_kwargs, next_handler):
        if self.model_calls >= 2:
            raise ValueError("diagnosis model-call limit exceeded")
        tools = input_kwargs.get("tools") or []
        if (
            len(tools) != 1
            or tools[0].get("function", {}).get("name") != _TOOL_NAME
        ):
            raise ValueError("diagnosis harness tool set changed")
        await self._reauthorize()
        estimated_input = estimate_tokens(str(input_kwargs.get("messages", [])))
        if estimated_input + self.input_tokens + self.output_tokens > self.token_budget:
            raise ValueError("diagnosis token budget exceeded")
        self.model_calls += 1
        return await next_handler(**input_kwargs)

    async def on_check_permission(self, agent, input_kwargs, next_handler):
        tool_call = input_kwargs.get("tool_call")
        if getattr(tool_call, "name", None) != _TOOL_NAME:
            raise PermissionError("diagnosis harness denied an unregistered tool")
        if self.tool_checks >= 1:
            raise ValueError("diagnosis tool-call limit exceeded")
        await self._reauthorize()
        self.tool_checks += 1
        return PermissionDecision(
            behavior=PermissionBehavior.ALLOW,
            message="authorized read-only diagnosis evidence",
        )

    async def on_acting(
        self,
        agent,
        input_kwargs,
        next_handler,
    ) -> AsyncGenerator[Any, None]:
        tool_call = input_kwargs.get("tool_call")
        if getattr(tool_call, "name", None) != _TOOL_NAME:
            raise PermissionError("diagnosis harness denied an unregistered tool")
        if self.tool_executions >= 1:
            raise ValueError("diagnosis tool-call limit exceeded")
        self._tool_evidence = await self._reauthorize()
        self.tool_executions += 1
        try:
            async for result in next_handler(**input_kwargs):
                yield result
        finally:
            self._tool_evidence = None


class AgentScopeDiagnosisProvider:
    """Run one bounded AgentScope diagnosis with explicit provider settings."""

    def __init__(
        self,
        config: Mapping[str, Any],
        *,
        model: ChatModelBase | None = None,
    ) -> None:
        if not isinstance(config, Mapping):
            raise ValueError("diagnosis provider configuration is required")
        # provider_kind 由服务端根据是否注入模型判定，调用方一律不得自报，
        # 尤其不能把注入脚本替身的 Provider 自报为真实 harness 类别。
        if "provider_kind" in config:
            raise ValueError("provider_kind is server-owned and cannot be self-reported")
        provider_id = config.get("provider_id")
        model_name = config.get("model")
        base_url = config.get("base_url")
        api_key = config.get("key")
        if not all(isinstance(value, str) and value.strip() for value in (
            provider_id, model_name, base_url, api_key,
        )):
            raise ValueError("provider_id, model, base_url, and key must be explicit")
        try:
            endpoint = urlsplit(base_url.strip())
        except ValueError:
            raise ValueError("base_url must be an HTTP(S) endpoint without credentials") from None
        if (
            endpoint.scheme not in {"http", "https"}
            or not endpoint.hostname
            or endpoint.username is not None
            or endpoint.password is not None
            or endpoint.query
            or endpoint.fragment
        ):
            raise ValueError("base_url must be an HTTP(S) endpoint without credentials or query parameters")
        deadline_seconds = config.get("deadline_seconds", 120)
        if (
            isinstance(deadline_seconds, bool)
            or not isinstance(deadline_seconds, (int, float))
            or deadline_seconds <= 0
            or deadline_seconds > 300
            or not math.isfinite(deadline_seconds)
        ):
            raise ValueError("deadline_seconds must be between 0 and 300")
        max_output_tokens = _positive_int(config.get("max_output_tokens", 1024), "max_output_tokens")
        if max_output_tokens > 32768:
            raise ValueError("max_output_tokens exceeds the diagnosis limit")

        self.config = {
            "provider_id": provider_id.strip(),
            "model": model_name.strip(),
            "base_url": base_url.strip(),
            "key": api_key,
            "deadline_seconds": float(deadline_seconds),
            "max_output_tokens": max_output_tokens,
        }
        # 注入模型（脚本/替身）只能登记为离线脚本证据；未注入模型、由服务端用
        # 真实凭据构造的才登记为 real harness，但本机无真实联调条件时仍不可
        # 作为真实 Provider 证据运行（服务端只接受非真实类别）。
        provider_kind = (PROVIDER_KIND_OFFLINE_SCRIPTED if model is not None
                         else PROVIDER_KIND_REAL_HARNESS)
        self.model = model if model is not None else OpenAIChatModel(
            credential=OpenAICredential(
                api_key=self.config["key"],
                base_url=self.config["base_url"],
            ),
            model=self.config["model"],
            parameters=OpenAIChatModel.Parameters(
                max_tokens=self.config["max_output_tokens"],
                temperature=0,
                parallel_tool_calls=False,
            ),
            stream=False,
            max_retries=0,
        )
        if getattr(self.model, "model", None) != self.config["model"]:
            raise ValueError("injected model must match the explicit model configuration")
        if hasattr(self.model, "max_retries"):
            self.model.max_retries = 0
        self.descriptor = {
            "provider_id": self.config["provider_id"],
            "model": self.config["model"],
            "base_url": self.config["base_url"],
            "provider_kind": provider_kind,
            "version": PROVIDER_VERSIONS[provider_kind],
            "contract_hash": PROVIDER_CONTRACT_HASH,
        }

    async def run(
        self,
        *,
        snapshot: dict[str, Any],
        read_evidence: Callable[[], Any],
        token_budget: int,
        max_output_bytes: int,
    ) -> dict[str, Any]:
        token_budget = _positive_int(token_budget, "token_budget")
        if token_budget > 100_000:
            raise ValueError("token_budget exceeds the diagnosis limit")
        max_output_bytes = _positive_int(max_output_bytes, "max_output_bytes")
        if not isinstance(snapshot, dict) or not callable(read_evidence):
            raise ValueError("a diagnosis snapshot and authority reader are required")
        snapshot = deepcopy(snapshot)
        snapshot_json = _canonical(snapshot)
        if len(snapshot_json.encode("utf-8")) > MAX_SNAPSHOT_BYTES:
            raise ValueError("diagnosis snapshot exceeds the size limit")
        output_limit = min(max_output_bytes, MAX_REPORT_BYTES)
        started = time.monotonic()
        deadline = started + self.config["deadline_seconds"]
        middleware = _DiagnosisMiddleware(
            snapshot_json=snapshot_json,
            read_evidence=read_evidence,
            token_budget=token_budget,
            deadline=deadline,
        )

        async def diagnosis_evidence() -> str:
            evidence = middleware._tool_evidence
            if evidence is None:
                raise PermissionError("diagnosis evidence is not authorized")
            return _canonical(evidence)

        toolkit = Toolkit()
        await toolkit.add_tool([
            FunctionTool(
                diagnosis_evidence,
                name=_TOOL_NAME,
                description="Read the evidence explicitly authorized for this diagnosis.",
                input_schema={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
                is_read_only=True,
                is_concurrency_safe=False,
            ),
        ])
        system_prompt = (
            "You are a governance-only diagnosis assistant. Read evidence only by calling "
            f"the read-only {_TOOL_NAME} tool exactly once. Do not infer facts beyond that snapshot. "
            "Return one JSON object only, with no markdown. Every category must either have one "
            "evidence-linked finding or appear in insufficient_categories. Preserve every snapshot "
            "limitation. The report is a proposal, never an approved change. Required JSON Schema: "
            + _canonical(REPORT_JSON_SCHEMA)
        )
        agent = Agent(
            name="diagnosis-agent",
            system_prompt=system_prompt,
            model=self.model,
            toolkit=toolkit,
            middlewares=[middleware],
            state=AgentState(),
            offloader=None,
            model_config=ModelConfig(max_retries=0, fallback_model=None),
            context_config=ContextConfig(
                max_image_num=0,
                compression_tool_enabled=False,
            ),
            react_config=ReActConfig(max_iters=2),
            injection_config=InjectionConfig(inject_runtime_state=False),
        )
        input_msg = Msg(
            name="user",
            role="user",
            content=[TextBlock(text=(
                "Read the authorized evidence, then produce the required JSON diagnosis report. "
                "If a category lacks support, list it in insufficient_categories."
            ))],
        )

        completed = False
        final_text: str | None = None
        usage_events = 0
        try:
            async with asyncio.timeout(self.config["deadline_seconds"]):
                async for event in agent.reply_stream(input_msg, yield_final_msg=True):
                    if isinstance(event, ModelCallEndEvent):
                        usage_events += 1
                        if (
                            type(event.input_tokens) is not int
                            or event.input_tokens < 0
                            or type(event.output_tokens) is not int
                            or event.output_tokens < 0
                        ):
                            raise ValueError("diagnosis provider returned invalid usage")
                        middleware.input_tokens += event.input_tokens
                        middleware.output_tokens += event.output_tokens
                        if middleware.input_tokens + middleware.output_tokens > token_budget:
                            raise ValueError("diagnosis token budget exceeded")
                    elif isinstance(event, ReplyEndEvent):
                        completed = (
                            event.finished_reason == ReplyFinishedReason.COMPLETED
                            and event.error is None
                        )
                    elif isinstance(event, Msg) and event.role == "assistant":
                        blocks = [
                            block.text for block in event.content
                            if isinstance(block, TextBlock) and isinstance(block.text, str)
                        ]
                        if blocks:
                            final_text = "".join(blocks)
        except asyncio.CancelledError:
            raise

        task = asyncio.current_task()
        if task is not None and task.cancelling():
            raise asyncio.CancelledError
        if not completed:
            raise ValueError("AgentScope did not confirm a completed reply")
        if (
            middleware.model_calls < 1
            or usage_events != middleware.model_calls
            or middleware.tool_executions != 1
        ):
            raise ValueError("diagnosis reply did not use its authorized evidence")
        if final_text is None:
            raise ValueError("diagnosis reply did not contain a final report")
        try:
            encoded = final_text.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("diagnosis report is not valid UTF-8") from None
        if len(encoded) > output_limit:
            raise ValueError("diagnosis report exceeds the output byte limit")
        try:
            report = _parse_json(final_text)
            validate(instance=report, schema=REPORT_JSON_SCHEMA)
            report = DiagnosticsService.validate_report(report, snapshot)
        except (ValidationError, TypeError, ValueError, RecursionError):
            raise ValueError("diagnosis report failed schema or evidence validation") from None

        return {
            "report": report,
            "usage": {
                "input_tokens": middleware.input_tokens,
                "output_tokens": middleware.output_tokens,
            },
            "provider_state": "stopped",
        }


__all__ = ["AgentScopeDiagnosisProvider"]
