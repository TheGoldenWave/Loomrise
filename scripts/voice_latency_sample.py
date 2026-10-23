# -*- coding: utf-8 -*-
"""首响与识别时延采样（`M-S1-11`）。

**测的是服务端链路，不是浏览器整链**：音频由 TTS 合成后按实时节奏推给 ASR，
没有麦克风、没有设备播放、没有弱网。所以本脚本产出的数字只能回答
"服务端这一段有多快"，不能当"用户从开口到听见回复"的时延。

用法：`.venv/bin/python scripts/voice_latency_sample.py [--rounds 12]`
输出：`runs/r0/voice/latency-<时间戳>.csv` + 控制台 p50/p95。
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from loomrise.adapters import aliyun_voice  # noqa: E402

SENTENCES = [
    "你好，我想了解一下成人在线课程的价格。",
    "晚上有课吗？我想报名。",
    "课程一共多少周，每周上几次？",
    "退费政策是怎么规定的？",
    "我基础比较差，适合上这个课吗？",
]


def pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    lo, hi = int(pos), min(int(pos) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


async def one_round(text: str) -> dict:
    """一轮：TTS 合成 → 按实时节奏推给 ASR → 记录三段时延。"""
    row: dict = {"text": text, "chars": len(text)}

    tts = aliyun_voice.TtsStream(text)
    t_start = time.monotonic()
    tts_task = asyncio.create_task(tts.start())
    pcm_chunks: list[bytes] = []
    while True:
        chunk = await tts.chunks.get()
        if chunk is None:
            break
        pcm_chunks.append(chunk)
    await tts_task  # 等线程收尾，timing 才写全
    pcm = b"".join(pcm_chunks)
    row["tts_first_packet_ms"] = tts.timing.first_package_ms
    row["tts_bytes"] = len(pcm)
    row["tts_wall_ms"] = round((time.monotonic() - t_start) * 1000, 1)
    if not pcm:
        row["error"] = tts.timing.error or "empty_audio"
        return row

    asr = aliyun_voice.AsrStream()
    await asr.open()
    t_push = time.monotonic()
    first_partial_at: float | None = None
    final_at: float | None = None
    texts: list[str] = []

    async def consume() -> None:
        nonlocal first_partial_at, final_at
        while True:
            event = await asr.events.get()
            if event.synthetic:
                return
            if event.text and first_partial_at is None:
                first_partial_at = time.monotonic()
            if event.final and event.text:
                texts.append(event.text)
                final_at = time.monotonic()

    consumer = asyncio.create_task(consume())
    for i in range(0, len(pcm), aliyun_voice.FRAME_BYTES):
        await asr.feed(pcm[i : i + aliyun_voice.FRAME_BYTES])
        await asyncio.sleep(0.02)  # 20 ms/100 ms 帧 ≈ 5 倍实时，不是真实语速
    t_push_done = time.monotonic()
    await asr.finish()
    try:
        await asyncio.wait_for(consumer, timeout=15)
    except TimeoutError:
        consumer.cancel()

    row["asr_first_partial_ms"] = (
        round((first_partial_at - t_push) * 1000, 1) if first_partial_at else None
    )
    row["asr_final_after_push_ms"] = (
        round((final_at - t_push_done) * 1000, 1) if final_at else None
    )
    row["asr_text"] = "".join(texts)
    row["match"] = row["asr_text"].replace("，", "").replace("？", "").replace("。", "") == (
        text.replace("，", "").replace("？", "").replace("。", "")
    )
    row["dropped_bytes"] = asr.dropped_bytes
    return row


async def main_async(rounds: int) -> int:
    try:
        aliyun_voice.public_config()
    except aliyun_voice.VoiceUnavailable as exc:
        print(f"语音凭据不可用：{exc}")
        return 2

    rows: list[dict] = []
    for i in range(rounds):
        text = SENTENCES[i % len(SENTENCES)]
        print(f"第 {i + 1}/{rounds} 轮：{text}")
        row = await one_round(text)
        print(
            f"  tts_first={row.get('tts_first_packet_ms')} ms  "
            f"asr_partial={row.get('asr_first_partial_ms')} ms  "
            f"asr_final={row.get('asr_final_after_push_ms')} ms  "
            f"match={row.get('match')}  dropped={row.get('dropped_bytes')}"
        )
        rows.append(row)

    out_dir = ROOT / "runs" / "r0" / "voice"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = out_dir / f"latency-{stamp}.csv"
    fields = ["text", "chars", "tts_first_packet_ms", "tts_bytes", "tts_wall_ms",
              "asr_first_partial_ms", "asr_final_after_push_ms", "asr_text", "match",
              "dropped_bytes", "error"]
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k) for k in fields})

    def collect(key: str) -> list[float]:
        return [r[key] for r in rows if isinstance(r.get(key), (int, float))]

    print("\n汇总（服务端链路，非浏览器整链）")
    for key, label in (
        ("tts_first_packet_ms", "TTS 首包"),
        ("tts_wall_ms", "TTS 整句墙钟"),
        ("asr_first_partial_ms", "ASR 首个部分结果"),
        ("asr_final_after_push_ms", "推流结束到最终文本"),
    ):
        values = collect(key)
        if values:
            print(f"  {label}: n={len(values)} p50={pct(values, 0.5):.0f} ms "
                  f"p95={pct(values, 0.95):.0f} ms max={max(values):.0f} ms")
    matched = sum(1 for r in rows if r.get("match"))
    print(f"  识别一致 {matched}/{len(rows)}；丢弃字节合计 {sum(r.get('dropped_bytes') or 0 for r in rows)}")
    print(f"原始件 → {out}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=12)
    args = parser.parse_args()
    print("首响与识别时延采样（服务端链路）")
    return asyncio.run(main_async(args.rounds))


if __name__ == "__main__":
    sys.exit(main())
