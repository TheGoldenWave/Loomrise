# -*- coding: utf-8 -*-
"""事件投影层：RunEvent 是事实，AG-UI / OTel 都只是投影。

- AG-UI：单向投影到前端，协议版本以 `spec/1.0/schema.json` 为准（不是包版本号）。
  只投影离散三段（START/CONTENT/END），避免同一事实两种编码。
  确认与取消在 AG-UI 1.0 的 31 类事件里没有对应类型 → 走 `CUSTOM`（私有扩展）。
- OTel：跨服务追踪。GenAI 语义约定处于实验/迁移期，Loomrise 自持属性映射并自 pin 版本。
"""

from __future__ import annotations

from typing import Any, Iterator

from ..contracts import (
    AGUI_SPEC_VERSION,
    LANGFUSE_INGESTION_VERSION,
    SEMCONV_PIN,
    RunEvent,
)

# GenAI 语义约定属性（自持映射，不跟随上游）
GEN_AI_ATTRS = {
    "operation.name": "gen_ai.operation.name",
    "provider.name": "gen_ai.provider.name",
    "request.model": "gen_ai.request.model",
    "usage.input_tokens": "gen_ai.usage.input_tokens",
    "usage.output_tokens": "gen_ai.usage.output_tokens",
    "conversation.id": "gen_ai.conversation.id",
}
LOOMRISE_ATTRS = (
    "loomrise.request_id",
    "loomrise.run_id",
    "loomrise.agent_version",
    "loomrise.channel",
    "loomrise.media_session_id",
)


class AguiProjector:
    """RunEvent 流 → AG-UI 事件流。"""

    def __init__(self) -> None:
        self._seq = 0
        self._text_open: dict[str, bool] = {}

    def _nid(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}_{self._seq}"

    def project(self, e: RunEvent) -> Iterator[dict[str, Any]]:
        t, p = e.event_type, e.payload
        rid = e.run_id

        if t == "run.started":
            yield {"type": "RUN_STARTED", "threadId": e.request_id, "runId": rid}
        elif t == "run.finished":
            state = p.get("request_state")
            if state in ("failed", "cancelled"):
                yield {
                    "type": "RUN_ERROR",
                    "message": f"request_state={state}",
                    "rawEvent": p,
                }
            else:
                yield {"type": "RUN_FINISHED", "threadId": e.request_id, "runId": rid}
        elif t == "reply.text":
            mid = p.get("block_id") or self._nid("msg")
            yield {"type": "TEXT_MESSAGE_START", "messageId": mid, "role": "assistant"}
            yield {"type": "TEXT_MESSAGE_CONTENT", "messageId": mid, "delta": p.get("text", "")}
            yield {"type": "TEXT_MESSAGE_END", "messageId": mid}
        elif t == "tool.call_start":
            tid = p.get("tool_call_id") or self._nid("tool")
            yield {
                "type": "TOOL_CALL_START",
                "toolCallId": tid,
                "toolCallName": p.get("tool"),
                "parentMessageId": None,
            }
        elif t == "tool.outcome":
            tid = p.get("tool_call_id") or self._nid("tool")
            yield {
                "type": "TOOL_CALL_RESULT",
                "toolCallId": tid,
                "messageId": self._nid("res"),
                "result": p.get("outcome"),
                "result_id": p.get("result_id"),
            }
        elif t == "model.call_end":
            yield {"type": "STEP_STARTED", "stepName": "model_call"}
            yield {"type": "STEP_FINISHED", "stepName": "model_call"}
        elif t in ("permission.confirm_required", "permission.confirm_answered"):
            # AG-UI 1.0 无人工确认/中断事件类型 → Loomrise 私有扩展
            yield {
                "type": "CUSTOM",
                "name": (
                    "loomrise.require_user_confirm"
                    if t.endswith("confirm_required")
                    else "loomrise.user_confirm_result"
                ),
                "value": p,
            }
        elif t == "run.cancel_requested" or t == "run.interrupt_requested":
            yield {"type": "CUSTOM", "name": "loomrise.cancel_requested", "value": p}
        # context.fragment / permission.decision / voice.* 默认不投影给终端业务界面


def project_all(events: list[RunEvent]) -> list[dict[str, Any]]:
    proj = AguiProjector()
    out: list[dict[str, Any]] = []
    for e in events:
        out.extend(proj.project(e))
    return out


# --------------------------------------------------------------------------
# OpenTelemetry 投影（可选）
# --------------------------------------------------------------------------


def otel_attributes(e: RunEvent) -> dict[str, Any]:
    p = e.payload
    attrs: dict[str, Any] = {
        "loomrise.request_id": e.request_id,
        "loomrise.run_id": e.run_id,
        "loomrise.agent_version": e.agent_version,
        "loomrise.channel": e.channel,
        "loomrise.event_type": e.event_type,
        "loomrise.semconv_pin": SEMCONV_PIN,
    }
    if e.media_session_id:
        attrs["loomrise.media_session_id"] = e.media_session_id
    if "model" in p:
        attrs[GEN_AI_ATTRS["request.model"]] = p["model"]
    if "input_tokens" in p:
        attrs[GEN_AI_ATTRS["usage.input_tokens"]] = p["input_tokens"]
    if "output_tokens" in p:
        attrs[GEN_AI_ATTRS["usage.output_tokens"]] = p["output_tokens"]
    return attrs


def export_otlp(events: list[RunEvent], endpoint: str | None = None) -> int:
    """导出 trace。默认关闭；失败只降级观测，不影响业务结果与审计。"""
    if not endpoint:
        return 0
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
        OTLPSpanExporter,
    )
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor

    provider = TracerProvider()
    exporter = OTLPSpanExporter(
        endpoint=endpoint,
        headers={"x-langfuse-ingestion-version": LANGFUSE_INGESTION_VERSION}
        if "langfuse" in endpoint
        else {},
    )
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("loomrise", SEMCONV_PIN)
    with tracer.start_as_current_span("loomrise.run") as span:
        for e in events:
            span.add_event(e.event_type, otel_attributes(e))
    provider.shutdown()
    return len(events)


__all__ = [
    "AguiProjector",
    "project_all",
    "otel_attributes",
    "export_otlp",
    "AGUI_SPEC_VERSION",
]
