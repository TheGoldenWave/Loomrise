import test from 'node:test';
import assert from 'node:assert/strict';
import { createStore } from '../store.js';
import { readiness } from '../domain.js';
import { renderShell, routes } from '../views/shell.js';
import { renderAgents, renderOverview, renderConfiguration } from '../views/editor.js';

function context(store) {
  const state = store.state;
  const current = store.currentAgent();
  const snapshot = current.versions.find(item => item.id === state.ui.previewVersionId);
  const agent = snapshot ? { ...current, config: snapshot.config, revision: snapshot.revision } : current;
  return { state, agent, ready: readiness(agent, state.connections), readonly: store.readonly() };
}

test('四组导航保留路由与作用域，概览和配置各自高亮', () => {
  const store = createStore();
  for (const page of ['overview', 'configuration', 'knowledge', 'materials', 'runs', 'versions']) {
    store.dispatch('navigate', { page });
    const html = renderShell(context(store), '');
    assert.deepEqual([...html.matchAll(/class="nav-group-title">([^<]+)/g)].map(match => match[1]), ['配置与资料', '客服应用', '运行与验收', '版本与设置']);
    assert.match(html, new RegExp(`data-page="${page}" aria-current="page"`));
    assert.equal((html.match(/aria-current="page"/g) || []).length, 1);
    assert.equal((html.match(/data-environment="local-prototype"/g) || []).length, 1);
    if (page === 'configuration') assert.match(html, /role="tab" aria-selected="true" data-action="set-depth" data-depth="business"/);
  }
  assert.equal(routes.length, 16);
  assert.equal(routes.find(item => item.id === 'materials').scoped, false);
  assert.equal(routes.find(item => item.id === 'overview').scoped, true);
  assert.equal(routes.find(item => item.id === 'inbox').label, '会话收件箱');
  assert.equal(routes.find(item => item.id === 'widget').label, '网站客服窗');
});

test('概览和配置是专家列表下的二级页面，无专家时不显示子入口', () => {
  const store = createStore();
  store.dispatch('select-agent', { id: store.currentAgent().id });
  assert.equal(store.state.ui.page, 'overview');
  let html = renderShell(context(store), '');
  assert.equal(routes.find(item => item.id === 'overview').parent, 'agents');
  assert.equal(routes.find(item => item.id === 'configuration').parent, 'agents');
  assert.match(html, /class="nav-subgroup"[^>]*data-parent-page="agents"/);
  const nested = html.match(/<div class="nav-subgroup"[\s\S]*?<\/div>/)?.[0];
  assert.match(nested, /data-page="overview" aria-current="page"/);
  assert.match(nested, /data-page="configuration"/);
  assert.match(html, /class="nav-link has-active-child"[^>]*data-page="agents"/);
  assert.match(html, /class="breadcrumb"[^>]*>[\s\S]*?>专家列表<\/button>/);
  store.dispatch('navigate', { page: 'configuration', section: 'outcome' });
  html = renderShell(context(store), '');
  assert.match(html, /data-page="configuration" aria-current="page"/);
  assert.equal(store.state.ui.section, 'outcome');
  const state = { ...store.state, selectedAgentId: null };
  html = renderShell({ state, agent: null, ready: readiness(null), readonly: false }, '');
  assert.doesNotMatch(html, /class="nav-subgroup"/);
  const navigation = html.match(/<nav class="sidebar-nav">[\s\S]*?<\/nav>/)?.[0];
  assert.doesNotMatch(navigation, /data-page="overview"|data-page="configuration"/);
});

test('历史版本的二级入口通过配置深度切换，保留冻结版本只读', () => {
  const store = createStore();
  store.state.ui.previewVersionId = 'v1';
  store.state.ui.page = 'overview';
  const html = renderShell(context(store), '');
  const nested = html.match(/<div class="nav-subgroup"[\s\S]*?<\/div>/)?.[0];
  assert.match(nested, /data-action="set-depth" data-depth="business" data-page="configuration"/);
  store.dispatch('set-depth', { depth: 'business' });
  assert.equal(store.state.ui.previewVersionId, 'v1');
  assert.equal(store.readonly(), true);
  assert.match(renderShell(context(store), ''), /data-page="configuration" aria-current="page"/);
});

test('专家与配置正文沿用网站客服窗、会话收件箱统一术语', () => {
  const store = createStore();
  store.dispatch('set-depth', { depth: 'business' });
  const html = renderAgents(context(store)) + renderOverview(context(store)) + renderConfiguration(context(store));
  assert.doesNotMatch(html, /网站客服组件|由客服收件箱记录/);
  assert.match(html, /网站客服窗/);
  assert.match(html, /由会话收件箱记录/);
});

