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

let browserStorage;
try { browserStorage = window.localStorage; } catch { browserStorage = { getItem() { throw new Error('存储不可用'); }, setItem() { throw new Error('存储不可用'); } }; }
const store = createStore(browserStorage);
const app = document.querySelector('#app');
let materialsController;
let visitorController;
function fileContext() {
  const { ui, selectedAgentId } = store.state;
  if (ui.page !== 'knowledge' || ui.sourceTab !== 'File' || !ui.sourceForm || store.readonly()) return null;
  return `${selectedAgentId}:${ui.sourceEdit || 'new'}:File`;
}
const fileReader = createLocalFileReader(fileContext);
let lastFileContext = fileContext();
const pages = { agents: renderAgents, create: renderCreate, overview: renderOverview, configuration: renderConfiguration, materials: renderMaterials, knowledge: renderKnowledge, trial: renderTrial, inbox: renderInbox, widget: renderWidget, contact: renderContact, connections: renderConnections, runs: renderRuns, cases: renderCases, iterations: renderIterations, versions: renderVersions, deployment: renderDeployment };
let toastTimer = null;
let suppressRoute = false;
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
    if (control.type === 'checkbox' && [...form.elements].filter(item => item.type === 'checkbox' && item.name === control.name).length > 1) {
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
      if (control.type === 'checkbox') control.checked = Array.isArray(values[control.name]) ? values[control.name].includes(control.value) : values[control.name]; else control.value = values[control.name];
    }
  }
}

