# -*- coding: utf-8 -*-
"""真实模型驱动的 AG-UI SSE 消费留档（M-S1-12）。

起真服务（**不加 `--scripted`**），用 HTTP 客户端消费 `/api/runs` 的流，
记录事件序列、首包时间、结束时间与模型信息。

**它证明的是"客户端能完整消费真实模型的流"，不证明模型回答质量。**

用法：`.venv/bin/python scripts/sse_live_check.py [--text ...]`
没有模型凭据时直接退出，不退回脚本模型冒充。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aiohttp import ClientSession, web  # noqa: E402

from loomrise.local_config import load_config  # noqa: E402
from loomrise.web import BrowserApp  # noqa: E402

DEFAULT_TEXT = "你们的数据分析入门课程多少钱？上课时间是怎么安排的？"


async def run(text: str) -> dict:
    if not load_config():
        print("没有本机模型凭据：先运行 `python -m loomrise.cli configure-model`")
        raise SystemExit(2)

    app = BrowserApp(scripted=False)
    runner = web.AppRunner(app.application())
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = runner.addresses[0][1]

    timeline: list[dict] = []
    text_chunks: list[str] = []
    result: dict = {"text": text, "scripted": False}

    try:
        async with ClientSession() as http:
            t0 = time.monotonic()

            def mark(kind: str, **extra):
                timeline.append({"t_ms": round((time.monotonic() - t0) * 1000, 1), "type": kind, **extra})

            mark("request.sent")
            async with http.post(
                f"http://127.0.0.1:{port}/api/runs",
                json={"text": text, "channel": "text"},
            ) as resp:
                result["http_status"] = resp.status
                mark("response.headers", status=resp.status,
                     content_type=resp.headers.get("Content-Type"))
                if resp.status != 200:
                    result["error"] = (await resp.text())[:400]
                    return result
                buffer = ""
                async for raw in resp.content.iter_any():
                    buffer += raw.decode("utf-8", "replace")
                    while "\n\n" in buffer:
                        frame, buffer = buffer.split("\n\n", 1)
                        payload = [l[6:] for l in frame.split("\n") if l.startswith("data: ")]
                        if not payload:
                            continue
                        event = json.loads("\n".join(payload))
                        kind = event.get("type")
                        extra = {}
                        if kind == "CUSTOM":
                            extra["name"] = event.get("name")
                            value = event.get("value") or {}
                            if event.get("name") == "loomrise.summary":
                                extra["state"] = value.get("state")
                                extra["version"] = value.get("version")
                                extra["request_id"] = value.get("request_id")
                                extra["result_id"] = value.get("result_id")
                                result["summary"] = value
                        if kind == "RUN_STARTED":
                            extra["threadId"] = event.get("threadId")
                            extra["runId"] = event.get("runId")
                            result["thread_id"] = event.get("threadId")
                            result["run_id"] = event.get("runId")
                        if kind == "TEXT_MESSAGE_CONTENT":
                            text_chunks.append(event.get("delta") or "")
                            extra["delta_chars"] = len(event.get("delta") or "")
                        if kind == "TEXT_MESSAGE_START":
                            extra["first_text"] = True
                        mark(kind, **extra)
                        if kind == "CUSTOM" and event.get("name") == "loomrise.summary":
                            result["finished_at_ms"] = timeline[-1]["t_ms"]
                mark("stream.closed")
    finally:
        await runner.cleanup()

    result["timeline"] = timeline
    result["reply"] = "".join(text_chunks)
    result["event_types"] = sorted({row["type"] for row in timeline})
    # 真实模型的三项可核标记。**声明模型、配置模型、事件里的模型分开记**：
    # 场景包的 `AgentVersion.model` 是冻结配置的声明值（当前是脚本模式名）；
    # 实际调用用的是本机凭据里的模型；上游 `ModelCallEndEvent` 实测**不带模型名**，
    # 所以"实际用了哪个模型"只能引配置，不能伪装成事件证据。
    events = app.service.ledger.events
    declared = app.service.pack.agent_version.model
    from loomrise.local_config import load_config as _load

    configured = (_load() or {}).get("model")
    event_models = sorted({
        e.payload.get("model")
        for e in events
        if e.event_type == "model.call_end" and e.payload.get("model")
    })
    result["ledger"] = {
        "declared_model": declared,
        "configured_model": configured,
        "event_models": event_models,
        "model_source": "event" if event_models else "local_config",
        "model_matches_declared": (event_models[0] if event_models else configured) == declared,
        "declared_model_version": app.service.pack.agent_version.model_version,
        "agent_version": app.service.pack.agent_version.version_id,
        "run_started_attempts": [
            e.payload.get("attempt") for e in events if e.event_type == "run.started"
        ],
        "model_calls": [
            {
                "model": e.payload.get("model"),
                "input_tokens": e.payload.get("input_tokens"),
                "output_tokens": e.payload.get("output_tokens"),
                "finished_reason": e.payload.get("finished_reason"),
                "ts": e.ts,
            }
            for e in events if e.event_type == "model.call_end"
        ],
    }
    result["ok"] = bool(
        result.get("run_id")
        and result.get("reply")
        and result.get("summary")
        and any(r["type"] == "TEXT_MESSAGE_CONTENT" for r in timeline)
    )
    result["stamp"] = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", default=DEFAULT_TEXT)
    args = parser.parse_args()
    print("真实模型 SSE 留档（非脚本模式）")
    result = asyncio.run(run(args.text))
    out = ROOT / "runs" / "r0" / "sse" / f"sse-{result.get('stamp', 'x')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    for row in result.get("timeline", []):
        label = row["type"] + (f"({row['name']})" if row.get("name") else "")
        print(f"  {row['t_ms']:>8.1f} ms  {label}")
    print(f"\n回复（{len(result.get('reply', ''))} 字）：{result.get('reply', '')[:120]}")
    ledger = result.get("ledger") or {}
    print(f"声明模型 {ledger.get('declared_model')} / 配置模型 {ledger.get('configured_model')}"
          f"（来源 {ledger.get('model_source')}，一致：{ledger.get('model_matches_declared')}）")
    print(f"结果 → {out}")
    if not result.get("ok"):
        print("失败：未取得完整链路（见 JSON 的 error / timeline）")
        return 1
    print("通过：真实模型 SSE 完整消费")
    return 0


if __name__ == "__main__":
    sys.exit(main())
