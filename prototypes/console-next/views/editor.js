import {
  escapeHtml, badge, button, field, section, emptyState, formatTime,
  renderReadiness, pageHeading,
} from '../helpers.js';
import { sourceValid, validateConfig } from '../domain.js';

const modules = [
  { id: 'service', title: '接待与回答', summary: '对象、范围、表达与人工出口', business: true },
  { id: 'knowledge', title: '依据资料', summary: '来源、授权与可引用状态', layer: 'ContextSnapshot', business: true },
  { id: 'flow', title: '服务流程', summary: '当前请求、步骤与回退', layer: 'RequestRouting', business: true },
  { id: 'fields', title: '业务字段', summary: '收集信息与工具结果', business: true },
  { id: 'skills', title: '处理策略', summary: '适用条件与退出方式', layer: 'Skill / SOP', business: true },
  { id: 'rules', title: '必须遵守的约束', summary: '锁定边界与待审建议', layer: 'HardRule' },
  { id: 'tools', title: '业务动作', summary: '模拟、确认与结果证据', layer: 'ToolPolicy', business: true },
  { id: 'outcome', title: '结果与验收', summary: '成功、未解与未知结果', layer: 'Outcome' },
  { id: 'model', title: '模型与预算', summary: '连接引用与单次预算' },
  { id: 'evidence', title: '版本与变更依据', summary: '有效值、来源与手动修改' },
];

const sourceStates = {
  received: ['已接收', 'neutral'], parsed: ['已解析', 'neutral'], review: ['待审阅', 'warning'],
  indexed: ['演示索引就绪', 'success'], failed: ['处理失败', 'danger'], revoked: ['已撤回', 'neutral'],
};
const integrationTerms = '<details><summary>技术名称与接入边界</summary><p class="helper">外部创作助手（Agent）后续通过 MCP / 配套 Skills 调用统一 API 提交受限草稿与候选；桥接尚未接入。候选不取得生产写入、批准或发布权。</p></details>';

function sourceMarker(agent, path) {
  const entry = agent.manualPaths?.[path];
  if (entry) return `<span class="source-marker">${badge('手动修改 · 受保护', 'neutral')}<span class="helper">${entry.revision ? `修订 r${escapeHtml(entry.revision)}` : '外部候选不会直接覆盖'}</span></span>`;
  const origin = agent.origins?.[path];
  if (!origin) return '';
  return `<span class="source-marker">${badge(origin.origin === '助手建议' ? '助手候选已采用 · 模拟' : origin.origin || '本地来源', 'neutral')}<span class="helper">修订 r${escapeHtml(origin.revision)}${origin.source ? ` · ${escapeHtml(origin.source)}` : ''}</span></span>`;
}

function editableField(ctx, label, path, value, options = {}) {
  const displayValue = Array.isArray(value) && options.format ? value.join(options.format === 'lines' ? '\n' : ', ') : value;
  return `<div class="config-field">${field(label, path, displayValue, { ...options, readonly: ctx.readonly })}${sourceMarker(ctx.agent, path)}</div>`;
}

function selectField(ctx, label, path, value, options, help = '') {
  return `<div class="field"><label for="config-${escapeHtml(path)}">${escapeHtml(label)}</label><select class="control input" id="config-${escapeHtml(path)}" name="${escapeHtml(path)}" data-bind="${escapeHtml(path)}" ${ctx.readonly ? 'disabled' : ''}>${options.map(option => `<option value="${escapeHtml(option.value)}" ${String(option.value) === String(value) ? 'selected' : ''}>${escapeHtml(option.label)}</option>`).join('')}</select>${help ? `<p class="helper">${escapeHtml(help)}</p>` : ''}${sourceMarker(ctx.agent, path)}</div>`;
}

function checkbox(ctx, label, path, checked, help = '', locked = false) {
  return `<div class="field"><label class="inline"><input type="checkbox" name="${escapeHtml(path)}" data-bind="${escapeHtml(path)}" ${checked ? 'checked' : ''} ${ctx.readonly || locked ? 'disabled' : ''}><span>${escapeHtml(label)}</span></label>${help ? `<p class="helper">${escapeHtml(help)}</p>` : ''}${sourceMarker(ctx.agent, path)}</div>`;
}

function formField(label, name, options = {}) {
  const { type = 'text', placeholder = '', required = false, value = '', help = '', uiBind = '' } = options;
  const binding = uiBind ? `data-ui-bind="${escapeHtml(uiBind)}"` : '';
  const control = type === 'textarea'
    ? `<textarea class="control textarea" id="new-${escapeHtml(name)}" name="${escapeHtml(name)}" ${binding} rows="3" placeholder="${escapeHtml(placeholder)}" ${required ? 'required' : ''}>${escapeHtml(value)}</textarea>`
    : `<input class="control input" id="new-${escapeHtml(name)}" name="${escapeHtml(name)}" ${binding} type="${escapeHtml(type)}" value="${escapeHtml(value)}" placeholder="${escapeHtml(placeholder)}" ${required ? 'required' : ''}>`;
  return `<div class="field"><label for="new-${escapeHtml(name)}">${escapeHtml(label)}${required ? ' <span class="helper">（必填）</span>' : ''}</label>${control}${help ? `<p class="helper">${escapeHtml(help)}</p>` : ''}</div>`;
}

function submitButton(label) {
  return `<button type="submit" class="btn btn-primary">${escapeHtml(label)}</button>`;
}

function unavailable(ctx) {
  if (ctx.agent) return '';
  return emptyState('先选择或创建专家', '每个专家都有独立的草稿、资料和版本；可以从空草稿开始手动搭建。', button('new-agent', '手动创建', { variant: 'primary', mode: 'manual' }));
}

function readonlyNotice(ctx) {
  if (!ctx.readonly) return '';
  const published = Boolean(ctx.state.ui.previewVersionId);
  return `<div class="notice notice-warning" role="status"><strong>${published ? '正在查看冻结版本' : '当前为只读查看'}</strong><p>可查看全部有效配置与依据。编辑、采用建议和批准需返回当前草稿；已有入口继续绑定原版本。</p><div class="button-group">${button('readonly-toggle', '返回可编辑草稿')}${button('navigate', '查看版本与入口绑定', { page: 'versions', variant: 'ghost' })}</div></div>`;
}

function saveState(ctx) {
  const ui = ctx.state.ui;
  const status = ui.saveStatus || 'saved';
  const labels = { saving: '正在保存到本机', saved: '已保存到本机', error: '保存失败', unsaved: '有未保存修改' };
  return `<div class="save-status inline" aria-live="polite">${badge(labels[status] || '草稿保存状态待确认', status === 'error' ? 'danger' : status === 'saved' ? 'success' : 'warning')}<span class="helper">${ui.savedAt ? formatTime(ui.savedAt) : '仅当前浏览器保存；未接后台'}</span>${button('save-now', status === 'error' ? '重试保存' : '保存草稿', { disabled: ctx.readonly || status === 'saving', variant: 'ghost' })}</div>`;
}

