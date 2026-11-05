import test from 'node:test';
import assert from 'node:assert/strict';
import { locateValidationIssue, projectOrchestration, unitAuxiliaryTargets } from '../orchestration/model.js';
import { overlayForNode, overlayForEdge, overlayLabel } from '../orchestration/overlay.js';
import { createR1ConfigurationWorkspace } from '../r1-configuration.js';

const unit = (id, exits = ['self.done']) => ({ unit_id: id, version: 1, load_mode: 'routed',
  entry_ports: [{ port: 'from_start', requires: [] }], reads: [], writes: [],
  exit_ports: [{ port: 'done', completion: { llm: '已答复' }, exits }],
  on_event: [], fallback: { type: 'clarify' }, max_rounds: 2, body: {},
});
const config = () => ({ persona: { entry_unit_ids: ['U-咨询'] },
  units: [unit('U-咨询', ['U-人工.from_start']), unit('U-人工')],
  g0_gates: [], hard_rules: [], legacy: { retained: true },
});

test('candidate exit projection preserves port identity without inventing execution order or mutating config', () => {
  const value = config(), before = structuredClone(value);
  const graph = projectOrchestration(value);
  assert.equal(graph.nodes.length, 2);
  assert.equal(graph.nodes[0].entry, true);
  assert.equal(graph.edges.length, 1);
  assert.equal(graph.edges[0].entryPort, 'from_start');
  assert.equal(graph.edges[0].sourcePort, 'done');
  assert.match(graph.edges[0].label, /候选出口/);
  assert.equal(graph.edges[0].order, undefined);
  assert.deepEqual(value, before);
});

test('concurrent capabilities stay out of graph and events do not become ordinary edges', () => {
  const value = config();
  value.units.push({ ...unit('U-共情'), load_mode: 'concurrent' });
  value.units[0].on_event = [{ event: 'handoff', goto: 'U-人工', scope: 'self' }];
  const graph = projectOrchestration(value);
  assert.equal(graph.nodes.length, 2);
  assert.equal(graph.concurrent.length, 1);
  assert.equal(graph.events.length, 1);
  assert.equal(graph.edges.length, 1);
});

test('broken intermediate states retain diagnostics and never draw ambiguous or unknown targets', () => {
  for (const units of [null, {}, [null, 1, {}]]) assert.doesNotThrow(() => projectOrchestration({ units }));
  const value = config();
  value.units.push(unit('U-人工'));
  value.units[0].exit_ports[0].exits.push('unknown', 'U-人工.from_start');
  const graph = projectOrchestration(value);
  assert.equal(graph.edges.length, 0);
  assert.ok(graph.issues.some(issue => issue.message.includes('重复')));
  assert.ok(graph.issues.some(issue => issue.path.includes('exits')));
  const nested = config();
  nested.units[0].body = { kind: 'graph', nodes: [] };
  assert.ok(projectOrchestration(nested).issues.some(issue => issue.path.endsWith('.body')));
  assert.equal(nested.units[0].body.kind, 'graph');
});

test('inspector edits update the same shared draft, retain unknown fields and never persist view state', async () => {
  const saved = [];
  const workspace = createR1ConfigurationWorkspace({ client: { async request(action, payload) {
    if (action === 'draft.save') { saved.push(payload); return { revision: 2, config: payload.config }; }
    throw new Error(action);
  } } });
  Object.assign(workspace.state, { agentId: 'expert', status: 'ready', draft: { revision: 1, config: config() }, editorConfig: config() });
  workspace.state.orchestration.selected = 'unit:0';
  workspace.patchUnit(0, { max_rounds: 4, waits: [{ on: 'approval.received', timeoutMs: 120000, timeoutTo: 'end' }] });
  assert.equal(workspace.state.editorConfig.units[0].max_rounds, 4);
  assert.equal(workspace.state.editorConfig.units[0].waits[0].on, 'approval.received');
  assert.equal(workspace.state.draft.config.units[0].max_rounds, 2);
  await workspace.save(workspace.state.editorConfig);
  assert.equal(saved[0].expected_revision, 1);
  assert.deepEqual(saved[0].config.legacy, { retained: true });
  assert.equal(JSON.stringify(saved).includes('unit:0'), false);
  assert.equal(JSON.stringify(saved).includes('position'), false);
  assert.equal(saved[0].config.units[0].waits[0].timeoutTo, 'end');
});

