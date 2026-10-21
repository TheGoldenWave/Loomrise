import { clone } from './fixtures.js';
import { readiness, simulateReply, sourceValid } from './domain.js';
import { ensureMaterialState, materialAllowed, materialAssetSendCheck, materialPreferredVariant } from './material-domain.js';

const SURFACES = ['trial', 'widget'];
const text = value => String(value ?? '').trim();
const normalized = value => text(value).toLocaleLowerCase().replace(/[\s，,。.!！?？、；;：:]/g, '');
let sequence = 0;

function fields(surface) {
  if (!SURFACES.includes(surface)) throw new Error('访客试用入口无效');
  const prefix = surface === 'trial' ? 'trial' : 'widgetTrial';
  return { input: `${prefix}Input`, messages: `${prefix}Messages`, status: `${prefix}State`, pending: surface === 'trial' ? 'pendingTrial' : 'pendingWidgetTrial', generation: `${prefix}Generation`, agentId: `${prefix}AgentId`, ownership: `${prefix}Ownership` };
}

export function ensureVisitorState(state) {
  state.ui ||= {};
  for (const surface of SURFACES) {
    const keys = fields(surface);
    state.ui[keys.input] ??= '';
    if (!Array.isArray(state.ui[keys.messages])) state.ui[keys.messages] = [];
    state.ui[keys.status] ??= 'idle';
    state.ui[keys.pending] ??= null;
    state.ui[keys.generation] ??= 1;
    state.ui[keys.agentId] ??= state.selectedAgentId || null;
    state.ui[keys.ownership] ??= 'ai';
    const pending = state.ui[keys.pending];
    if (pending && typeof pending === 'object') {
      const legacy = !pending.intent || !Array.isArray(pending.trace) || pending.surface === undefined || pending.generation === undefined;
      pending.surface ??= surface;
      pending.generation ??= state.ui[keys.generation];
      pending.page ??= state.ui.page;
      pending.intent ??= { type: 'legacy', explicitRequest: false, kind: null, query: '', terms: [] };
      if (!Array.isArray(pending.trace)) pending.trace = [];
      pending.attachments ||= [];
      pending.fileRefs ||= [];
      if (legacy && pending.recovery !== 'legacy-incomplete') {
        pending.recovery = 'legacy-incomplete';
        pending.trace.push({ stage: 'restore', status: 'blocked', detail: '旧版运行缺少冻结会话或检索证据，仅保留原问题并取消，不恢复发送。' });
      }
    }
  }
  return state;
}

export function visitorSession(state, surface = 'trial') {
  const keys = fields(surface);
  return clone({ input: state.ui?.[keys.input] ?? '', messages: state.ui?.[keys.messages] || [], status: state.ui?.[keys.status] || 'idle', pending: state.ui?.[keys.pending] || null, generation: state.ui?.[keys.generation] ?? 1, agentId: state.ui?.[keys.agentId] ?? state.selectedAgentId ?? null, ownership: state.ui?.[keys.ownership] || 'ai' });
}

function stamp(context) {
  return typeof context.now === 'function' ? context.now() : context.now || new Date().toISOString();
}

