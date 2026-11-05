# -*- coding: utf-8 -*-
"""把语音会话 trace 拆成"用户说完 → 听见回复"的分段时延。

输入是 `web.py:voice_ws` 落盘的 `ws-*.jsonl`（每条一行，带会话内 `t_ms`）。
输出是**分段表**（不是一个大数）加一组**确定性计数**，供棘轮与实验日志引用。

为什么要拆：一个总时延数字只能说明"慢"，说不清慢在哪一段；只有分段之后，
每一次改动才能对应到"哪一段少了几毫秒"，也才能在没变快时判断该回退。

用法：

    # 汇总现有证据
    python3 scripts/voice_latency_report.py --out runs/perf/voice-metrics.json

    # 指定一批 trace（可重复 --traces 或传 glob）
    python3 scripts/voice_latency_report.py --traces 'runs/r0/voice/ws-*.jsonl'

**边界（写清楚，不然数字会被误用）**：

- 只测**同一会话时钟内**两段之间的距离。`asr.final.end_ms` 是识别流内部时钟，
  与会话 `t_ms` 不同源，所以"最后一个字落到哪一刻"目前**不可测**，见
  `docs/PERFORMANCE-LATENCY-METHOD.md` §4.2 的测量缺口登记。
- 分段不区分场景、模型版本与网络条件；跨条件混算会得出假结论，故每段都带 `n`。
- 本脚本不联网、不调用云端、不产生新样本，只重算已有证据。
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 分段定义：名字 → (起点 kind, 终点 kind)。两端必须同属一轮、同一个会话时钟。
SPANS = {
    "final_to_closed": ("asr.final", "asr.closed"),
    "closed_to_tts_request": ("asr.closed", "tts.request"),
    "tts_request_to_first_audio": ("tts.request", "tts.first_audio"),
    "first_audio_to_playback": ("tts.first_audio", "client.playback.first_audio"),
    "tts_request_to_playback": ("tts.request", "client.playback.first_audio"),
    "first_audio_to_done": ("tts.first_audio", "tts.done"),
}


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo), 1)


def read_trace(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and "kind" in row:
                rows.append(row)
    rows.sort(key=lambda r: r.get("t_ms", 0.0))
    return rows


def split_turns(rows: list[dict]) -> list[list[dict]]:
    """按 `tts.request` 切轮：一轮 = 该请求前后相关的标记。

    前边界取最近的 `asr.final` / `asr.closed`；后边界取 `tts.done` /
    `tts.cancelled` 或下一条 `tts.request`。
    """
    turns: list[list[dict]] = []
    current: list[dict] = []
    for row in rows:
        kind = row.get("kind")
        if kind == "tts.request" and current and any(r.get("kind") == "tts.request" for r in current):
            turns.append(current)
            current = []
        current.append(row)
        if kind in ("tts.done", "tts.cancelled"):
            turns.append(current)
            current = []
    if any(r.get("kind") == "tts.request" for r in current):
        turns.append(current)
    return turns


def first_of(turn: list[dict], kind: str, *, after: float | None = None) -> dict | None:
    for row in turn:
        if row.get("kind") != kind:
            continue
        if after is not None and row.get("t_ms", 0.0) < after:
            continue
        return row
    return None


def last_before(turn: list[dict], kind: str, before: float) -> dict | None:
    found = None
    for row in turn:
        if row.get("kind") == kind and row.get("t_ms", 0.0) <= before:
            found = row
    return found


def analyse_turn(turn: list[dict]) -> dict:
    request = first_of(turn, "tts.request")
    if request is None:
        return {}
    t_req = request["t_ms"]
    closed = last_before(turn, "asr.closed", t_req)
    final = last_before(turn, "asr.final", t_req)
    first_audio = first_of(turn, "tts.first_audio", after=t_req)
    playback = first_of(turn, "client.playback.first_audio", after=t_req)
    done = first_of(turn, "tts.done", after=t_req)

    marks = {row.get("kind"): row for row in (closed, final, request, first_audio, playback, done) if row}
    spans: dict[str, float] = {}
    for name, (start_kind, end_kind) in SPANS.items():
        start, end = marks.get(start_kind), marks.get(end_kind)
        if start and end and end["t_ms"] >= start["t_ms"]:
            spans[name] = round(end["t_ms"] - start["t_ms"], 1)

    # 业务链路的串行档数：asr.closed 与 tts.request 之间落下的标记个数。
    # 这是一个确定性的计数——同样的代码路径，跑多少次都是同一个数。
    serial_stages = 0
    if closed:
        serial_stages = sum(
            1 for row in turn
            if closed["t_ms"] < row.get("t_ms", 0.0) < t_req and row.get("kind") != "asr.partial"
        )

    chars = request.get("chars")
    return {
        "run_id": request.get("run_id"),
        "spans_ms": spans,
        "counters": {
            "chars": chars,
            "tts_bytes": (first_audio or {}).get("bytes"),
            "serial_stages": serial_stages,
            "asr_sentences": (closed or {}).get("sentences"),
            "dropped_bytes": (closed or {}).get("dropped_bytes"),
            "has_playback_receipt": playback is not None,
        },
    }


def approx_speech_end(turn: list[dict]) -> float | None:
    """实验性近似：用 `asr.open` 当识别流原点，把 `end_ms` 换算到会话时钟。

    误差来源至少两个（首个音频帧到 `asr.open` 的间隔、服务端 VAD 的句尾迟滞），
    因此**不进棘轮、不进结论**，只作为下次补字段的动机。
    """
    opened = first_of(turn, "asr.open")
    final = first_of(turn, "asr.final")
    if not opened or not final:
        return None
    end_ms = final.get("end_ms")
    if not isinstance(end_ms, (int, float)):
        return None
    speech_end = opened["t_ms"] + float(end_ms)
    return round(final["t_ms"] - speech_end, 1)


def main() -> int:
    parser = argparse.ArgumentParser(description="语音分段时延与确定性计数")
    parser.add_argument("--traces", action="append", default=[],
                        help="glob 或文件路径，可重复；默认 runs/**/ws-*.jsonl")
    parser.add_argument("--out", type=Path, default=ROOT / "runs" / "perf" / "voice-metrics.json")
    parser.add_argument("--md", type=Path, default=None, help="另存一份 Markdown 表")
    args = parser.parse_args()

    patterns = args.traces or [str(ROOT / "runs" / "**" / "ws-*.jsonl")]
    paths: list[Path] = []
    for pattern in patterns:
        if any(ch in pattern for ch in "*?["):
            base = pattern if Path(pattern).is_absolute() else str(ROOT / pattern)
            paths.extend(sorted(Path(hit) for hit in glob.glob(base, recursive=True)))
            continue
        p = Path(pattern) if Path(pattern).is_absolute() else ROOT / pattern
        if p.exists():
            paths.append(p)
    paths = sorted(set(paths))
    if not paths:
        print("没有找到 trace。先跑 `scripts/voice_ws_smoke.py` 或真实网页会话落盘。")
        return 2

    turns: list[dict] = []
    coverage = {
        "files": len(paths),
        "files_with_playback_receipt": 0,
        "files_with_tts": 0,
        "turns_without_closed": 0,
    }
    approx: list[float] = []

    for path in paths:
        rows = read_trace(path)
        if not rows:
            continue
        if any(r.get("kind") == "client.playback.first_audio" for r in rows):
            coverage["files_with_playback_receipt"] += 1
        if any(r.get("kind") == "tts.request" for r in rows):
            coverage["files_with_tts"] += 1
        for turn in split_turns(rows):
            info = analyse_turn(turn)
            if not info:
                continue
            if not any(r.get("kind") == "asr.closed" for r in turn):
                coverage["turns_without_closed"] += 1
            value = approx_speech_end(turn)
            if value is not None:
                approx.append(value)
            info["trace"] = path.name
            turns.append(info)

    if not turns:
        print("trace 里没有可分析的轮次（缺 tts.request）。")
        return 2

    metrics: dict[str, float] = {}
    table: list[tuple[str, int, float | None, float | None, float | None]] = []
    for name in SPANS:
        values = [t["spans_ms"][name] for t in turns if name in t["spans_ms"]]
        if not values:
            continue
        p50, p75, p95 = percentile(values, 0.5), percentile(values, 0.75), percentile(values, 0.95)
        table.append((name, len(values), p50, p75, p95))
        for label, value in (("p50", p50), ("p75", p75), ("p95", p95)):
            if value is not None:
                metrics[f"voice.{name}_ms.{label}"] = value

    counters = {
        "turns": len(turns),
        "serial_stages_max": max((t["counters"]["serial_stages"] or 0) for t in turns),
        "tts_bytes_max": max((t["counters"]["tts_bytes"] or 0) for t in turns),
        "chars_max": max((t["counters"]["chars"] or 0) for t in turns),
        "dropped_bytes_total": sum((t["counters"]["dropped_bytes"] or 0) for t in turns),
    }

    payload = {
        "generated": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "source": "recompute from existing traces（不是新增采样）",
        "inputs": [f"{p.parent.name}/{p.name}" for p in paths],
        "coverage": coverage,
        "metrics": metrics,
        "counters": counters,
        "approx_metrics": {
            "voice.final_after_vad_sentence_end_approx_ms.p75": percentile(approx, 0.75),
            "n": len(approx),
            "why_not_gated": "识别流时钟与会话时钟不同源，误差未量化；仅用于提出补字段",
        },
        "turns": turns,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")

    header = "| 分段 | n | p50 | p75 | p95 |\n|---|---|---|---|---|"
    lines = [header]
    for name, n, p50, p75, p95 in table:
        lines.append(f"| `{name}` | {n} | {p50} | {p75} | {p95} |")
    md = "\n".join(lines)
    print("语音分段时延（毫秒，同会话时钟）\n")
    print(md)
    print(f"\n轮次 {counters['turns']}；覆盖：{coverage}")
    print(f"确定性计数：串行档数上限 {counters['serial_stages_max']}，"
          f"首包字节上限 {counters['tts_bytes_max']}，字符上限 {counters['chars_max']}，"
          f"丢弃字节合计 {counters['dropped_bytes_total']}")
    if approx:
        p75 = percentile(approx, 0.75)
        note = "出现负值即证明原点假设不成立" if (p75 or 0) < 0 else "原点假设未经验证"
        print(f"参考（不进棘轮、不作结论）：VAD 句尾到最终文本 ≈ p75 {p75} ms，n={len(approx)}；"
              f"{note}，见方法文档 §4.2")
    print(f"指标 JSON → {args.out}")

    if args.md:
        args.md.parent.mkdir(parents=True, exist_ok=True)
        args.md.write_text(md + "\n", encoding="utf-8")
        print(f"Markdown → {args.md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
