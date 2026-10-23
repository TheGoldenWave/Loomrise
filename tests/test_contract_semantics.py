# -*- coding: utf-8 -*-
"""合同语义自检：不依赖 pytest，直接 `python tests/test_contract_semantics.py`。

每条新语义至少一正一反。这里验的是**分层是否真的分开**，不是"代码能跑"：

- 裁决（`Verdict` 四值，无 allow）
- 授权（`AuthorizationResult`，登记即允许）
- 路由去向（`GateOutcome`，与裁决并列）
- 事项状态（`RequestState`，本文件只验不越界）
- 条件深度（2 层，`llm` 叶不计层）
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from loomrise.contracts import (  # noqa: E402
    AuthorizationResult,
    GateOutcome,
    HardRule,
    ServiceRequest,
    StateWindow,
    SubjectScope,
    ToolManifest,
    Verdict,
    Channel,
    RequestState,
)
from loomrise.rules import DecisionPolicy, VERDICT_PRECEDENCE  # noqa: E402
from loomrise.validation import (  # noqa: E402
    MAX_CONDITION_DEPTH,
    condition_depth,
    rule_conditions,
    validate_condition_depth,
)

FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        FAILED.append(name)


def rule(rule_id: str, verdict: Verdict, **kw) -> HardRule:
    return HardRule(rule_id=rule_id, scope=kw.pop("scope", "task"), verdict=verdict,
                    reason=kw.pop("reason", "测试规则"), **kw)


def tool(tool_id: str, level: str = "read_only") -> ToolManifest:
    return ToolManifest(
        tool_id=tool_id, version="1.0.0", business_meaning="测试工具",
        side_effect_level=level, idempotent=True, requires_confirm=False,
        timeout_ms=1000, result_id_required=False,
    )


def test_verdict_has_no_allow() -> None:
    values = {v.value for v in Verdict}
    check("Verdict 只有四值", values == {"deny", "require", "stop", "dedupe"}, str(values))
    check("Verdict 没有 allow", "allow" not in values)
    check("优先级链覆盖四值且顺序固定",
          VERDICT_PRECEDENCE == (Verdict.DENY, Verdict.STOP, Verdict.REQUIRE, Verdict.DEDUPE),
          str([v.value for v in VERDICT_PRECEDENCE]))


def test_legacy_behavior_rejected() -> None:
    ok = False
    try:
        HardRule.from_dict({"rule_id": "x", "scope": "task", "behavior": "allow", "reason": "旧字段"})
    except ValueError as exc:
        ok = "behavior" in str(exc)
    check("旧 behavior 键显式失败而不是静默丢弃", ok)

    parsed = HardRule.from_dict({"rule_id": "y", "scope": "task", "verdict": "require", "reason": "新字段"})
    check("verdict 在边界归一成枚举", parsed.verdict is Verdict.REQUIRE, repr(parsed.verdict))


def test_authorization_is_separate() -> None:
    policy = DecisionPolicy([], tools=[tool("search_knowledge")])
    auth = policy.authorize("search_knowledge")
    check("已登记即允许", auth.allowed and auth.side_effect_level == "read_only", str(auth))
    check("授权结果不是裁决对象", isinstance(auth, AuthorizationResult) and not hasattr(auth, "verdict"))

    denied = policy.authorize("delete_everything")
    check("未登记即拒绝", not denied.allowed, str(denied))

    d = policy.authorize("nope")
    check("授权查询不产生 Verdict", not hasattr(d, "verdict"))

    decision = policy.check("search_knowledge", {})
    check("无规则时放行（verdict 为 None）", decision.verdict is None and decision.allowed, str(decision.verdict))
    check("放行仍带授权依据", decision.authorization is not None and decision.authorization.allowed)

    decision = policy.check("delete_everything", {})
    check("未登记时拒绝且标明原因",
          decision.verdict is Verdict.DENY and "未在 ToolPolicy 中登记" in decision.reason,
          decision.reason)


def test_precedence_pairwise() -> None:
    tools = [tool("t")]
    pairs = [
        (Verdict.DENY, Verdict.STOP, Verdict.DENY),
        (Verdict.DENY, Verdict.REQUIRE, Verdict.DENY),
        (Verdict.DENY, Verdict.DEDUPE, Verdict.DENY),
        (Verdict.STOP, Verdict.REQUIRE, Verdict.STOP),
        (Verdict.STOP, Verdict.DEDUPE, Verdict.STOP),
        (Verdict.REQUIRE, Verdict.DEDUPE, Verdict.REQUIRE),
    ]
    for hi, lo, expected in pairs:
        policy = DecisionPolicy(
            [rule("r.lo", lo, tool="t"), rule("r.hi", hi, tool="t")],
            tools=tools,
        )
        d = policy.check("t", {})
        check(f"{hi.value} 压过 {lo.value}", d.verdict is expected, f"得到 {d.verdict}")

    policy = DecisionPolicy([rule("r.one", Verdict.REQUIRE, tool="t")], tools=tools)
    d = policy.check("t", {})
    check("单一规则按自身裁决", d.verdict is Verdict.REQUIRE and d.rule_ids == ["r.one"], str(d.rule_ids))


def test_dedupe() -> None:
    tools = [tool("book", "mock_write")]
    policy = DecisionPolicy([rule("r.req", Verdict.REQUIRE, tool="book")], tools=tools)
    policy.remember_write("k1", "res_1")

    d = policy.check("book", {"idempotency_key": "k1"})
    check("重复幂等键判 dedupe", d.verdict is Verdict.DEDUPE, str(d.verdict))
    check("dedupe 带已知 result_id", d.known_result_id == "res_1", str(d.known_result_id))

    d = policy.check("book", {"idempotency_key": "k2"})
    check("新幂等键不判 dedupe", d.verdict is not Verdict.DEDUPE, str(d.verdict))

    guard = policy.enforce_deny("book", {"idempotency_key": "k1"})
    check("执行前闸门也识别 dedupe", guard is not None and guard.verdict is Verdict.DEDUPE, str(guard))

    guard = policy.enforce_deny("book", {"idempotency_key": "k2"})
    check("执行前闸门对未重复的键放行", guard is None, str(guard))


def test_enforce_deny_only_denies() -> None:
    tools = [tool("book", "mock_write")]
    policy = DecisionPolicy(
        [rule("r.req", Verdict.REQUIRE, tool="book"), rule("r.stop", Verdict.STOP, tool="other")],
        tools=tools,
    )
    check("require 不在执行前闸门拦截", policy.enforce_deny("book", {}) is None)


def test_gate_outcome_parallel() -> None:
    values = {v.value for v in GateOutcome}
    check("GateOutcome 三值", values == {"route_to", "block", "suspend"}, str(values))
    check("GateOutcome 与 Verdict 不共享成员",
          values.isdisjoint({v.value for v in Verdict}), str(values))


def test_subject_scope() -> None:
    req = ServiceRequest(
        request_id="r1", tenant_id="t1", agent_version="v1",
        channel=Channel.TEXT, state=RequestState.RUNNING,
    )
    check("未给主体时默认 ephemeral", req.subject_scope is SubjectScope.EPHEMERAL)
    check("ephemeral 不产生可落库主体", req.persistent_subject is None)

    ok = True
    try:
        ServiceRequest(
            request_id="r2", tenant_id="t1", agent_version="v1",
            channel=Channel.TEXT, state=RequestState.RUNNING,
            subject_scope=SubjectScope.MAPPED,
        )
    except ValueError:
        ok = False
    check("mapped 缺 subject_id 必须失败（不许空值即默认主体）", not ok)

    mapped = ServiceRequest(
        request_id="r3", tenant_id="t1", agent_version="v1",
        channel=Channel.TEXT, state=RequestState.RUNNING,
        subject_id="u_1", subject_scope="mapped",
    )
    check("mapped 带主体时可落库", mapped.persistent_subject == "u_1", str(mapped.subject_scope))
    check("字符串 scope 归一成枚举", mapped.subject_scope is SubjectScope.MAPPED)


def test_state_window() -> None:
    check("StateWindow 四值",
          {v.value for v in StateWindow} == {"cycle", "24h", "forever", "session"})
    check("默认窗口是 cycle（本轮不实现计数器）", StateWindow.CYCLE.value == "cycle")


def test_condition_depth() -> None:
    leaf = {"arg": "course_id", "equals": "UNKNOWN"}
    two = {"all": [leaf, {"any": [{"arg": "a", "equals": 1}, {"arg": "b", "equals": 2}]}]}
    three = {"all": [{"any": [{"all": [leaf, leaf]}]}]}
    llm = {"llm": {"prompt": "判断用户是否在询价"}}

    check("单层深度 1", condition_depth(leaf) == 1)
    check("两层深度 2", condition_depth(two) == 2, str(condition_depth(two)))
    check("三层深度 3", condition_depth(three) == 3, str(condition_depth(three)))
    check("llm 叶不计层", condition_depth(llm) == 0)
    check("llm 嵌套在组合里只算组合那一层",
          condition_depth({"all": [llm, leaf]}) == 1,
          str(condition_depth({"all": [llm, leaf]})))

    check("两层通过", not validate_condition_depth([("edge.a", two)]))
    issues = validate_condition_depth([("edge.b", three)])
    check("三层被拒", len(issues) == 1 and issues[0].depth == 3, str(issues))

    bad = validate_condition_depth([("edge.c", {"whatever": 1})])
    check("无法识别的结构被报出", len(bad) == 1 and "无法识别" in bad[0].message, str(bad))

    bad_not = validate_condition_depth([("edge.d", {"not": [leaf, leaf]})])
    check("not 只接受一个子条件", len(bad_not) == 1, str(bad_not))

    check("空条件合法", not validate_condition_depth([("edge.e", {})]))


def test_rule_conditions_entry() -> None:
    rules = [
        rule("r.when", Verdict.DENY, tool="book", when_arg_equals={"course_id": "UNKNOWN"}),
        rule("r.plain", Verdict.REQUIRE, tool="book"),
    ]
    conds = rule_conditions(rules)
    check("有 when 的规则进校验入口", [c[0] for c in conds] == ["r.when"], str([c[0] for c in conds]))
    check("平铺 when 转成 1 层条件树", condition_depth(conds[0][1]) == 1)
    check("平铺 when 不触发深度问题", not validate_condition_depth(conds))


def main() -> int:
    print("合同语义自检")
    test_verdict_has_no_allow()
    test_legacy_behavior_rejected()
    test_authorization_is_separate()
    test_precedence_pairwise()
    test_dedupe()
    test_enforce_deny_only_denies()
    test_gate_outcome_parallel()
    test_subject_scope()
    test_state_window()
    test_condition_depth()
    test_rule_conditions_entry()
    if FAILED:
        print(f"\n失败 {len(FAILED)} 项：" + "、".join(FAILED))
        return 1
    print("\n全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
