# -*- coding: utf-8 -*-
"""S1 命令行：run / replay / voice-sim / export / audit。

回放用脚本化确定性模型，不依赖外部 API 与密钥，因此"固定输入 + 固定版本 + 模拟环境"
可以再次跑出同样结论。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from .adapters.projection import project_all
from .adapters.voice import VoiceSession, make_voice_emitter, simulate_session
from .contracts import Case, Channel, ScenarioPack, new_id
from .ledger import EventLedger
from .service import ExecutionService

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PACK = ROOT / "scenarios/course_consult_v1/pack.json"
DEFAULT_CASES = ROOT / "scenarios/course_consult_v1/cases"


# --------------------------------------------------------------------------
# 用例执行
# --------------------------------------------------------------------------


async def run_case(
    pack: ScenarioPack,
    case: Case,
    *,
    service: ExecutionService | None = None,
    ledger: EventLedger | None = None,
) -> dict[str, Any]:
    """执行一个案例。多轮案例复用同一个 ExecutionService（同一业务请求）。"""
    svc = service or ExecutionService(pack, ledger)
    if case.context_budget_tokens:
        pack.agent_version.context_budget_tokens = case.context_budget_tokens

    cursor = {"i": 0}

    def ask(calls: list[Any]) -> list[bool]:
        if case.cancel_on_confirm:
            started = svc.ledger.find("run.started")[-1]
            svc.cancel(started.request_id, run_id=started.run_id)
        out = []
        for _ in calls:
            i = cursor["i"]
            cursor["i"] += 1
            out.append(
                case.confirm_responses[i] if i < len(case.confirm_responses) else True,
            )
        return out

    request = None
    results = []
    media_session_id = new_id("media") if case.channel is Channel.VOICE else None
    for turn in case.turns:
        handler = (
            svc.handle_utterance
            if case.channel is Channel.VOICE
            else svc.handle_text
        )
        kwargs: dict[str, Any] = {
            "request": request,
            "script": case.script,
            "ask_confirm": ask,
            "failure_mode": case.tool_failure_mode,
        }
        if case.channel is Channel.VOICE:
            kwargs["media_session_id"] = media_session_id
        r = await handler(turn["text"], **kwargs)
        request = r.request
        results.append(r)

    last = results[-1]

    # 语音：播放状态四态由 Loomrise 自建，业务请求仍是同一个
    playback = None
    if case.channel is Channel.VOICE:
        session = VoiceSession(
            session_id=media_session_id,
            emit=make_voice_emitter(
                svc.ledger,
                request_id=last.request.request_id,
                run_id=last.run_id,
                tenant_id=svc.tenant_id,
                agent_version=pack.agent_version.version_id,
                media_session_id=media_session_id,
            ),
            request_id=last.request.request_id,
            run_id=last.run_id,
        )
        playback = simulate_session(
            session,
            ["TTSTextFrame", "BotStartedSpeakingFrame", "BotStoppedSpeakingFrame"],
            ack_all=True,
        )

    text = " ".join(r.text for r in results)
    agui = project_all(svc.ledger.events)
    write_count = sum(len(r.written_result_ids) for r in results)
    checks = _check(case, last, text, playback, write_count)
    if case.cancel_on_confirm:
        checks.append({
            "name": "执行端确认取消且未写入",
            "ok": bool(svc.ledger.find("run.cancel_confirmed")) and write_count == 0,
            "detail": "run.cancel_confirmed / zero writes",
        })
    return {
        "case_id": case.case_id,
        "title": case.title,
        "channel": case.channel.value,
        "state": last.request.state.value,
        "expected_state": case.expected_state.value,
        "write_count": write_count,
        "expected_write_count": case.expected_write_count,
        "result_ids": [rid for r in results for rid in r.written_result_ids],
        "outcomes": [o for r in results for o in r.outcomes],
        "text": text.strip(),
        "context_audit": last.context_audit,
        "playback": playback,
        "events": len(svc.ledger.events),
        "agui_events": len(agui),
        "ledger_intact": svc.ledger.verify(),
        "checks": checks,
        "passed": all(c["ok"] for c in checks),
    }


def _check(
    case: Case,
    result,
    text: str,
    playback: dict[str, Any] | None,
    writes: int,
) -> list[dict[str, Any]]:
    checks = [
        {
            "name": "终态一致",
            "ok": result.request.state == case.expected_state,
            "detail": f"{result.request.state.value} vs {case.expected_state.value}",
        },
        {
            "name": "写入次数一致",
            "ok": writes == case.expected_write_count,
            "detail": f"{writes} vs {case.expected_write_count}",
        },
    ]
    if case.expected_outcome_contains:
        checks.append(
            {
                "name": "输出包含预期内容",
                "ok": case.expected_outcome_contains in text,
                "detail": case.expected_outcome_contains,
            },
        )
    for bad in case.forbidden:
        checks.append(
            {"name": f"未出现禁用内容：{bad}", "ok": bad not in text, "detail": bad},
        )
    if playback is not None:
        checks.append(
            {
                "name": "语音播放四态可区分（已确认播出 ≠ 仅已发送）",
                "ok": bool(playback["confirmed"]) and playback["unknown"] == [],
                "detail": json.dumps(playback, ensure_ascii=False),
            },
        )
    return checks


# --------------------------------------------------------------------------
# 子命令
# --------------------------------------------------------------------------


async def cmd_run(args: argparse.Namespace) -> int:
    pack = ScenarioPack.load(str(args.pack))
    svc = ExecutionService(pack)
    r = await svc.handle_text(args.text)
    print(json.dumps(
        {
            "request_id": r.request.request_id,
            "run_id": r.run_id,
            "state": r.request.state.value,
            "text": r.text,
            "context_audit": r.context_audit,
            "events": [e.event_type for e in svc.ledger.events],
        },
        ensure_ascii=False,
        indent=2,
    ))
    return 0


async def cmd_replay(args: argparse.Namespace) -> int:
    cases = sorted(Path(args.cases).glob("*.json"))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    # 每个案例一个 JSONL 事件账本：哈希链按案例自成一体，可直接用 audit 命令校验
    ledger_dir = out.parent / "events"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    reports = []
    for path in cases:
        pack = ScenarioPack.load(str(args.pack))
        case = Case.load(str(path))
        ledger_path = ledger_dir / f"{case.case_id}.jsonl"
        ledger_path.write_text("", encoding="utf-8")
        rep = await run_case(pack, case, ledger=EventLedger(str(ledger_path)))
        rep["ledger_path"] = str(ledger_path)
        reports.append(rep)
        flag = "PASS" if rep["passed"] else "FAIL"
        print(f"[{flag}] {rep['case_id']} · {rep['title']}")
        for c in rep["checks"]:
            if not c["ok"]:
                print(f"       × {c['name']}: {c['detail']}")
    passed = sum(1 for r in reports if r["passed"])
    summary = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "total": len(reports),
        "passed": passed,
        "failed": len(reports) - passed,
        "reports": reports,
    }
    out.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n{passed}/{len(reports)} 通过 → {out}")
    print(f"事件账本 → {ledger_dir}/<case_id>.jsonl（可用 audit 命令查看上下文审计）")
    return 0 if passed == len(reports) else 1


def cmd_voice_sim(_: argparse.Namespace) -> int:
    """不接音频设备也能回归播放状态机。"""
    events: list[dict[str, Any]] = []
    session = VoiceSession(
        session_id="media_demo",
        emit=lambda et, **p: events.append({"type": et, **p}),
    )
    snap = simulate_session(
        session,
        [
            "TTSTextFrame",
            "BotStartedSpeakingFrame",
            "BotStoppedSpeakingFrame",
            "TTSTextFrame",
            "BotStartedSpeakingFrame",
            "InterruptionFrame",
        ],
        ack_all=True,
    )
    print(json.dumps(
        {"playback": snap, "events": [e["type"] for e in events]},
        ensure_ascii=False,
        indent=2,
    ))
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    import shutil

    out = Path(args.out)
    (out / "scenarios").mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        DEFAULT_PACK.parent,
        out / "scenarios" / "course_consult_v1",
        dirs_exist_ok=True,
    )
    (out / "loomrise").mkdir(exist_ok=True)
    for f in Path(__file__).parent.glob("*.py"):
        shutil.copy(f, out / "loomrise" / f.name)
    shutil.copytree(
        Path(__file__).parent / "adapters",
        out / "loomrise" / "adapters",
        dirs_exist_ok=True,
    )
    shutil.copy(ROOT / "requirements.txt", out / "requirements.txt")
    shutil.copy(ROOT / "VERSION-PINS.md", out / "VERSION-PINS.md")
    shutil.copy(ROOT / "loomrise" / "web.html", out / "loomrise" / "web.html")
    if getattr(args, "offline", False):
        lock = ROOT / "requirements-offline-macos-arm64-py313.txt"
        wheels = ROOT / ".build" / "offline" / "wheels"
        if not lock.exists() or not wheels.is_dir():
            raise RuntimeError("Build the offline wheelhouse first: python scripts/build_offline.py")
        shutil.copy(lock, out / lock.name)
        shutil.copytree(wheels, out / "wheels", dirs_exist_ok=True)
    (out / "voice-requirements.txt").write_text("pipecat-ai[tracing]==1.12.0\n", encoding="utf-8")
    (out / "README.md").write_text(
        "\n".join([
            "# Loomrise S1 交付包（虚构数据 · 模拟写入）",
            "",
            "```bash",
            "python3 -m venv .venv && .venv/bin/pip install -r requirements.txt",
            ".venv/bin/python -m loomrise.cli replay --out replay.json",
            "```",
            "",
            "- 资料、配置与案例均为虚构；写入工具为模拟实现，不触达真实系统。",
            "- 回放使用脚本化确定性模型，不需要 API 密钥。",
            "- AgentScope 锁到 a388212；语音 Worker 单独安装 voice-requirements.txt，安装限制见 VERSION-PINS.md。",
            "- 使用 --offline 导出的包含 macOS arm64/Python 3.13 wheelhouse，可用 --no-index --find-links=wheels --require-hashes 安装 requirements-offline-macos-arm64-py313.txt。",
            "",
        ]),
        encoding="utf-8",
    )
    print(f"导出完成 → {out}")
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    from .ledger import load_ledger

    led = load_ledger(args.ledger)
    frag = [e.payload for e in led.find("context.fragment")]
    print(json.dumps(
        {
            "events": len(led.events),
            "types": sorted(set(led.types())),
            "intact": led.verify(),
            "loaded": [f["fragment_id"] for f in frag if f["load_status"] == "loaded"],
            "skipped": [
                {"id": f["fragment_id"], "reason": f.get("skip_reason")}
                for f in frag
                if f["load_status"] != "loaded"
            ],
        },
        ensure_ascii=False,
        indent=2,
    ))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="loomrise", description="Loomrise S1 执行内核")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="单条文本运行")
    r.add_argument("--text", required=True)
    r.add_argument("--pack", default=str(DEFAULT_PACK))
    r.set_defaults(func=cmd_run)

    rp = sub.add_parser("replay", help="回放全部人工审定案例")
    rp.add_argument("--pack", default=str(DEFAULT_PACK))
    rp.add_argument("--cases", default=str(DEFAULT_CASES))
    rp.add_argument("--out", default=str(ROOT / "runs" / "replay-s1.json"))
    rp.set_defaults(func=cmd_replay)

    v = sub.add_parser("voice-sim", help="语音播放状态机回归（无需音频设备）")
    v.set_defaults(func=cmd_voice_sim)

    e = sub.add_parser("export", help="导出可迁移交付包")
    e.add_argument("--out", default=str(ROOT / "dist" / "loomrise-s1"))
    e.add_argument("--offline", action="store_true", help="附带平台专用 wheelhouse 与哈希锁")
    e.set_defaults(func=cmd_export)

    a = sub.add_parser("audit", help="查看账本与上下文审计")
    a.add_argument("--ledger", required=True)
    a.set_defaults(func=cmd_audit)

    c = sub.add_parser("configure-model", help="一次性录入本机 Coding Plan 凭据")
    c.set_defaults(func=lambda _: __import__("loomrise.local_config", fromlist=["configure"]).configure() or 0)

    v = sub.add_parser("configure-voice", help="一次性录入本机阿里云语音凭据与端点")
    v.set_defaults(func=lambda _: __import__("loomrise.voice_config", fromlist=["configure"]).configure() or 0)

    w = sub.add_parser("web", help="仅在本机提供文字/语音与 AG-UI SSE 试用页")
    w.add_argument("--port", type=int, default=8765)
    w.add_argument("--scripted", action="store_true", help="显式使用脚本模型，不调用真实模型")
    w.add_argument("--voice-trace", metavar="DIR", default=None,
                   help="把语音会话时序写入目录（跑测用；默认不落盘）")
    w.set_defaults(func=lambda args: __import__("loomrise.web", fromlist=["serve"]).serve(
        args.port, scripted=args.scripted,
        voice_trace_dir=Path(args.voice_trace) if args.voice_trace else None))

    args = p.parse_args(argv)
    fn = args.func
    return asyncio.run(fn(args)) if asyncio.iscoroutinefunction(fn) else fn(args)


if __name__ == "__main__":
    sys.exit(main())
