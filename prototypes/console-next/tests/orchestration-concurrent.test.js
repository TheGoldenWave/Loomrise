import test from 'node:test';
import assert from 'node:assert/strict';
import { projectOrchestration } from '../orchestration/model.js';
import { createR1ConfigurationWorkspace } from '../r1-configuration.js';

const unit = (id, loadMode = 'routed') => ({
  unit_id: id,
  version: 1,
  load_mode: loadMode,
  entry_ports: [{ port: 'from_start', requires: [] }],
  reads: [],
  writes: [],
  exit_ports: [{ port: 'done', completion: { deterministic: {} }, exits: ['self.done'] }],
  on_event: [],
  fallback: { kind: 'clarify' },
  max_rounds: 1,
  body: {},
});

const config = () => ({
  persona: { entry_unit_ids: ['U-start'] },
  units: [unit('U-start'), { ...unit('U-faq', 'concurrent'), load_scope: { after: 'U-start' } }],
  concurrent_config: { max_units: 1, unknown_future_field: { keep: true } },
});

test('concurrent units remain outside routed nodes while exposing group limit and scope summary', () => {
  const value = config();
  const before = structuredClone(value);
  const model = projectOrchestration(value);

  assert.deepEqual(model.nodes.map(node => node.unit.unit_id), ['U-start']);
  assert.deepEqual(model.concurrent.map(node => node.unit.unit_id), ['U-faq']);
  assert.deepEqual(model.concurrentConfig, value.concurrent_config);
  assert.equal(model.concurrent[0].loadScope.mode, 'after');
  assert.equal(model.concurrent[0].loadScope.after, 'U-start');
  assert.deepEqual(value, before);
});

test('concurrent tray edits the shared draft and preserves unknown group fields', () => {
  const value = config();
  const workspace = createR1ConfigurationWorkspace({ client: {} });
  Object.assign(workspace.state, { status: 'ready', editorConfig: structuredClone(value) });

  workspace.updateField('units.1.load_scope', { exclude: ['U-start'] });
  workspace.updateField('concurrent_config.max_units', 2);
  assert.deepEqual(workspace.state.editorConfig.units[1].load_scope, { exclude: ['U-start'] });
  assert.equal(workspace.state.editorConfig.concurrent_config.max_units, 2);
  assert.deepEqual(workspace.state.editorConfig.concurrent_config.unknown_future_field, { keep: true });
});

test('concurrent tray edits respect snapshot, candidate, busy and conflict protection', () => {
  const workspace = createR1ConfigurationWorkspace({ client: {} });
  Object.assign(workspace.state, { status: 'ready', editorConfig: config() });
  for (const block of [
    { selectedCandidate: {} },
    { readOnlySnapshot: {} },
    { busy: true },
    { status: 'conflict' },
  ]) {
    Object.assign(workspace.state, {
      selectedCandidate: null, readOnlySnapshot: null, busy: false, status: 'ready',
      editorConfig: config(),
    }, block);
    assert.equal(workspace.patchUnit(1, { load_scope: { after: 'U-start' } }), false);
    workspace.updateField('concurrent_config.max_units', 9);
    assert.equal(workspace.state.editorConfig.units[1].load_scope.after, 'U-start');
    assert.equal(workspace.state.editorConfig.concurrent_config.max_units, 1);
  }
});

test('scope and port edits apply atomically, and routed Units cannot acquire recall scope', () => {
  const changes = [];
  const workspace = createR1ConfigurationWorkspace({ client: {}, onChange: state => changes.push(structuredClone(state.editorConfig)) });
  Object.assign(workspace.state, { status: 'ready', editorConfig: config() });
  assert.equal(workspace.patchUnit(1, { max_rounds: 4, load_scope: { after: 'U-start', exclude: ['U-start'] } }), true);
  assert.equal(changes.length, 1);
  assert.equal(changes[0].units[1].max_rounds, 4);
  assert.deepEqual(changes[0].units[1].load_scope.exclude, ['U-start']);
  assert.equal(workspace.patchUnit(0, { load_scope: { after: 'U-start' } }), false);
  assert.equal(workspace.patchUnit(1, { load_scope: undefined }), true);
  assert.equal(Object.hasOwn(workspace.state.editorConfig.units[1], 'load_scope'), false);
});
