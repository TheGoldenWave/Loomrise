import test from 'node:test';
import assert from 'node:assert/strict';
import { conditionSummary } from '../orchestration/condition-summary.js';

test('summarizes unconditional and fact conditions without evaluating them', () => {
  assert.equal(conditionSummary({}), '无条件');
  assert.equal(conditionSummary({ fact: { field: 'price', op: 'gte', value: 100 } }), 'price ≥ 100');
  assert.equal(conditionSummary({ fact: { field: 'visitor.name', op: 'exists' } }), 'visitor.name 存在');
  assert.equal(conditionSummary({ fact: { field: 'status', op: 'eq', value: 'ready' } }), 'status = "ready"');
});

test('summarizes event attributes and state windows', () => {
  assert.equal(conditionSummary({ event: { event: 'tool_call', attributes: { tool_id: 'lookup' } } }), '事件：工具调用 · tool_id="lookup"');
  assert.equal(conditionSummary({ state: { metric: 'attempts', window: '24h', op: 'gt', value: 2 } }), '尝试次数 / 24h > 2');
});

test('summarizes model prompts and compound conditions concisely', () => {
  assert.equal(conditionSummary({ llm: { prompt: '用户正在询问退款' } }), '模型判据：用户正在询问退款');
  assert.equal(conditionSummary({ all_of: [
    { fact: { field: 'verified', op: 'eq', value: true } },
    { event: { event: 'human_takeover' } },
  ] }), '全部：verified = true 且 事件：人工接管');
  assert.equal(conditionSummary({ not: [{ fact: { field: 'count', op: 'gt', value: 0 } }] }), '不满足：count > 0');
  assert.equal(conditionSummary({ any: [{}, { llm: { prompt: '符合条件' } }] }), '任一：无条件 或 模型判据：符合条件');
});

test('keeps malformed or unsupported conditions safe and display-only', () => {
  const condition = { fact: { field: 'amount', op: 'between', value: [1, 5] } };
  const before = structuredClone(condition);
  assert.equal(conditionSummary(condition), 'amount 位于 [1, 5]');
  assert.deepEqual(condition, before);
  assert.equal(conditionSummary({ fact: { field: 'x', op: 'made_up', value: 1 } }), '条件结构未识别');
  assert.equal(conditionSummary({ state: { metric: 'runs', window: 'session', op: 'eq', value: 1 } }), '条件结构未识别');
  assert.equal(conditionSummary('{bad json'), '条件结构未识别');
});

test('truncates long display text and tolerates circular objects', () => {
  const summary = conditionSummary({ llm: { prompt: '问'.repeat(200) } });
  assert.equal(summary.length, 80);
  assert.ok(summary.endsWith('…'));
  const circular = { all_of: [] };
  circular.all_of.push(circular);
  assert.equal(conditionSummary(circular), '条件结构未识别');
});