function identifyIntent(config, question) {
  const query = normalized(question);
  if (config.handoff.phrases.some(phrase => text(phrase) && query.includes(normalized(phrase)))) return { type: 'handoff', explicitRequest: false, kind: null, query: '', terms: [] };
  if (/(不要|不用|无需|不需要|别|禁止|不能|不想|没必要|不必|不是想|不是要|不).{0,6}(发|发送|给|传|看|查看|下载|图片|视频|文档|文件|海报|手册)/.test(query)) return { type: 'declined', explicitRequest: false, kind: null, query: '', terms: [] };
  const kinds = [['image', /海报|图片|照片|图册|截图|图像|宣传图/], ['video', /视频|演示片|影片|短片/], ['document', /文档|手册|说明书|pdf|文件|文献|报告|表格|ppt|指南/]].filter(([, pattern]) => pattern.test(query)).map(([kind]) => kind);
  const inquiry = /(如何|怎么|是什么|有什么|包含什么|什么内容|介绍一下|介绍下|讲解|解释|为何|为什么|多少钱)/.test(query);
  const strongRequest = !inquiry && /(请发|发给|发送|传给|索取|下载|发一|发个|发.*给)/.test(query);
  const weakRequest = !inquiry && /(请给|给我|想看看|看一下|看看|查看|想看|要)/.test(query) && (kinds.length > 0 || /资料|附件/.test(query));
  if (!strongRequest && !weakRequest) return { type: 'faq', explicitRequest: false, kind: null, query: '', terms: [] };
  const content = query.replace(/请问|能不能|能否|可以|麻烦|帮我|发给|发送|发一下|传给|给我|看一下|看看|查看|下载|索取|一份|一个|一下|有关|相关|请|把|发|给|想|我要|我|的/g, '').replace(/海报|图片|照片|图册|截图|图像|宣传图|视频|演示片|影片|短片|文档|手册|说明书|pdf|文件|文献|报告|表格|ppt|指南/g, ' ');
  const terms = content.split(/[\s和与及]+/).map(text).filter(term => term.length >= 2);
  return { type: 'material', explicitRequest: true, kind: kinds.length === 1 ? kinds[0] : null, query: terms.join(' '), terms };
}

function retrieve(state, agent, intent, date) {
  const candidates = state.materials.filter(asset => materialAllowed(asset, agent.id, date) && asset.autoSendAllowed === true && (!intent.kind || asset.kind === intent.kind)).flatMap(asset => {
    const content = normalized([asset.title, ...(asset.tags || []), asset.summary.text].join(' '));
    if (!intent.terms.every(term => content.includes(normalized(term)))) return [];
    const variant = materialPreferredVariant(asset, agent.config.materialPolicy);
    return variant ? [{ id: asset.id, revision: asset.revision, variant }] : [];
  });
  return candidates.slice(0, Math.min(5, Number(agent.config.materialPolicy.maxCount) || 1));
}

function trace(stage, status, detail, extra = {}) {
  return { stage, status, detail, ...extra };
}

function materialEvidence(pending) {
  return pending.intent.type === 'material' ? { method: 'deterministic-local-preview', explicitRequest: pending.intent.explicitRequest, kind: pending.intent.kind, trace: clone(pending.trace) } : null;
}

function runFor(state, pending, { answer = '', status = 'cancelled', sources = [], attachments = [], traces = pending.trace, messageId = null, generated = false, time } = {}) {
  const run = { id: pending.id, agentId: pending.agentId, revision: pending.revision, surface: pending.surface, messageId, createdAt: time, input: pending.question, answer, status, sources: clone(sources), attachments: clone(attachments), trace: clone(traces), materialEvidence: materialEvidence(pending), requestEvidence: { query: pending.question, explicitRequest: pending.intent.explicitRequest, origin: 'local-visitor-input', surface: pending.surface }, materialPolicy: clone(pending.config?.materialPolicy || null), localReceipt: { status: 'pending', scope: 'local-preview', time: null }, attachmentInteractions: {}, mode: 'simulation', resultEvidence: { generated, delivered: false, resolved: 'unknown', localReceived: false }, cost: null };
  state.runs ||= [];
  state.runs.unshift(run);
  return run;
}

export function cancelVisitorSession(state, surface = 'trial', context = {}) {
  ensureVisitorState(state);
  const keys = fields(surface);
  const pending = state.ui[keys.pending];
  if (pending && state.ui[keys.status] === 'running') {
    const time = stamp(context);
    pending.trace.push(trace('send', 'blocked', context.reason || '访客试用已取消；旧回调不能继续生成或发送。'));
    runFor(state, pending, { time });
    state.ui[keys.messages].push({ role: 'system', text: context.reason || '模拟答复已取消；取消不会被记为成功或已解决。', time });
  }
  state.ui[keys.generation] += 1;
  state.ui[keys.status] = 'cancelled';
  state.ui[keys.pending] = null;
}