test('inspector cannot overwrite snapshots, busy state, conflicts or malformed JSON input', () => {
  const workspace = createR1ConfigurationWorkspace({ client: {} });
  const state = workspace.state;
  Object.assign(state, { status: 'ready', editorConfig: config() });
  for (const block of [{ selectedCandidate: {} }, { readOnlySnapshot: {} }, { busy: true }, { status: 'conflict' }, { jsonErrors: { units: 'syntax' } }]) {
    Object.assign(state, { selectedCandidate: null, readOnlySnapshot: null, busy: false, status: 'ready', jsonErrors: {}, jsonInputs: { units: 'retained' } }, block);
    workspace.patchUnit(0, { max_rounds: 9 });
    assert.equal(state.editorConfig.units[0].max_rounds, 2);
    assert.equal(state.jsonInputs.units, 'retained');
  }
});

function versionedConfig() {
  const parent = unit('U-package');
  parent.entry_ports[0].goto = 'child.from_start';
  parent.body = { kind: 'graph', routing: { mode: 'hybrid' }, nodes: [{ id: 'child', unit_ref: { unit_id: 'U-child', version: 1 } }],
    edges: [{ id: 'child-end', from: 'child.done', to: 'self.done', condition: {} }] };
  return { units: [parent, unit('U-child')], orchestration: { schema_version: 'unit-graph-v1', kind: 'graph',
    routing: { mode: 'deterministic' }, entry: 'package.from_start', nodes: [{ id: 'package', unit_ref: { unit_id: 'U-package', version: 1 } }],
    edges: [{ id: 'finish', from: 'package.done', to: 'end', condition: {} }], on_event: [] } };
}

test('tool inspector updates only the reference in the shared draft and preserves metadata', async () => {
  const value = versionedConfig();
  value.units[1].body = { kind: 'tool', tool_ref: { tool_id: 'lookup', version: '1', note: 'keep' }, arguments: { query: '原参数' }, extension: { keep: true } };
  const saved = [];
  const workspace = createR1ConfigurationWorkspace({ client: { async request(action, payload) {
    assert.equal(action, 'draft.save'); saved.push(payload); return { revision: 2, config: payload.config };
  } } });
  Object.assign(workspace.state, { agentId: 'expert', status: 'ready', draft: { revision: 1, config: structuredClone(value) }, editorConfig: value });
  const body = { ...value.units[1].body, tool_ref: { ...value.units[1].body.tool_ref, tool_id: 'lookup-new', version: '2' } };
  assert.equal(workspace.patchUnit(1, { body }), true);
  assert.deepEqual(workspace.state.editorConfig.units[1].body, body);
  assert.equal(workspace.state.draft.config.units[1].body.tool_ref.version, '1');
  assert.equal(workspace.patchUnit(1, { body: { ...body, arguments: { query: '覆盖' } } }), false);
  assert.equal(workspace.patchUnit(0, { body: { kind: 'tool', tool_ref: { tool_id: 'x', version: '1' } } }), false);
  workspace.state.selectedCandidate = {};
  assert.equal(workspace.patchUnit(1, { body }), false);
  workspace.state.selectedCandidate = null;
  await workspace.save(workspace.state.editorConfig);
  assert.deepEqual(saved[0].config.units[1].body, body);
});

