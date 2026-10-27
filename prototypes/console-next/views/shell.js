import { escapeHtml, attr, icon, badge, formatTime } from '../helpers.js';
import { pendingItems } from '../domain.js';
import { routeScope } from '../navigation.js';

export const routes = [
  { id: 'agents', label: '专家列表', group: '配置与资料', icon: 'agents', scoped: false },
  { id: 'overview', label: '首页', group: '专家', icon: 'agents', scoped: true },
  { id: 'configuration', label: '更多设置', group: '设置', icon: 'settings', scoped: true },
  { id: 'create', label: '新建专家', group: '配置与资料', icon: 'plus', scoped: false, hidden: true },
  { id: 'knowledge', label: '知识库', group: '专家', icon: 'book', scoped: true },
  { id: 'redlines', label: '红线', group: '专家', icon: 'lock', scoped: true },
  { id: 'business', label: '业务办理', group: '专家', icon: 'plug', scoped: true },
  { id: 'flow', label: '对话流程', group: '专家', icon: 'runs', scoped: true },
  { id: 'test', label: '测试', group: '专家', icon: 'cases', scoped: true },
  { id: 'settings', label: '专家设置', group: '设置', icon: 'settings', scoped: true },
  { id: 'materials', label: '物料库', group: '配置与资料', icon: 'book', scoped: false },
  { id: 'inbox', label: '会话收件箱', group: '客服应用', icon: 'inbox', scoped: true },
  { id: 'widget', label: '网站客服窗', group: '客服应用', icon: 'widget', scoped: true },
  { id: 'contact', label: '联系页', group: '客服应用', icon: 'contact', scoped: true },
  { id: 'trial', label: '试用台', group: '运行与验收', icon: 'play', scoped: true },
  { id: 'runs', label: '运行记录', group: '运行与验收', icon: 'runs', scoped: true },
  { id: 'cases', label: '案例与回放', group: '运行与验收', icon: 'cases', scoped: true },
  { id: 'iterations', label: '改进提案', group: '运行与验收', icon: 'change', scoped: true },
  { id: 'versions', label: '上线', group: '专家', icon: 'versions', scoped: true },
  { id: 'connections', label: '模型连接', group: '版本与设置', icon: 'plug', scoped: false },
  { id: 'deployment', label: '部署与维护', group: '版本与设置', icon: 'cloud', scoped: false },
].map(route => ({ ...route, scoped: routeScope(route.id) === 'agent' }));

const primary = ['overview', 'knowledge', 'redlines', 'business', 'flow', 'test', 'versions', 'settings'];
const workspaceResources = ['materials', 'connections', 'deployment'];
const owner = { create: 'agents', configuration: 'settings', inbox: 'versions', widget: 'versions', contact: 'versions', trial: 'test', runs: 'test', cases: 'test', iterations: 'test' };

function iconButton(action, label, name, extra = '') {
  return `<button type="button" class="btn btn-ghost icon-btn" data-action="${attr(action)}" aria-label="${attr(label)}" title="${attr(label)}" ${extra}>${icon(name, 18)}</button>`;
}

function renderNavigation(state, agent) {
  const active = owner[state.ui.page] || state.ui.page;
  const workspace = routeScope(state.ui.page) === 'workspace';
  const items = workspace ? [] : pendingItems(agent, state);
  const link = id => {
    const route = routes.find(item => item.id === id);
    const count = items.filter(item => item.page === id).length;
    return `<button type="button" class="nav-link" data-action="navigate" data-page="${id}" ${id === active ? 'aria-current="page"' : ''} ${route.scoped && !agent ? 'title="选择专家后查看此专家的内容"' : ''}>${icon(route.icon, 17)}<span>${escapeHtml(route.label)}</span>${count ? `<span class="nav-count" aria-label="${count} 件待处理">${count}</span>` : ''}</button>`;
  };
  if (!workspace) return primary.map(link).join('');
  return `${link('agents')}<div class="nav-group"><div class="nav-group-title">工作区资源</div>${workspaceResources.map(link).join('')}</div>`;
}

