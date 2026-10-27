import { escapeHtml, attr, badge, button, emptyState, pageHeading } from '../helpers.js';
import { sourceValid, validDate } from '../domain.js';
import { classifyCandidates, detectCandidateConflicts, factReferences, legacyQaItems, resolveFactReferences, sampleLowRisk, RULE_TEMPLATES, RULE_FIELDS, RULE_OPERATORS, RULE_ACTIONS, RULE_OPERATOR_LABELS, RULE_ACTION_LABELS, ruleHitCount } from '../knowledge-model.js';

const e = escapeHtml;
const a = attr;
const list = value => Array.isArray(value) ? value : [];
const typeNames = { FAQ: '问答', URL: '网页', File: '文件' };
const typeName = type => typeNames[type] || '资料';
const title = (text, description = '', actions = '') => pageHeading(text, description, actions).replace('<h1>', '<h1 data-library-heading tabindex="-1">');
const detailList = entries => `<dl class="detail-list">${entries.map(([label, value]) => `<div><dt>${e(label)}</dt><dd>${e(value ?? '未填写')}</dd></div>`).join('')}</dl>`;
const disclosureKey = (agent, source, name) => `knowledge:${agent.id}:${source.id}:v${source.version || 1}:${name}`;

function control(label, name, value = '', { type = 'text', required = false, help = '', placeholder = '', readonly = false, rows = 3, options = null, extra = '', idPrefix = 'surface' } = {}) {
  const id = `${idPrefix}-${name}`.replace(/[^a-zA-Z0-9_-]/g, '-');
  const attributes = `id="${a(id)}" name="${a(name)}"${required ? ' required' : ''}${readonly ? ' disabled' : ''}${help ? ` aria-describedby="${a(id)}-help"` : ''} ${extra}`;
  const input = options
    ? `<select class="input control" ${attributes}>${options.map(option => `<option value="${a(option.value)}"${String(value) === String(option.value) ? ' selected' : ''}>${e(option.label)}</option>`).join('')}</select>`
    : type === 'textarea'
      ? `<textarea class="textarea control" ${attributes} rows="${rows}" placeholder="${a(placeholder)}">${e(value)}</textarea>`
      : `<input class="input control" ${attributes} type="${a(type)}" value="${type === 'file' ? '' : a(value)}" placeholder="${a(placeholder)}">`;
  return `<div class="field"><label for="${a(id)}">${e(label)}${required ? '<span class="knowledge-required">（必填）</span>' : ''}</label>${input}${help ? `<p class="helper" id="${a(id)}-help">${e(help)}</p>` : ''}</div>`;
}

function sourceAvailability(source, agent) {
  const revoked = agent.revokedSourceIds || [];
  const today = new Date().toISOString().slice(0, 10);
  if (source.status === 'revoked' || revoked.includes(source.id)) return { filter: 'unavailable', label: '已撤回', tone: 'neutral', reason: '后续试用不再使用这条资料。' };
  if (!source.rights) return { filter: 'unavailable', label: '缺少授权', tone: 'warning', reason: '先确认该资料的客服使用授权。' };
  if (!source.sourceRef) return { filter: 'unavailable', label: '缺少来源', tone: 'warning', reason: '补充可追溯的来源引用。' };
  if (!validDate(source.expires)) return { filter: 'unavailable', label: '缺少有效期', tone: 'warning', reason: '补充有效的使用期限。' };
  if (source.expires < today) return { filter: 'unavailable', label: '授权已过期', tone: 'warning', reason: '修订资料并重新确认使用期限。' };
  if (source.metadataOnly) return { filter: 'pending', label: '仅登记 · 待接解析', tone: 'neutral', reason: source.type === 'URL' ? '页面地址已保存，网页抓取待接后端。' : '文件信息已保存，此格式解析待接后端。' };
  if (sourceValid(source, revoked, today)) return { filter: 'ready', label: '可用于脚本试用', tone: 'success', reason: '' };
  if (source.status === 'failed') return { filter: 'pending', label: '处理失败', tone: 'danger', reason: '可重试本地处理，再审阅内容。' };
  const states = {
    received: ['待处理', '登记解析结果，再审阅内容。'],
    parsed: ['解析已登记', '下一步提交人工审阅。'],
    review: ['待审阅', '核对内容后建立脚本索引。'],
  };
  const status = states[source.status] || ['待处理', '打开资料查看处理进度。'];
  return { filter: 'pending', label: status[0], tone: 'warning', reason: status[1] };
}

function availabilityCell(source, agent) {
  const status = sourceAvailability(source, agent);
  return `${badge(status.label, status.tone)}${status.reason ? `<p class="knowledge-status-note">${e(status.reason)}</p>` : ''}`;
}