function configNavigation(ctx) {
  const available = moduleStates(ctx);
  const active = available.find(item => item.id === ctx.state.ui.section) || available[0];
  const missing = available.filter(item => item.status === 'missing');
  const labels = { missing: ['缺项', 'warning'], pending: ['待确认', 'neutral'], usable: ['可用', 'success'], optional: ['可选', 'neutral'] };
  const navigation = `<nav class="config-nav" aria-label="配置模块"><div class="helper config-nav-hint">${missing.length} 个模块有必需缺项${missing.length ? `<div>${button('set-section', `优先补齐：${missing[0].title}`, { section: missing[0].id, variant: 'ghost' })}</div>` : ' · 可继续检查与试用'}</div>${available.map(item => `<button class="btn btn-ghost ${item.id === active.id ? 'is-active' : ''}" type="button" data-action="set-section" data-section="${item.id}" ${item.id === active.id ? 'aria-current="page"' : ''} data-module-status="${item.status}"><span class="module-nav-title"><span>${item.title}</span>${badge(...labels[item.status])}</span><small>${escapeHtml(item.detail || item.summary)}</small></button>`).join('')}</nav>`;
  return { active, navigation };
}

function moduleStates(ctx) {
  const config = ctx.agent.config;
  const errors = validateConfig(config);
  const issueFor = {
    service: /服务目标|服务对象|服务范围|资料不足|恢复检查/,
    flow: /处理步骤|步骤标题/,
    fields: /字段/,
    tools: /业务写入/,
    model: /预算/,
  };
  return modules.map(item => {
    const issue = errors.find(error => issueFor[item.id]?.test(error));
    let status = issue ? 'missing' : 'usable';
    let detail = issue || '';
    if (item.id === 'knowledge' && ctx.ready.items.find(entry => entry.id === 'knowledge')?.status !== 'ok') {
      status = 'missing'; detail = ctx.ready.items.find(entry => entry.id === 'knowledge')?.detail;
    }
    if (item.id === 'model' && !issue) {
      const connection = ctx.ready.items.find(entry => entry.id === 'connection');
      status = connection?.status === 'missing' ? 'missing' : 'pending';
      detail = connection?.detail;
    }
    if (['fields', 'skills', 'tools'].includes(item.id) && !config[item.id].length) status = 'optional';
    if (item.id === 'outcome' && (!config.outcome.definition?.trim() || !config.outcome.unknown?.trim())) status = 'pending';
    if (item.id === 'rules' && !config.rules.length) status = 'pending';
    if (item.id === 'evidence') {
      status = ctx.agent.checks.testedRevision === ctx.agent.revision ? 'usable' : 'pending';
      detail = status === 'pending' ? '当前修订尚未重新检查' : '当前修订有本地检查记录';
    }
    return { ...item, status, detail, validationIssue: issue };
  });
}

function nextStep(ctx) {
  const ready = ctx.ready;
  const item = ready.items.find(entry => ['goal', 'knowledge', 'connection'].includes(entry.id) && entry.status === 'missing')
    || ready.items.find(entry => entry.id === 'trial' && entry.status === 'missing')
    || ready.items.find(entry => entry.id === 'approval' && entry.status === 'missing')
    || ready.items.find(entry => entry.id === 'binding' && entry.status === 'missing');
  const missingModule = moduleStates(ctx).find(entry => entry.validationIssue === item?.detail);
  const mainAction = ctx.readonly
    ? button('readonly-toggle', '返回可编辑草稿', { variant: 'primary' })
    : item?.id === 'goal' && /预约外链|自动发送物料/.test(item.detail)
      ? button('navigate', '补齐应用配置', { page: /预约外链/.test(item.detail) ? 'widget' : 'materials', variant: 'primary' })
    : item?.id === 'goal'
      ? button('set-section', '补齐业务配置', { section: missingModule?.id || 'service', variant: 'primary' })
      : button('navigate', item ? ({ knowledge: '补充与审阅资料', connection: '选择可用连接', trial: '试用当前草稿', approval: '查看批准条件', binding: '配置网页入口' }[item.id]) : '查看当前版本', { page: item?.page || 'versions', variant: 'primary' });
  return `<section class="next-step section" aria-labelledby="next-step-heading"><div><p class="eyebrow">${ctx.readonly ? '历史与只读配置' : '当前优先处理'}</p><h2 id="next-step-heading">${ctx.readonly ? '当前配置只读，修改需返回草稿' : escapeHtml(item ? item.label : '当前演示检查已齐备')}</h2><p>${escapeHtml(ctx.readonly ? '可以展开摘要和查看全部配置；已有冻结版本与入口绑定不会被修改。' : item?.detail || '可查看版本与绑定依据；本地检查不代表真实模型、外部送达或上线。')}</p></div><div class="next-step-action">${mainAction}</div></section>`;
}

function moduleActions(ctx, scope) {
  return button('toggle-assistant', ctx.state.ui.assistantOpen ? '收起创作助手说明' : '查看创作助手方式', { scope, variant: 'ghost' });
}

export function renderAgents(ctx) {
  const { state } = ctx;
  const search = (state.ui.search || '').trim().toLocaleLowerCase();
  const agents = state.agents.filter(agent => !search || `${agent.name} ${agent.config.goal} ${agent.config.audience}`.toLocaleLowerCase().includes(search));
  const actions = `<div class="button-group">${button('new-agent', '手动创建', { variant: 'primary', mode: 'manual' })}${button('new-agent', '查看创作助手方式', { mode: 'assistant' })}</div>`;
  const heading = pageHeading('专家', '为客服或销售建立业务专家。从草稿开始，使用授权资料试用，再选择接入业务动作与网站。', actions);
  const toolbar = `<div class="toolbar"><div class="field"><label for="agent-search" class="sr-only">搜索专家</label><input class="control input" id="agent-search" type="search" data-ui-bind="search" value="${escapeHtml(state.ui.search || '')}" placeholder="搜索名称、目标或服务对象"></div><span class="muted">${agents.length} 个专家</span></div>`;
  if (!state.agents.length) return `${heading}${emptyState('从你的第一个专家开始', '不需要先有工具、模型凭据或外部创作助手。手动创建空草稿，再录入授权问答即可体验脚本模拟。', actions)}`;
  if (!agents.length) return `${heading}${toolbar}${emptyState('没有匹配的专家', '调整搜索词，或清空搜索查看已有草稿。')}`;
  return `${heading}${toolbar}<div class="table-wrap"><table class="data-table"><thead><tr><th scope="col">专家 / 服务目标</th><th scope="col">当前草稿</th><th scope="col">资料</th><th scope="col">入口绑定</th><th scope="col">操作</th></tr></thead><tbody>${agents.map(agent => {
    const sources = agent.config.sources || [];
    const usable = sources.filter(source => sourceValid(source, agent.revokedSourceIds || [])).length;
    const bindings = [agent.bindings?.widget && '网站客服窗', agent.bindings?.contact && '联系页'].filter(Boolean);
    return `<tr><td><button class="button-link agent-name" type="button" data-action="select-agent" data-id="${escapeHtml(agent.id)}">${escapeHtml(agent.name)}</button><p class="helper">${escapeHtml(agent.config.goal || '尚未填写服务目标')}</p></td><td>${badge(`草稿 r${agent.revision}`, 'neutral')}<p class="helper">${agent.versions.length} 个冻结版本</p></td><td>${usable ? badge(`${usable} 项演示可引用`, 'success') : badge('待补资料', 'warning')}<p class="helper">共 ${sources.length} 项来源</p></td><td>${bindings.length ? bindings.map(label => badge(`${label} · 沙盒演示`, 'neutral')).join(' ') : '<span class="muted">尚未绑定</span>'}</td><td>${button('select-agent', '继续配置', { id: agent.id })}</td></tr>`;
  }).join('')}</tbody></table></div><p class="helper">冻结版本与可变草稿分别保存；列表中的可引用状态和沙盒绑定均为本地演示，不代表真实服务已上线。</p>`;
}