test('versioned graphs project exactly one layer and drill into the same registry Unit', () => {
  const value = versionedConfig(), before = structuredClone(value);
  const root = projectOrchestration(value);
  assert.equal(root.issues.length, 0);
  assert.equal(root.nodes.filter(node => !node.terminal).length, 1);
  assert.equal(root.edges[0].order, 0);
  assert.equal(root.edges[0].candidate, false);
  const child = projectOrchestration(value, ['package']);
  assert.equal(child.issues.length, 0);
  assert.equal(child.nodes[0].unit, value.units[1]);
  assert.equal(child.nodes[0].index, 1);
  assert.equal(child.breadcrumbs.length, 2);
  assert.equal(child.nodes[1].terminal, true);
  assert.equal(child.edges[0].configIndex, 0);
  assert.deepEqual(child.edges[0].layerPath, ['package']);
  assert.equal(child.edges[0].edgeConfig, value.units[0].body.edges[0]);
  assert.deepEqual(child.edgeSources, [{ value: 'child.done', label: 'U-child · done' }]);
  assert.deepEqual(child.edgeTargets, [{ value: 'child.from_start', label: 'U-child · from_start' }, { value: 'self.done', label: '本单元出口 · done' }]);
  assert.deepEqual(value, before);
});

test('validation paths resolve to root and nested graph objects without guessing unknown paths', () => {
  const value = versionedConfig();
  assert.deepEqual(locateValidationIssue(value, '$.orchestration.edges[0].condition'), {
    layerPath: [], kind: 'edge', configIndex: 0, fieldPath: '$.orchestration.edges[0].condition',
  });
  assert.deepEqual(locateValidationIssue(value, '$.units[0].body.edges[0].condition'), {
    layerPath: ['package'], kind: 'edge', configIndex: 0, fieldPath: '$.units[0].body.edges[0].condition',
  });
  assert.deepEqual(locateValidationIssue(value, '$.units[0].body.nodes[0].unit_ref'), {
    layerPath: ['package'], kind: 'node', localId: 'child', configIndex: 0, unitIndex: 1,
    fieldPath: '$.units[0].body.nodes[0].unit_ref',
  });
  assert.equal(locateValidationIssue(value, '$.unknown[0].field'), null);
});

test('validation paths resolve Unit port issues to the shared registry Unit', () => {
  const value = versionedConfig();
  assert.deepEqual(locateValidationIssue(value, '$.units[1].entry_ports[0].requires[0]'), {
    layerPath: ['package'], kind: 'node', localId: 'child', configIndex: 0, unitIndex: 1,
    fieldPath: '$.units[1].entry_ports[0].requires[0]', portKind: 'entry_ports', portIndex: 0, portField: 'requires',
  });
});

test('validation locator refuses ambiguous Unit occurrences instead of selecting the first graph node', () => {
  const value = versionedConfig();
  value.orchestration.nodes.push({ id: 'package-copy', unit_ref: { unit_id: 'U-package', version: 1 } });
  assert.equal(locateValidationIssue(value, '$.units[0].entry_ports[0].requires'), null);
});

test('Unit auxiliary targets follow local graph entries and own exits only', () => {
  const value = versionedConfig();
  const parent = value.units[0];
  parent.exit_ports.push({ port: 'handoff', completion: { deterministic: {} }, exits: [] });
  const graphTargets = unitAuxiliaryTargets(value, parent);
  assert.deepEqual(graphTargets, [
    { value: 'child.from_start', label: 'U-child · from_start' },
    { value: 'self.done', label: 'U-package · done' },
    { value: 'self.handoff', label: 'U-package · handoff' },
  ]);
  assert.deepEqual(unitAuxiliaryTargets(value, value.units[1]), [
    { value: 'self.done', label: 'U-child · done' },
  ]);
});

test('Unit auxiliary targets omit ambiguous nodes, ports and stale registry versions', () => {
  const duplicateNode = versionedConfig();
  duplicateNode.units[0].body.nodes.push(structuredClone(duplicateNode.units[0].body.nodes[0]));
  assert.deepEqual(unitAuxiliaryTargets(duplicateNode, duplicateNode.units[0]), [
    { value: 'self.done', label: 'U-package · done' },
  ]);

  const duplicatePort = versionedConfig();
  duplicatePort.units[1].entry_ports.push({ port: 'from_start', requires: [] });
  duplicatePort.units[0].exit_ports.push({ port: 'handoff', completion: { deterministic: {} }, exits: [] });
  duplicatePort.units[0].exit_ports.push({ port: 'handoff', completion: { deterministic: {} }, exits: [] });
  assert.deepEqual(unitAuxiliaryTargets(duplicatePort, duplicatePort.units[0]), [
    { value: 'self.done', label: 'U-package · done' },
  ]);

  const staleReference = versionedConfig();
  staleReference.units[0].body.nodes[0].unit_ref.version = 2;
  assert.deepEqual(unitAuxiliaryTargets(staleReference, staleReference.units[0]), [
    { value: 'self.done', label: 'U-package · done' },
  ]);
});

