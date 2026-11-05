"""changed_to 可行性结论：本机实现风险过高，保留明确拒绝与诊断。

阻塞原因：GraphRuntime 的 state 完全来自调用方 routing_state，唯一的服务端持久投影
state_window_counts 只有 attempts/runs 计数，没有按字段的可信前值快照；冻结版本里的
常量不是真实前值。在引入「服务端签发、调用方不可自报」的 previous-value 来源之前，
仅凭表达式启用 changed_to 会让调用方用当前输入自报前值、伪装成有权威前值来源，
并放松 G0/G1 确定性裁决的硬边界。

本文件锁定：冻结/运行时都明确拒绝并给出原因；调用方自报前值、在表达式里声明来源、
否定或短路都不能绕过；两层条件深度上限与既有确定性算子不受影响。
"""
import unittest

from loomrise.config_validation import CHANGED_TO_BLOCKED_REASON, validate_configuration
from loomrise.graph_runtime import GraphRuntime, GraphRuntimeError
from tests.test_graph_runtime import config as runtime_config
from tests.test_graph_validation import codes, graph_spec


def changed_to_fact(**extra):
    return {'fact': {'field': 'verified', 'op': 'changed_to', 'value': True, **extra}}


class ChangedToRejectionTests(unittest.TestCase):
    def test_freeze_rejects_changed_to_with_explicit_previous_value_diagnostic(self):
        spec = graph_spec()
        spec['orchestration']['edges'][0]['condition'] = changed_to_fact()
        issues = validate_configuration(spec, submitting=True)
        self.assertIn('unsupported_runtime_fact_operator', [issue.code for issue in issues])
        self.assertIn(CHANGED_TO_BLOCKED_REASON, [issue.message for issue in issues])
        # 草稿保存仍可保留中间态，但提交/冻结一律拒绝。
        self.assertEqual(codes(spec, submitting=False).count('unsupported_runtime_fact_operator'), 0)

    def test_declaring_a_source_in_the_expression_does_not_enable_changed_to(self):
        # 缺来源、或调用方在表达式里自称「有冻结基线来源」，都不能仅凭表达式启用。
        for extra in ({}, {'source': 'frozen_baseline'},
                      {'previous_value': False, 'source': 'frozen_baseline'}):
            with self.subTest(extra=extra):
                spec = graph_spec()
                spec['orchestration']['edges'][0]['condition'] = changed_to_fact(**extra)
                self.assertIn('unsupported_runtime_fact_operator', codes(spec, submitting=True))

    def test_runtime_rejects_changed_to_with_the_same_explicit_diagnostic(self):
        value = runtime_config()
        value['orchestration']['edges'][0]['condition'] = changed_to_fact()
        with self.assertRaises(GraphRuntimeError) as ctx:
            GraphRuntime(value).route({'verified': True})
        self.assertEqual(str(ctx.exception), CHANGED_TO_BLOCKED_REASON)

    def test_caller_self_reported_previous_value_never_makes_changed_to_pass(self):
        # 无论调用方往 state 注入什么「前值」，changed_to 都是被拒绝而不是被静默求值。
        value = runtime_config()
        value['orchestration']['edges'][0]['condition'] = changed_to_fact()
        for spoof in (
            {'verified': True, 'previous_value': False},
            {'verified': True, 'previous_values': {'verified': False}},
            {'verified': True, '__previous_values': {'verified': False}},
            {'verified': True, 'state_window_counts': {'verified': False}},
            {'verified': True, 'changed_to_source': {'field': 'verified', 'value': False}},
        ):
            with self.subTest(spoof=spoof):
                with self.assertRaises(GraphRuntimeError) as ctx:
                    GraphRuntime(value).route(spoof)
                self.assertIn('changed_to', str(ctx.exception))

    def test_negation_and_short_circuit_cannot_bypass_changed_to(self):
        leaf = changed_to_fact()
        conditions = (
            leaf,
            {'none_of': [leaf]},
            {'not': [leaf]},
            {'any_of': [{}, leaf]},
            {'all_of': [{'fact': {'field': 'verified', 'op': 'eq', 'value': True}}, {'not': [leaf]}]},
        )
        value = runtime_config()
        for condition in conditions:
            with self.subTest(condition=condition):
                value['orchestration']['edges'][0]['condition'] = condition
                with self.assertRaises(GraphRuntimeError) as ctx:
                    GraphRuntime(value).route({'verified': True})
                self.assertIn('changed_to', str(ctx.exception))

    def test_deterministic_operators_and_two_layer_depth_cap_are_unchanged(self):
        # 既有确定性算子仍可冻结/求值，诊断只作用于 changed_to。
        spec = graph_spec()
        spec['orchestration']['edges'][0]['condition'] = {'fact': {'field': 'verified', 'op': 'eq', 'value': True}}
        self.assertNotIn('unsupported_runtime_fact_operator', codes(spec, submitting=True))
        value = runtime_config()
        value['orchestration']['edges'][0]['condition'] = {'fact': {'field': 'verified', 'op': 'eq', 'value': True}}
        self.assertIn(GraphRuntime(value).route({'verified': True}).status, ('completed', 'fallback'))
        # 两层组合深度上限没有被放宽。
        value['orchestration']['edges'][0]['condition'] = {
            'all_of': [{'any_of': [{'all_of': [{'fact': {'field': 'verified', 'op': 'eq', 'value': True}}]}]}]}
        with self.assertRaisesRegex(GraphRuntimeError, 'combination|layer'):
            GraphRuntime(value).route({'verified': True})


if __name__ == '__main__':
    unittest.main()