export function renderCreate(ctx) {
  const mode = ctx.state.ui.createMode || 'manual';
  const draft = ctx.state.ui.createDraft || {};
  return `${pageHeading('新建专家', '只需名称就能保存空草稿。业务目标与服务对象可以随后补齐。', button('navigate', '返回专家列表', { page: 'agents', variant: 'ghost' }))}
    <div class="creation-options" role="group" aria-label="选择创建方式">
      <button class="creation-option ${mode === 'manual' ? 'is-active' : ''}" type="button" data-action="create-mode" data-mode="manual" aria-pressed="${mode === 'manual'}"><strong>手动创建</strong><span>直接编辑同一份结构化草稿；无需外部创作助手或生成调用。</span></button>
      <button class="creation-option ${mode === 'assistant' ? 'is-active' : ''}" type="button" data-action="create-mode" data-mode="assistant" aria-pressed="${mode === 'assistant'}"><strong>查看创作助手方式</strong><span>后续可由用户自己的创作助手提交草稿或候选；当前未连接，仍使用下面的手动表单。</span></button>
    </div>
    ${section('基本信息', `<form class="stack compact-form" data-form="create"><input type="hidden" name="mode" value="${mode}">${formField('专家名称', 'name', { required: true, value: draft.name, uiBind: 'createDraft.name', placeholder: '例如：课程咨询客服', help: '使用业务名称；机器标识会自动生成。' })}${formField('希望帮助用户完成什么', 'goal', { type: 'textarea', value: draft.goal, uiBind: 'createDraft.goal', placeholder: '例如：依据课程资料回答问题，复杂退费问题交人工。', help: '纯答疑也可以，不要求预约或业务写入。' })}${formField('服务对象', 'audience', { value: draft.audience, uiBind: 'createDraft.audience', placeholder: '例如：了解职业技能课程的成年访客' })}<div class="notice">${mode === 'assistant' ? '<strong>创作助手为后续接入方式</strong><p>未来用户自己的创作助手通过受限接口提交草稿或候选，仍由你在同一配置中审阅和采用。当前未连接任何外部创作助手；先使用本表单完整手动创建。</p>' : '<strong>完整手动路径</strong><p>创建后可录入资料、配置回答与人工出口、检查并试用。创作助手说明为可选入口，不影响手动配置。</p>'}</div><div class="button-group">${submitButton('创建手动草稿')}${button('navigate', '取消', { page: 'agents', variant: 'ghost' })}</div></form>`, { description: '无需先填写处理策略、字段标识或运行框架。此操作只保存草稿。' })}
    ${section('创建后可以继续', '<ol class="detail-list"><li><strong>提供授权资料</strong><span>手动录入问答、登记网址或接收文件；来源状态和授权分别确认。</span></li><li><strong>审阅范围与人工出口</strong><span>确定能回答什么、缺资料怎么处理，以及无人承接时的失败出口。</span></li><li><strong>运行脚本模拟</strong><span>测试资料内、资料外和转人工问题；真实模型与工具留待后端接入。</span></li></ol>')}${integrationTerms}`;
}

export function renderOverview(ctx) {
  if (!ctx.agent) return unavailable(ctx);
  const { agent, ready, readonly } = ctx;
  const config = agent.config;
  const indexed = (config.sources || []).filter(source => sourceValid(source, agent.revokedSourceIds || []));
  const actions = button('set-depth', '查看业务配置', { depth: 'business', variant: 'ghost' });
  const summary = `<dl class="definition-list"><div><dt>服务对象</dt><dd>${escapeHtml(config.audience || '尚未填写；可先保存草稿')}</dd></div><div><dt>业务目标</dt><dd>${escapeHtml(config.goal || '尚未填写业务目标')}</dd></div><div><dt>能回答什么</dt><dd>${escapeHtml(config.scope || '尚未明确服务范围')}</dd></div><div><dt>暂不能做什么</dt><dd>仅能使用已授权资料与当前模拟动作。真实业务写入、真实模型、消息渠道和云服务均未接入。</dd></div><div><dt>资料外问题</dt><dd>${escapeHtml(config.fallback || '请配置缺资料时的明确答复或转人工出口')}</dd></div><div><dt>人工出口</dt><dd>${escapeHtml(config.handoff?.condition || '尚未设置转人工条件')}；${escapeHtml(config.handoff?.recipient || '尚未登记接收者，无法证明人工已承接')}</dd></div></dl>`;
  const sources = indexed.length
    ? `<ul class="summary-list">${indexed.map(source => `<li><span><strong>${escapeHtml(source.title)}</strong><small>${escapeHtml(source.sourceRef || '来源标识待补')} · v${source.version}</small></span>${badge(source.fictional ? '虚构资料 · 演示' : '已登记授权 · 本地', 'neutral')}</li>`).join('')}</ul>`
    : emptyState('还没有可引用资料', '新增问答并登记授权、有效期和撤回信息，完成演示审阅与索引；网址和复杂文件不会被真实抓取或解析。', button('navigate', readonly ? '查看资料' : '添加与审阅资料', { page: 'knowledge' }));
  return `${pageHeading('业务概览', '概览、业务配置与详细配置共用同一份草稿；保存不代表发布。', actions)}${nextStep(ctx)}${readonlyNotice(ctx)}${saveState(ctx)}
    <details class="overview-summary"><summary>服务摘要 · 对象、范围与人工出口</summary><div class="detail-content">${summary}${button('set-section', '查看接待与回答', { section: 'service' })}</div></details>
    <details class="overview-summary"><summary>资料与业务动作 · ${indexed.length} 项可引用资料，${(config.tools || []).length} 项动作</summary><div class="detail-content">
    <div class="grid-2">${section('依据资料', sources, { description: `${indexed.length} 项演示可引用；保存、授权、解析与索引是不同事实。`, actions: button('navigate', '管理全部来源', { page: 'knowledge', variant: 'ghost' }) })}${section('当前业务动作', (config.tools || []).length ? `<ul class="summary-list">${config.tools.map(tool => `<li><span><strong>${escapeHtml(tool.title)}</strong><small>${tool.sideEffect === 'write' ? '模拟写入 · 执行前需要确认' : '模拟只读'}</small></span>${badge('模拟', 'neutral')}</li>`).join('')}</ul>` : '<p>现在可以先做知识答疑。尚未配置业务动作，不能办理预约或生成外部结果。</p>', { actions: button('set-section', '配置业务动作', { section: 'tools' }) })}</div>
    </div></details>
    <details class="overview-summary"><summary>完整就绪检查 · 分项证据与版本条件</summary><div class="detail-content">${section('分项就绪与下一步', renderReadiness(ready), { description: '脚本模拟、人工批准演示、入口绑定演示分别记录；草稿保存不更新已冻结版本。', actions: `${button('recheck', '重新检查', { disabled: readonly })}${button('navigate', '查看版本与验收', { page: 'versions', variant: 'ghost' })}` })}</div></details>
    <details class="overview-summary"><summary>使用效果预览 · 未发送消息</summary><div class="detail-content">${section('使用效果预览', `<div class="chat"><div class="chat-message message-assistant"><span class="helper">欢迎语 · 配置预览</span><p>${escapeHtml(config.greeting || '欢迎语尚未填写')}</p></div></div><p class="helper">这是外观与表达预览，没有发送消息。真实送达、人工承接和问题解决需要各自的运行证据。</p>`, { actions: button('navigate', '查看网站客服窗外观', { page: 'widget', variant: 'ghost' }) })}</div></details>`;
}

