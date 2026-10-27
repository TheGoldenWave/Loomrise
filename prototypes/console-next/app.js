import { createStore } from './store.js';
import { createLocalFileReader } from './local-files.js';
import { createMaterialController } from './material-controller.js';
import { createVisitorController } from './visitor-controller.js';
import { clone } from './fixtures.js';
import { prepareAgentTask, readiness } from './domain.js';
import { button, emptyState, escapeHtml, section } from './helpers.js';
import { routes, renderShell } from './views/shell.js';
import { renderAgents, renderCreate, renderOverview, renderConfiguration, renderAssistant } from './views/editor.js';
import { renderKnowledge, renderTrial, renderInbox, renderWidget, widgetPreview, renderContact, renderConnections, renderRuns, renderCases, renderIterations, renderVersions, renderDeployment } from './views/surfaces.js';
import { renderMaterials, renderMaterialPreview } from './views/materials.js';
import { renderRedlines } from './views/knowledge.js';
import { renderBusiness, renderSettings, renderTest, renderRelease } from './views/config-pages.js';
import { renderFlow } from './views/flow.js';
import { renderQuickTrial, renderEvidencePanel } from './views/config-panels.js';
import { parseBatchText, parseWorkbook } from './knowledge-model.js';
import { createNavigationHistory, routeScope } from './navigation.js';
import { createR1ConfigurationWorkspace } from './r1-configuration.js';

let browserStorage;
try { browserStorage = window.localStorage; } catch { browserStorage = { getItem() { throw new Error('存储不可用'); }, setItem() { throw new Error('存储不可用'); } }; }
const store = createStore(browserStorage);
const app = document.querySelector('#app');
let renderingR1Configuration = false;
const r1Configuration = createR1ConfigurationWorkspace({
  onChange() {
    if (store.state.ui.page === 'configuration' && store.state.ui.section === 'r1-server') render();
  },
});
let materialsController;
let visitorController;
let previousR1Context = null;
function fileContext() {
  const { ui, selectedAgentId } = store.state;
  if (ui.page !== 'knowledge' || ui.sourceTab !== 'File' || !ui.sourceForm || store.readonly()) return null;
  return `${selectedAgentId}:${ui.sourceEdit || 'new'}:File`;
}
const fileReader = createLocalFileReader(fileContext);
let lastFileContext = fileContext();
const pages = { agents: renderAgents, create: renderCreate, overview: renderOverview, configuration: renderConfiguration, materials: renderMaterials, knowledge: renderKnowledge, redlines: renderRedlines, business: renderBusiness, flow: renderFlow, test: renderTest, settings: renderSettings, trial: renderTrial, inbox: renderInbox, widget: renderWidget, contact: renderContact, connections: renderConnections, runs: renderRuns, cases: renderCases, iterations: renderIterations, versions: renderRelease, deployment: renderDeployment };
let toastTimer = null;
let undoTimer = null;
let preserveOnExit = true;
let composing = false;
const disclosureKey = () => `${store.state.selectedAgentId}:${store.state.ui.page}:${store.state.ui.section}:${store.state.ui.previewVersionId || 'draft'}`;
const detailKey = detail => detail.dataset.disclosureKey || detail.querySelector(':scope > summary')?.textContent.trim() || '';

function librarySurface(ctx) {
  const { state, agent } = ctx;
  const page = state.ui.page;
  if (['runs', 'cases', 'iterations', 'connections'].includes(page)) {
    const ui = state.ui.collections[page];
    const mode = ui.form ? 'form' : ui.detailId ? 'detail' : 'list';
    const scope = `${page}:${page === 'connections' ? 'workspace' : agent?.id || ''}`;
    return { page, scope, mode, id: ui.detailId || '', key: `${scope}:${mode}:${ui.detailId || ''}` };
  }
  if (!['knowledge', 'materials'].includes(page)) return null;
  const ui = page === 'knowledge' ? state.ui : state.ui.materials;
  const form = page === 'knowledge' ? ui.sourceForm : ui.form;
  const editingId = page === 'knowledge' ? ui.sourceEdit : ui.editingId;
  const detailId = page === 'knowledge' ? ui.sourceDetail : ui.detailId;
  const items = page === 'knowledge' ? agent?.config.sources || [] : state.materials;
  const selected = items.find(item => item.id === detailId);
  const mode = form ? 'form' : selected ? 'detail' : 'list';
  const id = form ? editingId || '' : selected?.id || '';
  const scope = `${page}:${agent?.id || ''}:${page === 'knowledge' ? ui.sourceTab : ''}`;
  return { page, scope, mode, id, key: `${scope}:${mode}:${id}` };
}
let renderedLibrary = null;
const libraryListPositions = new Map();
let renderedMaterialPreview = false;
let materialPreviewReturn = null;
function actionSelector(element) {
  if (!element?.dataset.action) return null;
  return Object.entries(element.dataset).map(([key, value]) => `[data-${key.replace(/[A-Z]/g, char => '-' + char.toLowerCase())}="${CSS.escape(value)}"]`).join('');
}
function syncMaterialScope() {
  const form = app.querySelector('[data-form="material-upsert"]');
  const target = form?.querySelector('[data-material-scope-target]');
  if (!target) return;
  const workspace = form.elements.namedItem('scope')?.value === 'workspace';
  target.hidden = workspace;
  target.disabled = workspace || Boolean(form.elements.namedItem('title')?.disabled);
}

