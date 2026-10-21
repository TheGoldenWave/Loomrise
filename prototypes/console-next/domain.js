import { clone } from './fixtures.js';

export const LOCAL_CONNECTION = 'simulation';
export function getPath(object, path) {
  return path.split('.').reduce((value, key) => value?.[key], object);
}
export function setPath(object, path, value) {
  const keys = path.split('.');
  if (keys.some(key => ['__proto__', 'constructor', 'prototype'].includes(key))) throw new Error('不能修改此字段');
  const target = keys.slice(0, -1).reduce((part, key) => part?.[key], object);
  if (!target || !(keys.at(-1) in target)) throw new Error('字段已不存在，请重新载入配置');
  target[keys.at(-1)] = value;
}
export function configPathEditable(path) {
  if (/^materialPolicy\.(enabled|requireExplicitRequest|preferredVariant|allowOriginalFallback|maxCount)$/.test(path)) return true;
  return /^(goal|audience|scope|tone|greeting|fallback|handoff\.(phrases|recipient|condition|resumeMinutes)|model\.(connectionId|budget)|outcome\.(definition|unknown)|widget\.(title|color|language|timezone|hours|formMode|showFaq|bookingUrl|enabled)|contact\.(title|description|blocks\.\d+\.(title|body))|fields\.\d+\.(id|label|source|required)|flow\.\d+\.(title|instruction)|skills\.\d+\.(title|description|exit)|tools\.\d+\.(title|sideEffect|requiresConfirm))$/.test(path);
}
export function sourceValid(source, revoked = [], today = new Date().toISOString().slice(0, 10)) {
  return !source.metadataOnly && source.status === 'indexed' && source.rights === true && Boolean(source.sourceRef) && validDate(source.expires) && source.expires >= today && !revoked.includes(source.id);
}
export function validDate(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value || '')) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value;
}
export function prepareAgentTask(agent) {
  return {
    purpose: '在授权范围内提出客服配置候选，由人逐项审阅采用',
    target: { agentId: agent.id, baseRevision: agent.revision, name: agent.name, goal: agent.config.goal },
    sources: agent.config.sources.filter(source => sourceValid(source, agent.revokedSourceIds || [])).map(({ id, title, type, sourceRef, version, expires }) => ({ id, title, type, sourceRef, version, expires })),
    allowedSuggestions: ['业务表达', '处理步骤', '人工出口文案'],
    constraints: ['不要覆盖人工锁定项', '不要修改权限、硬规则、价格承诺、真值或发布状态', '返回每项旧值、新值、依据与基准修订', '实际读取资料必须另获授权'],
    integrationStatus: '真实 MCP/Skills 桥接尚未接入；这仅是人工准备的任务摘要',
    excluded: '未包含资料全文、凭据、客户会话、盲测或运行日志',
  };
}
export function knowledgeConflicts(config, revoked = []) {
  const groups = new Map();
  for (const source of config.sources.filter(source => source.type === 'FAQ' && sourceValid(source, revoked))) {
    const question = normalize(source.question); if (!question) continue;
    const group = groups.get(question) || []; group.push(source); groups.set(question, group);
  }
  return [...groups.values()].filter(group => new Set(group.map(source => normalize(source.answer))).size > 1);
}
export function validateConfig(config) {
  const errors = [];
  if (!config.goal.trim()) errors.push('请填写服务目标');
  if (!config.audience.trim()) errors.push('请填写服务对象');
  if (!config.scope.trim()) errors.push('请填写服务范围');
  if (!config.fallback.trim()) errors.push('请填写资料不足时的回复');
  if (!(config.model.budget > 0 && config.model.budget <= 100000)) errors.push('试用预算需为 1–100000 的整数');
  if (!(config.handoff.resumeMinutes >= 1 && config.handoff.resumeMinutes <= 1440)) errors.push('接待恢复检查间隔需在 1–1440 分钟内');
  if (config.materialPolicy && (!Number.isInteger(config.materialPolicy.maxCount) || config.materialPolicy.maxCount < 1 || config.materialPolicy.maxCount > 5)) errors.push('每次自动发送物料数量需为 1–5；此为本地演示上限');
  const ids = config.fields.map(field => field.id);
  if (new Set(ids).size !== ids.length) errors.push('业务字段标识重复，请修改为唯一标识');
  if (ids.some(id => !/^[a-z][a-z0-9_]{0,47}$/.test(id))) errors.push('字段标识需以小写字母开头，只含字母、数字或下划线');
  if (config.fields.some(field => !field.label.trim())) errors.push('业务字段名称不能为空');
  if (config.flow.length < 1) errors.push('至少保留一个处理步骤');
  if (config.flow.some(step => !step.title.trim() || !step.instruction.trim())) errors.push('请补齐步骤标题与处理说明');
  if (config.tools.some(tool => tool.sideEffect === 'write' && !tool.requiresConfirm)) errors.push('业务写入必须保留确认要求');
  if (config.widget.bookingUrl && !/^https?:\/\//.test(config.widget.bookingUrl)) errors.push('预约外链需以 http:// 或 https:// 开头');
  return errors;
}
export function versionValid(agent, version, connections) {
  if (!version) return false;
  const sources = version.config.sources.filter(source => sourceValid(source, agent.revokedSourceIds || []));
  const connection = connections.find(item => item.id === version.config.model.connectionId);
  return sources.length > 0 && Boolean(connection && ['simulation', 'mock-connected'].includes(connection.status));
}
export function readiness(agent, connections = []) {
  if (!agent) return { items: [], issues: ['请先选择专家'], knowledgeCount: 0, canTrial: false, canApprove: false };
  const errors = validateConfig(agent.config);
  const sources = agent.config.sources.filter(source => sourceValid(source, agent.revokedSourceIds || []));
  const conflicts = knowledgeConflicts(agent.config, agent.revokedSourceIds || []);
  const connection = connections.find(item => item.id === agent.config.model.connectionId);
  const connected = Boolean(connection && ['simulation', 'mock-connected'].includes(connection.status));
  const tested = agent.checks.testedRevision === agent.revision;
  const approved = agent.checks.approvedRevision === agent.revision;
  const bound = agent.versions.find(version => version.id === agent.bindings.widget);
  const bindingValid = versionValid(agent, bound, connections);
  const items = [
    { id: 'goal', label: '业务配置', status: errors.length ? 'missing' : 'ok', detail: errors[0] || '目标、处理范围和确定性约束已填写', page: 'configuration' },
    { id: 'knowledge', label: '可用资料', status: sources.length && !conflicts.length ? 'ok' : 'missing', detail: conflicts.length ? `发现 ${conflicts.length} 组相同问题的冲突答案，请人工核实后撤回不适用口径` : sources.length ? `${sources.length} 份授权且有效的演示资料可匹配问题` : '添加资料，确认授权并完成本地审阅；没有资料仍可继续编辑', page: 'knowledge' },
    { id: 'connection', label: '模型连接', status: connected ? 'warning' : 'missing', detail: connected ? '当前使用模拟连接，没有调用真实模型' : '先选择脚本演示连接；真实模型将在后端阶段接入', page: 'connections' },
    { id: 'trial', label: '本版试用', status: tested ? 'ok' : 'missing', detail: tested ? '当前草稿已完成脚本模拟试用，不能证明真实模型质量' : '修改后需重新试用，历史记录继续保留', page: 'trial' },
    { id: 'approval', label: '沙盒批准', status: approved ? 'warning' : 'missing', detail: approved ? '当前版本已完成本地模拟批准' : '脚本检查后，由人明确批准本地演示版本', page: 'versions' },
    { id: 'binding', label: '网页入口', status: bindingValid ? 'warning' : 'missing', detail: bound ? `${bound.id} 是本地绑定；${bindingValid ? '草稿修改不覆盖这个版本' : '来源或连接已失效，不能重新使用该版本'}` : '未绑定演示版本；保存不等于发布', page: 'widget' },
  ];
  const issues = [...errors, ...(!sources.length ? ['没有有效的已审阅资料'] : []), ...(conflicts.length ? ['资料存在未裁决的相同问题冲突口径'] : []), ...(!connected ? ['缺少可用的演示连接'] : [])];
  return { items, knowledgeCount: sources.length, issues, canTrial: issues.length === 0, canApprove: issues.length === 0 && tested };
}
const normalize = text => String(text || '').toLowerCase().replace(/[\s？?。！!，,]/g, '');
export function simulateReply(config, question, revokedIds = []) {
  const text = normalize(question);
  if (config.handoff.phrases.some(phrase => text.includes(normalize(phrase)) && phrase.trim())) {
    return { text: `已记录模拟转人工请求，目标为“${config.handoff.recipient || '未设置'}”。这不代表人工已承接或业务已取消。`, status: 'handoff', sources: [] };
  }
  const valid = config.sources.filter(source => sourceValid(source, revokedIds));
  if (knowledgeConflicts(config, revokedIds).some(group => group.some(source => normalize(source.question) === text))) {
    return { text: '资料中存在未确认的冲突口径，请人工核实后再答复。', status: 'unknown', sources: [] };
  }
  const source = valid.find(item => item.type === 'FAQ' && normalize(item.question) && (normalize(item.question) === text || (text.length >= 4 && normalize(item.question).includes(text))));
  if (source) return { text: source.answer, status: 'answered', sources: [{ id: source.id, title: source.title, version: source.version }] };
  const fragment = valid.find(item => item.type === 'File' && item.body && text.length >= 2 && (normalize(item.title).includes(text) || normalize(item.body).includes(text)));
  if (fragment) return { text: `本地脚本匹配到“${fragment.title}”：${fragment.body.slice(0, 600)}`, status: 'answered', sources: [{ id: fragment.id, title: fragment.title, version: fragment.version }] };
  return { text: config.fallback, status: 'unknown', sources: [] };
}
export function buildSuggestions(agent, prompt, scope = 'all') {
  const sourceTitles = agent.config.sources.filter(source => sourceValid(source, agent.revokedSourceIds || [])).map(source => source.title);
  const suggestions = [];
  const add = (path, label, after, why, risk = false) => {
    const before = getPath(agent.config, path);
    if (before === undefined || JSON.stringify(before) === JSON.stringify(after)) return;
    suggestions.push({ id: `suggestion-${suggestions.length + 1}`, path, label, before: clone(before), after, why, origin: sourceTitles.length ? `依据当前已审阅资料：${sourceTitles.join('、')}` : '模板建议，无新增业务事实', risk, blocked: risk || Boolean(agent.manualPaths[path]), baseRevision: agent.revision, status: 'pending' });
  };
  if (['all', 'service'].includes(scope)) {
    add('greeting', '开场说明服务范围', `你好，我是${agent.name}。可以先了解你的问题吗？我会依据资料回答，必要时交给人工。`, '确定性演示建议：介绍资料答疑与人工出口；不会自动采用。');
    add('scope', '整理资料范围', sourceTitles.length ? `当前可依据${sourceTitles.join('、')}答疑；资料外问题交人工，不作未授权承诺。` : '只回答已审阅且有效的资料；暂无资料时说明不足，不补造事实。', '将已登记资料名称整理为可审阅的范围摘要。');
  }
  if (['all', 'flow'].includes(scope) && agent.config.flow.length) add('flow.0.instruction', '先澄清当前问题', '先确认用户当前最需要了解的一个问题；不收集与答疑无关的个人信息。', '演示处理顺序建议，无权限变化。');
  if (['all', 'handoff'].includes(scope)) add('fallback', '补充资料不足的说明', `现有资料还不足以回答。我可以将这个问题交给${agent.config.handoff.recipient || '人工客服'}，或请你补充问题。`, '将未知结果与交接选项明确区分。');
  if (/权限|价格|退款|承诺|免确认|自动发布/.test(prompt)) add('rules.1.description', '涉及授权或业务承诺', prompt, '此项涉及硬规则/业务承诺，只能形成待审问题，助手不能修改。', true);
  const conflicting = knowledgeConflicts(agent.config, agent.revokedSourceIds || []).length > 0;
  return { suggestions, conflict: conflicting, message: conflicting ? '发现相同问题有不同答案，请在资料库核实并撤回不适用资料。助手不会自行选择口径。' : sourceTitles.length ? '建议已生成。这里只演示可审阅差异，没有运行真实 AI。' : '还没有可用资料，以下仅为模板建议；先添加自己的授权资料。' };
}
