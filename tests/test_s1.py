# -*- coding: utf-8 -*-
"""S1 自检：不依赖 pytest，直接 `python tests/test_s1.py`。

每条断言对应一条 S1 硬边界，失败即边界被破坏。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

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
    led.emit("tool.call_start", request_id="r", run_id="u", tenant_id="t", agent_version="v", channel="text", tool_call_id="tc1", tool="search_knowledge")
    led.emit("tool.outcome", request_id="r", run_id="u", tenant_id="t", agent_version="v", channel="text", tool_call_id="tc1", outcome="success")
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
    schema_path = ROOT / "_reference/ag-ui/spec/1.0/schema.json"
    if schema_path.exists():
        from jsonschema import Draft202012Validator
        validator = Draft202012Validator(json.loads(schema_path.read_text(encoding="utf-8")))
        errors = [(event["type"], list(validator.iter_errors(event))) for event in out]
        check("投影事件满足第一方 AG-UI 1.0 schema", all(not found for _, found in errors), str([name for name, found in errors if found]))

    cancelled = EventLedger()
    cancelled.emit("run.started", request_id="r", run_id="c", tenant_id="t", agent_version="v", channel="text")
    cancelled.emit("run.finished", request_id="r", run_id="c", tenant_id="t", agent_version="v", channel="text", request_state="cancelled")
    check("取消按第一方语料的 RUN_FINISHED outcome 投影", project_all(cancelled.events)[-1] == {"type": "RUN_FINISHED", "threadId": "r", "runId": "c", "outcome": {"type": "cancelled"}})


async def test_replay_cases() -> None:
    from loomrise.cli import run_case
    from loomrise.contracts import Case
    from loomrise.service import ExecutionService

    schema_path = ROOT / "_reference/ag-ui/spec/1.0/schema.json"
    validator = None
    if schema_path.exists():
        from jsonschema import Draft202012Validator
        validator = Draft202012Validator(json.loads(schema_path.read_text(encoding="utf-8")))
    for path in sorted(CASES.glob("*.json")):
        pack = ScenarioPack.load(str(PACK))
        case = Case.load(str(path))
        svc = ExecutionService(pack)
        rep = await run_case(pack, case, service=svc)
        check(f"案例 {case.case_id}", rep["passed"], str([c for c in rep["checks"] if not c["ok"]]))
        if validator:
            invalid = [e["type"] for e in project_all(svc.ledger.events) if not validator.is_valid(e)]
            check(f"AG-UI 案例 {case.case_id}", not invalid, str(invalid))
    # 业务终态不能靠模型口头声明
    pack = ScenarioPack.load(str(PACK))
    case = Case.load(str(CASES / "c7_timeout_unknown.json"))
    rep = await run_case(pack, case)
    check("超时未知不记成功", "unknown" in rep["outcomes"] and rep["state"] == "failed")


async def test_cancel_and_confirmation() -> None:
    from loomrise.service import ExecutionService
    from loomrise.contracts import RequestState
    from loomrise.contracts import Case

    case = Case.load(str(CASES / "c8_duplicate_write.json"))
    pack = ScenarioPack.load(str(PACK))
    svc = ExecutionService(pack)
    def cancel_at_confirmation(calls):
        started = svc.ledger.find("run.started")[-1]
        svc.cancel(started.request_id, run_id=started.run_id)
        return [True] * len(calls)

    result = await svc.handle_text(case.turns[0]["text"], script=case.script, ask_confirm=cancel_at_confirmation)
    check("确认点取消实际停止写入", result.request.state is RequestState.CANCELLED and result.write_count == 0, f"{result.request.state.value} / {result.write_count} / {svc.ledger.types()}")
    check("执行端确认取消并保留请求事件", bool(svc.ledger.find("run.cancel_requested")) and bool(svc.ledger.find("run.cancel_confirmed")))

    other = ExecutionService(ScenarioPack.load(str(PACK)))
    denied = await other.handle_text(case.turns[0]["text"], script=case.script)
    answers = other.ledger.find("permission.confirm_answered")
    check("无人工回调不能默认批准", denied.write_count == 0 and all(not a for e in answers for a in e.payload["answers"]))

    class CancelAfterWrite(EventLedger):
        def emit(self, event_type, **payload):
            event = super().emit(event_type, **payload)
            if event_type == "tool.outcome" and payload.get("result_id"):
                late.cancel(payload["request_id"], run_id=payload["run_id"])
            return event

    late = ExecutionService(ScenarioPack.load(str(PACK)), CancelAfterWrite())
    completed = await late.handle_text(case.turns[0]["text"], script=case.script, ask_confirm=lambda calls: [True] * len(calls))
    check("写入后取消不伪称撤销且保留结果 ID", completed.request.state is RequestState.SUCCESS and completed.request.result_id == completed.written_result_ids[0] and bool(late.ledger.find("run.cancel_confirmed")))


async def test_cross_channel_same_request() -> None:
    from loomrise.service import ExecutionService
    from loomrise.contracts import RequestState
    from loomrise.contracts import Case

    case = Case.load(str(CASES / "c8_duplicate_write.json"))
    pack = ScenarioPack.load(str(PACK))
    svc = ExecutionService(pack)
    started = await svc.handle_text("我想预约数据分析入门", script=[{"text": "请确认预约。"}])
    confirmed = await svc.handle_utterance("确认预约", media_session_id="media_switch", request=started.request, script=case.script, ask_confirm=lambda calls: [True] * len(calls))
    repeated = await svc.handle_text("再提交一次", request=started.request, script=case.script, ask_confirm=lambda calls: [True] * len(calls))
    events = svc.ledger.events
    check("文字语音跨渠道保持请求与版本", len({e.request_id for e in events}) == 1 and {e.agent_version for e in events} == {pack.agent_version.version_id} and {e.channel for e in events} == {"text", "voice"})
    check("跨渠道同一权限规则", any("booking.require_confirm" in e.payload.get("rule_ids", []) for e in events if e.event_type == "permission.decision") and any("dedupe.no_duplicate_write" in e.payload.get("rule_ids", []) for e in events if e.event_type == "permission.decision"))
    check("语音确认和文字重复提交只写一次", confirmed.write_count == 1 and repeated.write_count == 0 and repeated.request.result_id == confirmed.written_result_ids[0] and repeated.request.state is RequestState.SUCCESS)


def test_live_model_requires_key() -> None:
    from loomrise.adapters.agentscope_runtime import build_model

    # 隔离本机凭据：本用例验证的是"没有凭据时不许静默退回脚本模型"
    with patch.dict(os.environ, {"LOOMRISE_LIVE_MODEL": "fixed-model"}, clear=True), patch(
        "loomrise.local_config.load_config", return_value=None
    ):
        try:
            build_model()
        except RuntimeError:
            check("真实模型缺凭据不得回退脚本模型", True)
        else:
            check("真实模型缺凭据不得回退脚本模型", False)


def test_export_dependencies() -> None:
    from argparse import Namespace
    from loomrise.cli import cmd_export

    with tempfile.TemporaryDirectory() as dest:
        out = Path(dest)
        cmd_export(Namespace(out=out))
        requirements = (out / "requirements.txt").read_text(encoding="utf-8")
        check("导出包锁定相同 AgentScope 构件", "a38821287f35e9e45ed193d9d864cb46f263c946" in requirements)
        installed = [line for line in requirements.splitlines() if line.strip() and not line.lstrip().startswith("#")]
        check("导出包携带版本证据与隔离语音依赖", (out / "VERSION-PINS.md").exists() and (out / "voice-requirements.txt").exists() and not any("pipecat" in line for line in installed))
        check("导出包不含本机密钥且携带网页", not list(out.rglob("*coding-plan.json")) and (out / "loomrise/web.html").exists())


def test_offline_lock() -> None:
    """离线 wheelhouse 锁存在时校验：每条依赖都带哈希，且 wheel 在库内。"""
    lock = ROOT / "requirements-offline-macos-arm64-py313.txt"
    wheels = ROOT / ".build" / "offline" / "wheels"
    if not lock.exists():
        print("  skip  离线锁未生成（python scripts/build_offline.py）")
        return
    pins = []
    for line in lock.read_text(encoding="utf-8").splitlines():
        if line.startswith(("#", "--")) or "==" not in line or " --hash=sha256:" not in line:
            continue
        name, rest = line.split("==", 1)
        pins.append((name.strip(), rest.split(" ")[0].strip()))
    missing = [
        f"{n}=={v}" for n, v in pins
        # wheel 文件名是小写规范化名（Jinja2 → jinja2-3.1.6-...），大小写不敏感匹配
        if not list(wheels.glob(f"*{n.lower().replace('-', '_')}-{v}-*.whl"))
        and not list(wheels.glob(f"*{n.lower()}-{v}-*.whl"))
    ]
    check("离线锁覆盖核心依赖", "agentscope" in {n for n, _ in pins}, str(len(pins)))
    check("离线锁逐依赖哈希与 wheel 齐备", bool(pins) and not missing, str(missing))


def test_coding_plan_config() -> None:
    from loomrise.local_config import CONFIG_PATH, DEFAULT_MODEL, load_config, save_config
    from loomrise.adapters.agentscope_runtime import build_model, ScriptedChatModel
    from agentscope.model import OpenAIResponseModel

    # 验收默认档必须是实测稳定的档位；换档要同步改这里与 VERSION-PINS/S1-BUILD-REPORT。
    check("验收默认档为 gpt-6-sol", DEFAULT_MODEL == "gpt-6-sol", DEFAULT_MODEL)
    with tempfile.TemporaryDirectory() as dest:
        path = Path(dest) / "coding-plan.json"
        save_config("https://example.test/v1", "gpt-6-sol", "test-placeholder", path=path)
        check("凭据默认仅所有者可读", path.stat().st_mode & 0o077 == 0)
        check("凭据默认位置在仓库外", ROOT not in CONFIG_PATH.parents and ROOT != CONFIG_PATH.parent)
        check("凭据读取不回显", load_config(path)["key"] == "test-placeholder")
        with patch("loomrise.local_config.load_config", return_value=load_config(path)):
            model = build_model()
            check("Coding Plan 使用 Responses API", isinstance(model, OpenAIResponseModel) and model.model == "gpt-6-sol")
            check("案例显式脚本不消耗额度", isinstance(build_model([]), ScriptedChatModel))
        try:
            save_config("https://example.test/v1", "gpt-6-sol", "new-key", path=path)
        except FileExistsError:
            check("录入不覆盖已有密钥", True)
        else:
            check("录入不覆盖已有密钥", False)


async def test_web_sse() -> None:
    from aiohttp import ClientSession, web
    from loomrise.web import BrowserApp

    app = BrowserApp(scripted=True)
    runner = web.AppRunner(app.application())
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    base = f"http://127.0.0.1:{port}"

    async with ClientSession() as client:
        async def consume(text, channel="text", req_id=None, decision=None):
            payload = {"text": text, "channel": channel, "request_id": req_id}
            async with client.post(base + "/api/runs", json=payload) as response:
                check("HTTP SSE content-type", response.status == 200 and response.content_type == "text/event-stream")
                events = []
                async for line in response.content:
                    if not line.startswith(b"data: "):
                        continue
                    evt = json.loads(line[6:])
                    events.append(evt)
                    if evt.get("name") == "loomrise.require_user_confirm":
                        if decision == "cancel":
                            started = next(e for e in events if e["type"] == "RUN_STARTED")
                            async with client.post(base + "/api/cancel", json={"request_id": started["threadId"], "run_id": started["runId"]}) as ack:
                                check("HTTP 取消已发往运行任务", (await ack.json())["cancel_requested"])
                        else:
                            started = next(e for e in events if e["type"] == "RUN_STARTED")
                            async with client.post(base + "/api/confirm", json={"request_id": started["threadId"], "confirmed": bool(decision)}) as ack:
                                check("页面确认实际恢复运行", ack.status == 200)
                    if evt.get("name") == "loomrise.summary":
                        break
                return events

        try:
            first = await consume("数据分析入门多少钱？")
            req = next(e for e in first if e["type"] == "RUN_STARTED")["threadId"]
            voice = await consume("确认预约", "voice", req, True)
            repeated = await consume("再预约一次", "text", req, True)
            summaries = [next(e["value"] for e in run if e.get("name") == "loomrise.summary") for run in (first, voice, repeated)]
            check("HTTP/SSE 真正投送 AG-UI 事件", all(any(e["type"] == "RUN_FINISHED" for e in run) for run in (first, voice, repeated)))
            check("网页跨渠道共享请求、版本与结果", len({s["request_id"] for s in summaries}) == 1 and len({s["version"] for s in summaries}) == 1 and summaries[1]["result_id"] == summaries[2]["result_id"])
            check("网页跨渠道模拟写入仅一次", len(app.service._writes) == 1)
            session = app.voice[summaries[1]["run_id"]]
            async with client.post(base + "/api/playback", json={"run_id": session.run_id, "request_id": req, "action": "started", "text": summaries[1]["text"]}) as started:
                fragment = (await started.json())["fragment_id"]
            async with client.post(base + "/api/playback", json={"run_id": session.run_id, "request_id": req, "action": "finished", "fragment_id": fragment}) as played:
                check("设备播出回执独立于业务成功", played.status == 200 and session.snapshot()["confirmed"] == [fragment])
            rejected = await consume("预约课程", decision=False)
            check("网页拒绝返回终态", any(e.get("name") == "loomrise.summary" for e in rejected), str(rejected[-3:]))
            check("网页人工拒绝不写入", next(e["value"] for e in rejected if e.get("name") == "loomrise.summary")["result_id"] is None)
            cancelled = await consume("预约课程", decision="cancel")
            check("网页取消确认且无新增写入", any(e.get("outcome", {}).get("type") == "cancelled" for e in cancelled) and len(app.service._writes) == 1)
        finally:
            await runner.cleanup()


def main() -> int:
    print("S1 自检")
    test_ledger_chain()
    test_hard_rules()
    test_context_three_stage()
    test_compaction_policy()
    test_voice_playback()
    test_agui_projection()
    asyncio.run(test_replay_cases())
    asyncio.run(test_cancel_and_confirmation())
    asyncio.run(test_cross_channel_same_request())
    test_live_model_requires_key()
    test_export_dependencies()
    test_offline_lock()
    test_coding_plan_config()
    asyncio.run(test_web_sse())
    print("\n全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
