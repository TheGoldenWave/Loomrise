import { escapeHtml, attr, badge, button, field, section, emptyState, formatTime } from '../helpers.js';
import { materialAllowed, materialSearch } from '../material-domain.js';
import { validDate } from '../domain.js';

const e = escapeHtml;
const a = attr;
const list = value => Array.isArray(value) ? value : [];
const kinds = { image: '图片', video: '视频', document: '文档' };
const statuses = { draft: ['草稿', 'neutral'], published: ['已发布（本地）', 'success'], revoked: ['已撤回', 'warning'] };
const historyLabels = { created: '登记物料草稿', updated: '保存物料新修订', 'summary-reviewed': '人工审阅定位简介', published: '发布物料（本地）', revoked: '撤回物料', 'summary-candidate-simulation': '登记元数据简介候选（模拟）', 'summary-candidate-applied': '采用候选为待审简介', 'summary-simulation-failed': '简介建议处理失败（模拟）', 'compression-simulation': '登记压缩候选（模拟）', 'compression-simulation-failed': '压缩处理失败（模拟）' };
const uiOf = state => state.ui.materials || {};
const sizeLabel = size => !Number.isFinite(Number(size)) || size == null ? '未产生文件' : Number(size) < 1024 ? `${Number(size)} B` : Number(size) < 1024 * 1024 ? `${(Number(size) / 1024).toFixed(1)} KB` : `${(Number(size) / (1024 * 1024)).toFixed(1)} MB`;
const detailList = entries => `<dl class="detail-list">${entries.map(([label, value]) => `<div><dt>${e(label)}</dt><dd>${e(value ?? '未填写')}</dd></div>`).join('')}</dl>`;
const statusBadge = asset => badge(...(statuses[asset.status] || statuses.draft));
const submit = (label, disabled) => `<button type="submit" class="btn btn-primary"${disabled ? ' disabled' : ''}>${e(label)}</button>`;
const fileButton = (action, label, { variant = 'original', ...options } = {}) => button(action, label, options).replace('data-action=', `data-variant="${a(variant)}" data-action=`);

function input(label, name, value = '', options = {}) {
  const { type = 'text', readonly = false, required = false, help = '', placeholder = '', rows = 3, extra = '', choices } = options;
  const id = `material-${name.replace(/[^\w-]/g, '-')}`;
  const common = `id="${a(id)}" name="${a(name)}"${readonly ? ' disabled' : ''}${required ? ' required' : ''}${help ? ` aria-describedby="${a(id)}-help"` : ''} ${extra}`;
  const control = choices ? `<select class="control" ${common}>${choices.map(([key, text]) => `<option value="${a(key)}"${String(key) === String(value) ? ' selected' : ''}>${e(text)}</option>`).join('')}</select>` : type === 'textarea' ? `<textarea class="control textarea" ${common} rows="${Number(rows)}" placeholder="${a(placeholder)}">${e(value)}</textarea>` : `<input class="control" type="${a(type)}" ${common}${type !== 'file' ? ` value="${a(value)}"` : ''} placeholder="${a(placeholder)}">`;
  return `<div class="field"><label for="${a(id)}">${e(label)}</label>${control}${help ? `<p class="helper" id="${a(id)}-help">${e(help)}</p>` : ''}</div>`;
}

function checkbox(label, name, checked, readonly, help = '') {
  return `<label class="checkbox-field"><input type="checkbox" name="${a(name)}"${checked ? ' checked' : ''}${readonly ? ' disabled' : ''}><span>${e(label)}${help ? `<small class="helper">${e(help)}</small>` : ''}</span></label>`;
}

function scopeLabel(state, asset) {
  if (asset.scope === 'workspace') return '工作区全部专家';
  const names = list(asset.agentIds).map(id => state.agents.find(agent => agent.id === id)?.name || id);
  return names.length ? names.join('、') : '尚未指定专家';
}

function unavailableReason(asset, agentId) {
  if (asset.status === 'revoked') return '已撤回，不能用于新的发送';
  if (asset.status !== 'published') return '先审阅简介并发布物料';
  if (!asset.rights || !asset.sourceRef) return '缺少来源或使用授权';
  if (!asset.expires || !/^\d{4}-\d{2}-\d{2}$/.test(asset.expires)) return '有效期未确认';
  if (asset.expires < new Date().toISOString().slice(0, 10)) return '使用授权已过期';
  if (asset.scope !== 'workspace' && !list(asset.agentIds).includes(agentId)) return '不在当前专家的可用范围';
  if (!asset.summary?.reviewed || !asset.summary.text?.trim() || asset.summary.baseRevision !== asset.revision) return '定位简介尚未人工审阅';
  if (!asset.canSend) return '此物料未允许会话发送';
  if (!originalAvailable(asset)) return '原件缓存不可用，请重新上传';
  return '';
}

function originalAvailable(asset) {
  return Boolean(asset.original?.available && asset.original?.blobKey);
}