function routeFromHash() {
  const [page, query = ''] = location.hash.replace(/^#\/?/, '').split('?');
  if (!page) return;
  const values = new URLSearchParams(query);
  const id = values.get('agent');
  if (id && store.state.agents.some(agent => agent.id === id) && id !== store.state.selectedAgentId) store.dispatch('select-agent', { id });
  if (pages[page]) store.dispatch('navigate', { page, section: values.get('section') || undefined });
}
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
  const identifier = focused?.dataset.bind ? ['bind', focused.dataset.bind] : focused?.dataset.uiBind ? ['ui-bind', focused.dataset.uiBind] : focused?.hasAttribute('data-agent-name') ? ['agent-name', ''] : null;
  const selection = focused && ['INPUT', 'TEXTAREA'].includes(focused.tagName) ? { start: focused.selectionStart, end: focused.selectionEnd } : null;
  const focusedForm = focused?.closest('[data-form]');
  const formFocus = !identifier && focusedForm && focused.name ? { key: formKey(focusedForm), name: focused.name } : null;
  const key = disclosureKey();
  const disclosures = { ...store.state.ui.disclosures?.[key] };
  if (renderedDisclosureKey === key) for (const detail of app.querySelectorAll('details')) disclosures[detailKey(detail)] = detail.open;
  store.state.ui.disclosures ||= {}; store.state.ui.disclosures[key] = disclosures;
  renderedDisclosureKey = key;
  const ctx = context();
  const nextLibrary = librarySurface(ctx);
  const previousLibrary = renderedLibrary;
  if (previousLibrary?.mode === 'list' && previousLibrary.key !== nextLibrary?.key) {
    libraryListPositions.set(previousLibrary.scope, window.scrollY);
  }
  const renderer = pages[ctx.state.ui.page] || renderAgents;
  let body;
  try { body = renderer(ctx); }
  catch (error) { console.error(error); body = emptyState('这个页面未能载入', '草稿仍在本地保留。返回专家列表后重试。', button('navigate', '返回列表', { page: 'agents' })); }
  const scoped = ['overview', 'configuration', 'knowledge', 'trial', 'widget', 'contact', 'inbox', 'runs', 'cases', 'iterations', 'versions', 'deployment'].includes(ctx.state.ui.page);
  if (scoped && !ctx.agent) body = emptyState('先选择一个专家', '创建或选择专家后，查看它的资料、配置和运行记录。', button('new-agent', '手动创建', { mode: 'manual', variant: 'primary' }));
  const withSide = ctx.agent && ['overview', 'configuration'].includes(ctx.state.ui.page);
  const side = withSide ? ctx.state.ui.sidePanel === 'assistant' && ctx.state.ui.assistantOpen ? renderAssistant(ctx) : preview(ctx) : '';
  app.innerHTML = renderShell(ctx, body, side) + renderMaterialPreview(ctx);
  materialsController?.hydrate();
  visitorController?.afterRender();
  restoreForms();
  syncMaterialScope();
  for (const detail of app.querySelectorAll('details')) if (detailKey(detail) in disclosures) detail.open = disclosures[detailKey(detail)];
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
  const hash = `#/${ctx.state.ui.page}?agent=${encodeURIComponent(ctx.state.selectedAgentId || '')}`;
  if (!suppressRoute && location.hash !== hash) history.replaceState(null, '', hash);
}
materialsController = createMaterialController({ store, app, render, formKey, preserveForm });
visitorController = createVisitorController({ store, app, materialController: materialsController });
store.subscribe(() => {
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
app.addEventListener('click', async event => {
  const target = event.target.closest('[data-action]'); if (!target || target.disabled || target.tagName === 'SELECT' || target.tagName === 'INPUT') return;
  const { action, ...data } = target.dataset;
  if ((action === 'material-preview' && data.mode !== 'download') || action === 'visitor-attachment-preview') materialPreviewReturn = actionSelector(target);
  if (await visitorController.click(action, data)) return;
  if (await materialsController.click(action, data)) return;
  if (action === 'export-config') { downloadConfig(); return; }
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
  if (action === 'preview-question') { store.dispatch('navigate', { page: 'trial' }); visitorController.start('trial', data.question); return; }
  store.dispatch(action, data);
  if (action === 'navigate' || action === 'select-agent' || action === 'new-agent') window.scrollTo({ top: 0 });
  if (action === 'toggle-nav' && store.state.ui.navOpen) requestAnimationFrame(() => app.querySelector('.sidebar button')?.focus());
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
  store.state.ui.disclosures ||= {};
  store.state.ui.disclosures[disclosureKey()] ||= {};
  store.state.ui.disclosures[disclosureKey()][detailKey(event.target)] = event.target.open;
  store.save();
}, true);
app.addEventListener('change', async event => {
  const target = event.target;
  if (await materialsController.change(target)) return;
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
  if (await visitorController.submit(form, values)) return;
  if (await materialsController.submit(form, values)) return;
  if (action === 'source' && values.type === 'File') {
    const meta = store.state.ui.sourceFileMeta;
    if (meta) { values.filename = meta.name; values.metadataOnly = meta.metadataOnly; values.title ||= meta.name; values.body ||= store.state.ui.sourceFileBody; }
  }
  if (action === 'create') values.mode ||= store.state.ui.createMode;
  const key = formKey(form);
  const result = store.dispatch(action, values);
  if (result.ok && store.state.ui.formDrafts) { delete store.state.ui.formDrafts[key]; store.save(); render(); }
});
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
  if (event.key === 'Escape' && store.state.ui.materials.preview) { event.preventDefault(); store.dispatch('material-preview-close'); return; }
  if (event.key === 'Escape' && store.state.ui.navOpen) { event.preventDefault(); store.dispatch('toggle-nav'); app.querySelector('[data-action="toggle-nav"]')?.focus(); }
  if (event.key === 'Tab' && store.state.ui.navOpen && window.innerWidth < 1024) {
    const elements = [...app.querySelectorAll('.sidebar button:not(:disabled), .sidebar a[href]')].filter(element => element.getClientRects().length);
    const first = elements[0]; const last = elements.at(-1);
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
    if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
  }
});
window.addEventListener('hashchange', () => {
  if (!location.hash.startsWith('#/')) return;
  suppressRoute = true; routeFromHash(); suppressRoute = false; render();
});
window.addEventListener('beforeunload', () => { if (preserveOnExit) store.save(); });
window.__loomriseDemo = { store, readiness, reset() { preserveOnExit = false; browserStorage.removeItem?.('loomrise:console-next:v1'); history.replaceState(null, '', '#/agents'); location.reload(); } };
suppressRoute = true; routeFromHash(); suppressRoute = false; render();
materialsController.contextChanged();
visitorController.contextChanged();
materialsController.reconcileFiles();