function start(state, surface, data, context) {
  const keys = fields(surface);
  const agent = state.agents.find(item => item.id === state.selectedAgentId);
  if (!agent) throw new Error('请先选择专家');
  const readonly = typeof context.readonly === 'function' ? context.readonly() : context.readonly;
  if (readonly || state.ui.readonly || state.ui.previewVersionId) throw new Error('当前为只读预览，请返回草稿后试用');
  if (state.ui[keys.status] === 'running') throw new Error('上一条模拟答复仍在处理，可先取消');
  const question = text(data.question || state.ui[keys.input]);
  if (!question) throw new Error('请输入试用问题');
  if (question.length > 4000) throw new Error('本地试用问题请控制在 4000 字以内');
  if (state.ui[keys.agentId] !== agent.id) {
    state.ui[keys.messages] = []; state.ui[keys.generation] += 1; state.ui[keys.ownership] = 'ai'; state.ui[keys.agentId] = agent.id;
  }
  const intent = state.ui[keys.ownership] !== 'ai' ? { type: 'waiting', explicitRequest: false, kind: null, query: '', terms: [] } : identifyIntent(agent.config, question);
  if (intent.type === 'faq') {
    const ready = readiness(agent, state.connections);
    if (!ready.canTrial) throw new Error(ready.issues.join('；'));
  }
  const time = stamp(context);
  const uid = context.uid || (prefix => `${prefix}-${Date.now().toString(36)}-${++sequence}`);
  const pending = { id: uid('run'), surface, page: state.ui.page, agentId: agent.id, revision: agent.revision, config: clone(agent.config), revokedIds: clone(agent.revokedSourceIds || []), generation: state.ui[keys.generation], question, intent, attachments: [], fileRefs: [], trace: [trace('request', 'complete', intent.type === 'material' ? '已识别访客明确索取文件；使用本地确定性类型与关键词匹配。' : intent.type === 'handoff' ? '访客要求人工，优先记录本地交接。' : intent.type === 'declined' ? '访客明确拒绝索取文件，不发送附件。' : intent.type === 'waiting' ? '本地访客会话正在等待人工，不继续自动发送。' : '使用现有已审资料脚本答疑。', { intent: intent.type, kind: intent.kind, query: intent.query })] };
  if (intent.type === 'material') {
    if (agent.config.materialPolicy.enabled !== true) {
      pending.blockedReason = '自动发送策略未启用；请先到物料库配置允许发送的材料。';
      pending.trace.push(trace('policy', 'blocked', pending.blockedReason));
    } else {
      pending.attachments = retrieve(state, agent, intent, time.slice(0, 10));
      const checked = materialAssetSendCheck(state, { agentId: agent.id, attachments: pending.attachments, actor: 'agent', expectedRevision: agent.revision, explicitRequest: true, date: time.slice(0, 10) });
      if (!checked.ok) { pending.attachments = []; pending.blockedReason = '没有当前可自动发送的匹配物料，请由业务核实审阅、授权、适用范围和有效期。'; }
      pending.trace.push(trace('retrieval', checked.ok ? 'complete' : 'blocked', checked.ok ? '从已审、有效且允许自动发送的物料中匹配附件。' : pending.blockedReason, { method: 'deterministic-local-preview', matched: pending.attachments.length }));
      if (checked.ok) {
        pending.fileRefs = pending.attachments.map(selection => { const asset = state.materials.find(item => item.id === selection.id); return { id: asset.id, revision: asset.revision, blobKey: asset.original.blobKey, size: asset.original.size, filename: asset.filename }; });
        pending.trace.push(trace('policy', 'complete', '草稿策略、物料自动许可、明确请求、数量和版本偏好已通过本地预检。'));
        pending.trace.push(trace('files', 'pending', '等待实际读取本浏览器缓存原件；元数据可用不等于文件存在。'));
      }
    }
  }
  state.ui[keys.pending] = pending; state.ui[keys.status] = 'running'; state.ui[keys.input] = '';
  state.ui[keys.messages].push({ id: uid('visitor-message'), role: 'user', text: question, time, revision: agent.revision });
  return pending.id;
}