test('versioned edge projection includes a read-only condition summary', () => {
  const value = versionedConfig();
  value.orchestration.edges[0].condition = { fact: { field: 'verified', op: 'eq', value: true } };
  const before = structuredClone(value);
  assert.match(projectOrchestration(value).edges[0].label, /verified = true/);
  assert.deepEqual(value, before);
});

test('graph edge inspector writes contract fields through exact nested paths and reorders priority', async () => {
  const saved = [];
  const initial = versionedConfig();
  initial.orchestration.edges.push({ id: 'finish-later', from: 'package.done', to: 'end', condition: {} });
  initial.unknown = { retained: true };
  const workspace = createR1ConfigurationWorkspace({ client: { async request(action, payload) {
    if (action === 'draft.save') { saved.push(payload); return { revision: 2, config: payload.config }; }
    throw new Error(action);
  } } });
  Object.assign(workspace.state, { agentId: 'expert', status: 'ready', draft: { revision: 1, config: initial }, editorConfig: structuredClone(initial) });

  assert.equal(workspace.patchGraphEdge(['package'], 0, { to: 'self.done', condition: { fact: { field: 'ready', op: 'eq', value: true } } }), true);
  assert.equal(workspace.patchGraphEdge(['removed'], 0, { id: 'bad' }), false);
  assert.equal(workspace.patchGraphEdge(['package'], 0, { position: { x: 1, y: 2 } }), false);
  assert.equal(workspace.patchGraphEdge([], 0, { max_rounds: 2, counter: 'attempts', exit: 'end', window: 'cycle' }), true);
  assert.equal(workspace.moveGraphEdge([], 0, 1), true);
  assert.equal(workspace.moveGraphEdge([], 1, 1), false);
  assert.equal(workspace.moveGraphEdge([], -1, 1), false);
  assert.equal(workspace.moveGraphEdge([], 2, -1), false);

  const config = workspace.state.editorConfig;
  assert.equal(config.orchestration.edges[0].id, 'finish-later');
  assert.equal(config.units[0].body.edges[0].to, 'self.done');
  assert.deepEqual(config.units[0].body.edges[0].condition, { fact: { field: 'ready', op: 'eq', value: true } });
  assert.deepEqual(config.unknown, { retained: true });
  await workspace.save(config);
  assert.deepEqual(saved[0].config.unknown, { retained: true });
  assert.equal(JSON.stringify(saved[0].config).includes('position'), false);
});

test('graph edge mutation is blocked for snapshots, busy state, conflicts and malformed source fields', () => {
  const workspace = createR1ConfigurationWorkspace({ client: {} });
  const state = workspace.state;
  Object.assign(state, { status: 'ready', editorConfig: versionedConfig() });
  for (const block of [{ selectedCandidate: {} }, { readOnlySnapshot: {} }, { busy: true }, { status: 'conflict' }, { jsonErrors: { units: 'syntax' } }]) {
    Object.assign(state, { selectedCandidate: null, readOnlySnapshot: null, busy: false, status: 'ready', jsonErrors: {} }, block);
    assert.equal(workspace.patchGraphEdge([], 0, { to: 'end' }), false);
    assert.equal(workspace.moveGraphEdge([], 0, 1), false);
    assert.equal(workspace.addGraphEdge([], { id: 'new', from: 'package.done', to: 'end', condition: {} }), false);
    assert.equal(workspace.removeGraphEdge([], 0, 'finish'), false);
  }
});

