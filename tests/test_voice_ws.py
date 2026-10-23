# -*- coding: utf-8 -*-
"""语音媒体通道自检：不依赖 pytest、不联网、不调用云端。

用 fake 的 ASR/TTS 替换适配器，只验协议层：凭据缺失是否显式失败、
final 是否去重、二进制块是否原样下行、打断是否真的传到适配器、证据是否落盘。

真链路（阿里云端到端）由 `runs/r0/voice/` 下的实测记录承担，不在本文件里假装。
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aiohttp import WSMsgType  # noqa: E402
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from loomrise.adapters import aliyun_voice  # noqa: E402
from loomrise.web import BrowserApp  # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        FAILED.append(name)


class FakeAsr:
    def __init__(self) -> None:
        self.model = "fake-asr"
        self.events: asyncio.Queue = asyncio.Queue()
        self.dropped_bytes = 0
        self.error = None
        self.fed: list[bytes] = []
        self.opened = 0
        self.finished = 0

    async def open(self) -> None:
        self.opened += 1

    async def feed(self, chunk: bytes) -> None:
        self.fed.append(chunk)

    async def finish(self) -> None:
        self.finished += 1
        self.events.put_nowait(aliyun_voice.AsrEvent(text="", final=True, synthetic=True))


class FakeTts:
    made: list["FakeTts"] = []

    def __init__(self, text: str) -> None:
        self.text = text
        self.chunks: asyncio.Queue = asyncio.Queue()
        self.timing = aliyun_voice.TtsTiming(request_at=time.monotonic())
        self.cancelled = False
        FakeTts.made.append(self)

    async def start(self) -> None:
        self.chunks.put_nowait(b"\x01\x02" * 160)
        self.timing.first_pcm_at = time.monotonic()
        self.timing.bytes = 320
        self.timing.done_at = time.monotonic()
        self.chunks.put_nowait(None)

    def cancel(self) -> None:
        self.cancelled = True
        self.chunks.put_nowait(None)


def make_app(trace_dir: Path | None = None) -> BrowserApp:
    return BrowserApp(scripted=True, voice_trace_dir=trace_dir)


async def test_voice_unavailable() -> None:
    app = make_app()
    client = TestClient(TestServer(app.application()))
    await client.start_server()
    try:
        with patch.object(aliyun_voice, "public_config",
                          side_effect=aliyun_voice.VoiceUnavailable("未配置语音凭据")):
            ws = await client.ws_connect("/ws/voice")
            msg = await ws.receive_json()
            check("凭据缺失返回 voice_unavailable", msg.get("code") == "voice_unavailable", str(msg))
            check("凭据缺失带可读原因", "未配置语音凭据" in str(msg.get("message")), str(msg))
            closing = await ws.receive()
            check("凭据缺失后关闭连接",
                  closing.type in (WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED),
                  str(closing.type))
    finally:
        await client.close()


async def test_protocol() -> None:
    FakeTts.made.clear()
    fake_asr = FakeAsr()
    trace_dir = Path(tempfile.mkdtemp(prefix="loomrise-ws-"))
    app = make_app(trace_dir)
    client = TestClient(TestServer(app.application()))
    await client.start_server()
    try:
        with patch.object(aliyun_voice, "public_config",
                          return_value={"asr_model": "fake-asr", "tts_model": "fake-tts",
                                        "tts_voice": "v", "sample_rate": 16000}), \
             patch.object(aliyun_voice, "AsrStream", lambda: fake_asr), \
             patch.object(aliyun_voice, "TtsStream", FakeTts):
            ws = await client.ws_connect("/ws/voice")

            ready = await ws.receive_json()
            check("连接后下发 ready", ready.get("type") == "ready", str(ready))
            check("ready 带模型与采样率",
                  ready.get("asr_model") == "fake-asr" and ready.get("sample_rate") == 16000, str(ready))

            await ws.send_bytes(b"\x00" * 3200)
            check("未开会话时的音频被忽略不报错", ws.closed is False)

            await ws.send_json({"type": "asr.start"})
            opened = await ws.receive_json()
            check("asr.start 回 asr.ready", opened.get("type") == "asr.ready", str(opened))
            check("asr.start 真的打开了适配器", fake_asr.opened == 1, str(fake_asr.opened))

            await ws.send_bytes(b"\x00" * 3200)
            await ws.send_bytes(b"\x01" * 3200)
            await asyncio.sleep(0.05)
            check("上行音频原样交给适配器", len(fake_asr.fed) == 2 and len(fake_asr.fed[0]) == 3200,
                  str([len(c) for c in fake_asr.fed]))

            fake_asr.events.put_nowait(aliyun_voice.AsrEvent(text="你好", final=False, begin_ms=0))
            partial = await ws.receive_json()
            check("部分结果下发 asr.partial", partial.get("type") == "asr.partial"
                  and partial.get("text") == "你好", str(partial))

            fake_asr.events.put_nowait(aliyun_voice.AsrEvent(text="你好，我想问价格", final=True,
                                                             begin_ms=0, end_ms=1200))
            final = await ws.receive_json()
            check("句子结束下发 asr.final", final.get("type") == "asr.final"
                  and final.get("text") == "你好，我想问价格", str(final))
            check("asr.final 带时间戳与序号", final.get("end_ms") == 1200 and final.get("index") == 1, str(final))

            # 这条是真实踩到的坑：中文逗号处被判句尾，第二句曾被吞掉。
            fake_asr.events.put_nowait(aliyun_voice.AsrEvent(text="", final=True))
            fake_asr.events.put_nowait(aliyun_voice.AsrEvent(text="晚上有课吗", final=True,
                                                             begin_ms=1500, end_ms=2600))
            second = await ws.receive_json()
            check("第二句必须继续转发", second.get("type") == "asr.final"
                  and second.get("index") == 2, str(second))
            check("空句尾不占用 final", second.get("text") == "晚上有课吗", str(second))

            await ws.send_json({"type": "asr.stop"})
            closed = await ws.receive_json()
            check("asr.stop 后下发 asr.closed", closed.get("type") == "asr.closed", str(closed))
            check("asr.closed 带句数与丢弃量", closed.get("sentences") == 2
                  and closed.get("dropped_bytes") == 0, str(closed))
            check("asr.stop 传到适配器", fake_asr.finished >= 1, str(fake_asr.finished))

            await ws.send_json({"type": "tts.speak", "text": "您好，名额保留到今晚", "run_id": "run-1"})
            started = await ws.receive_json()
            check("tts.speak 回 tts.started", started.get("type") == "tts.started", str(started))
            first = await ws.receive_json()
            check("首块前先报 tts.first_audio", first.get("type") == "tts.first_audio", str(first))
            chunk = await ws.receive()
            check("下行是二进制音频块", chunk.type == WSMsgType.BINARY and len(chunk.data) == 320,
                  f"{chunk.type} {len(getattr(chunk, 'data', b''))}")
            done = await ws.receive_json()
            check("合成结束下发 tts.done", done.get("type") == "tts.done", str(done))
            check("tts.done 带时序", "first_pcm_ms" in (done.get("timing") or {}), str(done))

            first_tts = FakeTts.made[-1]
            await ws.send_json({"type": "tts.cancel", "reason": "barge_in"})
            cancelled = await ws.receive_json()
            check("tts.cancel 回 tts.cancelled", cancelled.get("type") == "tts.cancelled", str(cancelled))
            check("tts.cancel 真的传到适配器", first_tts.cancelled is True)

            await ws.send_str("not json")
            bad = await ws.receive_json()
            check("非法 JSON 回 bad_json", bad.get("code") == "bad_json", str(bad))

            await ws.send_json({"type": "nope"})
            unknown = await ws.receive_json()
            check("未知类型回 unknown_type", unknown.get("code") == "unknown_type", str(unknown))

            await ws.send_json({"type": "tts.speak", "text": "  ", "run_id": "run-2"})
            empty = await ws.receive_json()
            check("空文本被拒", empty.get("code") == "bad_text", str(empty))

            await ws.send_json({"type": "metric", "name": "playback.stopped", "value": {"stop_ms": 7}})
            await ws.send_json({"type": "close"})
            await asyncio.sleep(0.2)

        files = sorted(trace_dir.glob("ws-*.jsonl"))
        check("证据文件已落盘", len(files) == 1, str(files))
        if files:
            rows = [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines() if line]
            kinds = [r["kind"] for r in rows]
            check("证据含会话生命周期",
                  "session.ready" in kinds and "session.closed" in kinds, str(kinds[:3]))
            check("证据含识别与合成时序",
                  "asr.final" in kinds and "tts.done" in kinds, str(kinds))
            check("证据收下客户端时序",
                  any(k == "client.playback.stopped" for k in kinds), str([k for k in kinds if k.startswith("client")]))
            check("证据不含密钥字段",
                  not any("api_key" in json.dumps(r) or "sk-" in json.dumps(r) for r in rows))
    finally:
        await client.close()


async def test_trace_off_by_default() -> None:
    app = make_app(None)
    client = TestClient(TestServer(app.application()))
    await client.start_server()
    try:
        with patch.object(aliyun_voice, "public_config",
                          return_value={"asr_model": "a", "tts_model": "t", "tts_voice": "v",
                                        "sample_rate": 16000}):
            ws = await client.ws_connect("/ws/voice")
            await ws.receive_json()
            await ws.send_json({"type": "close"})
            await asyncio.sleep(0.1)
        check("默认不落盘", app.voice_trace_dir is None)
    finally:
        await client.close()


def main() -> int:
    print("语音媒体通道自检")
    asyncio.run(test_voice_unavailable())
    asyncio.run(test_protocol())
    asyncio.run(test_trace_off_by_default())
    if FAILED:
        print(f"\n失败 {len(FAILED)} 项：" + "、".join(FAILED))
        return 1
    print("\n全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
