import test from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { readCondition, writeCondition, newCondition } from '../orchestration/conditions.js';

test('condition form round-trips typed literals, operator aliases and nested combinations without mutating inputs', () => {
  for (const value of ['true', true, false, null, 2.5, [1, 'two', false, null]]) {
    const input = { fact: { field: 'known', op: Array.isArray(value) ? 'in' : 'eq', value } };
    const original = structuredClone(input);
    assert.deepEqual(writeCondition(readCondition(input)), input);
    assert.deepEqual(input, original);
  }
  for (const op of ['all', 'any', 'all_of', 'any_of', 'none_of']) {
    const input = { [op]: [{ fact: { field: 'ready', op: 'exists' } }] };
    assert.deepEqual(writeCondition(readCondition(input)), input);
  }
  const input = { all_of: [{ fact: { field: 'ready', op: 'eq', value: true } }, { any_of: [{ fact: { field: 'tier', op: 'eq', value: 'gold' } }] }] };
  assert.deepEqual(writeCondition(readCondition(input)), input);
});

test('unknown, legacy and unsupported model predicates remain in raw JSON rather than being converted', () => {
  for (const input of [[], null, { llm: '是退款意图' }, { llm: { prompt: '' } }, { llm: { prompt: 'ok', type: 'boolean' } },
    { fact: { field: 'x', op: 'eq', value: 1, custom: true } }, { not: { fact: { field: 'x', op: 'exists' } } },
    { field: 'x', op: 'eq', value: 1 }, { fact: { field: 'x', op: 'exists', value: null } },
    { fact: { field: 'x', op: 'eq', value: {} } }, { all: [] }]) assert.equal(readCondition(input), null);
});

test('string matches predicates round-trip as literal regex text', () => {
  const input = { fact: { field: 'order_code', op: 'matches', value: '^ORD-[0-9]{8}$' } };
  const tree = readCondition(input);
  assert.deepEqual(tree, { kind: 'fact', field: 'order_code', op: 'matches', type: 'string', value: input.fact.value });
  assert.deepEqual(writeCondition(tree), input);
  assert.equal(readCondition({ fact: { field: 'order_code', op: 'matches', value: 42 } }), null);
  assert.equal(writeCondition({ ...newCondition('fact'), field: 'order_code', op: 'matches', type: 'string', value: 'ORD-' }).fact.value, 'ORD-');
});

test('matches editor keeps its regex string, hides type selection, and shows length limits', async () => {
  const { outputFiles } = await build({ entryPoints: [new URL('../orchestration/condition-editor.jsx', import.meta.url).pathname],
    bundle: true, write: false, format: 'esm', external: ['react'] });
  const code = outputFiles[0].text.replace('from "react"', `from ${JSON.stringify(import.meta.resolve('react'))}`);
  const { ConditionEditor } = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);
  const value = JSON.stringify({ fact: { field: 'order_code', op: 'matches', value: '^ORD-[0-9]{8}$' } });
  const rendered = renderToStaticMarkup(React.createElement(ConditionEditor, { value, name: 'condition', onChange() {} }));
  assert.doesNotMatch(rendered, /值类型/);
  assert.ok(rendered.includes('value="^ORD-[0-9]{8}$"'));
  assert.match(rendered, /maxLength="128"/);
  assert.match(rendered, /128[^<]*1024/);
});

test('positive graph model predicates round-trip as Loomrise llm prompt leaves', () => {
  const model = { llm: { prompt: '用户是否已核验' } };
  const mixed = { any_of: [model, { fact: { field: 'verified', op: 'eq', value: true } }] };
  const tree = readCondition(mixed);
  assert.ok(tree);
  assert.deepEqual(tree.children[0], { kind: 'llm', prompt: '用户是否已核验' });
  assert.deepEqual(writeCondition(tree), mixed);
  assert.equal(readCondition(model, 0, false), null);
  assert.equal(readCondition({ none_of: [model] }), null);
  assert.throws(() => writeCondition({ kind: 'none_of', children: [{ kind: 'llm', prompt: '是否核验' }] }), /模型判据仅允许/);
  assert.throws(() => writeCondition({ kind: 'llm', prompt: '  ' }), /模型/);
});

test('model predicate controls are available only in graph-edge condition editors', async () => {
  const { outputFiles } = await build({ entryPoints: [new URL('../orchestration/condition-editor.jsx', import.meta.url).pathname],
    bundle: true, write: false, format: 'esm', external: ['react'] });
  const code = outputFiles[0].text.replace('from "react"', `from ${JSON.stringify(import.meta.resolve('react'))}`);
  const { ConditionEditor } = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);
  const render = props => renderToStaticMarkup(React.createElement(ConditionEditor, { value: '{}', onChange() {}, ...props }));
  assert.match(render({ name: 'condition' }), /<option value="llm">模型判据<\/option>/);
  assert.doesNotMatch(render({ label: '完成条件' }), /<option value="llm">/);
  const negative = render({ name: 'condition', value: '{"none_of":[{"fact":{"field":"ready","op":"exists"}}]}' });
  assert.equal([...negative.matchAll(/<option value="llm">/g)].length, 1);
  const editor = render({ name: 'condition', value: '{"llm":{"prompt":"用户已确认"}}' });
  assert.match(editor, /<textarea[^>]*>用户已确认<\/textarea>/);
  assert.match(editor, /&quot;llm&quot;:\{&quot;prompt&quot;:&quot;用户已确认&quot;\}/);
});

