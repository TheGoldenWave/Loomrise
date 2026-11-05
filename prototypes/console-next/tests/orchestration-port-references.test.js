import test from 'node:test';
import assert from 'node:assert/strict';
import { findPortReferences } from '../orchestration/port-references.js';

const fixture = () => ({
  units: [
    { unit_id: 'pack', version: 1, entry_ports: [{ port: 'in', goto: 'child.in' }],
      on_event: [{ goto: 'self.done' }],
      body: { kind: 'graph', nodes: [{ id: 'child', unit_ref: { unit_id: 'atom', version: 1 } }],
        edges: [{ from: 'child.done', to: 'self.done', exit: 'self.done', condition: { text: 'pack.in' } }] } },
    { unit_id: 'atom', version: 1, body: { kind: 'say' }, waits: [{ timeoutTo: 'self.done' }] },
  ],
  orchestration: { schema_version: 'unit-graph-v1', entry: 'a.in',
    nodes: ['a', 'b'].map(id => ({ id, unit_ref: { unit_id: 'pack', version: 1 } })),
    edges: [{ from: 'a.done', to: 'b.in', exit: 'a.in' }],
    on_event: [{ goto: 'b.in' }], fallback: { target: 'a.in' } },
});

test('port impact lists all exact-version instances and own exits without matching condition text', () => {
  const config = fixture(), before = structuredClone(config);
  const entries = findPortReferences(config, 0, 'entry_ports', 'in');
  assert.deepEqual(entries.references.map(ref => ref.path), [
    '$.orchestration.entry', '$.orchestration.edges[0].to', '$.orchestration.edges[0].exit',
    '$.orchestration.on_event[0].goto', '$.orchestration.fallback.target',
  ]);
  const exits = findPortReferences(config, 0, 'exit_ports', 'done');
  assert.deepEqual(exits.references.map(ref => ref.path), [
    '$.orchestration.edges[0].from', '$.units[0].body.edges[0].to',
    '$.units[0].body.edges[0].exit', '$.units[0].on_event[0].goto', '$.units[1].waits[0].timeoutTo',
  ]);
  assert.deepEqual(findPortReferences(config, 1, 'entry_ports', 'in').references.map(ref => ref.path), ['$.units[0].entry_ports[0].goto']);
  assert.deepEqual(config, before);
});

test('port impact includes containing-graph timeout paths once and rejects ambiguous or mismatched references', () => {
  const config = fixture();
  config.orchestration.nodes.push({ id: 'waiter', unit_ref: { unit_id: 'atom', version: 1 } });
  assert.equal(findPortReferences(config, 0, 'exit_ports', 'done').references.filter(ref => ref.path === '$.units[1].waits[0].timeoutTo').length, 1);
  config.orchestration.nodes[0].unit_ref.version = 2;
  assert.deepEqual(findPortReferences(config, 0, 'entry_ports', 'in').references.map(ref => ref.value), ['b.in', 'b.in']);
  config.orchestration.nodes.push({ ...config.orchestration.nodes[1] });
  const duplicateNodes = findPortReferences(config, 0, 'entry_ports', 'in');
  assert.equal(duplicateNodes.references.length, 0);
  assert.match(duplicateNodes.diagnostics.join(''), /歧义/);
  config.units.push(structuredClone(config.units[0]));
  const duplicateUnits = findPortReferences(config, 0, 'entry_ports', 'in');
  assert.equal(duplicateUnits.references.length, 0);
  assert.match(duplicateUnits.diagnostics.join(''), /重复/);
});

test('legacy candidates inspect explicit ports only and unknown schemas never guess', () => {
  const config = { units: [{ unit_id: 'atom', exit_ports: [{ exits: ['atom.in', 'atom', 'self.done'] }] }] };
  assert.equal(findPortReferences(config, 0, 'entry_ports', 'in').references.length, 1);
  assert.equal(findPortReferences(config, 0, 'exit_ports', 'done').references.length, 1);
  config.orchestration = { schema_version: 'future' };
  const result = findPortReferences(config, 0, 'entry_ports', 'in');
  assert.equal(result.references.length, 0);
  assert.match(result.diagnostics.join(''), /未知图版本/);
});