function formKey(form) {
  return `${store.state.selectedAgentId || ''}:${form.dataset.form}:${form.querySelector('[name="id"]')?.value || form.querySelector('[name="conversationId"]')?.value || ''}:${form.querySelector('[name="type"]')?.value || ''}`;
}
function preserveForm(form) {
  const values = {};
  for (const control of form.elements) {
    if (!control.name || control.type === 'file' || control.type === 'hidden' || control.dataset.bind || control.dataset.uiBind) continue;
    if (control.type === 'radio') {
      if (control.checked) values[control.name] = control.value;
    } else if (control.type === 'checkbox' && [...form.elements].filter(item => item.type === 'checkbox' && item.name === control.name).length > 1) {
      values[control.name] = [...form.elements].filter(item => item.name === control.name && item.checked).map(item => item.value);
    } else values[control.name] = control.type === 'checkbox' ? control.checked : control.value;
  }
  store.state.ui.formDrafts ||= {};
  store.state.ui.formDrafts[formKey(form)] = values;
  store.save();
}
function restoreForms() {
  for (const form of app.querySelectorAll('[data-form]')) {
    const values = store.state.ui.formDrafts?.[formKey(form)]; if (!values) continue;
    for (const control of form.elements) {
      if (!(control.name in values) || control.type === 'file' || control.type === 'hidden' || control.dataset.bind || control.dataset.uiBind) continue;
      if (control.type === 'radio') control.checked = control.value === values[control.name];
      else if (control.type === 'checkbox') control.checked = Array.isArray(values[control.name]) ? values[control.name].includes(control.value) : values[control.name]; else control.value = values[control.name];
    }
  }
}