test('空草稿概览先显示最高优先缺口及唯一主动作，摘要默认折叠', () => {
  const store = createStore();
  store.dispatch('create', { name: '空草稿' });
  const html = renderOverview(context(store));
  assert.match(html, /class="next-step/);
  assert.ok(html.indexOf('当前优先处理') < html.indexOf('服务摘要'));
  const focus = html.match(/<section class="next-step[\s\S]*?<\/section>/)?.[0];
  assert.match(focus, /可用资料/);
  assert.match(focus, /data-page="knowledge"/);
  assert.equal((focus.match(/btn-primary/g) || []).length, 1);
  assert.match(html, /<details class="overview-summary"><summary>服务摘要/);
});

test('十模块显式标状态，默认选必需缺口并保留有效选择', () => {
  const store = createStore();
  store.dispatch('create', { name: '空草稿' });
  store.dispatch('set-depth', { depth: 'business' });
  store.state.ui.section = '';
  store.dispatch('navigate', { page: 'configuration' });
  let html = renderConfiguration(context(store));
  assert.equal((html.match(/data-module-status=/g) || []).length, 10);
  assert.match(html, /id="module-knowledge"/);
  assert.match(html, /data-module-status="missing"/);
  assert.match(html, /data-module-status="optional"/);
  assert.match(html, /data-module-status="pending"/);
  assert.match(html, /data-module-status="usable"/);
  store.dispatch('set-section', { section: 'model' });
  store.dispatch('update-config', { path: 'goal', value: '' });
  html = renderConfiguration(context(store));
  assert.match(html, /id="module-model"/);
  assert.match(html, /data-section="model" aria-current="page"/);
});

test('无效模块在首次定位固化，补齐当前缺口后不跳到下一模块', () => {
  const store = createStore();
  store.dispatch('create', { name: '定位保持' });
  store.state.ui.section = 'removed-module';
  store.dispatch('navigate', { page: 'configuration' });
  assert.equal(store.state.ui.section, 'knowledge');
  const selected = store.state.ui.section;
  store.dispatch('load-demo-sources');
  assert.equal(store.state.ui.section, selected);
  assert.match(renderConfiguration(context(store)), /id="module-knowledge"/);
  store.dispatch('update-config', { path: 'goal', value: '' });
  assert.equal(store.state.ui.section, selected);
  assert.match(renderConfiguration(context(store)), /id="module-knowledge"/);
});

test('载入配置页时固化缺口选择，render 不写入状态或重新挑选模块', () => {
  const store = createStore();
  store.dispatch('create', { name: '恢复定位' });
  const restored = createStore(null, { ...store.state, ui: { ...store.state.ui, page: 'configuration', section: '' } });
  assert.equal(restored.state.ui.section, 'knowledge');
  const before = JSON.stringify(restored.state);
  assert.match(renderConfiguration(context(restored)), /id="module-knowledge"/);
  assert.equal(JSON.stringify(restored.state), before);
  restored.dispatch('load-demo-sources');
  assert.match(renderConfiguration(context(restored)), /id="module-knowledge"/);
  assert.equal(restored.state.ui.section, 'knowledge');
});

test('历史版本可发现全部配置，缺口主动作不引导修改冻结快照', () => {
  const store = createStore();
  store.state.ui.previewVersionId = 'v1';
  store.state.ui.page = 'overview';
  const html = renderOverview(context(store));
  assert.match(html, /正在查看冻结版本/);
  const focus = html.match(/<section class="next-step[\s\S]*?<\/section>/)?.[0];
  assert.match(focus, /返回可编辑草稿/);
  assert.match(focus, /data-action="readonly-toggle"/);
  store.state.ui.depth = 'detailed';
  store.state.ui.section = 'service';
  const config = renderConfiguration(context(store));
  assert.equal((config.match(/data-module-status=/g) || []).length, 10);
  assert.match(config, /data-bind="goal"[^>]*disabled/);
});

test('最高优先配置错误直达对应模块，非配置页缺口不误导到接待模块', () => {
  const store = createStore();
  store.dispatch('create', { name: '预算缺口' });
  store.dispatch('update-config', { path: 'model.budget', value: 0 });
  let focus = renderOverview(context(store)).match(/<section class="next-step[\s\S]*?<\/section>/)?.[0];
  assert.match(focus, /data-section="model"/);
  store.dispatch('update-config', { path: 'model.budget', value: 2000 });
  store.dispatch('update-config', { path: 'widget.bookingUrl', value: 'invalid' });
  focus = renderOverview(context(store)).match(/<section class="next-step[\s\S]*?<\/section>/)?.[0];
  assert.match(focus, /data-page="widget"/);
});
