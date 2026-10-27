import test from 'node:test';
import assert from 'node:assert/strict';
import { createStore } from '../store.js';
import { createNavigationHistory, navigationHash } from '../navigation.js';

const pages = ['agents', 'create', 'materials', 'connections', 'deployment', 'overview', 'knowledge', 'redlines', 'business', 'flow', 'test', 'versions', 'settings', 'configuration'];

function browser(store, hash = '#/agents') {
  const location = { hash };
  const entries = [hash];
  const writes = [];
  let index = 0;
  const history = {
    replaceState(_state, _title, value) { entries[index] = value; location.hash = value; writes.push(['replace', value]); },
    pushState(_state, _title, value) { entries.splice(index + 1); entries.push(value); index += 1; location.hash = value; writes.push(['push', value]); },
  };
  const navigation = createNavigationHistory({ store, location, history, pages });
  store.subscribe(navigation.sync);
  navigation.restore();
  return {
    location, writes, entries, navigation,
    back() { index = Math.max(0, index - 1); location.hash = entries[index]; navigation.restore(); },
    forward() { index = Math.min(entries.length - 1, index + 1); location.hash = entries[index]; navigation.restore(); },
  };
}

test('工作区地址不携带专家；旧地址规范化不会切换所选专家', () => {
  const store = createStore();
  const original = store.currentAgent().id;
  store.dispatch('create', { name: '另一位专家' });
  const selected = store.currentAgent().id;
  const app = browser(store, `#/materials?agent=${original}`);
  assert.equal(store.state.ui.page, 'materials');
  assert.equal(store.state.selectedAgentId, selected);
  assert.equal(app.location.hash, '#/materials');
  assert.deepEqual(app.writes, [['replace', '#/materials']]);
  for (const page of ['agents', 'create', 'connections', 'deployment']) {
    store.dispatch('navigate', { page });
    assert.equal(app.location.hash, `#/${page}`);
  }
});

test('列表进入专家与页间导航新增历史，普通编辑不新增，前进后退恢复层级', () => {
  const store = createStore();
  const id = store.currentAgent().id;
  const app = browser(store);
  store.dispatch('select-agent', { id });
  assert.equal(app.location.hash, `#/overview?agent=${id}`);
  store.dispatch('update-config', { path: 'greeting', value: '保留这段草稿' });
  store.dispatch('dismiss-toast');
  assert.equal(app.writes.length, 1);
  store.dispatch('navigate', { page: 'knowledge' });
  assert.equal(app.location.hash, `#/knowledge?agent=${id}`);
  assert.equal(app.writes.length, 2);
  app.back();
  assert.equal(store.state.ui.page, 'overview');
  app.back();
  assert.equal(store.state.ui.page, 'agents');
  assert.equal(store.state.selectedAgentId, id);
  assert.equal(store.currentAgent().config.greeting, '保留这段草稿');
  app.forward();
  assert.equal(store.state.ui.page, 'overview');
  app.forward();
  assert.equal(store.state.ui.page, 'knowledge');
  assert.equal(app.writes.length, 2);
  assert.equal(app.entries.length, 3);
});

test('侧栏展开收起不新增历史，页面前进后退不重置桌面偏好', () => {
  const store = createStore();
  const id = store.currentAgent().id;
  const app = browser(store, `#/overview?agent=${id}`);
  for (const action of ['toggle-sidebar', 'toggle-sidebar', 'toggle-nav', 'toggle-nav']) assert.equal(store.dispatch(action).ok, true);
  assert.deepEqual(app.writes, []);
  assert.equal(app.location.hash, `#/overview?agent=${id}`);
  store.dispatch('navigate', { page: 'agents' });
  store.dispatch('toggle-sidebar');
  assert.equal(store.state.ui.sidebarCollapsed, true);
  assert.equal(app.writes.length, 1);
  app.back();
  assert.equal(store.state.ui.page, 'overview');
  assert.equal(store.state.ui.sidebarCollapsed, true);
  assert.equal(app.writes.length, 1);
});

test('专家深链接选择指定专家并恢复设置分节，刷新不会新增历史', () => {
  const store = createStore();
  const first = store.currentAgent().id;
  store.dispatch('create', { name: '链接指向的专家' });
  const second = store.currentAgent().id;
  store.dispatch('select-agent', { id: first });
  const hash = `#/configuration?agent=${second}&section=model`;
  const app = browser(store, hash);
  assert.equal(store.state.selectedAgentId, second);
  assert.equal(store.state.ui.page, 'configuration');
  assert.equal(store.state.ui.section, 'model');
  assert.equal(app.location.hash, hash);
  assert.deepEqual(app.writes, []);
  app.navigation.restore();
  assert.deepEqual(app.writes, []);
  store.dispatch('navigate', { page: 'settings' });
  assert.equal(app.location.hash, `#/settings?agent=${second}`);
});

test('不存在或空专家的深链接回到工作区，不把上次专家显示为链接目标', () => {
  for (const agent of ['missing', '']) {
    const store = createStore();
    const selected = store.currentAgent().id;
    const config = JSON.stringify(store.currentAgent().config);
    const app = browser(store, `#/knowledge?agent=${agent}`);
    assert.equal(store.state.ui.page, 'agents');
    assert.equal(store.state.selectedAgentId, selected);
    assert.match(store.state.ui.toast.text, /专家不存在/);
    assert.equal(app.location.hash, '#/agents');
    assert.deepEqual(app.writes, [['replace', '#/agents']]);
    assert.equal(JSON.stringify(store.currentAgent().config), config);
  }
});

test('新建与处理快捷入口都从工作区进入专家，返回保留专家草稿', () => {
  const store = createStore();
  const app = browser(store);
  store.dispatch('new-agent', { mode: 'manual' });
  assert.equal(app.location.hash, '#/create');
  store.dispatch('create', { name: '新建的专家' });
  const id = store.currentAgent().id;
  assert.equal(app.location.hash, `#/overview?agent=${id}`);
  app.back();
  assert.equal(store.state.ui.page, 'create');
  assert.equal(store.state.selectedAgentId, id);
  store.dispatch('navigate', { page: 'agents' });
  store.dispatch('agent-next', { id });
  assert.notEqual(store.state.ui.page, 'agents');
  assert.match(app.location.hash, new RegExp(`agent=${id}`));
  assert.equal(app.location.hash, navigationHash(store.state));
});
