import test from 'node:test';
import assert from 'node:assert/strict';
import { projectComparison } from '../orchestration/comparison.js';

const unit = id => ({ unit_id: id, version: 1, load_mode: 'routed',
  entry_ports: [{ port: 'in', requires: [] }], exit_ports: [{ port: 'out', completion: {} }],
  body: { kind: 'say', text: 'hello' }, max_rounds: 2 });
const snapshot = () => ({ units: [unit('a'), unit('b')], orchestration: {
  schema_version: 'unit-graph-v1', kind: 'graph', entry: 'first.in', routing: { mode: 'deterministic' },
  nodes: [{ id: 'first', unit_ref: { unit_id: 'a', version: 1 } }, { id: 'second', unit_ref: { unit_id: 'b', version: 1 } }],
  edges: [{ id: 'go', from: 'first.out', to: 'second.in', condition: {} }, { id: 'end', from: 'second.out', to: 'end', condition: {} }],
} });
const comparison = (before, after, changes, diagnostics = []) => ({ before: { config: before }, after: { config: after }, object_diff: { changes, diagnostics } });

test('comparison uses server object changes and keeps removed ports and edges visible without rewriting snapshots', () => {
  const before = snapshot(), after = snapshot();
  after.units[1].entry_ports = [{ port: 'verified', requires: ['ready'] }];
  after.orchestration.edges[0].to = 'second.verified';
  after.orchestration.edges.reverse();
  const source = comparison(before, after, [
    { object_type: 'entry_port', object_id: 'in', operation: 'removed', path: '$.units[unit_id="b"].entry_ports[port="in"]' },
    { object_type: 'entry_port', object_id: 'verified', operation: 'added', path: '$.units[unit_id="b"].entry_ports[port="verified"]' },
    { object_type: 'edge', object_id: 'go', operation: 'changed', path: '$.orchestration.edges[id="go"].to' },
    { object_type: 'edge_order', object_id: '$', operation: 'priority', path: '$.orchestration.edges', before: ['go', 'end'], after: ['end', 'go'] },
  ]);
  const original = structuredClone(source);
  const model = projectComparison(source);
  const second = model.nodes.find(node => node.localId === 'second');
  assert.deepEqual(second.unit.entry_ports.map(port => port.port), ['verified', 'in']);
  assert.equal(second.comparison.ports.entry_ports.verified.status, 'added');
  assert.equal(second.comparison.ports.entry_ports.in.status, 'removed');
  assert.equal(second.comparison.status, null, 'port-only changes must not collapse into node modification');
  const go = model.edges.find(edge => edge.edgeConfig.id === 'go');
  assert.equal(go.comparison.status, 'changed');
  assert.equal(go.comparison.priority, true);
  assert.equal(go.comparison.beforeOrder, 1);
  assert.equal(go.comparison.afterOrder, 2);
  assert.deepEqual(source, original);
  assert.equal(projectComparison(comparison(before, after, [])).edges.find(edge => edge.edgeConfig.id === 'go').comparison.status, null, 'client must not invent authoritative diff');
});

test('removed nodes and their old ports remain selectable and removed edges use the union node identities', () => {
  const before = snapshot(), after = snapshot();
  after.orchestration.nodes.pop();
  after.orchestration.edges = [];
  after.units.pop();
  const model = projectComparison(comparison(before, after, [
    { object_type: 'node', object_id: 'second', operation: 'removed', path: '$.orchestration.nodes[id="second"]' },
    { object_type: 'unit', object_id: 'b', operation: 'removed', path: '$.units[unit_id="b"]' },
    { object_type: 'edge', object_id: 'go', operation: 'removed', path: '$.orchestration.edges[id="go"]' },
    { object_type: 'edge', object_id: 'end', operation: 'removed', path: '$.orchestration.edges[id="end"]' },
  ]));
  const second = model.nodes.find(node => node.localId === 'second');
  assert.equal(second.comparison.status, 'removed');
  assert.equal(second.comparison.ports.entry_ports.in.status, 'removed');
  assert.equal(model.edges.find(edge => edge.edgeConfig.id === 'go').target, second.id);
  assert.equal(model.edges.find(edge => edge.edgeConfig.id === 'go').comparison.status, 'removed');
});

test('nested layers distinguish repeated edge IDs and remain navigable when the target version removed the layer', () => {
  const before = snapshot(), after = snapshot();
  for (const value of [before, after]) {
    value.units[0].entry_ports[0].goto = 'nested.in';
    value.units[0].body = { kind: 'graph', nodes: [{ id: 'nested', unit_ref: { unit_id: 'b', version: 1 } }],
      edges: [{ id: 'go', from: 'nested.out', to: 'self.out', condition: {} }] };
  }
  after.units[0].body = { kind: 'say', text: 'replaced' };
  const changes = [{ object_type: 'unit', object_id: 'a', operation: 'changed', path: '$.units[unit_id="a"].body', before: before.units[0].body, after: after.units[0].body }];
  const root = projectComparison(comparison(before, after, changes));
  assert.equal(root.edges.find(edge => edge.edgeConfig.id === 'go').comparison.status, null);
  const nested = projectComparison(comparison(before, after, changes), ['first']);
  assert.equal(nested.nodes.find(node => node.localId === 'nested').comparison.status, 'removed');
  assert.equal(nested.edges[0].comparison.status, 'removed');
  assert.equal(nested.breadcrumbs.length, 2);
});

test('ambiguous object identities preserve the server diagnostic and skip unsupported highlighting', () => {
  const value = snapshot();
  value.units[0].entry_ports.push({ port: 'in', requires: ['x'] });
  const model = projectComparison(comparison(value, value, [
    { object_type: 'unit', object_id: 'a', operation: 'positional', path: '$.units[unit_id="a"].entry_ports[1].requires' },
  ], [{ path: '$.units[unit_id="a"].entry_ports', message: '标识重复，仅按位置比较' }]));
  assert.ok(model.issues.some(issue => issue.message.includes('标识重复')));
  assert.equal(model.nodes.find(node => node.localId === 'first').comparison.status, null);
  assert.equal(Object.keys(model.nodes.find(node => node.localId === 'first').comparison.ports.entry_ports).length, 0);
});

test('legacy candidate edges do not become changes when only the Unit registry order differs', () => {
  const before = { units: [unit('a'), unit('b')] };
  before.units[0].exit_ports[0].exits = ['b.in'];
  const after = structuredClone(before);
  after.units.reverse();
  const model = projectComparison(comparison(before, after, []));
  assert.equal(model.edges.length, 1);
  assert.equal(model.edges[0].comparison.status, null);
  assert.equal(model.edges[0].comparison.priority, false);
});