function originalActions(asset) {
  const available = originalAvailable(asset);
  return `<div class="button-group">${fileButton('material-preview', '预览原件', { id: asset.id, variant: 'original', blobKey: asset.original?.blobKey || '', disabled: !available, title: available ? '读取当前浏览器中的原件' : '当前没有可读取的本地原件' })}${fileButton('material-preview', '下载原件', { id: asset.id, variant: 'original', blobKey: asset.original?.blobKey || '', mode: 'download', filename: asset.filename, disabled: !available })}</div>`;
}

function libraryHeading(title, description, actions = '') {
  return '<header class="page-header"><div><h1 data-library-heading tabindex="-1">' + e(title) + '</h1>' + (description ? '<p>' + e(description) + '</p>' : '') + '</div><div class="inline">' + actions + '</div></header>';
}

function materialGaps(asset, state, agentId) {
  const gaps = [];
  if (asset.status === 'revoked') return ['已撤回，阻断新的检索与发送'];
  if (!originalAvailable(asset)) gaps.push('原件缓存缺失，请重新上传');
  if (!asset.rights || !String(asset.sourceRef || '').trim()) gaps.push('待补齐来源与使用授权');
  if (!validDate(asset.expires)) gaps.push('有效期尚未确认');
  else if (asset.expires < new Date().toISOString().slice(0, 10)) gaps.push('使用授权已过期');
  if (!['selected', 'workspace'].includes(asset.scope) || (asset.scope === 'selected' && (!list(asset.agentIds).length || list(asset.agentIds).some(id => !state.agents.some(agent => agent.id === id))))) gaps.push('可用专家范围无效');
  else if (agentId && asset.scope !== 'workspace' && !list(asset.agentIds).includes(agentId)) gaps.push('不在当前专家的可用范围');
  if (!asset.summary?.text?.trim()) gaps.push('待填写定位简介');
  else if (!asset.summary.reviewed || asset.summary.baseRevision !== asset.revision) gaps.push('当前简介待人工审阅');
  if (asset.status !== 'published') gaps.push('尚未发布');
  if (!asset.canSend) gaps.push('未允许会话发送');
  return gaps;
}

function availability(ctx, asset) {
  const gaps = materialGaps(asset, ctx.state, ctx.agent?.id);
  if (asset.status === 'revoked') return { label: '已撤回', tone: 'warning', gaps };
  if (gaps.length) return { label: asset.status === 'published' ? '当前不可发送' : '待完善', tone: 'warning', gaps };
  if (!ctx.agent) return { label: '待选择专家', tone: 'neutral', gaps: ['顶部选择专家后核验可用范围'] };
  if (!materialAllowed(asset, ctx.agent.id)) return { label: '当前不可发送', tone: 'warning', gaps: ['授权或当前简介修订无效'] };
  return { label: '当前专家可发送', tone: 'success', gaps: [] };
}

function materialDisclosure(asset, key, title, body) {
  return '<details class="library-disclosure" data-disclosure-key="material-' + a(asset.id) + '-' + a(key) + '"><summary>' + e(title) + '</summary>' + body + '</details>';
}

