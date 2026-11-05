# -*- coding: utf-8 -*-
"""棘轮：把已经赢下来的数字锁住，只许降不许升。

**它和 Gate 阈值不是一回事**（见 `docs/PERFORMANCE-LATENCY-METHOD.md` §3）：

- 棘轮上限 = 由**实测基线**导出的回归护栏。用途是防止后面某个改动悄悄退步。
- Gate 阈值 = **跑测前登记**的绝对上限，不倒填（`VOICE-COORDINATION-VALIDATION.md` §0）。

过了棘轮 ≠ 达标；达标的判据仍是 Gate。棘轮只能回答"有没有比以前差"。

用法：

    # 首次建立基线（把当前指标记为上限）
    python3 scripts/perf_ratchet.py --baseline perf/ratchet.json \
        --record runs/perf/voice-metrics.json

    # CI / 本地回归：变差则退出码 1
    python3 scripts/perf_ratchet.py --baseline perf/ratchet.json \
        --check runs/perf/voice-metrics.json

    # 数字降了，把上限跟着往下拧（只降不升）
    python3 scripts/perf_ratchet.py --baseline perf/ratchet.json \
        --tighten runs/perf/voice-metrics.json

只依赖标准库。指标文件形如 `{"metrics": {"voice.x.p75": 347.0, ...}}`，
也接受扁平的 `{"voice.x.p75": 347.0}`。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = ROOT / "perf" / "ratchet.json"

# 默认容差：同口径重复测量本身有抖动，5% 以内不算退步；超了才算。
DEFAULT_TOLERANCE = 0.05


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def read_metrics(path: Path, match: str | None = None) -> dict[str, float]:
    raw = load_json(path)
    metrics = raw.get("metrics", raw)
    pattern = re.compile(match) if match else None
    out: dict[str, float] = {}
    for key, value in metrics.items():
        if isinstance(value, bool):
            continue
        if not isinstance(value, (int, float)):
            continue
        if pattern is not None and not pattern.search(str(key)):
            continue
        out[str(key)] = float(value)
    return out


def load_baseline(path: Path) -> dict:
    if not path.exists():
        return {"version": 1, "updated": None, "bounds": {}}
    data = load_json(path)
    data.setdefault("version", 1)
    data.setdefault("bounds", {})
    return data


def save_baseline(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data["updated"] = now_iso()
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def cmd_record(baseline_path: Path, metrics_path: Path, note: str = "", match: str | None = None) -> int:
    """把本次指标全部记为上限。只在基线为空或确认换口径时用。"""
    data = load_baseline(baseline_path)
    metrics = read_metrics(metrics_path, match)
    for key, value in metrics.items():
        entry = data["bounds"].setdefault(key, {})
        entry["upper"] = value
        entry["source"] = str(metrics_path.relative_to(ROOT)) if metrics_path.is_relative_to(ROOT) else str(metrics_path)
        entry["recorded"] = now_iso()
        if note:
            entry["note"] = note
    save_baseline(baseline_path, data)
    print(f"已记录 {len(metrics)} 项上限 → {baseline_path}")
    return 0


def cmd_tighten(baseline_path: Path, metrics_path: Path, match: str | None = None) -> int:
    """上限只降不升：本次更小就跟着降，更大则保持不动并提示。"""
    data = load_baseline(baseline_path)
    metrics = read_metrics(metrics_path, match)
    tightened = 0
    kept = 0
    added = 0
    for key, value in metrics.items():
        entry = data["bounds"].get(key)
        if entry is None:
            data["bounds"][key] = {"upper": value, "source": "tighten", "recorded": now_iso()}
            added += 1
            continue
        if value < entry["upper"]:
            entry["upper"] = value
            entry["recorded"] = now_iso()
            tightened += 1
        else:
            kept += 1
    save_baseline(baseline_path, data)
    print(f"拧紧 {tightened} 项，新增 {added} 项，保持不变 {kept} 项 → {baseline_path}")
    return 0


def cmd_check(baseline_path: Path, metrics_path: Path, tolerance: float) -> int:
    data = load_baseline(baseline_path)
    bounds = data["bounds"]
    metrics = read_metrics(metrics_path)
    if not bounds:
        print("基线为空：先跑 --record 建立上限，否则棘轮无从判断。")
        return 2

    regressions: list[str] = []
    missing: list[str] = []
    ok = 0
    for key, entry in sorted(bounds.items()):
        if key not in metrics:
            missing.append(key)
            continue
        upper = float(entry["upper"])
        limit = upper * (1 + tolerance)
        value = metrics[key]
        if value > limit:
            regressions.append(f"  ✗ {key}: {value:.1f} > 上限 {upper:.1f}（容差 {tolerance:.0%} → {limit:.1f}）")
        else:
            ok += 1

    print(f"棘轮检查：{ok} 项在限内，{len(regressions)} 项退步，{len(missing)} 项本次未测")
    for line in regressions:
        print(line)
    if missing:
        print("  本次未覆盖：" + "、".join(missing[:12]) + ("…" if len(missing) > 12 else ""))
    if regressions:
        print("\n退步不等于不允许——但必须写明原因并更新基线上限，不能默默放过。")
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="性能/延迟棘轮")
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--record", type=Path, help="用本次指标建立上限（初始化）")
    group.add_argument("--check", type=Path, help="检查是否退步，退步退出码 1")
    group.add_argument("--tighten", type=Path, help="把上限往下拧（只降不升）")
    parser.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE)
    parser.add_argument("--note", default="", help="写入基线的备注（来源、口径、样本量）")
    parser.add_argument("--match", default=None, help="只处理键名匹配该正则的指标（record/tighten 用）")
    args = parser.parse_args()

    if args.record:
        return cmd_record(args.baseline, args.record, args.note, args.match)
    if args.tighten:
        return cmd_tighten(args.baseline, args.tighten, args.match)
    return cmd_check(args.baseline, args.check, args.tolerance)


if __name__ == "__main__":
    sys.exit(main())
