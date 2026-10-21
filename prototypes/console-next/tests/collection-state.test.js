import test from 'node:test';
import assert from 'node:assert/strict';
import { createStore } from '../store.js';

test('只读状态层拒绝提名与评估，既有集合证据不变', () => {
  const store = createStore();
  const agentId = store.currentAgent().id;
  store.state.runs.push({ id: 'readonly-run', agentId, input: '未知问题', status: 'unknown' });
  store.state.cases.push({ id: 'readonly-case', agentId, input: '未知问题', expected: 'unknown', status: 'reviewed', must: '不补造', forbid: '不承诺' });
  store.state.proposals.push({ id: 'readonly-proposal', agentId, baseRevision: store.currentAgent().revision, status: 'pending', diff: [{ path: 'fallback', after: '待人工核实' }] });
  store.dispatch('readonly-toggle');
  const before = JSON.stringify([store.state.cases, store.state.proposals]);
  for (const [action, id] of [['case-from-run', 'readonly-run'], ['proposal-from-run', 'readonly-run'], ['case-evaluate', 'readonly-case'], ['proposal-evaluate', 'readonly-proposal']]) {
    assert.equal(store.dispatch(action, { id }).ok, false, action);
    assert.equal(JSON.stringify([store.state.cases, store.state.proposals]), before);
  }
});

test('集合详情与表单互斥，返回保留当前集合的检索条件', () => {
  const store = createStore();
  store.state.runs.push({ id: 'run-ui', agentId: store.currentAgent().id, input: '虚构问题' });
  assert.equal(store.dispatch('update-ui', { path: 'collections.runs.query', value: '虚构' }).ok, true);
  assert.equal(store.dispatch('collection-open', { page: 'runs', id: 'run-ui' }).ok, true);
  assert.equal(store.state.ui.collections.runs.detailId, 'run-ui');
  assert.equal(store.dispatch('collection-back', { page: 'runs' }).ok, true);
  assert.equal(store.state.ui.collections.runs.detailId, null);
  assert.equal(store.state.ui.collections.runs.query, '虚构');
  assert.equal(store.dispatch('collection-clear', { page: 'runs' }).ok, true);
  assert.equal(store.state.ui.collections.runs.query, '');
});

test('案例保存成功进入该详情，失败保留表单；取消不修改案例', () => {
  const store = createStore();
  assert.equal(store.dispatch('collection-new', { page: 'cases' }).ok, true);
  assert.equal(store.dispatch('case', { title: '不完整' }).ok, false);
  assert.equal(store.state.ui.collections.cases.form, true);
  assert.equal(store.dispatch('case', { title: '虚构案例', input: '你好', must: '说明范围', forbid: '补造事实', expected: 'unknown' }).ok, true);
  const item = store.state.cases[0];
  assert.equal(store.state.ui.collections.cases.detailId, item.id);
  assert.equal(store.state.ui.collections.cases.form, false);
  store.dispatch('collection-edit', { page: 'cases', id: item.id });
  assert.equal(store.state.ui.caseEdit, item.id);
  const before = JSON.stringify(item);
  store.dispatch('collection-cancel', { page: 'cases' });
  assert.equal(store.state.ui.collections.cases.detailId, item.id);
  assert.equal(JSON.stringify(item), before);
});

test('只读仍能查看与筛选，但不能开始新增或编辑', () => {
  const store = createStore();
  store.dispatch('readonly-toggle');
  assert.equal(store.dispatch('collection-new', { page: 'connections' }).ok, false);
  assert.equal(store.dispatch('case-create').ok, false);
  assert.equal(store.dispatch('proposal-create').ok, false);
  assert.equal(store.dispatch('collection-open', { page: 'connections', id: 'simulation' }).ok, true);
  assert.equal(store.dispatch('update-ui', { path: 'collections.connections.query', value: '脚本' }).ok, true);
  assert.equal(store.dispatch('collection-clear', { page: 'connections' }).ok, true);
});

test('切专家不保留旧集合详情与编辑，不能打开其他专家的记录', () => {
  const store = createStore();
  const previousId = store.currentAgent().id;
  store.state.runs.push({ id: 'run-old', agentId: previousId, input: '旧问题' });
  store.dispatch('collection-open', { page: 'runs', id: 'run-old' });
  store.dispatch('collection-new', { page: 'cases' });
  store.dispatch('create', { name: '另一位虚构专家' });
  assert.equal(store.state.ui.collections.runs.detailId, null);
  assert.equal(store.state.ui.collections.cases.form, false);
  assert.equal(store.state.ui.caseForm, false);
  assert.equal(store.dispatch('collection-open', { page: 'runs', id: 'run-old' }).ok, false);
  assert.equal(store.dispatch('update-ui', { path: 'collections.__proto__.query', value: 'x' }).ok, false);
});

test('知识无匹配恢复仅清筛选，保留类型和资料', () => {
  const store = createStore();
  store.dispatch('source-tab', { tab: 'URL' });
  store.dispatch('update-ui', { path: 'search', value: '不存在' });
  store.dispatch('update-ui', { path: 'sourceFilter', value: 'unavailable' });
  const before = JSON.stringify(store.currentAgent().config.sources);
  assert.equal(store.dispatch('source-clear').ok, true);
  assert.equal(store.state.ui.search, '');
  assert.equal(store.state.ui.sourceFilter, 'all');
  assert.equal(store.state.ui.sourceTab, 'URL');
  assert.equal(JSON.stringify(store.currentAgent().config.sources), before);
});