const navigation = createNavigationHistory({ store, location: window.location, history: window.history, pages: Object.keys(pages) });
function context() {
  const state = store.state;
  let agent = store.currentAgent();
  if (agent && state.ui.previewVersionId) {
    const version = agent.versions.find(item => item.id === state.ui.previewVersionId);
    if (version) agent = { ...agent, config: clone(version.config), revision: version.revision };
  }
  return { state, agent, ready: readiness(agent, state.connections), readonly: store.readonly() };
}
function preview(ctx) {
  const { agent, ready } = ctx;
  if (!agent) return '';
  return section('访客看到的样子', widgetPreview(agent, ctx) + `<p class="helper">当前草稿 r${agent.revision}；不会改变已绑定入口。</p>` + button('navigate', '进入脚本试用', { page: 'trial', variant: 'primary', disabled: false }), { description: '当前草稿的本地访客预览，检索和发送按策略演示。' });
}
let renderedDisclosureKey;
function render() {
  visitorController?.beforeRender();
  const focused = document.activeElement;
  const previewFocus = focused?.closest('.material-preview-dialog') ? actionSelector(focused) : null;
  const identifier = focused?.dataset.bind ? ['bind', focused.dataset.bind] : focused?.dataset.uiBind ? ['ui-bind', focused.dataset.uiBind] : focused?.dataset.r1Bind ? ['r1-bind', focused.dataset.r1Bind] : focused?.dataset.r1Json ? ['r1-json', focused.dataset.r1Json] : focused?.hasAttribute('data-agent-name') ? ['agent-name', ''] : null;
  const selection = focused && ['INPUT', 'TEXTAREA'].includes(focused.tagName) ? { start: focused.selectionStart, end: focused.selectionEnd } : null;
  const focusedForm = focused?.closest('[data-form]');
  const formFocus = !identifier && focusedForm && focused.name ? { key: formKey(focusedForm), name: focused.name } : null;
  const key = disclosureKey();
  const disclosures = { ...store.state.ui.disclosures?.[key] };
  if (renderedDisclosureKey === key) for (const detail of app.querySelectorAll('details:not([data-flow-branch-disclosure])')) disclosures[detailKey(detail)] = detail.open;
  store.state.ui.disclosures ||= {}; store.state.ui.disclosures[key] = disclosures;
  renderedDisclosureKey = key;
  const ctx = context();
  const nextLibrary = librarySurface(ctx);
  const previousLibrary = renderedLibrary;
  if (previousLibrary?.mode === 'list' && previousLibrary.key !== nextLibrary?.key) {
    libraryListPositions.set(previousLibrary.scope, window.scrollY);
  }
  ctx.r1Configuration = r1Configuration;
  const renderer = pages[ctx.state.ui.page] || renderAgents;
  let body;
  try { body = renderer(ctx); }
  catch (error) { console.error(error); body = emptyState('这个页面未能载入', '草稿仍在本地保留。返回专家列表后重试。', button('navigate', '返回列表', { page: 'agents' })); }
  const scoped = routeScope(ctx.state.ui.page) === 'agent';
  if (scoped && !ctx.agent) body = emptyState('先选择一个专家', '创建或选择专家后，查看它的资料、配置和运行记录。', button('new-agent', '手动创建', { mode: 'manual', variant: 'primary' }));
  if (!scoped || !ctx.agent) ctx.r1Configuration.closeSnapshot();
  const withSide = scoped && ctx.agent && ctx.state.ui.sideOpen;
  const side = withSide ? ctx.state.ui.sidePanel === 'evidence' ? renderEvidencePanel(ctx) : renderQuickTrial(ctx) : '';
  app.innerHTML = renderShell(ctx, body, side) + renderMaterialPreview(ctx);
  materialsController?.hydrate();
  visitorController?.afterRender();
  restoreForms();
  syncMaterialScope();
  for (const detail of app.querySelectorAll('details:not([data-flow-branch-disclosure])')) if (detailKey(detail) in disclosures) detail.open = disclosures[detailKey(detail)];
  document.title = `${routes.find(route => route.id === ctx.state.ui.page)?.label || '配置工作台'} · Loomrise`;
  if (identifier) {
    const [key, value] = identifier;
    const restored = app.querySelector(`[data-${key}${value ? `="${CSS.escape(value)}"` : ''}]`);
    if (restored) { restored.focus({ preventScroll: true }); if (selection?.start !== null && typeof restored.setSelectionRange === 'function') { try { restored.setSelectionRange(selection.start, selection.end); } catch { /* Color/select controls have no selection range. */ } } }
  }
  if (formFocus) {
    const form = [...app.querySelectorAll('[data-form]')].find(form => formKey(form) === formFocus.key);
    const restored = form?.elements.namedItem(formFocus.name);
    if (restored?.focus) { restored.focus({ preventScroll: true }); if (selection?.start !== null && typeof restored.setSelectionRange === 'function') { try { restored.setSelectionRange(selection.start, selection.end); } catch {} } }
  }
  renderedLibrary = nextLibrary;
  const r1Context = ctx.state.ui.page === 'configuration' && ctx.state.ui.section === 'r1-server' && ctx.agent
    ? `${ctx.agent.id}:r1-server` : null;
  if (r1Context !== previousR1Context && r1Context && !renderingR1Configuration) {
    renderingR1Configuration = true;
    void r1Configuration.load(ctx.agent?.id).finally(() => { renderingR1Configuration = false; });
  }
  previousR1Context = r1Context;
  if (nextLibrary && nextLibrary.key !== previousLibrary?.key) {
    if (nextLibrary.mode === 'list' && nextLibrary.scope === previousLibrary?.scope) {
      window.scrollTo({ top: libraryListPositions.get(nextLibrary.scope) || 0, behavior: 'instant' });
      const action = nextLibrary.page === 'knowledge' ? 'source-detail' : nextLibrary.page === 'materials' ? 'material-detail' : 'collection-open';
      const row = previousLibrary?.id && app.querySelector(`[data-action="${action}"][data-id="${CSS.escape(previousLibrary.id)}"]`);
      (row || app.querySelector('[data-library-heading], [data-collection-heading]'))?.focus({ preventScroll: true });
    } else {
      window.scrollTo({ top: 0, behavior: 'instant' });
      app.querySelector('[data-library-heading], [data-collection-heading], .library-focus, main h1')?.focus({ preventScroll: true });
    }
  }
  const dialog = app.querySelector('.material-preview-dialog');
  if (dialog) {
    const shell = app.querySelector('.app-shell');
    if (shell) shell.inert = true;
    (previewFocus && dialog.querySelector(previewFocus) || dialog.querySelector('[data-action="material-preview-close"]'))?.focus({ preventScroll: true });
  } else if (renderedMaterialPreview) {
    (materialPreviewReturn && app.querySelector(materialPreviewReturn) || app.querySelector('[data-library-heading]') || app.querySelector('#workspace-content'))?.focus({ preventScroll: true });
    materialPreviewReturn = null;
  }
  renderedMaterialPreview = Boolean(dialog);
  if (ctx.state.ui.navOpen) {
    const nav = app.querySelector('.sidebar');
    nav?.setAttribute('aria-label', '主导航（按 Escape 关闭）');
  }
  const toast = ctx.state.ui.toast;
  if (toast) {
    const target = app.querySelector('.toast');
    if (target && !target.hasAttribute('role')) { target.setAttribute('role', 'status'); target.setAttribute('aria-live', 'polite'); }
    clearTimeout(toastTimer); toastTimer = setTimeout(() => store.dispatch('dismiss-toast'), toast.tone === 'danger' ? 9000 : 5500);
  }
  clearTimeout(undoTimer);
  const undo = ctx.state.ui.undoBatch;
  if (undo && undo.expiresAt > Date.now()) undoTimer = setTimeout(render, undo.expiresAt - Date.now() + 20);
  if (ctx.state.ui.focusTarget) {
    const target = ctx.state.ui.focusTarget;
    delete ctx.state.ui.focusTarget;
    requestAnimationFrame(() => {
      const toolIndex = ctx.agent?.config.tools.findIndex(item => item.id === target);
      const bound = app.querySelector(`[data-bind="${CSS.escape(target)}"]`) || (toolIndex >= 0 && app.querySelector(`[data-bind="tools.${toolIndex}.successField"]`));
      const node = bound || (ctx.state.ui.page === 'flow' && app.querySelector('.flow-inspector')) || app.querySelector(`[data-rule-id="${CSS.escape(target)}"], [data-fact-id="${CSS.escape(target)}"]`) || app.querySelector('.test-detail, .test-feedback, .knowledge-review-item, .library-focus, main h1');
      if (!node) return;
      for (let parent = node.parentElement; parent; parent = parent.parentElement) if (parent.tagName === 'DETAILS') parent.open = true;
      if (!node.matches('input, select, textarea, button, a')) node.tabIndex = -1;
      node.classList.add('focus-target'); node.focus(); node.scrollIntoView({ block: 'center' });
      node.addEventListener('blur', () => node.classList.remove('focus-target'), { once: true });
    });
  }
}
materialsController = createMaterialController({ store, app, render, formKey, preserveForm });
visitorController = createVisitorController({ store, app, materialController: materialsController });
function syncSidebarState() {
  const { sidebarCollapsed: collapsed, navOpen } = store.state.ui;
  app.querySelector('.app-shell').dataset.sidebarCollapsed = String(collapsed);
  const sidebar = app.querySelector('.sidebar');
  sidebar.classList.toggle('is-open', navOpen);
  sidebar.inert = collapsed && !navOpen;
  sidebar.setAttribute('aria-label', navOpen ? '主导航（按 Escape 关闭）' : routeScope(store.state.ui.page) === 'agent' ? '专家导航' : '工作区导航');
  const backdrop = app.querySelector('.nav-backdrop');
  backdrop.classList.toggle('is-open', navOpen);
  backdrop.tabIndex = navOpen ? 0 : -1;
  const desktopToggle = app.querySelector('[data-action="toggle-sidebar"]');
  const label = collapsed ? '展开侧边栏' : '收起侧边栏';
  desktopToggle.setAttribute('aria-expanded', String(!collapsed));
  desktopToggle.setAttribute('aria-label', label);
  desktopToggle.title = label;
  app.querySelector('.mobile-menu [data-action="toggle-nav"]').setAttribute('aria-expanded', String(navOpen));
}
store.subscribe((_state, action) => {
  navigation.sync();
  if (['toggle-sidebar', 'toggle-nav'].includes(action) && store.state.ui.saveStatus !== 'error') { syncSidebarState(); return; }
  const current = fileContext();
  if (current !== lastFileContext) { fileReader.invalidate(); lastFileContext = current; }
  materialsController.contextChanged();
  visitorController.contextChanged();
  render();
});