function complete(state, surface, data, context) {
  const keys = fields(surface);
  const pending = state.ui[keys.pending];
  if (!pending || state.ui[keys.status] !== 'running' || pending.id !== data.id || pending.agentId !== state.selectedAgentId || pending.generation !== state.ui[keys.generation]) return;
  if (pending.recovery === 'legacy-incomplete') { cancelVisitorSession(state, surface, { ...context, reason: '旧版试用缺少冻结证据，已取消；请重新发起试用。' }); return; }
  const agent = state.agents.find(item => item.id === pending.agentId);
  const readonly = typeof context.readonly === 'function' ? context.readonly() : context.readonly;
  if (!agent || agent.revision !== pending.revision || JSON.stringify(agent.config) !== JSON.stringify(pending.config) || state.ui.page !== pending.page || readonly || state.ui.readonly || state.ui.previewVersionId) {
    cancelVisitorSession(state, surface, { ...context, reason: '试用期间草稿或页面上下文已变化，旧答复已中止，请重新试用。' }); return;
  }
  const time = stamp(context);
  let reply;
  let attachments = [];
  if (pending.intent.type === 'material') {
    let failure = pending.blockedReason;
    if (!failure && state.ui[keys.ownership] !== 'ai') failure = '访客会话正在等待人工，不能继续自动发送。';
    const checked = failure ? null : materialAssetSendCheck(state, { agentId: agent.id, attachments: pending.attachments, actor: 'agent', explicitRequest: pending.intent.explicitRequest, expectedRevision: pending.revision, date: time.slice(0, 10) });
    if (!failure && !checked.ok) failure = '物料或自动发送授权在检索后已变化，本次未发送；请重新核实并重试。';
    if (!failure && pending.fileRefs.some(ref => {
      const asset = state.materials.find(item => item.id === ref.id);
      return !asset || asset.original.blobKey !== ref.blobKey || asset.original.size !== ref.size || asset.filename !== ref.filename;
    })) failure = '检索后原件引用已变化，本次未发送；请重新检索。';
    const proofs = Array.isArray(data.availableFiles) ? data.availableFiles : [];
    const filesMatch = pending.fileRefs.every(ref => proofs.some(file => file?.blobKey === ref.blobKey && file.size === ref.size && file.filename === ref.filename));
    if (!failure && !filesMatch) failure = '本浏览器缓存原件缺失或与冻结引用不符，本次未发送文件。';
    if (failure) {
      reply = { text: '目前无法向你发送这份资料，可以请人工帮你核实。', status: 'material_blocked', sources: [] };
      pending.trace.push(trace('send', 'blocked', failure));
    } else {
      attachments = checked.attachments;
      reply = { text: attachments.some(item => item.simulated) ? '已生成文件附件演示卡片；模拟压缩版本没有实际文件，请在物料库选择原件体验查看。' : '已为你找到资料，可打开查看或下载。', status: 'material_sent', sources: [] };
      pending.trace.push(trace('files', 'complete', '已实际读取原件缓存，文件键、大小和名称与冻结引用一致。'));
      pending.trace.push(trace('send', 'complete', '最终重验当前草稿、会话代次、物料修订和发送授权后，生成本地附件卡片。'));
    }
  } else if (pending.intent.type === 'declined') reply = { text: '好的，本次不发送文件。你可以继续咨询，或随时明确索取资料。', status: 'unknown', sources: [] };
  else if (pending.intent.type === 'waiting') reply = { text: '这次本地试用正在等待人工；重新开始会话后才会恢复 AI 接待。', status: 'handoff', sources: [] };
  else {
    reply = simulateReply(pending.config, pending.question, agent.revokedSourceIds || []);
    if (pending.intent.type === 'handoff' || reply.status === 'handoff') state.ui[keys.ownership] = 'waiting';
    if (pending.intent.type === 'faq') agent.checks.testedRevision = agent.revision;
  }
  if (!pending.trace.some(item => item.stage === 'send')) pending.trace.push(trace('send', 'complete', '已生成本地脚本回复；外部送达与业务解决没有证据。'));
  const uid = context.uid || (prefix => `${prefix}-${Date.now().toString(36)}-${++sequence}`);
  const message = { id: uid('visitor-message'), role: 'assistant', actor: 'agent', text: reply.text, sources: clone(reply.sources), time, status: reply.status, revision: pending.revision, attachments: clone(attachments), trace: clone(pending.trace), materialEvidence: materialEvidence(pending), requestEvidence: { query: pending.question, explicitRequest: pending.intent.explicitRequest, origin: 'local-visitor-input', surface }, materialPolicy: clone(pending.config.materialPolicy), mode: 'simulation', delivery: 'unknown', localReceipt: { status: 'pending', scope: 'local-preview', time: null }, attachmentInteractions: {} };
  state.ui[keys.messages].push(message);
  runFor(state, pending, { answer: reply.text, status: reply.status, sources: reply.sources, attachments, traces: pending.trace, messageId: message.id, generated: true, time });
  state.ui[keys.status] = 'complete'; state.ui[keys.pending] = null;
  return message.id;
}