test('adding and removing nested edges retains contracts and undo refuses intervening edge edits', () => {
  const workspace = createR1ConfigurationWorkspace({ client: {} });
  Object.assign(workspace.state, { status: 'ready', editorConfig: versionedConfig() });
  const path = ['package'];
  const edge = { id: 'alternate', from: 'child.done', to: 'self.done', condition: { fact: { field: 'ready', op: 'eq', value: true } } };
  assert.equal(workspace.addGraphEdge(path, edge), true);
  assert.equal(workspace.addGraphEdge(path, edge), false);
  assert.equal(workspace.addGraphEdge(path, { ...edge, id: 'escape', to: 'end' }), false);
  assert.equal(workspace.addGraphEdge(path, { ...edge, id: 'cross', to: 'package.child.from_start' }), false);
  assert.equal(workspace.addGraphEdge(['missing'], { ...edge, id: 'another' }), false);
  assert.equal(workspace.state.editorConfig.units[0].body.edges.length, 2);
  assert.equal(workspace.removeGraphEdge(path, 1, 'wrong-id'), false);
  assert.equal(workspace.removeGraphEdge(path, 1, 'alternate'), true);
  assert.equal(workspace.restoreGraphEdge(), true);
  assert.deepEqual(workspace.state.editorConfig.units[0].body.edges[1], edge);
  assert.equal(workspace.restoreGraphEdge(), false);
  assert.equal(workspace.removeGraphEdge(path, 1, 'alternate'), true);
  workspace.patchGraphEdge(path, 0, { condition: { fact: { field: 'verified', op: 'eq', value: true } } });
  assert.equal(workspace.restoreGraphEdge(), false);
  assert.equal(workspace.state.editorConfig.units[0].body.edges.length, 1);
  assert.equal(workspace.state.editorConfig.units[0].body.edges[0].condition.fact.field, 'verified');
});

test('waits appear as separate timeout overlays and resolve only within the current layer', () => {
  const value = versionedConfig();
  value.units[0].waits = [{ on: 'approval.received', timeoutMs: 120000, timeoutTo: 'end' }];
  value.units[1].waits = [{ on: 'approval.received', timeoutTo: 'self.done' }];
  const root = projectOrchestration(value);
  assert.equal(root.waitEdges.length, 1);
  assert.equal(root.waitEdges[0].wait, true);
  assert.match(root.waitEdges[0].label, /超时 ≤120000ms → end/);
  assert.equal(root.edges[0].candidate, false);
  assert.equal(root.waitEdges[0].candidate, undefined);

  const nested = projectOrchestration(value, ['package']);
  assert.equal(nested.waitEdges.length, 1);
  assert.match(nested.waitEdges[0].label, /超时 → self.done/);
  value.units[1].waits[0].timeoutTo = 'missing';
  const broken = projectOrchestration(value, ['package']);
  assert.equal(broken.waitEdges.length, 0);
  assert.ok(broken.issues.some(issue => issue.path.endsWith('.waits[0].timeoutTo')));
});

test('closed-set advisories are mode-specific, non-blocking and exclude concurrent units', () => {
  const makeWideGraph = (mode, count) => {
    const value = versionedConfig();
    value.orchestration.routing.mode = mode;
    for (let index = 0; index < count; index++) {
      const id = `target-${index}`;
      value.units.push(unit(id));
      value.orchestration.nodes.push({ id, unit_ref: { unit_id: id, version: 1 } });
      value.orchestration.edges.push({ id: `route-${index}`, from: 'package.done', to: `${id}.from_start`, condition: {} });
    }
    value.units.push({ ...unit('concurrent-helper'), load_mode: 'concurrent' });
    return value;
  };
  const deterministic = projectOrchestration(makeWideGraph('deterministic', 9));
  assert.equal(deterministic.advisories.length, 1);
  assert.equal(deterministic.advisories[0].level, 'notice');
  assert.equal(deterministic.advisories[0].closedSetSize, 10);
  assert.equal(deterministic.advisories[0].key, 'closed-set:[]');
  assert.equal(deterministic.issues.length, 0);
  assert.equal(deterministic.concurrent.length, 1);

  const llmNotice = projectOrchestration(makeWideGraph('llm', 6));
  assert.equal(llmNotice.advisories[0].level, 'notice');
  const llmStrong = projectOrchestration(makeWideGraph('llm', 9));
  assert.equal(llmStrong.advisories[0].level, 'strong');
  const hybrid = projectOrchestration(makeWideGraph('hybrid', 6));
  assert.match(hybrid.advisories[0].message, /筛前闭集/);
});

