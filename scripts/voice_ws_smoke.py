# -*- coding: utf-8 -*-
"""语音媒体通道端到端冒烟：真服务 + 真阿里云，不经浏览器。

验三件事：
1. `POST` 之外的媒体链路能走通——WS 上行 PCM 经服务端进 DashScope ASR，回到文本；
2. 下行合成音频能分块到达客户端，且首块时延可测；
3. 时序字段足以支撑 M-S1-11 / M-S1-13 的采样（本脚本只出单次结果，不出 p95）。

**它替代不了浏览器实测**：没有麦克风、没有设备播放、没有回声与网络抖动。
M-S1-08 仍然只能由人工在浏览器里跑。

用法：`.venv/bin/python scripts/voice_ws_smoke.py [--text ...] [--keep]
没有语音凭据时直接退出，不退回任何替代实现。
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

from aiohttp import ClientSession, WSMsgType, web  # noqa: E402

from loomrise.adapters import aliyun_voice  # noqa: E402
from loomrise.web import BrowserApp  # noqa: E402

DEFAULT_TEXT = "你好，我想问一下成人在线课程的价格，晚上有课吗？"


async def synth_source_audio(text: str) -> bytes:
    """用 TTS 造一段"用户语音"，替代麦克风。仅用于打通链路，不能当可懂度样本。"""
    stream = aliyun_voice.TtsStream(text)
    await stream.start()
    chunks: list[bytes] = []
    while True:
        chunk = await stream.chunks.get()
        if chunk is None:
            break
        chunks.append(chunk)
    if stream.timing.error:
        raise RuntimeError(f"源音频合成失败：{stream.timing.error}")
    return b"".join(chunks)


async def run(text: str) -> dict:
    try:
        cfg = aliyun_voice.public_config()
    except aliyun_voice.VoiceUnavailable as exc:
        print(f"语音凭据不可用：{exc}")
        raise SystemExit(2) from None

    trace_dir = ROOT / "runs" / "r0" / "voice"
    app = BrowserApp(voice_trace_dir=trace_dir)
    runner = web.AppRunner(app.application())
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = runner.addresses[0][1]
    result: dict = {"text": text, "config": cfg}

    try:
        async with ClientSession() as http:
            async with http.ws_connect(f"http://127.0.0.1:{port}/ws/voice") as ws:
                ready = await ws.receive_json()
                print(f"ready  {ready.get('asr_model')} → {ready.get('tts_model')}")

                pcm = await synth_source_audio(text)
                print(f"源音频 {len(pcm)} 字节 / {len(pcm) / 32000:.2f}s")

                await ws.send_json({"type": "asr.start"})
                assert (await ws.receive_json())["type"] == "asr.ready"

                t_up = time.monotonic()
                for i in range(0, len(pcm), aliyun_voice.FRAME_BYTES):
                    await ws.send_bytes(pcm[i : i + aliyun_voice.FRAME_BYTES])
                    await asyncio.sleep(0.02)
                await ws.send_json({"type": "asr.stop"})

                final_text = ""
                while True:
                    msg = await ws.receive(timeout=30)
                    if msg.type != WSMsgType.TEXT:
                        continue
                    event = json.loads(msg.data)
                    kind = event.get("type")
                    if kind == "asr.partial":
                        print(f"  partial  {event.get('text')}")
                    elif kind == "asr.final":
                        final_text += event.get("text") or ""
                        result.setdefault("sentences", []).append(event)
                        print(f"  sentence[{event.get('index')}] {event.get('text')}  (end_ms={event.get('end_ms')})")
                    elif kind == "asr.closed":
                        result["asr_closed"] = event
                        print(f"  closed   sentences={event.get('sentences')} "
                              f"dropped={event.get('dropped_bytes')}")
                        break
                    elif kind == "error":
                        raise RuntimeError(f"ASR 错误：{event}")
                result["asr_text"] = final_text
                print(f"  合成文本  {final_text}")
                result["asr_roundtrip_ms"] = round((time.monotonic() - t_up) * 1000, 1)

                reply = "好的，成人课程晚上七点到九点有课，名额我帮您保留到今天十八点。"
                await ws.send_json({"type": "tts.speak", "text": reply, "run_id": "smoke"})
                audio = bytearray()
                timing: dict = {}
                first_audio_wall = None
                first_event_at = None
                while True:
                    msg = await ws.receive(timeout=30)
                    if msg.type == WSMsgType.BINARY:
                        if first_audio_wall is None:
                            first_audio_wall = time.monotonic()
                        audio.extend(msg.data)
                        continue
                    if msg.type != WSMsgType.TEXT:
                        continue
                    event = json.loads(msg.data)
                    if event.get("type") == "tts.first_audio":
                        first_event_at = time.monotonic()
                        timing = event.get("timing") or {}
                    elif event.get("type") == "tts.done":
                        timing = event.get("timing") or timing
                        break
                    elif event.get("type") == "error":
                        raise RuntimeError(f"TTS 错误：{event}")
                result["tts"] = {
                    "pcm_bytes": len(audio),
                    "first_audio_ms": round((first_audio_wall - t_up) * 1000, 1) if first_audio_wall else None,
                    "sdk_first_package_ms": timing.get("sdk_first_package_ms"),
                    "first_pcm_ms": timing.get("first_pcm_ms"),
                }
                print(f"下行音频 {len(audio)} 字节 / {len(audio) / 32000:.2f}s")
                print(f"TTS 首块 {result['tts']['first_pcm_ms']} ms（服务端计时）")
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                (trace_dir).mkdir(parents=True, exist_ok=True)
                (trace_dir / f"smoke-downlink-{stamp}.pcm").write_bytes(bytes(audio))
                result["asr_roundtrip_ok"] = bool(final_text)
                result["downlink_ok"] = len(audio) > 0
                result["stamp"] = stamp
    finally:
        await runner.cleanup()
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", default=DEFAULT_TEXT)
    args = parser.parse_args()
    print("语音通道冒烟（真服务 + 真云端，不经浏览器）")
    result = asyncio.run(run(args.text))
    out = ROOT / "runs" / "r0" / "voice" / f"smoke-{result.get('stamp', 'x')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n结果 → {out}")
    failed = [k for k in ("asr_roundtrip_ok", "downlink_ok") if not result.get(k)]
    if failed:
        print("失败：" + "、".join(failed))
        return 1
    print("通过：上行识别与下行合成都通")
    return 0


if __name__ == "__main__":
    sys.exit(main())
