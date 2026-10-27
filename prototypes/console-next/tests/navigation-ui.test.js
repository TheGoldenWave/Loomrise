import test from 'node:test';
import assert from 'node:assert/strict';
import { createStore } from '../store.js';
import { pendingItems, readiness } from '../domain.js';
import { renderShell, routes } from '../views/shell.js';
import { renderAgents, renderOverview, renderConfiguration } from '../views/editor.js';
import { renderSettings } from '../views/config-pages.js';

function context(store) {
  const state = store.state;
  const current = store.currentAgent();
  const snapshot = current?.versions.find(item => item.id === state.ui.previewVersionId);
  const agent = snapshot ? { ...current, config: snapshot.config, revision: snapshot.revision } : current;
  return { state, agent, ready: readiness(agent, state.connections), readonly: store.readonly() };
}

const navigation = html => html.match(/<nav class="sidebar-nav"[^>]*>([\s\S]*?)<\/nav>/)?.[1] || '';
const navigationLabels = html => [...navigation(html).matchAll(/class="nav-link"[^>]*>[\s\S]*?<span>([^<]+)<\/span>/g)].map(match => match[1]);

test('两平面的展开收起入口位于顶栏标题之前，状态和无障碍名称同步', () => {
  const store = createStore();
  for (const page of ['agents', 'overview']) {
    store.dispatch('navigate', { page });
    for (const collapsed of [false, true]) {
      if (store.state.ui.sidebarCollapsed !== collapsed) store.dispatch('toggle-sidebar');
      const html = renderShell(context(store), '');
      const topbar = html.match(/<header class="topbar">([\s\S]*?)<\/header>/)?.[1] || '';
      const trigger = topbar.match(/<button[^>]*data-action="toggle-sidebar"[^>]*>/)?.[0] || '';
      assert.match(html, new RegExp(`data-sidebar-collapsed="${collapsed}"`));
      assert.match(trigger, new RegExp(`aria-label="${collapsed ? '展开侧边栏' : '收起侧边栏'}"`));
      assert.match(trigger, new RegExp(`aria-expanded="${!collapsed}"`));
      assert.match(trigger, /aria-controls="app-navigation"/);
      assert.ok(topbar.indexOf('data-action="toggle-sidebar"') < topbar.indexOf('class="breadcrumb"'));
      assert.match(topbar, /data-action="toggle-nav"[^>]*aria-label="打开导航"/);
      assert.match(html, /aria-label="关闭导航"/);
    }
  }
});

test('进入专家后仅展示七个专家入口与专家设置，旧页面保留入口归属', () => {
  const store = createStore();
  const expected = ['首页', '知识库', '红线', '业务办理', '对话流程', '测试', '上线', '专家设置'];
  for (const page of ['overview', 'knowledge', 'redlines', 'business', 'flow', 'test', 'versions', 'settings', 'widget', 'runs']) {
    store.dispatch('navigate', { page });
    const html = renderShell(context(store), '');
    assert.deepEqual(navigationLabels(html), expected);
    assert.equal((navigation(html).match(/aria-current="page"/g) || []).length, 1);
    assert.match(html, /data-scope="agent"/);
    assert.match(html, /class="nav-link workspace-back"[^>]*data-page="agents"/);
    assert.match(html, /aria-label="当前配置上下文"/);
    assert.doesNotMatch(navigation(html), /data-page="agents"|data-page="materials"|data-page="connections"|data-page="deployment"/);
    assert.equal((html.match(/data-environment="local-prototype"/g) || []).length, 1);
    assert.doesNotMatch(html, /配置深度|业务概览|详细配置|保存草稿/);
  }
  assert.ok(routes.some(item => item.id === 'inbox' && item.scoped));
  assert.ok(routes.some(item => item.id === 'settings' && item.scoped));
});

test('工作区与创建页独立于上次选中的专家，不泄露专家配置上下文', () => {
  const store = createStore();
  const selectedId = store.currentAgent().id;
  for (const page of ['agents', 'create', 'materials', 'connections', 'deployment']) {
    store.dispatch('navigate', { page });
    // 即使旧记录残留临时面板，工作区也不展示专家界面。
    store.state.ui.pendingOpen = true;
    store.state.ui.mobilePanel = 'trial';
    const html = renderShell(context(store), '', '<p>专家试用内容</p>');
    assert.equal(store.state.selectedAgentId, selectedId);
    assert.deepEqual(navigationLabels(html), ['专家列表', '物料库', '模型连接', '部署与维护']);
    assert.equal((navigation(html).match(/aria-current="page"/g) || []).length, 1);
    assert.match(html, /data-scope="workspace"/);
    assert.doesNotMatch(html, /当前专家|切换当前专家|当前配置上下文|待处理队列|data-action="pending-toggle"|data-action="open-trial"|专家试用内容|data-mobile-panel="side"/);
    assert.doesNotMatch(navigation(html), /data-page="knowledge"|data-page="settings"/);
  }
});