function materialForm(ctx) {
  const { state, readonly } = ctx;
  const ui = uiOf(state);
  const existing = list(state.materials).find(asset => asset.id === ui.editingId);
  const upload = ui.upload;
  const busy = ['saving', 'reading', 'uploading', 'processing'].includes(ui.uploadStatus);
  const locked = readonly || busy;
  const selectedAgents = existing ? list(existing.agentIds) : ctx.agent ? [ctx.agent.id] : [];
  const scope = existing?.scope || 'selected';
  const fileStatus = busy ? '<p class="library-hint" aria-busy="true">正在保存原件…离开或重新选择文件会取消旧读取。</p>' : upload ? '<p class="library-hint">已自动保存：' + e(upload.filename) + ' · ' + e(kinds[upload.kind] || '文件') + ' · ' + e(sizeLabel(upload.size)) + '</p>' : existing ? '<p class="library-hint">当前原件：' + e(existing.filename) + ' · ' + e(sizeLabel(existing.original?.size)) + '。替换文件后需重新审阅与发布。</p>' : '<p class="library-hint">原件保存在当前浏览器；自动保存后仍需审阅与发布。</p>';
  const content = input(existing ? '替换原件（可选）' : '选择原件', 'file', '', { type: 'file', readonly: locked, extra: 'data-material-file accept=".png,.jpg,.jpeg,.webp,.gif,.mp4,.webm,.mov,.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.md,.csv,.rtf,.odt,.ods,.odp"', help: '图片、视频或文档；SVG 与 HTML 不作为可执行内容载入。' }) + fileStatus + input('物料名称', 'title', existing?.title || upload?.filename || '', { readonly: locked, required: true, placeholder: '例如：课程介绍视频' }) + input('定位简介', 'description', existing?.summary?.text || '', { type: 'textarea', rows: 4, readonly: locked, placeholder: '说明文件内容、适用场景和不适用条件', help: '帮助智能客服找到并选择文件。可人工填写，保存后审阅；不自动成为知识答疑事实。' });
  const authorization = '<div class="grid-2">' + input('来源引用', 'sourceRef', existing?.sourceRef || '', { readonly: locked, required: true, placeholder: '自有手册 / 授权记录', help: '填写可追溯的来源。' }) + input('有效期至', 'expires', existing?.expires || '', { type: 'date', readonly: locked, required: true }) + '</div>' + checkbox('我确认有权在所选范围使用和发送此物料', 'rights', Boolean(existing?.rights), locked, '简介或处理候选不能代替业务授权。') + input('可用专家范围', 'scope', scope, { readonly: locked, choices: [['selected', '指定专家'], ['workspace', '工作区全部专家']], help: '文件属于工作区，默认仅当前专家可用。' }) + '<fieldset class="material-agent-scope" data-material-scope-target' + (locked || scope === 'workspace' ? ' disabled' : '') + (scope === 'workspace' ? ' hidden' : '') + '><legend>指定专家</legend>' + (list(state.agents).length ? state.agents.map(agent => '<label class="checkbox-field"><input type="checkbox" name="agentIds" value="' + a(agent.id) + '"' + (selectedAgents.includes(agent.id) ? ' checked' : '') + '><span>' + e(agent.name) + '</span></label>').join('') : '<p class="helper">暂无专家。可选择工作区全部专家保存草稿，创建专家后再修订范围。</p>') + '</fieldset>';
  const advanced = '<details class="library-disclosure" data-disclosure-key="material-form-' + a(existing?.id || 'new') + '-advanced"><summary>标签、适用说明与发送权限</summary><div class="grid-2">' + input('标签', 'tags', list(existing?.tags).join(', '), { readonly: locked, placeholder: '课程介绍, 家长, 入门', help: '多个标签用逗号分隔。' }) + input('适用说明', 'usage', existing?.usage || '', { readonly: locked, placeholder: '例如：访客明确索取课程手册时使用' }) + '</div>' + checkbox('允许在会话中发送', 'canSend', existing ? Boolean(existing.canSend) : true, locked) + checkbox('允许智能客服按策略自动选择并发送', 'autoSendAllowed', Boolean(existing?.autoSendAllowed), locked, '默认关闭。还需专家开启策略、物料发布和简介审阅；发送前重新核验。') + '</details>';
  return '<div class="library-back">' + button('material-form-toggle', existing ? '返回物料详情' : '返回物料列表', { variant: 'ghost' }) + '</div>' + libraryHeading(existing ? '修订物料' : '录入物料', existing ? '保存为新修订，历史会话中的附件保持原记录。' : '先录入原件与业务授权，再审阅简介和发布。') + '<section class="section library-panel library-focus material-form-panel" tabindex="-1"><form data-form="material-upsert" class="stack"><input type="hidden" name="id" value="' + a(existing?.id || '') + '"><input type="hidden" name="session" value="' + a(ui.session || 0) + '">' + (ui.error ? '<p class="notice notice-danger" role="alert">' + e(ui.error) + '<br>重新选择文件或修正登记信息后保存。</p>' : '') + '<div class="library-form-group"><h2>文件与内容</h2>' + content + '</div><div class="library-form-group"><h2>来源授权与可用范围</h2>' + authorization + '</div>' + advanced + '<div class="library-actions">' + submit(existing ? '保存新修订' : '保存物料草稿', locked || (!existing && !upload)) + button('material-form-toggle', existing ? '取消修订' : '取消录入') + '</div></form></section>';
}

function processingBlock(asset, readonly) {
  const compression = asset.processing?.compression || 'none';
  const understanding = asset.processing?.understanding || 'none';
  const canCompress = ['image', 'video'].includes(asset.kind);
  const compressionText = ({ none: canCompress ? '尚未演示' : '此类型保留原件', 'mock-ready': '模拟候选已登记，无真实文件', failed: '模拟压缩失败，原件仍保留', processing: '正在演示', pending: '等待演示' })[compression] || compression;
  const understandingText = ({ none: '尚无建议候选', candidate: '元数据候选待审阅', failed: '模拟简介处理失败', processing: '正在演示', pending: '等待演示' })[understanding] || understanding;
  const busy = ['processing', 'pending'].includes(compression) || ['processing', 'pending'].includes(understanding);
  return `<div class="material-processing"${busy ? ' aria-busy="true"' : ''}>${detailList([['图片 / 视频压缩', compressionText], ['简介建议', understandingText]])}<div class="button-group">${canCompress ? button('material-compress-demo', compression === 'failed' ? '重试压缩候选（模拟）' : '演示压缩候选', { id: asset.id, disabled: readonly || busy }) : ''}${canCompress ? button('material-compress-fail', '演示压缩失败', { id: asset.id, disabled: readonly || busy, variant: 'ghost' }) : ''}${button('material-summary-demo', understanding === 'failed' ? '重试简介候选（模拟）' : '生成简介候选（模拟）', { id: asset.id, disabled: readonly || busy })}${button('material-summary-fail', '演示简介失败', { id: asset.id, disabled: readonly || busy, variant: 'ghost' })}</div><p class="helper">压缩仅演示处理状态，不重编码、不生成压缩文件；简介候选仅依据登记信息建议，未理解图片或视频内容。</p></div>`;
}

