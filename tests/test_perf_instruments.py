# -*- coding: utf-8 -*-
"""性能测量与棘轮的自检：不联网、不调云端、不依赖 pytest。

验三件事：
1. trace 分段算得对（给定标记，跨段时间必须是可预期的数）；
2. 棘轮真能拦住退步，且只许往下拧；
3. 首屏计数能区分阻塞脚本与非阻塞脚本。

真链路数字由 `runs/perf/` 下的实测记录承担，不在本文件里假装。
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import perf_ratchet  # noqa: E402
import voice_latency_report as vlr  # noqa: E402
import web_perf_probe  # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  ✓ {name}")
        return
    FAILED.append(name)
    print(f"  ✗ {name} {detail}")


def make_turn(*, gap_closed_to_request: float = 50.0,
              tts_first_audio: float = 400.0,
              playback: float | None = 5.0) -> list[dict]:
    """造一轮：final → closed → request → first_audio → [playback] → done。"""
    rows = [
        {"t_ms": 1000.0, "kind": "asr.final", "text": "你好", "end_ms": 900, "index": 1},
        {"t_ms": 1020.0, "kind": "asr.closed", "sentences": 1, "dropped_bytes": 0},
        {"t_ms": 1020.0 + gap_closed_to_request, "kind": "tts.request", "run_id": "r1", "chars": 10},
        {"t_ms": 1020.0 + gap_closed_to_request + tts_first_audio, "kind": "tts.first_audio",
         "run_id": "r1", "bytes": 8000, "first_pcm_ms": tts_first_audio},
    ]
    if playback is not None:
        rows.append({"t_ms": 1020.0 + gap_closed_to_request + tts_first_audio + playback,
                     "kind": "client.playback.first_audio", "value": {"after_tts_request_ms": 0}})
    rows.append({"t_ms": 1020.0 + gap_closed_to_request + tts_first_audio + 900.0,
                 "kind": "tts.done", "run_id": "r1"})
    return rows


def test_spans() -> None:
    print("trace 分段")
    info = vlr.analyse_turn(make_turn())
    spans = info["spans_ms"]
    check("final → closed = 20ms", spans.get("final_to_closed") == 20.0, spans.get("final_to_closed"))
    check("closed → request = 50ms", spans.get("closed_to_tts_request") == 50.0, spans.get("closed_to_tts_request"))
    check("request → first_audio = 400ms",
          spans.get("tts_request_to_first_audio") == 400.0, spans.get("tts_request_to_first_audio"))
    check("first_audio → playback = 5ms",
          spans.get("first_audio_to_playback") == 5.0, spans.get("first_audio_to_playback"))
    check("request → playback = 405ms",
          spans.get("tts_request_to_playback") == 405.0, spans.get("tts_request_to_playback"))
    check("首包字节计数", info["counters"]["tts_bytes"] == 8000)
    check("回执存在标记", info["counters"]["has_playback_receipt"] is True)


def test_missing_receipt() -> None:
    print("缺失回执不臆造数字")
    info = vlr.analyse_turn(make_turn(playback=None))
    check("没有回执就没有该段",
          "first_audio_to_playback" not in info["spans_ms"]
          and info["counters"]["has_playback_receipt"] is False)


def test_turn_split() -> None:
    print("多轮切分")
    rows = make_turn() + [dict(row, t_ms=row["t_ms"] + 5000.0) for row in make_turn(gap_closed_to_request=80.0)]
    rows.sort(key=lambda r: r["t_ms"])
    turns = vlr.split_turns(rows)
    check("两轮切成两段", len(turns) == 2, len(turns))
    second = vlr.analyse_turn(turns[1])
    check("第二轮独立取自己的 closed→request",
          second["spans_ms"].get("closed_to_tts_request") == 80.0,
          second["spans_ms"].get("closed_to_tts_request"))


def test_ratchet() -> None:
    print("棘轮")
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "ratchet.json"
        metrics = Path(tmp) / "m.json"
        metrics.write_text(json.dumps({"metrics": {"voice.x_ms.p75": 400.0}}), encoding="utf-8")
        perf_ratchet.cmd_record(base, metrics, note="test", match=None)
        check("记录后检查通过", perf_ratchet.cmd_check(base, metrics, 0.05) == 0)

        worse = Path(tmp) / "worse.json"
        worse.write_text(json.dumps({"metrics": {"voice.x_ms.p75": 460.0}}), encoding="utf-8")
        check("退步被拦住", perf_ratchet.cmd_check(base, worse, 0.05) == 1)

        close = Path(tmp) / "close.json"
        close.write_text(json.dumps({"metrics": {"voice.x_ms.p75": 410.0}}), encoding="utf-8")
        check("容差内不算退步", perf_ratchet.cmd_check(base, close, 0.05) == 0)

        better = Path(tmp) / "better.json"
        better.write_text(json.dumps({"metrics": {"voice.x_ms.p75": 300.0}}), encoding="utf-8")
        perf_ratchet.cmd_tighten(base, better)
        data = perf_ratchet.load_baseline(base)
        check("变快后上限跟着降到 300", data["bounds"]["voice.x_ms.p75"]["upper"] == 300.0,
              data["bounds"]["voice.x_ms.p75"]["upper"])

        perf_ratchet.cmd_tighten(base, metrics)
        data = perf_ratchet.load_baseline(base)
        check("上限不会被调高", data["bounds"]["voice.x_ms.p75"]["upper"] == 300.0,
              data["bounds"]["voice.x_ms.p75"]["upper"])


def test_web_probe() -> None:
    print("首屏计数")
    html = """<html><head>
    <link rel="stylesheet" href="https://cdn.example.com/a.css">
    <script src="/blocking.js"></script>
    <script src="/deferred.js" defer></script>
    <script>var a = 1;</script>
    </head><body><img src="https://img.example.com/x.png"></body></html>"""
    metrics, refs = web_perf_probe.probe_html(html, "http://127.0.0.1:8080/")
    check("阻塞脚本只算 1 个", metrics["blocking_scripts"] == 1, metrics["blocking_scripts"])
    check("样式表算 1 个", metrics["stylesheets"] == 1)
    check("外域来源 2 个", metrics["external_origins"] == 2, metrics["external_origins"])
    check("关键路径请求 = 文档 + 阻塞脚本 + 样式表", metrics["critical_path_requests"] == 3,
          metrics["critical_path_requests"])
    check("内联脚本按字节计", metrics["inline_script_bytes"] == len("var a = 1;"))


def main() -> int:
    print("性能测量与棘轮自检\n")
    test_spans()
    test_missing_receipt()
    test_turn_split()
    test_ratchet()
    test_web_probe()
    if FAILED:
        print(f"\n失败 {len(FAILED)} 项：" + "、".join(FAILED))
        return 1
    print("\n全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