function renderService(ctx) {
  const config = ctx.agent.config;
  const handoff = config.handoff || {};
  return `${section('接待与回答', `<div class="field"><label for="config-agent-name">专家名称</label><input class="control input" id="config-agent-name" data-agent-name value="${escapeHtml(ctx.agent.name)}" ${ctx.readonly ? 'disabled' : ''}></div><div class="grid-2">${editableField(ctx, '服务对象', 'audience', config.audience)}${editableField(ctx, '服务目标', 'goal', config.goal, { type: 'textarea', rows: 3 })}</div>${editableField(ctx, '回答范围', 'scope', config.scope, { type: 'textarea', help: '列出允许回答的业务范围；不把未确认价格、政策或承诺写成事实。' })}${editableField(ctx, '表达方式', 'tone', config.tone, { help: '只调整表达，不改变权限、确认要求或业务结果。' })}${editableField(ctx, '欢迎语', 'greeting', config.greeting, { type: 'textarea', rows: 3 })}${editableField(ctx, '没有资料或无人承接时如何回答', 'fallback', config.fallback, { type: 'textarea', help: '明确缺什么资料以及可继续的人工入口，不声称已经解决。' })}`, { actions: moduleActions(ctx, 'service') })}
    ${section('转人工与恢复', `${editableField(ctx, '转人工条件', 'handoff.condition', handoff.condition, { type: 'textarea' })}<div class="grid-2">${editableField(ctx, '接收者或队列', 'handoff.recipient', handoff.recipient, { help: '这里只登记配置；接收者可用与实际承接由会话收件箱记录。' })}${editableField(ctx, '恢复检查等待时间（分钟）', 'handoff.resumeMinutes', handoff.resumeMinutes ?? 10, { type: 'number', help: '等待时间仅触发恢复检查，不自动证明任务完成或重用旧确认。' })}</div>${editableField(ctx, '触发短语', 'handoff.phrases', handoff.phrases || [], { type: 'textarea', format: 'lines', help: '每行一条。当前只是本地模拟触发，真实语义路由下一轮接入。' })}<p class="notice">人工接管、业务取消与问题解决分别留证。恢复前须检查当前占用、资料、权限、预算和确认有效性。</p>`, { actions: moduleActions(ctx, 'handoff') })}
    ${ctx.state.ui.depth === 'detailed' ? section('表达层与结构化配置的关系', `<p>下面是当前字段的只读组合预览；没有独立隐藏提示词，也不会把硬规则交给表达层修改。</p><pre class="diff-value">${escapeHtml([`服务目标：${config.goal || '未填写'}`, `服务范围：${config.scope || '未填写'}`, `表达方式：${config.tone || '未填写'}`, `缺资料出口：${config.fallback || '未填写'}`].join('\n'))}</pre><p class="helper">模型外规则、工具授权、幂等与结果裁决仍在各自层；预览不代表运行模型已接入。</p>`) : ''}`;
}

function renderKnowledgeSummary(ctx) {
  const sources = ctx.agent.config.sources || [];
  if (!sources.length) return section('资料与当前事实', emptyState('没有来源资料', '先添加一条有授权、来源标识和有效期的问答。资料缺失不会阻断保存草稿。', button('navigate', '去添加资料', { page: 'knowledge', variant: 'primary' })), { description: '来源上下文 · 来源事实，不由助手补造。' });
  return section('资料与当前事实', `<ul class="config-list">${sources.map(source => {
    const [statusLabel, tone] = sourceStates[source.status] || ['状态待确认', 'warning'];
    return `<li><div class="item-heading"><strong>${escapeHtml(source.title)}</strong><div class="inline">${badge(({ FAQ: '问答', URL: '网址', File: '文件' })[source.type] || '其他资料')}${badge(statusLabel, tone)}${badge(source.rights ? '授权已登记' : '缺授权', source.rights ? 'neutral' : 'warning')}</div></div><dl class="definition-list"><div><dt>来源 / 版本</dt><dd>${escapeHtml(source.sourceRef || '来源标识缺失')} · v${source.version}</dd></div><div><dt>有效期</dt><dd>${escapeHtml(source.expires || '尚未登记')}</dd></div><div><dt>撤回方式</dt><dd>${escapeHtml(source.revokeNote || '可在知识来源页撤回；后续模拟检索将停用')}</dd></div></dl>${source.error ? `<p class="notice notice-danger">${escapeHtml(source.error)}</p>` : ''}<details><summary>查看本地资料原文与引用范围</summary><div class="detail-content"><p>${escapeHtml(source.question || source.url || '本地来源')}</p><p class="preserve-lines">${escapeHtml(source.answer || source.body || '仅登记来源，正文解析尚未接入')}</p><p class="helper">来源被当前专家的答疑与试用引用；撤回或修改使当前检查和审批证据待重验，旧冻结版本保留自己的快照。</p></div></details></li>`;
  }).join('')}</ul><p class="notice">“演示索引就绪”只记录本地状态。网址不抓取、复杂文件不真实解析；资料审核与事实正确性仍需人工确认。</p>`, { description: '来源上下文 · 授权、版本、有效期与引用逐项可查看。', actions: button('navigate', '编辑来源与授权', { page: 'knowledge', variant: 'primary' }) });
}