function renderScope(state, agent, workspace) {
  if (workspace) return '<div class="scope-summary workspace-scope"><strong>工作区</strong><p>管理专家与工作区资源</p></div>';
  const options = state.agents.map(item => `<option value="${attr(item.id)}" ${item.id === agent?.id ? 'selected' : ''}>${escapeHtml(item.name)}</option>`).join('');
  return `<button class="nav-link workspace-back" type="button" data-action="navigate" data-page="agents">${icon('arrow', 16)}<span>返回工作区</span></button><div class="scope-summary expert-scope"><label for="sidebar-agent">当前专家</label><select id="sidebar-agent" class="control" data-action="select-agent" aria-label="切换当前专家">${!agent ? '<option value="">选择专家</option>' : ''}${options}</select><p>知识与配置按专家分别保存</p></div>`;
}

function renderSaveStatus(state, readonly) {
  if (readonly) return `<span class="save-status">${icon('lock', 13)}只读 · 不写入草稿</span>`;
  const { saveStatus, savedAt } = state.ui;
  const label = saveStatus === 'saving' ? '正在自动保存…' : saveStatus === 'error' ? '保存失败 · 重试' : '已自动保存';
  return `<span class="save-status ${saveStatus === 'error' ? 'is-error' : ''}" aria-live="polite" ${savedAt ? `title="最近保存 ${attr(formatTime(savedAt))}"` : ''}>${icon(saveStatus === 'error' ? 'info' : saveStatus === 'saved' ? 'check' : 'info', 13)}${escapeHtml(label)}</span>`;
}

function renderContext(ctx) {
  const { state, agent, readonly } = ctx;
  if (!agent) return '';
  const preview = agent.versions?.find(version => version.id === state.ui.previewVersionId);
  return `<section class="contextbar" aria-label="当前配置上下文">
    <div class="context-heading">
      <div class="context-title"><strong>${escapeHtml(agent.name)}</strong>${badge(preview ? '历史版本' : '草稿', preview ? 'neutral' : 'info')}</div>
      <div class="context-actions">${renderSaveStatus(state, readonly)}${!readonly && state.ui.saveStatus === 'error' ? '<button class="btn btn-secondary btn-sm" type="button" data-action="save-now">重试保存</button>' : ''}</div>
    </div>
  </section>`;
}

function renderPanelTabs(state, mobile = false) {
  const panel = state.ui.sidePanel || 'trial';
  const viewingEditor = !state.ui.mobilePanel || state.ui.mobilePanel === 'editor';
  const entries = mobile ? [['editor', '当前页', 'settings'], ['trial', '试一试', 'play'], ['evidence', '依据', 'book']] : [['trial', '试一试', 'play'], ['evidence', '依据', 'book']];
  return `<div class="${mobile ? 'mobile-panel-tabs' : 'panel-tabs'}" role="group" aria-label="${mobile ? '工作面板' : '侧栏内容'}">${entries.map(([value, label, name]) => `<button class="btn btn-ghost" type="button" data-action="set-side-panel" data-panel="${value}" aria-pressed="${mobile ? value === 'editor' ? viewingEditor : !viewingEditor && panel === value : panel === value}">${icon(name, 14)}${label}</button>`).join('')}</div>`;
}