function materialDetail(ctx, asset) {
  const { state, agent } = ctx;
  const readonly = ctx.readonly || asset.status === 'revoked';
  const summary = asset.summary || {};
  const summaryReviewed = summary.reviewed && summary.baseRevision === asset.revision;
  const current = availability(ctx, asset);
  const publishGaps = materialGaps(asset, state).filter(gap => !['尚未发布', '未允许会话发送'].includes(gap));
  const publishable = !publishGaps.length && asset.status !== 'revoked';
  const variants = list(asset.variants).filter(variant => variant.id !== 'original');
  let nextAction = '';
  let nextActionKind = '';
  if (!readonly) {
    if (publishGaps.some(gap => gap !== '当前简介待人工审阅')) nextAction = button('material-edit', '完善物料信息', { id: asset.id, variant: 'primary' });
    else if (!summaryReviewed) { nextAction = button('material-review-summary', '人工审阅当前简介', { id: asset.id, variant: 'primary', disabled: !summary.text?.trim() }); nextActionKind = 'review'; }
    else if (asset.status !== 'published') nextAction = button('material-publish', '发布物料（本地）', { id: asset.id, variant: 'primary', disabled: !publishable });
    else if (!asset.canSend) nextAction = button('material-edit', '调整发送权限', { id: asset.id, variant: 'primary' });
  }
  const trialActions = asset.status === 'published' && !current.gaps.length && agent ? '<div class="library-actions">' + button('navigate', '到客服试用台体验', { page: 'trial' }) + button('navigate', '网站客服窗访客预览', { page: 'widget' }) + '</div>' + (!asset.autoSendAllowed || agent.config.materialPolicy?.enabled !== true ? '<p class="library-hint">智能客服自动发送还需此物料授权与当前专家策略均开启。</p>' : '') : '';
  const visibleStatus = '<div class="library-summary material-ready-summary"><div class="inline">' + badge(current.label, current.tone) + badge(asset.status === 'published' ? '已发布（本地）' : asset.status === 'revoked' ? '已撤回' : '草稿') + (asset.fictional ? badge('虚构元数据示例', 'warning') : '') + '</div><p class="library-hint">' + e(current.gaps.length ? current.gaps.join('；') : '原件、授权、范围与简介当前有效，发送时仍读取文件并重新核验。') + '</p>' + (nextAction ? '<div class="library-actions">' + nextAction + '</div>' : '') + trialActions + '</div>';
  const original = '<div class="material-detail-section"><h2>原件</h2><div class="material-file-row"><div><strong>' + e(asset.filename || '未登记文件') + '</strong><p class="helper">' + e(kinds[asset.kind] || '文件') + ' · ' + e(sizeLabel(asset.original?.size)) + ' · ' + (originalAvailable(asset) ? '当前浏览器缓存' : '原件缓存缺失') + '</p></div>' + originalActions(asset) + '</div>' + (!originalAvailable(asset) ? '<p class="library-hint material-gap">重新上传授权原件后才可预览、下载和发送。</p>' : '') + '</div>';
  const description = '<div class="material-detail-section"><div class="material-content-heading"><h2>定位简介</h2>' + badge(summaryReviewed ? '当前简介已审阅' : '待人工审阅', summaryReviewed ? 'success' : 'warning') + '</div><p class="source-text material-description">' + e(summary.text || '尚未填写定位简介。修订物料后可直接人工填写。') + '</p><p class="library-hint">' + (summary.origin === 'simulation' ? '采用了元数据模拟建议，未读取或理解文件内容。' : '人工填写的摘要。') + '用于定位文件与判断用途，不自动成为知识答疑事实。</p>' + (summary.candidate ? '<div class="material-candidate"><strong>待采用的简介候选（模拟）</strong><p class="source-text">' + e(summary.candidate) + '</p><p class="helper">仅依据登记信息建议；采用后仍需人工审阅。</p>' + button('material-apply-summary', '采用候选为待审简介', { id: asset.id, disabled: readonly }) + '</div>' : '') + '<div class="library-actions">' + button('material-edit', '人工编辑简介', { id: asset.id, disabled: readonly }) + (!summaryReviewed && nextActionKind !== 'review' ? button('material-review-summary', '人工审阅当前简介', { id: asset.id, disabled: readonly || !summary.text?.trim() }) : '') + (summaryReviewed ? '<span class="helper">后续修订需重新审阅与发布。</span>' : '') + '</div></div>';
  const authorization = materialDisclosure(asset, 'authorization', '来源授权、范围与发送权限', detailList([['来源引用', asset.sourceRef || '缺少来源'], ['使用授权', asset.rights ? '业务人员已声明' : '尚未声明'], ['有效期', asset.expires || '未确认'], ['可用范围', scopeLabel(state, asset)], ['会话发送', asset.canSend ? '允许，发送前重新核验' : '禁止发送'], ['智能客服自动发送', asset.autoSendAllowed ? '已允许，仍受当前专家策略约束' : '此物料未允许'], ['标签', list(asset.tags).join('、') || '未填写'], ['适用说明', asset.usage || '未填写']]) + button('material-edit', '修订授权与用途', { id: asset.id, disabled: readonly }));
  const derived = materialDisclosure(asset, 'variants', '派生版本（' + variants.length + '）', variants.length ? variants.map(variant => '<div class="material-file-row"><div><strong>' + e(variant.label || variant.id) + '</strong><p class="helper">' + (variant.simulated ? '模拟记录，无真实文件，不能预览或下载' : e(sizeLabel(variant.size))) + '</p></div>' + badge(variant.simulated ? '仅状态演示' : '派生版本', variant.simulated ? 'warning' : 'neutral') + '</div>').join('') : '<p class="library-hint">尚无派生版本。原件独立保留，真实压缩服务待接入。</p>');
  const processing = materialDisclosure(asset, 'processing', '后处理演示：压缩与简介建议', processingBlock(asset, readonly));
  const history = materialDisclosure(asset, 'history', '修订与操作记录（' + list(asset.history).length + '）', list(asset.history).length ? '<ol class="timeline">' + asset.history.map(item => '<li class="timeline-item"><strong>' + e(item.text || historyLabels[item.action] || '本地操作') + '</strong><p class="helper">' + e(item.time || item.createdAt ? formatTime(item.time || item.createdAt) : '时间未登记') + (item.revision ? ' · r' + e(item.revision) : '') + '</p></li>').join('') + '</ol>' : '<p class="library-hint">尚无操作记录。</p>');
  const manage = materialDisclosure(asset, 'management', '撤回与重新登记', '<p class="library-hint">撤回后阻断新的检索和发送，历史会话附件保留发送时快照。再次使用需重新登记并确认授权。</p><div class="library-actions">' + button('material-revoke', '撤回物料', { id: asset.id, disabled: readonly || asset.status === 'revoked', variant: 'danger' }) + (asset.status === 'revoked' ? button('material-form-toggle', '重新录入物料', { disabled: ctx.readonly }) : '') + '</div>');
  const processingFailed = asset.processing?.compression === 'failed' || asset.processing?.understanding === 'failed';
  return '<div class="library-back">' + button('material-list', '返回物料列表', { variant: 'ghost' }) + '</div>' + libraryHeading(asset.title || asset.filename || '物料详情', 'r' + (asset.revision || 1) + ' · ' + scopeLabel(state, asset), button('material-edit', '修订物料', { id: asset.id, disabled: readonly })) + '<section class="section library-panel library-focus material-detail" tabindex="-1">' + visibleStatus + original + description + (processingFailed ? '<p class="library-hint material-gap">后处理演示失败，原件未丢失；展开“后处理演示”可重试。</p>' : '') + authorization + derived + processing + history + manage + '<p class="library-hint material-boundary">原件预览与下载读取本地缓存；发布、处理和发送为前端演示，未接服务端文件库或外部渠道。</p></section>';
}

