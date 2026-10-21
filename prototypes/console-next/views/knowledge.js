import { escapeHtml, attr, badge, button, emptyState, pageHeading } from '../helpers.js';
import { sourceValid, validDate } from '../domain.js';

const e = escapeHtml;
const a = attr;
const list = value => Array.isArray(value) ? value : [];
const typeNames = { FAQ: '问答', URL: '网页', File: '文件' };
const typeName = type => typeNames[type] || '资料';
const title = (text, description = '', actions = '') => pageHeading(text, description, actions).replace('<h1>', '<h1 data-library-heading tabindex="-1">');
const detailList = entries => `<dl class="detail-list">${entries.map(([label, value]) => `<div><dt>${e(label)}</dt><dd>${e(value ?? '未填写')}</dd></div>`).join('')}</dl>`;
const disclosureKey = (agent, source, name) => `knowledge:${agent.id}:${source.id}:v${source.version || 1}:${name}`;

function control(label, name, value = '', { type = 'text', required = false, help = '', placeholder = '', readonly = false, rows = 3, options = null, extra = '' } = {}) {
  const id = `surface-${name.replace(/[^a-zA-Z0-9_-]/g, '-')}`;
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

export function renderKnowledge(ctx) {
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