function sourceForm(ctx) {
  const { state, agent, readonly } = ctx;
  const existing = list(agent.config.sources).find(source => source.id === state.ui.sourceEdit);
  const type = existing?.type || (typeNames[state.ui.sourceTab] ? state.ui.sourceTab : 'FAQ');
  const back = button('source-form-toggle', existing ? '返回资料详情' : '返回资料列表', { id: existing?.id || '', variant: 'ghost' });
  let contents = control('资料名称', 'title', existing?.title || '', { required: true, placeholder: type === 'FAQ' ? '例如：课程安排' : '便于团队识别的资料名', readonly });
  if (type === 'FAQ') contents += control('问题', 'question', existing?.question || '', { required: true, placeholder: '访客可能会怎样提问？', readonly }) + control('标准解答', 'answer', existing?.answer || '', { type: 'textarea', required: true, readonly, rows: 7 });
  if (type === 'URL') contents += control('授权网页地址', 'url', existing?.url || '', { type: 'url', required: true, placeholder: 'https://example.invalid/course', readonly, help: '只登记这个网页地址；网页抓取待接后端。' });
  if (type === 'File') {
    const filename = state.ui.sourceFileMeta?.name || existing?.filename || existing?.fileName;
    contents += control('选择本地文件', 'file', '', { type: 'file', readonly, extra: 'data-source-file accept=".txt,.md,.csv,.json,.pdf,.docx,.xlsx"', help: 'TXT / Markdown / CSV / JSON 可读取文本；PDF、DOCX、XLSX 暂只登记文件信息。文件不会上传。' });
    if (filename) contents += `<p class="knowledge-file-name">${e(state.ui.sourceFileMeta ? '已选择文件' : '已登记文件')}：${e(filename)}</p>`;
    contents += control('本地文本内容', 'body', existing?.body || state.ui.sourceFileBody || '', { type: 'textarea', readonly, rows: 8, extra: 'data-source-body', help: '可粘贴授权文本，也可选择文本文件填入后审阅。' });
  }
  const rights = `<label class="checkbox-field"><input type="checkbox" name="rights"${existing?.rights ? ' checked' : ''}${readonly ? ' disabled' : ''}><span>我确认有权在此客服场景中使用该资料</span></label><p class="helper">可先保存未授权草稿；确认授权后才能参与试用。</p>`;
  return `<div class="library-back">${back}<span>${e(agent.name)}</span></div>${title(`${existing ? '修订' : '添加'}${typeName(type)}资料`, existing ? '保存后生成新资料版本，重新处理与审阅。' : '填写内容与使用授权，保存后再审阅。')}<section class="library-panel library-focus knowledge-form-panel" tabindex="-1"><form data-form="source" class="knowledge-source-form"><input type="hidden" name="type" value="${a(type)}">${existing ? `<input type="hidden" name="id" value="${a(existing.id)}">` : ''}<fieldset class="library-form-group"><legend>资料内容</legend>${contents}</fieldset><fieldset class="library-form-group"><legend>来源与使用授权</legend><div class="grid-2">${control('来源引用', 'sourceRef', existing?.sourceRef || '', { required: true, readonly, placeholder: '例如：自有课程手册 2026-10' })}${control('有效期至', 'expires', existing?.expires || '', { type: 'date', required: true, readonly })}</div>${rights}</fieldset><div class="library-actions"><button class="btn btn-primary" type="submit"${readonly ? ' disabled' : ''}>${existing ? '保存新资料版本' : '登记资料'}</button>${button('source-form-toggle', '取消', { id: existing?.id || '' })}</div></form></section>`;
}

function sourceDetail(ctx, source) {
  const { agent, readonly } = ctx;
  const availability = sourceAvailability(source, agent);
  const revoked = source.status === 'revoked' || (agent.revokedSourceIds || []).includes(source.id);
  const steps = { received: ['parsed', '登记解析（模拟）'], parsed: ['review', '送审'], review: ['indexed', '审阅并建立脚本索引'] };
  const next = steps[source.status];
  const canProcess = !readonly && !revoked && !source.metadataOnly && availability.filter !== 'unavailable';
  const content = source.type === 'FAQ'
    ? `<div class="knowledge-question"><h2>问题</h2><p class="source-text">${e(source.question || '未填写问题')}</p></div><div class="knowledge-answer"><h2>标准解答</h2><p class="source-text">${e(source.answer || '尚未填写标准解答')}</p></div>`
    : source.type === 'URL'
      ? `<div class="knowledge-body"><h2>页面地址</h2><p class="source-text">${e(source.url || '未填写页面地址')}</p><p class="helper">仅登记页面地址；当前没有抓取到网页正文。</p></div>`
      : `<div class="knowledge-body"><h2>${source.body ? '文本内容' : '文件信息'}</h2>${source.filename || source.fileName ? `<p class="knowledge-file-name">${e(source.filename || source.fileName)}</p>` : ''}<p class="source-text">${e(source.body || '此文件已登记，尚无可读取文本。格式解析待接后端，可修订为授权文本或添加问答。')}</p></div>`;
  const nextAction = next ? button('source-stage', next[1], { id: source.id, stage: next[0], variant: 'primary', disabled: !canProcess }) : '';
  const primary = revoked ? '' : availability.filter === 'unavailable'
    ? button('source-edit', '补充来源与授权', { id: source.id, variant: 'primary', disabled: readonly })
    : source.status === 'failed' && !source.metadataOnly
      ? button('source-retry', '重试脚本处理', { id: source.id, variant: 'primary', disabled: readonly })
      : nextAction;
  const processing = `<p class="helper">以下仅记录本地脚本流程，真实解析与检索索引待接入。</p><ol class="knowledge-processing"><li><strong>登记解析</strong><span>确认已登记的资料或本地文本。</span></li><li><strong>送审</strong><span>由业务核对内容和使用范围。</span></li><li><strong>建立脚本索引</strong><span>用于当前专家的本地试用。</span></li></ol>${source.error ? `<p class="knowledge-processing-error">${e(source.error)}</p>` : ''}${!revoked && !source.metadataOnly && source.status !== 'failed' ? `<div class="library-actions">${button('source-stage', '演示处理失败', { id: source.id, stage: 'failed', disabled: readonly })}</div>` : ''}`;
  const management = `<p class="helper">撤回后从后续试用依据中移除；历史运行引用继续留存，回滚不能恢复已撤回授权。</p>${source.revokeNote ? `<p class="helper">${e(source.revokeNote)}</p>` : ''}<div class="library-actions">${!revoked ? button('source-revoke', '撤回资料', { id: source.id, variant: 'danger', disabled: readonly }) : ''}${button('source-remove', '移除登记', { id: source.id, variant: 'danger', disabled: readonly })}</div>`;
  return `<div class="library-back">${button('source-list', '返回资料列表', { id: source.id, variant: 'ghost' })}<span>${e(agent.name)}</span></div>${title(source.title || '资料详情', `${typeName(source.type)} · v${source.version || 1}`, button('source-edit', '修订资料', { id: source.id, disabled: readonly || revoked }))}<section class="library-panel library-focus knowledge-source-detail source-detail" tabindex="-1"><div class="knowledge-detail-status">${badge(availability.label, availability.tone)}${source.fictional ? badge('虚构示例', 'warning') : ''}${availability.reason ? `<span>${e(availability.reason)}</span>` : ''}</div>${content}<div class="knowledge-next-step">${availability.filter === 'ready' ? `<p>此资料已满足当前脚本试用条件。</p>${button('navigate', '去客服试用', { page: 'trial', variant: 'primary' })}` : `${source.metadataOnly ? '<p>当前仅登记信息。可添加问答或授权文本体验答疑，真实格式解析后续接入。</p>' : ''}${primary}`}</div><details class="library-disclosure" data-disclosure-key="${a(disclosureKey(agent, source, 'authorization'))}"><summary>来源、使用授权与版本</summary>${detailList([['所属专家', agent.name], ['来源引用', source.sourceRef || '缺少来源引用'], ['使用授权', source.rights && !revoked ? '已由业务声明' : '未声明或已撤回'], ['有效期', source.expires || '未登记'], ['资料版本', `v${source.version || 1}`]])}</details><details class="library-disclosure" data-disclosure-key="${a(disclosureKey(agent, source, 'processing'))}"><summary>${source.metadataOnly ? '查看登记限制与处理流程' : '处理流程与失败演示'}</summary>${processing}</details><details class="library-disclosure" data-disclosure-key="${a(disclosureKey(agent, source, 'management'))}"><summary>撤回与移除资料</summary>${management}</details></section>`;
}