function interaction(state, action, data, context) {
  const surface = data.surface || 'trial';
  const keys = fields(surface);
  const message = state.ui[keys.messages].find(item => item.id === data.messageId && item.role === 'assistant');
  const run = state.runs.find(item => item.agentId === state.selectedAgentId && item.surface === surface && (data.runId ? item.id === data.runId : message && item.messageId === message.id));
  const target = message || (run?.resultEvidence.generated && run);
  if (!target) return;
  target.localReceipt ||= { status: 'pending', scope: 'local-preview', time: null };
  target.attachmentInteractions ||= {};
  if (action === 'visitor-received') {
    if (target.localReceipt.status === 'received') return;
    target.localReceipt = { status: 'received', scope: 'local-preview', time: stamp(context) };
    if (run) { run.localReceipt = clone(target.localReceipt); run.resultEvidence.localReceived = true; }
    return;
  }
  const attachment = target.attachments.find(item => item.id === data.id && item.revision === Number(data.revision) && item.variant === data.variant);
  if (!attachment || attachment.simulated || !attachment.blobKey) return;
  const key = `${attachment.id}:${attachment.revision}:${attachment.variant}`;
  target.attachmentInteractions[key] = { ...target.attachmentInteractions[key], [action === 'visitor-opened' ? 'openedAt' : 'downloadStartedAt']: stamp(context) };
  if (run) run.attachmentInteractions = clone(target.attachmentInteractions);
}

export function handleVisitorAction(state, action, data = {}, context = {}) {
  const match = action.match(/^(trial|widget-trial)-(start|complete|cancel|clear|example|stage)$/);
  if (!match && !['visitor-received', 'visitor-opened', 'visitor-downloaded'].includes(action)) return { handled: false };
  ensureMaterialState(state); ensureVisitorState(state);
  if (!match) { interaction(state, action, data, context); return { handled: true }; }
  const surface = match[1] === 'trial' ? 'trial' : 'widget';
  const operation = match[2];
  const keys = fields(surface);
  let value;
  if (operation === 'start') value = start(state, surface, data, context);
  else if (operation === 'complete') value = complete(state, surface, data, context);
  else if (operation === 'cancel') cancelVisitorSession(state, surface, context);
  else if (operation === 'clear') {
    cancelVisitorSession(state, surface, context);
    state.ui[keys.messages] = []; state.ui[keys.input] = ''; state.ui[keys.status] = 'idle'; state.ui[keys.ownership] = 'ai'; state.ui[keys.agentId] = state.selectedAgentId;
  } else if (operation === 'stage') {
    const pending = state.ui[keys.pending];
    if (pending?.id === data.id && state.ui[keys.status] === 'running' && ['files'].includes(data.stage)) pending.trace.push(trace(data.stage, 'pending', text(data.detail) || '正在读取冻结文件引用对应的浏览器缓存原件。'));
  } else {
    const agent = state.agents.find(item => item.id === state.selectedAgentId);
    const known = agent?.config.sources.find(source => source.type === 'FAQ' && sourceValid(source, agent.revokedSourceIds || []));
    state.ui[keys.input] = text(data.question) || { image: '请发课程海报', video: '想看看介绍视频', document: '把服务手册给我', handoff: '转人工', unknown: '你们保证我的收入翻倍吗？' }[data.kind] || known?.question || '资料里介绍了什么？';
  }
  return { handled: true, value };
}
