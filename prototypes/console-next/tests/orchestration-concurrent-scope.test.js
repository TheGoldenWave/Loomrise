import test from 'node:test';
import assert from 'node:assert/strict';
import { scopeForm, serializeScope } from '../orchestration/concurrent-scope.js';

test('opening and applying a combined loading scope retains both restrictions and metadata', () => {
  const scope = { after: 'A', exclude: ['B'], future: { keep: true } };
  const form = scopeForm(scope);
  assert.equal(form.mode, 'both');
  assert.deepEqual(serializeScope(scope, form), scope);
  assert.deepEqual(scope.exclude, ['B']);
});

test('malformed scope stays raw and complete forms reject missing restrictions', () => {
  for (const scope of [null, [], { after: 4 }, { exclude: 'A' }, { after: '' }, { exclude: [] }]) {
    assert.equal(scopeForm(scope), null);
    assert.throws(() => serializeScope(scope, { mode: 'all' }));
  }
  assert.throws(() => serializeScope(undefined, { mode: 'both', after: 'A', exclude: '' }));
  assert.deepEqual(serializeScope(undefined, { mode: 'exclude', exclude: 'A\nB' }), { exclude: ['A', 'B'] });
  assert.equal(serializeScope({ after: 'A' }, { mode: 'all' }), undefined);
});