function answerPreview(ctx, source) {
  const answer = String(source.answer || '尚未填写标准解答');
  const preview = answer.length > 180 ? answer.slice(0, 180).trimEnd() + '…' : answer;
  return `<details class="knowledge-answer-disclosure" data-disclosure-key="${a(disclosureKey(ctx.agent, source, 'answer'))}"><summary><span class="knowledge-answer-excerpt source-text">${e(preview)}</span><span class="knowledge-answer-expand"><span class="knowledge-expand-label">展开完整解答</span><span class="knowledge-collapse-label">收起解答</span></span></summary><p class="knowledge-answer-full source-text">${e(answer)}</p></details>`;
}

function sourceRows(ctx, sources, tab) {
  const { agent, readonly } = ctx;
  return sources.map(source => {
    const revoked = source.status === 'revoked' || (agent.revokedSourceIds || []).includes(source.id);
    const name = `<button type="button" class="btn btn-ghost table-link" data-action="source-detail" data-id="${a(source.id)}">${e(source.title || '未命名资料')}</button>${source.fictional ? '<span class="knowledge-fictional">虚构示例</span>' : ''}`;
    const actions = `<div class="knowledge-row-actions">${tab === 'FAQ' ? button('source-edit', '编辑问答', { id: source.id, disabled: readonly || revoked, variant: 'ghost' }) : ''}${button('source-detail', '详情', { id: source.id, variant: 'ghost' })}</div>`;
    if (tab === 'FAQ') return `<tr data-source-id="${a(source.id)}"><td class="knowledge-question-cell" data-label="问题">${name}<p class="source-text">${e(source.question || '尚未填写问题')}</p></td><td class="knowledge-answer-cell" data-label="标准解答">${answerPreview(ctx, source)}</td><td class="knowledge-status-cell" data-label="状态">${availabilityCell(source, agent)}</td><td class="knowledge-action-cell" data-label="操作">${actions}</td></tr>`;
    const location = tab === 'URL' ? source.url : source.filename || source.fileName || '本地文本';
    const excerpt = tab === 'File' && source.body ? `<p class="knowledge-file-excerpt">${e(source.body.slice(0, 130))}${source.body.length > 130 ? '…' : ''}</p>` : '';
    return `<tr data-source-id="${a(source.id)}"><td class="knowledge-content-cell" data-label="资料">${name}<p class="knowledge-location">${e(location || '未登记地址')}</p>${excerpt}</td><td class="knowledge-status-cell" data-label="状态">${availabilityCell(source, agent)}</td><td class="knowledge-action-cell" data-label="操作">${actions}</td></tr>`;
  }).join('');
}