function filterControl(label, path, value, choices, placeholder = '') {
  return input(label, `filter-${path}`, value, { choices, placeholder, extra: `data-action="material-filter" data-path="${a(path)}" data-ui-bind="materials.${a(path)}"` });
}

function policyBlock(ctx) {
  const { agent, state, readonly } = ctx;
  if (!agent) return '<details class="library-disclosure material-policy" data-disclosure-key="material-policy-no-agent"><summary>专家自动发送策略 · 尚未选择专家</summary><p class="library-hint">顶部选择专家后配置。物料属于工作区，发送策略属于各专家草稿。</p></details>';
  const policy = agent.config.materialPolicy || {};
  const ui = uiOf(state);
  const results = list(ui.autoResults);
  const countField = field('单次最多附件数', 'materialPolicy.maxCount', policy.maxCount ?? 1, { type: 'number', readonly, help: '本地演示支持 1–5 个，发送前逐项校验。' }).replace('name="materialPolicy.maxCount"', 'name="materialPolicy.maxCount" min="1" max="5" step="1"');
  const core = '<div class="grid-2 material-policy-core">' + field('开启物料自动发送', 'materialPolicy.enabled', Boolean(policy.enabled), { type: 'checkbox', readonly, help: '默认关闭，仅作用于当前专家草稿的本地模拟。' }) + field('要求访客明确索取', 'materialPolicy.requireExplicitRequest', policy.requireExplicitRequest !== false, { type: 'checkbox', readonly }) + countField + '</div>';
  const versions = '<details class="library-disclosure" data-disclosure-key="material-policy-' + a(agent.id) + '-versions"><summary>发送版本与原件回退</summary><div class="grid-2">' + field('优先版本', 'materialPolicy.preferredVariant', policy.preferredVariant || 'original', { type: 'select', readonly, options: [['original', '原件'], ['compressed-demo', '模拟压缩候选（无真实文件）']] }) + field('候选不可用时允许原件回退', 'materialPolicy.allowOriginalFallback', policy.allowOriginalFallback !== false, { type: 'checkbox', readonly }) + '</div><p class="library-hint">模拟压缩候选没有真实文件。访客发送需要可读取的原件或实际文件版本。</p></details>';
  const retrieval = '<div class="material-retrieval"><h3>检索与试用</h3><form data-form="material-retrieve"><input type="hidden" name="agentId" value="' + a(agent.id) + '">' + filterControl('检索测试', 'autoQuery', ui.autoQuery || '', null, '名称、标签或定位简介中的词') + '<div class="library-actions">' + button('material-auto-retrieve', '测试当前专家可检索物料', { disabled: readonly }) + '</div></form>' + (results.length ? '<ul class="material-search-results">' + results.map(result => { const asset = typeof result === 'string' ? list(state.materials).find(item => item.id === result) : result; return '<li><div><strong>' + e(asset?.title || asset?.filename || result?.title || '检索记录') + '</strong><p class="helper">' + e(asset?.summary?.text || (typeof asset?.summary === 'string' ? asset.summary : '') || '定位简介未登记') + '</p></div>' + (asset?.id ? button('material-detail', '详情', { id: asset.id }) : '') + '</li>'; }).join('') + '</ul>' : '<p class="library-hint">筛选已发布、授权有效、当前专家范围内、简介已审阅且允许自动发送的物料，未做文件全文理解。</p>') + '<div class="library-actions">' + button('navigate', '客服试用台', { page: 'trial' }) + button('navigate', '网站客服窗访客预览', { page: 'widget' }) + button('navigate', '会话收件箱发送模拟', { page: 'inbox', variant: 'ghost' }) + '</div></div>';
  return '<details class="library-disclosure material-policy" data-disclosure-key="material-policy-' + a(agent.id) + '"><summary><span>专家自动发送策略 · ' + e(agent.name) + '</span>' + badge(policy.enabled === true ? '已开启（本地）' : '未开启', policy.enabled === true ? 'neutral' : 'neutral') + '</summary><div class="material-policy-body"><p class="library-hint">此策略和物料可用范围分别维护。正式发送仍需批准版本、权限与渠道服务；本轮无平台内智能体工作进程。</p>' + core + versions + retrieval + '</div></details>';
}

