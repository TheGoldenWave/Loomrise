import test from 'node:test';
import assert from 'node:assert/strict';
import {
  readUnitEventRows, serializeUnitEventRows,
  readUnitWaitRows, serializeUnitWaitRows,
} from '../orchestration/unit-auxiliary.js';

const targets = ['self.done', 'child.from_start'];

test('Unit event rows expose only supported event, scope, and target values', () => {
  const source = [{ event: 'handoff', scope: 'subtree', goto: 'child.from_start', custom: { keep: true } }];
  const rows = readUnitEventRows(source, targets);
  assert.equal(rows[0].event, 'handoff');
  assert.deepEqual(serializeUnitEventRows(rows, targets), source);
  assert.equal(readUnitEventRows([{ event: 'unknown', scope: 'self', goto: 'self.done' }], targets), null);
  assert.equal(readUnitEventRows([{ event: 'timeout', scope: 'global', goto: 'self.done' }], targets), null);
  assert.equal(readUnitEventRows([{ event: 'timeout', scope: 'self', goto: 'missing.port' }], targets), null);
});

test('Unit event rows preserve optional deterministic conditions and reject unsupported trees', () => {
  const source = [{ event: 'timeout', scope: 'self', goto: 'self.done', when: { fact: { field: 'ready', op: 'eq', value: true } } }];
  const rows = readUnitEventRows(source, targets);
  assert.deepEqual(serializeUnitEventRows(rows, targets), source);
  assert.equal(readUnitEventRows([{ ...source[0], when: { llm: { prompt: 'choose' } } }], targets), null);
});

test('Unit wait rows preserve extensions and require timeout target and duration together', () => {
  const source = [{ on: 'approval.received', timeoutMs: 120000, timeoutTo: 'self.done', custom: 'retain' }];
  const rows = readUnitWaitRows(source, targets);
  assert.deepEqual(serializeUnitWaitRows(rows, targets), source);
  assert.throws(() => serializeUnitWaitRows([{ ...rows[0], timeoutTo: '' }], targets), /超时毫秒与去处必须同时填写/);
  assert.throws(() => serializeUnitWaitRows([{ ...rows[0], timeoutMs: '' }], targets), /超时毫秒与去处必须同时填写/);
  assert.equal(readUnitWaitRows([{ on: 'approval.received', timeoutMs: 1 }], targets), null);
  assert.equal(readUnitWaitRows({ on: 'approval.received' }, targets), null);
});

test('empty Unit waits remain empty and simple wait edits do not mutate their source', () => {
  const source = [{ on: 'approval.received' }];
  const rows = readUnitWaitRows(source, targets);
  rows[0].on = 'approval.updated';
  assert.equal(source[0].on, 'approval.received');
  assert.deepEqual(serializeUnitWaitRows(rows, targets), [{ on: 'approval.updated' }]);
  assert.deepEqual(serializeUnitWaitRows([], targets), []);
});