function renderSourceLibrary(ctx) {
  const { state, agent, readonly } = ctx;
  if (!agent) return emptyState('先选择或创建一位专家', '知识资料作为这位专家的答疑依据。', button('navigate', '查看专家', { page: 'agents', variant: 'primary' }));
  const hint = `<p class="library-hint">${readonly ? '只读预览 · ' : ''}本地演示：内容保存在当前浏览器；网页抓取、文档解析与真实检索待接入。</p>`;
  if (state.ui.sourceForm) return `<div class="library-workspace knowledge-workspace">${sourceForm(ctx)}${hint}</div>`;
  const sources = list(agent.config.sources);
  const selected = sources.find(source => source.id === state.ui.sourceDetail);
  if (selected) return `<div class="library-workspace knowledge-workspace">${sourceDetail(ctx, selected)}${hint}</div>`;
  const tab = typeNames[state.ui.sourceTab] ? state.ui.sourceTab : 'FAQ';
  const search = String(state.ui.search || '').trim().toLowerCase();
  const filter = ['ready', 'pending', 'unavailable'].includes(state.ui.sourceFilter) ? state.ui.sourceFilter : 'all';
  const ofType = sources.filter(source => source.type === tab);
  const filtered = ofType.filter(source => {
    const haystack = [source.title, source.question, source.answer, source.url, source.filename, source.fileName, source.body, source.sourceRef].filter(Boolean).join(' ').toLowerCase();
    return haystack.includes(search) && (filter === 'all' || sourceAvailability(source, agent).filter === filter);
  });
  const count = kind => sources.filter(source => sourceAvailability(source, agent).filter === kind).length;
  const noMatch = ofType.length > 0 && (search || filter !== 'all');
  const emptyDescription = noMatch ? '调整搜索词或状态筛选，查看已有资料。' : readonly
    ? `${state.ui.previewVersionId ? '正在查看冻结版本' : '只读预览中'}不能添加资料；返回可编辑草稿后可补充授权内容。`
    : '添加授权内容，保存后核对内容并审阅。';
  const emptyActions = noMatch ? button('source-clear', '清除筛选', { variant: 'primary' }) : readonly
    ? button('readonly-toggle', '返回可编辑草稿', { variant: 'primary' })
    : `${button('source-form-toggle', `添加${typeName(tab)}资料`, { variant: 'primary' })}${tab === 'FAQ' ? button('load-demo-sources', '载入虚构示例') : ''}`;
  const toolbar = `<div class="library-toolbar"><div class="library-tabs source-tabs" role="tablist" aria-label="资料类型">${Object.entries(typeNames).map(([type, label]) => `<button type="button" class="btn ${type === tab ? 'btn-primary' : 'btn-ghost'}" role="tab" id="knowledge-tab-${a(type)}" tabindex="${type === tab ? 0 : -1}" aria-selected="${type === tab}" aria-controls="knowledge-list-panel" data-action="source-tab" data-tab="${type}">${e(label)} <span>${sources.filter(source => source.type === type).length}</span></button>`).join('')}</div><div class="knowledge-filters">${control('搜索资料', 'knowledge-search', state.ui.search || '', { extra: 'data-ui-bind="search"', placeholder: tab === 'FAQ' ? '搜索问题、解答或来源' : tab === 'URL' ? '搜索地址、名称或来源' : '搜索文件名、正文或来源' })}${control('状态', 'knowledge-status-filter', filter, { extra: 'data-ui-bind="sourceFilter"', options: [{ value: 'all', label: '全部状态' }, { value: 'ready', label: '可试用' }, { value: 'pending', label: '待处理' }, { value: 'unavailable', label: '不可用' }] })}</div></div>`;
  const table = filtered.length ? `<div class="table-wrap"><table class="data-table knowledge-table mobile-list${tab === 'FAQ' ? ' faq-table' : ''}"><thead><tr>${tab === 'FAQ' ? '<th scope="col">问题</th><th scope="col">标准解答</th>' : '<th scope="col">资料与内容</th>'}<th scope="col">状态</th><th scope="col">操作</th></tr></thead><tbody>${sourceRows(ctx, filtered, tab)}</tbody></table></div>` : `<div class="library-empty">${emptyState(noMatch ? '没有匹配的资料' : `还没有${typeName(tab)}资料`, emptyDescription, emptyActions)}</div>`;
  return `<div class="library-workspace knowledge-workspace">${title('知识资料', '管理专家用于回答问题的内容。', button('source-form-toggle', '添加资料', { variant: 'primary', disabled: readonly }))}<div class="library-context"><span>当前专家：<strong>${e(agent.name)}</strong></span><span>需要向访客发送文件？${button('navigate', '打开物料库', { page: 'materials', variant: 'ghost' })}</span></div><div class="library-summary"><strong>全部资料</strong><span>${sources.length} 条资料</span><span>${count('ready')} 条可试用</span><span>${count('pending')} 条待处理</span>${count('unavailable') ? `<span>${count('unavailable')} 条不可用</span>` : ''}</div><section class="library-panel" id="knowledge-list-panel" role="tabpanel" aria-labelledby="knowledge-tab-${a(tab)}">${toolbar}<p class="knowledge-list-count"><span>当前类型：${typeName(tab)} · 共 ${ofType.length} 条</span><span>筛选结果：${filtered.length} 条</span></p>${table}</section>${hint}</div>`;
}

const knowledgeTabs = [['qa', '问答'], ['facts', '关键信息'], ['phrases', '标准话术'], ['sources', '按资料看']];
const reviewLabel = status => ({ reviewed: '已审', approved: '已审', pending: '待审', conflict: '不一致', missing: '缺出处', rejected: '不该由 AI 答' })[status] || '待审';

function qaEntries(agent) {
  const sources = new Map(list(agent.config.sources).map(source => [source.id, source]));
  return legacyQaItems(agent.config).map(item => {
    const source = sources.get(item.sourceId);
    const conflicts = detectCandidateConflicts({ ...item, kind: 'qa' }, {
      qaItems: legacyQaItems(agent.config).filter(other => other.id !== item.id),
      sources: [], keyFacts: agent.config.keyFacts || [],
    });
    const status = conflicts.length ? 'conflict' : !source?.sourceRef && item.sourceId ? 'missing' : item.reviewStatus;
    return { ...item, source, conflicts, status: status || 'pending' };
  });
}