function renderFields(ctx) {
  const fields = ctx.agent.config.fields || [];
  const items = fields.length ? `<ul class="config-list">${fields.map((item, index) => `<li><div class="item-heading"><strong>${escapeHtml(item.label)}</strong>${button('field-remove', '删除字段', { id: item.id, variant: 'danger', disabled: ctx.readonly })}</div><div class="grid-2">${editableField(ctx, '业务名称', `fields.${index}.label`, item.label)}${selectField(ctx, '取值来源', `fields.${index}.source`, item.source, [{ value: 'visitor', label: '访客提供' }, { value: 'tool', label: '工具结果' }])}</div>${checkbox(ctx, '必须填写', `fields.${index}.required`, item.required)}<details><summary>机器标识与引用影响</summary><div class="detail-content">${editableField(ctx, '字段 ID', `fields.${index}.id`, item.id, { help: '必须唯一。修改后需要复核流程、工具、案例与网站客服窗表单的字段映射。' })}<p class="field-impact helper">删除或改名会影响使用该字段的当前流程、工具和验收案例；本地原型不推断完整依赖图。已冻结版本保留旧字段，当前检查证据失效。</p></div></details></li>`).join('')}</ul>` : emptyState('尚未设置业务字段', '知识答疑可以不收集访客信息。需要办理业务时，再按最小必要范围添加字段。');
  const add = ctx.readonly ? '' : `<details class="add-section"><summary>添加业务字段</summary><form class="stack compact-form" data-form="field">${formField('业务名称', 'label', { required: true, placeholder: '例如：希望试听的课程' })}<div class="field"><label for="new-field-source">取值来源</label><select class="control input" id="new-field-source" name="source"><option value="visitor">访客提供</option><option value="tool">工具结果</option></select></div><label class="inline"><input type="checkbox" name="required"><span>必须填写</span></label><details><summary>自定义机器标识（可选）</summary>${formField('字段 ID', 'id', { help: '留空自动生成；自定义 ID 必须唯一。' })}</details>${submitButton('添加字段')}</form></details>`;
  return section('业务字段', items + add, { description: '同一个字段只定义一次。业务标签优先，机器标识与引用影响按需查看。' });
}

function renderFlow(ctx) {
  const flow = ctx.agent.config.flow || [];
  const body = flow.length ? `<ol class="config-list">${flow.map((item, index) => `<li><div class="item-heading"><strong>步骤 ${index + 1} · ${escapeHtml(item.title)}</strong><div class="item-actions">${button('flow-up', '上移', { id: item.id, variant: 'ghost', disabled: ctx.readonly || index === 0 })}${button('flow-down', '下移', { id: item.id, variant: 'ghost', disabled: ctx.readonly || index === flow.length - 1 })}${button('flow-remove', '删除', { id: item.id, variant: 'danger', disabled: ctx.readonly })}</div></div>${editableField(ctx, '步骤名称', `flow.${index}.title`, item.title)}${editableField(ctx, '触发、处理与回退说明', `flow.${index}.instruction`, item.instruction, { type: 'textarea', help: '说明何时进入、下一步、信息不足和失败时怎样结束；不使用任意脚本。' })}<details><summary>步骤标识与执行边界</summary><p class="helper">步骤 ID：<code>${escapeHtml(item.id)}</code>。当前按顺序模拟展示；优先级、任务代次和真实路由事件须由后端合同确认与记录。</p></details></li>`).join('')}</ol>` : emptyState('没有额外服务步骤', '纯问答答疑无需编排预约流程；需要收集信息或确认动作时可以添加步骤。');
  const add = ctx.readonly ? '' : `<details class="add-section"><summary>添加服务步骤</summary><form class="stack compact-form" data-form="flow">${formField('步骤名称', 'title', { required: true, placeholder: '例如：确认用户希望了解的课程' })}${formField('处理与回退说明', 'instruction', { type: 'textarea', required: true, placeholder: '何时进入、如何处理、缺信息或取消时如何退出' })}${submitButton('添加步骤')}</form></details>`;
  return section('请求与处理流程', `<p class="notice">请求路由选择当前唯一主请求。步骤文本是策略描述；权限与确认由锁定约束和工具策略决定。</p>${body}${add}`, { description: '请求路由 · 查看顺序、进入与回退，完整编辑当前草稿。', actions: moduleActions(ctx, 'flow') });
}

function renderSkills(ctx) {
  const skills = ctx.agent.config.skills || [];
  const body = skills.length ? `<ul class="config-list">${skills.map((item, index) => `<li><div class="item-heading"><strong>${escapeHtml(item.title)}</strong>${button('skill-remove', '删除策略', { id: item.id, variant: 'danger', disabled: ctx.readonly })}</div>${editableField(ctx, '策略名称', `skills.${index}.title`, item.title)}${editableField(ctx, '适用范围、步骤与示例', `skills.${index}.description`, item.description, { type: 'textarea', rows: 4 })}${editableField(ctx, '退出或转人工条件', `skills.${index}.exit`, item.exit, { type: 'textarea' })}<details><summary>策略标识与依赖边界</summary><p class="helper">Skill ID：<code>${escapeHtml(item.id)}</code>。依赖仅能使用当前已授权资料与已登记模拟工具；独立知识/工具引用和 Skill 版本合同留待后端接入，不能从文本推断授权。</p></details></li>`).join('')}</ul>` : emptyState('尚未添加处理策略', '按需补充业务的适用条件、示例与退出方式。没有额外策略不代表知识答疑不可用。');
  const add = ctx.readonly ? '' : `<details class="add-section"><summary>添加处理策略</summary><form class="stack compact-form" data-form="skill">${formField('策略名称', 'title', { required: true })}${formField('适用范围、处理步骤与示例', 'description', { type: 'textarea', required: true })}${formField('退出或转人工条件', 'exit', { type: 'textarea', required: true })}${submitButton('添加策略')}</form></details>`;
  return section('服务策略', `<p class="notice">处理策略与标准流程描述如何处理业务，不授予工具权限，也不开放任意代码执行。</p>${body}${add}`, { description: '处理策略与标准流程 · 当前版本的可审阅处理策略。' });
}