test('form enforces complete values and two combination layers while preserving boolean/number distinction', () => {
  const node = newCondition('fact');
  assert.throws(() => writeCondition(node), /填写字段/);
  Object.assign(node, { field: 'price', op: 'gt', type: 'string', value: '2' });
  assert.throws(() => writeCondition(node), /数字/);
  Object.assign(node, { type: 'number', value: 'true' });
  assert.throws(() => writeCondition(node), /类型/);
  Object.assign(node, { type: 'number', value: '2' });
  assert.equal(writeCondition(node).fact.value, 2);
  node.op = 'in';
  assert.throws(() => writeCondition(node), /数组/);
  const tooDeep = { all_of: [{ any_of: [{ all_of: [{ fact: { field: 'x', op: 'exists' } }] }] }] };
  assert.equal(readCondition(tooDeep), null);
  assert.throws(() => writeCondition({ kind: 'all_of', children: [{ kind: 'any_of', children: [{ kind: 'all_of', children: [newCondition('fact')] }] }] }), /两层/);
});

test('event name and structured attribute conditions round-trip without discarding filters', () => {
  for (const name of ['tool_call', 'route_step', 'recall_hit', 'input_matched', 'channel', 'attempts', 'user_hangup', 'timeout', 'side_effect_unknown', 'human_takeover', 'handoff']) {
    const input = { event: { event: name } };
    const tree = readCondition(input);
    assert.ok(tree, `未识别事件：${name}`);
    assert.deepEqual(writeCondition(tree), input);
    const negated = { not: [input] };
    assert.deepEqual(writeCondition(readCondition(negated)), negated);
  }
  const withAttributes = { event: { event: 'tool_call', attributes: { tool_id: 'lookup', source: 'sandbox' } } };
  assert.deepEqual(writeCondition(readCondition(withAttributes)), withAttributes);
  const explicitEmptyAttributes = { event: { event: 'timeout', attributes: {} } };
  assert.deepEqual(writeCondition(readCondition(explicitEmptyAttributes)), explicitEmptyAttributes);
  for (const input of [{ event: { event: 'tool_call', tool: 'approved' } }, { event: { event: 'future' } }, { state: { metric: 'attempts', op: 'gt', value: 2 } }]) {
    assert.equal(readCondition(input), null);
  }
  for (const input of [
    { state: { metric: 'attempts', window: '24h', op: 'gt', value: 2 } },
    { state: { metric: 'runs', window: 'forever', op: 'eq', value: 0 } },
    { state: { metric: 'attempts', window: 'cycle', op: 'gte', value: 1 } },
  ]) assert.deepEqual(writeCondition(readCondition(input)), input);
  assert.throws(() => writeCondition(newCondition('event')), /事件/);
  assert.throws(() => writeCondition({ kind: 'event', event: 'timeout', attributesText: '{' }), /JSON/);
  assert.throws(() => writeCondition({ kind: 'event', event: 'timeout', attributesText: '[]' }), /对象/);
  assert.throws(() => writeCondition({ ...newCondition('state'), value: '' }), /数字/);
  assert.equal(readCondition({ state: { metric: 'attempts', window: 'session', op: 'gt', value: 2 } }), null);
});

test('numeric between predicates round-trip as inclusive ranges', () => {
  const input = { fact: { field: 'score', op: 'between', value: [1, 3] } };
  assert.deepEqual(writeCondition(readCondition(input)), input);
  assert.equal(readCondition({ fact: { field: 'score', op: 'between', value: [1] } }), null);
  assert.equal(readCondition({ fact: { field: 'score', op: 'between', value: [true, 3] } }), null);
  assert.equal(readCondition({ fact: { field: 'score', op: 'between', value: [3, 1] } }), null);
  assert.throws(() => writeCondition({ kind: 'fact', field: 'score', op: 'between', type: 'number', value: '[3,1]' }), /上限/);
});

test('condition editor exposes cycle windows and numeric range inputs', async () => {
  const { outputFiles } = await build({ entryPoints: [new URL('../orchestration/condition-editor.jsx', import.meta.url).pathname],
    bundle: true, write: false, format: 'esm', external: ['react'] });
  const code = outputFiles[0].text.replace('from "react"', `from ${JSON.stringify(import.meta.resolve('react'))}`);
  const { ConditionEditor } = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);
  const render = value => renderToStaticMarkup(React.createElement(ConditionEditor, { value: JSON.stringify(value), name: 'condition', onChange() {} }));
  const cycle = render({ state: { metric: 'attempts', window: 'cycle', op: 'gt', value: 2 } });
  assert.match(cycle, /本服务周期/);
  const between = render({ fact: { field: 'score', op: 'between', value: [1, 3] } });
  assert.match(between, /最小值/);
  assert.match(between, /最大值/);
});