export function renderMaterials(ctx) {
  const { state, readonly } = ctx;
  const ui = uiOf(state);
  const all = list(state.materials);
  const selected = all.find(asset => asset.id === ui.detailId);
  const readOnlyHint = readonly ? '<p class="library-hint">只读预览：可查看和预览原件，不能修改物料或策略。</p>' : '';
  if (ui.form) return '<div class="library-workspace materials-workspace" data-library-surface="material-form">' + readOnlyHint + materialForm(ctx) + '</div>';
  if (selected) return '<div class="library-workspace materials-workspace" data-library-surface="material-detail">' + readOnlyHint + materialDetail(ctx, selected) + '</div>';
  const filtered = materialSearch(state, ui.query || '').filter(asset => (ui.kind === 'all' || !ui.kind || asset.kind === ui.kind) && (ui.status === 'all' || !ui.status || asset.status === ui.status));
  const rows = filtered.map(asset => {
    const current = availability(ctx, asset);
    const tags = list(asset.tags);
    const gaps = current.gaps.slice(0, 2).join('；') + (current.gaps.length > 2 ? '；另有 ' + (current.gaps.length - 2) + ' 项待完善' : '');
    return '<tr data-material-row="' + a(asset.id) + '"><td data-label="文件与简介" class="material-content-cell"><button type="button" class="btn btn-ghost table-link" data-action="material-detail" data-id="' + a(asset.id) + '">' + e(asset.title || asset.filename || '未命名物料') + '</button><p class="helper">' + e(kinds[asset.kind] || '文件') + ' · ' + e(sizeLabel(asset.original?.size)) + ' · ' + e(asset.filename || '未登记文件') + '</p><p class="material-summary-line">' + e(asset.summary?.text || '尚无定位简介') + '</p>' + (tags.length ? '<div class="material-tags">' + tags.slice(0, 2).map(tag => '<button type="button" class="material-tag" data-action="material-filter" data-path="query" data-value="' + a(tag) + '" title="按此标签搜索">' + e(tag) + '</button>').join('') + (tags.length > 2 ? '<span class="helper">另 ' + (tags.length - 2) + ' 个标签</span>' : '') + '</div>' : '') + '</td><td data-label="当前可用性" class="material-status-cell">' + badge(current.label, current.tone) + '<p class="helper">' + e(gaps || (asset.autoSendAllowed ? '物料允许智能客服发送，仍受专家策略约束' : '人工可发送，智能客服未授权')) + '</p></td><td data-label="可用范围" class="material-scope-cell">' + e(scopeLabel(state, asset)) + '</td><td data-label="操作"><div class="button-group">' + button('material-detail', '详情', { id: asset.id }) + button('material-edit', '修订', { id: asset.id, disabled: readonly || asset.status === 'revoked' }) + '</div></td></tr>';
  }).join('');
  const filters = '<div class="material-toolbar library-toolbar">' + filterControl('搜索物料', 'query', ui.query || '', null, '名称、简介、标签或用途') + filterControl('类型', 'kind', ui.kind || 'all', [['all', '全部类型'], ['image', '图片'], ['video', '视频'], ['document', '文档']]) + filterControl('发布状态', 'status', ui.status || 'all', [['all', '全部状态'], ['draft', '草稿'], ['published', '已发布（本地）'], ['revoked', '已撤回']]) + '</div>';
  const content = filtered.length ? '<div class="table-wrap"><table class="data-table material-table mobile-list"><thead><tr><th scope="col">文件与简介</th><th scope="col">当前可用性</th><th scope="col">可用范围</th><th scope="col">操作</th></tr></thead><tbody>' + rows + '</tbody></table></div>' : emptyState(all.length ? '没有匹配的物料' : '还没有物料', all.length ? '调整搜索、类型或发布状态。' : '录入授权文件，填写定位简介与可用范围后审阅、发布。', all.length ? button('material-list', '清空筛选', { reset: 'true' }) : button('material-form-toggle', '录入第一个物料', { disabled: readonly, variant: 'primary' }) + button('material-load-demo', '载入虚构元数据示例', { disabled: readonly }));
  const hasMaterialFilter = Boolean(ui.query || (ui.kind && ui.kind !== 'all') || (ui.status && ui.status !== 'all'));
  const showCollectionTools = all.length > 0 || hasMaterialFilter;
  const summary = showCollectionTools ? '<div class="library-summary material-list-summary"><span>' + filtered.length + ' / ' + all.length + ' 条物料</span><span>本地缓存可预览；处理、发布与发送为前端演示。</span></div>' : '';
  const listSurface = showCollectionTools ? '<section class="section library-panel">' + filters + summary + content + '</section>' : '<div class="material-empty-state">' + content + '<p class="helper">本地缓存只用于预览；处理、发布与发送仍为前端演示。</p></div>';
  return '<div class="library-workspace materials-workspace" data-library-surface="material-list">' + libraryHeading('物料库', '管理可发送给访客的图片、视频与文档，简介供智能客服定位文件。', button('material-form-toggle', '录入物料', { disabled: readonly, variant: 'primary' }) + button('navigate', '知识资料', { page: 'knowledge' })) + '<p class="library-context">工作区共享库 · 当前专家：' + e(ctx.agent?.name || '尚未选择') + '。可用范围按每条物料维护。</p>' + readOnlyHint + listSurface + policyBlock(ctx) + '</div>';
}