function renderRules(ctx) {
  const rules = ctx.agent.config.rules || [];
  const body = rules.length ? `<ul class="config-list">${rules.map(rule => `<li><div class="item-heading"><strong>${escapeHtml(rule.title)}</strong>${badge('锁定 · 只读', 'neutral')}</div><p>${escapeHtml(rule.description)}</p><dl class="definition-list"><div><dt>规则标识</dt><dd><code>${escapeHtml(rule.id)}</code></dd></div><div><dt>作用域</dt><dd>${rule.scope === 'task' ? '当前任务' : '全局'}</dd></div><div><dt>执行位置</dt><dd>模型外裁决；本页展示边界，不提供新规则引擎。</dd></div><div><dt>版本</dt><dd>随当前配置修订 r${ctx.agent.revision} 查看；冻结时进入版本快照。</dd></div></dl><details><summary>条件、裁决与关联证据</summary><p class="helper">可查看已登记的规则说明。条件算子、冲突偏序、具体裁决与关联案例合同仍待后端实现，当前不允许用自由文本新增可执行硬规则。</p></details><div class="button-group">${button('rule-propose', '提出待审修改建议', { id: rule.id, disabled: ctx.readonly })}${button('navigate', '查看验收案例', { page: 'cases', variant: 'ghost' })}</div></li>`).join('')}</ul>` : emptyState('未登记可展示的规则', '规则配置不由助手生成或自动授权。执行边界需在明确的规则合同中登记与审批。');
  return section('必须遵守的约束', `<div class="notice notice-warning"><strong>已批准边界不可直接修改</strong><p>权限、价格承诺、确认、停止与去重不能通过改表达或采用助手建议绕过。建议只进入待审提案，不使规则生效。</p></div>${body}`, { description: '硬性规则 · 只读定义与受控提案入口。' });
}

function renderTools(ctx) {
  const tools = ctx.agent.config.tools || [];
  const body = tools.length ? `<ul class="config-list">${tools.map((item, index) => `<li><div class="item-heading"><strong>${escapeHtml(item.title)}</strong><div class="inline">${badge('模拟 · 无外部写入', 'neutral')}${button('tool-remove', '删除动作', { id: item.id, variant: 'danger', disabled: ctx.readonly })}</div></div><div class="grid-2">${editableField(ctx, '动作名称', `tools.${index}.title`, item.title)}${selectField(ctx, '副作用类型', `tools.${index}.sideEffect`, item.sideEffect, [{ value: 'read', label: '模拟只读' }, { value: 'write', label: '模拟写入' }], '所有动作仍为 模拟；切换类型不能连接真实业务系统。')}</div>${checkbox(ctx, '执行前需要用户确认', `tools.${index}.requiresConfirm`, item.requiresConfirm, item.sideEffect === 'write' ? '模拟写入强制确认；不能关闭。' : '确认要求随配置冻结。', item.sideEffect === 'write')}<details><summary>工具合同与结果要求</summary><dl class="definition-list"><div><dt>工具 ID / 当前状态</dt><dd><code>${escapeHtml(item.id)}</code> · ${escapeHtml(item.status || 'mock')}</dd></div><div><dt>输入与字段映射</dt><dd>当前仅登记动作及业务字段。输入输出 Schema、参数映射与连接授权尚未接入。</dd></div><div><dt>超时、预算与幂等</dt><dd>真实执行前须由后端重新检查权限、预算、确认版本和幂等键；此页不假造已通过结果。</dd></div><div><dt>结果证据</dt><dd>${item.sideEffect === 'write' ? '模拟写入也须留模拟结果 ID；真实工具必须留外部结果 ID，缺回执标为未知。' : '只读结果须记录来源与实际返回；口头完成不构成证据。'}</dd></div></dl></details></li>`).join('')}</ul>` : emptyState('尚未配置业务动作', '可以先完成知识答疑试用。准备办理业务时，再添加受控的模拟动作。');
  const add = ctx.readonly ? '' : `<details class="add-section"><summary>添加模拟业务动作</summary><form class="stack compact-form" data-form="tool">${formField('动作名称', 'title', { required: true, placeholder: '例如：模拟创建试听预约' })}<div class="field"><label for="new-tool-effect">副作用类型</label><select class="control input" id="new-tool-effect" name="sideEffect"><option value="read">模拟只读</option><option value="write">模拟写入（强制确认）</option></select></div><p class="helper">不会接受凭据或产生外部副作用；真实连接、授权与结果合同将在下一轮接入。</p>${submitButton('添加 模拟 动作')}</form></details>`;
  return section('允许的业务动作', `<p class="notice">工具策略控制动作副作用与确认。处理策略引用动作不等于获得授权。</p>${body}${add}`, { description: '工具策略 · 仅本地 模拟 策略，保留权限与证据边界。' });
}

function renderOutcome(ctx) {
  const outcome = ctx.agent.config.outcome || {};
  return section('结果与验收依据', `${editableField(ctx, '什么才算完成', 'outcome.definition', outcome.definition, { type: 'textarea', rows: 4, help: '描述可核验业务结果；答疑不要求制造预约或其他业务写入。' })}${editableField(ctx, '未解决、失败或未知如何记录', 'outcome.unknown', outcome.unknown, { type: 'textarea', help: '区分缺资料、转人工未承接、取消、工具失败与结果回执未知。' })}<dl class="definition-list"><div><dt>答复生成</dt><dd>记录回答与所用资料引用；脚本模拟另计。</dd></div><div><dt>消息送达</dt><dd>需有独立送达回执；配置预览不等于送达。</dd></div><div><dt>问题解决</dt><dd>用户确认解决或标记未知；不能从生成成功推断。</dd></div><div><dt>业务办理</dt><dd>需保存业务状态、副作用与适用的结果 ID；失败、取消与未知分别留证。</dd></div></dl><p class="notice">这些是配置和验收要求。当前前端仅保存本地模拟记录，没有真实送达、后端持久化或外部结果证据。</p>`, { description: '结果证据 · 模型说“完成”不等于业务完成。', actions: `${button('navigate', '查看运行依据', { page: 'runs' })}${button('navigate', '编辑验收案例', { page: 'cases', variant: 'ghost' })}` });
}

function renderModel(ctx) {
  const connections = ctx.state.connections || [];
  const model = ctx.agent.config.model || { connectionId: 'simulation', budget: 2000 };
  const active = connections.find(item => item.id === model.connectionId);
  const options = connections.map(item => ({ value: item.id, label: `${item.name} · ${item.status === 'connected' || item.status === 'simulation' ? '演示可用' : '未验证'}` }));
  if (!options.some(item => item.value === model.connectionId)) options.unshift({ value: model.connectionId, label: '当前引用不可用 · 请重新选择' });
  return section('模型连接与预算', `<div class="grid-2">${selectField(ctx, '运行连接引用', 'model.connectionId', model.connectionId, options, '只保存连接引用，不在前端输入模型密钥。')}${editableField(ctx, '单次词元预算', 'model.budget', model.budget, { type: 'number', help: '本地检查的预算上限；没有真实词元消耗或费用统计。' })}</div><dl class="definition-list"><div><dt>当前连接</dt><dd>${escapeHtml(active?.name || '连接不可用')} · ${escapeHtml(active?.provider || '未登记')} / ${escapeHtml(active?.model || '未登记')}</dd></div><div><dt>数据去向</dt><dd>当前脚本模拟只在浏览器本地处理，不发送模型请求。真实服务端连接的数据流与凭据保管待接入。</dd></div><div><dt>流式 / 工具 / 取消</dt><dd>分别验证；连接测试演示不代表模型能力、业务权限或完整取消已通过。</dd></div><div><dt>外部创作助手接入</dt><dd>创建协助优先使用用户自己的创作助手，通过统一接口提交候选的方向已规划；桥接尚未接入，与客服执行模型连接分别管理。</dd></div></dl><details><summary>词元预算与接入技术说明</summary><p class="helper">词元（token）是模型计量单位；这里只检查本地预算值，不统计真实消耗。</p>${integrationTerms}</details><p class="notice notice-warning">创建草稿不要求模型连接。真实客服答疑仍需有权使用的有效连接；原型不会静默回退为模拟并声称真实 AI 已答复。</p>`, { actions: button('navigate', '管理连接与分项测试', { page: 'connections' }) });
}