test('closed-set advisory identity follows the graph layer rather than array position', () => {
  const value = versionedConfig();
  value.orchestration.routing.mode = 'llm';
  for (let index = 0; index < 6; index++) {
    const id = `target-${index}`;
    value.units.push(unit(id));
    value.orchestration.nodes.push({ id, unit_ref: { unit_id: id, version: 1 } });
    value.orchestration.edges.push({ id: `route-${index}`, from: 'package.done', to: `${id}.from_start`, condition: {} });
  }
  const root = projectOrchestration(value);
  assert.equal(root.advisories[0].key, 'closed-set:[]');
});

test('run overlay keeps nested node identities and hides unmeasured timing and small-sample percentages', () => {
  const aggregate = {
    sample_count: 40, low_sample: false,
    termination_targets: { '["parent","package"]': 1 },
    nodes: {
      '["parent","package"]': { entered: 1, dwell_ms: 237, dwell_sample_count: 1, percentage: null, low_sample: true },
      '["package"]': { entered: 40, dwell_ms: 1200, dwell_sample_count: 2, percentage: 100, low_sample: false },
    },
    edges: { '["parent","to-child"]': { traversed: 1, percentage: null, low_sample: true } },
  };
  const node = { localId: 'package', unit: { unit_id: 'U-package' } };
  const edge = { edgeConfig: { id: 'to-child' } };
  assert.deepEqual(overlayForNode(node, aggregate, ['parent']), {
    ...aggregate.nodes['["parent","package"]'], terminated: 1,
  });
  assert.deepEqual(overlayForEdge(edge, aggregate, ['parent']), aggregate.edges['["parent","to-child"]']);
  assert.equal(overlayLabel(overlayForNode(node, aggregate, ['parent']), aggregate), '进入 1');
  assert.equal(overlayLabel(overlayForNode(node, aggregate), aggregate), '进入 40 · 100%');
  assert.equal(overlayLabel(overlayForNode(node, aggregate, ['parent']), aggregate, 'detail'), '进入 1 · 执行 237ms (n=1) · 终止 1');
  assert.equal(overlayLabel(overlayForNode(node, aggregate), aggregate, 'detail'), '进入 40 · 执行 1.2s (n=2) · 100%');
  assert.equal(overlayLabel(overlayForEdge(edge, aggregate, ['parent']), aggregate), '经过 1');
  assert.equal(overlayForEdge(edge, aggregate), null);
});

test('versioned projection rejects stale references, ambiguous instances and cross-layer edges', () => {
  const value = versionedConfig();
  value.orchestration.nodes[0].unit_ref.version = 2;
  assert.equal(projectOrchestration(value).edges.length, 0);
  value.orchestration.nodes[0].unit_ref.version = 1;
  value.orchestration.nodes.push(structuredClone(value.orchestration.nodes[0]));
  assert.equal(projectOrchestration(value).edges.length, 0);
  value.orchestration.nodes.pop();
  value.orchestration.edges[0].to = 'package.child.from_start';
  assert.equal(projectOrchestration(value).edges.length, 0);
  value.orchestration.schema_version = 'unknown';
  const unknown = projectOrchestration(value);
  assert.equal(unknown.nodes.length, 0);
  assert.ok(unknown.issues.length);
});

test('drill paths fail visibly when removed or cyclic instead of rendering another layer', () => {
  const value = versionedConfig();
  assert.ok(projectOrchestration(value, ['missing']).issues.length);
  value.units[0].body.nodes[0].unit_ref.unit_id = 'U-package';
  assert.ok(projectOrchestration(value, ['package', 'child']).issues.length);
});
