import test from 'node:test';
import assert from 'node:assert/strict';
import { portRows, serializePortRows } from '../orchestration/ports.js';

test('port form changes interface fields while retaining unknown metadata and input immutability', () => {
  const value = [{ port: 'in', requires: ['phone'], goto: 'child.in', custom: { keep: true } }];
  const before = structuredClone(value);
  const rows = portRows(value, 'entry_ports');
  rows[0].requires = 'phone\nverified\nphone\n';
  rows[0].port = 'verified_entry';
  rows[0].goto = 'child.verified';
  assert.deepEqual(serializePortRows(rows, 'entry_ports', { graph: true }), [{
    port: 'verified_entry', requires: ['phone', 'verified'], goto: 'child.verified', custom: { keep: true },
  }]);
  assert.deepEqual(value, before);
  rows[0].goto = '';
  assert.ok(!Object.hasOwn(serializePortRows(rows, 'entry_ports', { graph: true })[0], 'goto'));
});

test('port completion separates deterministic and model conditions without losing extensions or candidate exits', () => {
  const value = [{ port: 'done', completion: { deterministic: {}, llm: '已核验', custom: false }, exits: ['other.in'], retained: 1 }];
  const rows = portRows(value, 'exit_ports');
  rows[0].deterministic = '{"fact":{"field":"ready","op":"eq","value":true}}';
  rows[0].llmEnabled = false;
  const actual = serializePortRows(rows, 'exit_ports')[0];
  assert.deepEqual(actual.completion, { deterministic: { fact: { field: 'ready', op: 'eq', value: true } }, custom: false });
  assert.deepEqual(actual.exits, ['other.in']);
  assert.equal(actual.retained, 1);
  const noExits = serializePortRows(portRows([{ port: 'done', completion: { deterministic: {} } }], 'exit_ports'), 'exit_ports')[0];
  assert.ok(!Object.hasOwn(noExits, 'exits'));
  assert.equal(value[0].completion.llm, '已核验');
});

test('malformed port drafts keep raw repair path; form rejects duplicates, dotted IDs and invalid conditions', () => {
  for (const value of [null, {}, [null], [{ port: 'in' }], [{ port: 'in', requires: [1] }]]) assert.equal(portRows(value, 'entry_ports'), null);
  for (const value of [[{ port: 'out', completion: null }], [{ port: 'out', completion: { llm: 1 } }]]) assert.equal(portRows(value, 'exit_ports'), null);
  assert.equal(portRows([{ port: 'out', completion: { deterministic: '旧判据' } }], 'exit_ports'), null);
  assert.equal(portRows([{ port: 'legacy.in', requires: [] }], 'entry_ports'), null);
  assert.equal(portRows([{ port: 'in', requires: [' spaced '] }], 'entry_ports'), null);
  const rows = portRows([{ port: 'in', requires: [] }], 'entry_ports');
  assert.throws(() => serializePortRows([...rows, ...rows], 'entry_ports'), /重复/);
  rows[0].port = 'other.in';
  assert.throws(() => serializePortRows(rows, 'entry_ports'), /句点/);
  const exits = portRows([{ port: 'out', completion: { deterministic: {} } }], 'exit_ports');
  exits[0].deterministic = '[]';
  assert.throws(() => serializePortRows(exits, 'exit_ports'), /JSON 对象/);
  exits[0].deterministicEnabled = false;
  assert.throws(() => serializePortRows(exits, 'exit_ports'), /至少需要/);
});