function renderEvidence(ctx) {
  const { agent } = ctx;
  const origins = { ...(agent.manualPaths || {}), ...(agent.origins || {}) };
  const paths = Object.entries(origins);
  const changes = Array.isArray(agent.changeLog) ? agent.changeLog.slice(0, 100) : [];
  const moduleFor = path => modules.some(item => item.id === path.split('.')[0]) ? path.split('.')[0]
    : path.startsWith('sources') ? 'knowledge' : path.startsWith('model') ? 'model' : path.startsWith('outcome') ? 'outcome' : 'service';
  const sourceRows = paths.length
    ? `<div class="table-wrap"><table class="data-table"><thead><tr><th scope="col">字段路径</th><th scope="col">来源与依据</th><th scope="col">修订 / 时间</th><th scope="col">保护与定位</th></tr></thead><tbody>${paths.map(([path, entry]) => `<tr><td><code>${escapeHtml(path)}</code></td><td>${badge(entry?.origin === '助手建议' ? '助手建议 · 模拟' : entry?.origin || '人工修改', 'neutral')}<p class="helper">${escapeHtml(entry?.source || '当前浏览器草稿')}</p></td><td>${entry?.revision ? `r${escapeHtml(entry.revision)}` : '当前草稿'}<p class="helper">${entry?.time || entry?.at ? formatTime(entry.time || entry.at) : '旧数据未记录时间'}</p></td><td>${agent.manualPaths?.[path] ? '<p class="helper">手动修改，助手默认不能覆盖</p>' : ''}${button('set-section', '查看字段所在模块', { section: moduleFor(path), variant: 'ghost' })}</td></tr>`).join('')}</tbody></table></div>`
    : '<p class="muted">尚无本地字段来源记录。旧数据缺少记录时不推断来源，可继续手动配置。</p>';
  const changeRows = changes.length
    ? `<ul class="config-list">${changes.map(change => `<li><div class="item-heading"><strong><code>${escapeHtml(change.path)}</code> · r${escapeHtml(change.revision)}</strong>${badge(change.origin === '助手建议' ? '助手建议 · 模拟' : change.origin || '来源未记录', 'neutral')}</div><p class="helper">${formatTime(change.time)}${change.source ? ` · ${escapeHtml(change.source)}` : ''}</p><details><summary>查看旧值 / 新值与修改依据</summary><div class="diff-grid"><div><span class="helper">修改前</span><pre class="diff-value">${escapeHtml(diffValue(change.before))}</pre></div><div><span class="helper">修改后</span><pre class="diff-value">${escapeHtml(diffValue(change.after))}</pre></div></div><p class="helper">此记录只描述本地草稿修改；采用后需要重新检查，不自动替换旧入口绑定。</p></details><div class="button-group">${button('set-section', '查看配置所在模块', { section: moduleFor(change.path || ''), variant: 'ghost' })}</div></li>`).join('')}</ul>`
    : emptyState('尚无本地修改差异', '手动编辑或逐项采用模拟建议后，记录会在这里展示；旧数据不会补造历史。');
  return `${section('版本、有效值与证据', `<dl class="definition-list"><div><dt>当前配置</dt><dd>${ctx.state.ui.previewVersionId ? '当前冻结配置快照' : '同一个专家草稿'} r${escapeHtml(agent.revision)}；概览、业务配置与详细配置读取同一配置对象。</dd></div><div><dt>默认值与当前覆盖</dt><dd>界面展示当前配置的实际有效值。没有可变平台默认注入；已有冻结版本保留自己的值。</dd></div><div><dt>当前试用检查</dt><dd>${agent.checks?.testedRevision === agent.revision ? `r${escapeHtml(agent.revision)} · 本地演示检查` : '当前修改尚未重新检查'}</dd></div><div><dt>人工批准</dt><dd>${agent.checks?.approvedRevision === agent.revision ? `r${escapeHtml(agent.revision)} · 沙盒批准演示` : '当前草稿未批准'}</dd></div><div><dt>入口绑定</dt><dd>网站客服窗：${escapeHtml(agent.bindings?.widget || '未绑定')}；联系页：${escapeHtml(agent.bindings?.contact || '未绑定')}。修改草稿不自动替换旧绑定。</dd></div></dl><p class="notice">变更会使当前检查与审批待重验，旧运行和冻结版本保留自己的快照。服务端审计、完整依赖与真实发布门禁 尚未接入。</p>`, { actions: `${button('recheck', '检查当前草稿', { disabled: ctx.readonly })}${button('navigate', '查看版本与差异', { page: 'versions' })}${button('export-config', '导出当前配置', { variant: 'ghost' })}` })}
    ${section('本地字段来源', sourceRows, { description: '人工修改与助手采用保存在浏览器；手动字段默认受保护。这不是服务端审计。' })}
    ${section('本地修改差异', changeRows, { description: '最近最多 100 条草稿修改，包含来源、修订、时间与旧值/新值。冻结版本的完整来源审计尚未接入。' })}`;
}

export function renderConfiguration(ctx) {
  if (!ctx.agent) return unavailable(ctx);
  const detailed = ctx.state.ui.depth === 'detailed';
  const { active, navigation } = configNavigation(ctx);
  const renderers = {
    service: renderService, knowledge: renderKnowledgeSummary, flow: renderFlow, fields: renderFields,
    skills: renderSkills, rules: renderRules, tools: renderTools, outcome: renderOutcome,
    model: renderModel, evidence: renderEvidence,
  };
  const layers = detailed ? `<details class="section layer-map"><summary>六层配置与当前页面的关系</summary><dl class="definition-list">${modules.filter(item => item.layer).map(item => `<div><dt>${item.layer}</dt><dd>${item.title} · ${item.summary}</dd></div>`).join('')}</dl><p class="helper">接待表达、字段、模型、应用外观与版本证据围绕同一六层配置工作，不增加第七个业务层，也不暴露框架私有状态。</p></details>` : '';
  return `${pageHeading(detailed ? '详细配置与证据' : '业务配置', detailed ? '查看六层定义、实际有效值、受保护边界与版本依据。未决合同明确保留，不用配置原文代替业务配置。' : '从日常业务模块编辑同一份草稿；需要时下探完整定义与证据。', `<div class="button-group">${button('navigate', '脚本模拟', { page: 'trial' })}${button('toggle-assistant', ctx.state.ui.assistantOpen ? '关闭创作助手' : '创作助手（后续）', { variant: 'ghost' })}</div>`)}${readonlyNotice(ctx)}${saveState(ctx)}${layers}<div class="config-layout">${navigation}<div class="config-module" id="module-${active.id}">${renderers[active.id](ctx)}</div></div>`;
}

