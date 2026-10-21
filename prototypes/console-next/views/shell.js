import { escapeHtml, attr, icon, badge, formatTime } from '../helpers.js';

export const routes = [
  { id: 'agents', label: '专家列表', group: '配置与资料', icon: 'agents', scoped: false },
  { id: 'overview', label: '业务概览', group: '配置与资料', icon: 'agents', scoped: true, parent: 'agents' },
  { id: 'configuration', label: '专家配置', group: '配置与资料', icon: 'settings', scoped: true, parent: 'agents' },
  { id: 'create', label: '新建专家', group: '配置与资料', icon: 'plus', scoped: false, hidden: true },
  { id: 'knowledge', label: '知识资料', group: '配置与资料', icon: 'book', scoped: true },
  { id: 'materials', label: '物料库', group: '配置与资料', icon: 'book', scoped: false },
  { id: 'inbox', label: '会话收件箱', group: '客服应用', icon: 'inbox', scoped: true },
  { id: 'widget', label: '网站客服窗', group: '客服应用', icon: 'widget', scoped: true },
  { id: 'contact', label: '联系页', group: '客服应用', icon: 'contact', scoped: true },
  { id: 'trial', label: '试用台', group: '运行与验收', icon: 'play', scoped: true },
  { id: 'runs', label: '运行记录', group: '运行与验收', icon: 'runs', scoped: true },
  { id: 'cases', label: '案例与回放', group: '运行与验收', icon: 'cases', scoped: true },
  { id: 'iterations', label: '改进提案', group: '运行与验收', icon: 'change', scoped: true },
  { id: 'versions', label: '版本与发布', group: '版本与设置', icon: 'versions', scoped: true },
  { id: 'connections', label: '模型连接', group: '版本与设置', icon: 'plug', scoped: false },
  { id: 'deployment', label: '部署与维护', group: '版本与设置', icon: 'cloud', scoped: false },
];

const groups = ['配置与资料', '客服应用', '运行与验收', '版本与设置'];
const depths = [['overview', '业务概览'], ['business', '业务配置'], ['detailed', '详细配置']];

function iconButton(action, label, name, extra = '') {
  return `<button type="button" class="btn btn-ghost icon-btn" data-action="${attr(action)}" aria-label="${attr(label)}" title="${attr(label)}" ${extra}>${icon(name, 18)}</button>`;
}

function renderNavigation(state, agent) {
  const page = state.ui.page;
  const active = page === 'create' ? 'agents' : page;
  const parent = routes.find(route => route.id === active)?.parent;
  const link = route => {
    const depth = route.id === 'overview' ? 'overview' : state.ui.depth === 'detailed' ? 'detailed' : 'business';
    const action = route.parent ? `data-action="set-depth" data-depth="${depth}"` : 'data-action="navigate"';
    return `<button type="button" class="nav-link${route.parent ? ' nav-sub-link' : parent === route.id ? ' has-active-child' : ''}" ${action} data-page="${attr(route.id)}" ${route.id === active ? 'aria-current="page"' : ''} ${route.scoped && !agent ? 'title="选择专家后查看此专家的内容"' : ''}>${icon(route.icon, 17)}<span>${escapeHtml(route.label)}</span></button>`;
  };
  return groups.map(group => `<div class="nav-group"><div class="nav-group-title">${escapeHtml(group)}</div>${routes.filter(route => route.group === group && !route.hidden && !route.parent).map(route => `${link(route)}${agent && routes.some(child => child.parent === route.id) ? `<div class="nav-subgroup" data-parent-page="${route.id}" role="group" aria-label="${attr(agent.name)}的专家页面"><span class="nav-subgroup-label">${escapeHtml(agent.name)}</span>${routes.filter(child => child.parent === route.id && !child.hidden).map(link).join('')}</div>` : ''}`).join('')}</div>`).join('');
}

function renderSaveStatus(state, readonly) {
  if (readonly) return `<span class="save-status">${icon('lock', 13)}只读 · 不写入草稿</span>`;
  const { saveStatus, savedAt } = state.ui;
  const label = saveStatus === 'saving' ? '正在本地保存…' : saveStatus === 'error' ? '本地保存失败 · 可重试' : saveStatus === 'saved' ? '已保存到当前浏览器' : '本地草稿';
  return `<span class="save-status ${saveStatus === 'error' ? 'is-error' : ''}" aria-live="polite" ${savedAt ? `title="最近保存 ${attr(formatTime(savedAt))}"` : ''}>${icon(saveStatus === 'error' ? 'info' : saveStatus === 'saved' ? 'check' : 'info', 13)}${escapeHtml(label)}</span>`;
}

function renderContext(ctx) {
  const { state, agent, readonly } = ctx;
  if (!agent || !['overview', 'configuration'].includes(state.ui.page)) return '';
  const preview = agent.versions?.find(version => version.id === state.ui.previewVersionId);
  const depth = state.ui.page === 'overview' ? 'overview' : state.ui.depth === 'detailed' ? 'detailed' : 'business';
  return `<section class="contextbar" aria-label="当前配置上下文">
    <div class="context-heading">
      <div class="context-title"><strong>${escapeHtml(agent.name)}</strong><span class="revision">r${escapeHtml(preview?.revision ?? agent.revision)}</span>${badge(preview ? '历史版本' : '草稿', preview ? 'neutral' : 'info')}</div>
      <div class="context-actions">${renderSaveStatus(state, readonly)}${!readonly && state.ui.saveStatus === 'error' ? '<button class="btn btn-secondary btn-sm" type="button" data-action="save-now">重试保存</button>' : ''}</div>
    </div>
    <div class="context-depth">
      <div class="depth-tabs" role="tablist" aria-label="配置深度">${depths.map(([value, label]) => `<button class="depth-tab" type="button" role="tab" aria-selected="${depth === value}" data-action="set-depth" data-depth="${value}">${label}</button>`).join('')}</div>
      <div class="button-group"><button class="btn btn-ghost btn-sm" type="button" data-action="toggle-assistant" aria-pressed="${Boolean(state.ui.assistantOpen)}">${icon('spark', 15)}${state.ui.assistantOpen ? '收起协助' : '创作助手（后续）'}</button></div>
    </div>
  </section>`;
}

