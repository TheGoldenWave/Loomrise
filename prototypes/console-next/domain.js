import { clone } from './fixtures.js';
import { detectCandidateConflicts, normalizeQuestion, resolveFactReferences, ruleHitCount } from './knowledge-model.js';
import { projectRouteGraph, validateRouteGraph } from './flow-model.js';

export const LOCAL_CONNECTION = 'simulation';
export function describeChange(change) {
  if (change.summary) return change.summary;
  const path = change.path || '';
  if (path.startsWith('tools.') && change.objectTitle) return `办理“${change.objectTitle}”的${({ input: '客户入参', successField: '办成标志', requiresConfirm: '客户确认要求', failureAction: '未办成处理', unknownAction: '结果不明处理', title: '名称' })[path.split('.').at(-1)] || '设置'}已调整`;
  const labels = { name: '专家名称', goal: '服务目标', audience: '服务对象', scope: '回答范围', tone: '表达方式', greeting: '欢迎语', fallback: '资料不足时的回复', 'model.budget': '模型预算', 'handoff.recipient': '人工接收方' };
  const label = labels[change.path];
  if (label && typeof change.after !== 'object') return `${label}${change.before != null ? `从“${change.before}”改为` : '设为'}“${change.after}”`;
  return ({ sources: '知识库资料已更新', qaItems: '问答已核对或修改', keyFacts: '关键信息已更新', businessRules: '红线已调整', routeGraph: '对话流程已调整', tools: '业务办理已调整', 'undo-batch': '已撤销上一次批量操作' })[change.path] || '接待设置已调整';
}
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
  return /^(goal|audience|scope|tone|greeting|fallback|handoff\.(phrases|recipient|condition|resumeMinutes)|model\.(connectionId|budget)|outcome\.(definition|unknown)|widget\.(title|color|language|timezone|hours|formMode|showFaq|bookingUrl|enabled)|contact\.(title|description|blocks\.\d+\.(title|body))|fields\.\d+\.(id|label|source|required)|flow\.\d+\.(title|instruction)|skills\.\d+\.(title|description|exit)|tools\.\d+\.(title|sideEffect|requiresConfirm|input|successField|failureAction|unknownAction))$/.test(path);
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
  const validSources = config.sources.filter(source => sourceValid(source, revoked));
  for (const source of validSources) {
    const explicit = (config.qaItems || []).filter(item => item.sourceId === source.id);
    const records = explicit.length ? explicit.filter(item => item.reviewStatus !== 'rejected').map(item => ({ ...item, type: 'FAQ', sourceId: source.id, status: item.reviewStatus === 'pending' ? 'review' : 'indexed' })) : source.type === 'FAQ' ? [{ ...source, status: 'indexed' }] : [];
    for (const record of records) {
      const question = normalize(record.question); if (!question) continue;
      const group = groups.get(question) || []; group.push({ ...record, sourceTitle: source.title, batchId: source.batchId || source.id, status: record.status || 'reviewed' }); groups.set(question, group);
    }
  }
  return [...groups.values()].filter(group => group.some(item => item.status !== 'review') && new Set(group.filter(item => item.status !== 'review').map(item => normalize(item.answer))).size > 1);
}
export function validateConfig(config) {
  const errors = [];
  const add = (path, message, page = 'settings') => errors.push({ path, message, page });
  if (!config.goal.trim()) add('goal', '请填写服务目标');
  if (!config.audience.trim()) add('audience', '请填写服务对象');
  if (!config.scope.trim()) add('scope', '请填写服务范围');
  if (!config.fallback.trim()) add('fallback', '请填写资料不足时的回复');
  if (!(Number.isInteger(config.model.budget) && config.model.budget > 0 && config.model.budget <= 100000)) add('model.budget', '模型预算需为 1–100000 的整数', 'settings');
  if (!(config.handoff.resumeMinutes >= 1 && config.handoff.resumeMinutes <= 1440)) add('handoff.resumeMinutes', '接待恢复检查间隔需在 1–1440 分钟内', 'settings');
  if (config.materialPolicy && (!Number.isInteger(config.materialPolicy.maxCount) || config.materialPolicy.maxCount < 1 || config.materialPolicy.maxCount > 5)) add('materialPolicy.maxCount', '每次自动发送物料数量需为 1–5', 'settings');
  const ids = config.fields.map(field => field.id);
  if (new Set(ids).size !== ids.length) add('fields', '业务字段标识重复，请修改为唯一标识', 'business');
  if (ids.some(id => !/^[a-z][a-z0-9_]{0,47}$/.test(id))) add('fields', '字段标识需以小写字母开头，只含字母、数字或下划线', 'business');
  if (config.fields.some(field => !field.label.trim())) add('fields', '业务字段名称不能为空', 'business');
  if (!config.routeGraph && config.flow.length < 1) add('flow', '至少保留一个处理步骤', 'flow');
  if (!config.routeGraph && config.flow.some(step => !step.title.trim() || !step.instruction.trim())) add('flow', '请补齐步骤标题与处理说明', 'flow');
  if (config.tools.some(tool => tool.sideEffect === 'write' && !tool.requiresConfirm)) add('tools', '业务写入必须保留确认要求', 'business');
  if (config.widget.bookingUrl && !/^https?:\/\//.test(config.widget.bookingUrl)) add('widget.bookingUrl', '预约外链需以 http:// 或 https:// 开头', 'versions');
  return errors;
}
export function pendingItems(agent, state = {}) {
  if (!agent) return [];
  const items = validateConfig(agent.config).map(issue => ({
    id: `config:${issue.path}`, level: 'block', page: issue.page, target: issue.path,
    text: issue.message, fix: '去处理',
  }));
  if (Array.isArray(state.connections) && !state.connections.some(connection => connection.id === agent.config.model.connectionId && ['simulation', 'mock-connected'].includes(connection.status))) items.push({ id: 'connection:ready', level: 'block', page: 'settings', target: 'model.connectionId', text: '当前模型连接不可用，请选择并检查连接', fix: '检查模型连接' });
  const sources = agent.config.sources || [];
  const batches = new Set();
  for (const source of sources) {
    if (source.status === 'revoked') continue;
    const batch = source.batchId || source.id;
    if ((!source.rights || !source.sourceRef || !validDate(source.expires) || source.expires < new Date().toISOString().slice(0, 10)) && !batches.has(batch)) {
      batches.add(batch);
      items.push({ id: `rights:${batch}`, level: 'block', page: 'knowledge', target: batch, text: `“${source.title}”这批资料还没声明授权、出处和有效期`, fix: '核对资料' });
    }
    const unreviewed = [...(agent.config.qaItems || []), ...(agent.config.keyFacts || [])].filter(item => item.sourceId === source.id && item.reviewStatus === 'pending');
    if (unreviewed.length) items.push({ id: `review:${batch}`, level: 'block', page: 'knowledge', target: source.id, text: `“${source.title}”有 ${unreviewed.length} 条新内容待核对`, fix: '开始核对' });
  }
  if (!sources.some(source => sourceValid(source, agent.revokedSourceIds || []))) items.push({ id: 'knowledge:ready', level: 'block', page: 'knowledge', target: 'sources', text: '知识库还没有已核对的可用资料', fix: '放资料' });
  for (const fact of agent.config.keyFacts || []) if (fact.reviewStatus !== 'rejected' && !fact.sourceRef?.trim()) items.push({ id: `fact:${fact.id}`, level: 'block', page: 'knowledge', target: fact.id, text: `关键信息“${fact.name}”缺出处，不能上线`, fix: '补出处' });
  for (const tool of agent.config.tools || []) if (tool.sideEffect === 'write' && !tool.successField?.trim()) items.push({ id: `tool:${tool.id}`, level: 'block', page: 'business', target: tool.id, text: `“${tool.title}”缺少办成标志`, fix: '设置办成标志' });
  const conflictedQuestions = new Map();
  for (const group of knowledgeConflicts(agent.config, agent.revokedSourceIds || [])) conflictedQuestions.set(normalize(group[0].question), group[0]);
  for (const item of agent.config.qaItems || []) {
    if (!item.question || item.reviewStatus === 'rejected') continue;
    const conflicts = detectCandidateConflicts({ ...item, kind: 'qa' }, { qaItems: agent.config.qaItems.filter(other => other.id !== item.id), keyFacts: agent.config.keyFacts || [], sources: agent.config.sources || [] });
    if (conflicts.length) conflictedQuestions.set(normalize(item.question), item);
  }
  for (const [index, [question, item]] of [...conflictedQuestions.entries()].entries()) items.push({ id: `knowledge:conflict:${index}`, level: 'block', page: 'knowledge', target: item.sourceId || item.id, text: `“${item.question || question}”在多份资料中说法不一致`, fix: '核对说法' });
  const conflictedFacts = new Set();
  for (const fact of agent.config.keyFacts || []) {
    if (fact.reviewStatus === 'rejected' || conflictedFacts.has(normalize(fact.name))) continue;
    if (detectCandidateConflicts({ ...fact, kind: 'fact' }, { keyFacts: agent.config.keyFacts }).length) {
      conflictedFacts.add(normalize(fact.name));
      items.push({ id: `knowledge:conflict:fact:${fact.id}`, level: 'block', page: 'knowledge', target: fact.sourceId || fact.id, text: `关键信息“${fact.name}”存在不同数值或条件`, fix: '核对数值' });
    }
  }
  for (const issue of validateRouteGraph(projectRouteGraph(agent.config), agent.config)) items.push({ id: `flow:${issue.path}`, level: 'block', page: 'flow', target: issue.path, text: issue.message, fix: issue.path.endsWith('.fallback') ? '加转人工' : '定位' });
  for (const rule of agent.config.businessRules || []) {
    if (rule.enabled === false) continue;
    const hits = ruleHitCount(state.runs || [], agent.id, rule.id);
    if (!hits) items.push({ id: `rule-unused:${rule.id}`, level: 'suggest', page: 'redlines', target: rule.id, text: `红线“${rule.title || rule.condition?.value || '未命名'}”近 7 天没触发过，确认是否生效`, fix: '检查红线' });
  }
  for (const feedback of state.feedback || []) if (feedback.agentId === agent.id && feedback.status === 'open') items.push({ id: `feedback:${feedback.id}`, level: 'suggest', page: 'test', target: feedback.id, text: `试一试反馈“${feedback.question}”答错了`, fix: '转为测试题' });
  for (const item of state.cases || []) if (item.agentId === agent.id && (item.result === 'fail' || item.decision === 'wrong')) items.push({ id: `case:${item.id}`, level: 'block', page: 'test', target: item.id, text: `测试题“${item.title}”变差，${item.decision === 'wrong' ? '答案需修正并重新验证' : '请先决定答案错了还是题过时'}`, fix: '去看测试题' });
  return items;
}
export function versionValid(agent, version, connections) {
  if (!version) return false;
  const sources = version.config.sources.filter(source => sourceValid(source, agent.revokedSourceIds || []));
  const connection = connections.find(item => item.id === version.config.model.connectionId);
  return sources.length > 0 && Boolean(connection && ['simulation', 'mock-connected'].includes(connection.status));
}
export function readiness(agent, connections = []) {
  if (!agent) return { items: [], issues: ['请先选择专家'], knowledgeCount: 0, canTrial: false, canApprove: false };
  const errors = validateConfig(agent.config).map(issue => issue.message);
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
const normalize = normalizeQuestion;
function ruleMatches(rule, question, validSources, facts) {
  const { field, operator } = rule.condition || {};
  const resolvedValue = resolveFactReferences(rule.condition?.value, facts);
  if (/\{[^{}]+\}/.test(resolvedValue)) return false;
  const text = normalize(question), value = normalize(resolvedValue);
  if (!value || rule.enabled === false) return false;
  const asksPrice = /价格|费用|学费|报价|多少钱|收费|元|￥|¥/.test(question);
  if (field === '报价金额') {
    if (!asksPrice) return false;
    const limit = Number(value.replace(/[^0-9.]/g, ''));
    const amounts = [...question.matchAll(/\d+(?:\.\d+)?/g)].map(match => Number(match[0]));
    return operator === 'gt' ? amounts.some(amount => amount > limit) : amounts.some(amount => amount === limit);
  }
  if (field === '资料范围' && operator === 'missing') {
    if (!asksPrice || !/价格|费用|学费|报价/.test(value)) return false;
    const known = [...validSources.map(source => `${source.question || ''} ${source.answer || ''} ${source.body || ''}`), ...facts.map(fact => `${fact.name} ${fact.value}`)];
    return !known.some(entry => /价格|费用|学费|报价|元|￥|¥/.test(entry) && /\d/.test(entry));
  }
  if (operator === 'exact' || (operator === 'is' && field === '客户说了')) return text === value;
  if (operator === 'contains') return text.includes(value);
  if (operator !== 'is') return false;
  const categories = field === '客户诉求' ? { 退款: /退款|退费/, 人工: /人工|真人/, 退款时效: /(?:退款|退费).*(?:多久|几天|到账|时效)/, 保证结果: /保证|保底|一定.*(?:通过|成功)|包过/, 取消: /取消/ } : field === '客户情绪' ? { 投诉: /投诉|不满意|差评|太差|气死/ } : field === '客户资料' ? { 证件号: /证件号|身份证号/ } : {};
  return categories[value] ? categories[value].test(question) : text === value;
}
export function simulateReply(config, question, revokedIds = []) {
  const text = normalize(question);
  const valid = config.sources.filter(source => sourceValid(source, revokedIds));
  const disputedFacts = new Set((config.keyFacts || []).filter(fact => fact.reviewStatus !== 'rejected' && detectCandidateConflicts({ ...fact, kind: 'fact' }, { keyFacts: config.keyFacts || [] }).length).map(fact => normalize(fact.name)));
  const facts = (config.keyFacts || []).filter(fact => !disputedFacts.has(normalize(fact.name)) && !['pending', 'rejected'].includes(fact.reviewStatus) && (!fact.sourceId || valid.some(source => source.id === fact.sourceId)));
  const resolveAnswer = answer => {
    const resolved = resolveFactReferences(answer, facts);
    return /\{[^{}]+\}/.test(resolved) ? { text: '这条答复引用的关键信息仍待核对，请人工确认后再回答。', status: 'unknown', sources: [], ruleHits: [] } : null;
  };
  const rules = (config.businessRules || []).filter(rule => ruleMatches(rule, String(question), valid, facts));
  if (rules.length) {
    const rule = rules[0];
    const replies = { handoff: `已记录模拟转人工请求，目标为“${rule.recipient || config.handoff.recipient || '未设置'}”。这不代表人工已承接或业务已取消。`, confirm: '这一步需要你先确认，未确认前不会办理。', refuse: '目前没有可核实依据，不能按这个说法答复。', end: '本次对话到这里结束，如需帮助请联系人工。', later: '已记录问题，稍后由人工核实后回复。' };
    return { text: replies[rule.action] || replies.refuse, status: rule.action === 'handoff' ? 'handoff' : 'unknown', sources: [], ruleHits: [rule.id] };
  }
  if (!config.handoffMigrated && config.handoff.phrases.some(phrase => text.includes(normalize(phrase)) && phrase.trim())) {
    return { text: `已记录模拟转人工请求，目标为“${config.handoff.recipient || '未设置'}”。这不代表人工已承接或业务已取消。`, status: 'handoff', sources: [], ruleHits: [] };
  }
  const pendingConflict = (config.qaItems || []).some(item => item.reviewStatus === 'pending' && normalize(item.question) === text && detectCandidateConflicts({ ...item, kind: 'qa' }, { qaItems: config.qaItems.filter(other => other.id !== item.id), keyFacts: config.keyFacts || [], sources: config.sources || [] }).length > 0);
  if (pendingConflict || knowledgeConflicts(config, revokedIds).some(group => group.some(source => normalize(source.question) === text))) {
    return { text: '资料中存在未确认的不同说法，请人工核实后再答复。', status: 'unknown', sources: [], ruleHits: [] };
  }
  if ((config.qaItems || []).some(item => item.reviewStatus === 'pending' && normalize(item.question) === text)) return { text: '这条问题有新资料待核对，先请人工确认当前说法。', status: 'unknown', sources: [], ruleHits: [] };
  const qa = (config.qaItems || []).find(item => item.reviewStatus === 'reviewed' && normalize(item.question) === text && valid.some(source => source.id === item.sourceId));
  if (qa) {
    const origin = valid.find(source => source.id === qa.sourceId);
    const unresolved = resolveAnswer(qa.answer); if (unresolved) return unresolved;
    return { text: resolveFactReferences(qa.answer, facts), status: 'answered', sources: [{ id: origin.id, title: origin.title, version: origin.version }], ruleHits: [] };
  }
  const reviewedSources = new Set((config.qaItems || []).map(item => item.sourceId));
  const source = valid.find(item => item.type === 'FAQ' && !reviewedSources.has(item.id) && normalize(item.question) && (normalize(item.question) === text || (text.length >= 4 && normalize(item.question).includes(text))));
  if (source) return resolveAnswer(source.answer) || { text: resolveFactReferences(source.answer, facts), status: 'answered', sources: [{ id: source.id, title: source.title, version: source.version }], ruleHits: [] };
  const fragment = valid.find(item => item.type === 'File' && !item.batchId && !reviewedSources.has(item.id) && item.body && text.length >= 2 && (normalize(item.title).includes(text) || normalize(item.body).includes(text)));
  if (fragment) return { text: `本地脚本匹配到“${fragment.title}”：${fragment.body.slice(0, 600)}`, status: 'answered', sources: [{ id: fragment.id, title: fragment.title, version: fragment.version }], ruleHits: [] };
  return { text: config.fallback, status: 'unknown', sources: [], ruleHits: [] };
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
