# -*- coding: utf-8 -*-
"""真实模型验收：咨询 / 确认写入 / 拒绝 / 工具失败 / 确认前取消 / 文字→语音同请求。

依赖本机 Coding Plan 凭据（`python -m loomrise.cli configure-model`）。
没有凭据时脚本直接退出并说明，不会退回脚本模型冒充真实调用。
结果写入 `runs/live-model-<时间戳>.json`（`runs/` 已被 Git 忽略）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loomrise.contracts import ScenarioPack  # noqa: E402
from loomrise.ledger import EventLedger  # noqa: E402
from loomrise.local_config import load_config  # noqa: E402
from loomrise.service import ExecutionService  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PACK = ROOT / "scenarios" / "course_consult_v1" / "pack.json"
BOOKING_TEXT = "帮我报名数据分析入门，学员张三，时段周二晚 20:00"


def _ts(event: Any) -> datetime | None:
    raw = getattr(event, "ts", None)
    return datetime.fromisoformat(raw) if isinstance(raw, str) else None


def _gaps(ledger: EventLedger) -> dict[str, float | None]:
    """首响 = run.started → 首个模型可见产出（文本片段或工具调用）；总耗时到 run.finished。"""
    start = ledger.one("run.started")
    done = ledger.one("run.finished")
    # 首个产出：文本片段与工具调用谁先到算谁（纯工具轮次没有文本）
    candidates = [
        e
        for et in ("reply.text", "tool.call_start")
        for e in ledger.find(et)[:1]
    ]
    first = min((e for e in candidates if _ts(e)), key=lambda e: _ts(e), default=None)
    out: dict[str, float | None] = {"first_response_ms": None, "total_ms": None}
    if start and first and _ts(start):
        out["first_response_ms"] = round((_ts(first) - _ts(start)).total_seconds() * 1000, 1)
    if start and done and _ts(start) and _ts(done):
        out["total_ms"] = round((_ts(done) - _ts(start)).total_seconds() * 1000, 1)
    return out


async def _run(
    pack: ScenarioPack,
    name: str,
    text: str,
    *,
    confirm: bool = False,
    failure_mode: str | None = None,
    cancel: bool = False,
    attempts: int = 1,
) -> dict[str, Any]:
    # 真实小模型不保证每轮都发起写入；需要写入工具出现的场景允许重试，
    # 重试次数写进报告，不把"模型没调用工具"伪装成权限层拦截。
    for attempt in range(1, attempts + 1):
        svc = ExecutionService(pack)
        wall = time.perf_counter()

        def ask(calls: list[Any]) -> list[bool]:
            if cancel:
                started = svc.ledger.find("run.started")[-1]
                svc.cancel(started.request_id, run_id=started.run_id)
            return [confirm for _ in calls]

        result = await svc.handle_text(text, ask_confirm=ask, failure_mode=failure_mode)
        wall_ms = round((time.perf_counter() - wall) * 1000, 1)
        if attempt == attempts or "create_booking" in [
            e.payload.get("tool") for e in svc.ledger.find("tool.call_start")
        ]:
            break
    return {
        "attempts": attempt,
        "scenario": name,
        "input": text,
        "state": result.request.state.value,
        "write_count": result.write_count,
        "result_ids": result.written_result_ids,
        "outcomes": result.outcomes,
        "text": result.text.strip(),
        "ledger_intact": svc.ledger.verify(),
        "cancel_confirmed": bool(svc.ledger.find("run.cancel_confirmed")),
        "permission": [
            e.payload.get("behavior")
            for e in svc.ledger.find("permission.decision")
        ],
        "tool_calls": [
            e.payload.get("tool")
            for e in svc.ledger.find("tool.call_start")
        ],
        "wall_ms": wall_ms,
        **_gaps(svc.ledger),
    }


async def _cross_channel(pack: ScenarioPack) -> dict[str, Any]:
    """文字发起被拒 → 语音渠道确认：同一请求、同一版本、只写一次。"""
    svc = ExecutionService(pack)
    first = await svc.handle_text(BOOKING_TEXT, ask_confirm=lambda calls: [False] * len(calls))
    second = await svc.handle_utterance(
        "确认报名，就按刚才说的提交",
        request=first.request,
        media_session_id="media_live_check",
        ask_confirm=lambda calls: [True] * len(calls),
    )
    return {
        "scenario": "文字发起 → 语音确认",
        "same_request_id": first.request.request_id == second.request.request_id,
        "same_version": first.request.agent_version == second.request.agent_version,
        "turn1_state": first.request.state.value,
        "turn2_state": second.request.state.value,
        "total_write_count": first.write_count + second.write_count,
        "result_ids": second.written_result_ids,
        "text": second.text.strip(),
        "ledger_intact": svc.ledger.verify(),
    }


def _checks(report: dict[str, Any]) -> list[dict[str, Any]]:
    by = {r["scenario"]: r for r in report["scenarios"]}
    consult = by["咨询"]
    confirmed = by["确认写入"]
    denied = by["拒绝"]
    failed = by["工具失败"]
    cancelled = by["确认前取消"]
    cross = by["文字发起 → 语音确认"]
    return [
        {"name": "真实模型咨询返回资料内价格", "ok": "3980" in consult["text"],
         "detail": consult["text"][:120]},
        {"name": "咨询无写入且终态成功", "ok": consult["write_count"] == 0 and consult["state"] == "success",
         "detail": f"{consult['state']} / writes={consult['write_count']}"},
        {"name": "人工确认后写入一次且成功", "ok": confirmed["write_count"] == 1 and confirmed["state"] == "success",
         "detail": f"{confirmed['state']} / writes={confirmed['write_count']}"},
        {"name": "确认路径有 permission.allow", "ok": "allow" in confirmed["permission"],
         "detail": f"{confirmed['permission']} / calls={confirmed['tool_calls']}"},
        {"name": "确认路径确实调用了写入工具", "ok": "create_booking" in confirmed["tool_calls"],
         "detail": f"{confirmed['tool_calls']} / attempts={confirmed['attempts']}"},
        {"name": "人工拒绝后零写入", "ok": denied["write_count"] == 0,
         "detail": f"{denied['state']} / writes={denied['write_count']}"},
        {"name": "模型发起写入时人工拒绝生效且记账 deny",
         "ok": ("create_booking" not in denied["tool_calls"])
         or (denied["state"] == "failed" and "deny" in denied["permission"]),
         "detail": f"called={denied['tool_calls']} state={denied['state']} perm={denied['permission']}"},
        {"name": "工具失败不记为成功",
         "ok": ("create_booking" not in failed["tool_calls"])
         or (failed["write_count"] == 0 and failed["state"] == "failed" and "error" in failed["outcomes"]),
         "detail": f"called={failed['tool_calls']} state={failed['state']} outcomes={failed['outcomes']}"},
        {"name": "确认前取消零写入且有执行端确认", "ok": cancelled["write_count"] == 0 and cancelled["cancel_confirmed"],
         "detail": f"cancel_confirmed={cancelled['cancel_confirmed']} writes={cancelled['write_count']}"},
        {"name": "跨渠道同一请求且只写一次",
         "ok": cross["same_request_id"] and cross["same_version"] and cross["total_write_count"] == 1,
         "detail": f"same_request={cross['same_request_id']} writes={cross['total_write_count']}"},
        {"name": "全部账本哈希链完整", "ok": all(r.get("ledger_intact", True) for r in report["scenarios"]),
         "detail": "ledger.verify()"},
    ]


async def main(pack_path: str, out_path: str) -> int:
    # 走模块属性：--model 覆盖是通过替换 load_config 实现的
    import loomrise.local_config as local_config

    config = local_config.load_config()
    if not config:
        print("未配置本机 Coding Plan 凭据：先跑 `python -m loomrise.cli configure-model`。")
        print("本脚本不会退回脚本模型，避免把模拟结果当成真实模型证据。")
        return 2
    pack = ScenarioPack.load(pack_path)
    scenarios = [
        await _run(pack, "咨询", "数据分析入门多少钱？"),
        await _run(pack, "确认写入", BOOKING_TEXT, confirm=True, attempts=3),
        await _run(pack, "拒绝", BOOKING_TEXT, confirm=False, attempts=3),
        await _run(pack, "工具失败", BOOKING_TEXT, confirm=True, failure_mode="error", attempts=3),
        await _run(pack, "确认前取消", BOOKING_TEXT, confirm=True, cancel=True, attempts=3),
        await _cross_channel(pack),
    ]
    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "model": config["model"],
        "base_url": config["base_url"],
        "scenarios": scenarios,
    }
    report["checks"] = _checks(report)
    report["passed"] = sum(1 for c in report["checks"] if c["ok"])
    report["total"] = len(report["checks"])
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for s in scenarios:
        print(f"[{s['scenario']}] state={s.get('state') or s.get('turn2_state')} "
              f"writes={s.get('write_count', s.get('total_write_count'))}")
    for c in report["checks"]:
        print(("  ✓ " if c["ok"] else "  × ") + f"{c['name']}: {c['detail'][:100]}")
    print(f"\n{report['passed']}/{report['total']} 通过 → {out}")
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="真实模型验收（需本机 Coding Plan 凭据）")
    ap.add_argument("--pack", default=str(DEFAULT_PACK))
    ap.add_argument("--out", default="")
    ap.add_argument("--model", default="", help="临时覆盖凭据里的模型名，用于对比不同模型")
    args = ap.parse_args()
    if args.model:
        import loomrise.local_config as lc

        original = lc.load_config

        def patched(*a: Any, **k: Any) -> dict[str, Any] | None:
            cfg = original(*a, **k)
            return None if cfg is None else {**cfg, "model": args.model}

        lc.load_config = patched
    out = args.out or str(ROOT / "runs" / f"live-model-{time.strftime('%Y%m%d-%H%M%S')}.json")
    raise SystemExit(asyncio.run(main(args.pack, out)))