function renderPanelTabs(state, mobile = false) {
  const panel = state.ui.sidePanel || 'preview';
  const viewingEditor = !state.ui.mobilePanel || state.ui.mobilePanel === 'editor';
  const entries = mobile ? [['editor', '编辑', 'settings'], ['preview', '预览', 'eye'], ['assistant', '协助', 'spark']] : [['preview', '预览', 'eye'], ['assistant', '协助', 'spark']];
  return `<div class="${mobile ? 'mobile-panel-tabs' : 'panel-tabs'}" role="group" aria-label="${mobile ? '工作面板' : '侧栏内容'}">${entries.map(([value, label, name]) => `<button class="btn btn-ghost" type="button" data-action="set-side-panel" data-panel="${value}" aria-pressed="${mobile ? value === 'editor' ? viewingEditor : !viewingEditor && panel === value : panel === value}">${icon(name, 14)}${label}</button>`).join('')}</div>`;
}

export function renderShell(ctx, body, side = '') {
  const { state, agent, readonly } = ctx;
  const ui = state.ui;
  const route = routes.find(item => item.id === ui.page) || routes[0];
  const parentRoute = routes.find(item => item.id === route.parent);
  const selectedOptions = state.agents.map(item => `<option value="${attr(item.id)}" ${item.id === agent?.id ? 'selected' : ''}>${escapeHtml(item.name)}</option>`).join('');
  const toast = typeof ui.toast === 'string' ? ui.toast : ui.toast?.message || ui.toast?.text;
  const navOpen = Boolean(ui.navOpen);
  return `<div class="app-shell" data-page="${attr(ui.page)}">
    <a class="skip-link" href="#workspace-content">跳到当前页面</a>
    <button type="button" class="nav-backdrop ${navOpen ? 'is-open' : ''}" data-action="toggle-nav" aria-label="关闭导航" tabindex="${navOpen ? '0' : '-1'}"></button>
    <aside class="sidebar ${navOpen ? 'is-open' : ''}" id="app-navigation" aria-label="工作台导航">
      <div class="sidebar-head"><div><div class="brand">Loomrise</div><div class="brand-subtitle">智能客服交付工作台</div></div><div class="mobile-close">${iconButton('toggle-nav', '关闭导航', 'close')}</div></div>
      <div class="scope-summary"><small>当前专家</small><strong>${escapeHtml(agent?.name || '未选择专家')}</strong><p>${ui.page === 'materials' ? '工作区独立物料库 · 按物料指定可用专家' : agent ? `草稿 r${escapeHtml(agent.revision)} · 页面按此专家筛选` : '先从专家列表打开或新建专家'}</p></div>
      <nav class="sidebar-nav">${renderNavigation(state, agent)}</nav>
      <div class="sidebar-footer"><small>配置与资料 → 试用验收 → 版本发布</small></div>
    </aside>
    <div class="workspace">
      <header class="topbar">
        <div class="topbar-start"><div class="mobile-menu">${iconButton('toggle-nav', '打开导航', 'menu', `aria-expanded="${navOpen}" aria-controls="app-navigation"`)}</div><div class="breadcrumb">${parentRoute ? `<button class="button-link breadcrumb-parent" type="button" data-action="navigate" data-page="${parentRoute.id}">${escapeHtml(parentRoute.label)}</button>` : `<span>${escapeHtml(route.group)}</span>`}<span class="separator" aria-hidden="true">/</span><strong>${escapeHtml(route.label)}</strong></div></div>
        <div class="topbar-end"><label class="agent-switch"><span>专家</span><select data-action="select-agent" aria-label="切换当前专家"><option value="" ${!agent ? 'selected' : ''}>选择专家</option>${selectedOptions}</select></label><span class="badge badge-neutral environment-label" data-environment="local-prototype" title="仅当前浏览器保存；没有真实模型、外部业务写入或线上发布">本地交互原型</span>${agent && !ui.previewVersionId ? `<label class="readonly-switch" title="本地界面的只读预览，不代表真实权限"><input type="checkbox" data-action="readonly-toggle" ${readonly ? 'checked' : ''}>只读预览</label>` : ''}</div>
      </header>
      ${renderContext(ctx)}
      ${side ? renderPanelTabs(state, true) : ''}
      <div class="workspace-body ${side ? 'has-side-panel' : ''}" data-mobile-panel="${ui.mobilePanel && ui.mobilePanel !== 'editor' ? 'side' : 'editor'}">
        <main class="editor-main" id="workspace-content" tabindex="-1" aria-label="${attr(route.label)}">${body}</main>
        ${side ? `<aside class="side-panel" aria-label="${ui.sidePanel === 'assistant' ? '创作助手预留' : '编辑预览'}"><div class="side-panel-header">${renderPanelTabs(state)}${ui.sidePanel === 'assistant' ? iconButton('toggle-assistant', '收起协助，返回编辑', 'close') : ''}</div><div class="side-panel-content">${side}</div></aside>` : ''}
      </div>
    </div>
    ${toast ? `<div class="toast" role="status"><span>${escapeHtml(toast)}</span>${iconButton('dismiss-toast', '关闭提示', 'close')}</div>` : ''}
  </div>`;
}
