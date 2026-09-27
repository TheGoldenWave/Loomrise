# -*- coding: utf-8 -*-
"""S1 自检：不依赖 pytest，直接 `python tests/test_s1.py`。

每条断言对应一条 S1 硬边界，失败即边界被破坏。
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from loomrise.adapters.projection import project_all  # noqa: E402
from loomrise.adapters.voice import VoiceSession, simulate_session  # noqa: E402
from loomrise.context import CompactionPolicy, ContextLedger  # noqa: E402
from loomrise.contracts import (  # noqa: E402
    Behavior,
    ContextScope,
    LoadStatus,
    PlaybackState,
    ScenarioPack,
    ToolOutcome,
)
from loomrise.ledger import EventLedger  # noqa: E402
from loomrise.rules import DecisionPolicy  # noqa: E402

PACK = ROOT / "scenarios/course_consult_v1" / "pack.json"
CASES = ROOT / "scenarios/course_consult_v1" / "cases"


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("  ok   " if ok else "  FAIL ") + name + (f" — {detail}" if detail else ""))
    if not ok:
        raise AssertionError(name)


def test_ledger_chain() -> None:
    led = EventLedger()
    led.emit("a", request_id="r", run_id="u", tenant_id="t", agent_version="v", channel="text")
    led.emit("b", request_id="r", run_id="u", tenant_id="t", agent_version="v", channel="text")
    check("账本哈希链完整", led.verify())
    led.events[0].payload["x"] = 1  # 篡改
    check("篡改可被发现", not led.verify())


def test_hard_rules() -> None:
    pack = ScenarioPack.load(str(PACK))
    policy = DecisionPolicy(pack.rules)
    d = policy.check("create_booking", {"course_id": "UNKNOWN"})
    check("硬规则确定性拒绝", d.behavior is Behavior.DENY, str(d.rule_ids))
    d = policy.check("create_booking", {"course_id": "ok"})
    check("写入需人工确认（模型外）", d.behavior is Behavior.ASK, str(d.rule_ids))
    d = policy.check("search_knowledge", {"query": "x"})
    check("只读放行", d.behavior is Behavior.ALLOW)

    policy.remember_write("k1", "res_1")
    d = policy.check("create_booking", {"course_id": "ok", "idempotency_key": "k1"})
    check("重复写入被拦截", d.behavior is Behavior.DENY, d.reason)


def test_context_three_stage() -> None:
    pack = ScenarioPack.load(str(PACK))
    events: list = []
    led = EventLedger()
    ctx = ContextLedger(
        emit=lambda t, **p: led.emit(
            t, request_id="r", run_id="u", tenant_id="t",
            agent_version="v", channel="text", **p,
        ),
        run_id="u",
        request_id="r",
        budget_tokens=4000,
    )
    ctx.register_many(pack.fragments)
    ctx.stage_baseline()
    ctx.stage_task("course_consult_booking")
    ids = ctx.loaded_ids()
    check("基线加载", "ctx.identity" in ids and "ctx.safety" in ids)
    check("命中 Skill 加载", "ctx.sop.booking" in ids)
    check("未命中 Skill 跳过", "ctx.sop.refund" not in ids)

    # 过期片段
    ctx.stage_evidence(["kb.promo_expired"], trigger="test")
    expired = [d for d in ctx.decisions if d.fragment_id == "kb.promo_expired"]
    check("过期片段不得加载", expired[0].status is LoadStatus.EXPIRED)

    # 预算截断
    small = ContextLedger(
        emit=lambda t, **p: None, run_id="u2", request_id="r2", budget_tokens=1,
    )
    small.register_many(pack.fragments)
    small.stage_baseline()
    check("预算不足时记为 budget_capped", len(small.audit_answer()["budget_capped"]) > 0)


def test_compaction_policy() -> None:
    events: list = []
    deny = CompactionPolicy("deny")
    allowed = deny.intercept(emit=lambda t, **p: events.append(t), trigger="t", would_trigger=True)
    check("S1 拦截未登记压缩", allowed is False)
    check("拦截落事件", events == ["context.compaction_blocked"])
    try:
        CompactionPolicy("loomrise").intercept(
            emit=lambda t, **p: None, trigger="t", would_trigger=True,
        )
        check("未实现编排器时报错", False)
    except RuntimeError:
        check("未实现编排器时报错", True)


def test_voice_playback() -> None:
    events: list = []
    session = VoiceSession(
        session_id="m1", emit=lambda t, **p: events.append({"type": t, **p}),
    )
    snap = simulate_session(
        session,
        ["TTSTextFrame", "BotStartedSpeakingFrame", "BotStoppedSpeakingFrame"],
        ack_all=True,
    )
    check("客户端回执才算已确认播出", snap["confirmed"] == ["m1_frag_1"])
    session2 = VoiceSession(session_id="m2", emit=lambda t, **p: None)
    snap2 = simulate_session(
        session2,
        ["TTSTextFrame", "BotStartedSpeakingFrame", "InterruptionFrame"],
        ack_all=True,
    )
    check("打断后未确认播出记为 unknown", snap2["unknown"] == ["m2_frag_1"] and not snap2["confirmed"])
    states = {r["state"] for r in snap2["records"]}
    check("四态可区分", states <= {"generated", "sent", "confirmed", "unknown"})


def test_agui_projection() -> None:
    led = EventLedger()
    led.emit("run.started", request_id="r", run_id="u", tenant_id="t", agent_version="v", channel="text")
    led.emit("reply.text", request_id="r", run_id="u", tenant_id="t", agent_version="v", channel="text", text="hi")
    led.emit(
        "permission.confirm_required", request_id="r", run_id="u", tenant_id="t",
        agent_version="v", channel="text", tools=["create_booking"],
    )
    led.emit(
        "run.finished", request_id="r", run_id="u", tenant_id="t", agent_version="v",
        channel="text", request_state="success",
    )
    out = project_all(led.events)
    types = [e["type"] for e in out]
    check("AG-UI 运行开始/结束", "RUN_STARTED" in types and "RUN_FINISHED" in types)
    check("文本走离散三段", types.count("TEXT_MESSAGE_START") == 1)
    customs = [e for e in out if e["type"] == "CUSTOM"]
    check("确认走 CUSTOM 私有扩展", len(customs) == 1 and "confirm" in customs[0]["name"])


async def test_replay_cases() -> None:
    from loomrise.cli import run_case
    from loomrise.contracts import Case

    for name in ("c1_consult_success", "c2_booking_confirmed", "c8_duplicate_write"):
        pack = ScenarioPack.load(str(PACK))
        case = Case.load(str(CASES / f"{name}.json"))
        rep = await run_case(pack, case)
        check(f"案例 {name}", rep["passed"], str([c for c in rep["checks"] if not c["ok"]]))
    # 业务终态不能靠模型口头声明
    pack = ScenarioPack.load(str(PACK))
    case = Case.load(str(CASES / "c7_timeout_unknown.json"))
    rep = await run_case(pack, case)
    check("超时未知不记成功", "unknown" in rep["outcomes"] and rep["state"] == "failed")


def main() -> int:
    print("S1 自检")
    test_ledger_chain()
    test_hard_rules()
    test_context_three_stage()
    test_compaction_policy()
    test_voice_playback()
    test_agui_projection()
    asyncio.run(test_replay_cases())
    print("\n全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