function factEntries(agent) {
  return list(agent.config.keyFacts).filter(item => item.reviewStatus !== 'rejected').map(item => {
    const conflicts = detectCandidateConflicts({ ...item, kind: 'fact' }, { keyFacts: agent.config.keyFacts });
    return { ...item, conflicts, status: conflicts.length ? 'conflict' : item.reviewStatus || 'reviewed' };
  });
}

function knowledgeNavigation(ctx, active) {
  const { agent, readonly } = ctx;
  if (active === 'review') return '';
  const qa = qaEntries(agent);
  const counts = { qa: qa.length, facts: list(agent.config.keyFacts).length, phrases: list(agent.config.standardPhrases).length };
  const needsReview = [...qa, ...factEntries(agent)].some(item => item.status === 'pending' || item.status === 'conflict');
  const intake = `<details class="knowledge-batch-intake"><summary class="btn btn-primary">放资料</summary><form data-form="source-batch" class="knowledge-batch-form"><div class="field"><label for="knowledge-batch-files">选择资料</label><input class="control input" id="knowledge-batch-files" name="files" type="file" multiple accept=".csv,.tsv,.txt,.md,.xlsx,.pdf,.docx"${readonly ? ' disabled' : ''}><p class="helper">CSV、XLSX、TXT、Markdown 可在浏览器内拆成待核对内容；PDF 和 Word 文档解析待后端接入。</p></div>${control('这批资料的出处', 'sourceRef', '', { readonly, placeholder: '例如：自有课程政策 2026-10' })}${control('使用有效期至', 'expires', '', { type: 'date', readonly })}<label class="checkbox-field"><input type="checkbox" name="rights"${readonly ? ' disabled' : ''}><span>我确认有权在此客服场景中使用这批资料</span></label><p class="helper">授权按这批资料声明一次；未确认也可保留待核对草稿，不能用于试用或上线。</p><div class="library-actions"><button class="btn btn-primary" type="submit"${readonly ? ' disabled' : ''}>拆分并核对</button>${button('source-form-toggle', '单条录入', { disabled: readonly, variant: 'ghost' })}</div></form></details>`;
  return `<div class="knowledge-v2-toolbar"><div class="library-tabs source-tabs" role="tablist" aria-label="知识库内容">${knowledgeTabs.map(([key, label]) => `<button type="button" class="btn ${key === active ? 'btn-primary' : 'btn-ghost'}" role="tab" id="knowledge-v2-tab-${key}" tabindex="${key === active ? '0' : '-1'}" aria-selected="${key === active}" aria-controls="knowledge-v2-content" data-action="knowledge-tab" data-tab="${key}">${label}${counts[key] === undefined ? '' : ` <span>${counts[key]}</span>`}</button>`).join('')}</div><div class="knowledge-v2-toolbar-actions">${button('navigate', '物料库', { page: 'materials', variant: 'ghost', className: 'knowledge-v2-material-link' })}${intake}${needsReview ? button('source-review-open', '核对新资料', { variant: 'secondary' }) : ''}</div></div>`;
}

function qaStatus(item) {
  const text = reviewLabel(item.status);
  return badge(text, item.status === 'reviewed' || item.status === 'approved' ? 'success' : item.status === 'rejected' ? 'neutral' : 'warning');
}

function qaEditForm(item, readonly) {
  if (readonly) return '';
  return `<form class="knowledge-qa-edit" data-form="qa-save"><input type="hidden" name="id" value="${a(item.id)}">${control('问题', 'question', item.question, { required: true })}${control('标准解答', 'answer', item.answer, { type: 'textarea', required: true, rows: 5 })}<div class="library-actions"><button class="btn btn-primary" type="submit">保存修改</button>${button('qa-edit', '取消', { id: item.id, variant: 'ghost' })}</div></form>`;
}

function renderQa(ctx) {
  const { agent, state, readonly } = ctx;
  const all = qaEntries(agent);
  const search = String(state.ui.search || '').trim().toLowerCase();
  const filtered = search ? all.filter(item => [item.question, item.answer, item.source?.title].some(value => String(value || '').toLowerCase().includes(search))) : all;
  const authorization = list(agent.config.sources).filter(source => !source.rights);
  const rows = filtered.map(item => {
    const source = item.source;
    const answer = resolveFactReferences(item.answer, agent.config.keyFacts || []);
    const factNames = [...String(item.answer || '').matchAll(/\{([^{}]+)\}/g)].map(match => match[1]);
    const metadata = `<div class="knowledge-qa-meta"><span>出处：${e(source?.title || item.sourceTitle || item.sourceRef || '未登记')}${source?.sourceRef ? ` · ${e(source.sourceRef)}` : ''}</span>${item.conflicts.length ? `<span>和已有内容不一致：${e(item.conflicts[0].current)}</span>` : ''}</div>`;
    return `<article class="knowledge-qa-row" data-qa-id="${a(item.id)}"><div class="knowledge-qa-main"><div class="knowledge-qa-heading"><h2>${e(item.question || '未填写问题')}</h2>${qaStatus(item)}</div><p class="knowledge-qa-answer">${e(answer || '尚未填写标准解答')}</p>${factNames.length ? `<p class="helper">${factNames.map(name => `${e(name)}由关键信息统一更新`).join(' · ')}</p>` : ''}${metadata}</div><div class="knowledge-qa-actions">${button('qa-edit', '编辑', { id: item.id, disabled: readonly })}${button('qa-decision', '不该由 AI 答', { id: item.id, decision: 'no-answer', disabled: readonly, variant: 'ghost' })}${button('trial-open', '试这一条', { question: item.question, variant: 'ghost' })}${button('evidence-open', '依据', { kind: 'qa', id: item.id, variant: 'ghost' })}</div>${state.ui.qaEditId === item.id ? qaEditForm(item, readonly) : ''}</article>`;
  }).join('');
  return `<div class="knowledge-v2-search">${control('搜索问答', 'knowledge-search', state.ui.search || '', { extra: 'data-ui-bind="search"', placeholder: '搜索问题、解答或出处' })}<span>${filtered.length} 条问答</span></div>${authorization.length ? `<p class="notice notice-warning">${authorization.length} 批资料还没声明授权，请在“按资料看”逐批确认；同批问答不重复提示。</p>` : ''}<div class="knowledge-qa-list">${rows || emptyState(search ? '没有匹配的问答' : '还没有问答', search ? '更换搜索词查看已有问答。' : '放入授权资料，核对后即可试一试。', search ? button('source-clear', '清除筛选') : button('source-form-toggle', '放资料', { disabled: readonly }))}</div>`;
}