export function renderMaterialPicker(ctx) {
  const { state, agent, readonly } = ctx;
  const ui = uiOf(state);
  if (!ui.picker) return '';
  const context = ui.sendContext || {};
  const current = agent?.conversations?.find(conversation => conversation.id === state.ui.activeConversation);
  const validContext = Boolean(agent && current && context.agentId === agent.id && context.conversationId === current.id && Number(context.generation) === Number(current.generation) && (current.ownership || current.status) === 'human');
  const locked = readonly || !validContext;
  const assets = materialSearch(state, ui.pickerQuery || '');
  return section('选择会话物料', `<p class="helper">选择的是物料当前修订。发送时再次核验授权、有效期、专家范围、会话占用与修订；选择不表示已发送。</p>${!validContext ? '<p class="notice notice-warning">会话或接待占用已变化。关闭选择器，人工接管当前会话后重新选择。</p>' : ''}${filterControl('搜索可发送物料', 'pickerQuery', ui.pickerQuery || '', null, '物料名称、标签或简介')}${assets.length ? `<ul class="material-picker-list">${assets.map(asset => {
    const reason = unavailableReason(asset, agent?.id) || (!materialAllowed(asset, agent?.id) ? '物料授权或当前简介修订无效' : '');
    const selected = list(ui.selected).some(item => item.id === asset.id && item.variant === 'original');
    const compressed = list(asset.variants).find(variant => variant.id === 'compressed-demo');
    const compressedSelected = list(ui.selected).some(item => item.id === asset.id && item.variant === 'compressed-demo');
    return `<li><div class="material-picker-description"><div class="inline"><strong>${e(asset.title || asset.filename)}</strong>${badge(kinds[asset.kind] || '文件')}${statusBadge(asset)}</div><p class="helper">${e(asset.summary?.text || '尚未填写定位简介')}</p><p class="helper">${e(reason || '授权和范围当前有效；发送前仍重新校验。')}${!originalAvailable(asset) ? ' · 原件缓存不可用' : ''}</p></div><div class="button-group">${selected ? fileButton('material-unpick', '移除原件', { id: asset.id, variant: 'original', disabled: locked }) : fileButton('material-pick', '选择原件', { id: asset.id, variant: 'original', disabled: locked || Boolean(reason) || !originalAvailable(asset) })}${compressed ? compressedSelected ? fileButton('material-unpick', '移除模拟候选', { id: asset.id, variant: 'compressed-demo', disabled: locked }) : fileButton('material-pick', '选择模拟压缩候选', { id: asset.id, variant: 'compressed-demo', disabled: locked || Boolean(reason) || compressed.available !== true || asset.processing?.compression !== 'mock-ready' || !originalAvailable(asset), title: '仅记录模拟附件，不存在可下载的压缩文件' }) : ''}${fileButton('material-preview', '预览', { id: asset.id, variant: 'original', blobKey: asset.original?.blobKey || '', disabled: !originalAvailable(asset), variantLabel: '原件' })}</div></li>`;
  }).join('')}</ul>` : emptyState('没有匹配的物料', '调整搜索，或先到物料库录入和发布物料。', button('navigate', '打开物料库', { page: 'materials' }))}<div class="button-group">${button('material-picker-done', '完成选择', { variant: 'primary' })}<span class="helper">已选 ${list(ui.selected).length} 个附件</span></div>`, { className: 'material-picker', actions: button('material-picker-close', '关闭选择器') });
}