export function renderShell(ctx, body, side = '') {
  const { state, agent, readonly } = ctx;
  const ui = state.ui;
  const route = routes.find(item => item.id === ui.page) || routes[0];
  const workspace = !route.scoped;
  const active = owner[ui.page] || ui.page;
  const parentRoute = active !== ui.page ? routes.find(item => item.id === active) : null;
  const pending = workspace ? [] : pendingItems(agent, state);
  const visibleSide = workspace ? '' : side;
  const toast = typeof ui.toast === 'string' ? ui.toast : ui.toast?.message || ui.toast?.text;
  const navOpen = Boolean(ui.navOpen);
  const collapsed = Boolean(ui.sidebarCollapsed);
  return `<div class="app-shell" data-page="${attr(ui.page)}" data-scope="${workspace ? 'workspace' : 'agent'}" data-sidebar-collapsed="${collapsed}">
    <a class="skip-link" href="#workspace-content">跳到当前页面</a>
    <button type="button" class="nav-backdrop ${navOpen ? 'is-open' : ''}" data-action="toggle-nav" aria-label="关闭导航" tabindex="${navOpen ? '0' : '-1'}"></button>
    <aside class="sidebar ${navOpen ? 'is-open' : ''}" id="app-navigation" aria-label="${workspace ? '工作区导航' : '专家导航'}" ${collapsed && !navOpen ? 'inert' : ''}>
      <div class="sidebar-head"><div><div class="brand">Loomrise</div><div class="brand-subtitle">智能客服交付工作台</div></div><div class="mobile-close">${iconButton('toggle-nav', '关闭导航', 'close')}</div></div>
      ${renderScope(state, agent, workspace)}
      <nav class="sidebar-nav" aria-label="${workspace ? '工作区页面' : '专家页面'}">${renderNavigation(state, agent)}</nav>
    </aside>
    <div class="workspace">
      <header class="topbar">
        <div class="topbar-start"><div class="desktop-sidebar-toggle">${iconButton('toggle-sidebar', collapsed ? '展开侧边栏' : '收起侧边栏', 'panel-left', `aria-expanded="${!collapsed}" aria-controls="app-navigation"`)}</div><div class="mobile-menu">${iconButton('toggle-nav', '打开导航', 'panel-left', `aria-expanded="${navOpen}" aria-controls="app-navigation"`)}</div><div class="breadcrumb">${parentRoute ? `<button class="button-link breadcrumb-parent" type="button" data-action="navigate" data-page="${parentRoute.id}">${escapeHtml(parentRoute.label)}</button>` : workspace ? '<span>工作区</span>' : '<button class="button-link breadcrumb-parent" type="button" data-action="navigate" data-page="agents">工作区</button>'}<span class="separator" aria-hidden="true">/</span><strong>${escapeHtml(route.label)}</strong></div></div>
        <div class="topbar-end"><span class="badge badge-neutral environment-label" data-environment="local-prototype" title="仅当前浏览器保存；没有真实模型、外部业务写入或线上发布">本地交互原型</span>${!workspace && agent ? `<button class="btn btn-ghost btn-sm" type="button" data-action="pending-toggle" aria-expanded="${Boolean(ui.pendingOpen)}">待处理 ${pending.length}</button><button class="btn btn-primary btn-sm" type="button" data-action="open-trial">${icon('play', 15)}试一试</button>` : ''}</div>
      </header>
      ${workspace ? '' : renderContext(ctx)}
      ${!workspace && ui.pendingOpen && agent ? `<section class="pending-popover" aria-label="待处理队列"><div class="item-heading"><strong>待处理 ${pending.length}</strong>${iconButton('pending-toggle', '关闭待处理队列', 'close')}</div>${['block', 'suggest'].map(level => `<div class="pending-group"><h2>${level === 'block' ? '上线前必须处理' : '建议处理'}</h2>${pending.filter(item => item.level === level).map(item => `<div class="pending-row"><span>${escapeHtml(item.text)}</span><button class="button-link" type="button" data-action="pending-open" data-id="${attr(item.id)}">${escapeHtml(item.fix)}</button></div>`).join('') || '<p class="muted">暂无</p>'}</div>`).join('')}</section>` : ''}
      ${visibleSide ? renderPanelTabs(state, true) : ''}
      <div class="workspace-body ${visibleSide ? 'has-side-panel' : ''}" data-mobile-panel="${visibleSide && ui.mobilePanel && ui.mobilePanel !== 'editor' ? 'side' : 'editor'}">
        <main class="editor-main" id="workspace-content" tabindex="-1" aria-label="${attr(route.label)}">${body}</main>
        ${visibleSide ? `<aside class="side-panel" aria-label="${ui.sidePanel === 'evidence' ? '依据' : '试一试'}"><div class="side-panel-header">${renderPanelTabs(state)}${iconButton('close-side-panel', '关闭侧栏', 'close')}</div><div class="side-panel-content">${visibleSide}</div></aside>` : ''}
      </div>
    </div>
    ${!workspace && ui.undoBatch?.agentId === agent?.id && Date.now() < ui.undoBatch.expiresAt ? `<div class="undo-bar" role="status"><span>${escapeHtml(ui.undoBatch.label)}已更新</span><button class="btn btn-ghost icon-btn" type="button" data-action="undo-batch" aria-label="撤销这次批量修改" title="撤销这次批量修改">↶</button></div>` : ''}
    ${toast ? `<div class="toast" role="status"><span>${escapeHtml(toast)}</span>${iconButton('dismiss-toast', '关闭提示', 'close')}</div>` : ''}
  </div>`;
}