function factEditForm(ctx, fact, { review = false } = {}) {
  const { agent, readonly } = ctx;
  if (readonly) return '';
  const references = fact?.name ? factReferences(agent, fact.name) : [];
  const affected = references.map(item => `<label class="checkbox-field"><input type="checkbox" name="include:${a(item.kind)}:${a(item.id)}" checked><span>${item.kind === 'qa' ? '问答' : item.kind === 'rule' ? '红线' : '办理'}「${e(item.title || '未命名')}」</span></label>`).join('');
  return `<form class="knowledge-fact-edit" data-form="fact-save"><input type="hidden" name="id" value="${a(fact?.id || '')}">${review ? '<input type="hidden" name="review" value="true">' : ''}${control('名称', 'name', fact?.name || '', { required: true })}<div class="knowledge-fact-fields">${control('当前值', 'value', fact?.value || '', { required: true })}${control('单位', 'unit', fact?.unit || '')}${control('生效时间', 'effectiveFrom', fact?.effectiveFrom || '', { type: 'date' })}</div>${control('出处', 'sourceRef', fact?.sourceRef || '', { required: true, placeholder: '例如：价格表第 2 行' })}${fact ? `<fieldset class="knowledge-impact"><legend>以下 ${references.length} 处会一起改</legend>${affected || '<p>当前没有直接引用。</p>'}</fieldset>` : ''}<div class="library-actions"><button class="btn btn-primary" type="submit">${review ? '保存并核对' : '确认修改'}</button>${button('fact-edit', '取消', { id: fact?.id || '', review, variant: 'ghost' })}</div></form>`;
}

function renderFacts(ctx) {
  const { agent, state, readonly } = ctx;
  const facts = list(agent.config.keyFacts);
  const editing = facts.find(item => item.id === state.ui.factEditId);
  const rows = facts.map(fact => {
    const references = factReferences(agent, fact.name);
    const grouped = [['qa', '问答'], ['rule', '红线'], ['tool', '办理']].map(([kind, label]) => {
      const count = references.filter(item => item.kind === kind).length;
      return count ? `${count} 条${label}` : '';
    }).filter(Boolean).join(' · ') || '尚未引用';
    return `<tr data-fact-id="${a(fact.id)}"><td data-label="名称"><strong>${e(fact.name)}</strong></td><td data-label="当前值">${button('fact-edit', `${fact.value} ${fact.unit || ''}`.trim(), { id: fact.id, disabled: readonly, variant: 'ghost' })}</td><td data-label="生效时间">${e(fact.effectiveFrom || '长期')}</td><td data-label="用在哪">${e(grouped)}${!fact.sourceRef ? '<p class="knowledge-fact-warning">缺出处，不能上线</p>' : ''}</td><td data-label="依据">${button('evidence-open', '依据', { kind: 'fact', id: fact.id, variant: 'ghost' })}</td></tr>`;
  }).join('');
  return `<div class="knowledge-fact-head"><p>价格、时效这类会变的值</p>${button('fact-edit', '新增', { id: 'new', disabled: readonly, variant: 'primary' })}</div>${state.ui.factEditId ? factEditForm(ctx, editing) : ''}${facts.length ? `<div class="table-wrap"><table class="data-table knowledge-fact-table mobile-list"><thead><tr><th>名称</th><th>当前值</th><th>生效时间</th><th>用在哪</th><th>依据</th></tr></thead><tbody>${rows}</tbody></table></div>` : emptyState('还没有关键信息', '把价格、时效等常变的值集中管理。', button('fact-edit', '新增关键信息', { id: 'new', disabled: readonly, variant: 'primary' }))}`;
}