function diffValue(value) {
  if (value === null || value === undefined || value === '') return '（空）';
  if (Array.isArray(value)) return value.map(item => typeof item === 'object' ? JSON.stringify(item, null, 2) : item).join('\n');
  return typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value);
}

function renderSuggestion(ctx, suggestion) {
  const pending = suggestion.status === 'pending';
  const stale = pending && suggestion.baseRevision !== ctx.agent.revision;
  const manual = Boolean(ctx.agent.manualPaths?.[suggestion.path]);
  const blocked = Boolean(suggestion.blocked) || stale || manual;
  const statusLabel = suggestion.status === 'accepted' ? '已采用' : suggestion.status === 'rejected' ? '已拒绝' : stale ? '已过期' : blocked ? '受保护 · 不可采用' : '待审阅';
  const reason = stale ? '候选基于旧修订。当前草稿已改变，请保留修改，更新任务说明并重新接收候选。' : manual ? '该字段有手动修改，默认受保护；可拒绝这项建议后继续手动编辑。' : suggestion.blocked ? typeof suggestion.blocked === 'string' ? suggestion.blocked : '涉及锁定约束或高风险边界，只能形成待审提案。' : '';
  return `<article class="suggestion-item"><div class="item-heading"><strong>${escapeHtml(suggestion.label || suggestion.path)}</strong>${badge(statusLabel, stale || blocked ? 'warning' : suggestion.status === 'accepted' ? 'success' : 'neutral')}</div><p class="helper"><code>${escapeHtml(suggestion.path)}</code> · 基于 r${escapeHtml(suggestion.baseRevision)} · ${escapeHtml(suggestion.origin || '外部创作助手候选（本地模拟）')}</p><div class="diff-grid"><div><span class="helper">候选基准旧值</span><pre class="diff-value">${escapeHtml(diffValue(suggestion.before))}</pre></div><div><span class="helper">候选修改</span><pre class="diff-value">${escapeHtml(diffValue(suggestion.after))}</pre></div></div><p>${escapeHtml(suggestion.why || '尚未给出依据，采用前需要人工确认。')}</p><p class="helper">影响：${escapeHtml(suggestion.risk || '当前配置与试用检查需重新确认')}。采用后仅修改草稿，原检查与批准待重验，不更新入口绑定。</p>${reason ? `<p class="notice notice-warning">${escapeHtml(reason)}</p>` : ''}<div class="button-group">${button('assistant-accept', '采用此项', { id: suggestion.id, disabled: ctx.readonly || !pending || blocked, variant: 'primary' })}${button('assistant-reject', '拒绝此项', { id: suggestion.id, disabled: !pending, variant: 'ghost' })}</div></article>`;
}

export function renderAssistant(ctx) {
  if (!ctx.agent) return '';
  const assistant = ctx.state.ui.assistant || { suggestions: [] };
  const suggestions = assistant.suggestions || [];
  const sources = (ctx.agent.config.sources || []).filter(source => sourceValid(source, ctx.agent.revokedSourceIds || []));
  const protectedCount = Object.keys(ctx.agent.manualPaths || {}).length;
  const heading = `<div class="assistant-heading item-heading"><h2>创作助手（后续接入）</h2>${button('toggle-assistant', '关闭', { variant: 'ghost' })}</div>${badge('当前未连接外部创作助手', 'neutral')}<p>后续可由你自己的创作助手通过受限接口提交草稿或候选，继续在这里人工审阅。当前手动创建与配置完整可用，协助面板可以随时关闭。</p>${integrationTerms}`;
  const context = `<dl class="definition-list"><div><dt>当前目标</dt><dd>${escapeHtml(ctx.agent.config.goal || '尚未填写，可在业务配置中补齐')}</dd></div><div><dt>草稿修订</dt><dd>${escapeHtml(ctx.agent.name)} · r${escapeHtml(ctx.agent.revision)}；所有配置深度共用此草稿。</dd></div><div><dt>授权资料范围</dt><dd>${sources.length} 项有效授权来源，仅列引用元数据。</dd></div><div><dt>手动保护</dt><dd>${protectedCount} 项人工修改受保护；过期候选不能覆盖当前值。</dd></div></dl>${sources.length ? `<ul class="summary-list">${sources.map(source => `<li><span><strong>${escapeHtml(source.title)}</strong><small>${escapeHtml(source.sourceRef)} · v${escapeHtml(source.version)}</small></span></li>`).join('')}</ul>` : '<p class="helper">还没有有效授权资料。先手动补充并审阅来源，避免从缺失资料推断业务事实。</p>'}<div class="button-group">${button('assistant-copy', '复制受限配置任务说明')}${button('navigate', '管理资料', { page: 'knowledge', variant: 'ghost' })}</div><p class="helper">复制内容仅含服务目标、草稿标识与资料引用元数据，不包含资料正文、凭据或新增访问授权；不会发送外部请求。</p>`;
  const candidateBody = suggestions.length
    ? `<div class="stack">${suggestions.map(item => renderSuggestion(ctx, item)).join('')}</div><div class="button-group">${button('assistant-clear', '清空样例候选', { variant: 'ghost' })}</div>`
    : '<p class="helper">可载入固定的虚构候选，预览逐项差异与人工采用方式。真实桥接及外部候选提交尚未接入。</p>';
  const review = `<details ${suggestions.length ? 'open' : ''}><summary>候选差异预览（虚构样例）</summary><div class="stack detail-content"><p class="notice">仅演示未来协作的审阅界面。样例不会自动采用，修改草稿不会更新已冻结版本或入口。</p>${button('assistant-generate', suggestions.length ? '重新载入虚构候选' : '载入虚构候选样例', { scope: 'all', prompt: '', disabled: ctx.readonly })}${candidateBody}</div></details>`;
  return `<div class="assistant-content stack">${heading}${context}${ctx.readonly ? '<div class="notice notice-warning">当前版本只读。可以查看差异与复制说明；返回草稿后才能采用候选。</div>' : ''}${review}<p class="helper">配置事实、授权、硬规则、工具权限、验收真值与发布权继续由人工和平台规则控制。</p></div>`;
}