test('专家列表名称与进入按钮都进入专家，去处理是单独的快捷动作', () => {
  const store = createStore();
  const html = renderAgents(context(store));
  const id = store.currentAgent().id;
  assert.match(html, new RegExp(`data-action="select-agent" data-id="${id}"[^>]*aria-label="进入`));
  assert.match(html, new RegExp(`data-action="select-agent" data-id="${id}"[^>]*>进入</button>`));
  assert.match(html, /选择一个专家，进入它的知识、配置与测试/);
});

test('旧路由仍可查看，默认不占用新的一级位置', () => {
  const store = createStore();
  store.dispatch('navigate', { page: 'configuration', section: 'outcome' });
  assert.equal(store.state.ui.section, 'outcome');
  let html = renderShell(context(store), '');
  assert.match(html, /data-page="settings" aria-current="page"/);
  assert.doesNotMatch(html, /class="nav-subgroup"/);
  store.dispatch('navigate', { page: 'widget' });
  html = renderShell(context(store), '');
  assert.match(html, /data-page="versions" aria-current="page"/);
});

test('新专家落首页三步空态，填资料后单个待处理与列表一致', () => {
  const store = createStore();
  store.dispatch('create', { name: '空草稿' });
  let html = renderOverview(context(store));
  assert.match(html, /放资料[\s\S]*核对[\s\S]*试一试/);
  assert.match(html, /data-batch-drop/);
  store.dispatch('load-demo-sources');
  store.dispatch('update-config', { path: 'model.budget', value: 0 });
  html = renderOverview(context(store));
  const first = pendingItems(store.currentAgent(), store.state).find(item => item.level === 'block');
  assert.match(html, /现在先做/);
  assert.match(html, new RegExp(first.text));
  assert.match(renderAgents(context(store)), new RegExp(first.text));
  assert.equal((html.match(/class="next-step/g) || []).length, 1);
});

test('历史只读首页引导返回草稿且旧配置可追溯', () => {
  const store = createStore();
  store.state.ui.previewVersionId = 'v1';
  store.state.ui.page = 'overview';
  const html = renderOverview(context(store));
  assert.match(html, /正在查看冻结版本/);
  assert.match(html, /返回可编辑草稿/);
  assert.doesNotMatch(html.match(/<section class="next-step[\s\S]*?<\/section>/)?.[0], /data-action="pending-open"/);
  store.state.ui.page = 'configuration';
  store.state.ui.section = 'service';
  assert.match(renderConfiguration(context(store)), /data-bind="goal"[^>]*disabled/);
});

test('配置模块沿用结构化路径缺口，修复后不自动跳模块', () => {
  const store = createStore();
  store.dispatch('create', { name: '定位保持' });
  store.state.ui.section = '';
  store.dispatch('navigate', { page: 'configuration' });
  const selected = store.state.ui.section;
  assert.equal(selected, 'knowledge');
  const moduleStatus = renderConfiguration(context(store)).match(/data-module-status="[^"]+"/g) || [];
  assert.equal(moduleStatus.length, 10);
  assert.match(renderConfiguration(context(store)), /data-section="r1-server"/);
  store.dispatch('load-demo-sources');
  assert.equal(store.state.ui.section, selected);
  store.dispatch('set-section', { section: 'model' });
  store.dispatch('update-config', { path: 'model.budget', value: 0 });
  assert.match(renderConfiguration(context(store)), /id="module-model"/);
  assert.ok(pendingItems(store.currentAgent(), store.state).some(item => item.target === 'model.budget' && item.page === 'settings'));
});

test('来源视图和客服应用保持现有中文名称', () => {
  const store = createStore();
  const html = renderAgents(context(store)) + renderOverview(context(store)) + renderSettings(context(store));
  assert.doesNotMatch(html, /网站客服组件|由客服收件箱记录/);
  assert.match(html, /网站小窗/);
  assert.equal(routes.find(item => item.id === 'inbox').label, '会话收件箱');
});