function reviewItem(ctx, item) {
  const { state, readonly } = ctx;
  const conflicts = item.conflicts || [];
  const question = item.kind === 'fact' ? item.name : item.question;
  const answer = item.kind === 'fact' ? `${item.value} ${item.unit || ''}`.trim() : item.answer;
  const isFact = item.kind === 'fact';
  const decisionAction = isFact ? 'fact-decision' : 'qa-decision';
  const editAction = isFact ? 'fact-edit' : 'qa-edit';
  const customFields = isFact
    ? `<div class="knowledge-fact-choice-fields">${control('需要另写时填写正确值', 'value', '', { idPrefix: `review-${item.id}` })}${control('单位', 'unit', item.unit || '', { idPrefix: `review-${item.id}` })}</div>`
    : control('需要另写时填写正确说法', 'answer', '', { type: 'textarea', rows: 2, idPrefix: `review-${item.id}` });
  const choice = conflicts.length ? `<form class="knowledge-review-choice notice notice-warning" data-form="${isFact ? 'fact-decision' : 'qa-save'}"><input type="hidden" name="id" value="${a(item.id)}"><input type="hidden" name="conflictId" value="${a(conflicts[0].currentId)}"><input type="hidden" name="review" value="true"><p>和已有资料说法不一致：${e(conflicts[0].current)}</p><fieldset><legend>以哪个为准？</legend><label><input type="radio" name="choice" value="candidate" required${readonly ? ' disabled' : ''}>${e(answer)}</label><label><input type="radio" name="choice" value="current"${readonly ? ' disabled' : ''}>${e(conflicts[0].current)}</label><label><input type="radio" name="choice" value="custom"${readonly ? ' disabled' : ''}>都不对，我来写</label></fieldset>${readonly ? '' : customFields}<button class="btn btn-primary" type="submit"${readonly ? ' disabled' : ''}>确定${isFact ? '值' : '说法'}</button></form>` : '';
  const edit = isFact && state.ui.factEditId === item.id ? factEditForm(ctx, item, { review: true }) : state.ui.qaEditId === item.id ? qaEditForm(item, readonly) : '';
  return `<article class="knowledge-review-item" data-qa-id="${a(item.id)}" data-review-kind="${isFact ? 'fact' : 'qa'}" tabindex="0" aria-label="核对${a(question)}"><h3>${e(question)}</h3><p>${e(answer)}</p>${choice}<div class="library-actions">${conflicts.length ? '' : button(decisionAction, '对', { id: item.id, decision: 'approve', disabled: readonly, variant: 'primary' })}${button(editAction, '改一下', { id: item.id, review: true, disabled: readonly })}${button(decisionAction, '不该由 AI 答', { id: item.id, decision: 'no-answer', disabled: readonly, variant: 'ghost' })}</div>${edit}</article>`;
}

function renderReview(ctx) {
  const { agent, state, readonly } = ctx;
  const sourceId = state.ui.reviewBatchId || [...qaEntries(agent), ...factEntries(agent)].find(item => item.status === 'pending' || item.status === 'conflict')?.sourceId;
  const source = list(agent.config.sources).find(item => item.id === sourceId);
  const candidates = qaEntries(agent).filter(item => item.sourceId === sourceId && ['pending', 'conflict'].includes(item.status)).map(item => ({ ...item, kind: 'qa' }));
  const facts = factEntries(agent).filter(item => item.sourceId === sourceId && ['pending', 'conflict'].includes(item.status)).map(item => ({ ...item, kind: 'fact' }));
  const groups = classifyCandidates([...candidates, ...facts], {
    qaItems: qaEntries(agent),
    keyFacts: list(agent.config.keyFacts),
  });
  const sample = sampleLowRisk(groups.lowRisk, 2, sourceId);
  const rights = source ? `<div class="knowledge-batch-rights"><p>这批资料：${source.rights ? '已声明使用授权' : '尚未声明使用授权'} · ${e(source.expires || '未设有效期')} · 撤回后停止后续试用</p>${button('source-edit', '修改', { id: source.id, disabled: readonly })}</div>` : '';
  return `<div class="knowledge-review"><div class="library-back">${button('knowledge-tab', '返回问答', { tab: 'qa', variant: 'ghost' })}</div><div class="knowledge-review-heading"><h2>核对新资料 · ${e(source?.title || '未命名资料')}</h2><span>${candidates.length + facts.length} 条待核对</span></div>${rights}${candidates.length + facts.length ? `<section><h3>需要你逐条看（${groups.risky.length}）</h3><p>含价格、承诺，或和已有资料说法不一致</p>${groups.risky.map(item => reviewItem(ctx, item)).join('') || '<p>这一组没有待核对内容。</p>'}</section><section><h3>系统判断风险低（${groups.lowRisk.length}）</h3><p>已抽 ${sample.length} 条供核对</p>${sample.map(item => reviewItem(ctx, item)).join('')}<details><summary>展开看全部</summary>${groups.lowRisk.filter(item => !sample.includes(item)).map(item => reviewItem(ctx, item)).join('')}</details>${groups.lowRisk.length ? button('qa-low-confirm', `这 ${groups.lowRisk.length} 条都没问题`, { sourceId, disabled: readonly, variant: 'primary' }) : ''}</section>` : emptyState('这批资料已核对', '可返回问答查看结果。', button('knowledge-tab', '返回问答', { tab: 'qa' }))}</div>`;
}

function renderPhrases(ctx) {
  const phrases = list(ctx.agent.config.standardPhrases);
  return phrases.length ? `<div class="knowledge-phrase-list">${phrases.map(item => `<article><h2>${e(item.title || item.name)}</h2><p>${e(item.text || item.body)}</p>${button('evidence-open', '依据', { kind: 'phrase', id: item.id, variant: 'ghost' })}</article>`).join('')}</div>` : emptyState('还没有标准话术', '先放入授权资料并核对需要固定表达的内容。', button('source-form-toggle', '放资料', { disabled: ctx.readonly, variant: 'primary' }));
}