export function renderMaterialAttachments(attachments) {
  if (!list(attachments).length) return '';
  return `<div class="material-attachments" aria-label="消息附件快照">${attachments.map(item => {
    const available = !item.simulated && Boolean(item.blobKey);
    return `<article class="material-attachment"><div class="material-attachment-content"><div class="inline">${badge(kinds[item.kind] || '文件')}<strong>${e(item.title || item.name || item.filename || '附件')}</strong>${item.simulated ? badge('模拟附件，无真实派生文件', 'warning') : ''}</div><p class="helper">${e(item.filename || '文件名未登记')} · ${e(item.variantLabel || (item.variant === 'original' ? '原件' : item.variant || '原件'))} · r${e(item.revision || 1)}${item.size != null ? ` · ${e(sizeLabel(item.size))}` : ''}</p>${item.summary ? `<p class="material-attachment-summary">${e(typeof item.summary === 'string' ? item.summary : item.summary.text || '')}</p>` : ''}<p class="helper">已记录本地消息；外部送达未知。附件名称和简介保留发送时快照。</p></div><div class="button-group">${fileButton('material-preview', '预览附件', { id: item.id, variant: item.variant || 'original', blobKey: item.blobKey || '', filename: item.filename || '', snapshotTitle: item.title || item.name || item.filename || '附件', kind: item.kind || 'document', mimeType: item.mimeType || '', revision: item.revision, snapshot: 'true', disabled: !available })}${fileButton('material-preview', '下载附件', { id: item.id, variant: item.variant || 'original', blobKey: item.blobKey || '', filename: item.filename || '', kind: item.kind || 'document', mimeType: item.mimeType || '', mode: 'download', snapshot: 'true', disabled: !available })}</div></article>`;
  }).join('')}</div>`;
}

export function renderMaterialPreview(ctx) {
  const ui = uiOf(ctx.state);
  const preview = ui.preview;
  if (!preview) return '';
  const asset = list(ctx.state.materials).find(item => item.id === preview.id);
  const data = preview.snapshot ? preview : { ...asset, ...preview, blobKey: preview.blobKey || asset?.original?.blobKey };
  const blobKey = data.blobKey;
  const kind = data.kind || 'document';
  const mimeType = data.mimeType || '';
  const filename = data.filename || '附件';
  const safeImage = kind === 'image' && ['image/png', 'image/jpeg', 'image/webp', 'image/gif'].includes(mimeType);
  const safeVideo = kind === 'video' && ['video/mp4', 'video/webm', 'video/quicktime'].includes(mimeType);
  const safePDF = mimeType === 'application/pdf';
  const safeText = ['text/plain', 'text/markdown', 'text/csv'].includes(mimeType) || /\.(txt|md|csv)$/i.test(filename);
  const media = !blobKey ? '<p class="notice notice-warning">没有可读取的本地原件。模拟派生版本没有真实文件。</p>' : safeImage ? `<img class="material-preview-image" alt="${a(data.title || filename)}" data-material-blob="${a(blobKey)}" data-material-kind="image">` : safeVideo ? `<video class="material-preview-video" controls preload="metadata" data-material-blob="${a(blobKey)}" data-material-kind="video">当前浏览器不支持播放此视频，可下载原件查看。</video>` : safeText ? `<pre class="material-preview-text" data-material-text="${a(blobKey)}">正在读取文档正文…</pre>` : safePDF ? `<iframe class="material-preview-pdf" title="${a(filename)}" data-material-blob="${a(blobKey)}" data-material-kind="document"></iframe>` : '<div class="empty-state"><h3>此文档使用原应用打开</h3><p>浏览器不执行文件中的网页、脚本或宏。下载原件后用对应应用查看。</p></div>';
  return `<div class="material-preview-overlay"><section class="material-preview-dialog" role="dialog" aria-modal="true" aria-labelledby="material-preview-title" tabindex="-1"><div class="section-heading"><div><h2 id="material-preview-title">${e(data.title || filename)}</h2><p class="helper">${e(filename)} · ${e(mimeType || '文件类型未知')} · 当前浏览器原件</p></div>${button('material-preview-close', '关闭预览')}</div><p class="helper" data-material-cache-status aria-live="polite">${!blobKey ? '没有本地文件' : safeImage || safeVideo || safePDF || safeText ? '正在读取本地文件…' : '原件保存在当前浏览器；可下载后打开。'}</p><div class="material-preview-body">${media}</div><div class="button-group">${fileButton('material-preview', '下载原件', { id: data.id || '', variant: data.variant || 'original', blobKey: blobKey || '', filename, mode: 'download', disabled: !blobKey, snapshot: data.snapshot ? 'true' : '' })}${button('material-preview-close', '返回工作台')}</div></section></div>`;
}