function downloadConfig() {
  const agent = context().agent; if (!agent) return;
  const payload = { format: 'loomrise-frontend-draft-v1', environment: 'local-simulation', agent: { id: agent.id, name: agent.name, revision: agent.revision, config: agent.config }, note: '仅前端配置草稿，非可执行发行包；不含凭据、运行日志或客户会话。' };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob); const anchor = document.createElement('a'); anchor.href = url; anchor.download = `loomrise-${agent.id}-r${agent.revision}.json`; anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
async function intakeFiles(files, details = {}) {
  const agentId = store.state.selectedAgentId;
  const revision = store.currentAgent()?.revision;
  if (store.readonly()) { store.state.ui.toast = { text: '当前为只读预览，返回草稿后放资料。', tone: 'warning' }; render(); return; }
  if (!files.length || files.length > 20) { store.state.ui.toast = { text: '一次请选择 1–20 份资料。', tone: 'warning' }; render(); return; }
  let created = 0;
  const unsupported = [];
  for (const file of files) {
    if (file.size > 2 * 1024 * 1024) { unsupported.push(`${file.name} 超出本地 2 MB 上限`); continue; }
    const type = file.name.split('.').pop()?.toLowerCase();
    if (!['csv', 'tsv', 'txt', 'md', 'markdown', 'xlsx'].includes(type)) { unsupported.push(`${file.name} 尚未接入解析`); continue; }
    let candidates;
    try { candidates = type === 'xlsx' ? await parseWorkbook({ name: file.name, buffer: await file.arrayBuffer() }) : parseBatchText({ name: file.name, text: await file.text() }); }
    catch (error) { unsupported.push(`${file.name}：${error.message || '无法读取，请重新选择'}`); continue; }
    if (store.state.selectedAgentId !== agentId || store.currentAgent()?.revision !== revision + created) return;
    if (!candidates.length) { unsupported.push(`${file.name} 没有可拆分的内容`); continue; }
    const intake = app.querySelector('.knowledge-batch-intake');
    if (intake) {
      intake.open = false;
      store.state.ui.disclosures ||= {};
      store.state.ui.disclosures[disclosureKey()] ||= {};
      store.state.ui.disclosures[disclosureKey()][detailKey(intake)] = false;
    }
    const result = store.dispatch('batch-intake', { title: file.name, candidates, sourceRef: details.sourceRef || '', expires: details.expires || '', rights: details.rights || false });
    if (result.ok) {
      created += 1;
      const disclosure = app.querySelector('.knowledge-batch-intake');
      if (disclosure) disclosure.open = false;
    }
  }
  if (unsupported.length) { store.state.ui.toast = { text: `${created ? `已接收 ${created} 份；` : ''}${unsupported.join('；')}。PDF、DOCX 的解析待后端接入。`, tone: 'warning' }; render(); }
}
app.addEventListener('click', async event => {
  const target = event.target.closest('[data-action]'); if (!target || target.disabled || target.tagName === 'SELECT' || target.tagName === 'INPUT') return;
  const { action, ...data } = target.dataset;
  if (action === 'r1-refresh') { await r1Configuration.refresh(); return; }
  if (action === 'r1-create-draft') { await r1Configuration.createDraft(data.versionId); return; }
  if (action === 'r1-save') { await r1Configuration.save(r1Configuration.state.editorConfig); return; }
  if (action === 'r1-validate') { await r1Configuration.validate(); return; }
  if (action === 'r1-freeze') { await r1Configuration.freezeCandidate(); return; }
  if (action === 'r1-reload-conflict') { r1Configuration.reloadConflict(); return; }
  if (action === 'r1-retry-conflict') { await r1Configuration.retryConflict(); return; }
  if (action === 'r1-open-stable') { await r1Configuration.openStable(data.versionId); return; }
  if (action === 'r1-open-candidate') { await r1Configuration.openCandidate(data.candidateId); return; }
  if (action === 'r1-close-snapshot') { r1Configuration.closeSnapshot(); return; }
  if (action === 'r1-tab') { r1Configuration.setTab(data.tab); return; }
  if ((action === 'material-preview' && data.mode !== 'download') || action === 'visitor-attachment-preview') materialPreviewReturn = actionSelector(target);
  if (await visitorController.click(action, data)) return;
  if (await materialsController.click(action, data)) return;
  if (action === 'export-config') { downloadConfig(); return; }
  if (action === 'export-migration-backup') {
    const backup = browserStorage.getItem(store.state.ui.migrationBackupKey);
    if (!backup) { store.state.ui.toast = { tone: 'warning', text: '迁移前副本已不存在；当前草稿仍保留，可先导出草稿。' }; render(); return; }
    const url = URL.createObjectURL(new Blob([backup], { type: 'application/json' }));
    const link = document.createElement('a'); link.href = url; link.download = 'loomrise-before-config-ui-v2.json'; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); return;
  }
  if (action === 'assistant-copy') {
    const task = prepareAgentTask(context().agent);
    try { await navigator.clipboard.writeText(JSON.stringify(task, null, 2)); store.state.ui.toast = { text: '受限任务摘要已复制；没有调用外部创作助手，也未复制资料全文或会话。', tone: 'neutral' }; }
    catch { store.state.ui.toast = { text: '浏览器未允许复制，可以按面板中的目标与资料引用手动准备任务。', tone: 'warning' }; }
    render(); return;
  }
  if (action === 'widget-copy') {
    const code = document.querySelector('.install-code code')?.textContent || '<!-- 前端示例，尚无可运行安装代码 -->';
    try { await navigator.clipboard.writeText(code); store.state.ui.toast = { text: '不可运行的示例代码已复制；没有安装真实网站客服窗。', tone: 'neutral' }; render(); }
    catch { store.state.ui.toast = { text: '浏览器未允许复制，请选中示例代码手动复制。', tone: 'warning' }; render(); }
    return;
  }
  if (action === 'preview-question') { store.dispatch('open-trial', { question: data.question }); return; }
  store.dispatch(action, data);
  if (action === 'navigate' || action === 'select-agent' || action === 'new-agent') window.scrollTo({ top: 0 });
  if (action === 'toggle-sidebar') requestAnimationFrame(() => app.querySelector('[data-action="toggle-sidebar"]')?.focus({ preventScroll: true }));
  if (action === 'toggle-nav') requestAnimationFrame(() => app.querySelector(store.state.ui.navOpen ? '.mobile-close [data-action="toggle-nav"]' : '.mobile-menu [data-action="toggle-nav"]')?.focus({ preventScroll: true }));
});
app.addEventListener('input', event => {
  const target = event.target;
  if (target.dataset.r1Bind) {
    const value = target.type === 'number' ? Number(target.value) : target.value;
    r1Configuration.updateField(target.dataset.r1Bind, value);
  } else if (target.dataset.r1Json) {
    r1Configuration.updateJsonField(target.dataset.r1Json, target.value);
  }
});
function updateBound(target) {
  if (target.dataset.action === 'material-filter') { store.dispatch('material-filter', { path: target.dataset.path, value: target.value }); return; }
  if (target.dataset.bind) {
    let value = target.type === 'checkbox' ? target.checked : target.type === 'number' ? Number(target.value) : target.value;
    if (target.dataset.format === 'lines') value = String(value).split('\n').map(part => part.trim()).filter(Boolean);
    if (target.dataset.format === 'csv') value = String(value).split(/[,，]/).map(part => part.trim()).filter(Boolean);
    store.dispatch('update-config', { path: target.dataset.bind.replace(/^config\./, ''), value });
  } else if (target.dataset.uiBind) store.dispatch('update-ui', { path: target.dataset.uiBind, value: target.value });
  else if (target.hasAttribute('data-agent-name')) store.dispatch('update-name', { value: target.value });
}
app.addEventListener('input', event => {
  const target = event.target;
  if (composing || event.isComposing) return;
  if (target.dataset.bind || target.dataset.uiBind || target.hasAttribute('data-agent-name')) updateBound(target);
  else if (target.closest('[data-form]')) preserveForm(target.closest('[data-form]'));
});
app.addEventListener('compositionstart', () => { composing = true; });
app.addEventListener('compositionend', event => { composing = false; updateBound(event.target); });
app.addEventListener('toggle', event => {
  if (event.target.tagName !== 'DETAILS') return;
  if (event.target.matches('[data-flow-branch-disclosure]')) { if (store.state.ui.flowBranchOpen !== event.target.open) store.dispatch('flow-branch-disclosure', { open: event.target.open }); return; }
  store.state.ui.disclosures ||= {};
  store.state.ui.disclosures[disclosureKey()] ||= {};
  store.state.ui.disclosures[disclosureKey()][detailKey(event.target)] = event.target.open;
  store.save();
}, true);
app.addEventListener('change', async event => {
  const target = event.target;
  if (await materialsController.change(target)) return;
  if (target.matches('[data-batch-files]')) { await intakeFiles([...target.files]); return; }
  if (target.matches('[data-action="flow-select"]')) { store.dispatch('flow-select', { id: target.dataset.id }); return; }
  if (target.matches('[data-action="select-agent"]')) { if (target.value) store.dispatch('select-agent', { id: target.value }); return; }
  if (target.matches('[data-action="readonly-toggle"]')) { store.dispatch('readonly-toggle'); return; }
  if (target.matches('[data-source-file]')) {
    const originalForm = target.closest('form');
    const originalKey = formKey(originalForm);
    preserveForm(originalForm);
    const file = target.files?.[0]; if (!file) return;
    const result = await fileReader.read(file);
    if (result.status === 'stale') return;
    if (result.status === 'error') { store.state.ui.toast = { text: result.message, tone: 'danger' }; render(); return; }
    store.state.ui.formDrafts[originalKey] ||= {};
    store.state.ui.formDrafts[originalKey].body = result.body;
    if (!store.state.ui.formDrafts[originalKey].title) store.state.ui.formDrafts[originalKey].title = file.name;
    store.dispatch('file-selected', { body: result.body, meta: result.meta });
    return;
  }
  if (target.tagName === 'SELECT' || target.type === 'checkbox' || target.type === 'color') updateBound(target);
  if (target.closest('[data-form="material-upsert"]') && target.name === 'scope') syncMaterialScope();
  if (!target.dataset.bind && !target.dataset.uiBind && target.closest('[data-form]')) preserveForm(target.closest('[data-form]'));
});
app.addEventListener('submit', async event => {
  const form = event.target.closest('[data-form]'); if (!form) return;
  event.preventDefault();
  const values = Object.fromEntries(new FormData(form).entries());
  const action = form.dataset.form;
  if (action === 'source-batch') { await intakeFiles([...form.elements.namedItem('files').files], values); return; }
  if (action === 'quick-trial') { store.dispatch('quick-trial', values); return; }
  if (action === 'fact-save') values.excluded = [...form.querySelectorAll('input[name^="include:"]:not(:checked)')].map(input => input.name.slice('include:'.length));
  if (await visitorController.submit(form, values)) return;
  if (await materialsController.submit(form, values)) return;
  if (action === 'source' && values.type === 'File') {
    const meta = store.state.ui.sourceFileMeta;
    if (meta) { values.filename = meta.name; values.metadataOnly = meta.metadataOnly; values.title ||= meta.name; values.body ||= store.state.ui.sourceFileBody; }
  }
  if (action === 'create') values.mode ||= store.state.ui.createMode;
  const key = formKey(form);
  const result = store.dispatch(action, values);
  if (result.ok && action === 'flow-branch') {
    const disclosure = form.closest('details');
    if (disclosure) disclosure.open = false;
    requestAnimationFrame(() => app.querySelector(`.flow-node[data-id="${CSS.escape(store.state.ui.selectedFlowNode || '')}"]`)?.focus({ preventScroll: true }));
  }
  if (result.ok && store.state.ui.formDrafts) { delete store.state.ui.formDrafts[key]; store.save(); render(); }
});
app.addEventListener('dragover', event => { if (event.target.closest('[data-batch-drop]')) event.preventDefault(); });
app.addEventListener('drop', async event => { if (!event.target.closest('[data-batch-drop]')) return; event.preventDefault(); await intakeFiles([...event.dataTransfer.files]); });
document.addEventListener('keydown', event => {
  const previewDialog = app.querySelector('.material-preview-dialog');
  if (previewDialog && event.key === 'Tab') {
    const controls = [...previewDialog.querySelectorAll('button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), video[controls], iframe, [tabindex="0"]')].filter(element => element.getClientRects().length);
    const first = controls[0]; const last = controls.at(-1);
    if (event.shiftKey && (document.activeElement === first || !previewDialog.contains(document.activeElement))) { event.preventDefault(); last?.focus(); }
    if (!event.shiftKey && (document.activeElement === last || !previewDialog.contains(document.activeElement))) { event.preventDefault(); first?.focus(); }
    return;
  }
  const sourceTab = event.target.closest?.('.source-tabs [role="tab"]');
  if (sourceTab && ['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
    event.preventDefault();
    const tabs = [...app.querySelectorAll('.source-tabs [role="tab"]')];
    const current = tabs.indexOf(sourceTab);
    const index = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (current + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
    const tab = tabs[index]?.dataset.tab;
    if (tab) { store.dispatch('source-tab', { tab }); app.querySelector(`.source-tabs [data-tab="${tab}"]`)?.focus({ preventScroll: true }); }
    return;
  }
  if (store.state.ui.page === 'knowledge' && store.state.ui.knowledgeTab === 'review' && !store.readonly() && !event.target.closest('input, textarea, select, [contenteditable]')) {
    const items = [...app.querySelectorAll('.knowledge-review-item')];
    const selected = event.target.closest('.knowledge-review-item');
    const index = Math.max(0, items.indexOf(selected));
    if (['ArrowLeft', 'ArrowRight'].includes(event.key) && items.length) {
      event.preventDefault();
      items[(index + (event.key === 'ArrowRight' ? 1 : -1) + items.length) % items.length].focus(); return;
    }
    if (['1', '2', '3'].includes(event.key) && selected) {
      if (selected.querySelector('.knowledge-review-choice') && event.key === '1') return;
      event.preventDefault();
      const kind = selected.dataset.reviewKind === 'fact' ? 'fact' : 'qa';
      const action = event.key === '2' ? `${kind}-edit` : `${kind}-decision`;
      const result = store.dispatch(action, { id: selected.dataset.qaId, review: true, decision: event.key === '1' ? 'approve' : 'no-answer' });
      if (result.ok) app.querySelector(`.knowledge-review-item[data-qa-id="${CSS.escape(selected.dataset.qaId)}"]`)?.focus();
      return;
    }
  }
  if (store.state.ui.page === 'flow' && store.state.ui.flowView === 'list' && event.target.matches?.('[data-flow-row]') && ['ArrowUp', 'ArrowDown', 'Enter'].includes(event.key)) {
    event.preventDefault();
    if (event.key === 'Enter') { store.dispatch('flow-select-node', { id: event.target.dataset.id }); return; }
    const rows = [...app.querySelectorAll('[data-flow-row]')];
    rows[(rows.indexOf(event.target) + (event.key === 'ArrowDown' ? 1 : -1) + rows.length) % rows.length]?.focus(); return;
  }
  if (store.state.ui.page === 'flow' && store.state.ui.flowView !== 'list' && event.target.matches?.('.flow-diagram-scroll') && ['ArrowLeft', 'ArrowRight'].includes(event.key)) {
    event.preventDefault();
    event.target.scrollLeft += (event.key === 'ArrowRight' ? 1 : -1) * Math.max(80, event.target.clientWidth * 0.65);
    return;
  }
  if (event.key === 'Escape' && store.state.ui.materials.preview) { event.preventDefault(); store.dispatch('material-preview-close'); return; }
  if (event.key === 'Escape' && store.state.ui.navOpen) { event.preventDefault(); store.dispatch('toggle-nav'); app.querySelector('.mobile-menu [data-action="toggle-nav"]')?.focus(); }
  if (event.key === 'Tab' && store.state.ui.navOpen && window.innerWidth < 1024) {
    const elements = [...app.querySelectorAll('.sidebar button:not(:disabled), .sidebar a[href], .sidebar select:not(:disabled)')].filter(element => element.getClientRects().length);
    const first = elements[0]; const last = elements.at(-1);
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
    if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
  }
});
function restoreNavigation() {
  if (!location.hash.startsWith('#/')) return;
  navigation.restore(); render();
}
window.addEventListener('hashchange', restoreNavigation);
window.addEventListener('popstate', restoreNavigation);
window.addEventListener('beforeunload', () => { if (preserveOnExit) store.save(); });
window.__loomriseDemo = { store, readiness, reset() { preserveOnExit = false; browserStorage.removeItem?.('loomrise:console-next:v1'); history.replaceState(null, '', '#/agents'); location.reload(); } };
navigation.restore(); render();
materialsController.contextChanged();
visitorController.contextChanged();
materialsController.reconcileFiles();