export function renderKnowledge(ctx) {
  const { state, agent } = ctx;
  if (!agent || state.ui.knowledgeTab == null) return renderSourceLibrary(ctx);
  if (state.ui.sourceForm || state.ui.sourceDetail) return renderSourceLibrary(ctx);
  const active = knowledgeTabs.some(([key]) => key === state.ui.knowledgeTab) || state.ui.knowledgeTab === 'review' ? state.ui.knowledgeTab : 'qa';
  if (active === 'sources') return `<div class="knowledge-v2-source-view">${knowledgeNavigation(ctx, active)}${renderSourceLibrary(ctx)}</div>`;
  const body = active === 'facts' ? renderFacts(ctx) : active === 'review' ? renderReview(ctx) : active === 'phrases' ? renderPhrases(ctx) : renderQa(ctx);
  return `<div class="library-workspace knowledge-workspace knowledge-v2">${title(active === 'review' ? '核对新资料' : '知识库')}${knowledgeNavigation(ctx, active)}<section class="knowledge-v2-content" id="knowledge-v2-content" role="tabpanel" aria-labelledby="knowledge-v2-tab-${active === 'review' ? 'qa' : active}">${body}</section></div>`;
}

const ruleActions = RULE_ACTION_LABELS;
function ruleForm(rule) {
  const id = rule?.id || '';
  const field = rule?.condition?.field || '客户诉求';
  const operator = rule?.condition?.operator || 'is';
  const action = rule?.action || 'handoff';
  const select = (name, current, options) => `<select class="control input" name="${a(name)}" aria-label="${a({ field: '条件字段', operator: '判断方式', action: '处理方式' }[name])}">${options.map(([value, label]) => `<option value="${a(value)}"${value === current ? ' selected' : ''}>${e(label)}</option>`).join('')}</select>`;
  return `<form data-form="rule-save" class="knowledge-rule-form"><input type="hidden" name="id" value="${a(id)}"><div class="knowledge-rule-condition"><span>当</span>${select('field', field, RULE_FIELDS.map(value => [value, value]))}${select('operator', operator, RULE_OPERATORS.map(value => [value, RULE_OPERATOR_LABELS[value]]))}<input class="control input" name="value" aria-label="条件值" value="${a(rule?.condition?.value || '')}" required><span>就</span>${select('action', action, RULE_ACTIONS.map(value => [value, ruleActions[value]]))}</div>${control('接收组（转人工时填写）', 'recipient', rule?.recipient || '')}${control('依据', 'sourceRef', rule?.sourceRef || '')}<div class="library-actions"><button class="btn btn-primary" type="submit">保存红线</button>${button('rule-edit', '取消', { id, variant: 'ghost' })}</div></form>`;
}

export function renderRedlines(ctx) {
  const { state, agent, readonly } = ctx;
  if (!agent) return emptyState('先选择或创建一位专家', '红线随专家草稿管理。', button('navigate', '查看专家', { page: 'agents', variant: 'primary' }));
  const business = list(agent.config.businessRules);
  const platform = list(agent.config.rules).filter(rule => rule.locked);
  const selected = business.find(rule => rule.id === state.ui.ruleEditId);
  const rows = business.map(rule => {
    const condition = [rule.condition?.field, RULE_OPERATOR_LABELS[rule.condition?.operator] || rule.condition?.operator, resolveFactReferences(rule.condition?.value, agent.config.keyFacts || [])].filter(Boolean).join(' ');
    const used = ruleHitCount(state.runs, agent.id, rule.id);
    return `<div class="knowledge-rule-row" data-rule-id="${a(rule.id)}"><div><strong>当 ${e(condition)} → ${e(ruleActions[rule.action] || '转人工')}${rule.action === 'handoff' && rule.recipient ? `（${e(rule.recipient)}）` : ''}</strong><p>${rule.enabled === false ? '已停用' : '在用'} · 近 7 天 ${used} 次${!used ? ' · 请确认是否生效' : ''}</p></div><div class="library-actions">${button('rule-edit', '编辑', { id: rule.id, disabled: readonly })}${button('rule-toggle', rule.enabled === false ? '启用' : '停用', { id: rule.id, disabled: readonly, variant: 'ghost' })}${button('trial-open', '试一句话', { question: rule.condition?.value || '', variant: 'ghost' })}${button('evidence-open', '依据', { kind: 'rule', id: rule.id, variant: 'ghost' })}</div></div>`;
  }).join('');
  return `<div class="library-workspace knowledge-workspace knowledge-redlines">${title('红线', '', button('rule-edit', '新增红线', { id: 'new', disabled: readonly, variant: 'primary' }))}<div class="knowledge-rule-tabs"><strong>我的红线 ${business.length}</strong><span>平台底线 ${platform.length}</span></div><div class="knowledge-rule-templates"><span>从常用里选</span>${RULE_TEMPLATES.map(item => button('rule-template', item.label, { template: item.id, disabled: readonly, variant: 'ghost' })).join('')}</div>${state.ui.ruleEditId && !readonly ? ruleForm(selected) : ''}<section class="knowledge-rule-list" aria-label="我的红线">${rows || emptyState('还没有我的红线', '从常用模板添加，或按条件和处理方式建立一条。', button('rule-edit', '新增红线', { id: 'new', disabled: readonly }))}</section><details class="knowledge-platform-rules"><summary>平台底线（所有专家生效，不能关） · 查看全部 ${platform.length} 条和原因</summary><ul>${platform.map(rule => `<li><strong>${e(rule.title)}</strong><p>${e(rule.description || '平台统一执行，不可在此修改。')}</p></li>`).join('')}</ul></details></div>`;
}
