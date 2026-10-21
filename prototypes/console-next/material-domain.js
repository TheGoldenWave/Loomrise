import { validDate } from './domain.js';

const POLICY_DEFAULTS = { enabled: false, requireExplicitRequest: true, preferredVariant: 'original', allowOriginalFallback: true, maxCount: 1 };
const UI_DEFAULTS = { query: '', kind: 'all', status: 'all', form: false, editingId: null, detailId: null, session: 0, upload: null, uploadStatus: 'idle', error: '', picker: false, pickerQuery: '', selected: [], sendContext: null, autoQuery: '', autoExplicit: true, autoResults: [], preview: null };
const WRITE_ACTIONS = new Set(['material-upsert', 'material-review-summary', 'material-publish', 'material-revoke', 'material-summary-demo', 'material-summary-fail', 'material-apply-summary', 'material-compress-demo', 'material-compress-fail', 'material-send', 'material-auto-send', 'material-load-demo']);
const ACTIONS = new Set([...WRITE_ACTIONS, 'material-list', 'material-form-toggle', 'material-edit', 'material-detail', 'material-filter', 'material-upload-ready', 'material-upload-failed', 'material-picker-open', 'material-picker-close', 'material-picker-done', 'material-pick', 'material-unpick', 'material-auto-retrieve', 'material-preview', 'material-preview-close', 'material-file-availability']);
const text = value => String(value ?? '').trim();
const yes = value => value === true || value === 'true' || value === 'on';
const today = () => new Date().toISOString().slice(0, 10);
const copy = value => JSON.parse(JSON.stringify(value));
let sequence = 0;

export function ensureMaterialState(state) {
  state.materials ||= [];
  state.ui ||= {};
  state.ui.materials = { ...copy(UI_DEFAULTS), ...state.ui.materials };
  for (const agent of state.agents || []) {
    if (agent.config) agent.config.materialPolicy = { ...POLICY_DEFAULTS, ...agent.config.materialPolicy };
  }
  for (const asset of state.materials) {
    asset.revision ??= 1;
    asset.tags ||= [];
    asset.agentIds ||= [];
    asset.scope ||= 'selected';
    asset.status ||= 'draft';
    asset.rights ??= false;
    asset.canSend ??= true;
    asset.autoSendAllowed ??= false;
    asset.original = { blobKey: null, size: null, available: false, ...asset.original };
    asset.summary = { text: '', candidate: '', reviewed: false, origin: 'manual', baseRevision: asset.revision, ...asset.summary };
    asset.processing = { compression: 'none', understanding: 'none', ...asset.processing };
    asset.variants ||= [];
    if (!asset.variants.some(item => item.id === 'original')) asset.variants.unshift(originalVariant(asset.original));
    asset.history ||= [];
  }
  return state;
}

export function materialKind(filename, mimeType) {
  const extension = text(filename).toLowerCase().split('.').at(-1);
  const mime = text(mimeType).toLowerCase().split(';')[0];
  if (['html', 'htm', 'svg', 'js', 'mjs', 'exe', 'sh'].includes(extension) || ['text/html', 'image/svg+xml', 'application/javascript'].includes(mime)) return null;
  if (/^image\/(png|jpeg|gif|webp|avif|bmp|tiff)$/.test(mime) || ['jpg', 'jpeg', 'png', 'gif', 'webp', 'avif', 'bmp', 'tif', 'tiff'].includes(extension)) return 'image';
  if (/^video\/(mp4|webm|quicktime|mpeg|x-msvideo|x-m4v)$/.test(mime) || ['mp4', 'webm', 'mov', 'm4v', 'mpeg', 'mpg', 'avi'].includes(extension)) return 'video';
  if (['pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'txt', 'md', 'csv', 'rtf', 'odt', 'ods', 'odp'].includes(extension) || ['application/pdf', 'text/plain', 'text/csv', 'text/markdown', 'application/rtf', 'application/msword', 'application/vnd.ms-excel', 'application/vnd.ms-powerpoint'].includes(mime) || /^application\/vnd\.(openxmlformats-officedocument|oasis\.opendocument)\./.test(mime)) return 'document';
  return null;
}

function authorizationIssue(asset, agentId, date) {
  if (!asset || asset.status === 'revoked') return '物料已撤回或不存在';
  if (asset.rights !== true || !text(asset.sourceRef)) return '物料缺少有效授权或来源';
  if (!validDate(asset.expires) || !validDate(date) || asset.expires < date) return '物料有效期已过或日期无效';
  if (asset.scope !== 'workspace' && !(asset.scope === 'selected' && asset.agentIds?.includes(agentId))) return '物料不在当前专家适用范围';
  return '';
}

function materialIssue(asset, agentId, date = today()) {
  const issue = authorizationIssue(asset, agentId, date);
  if (issue) return issue;
  if (asset.status !== 'published') return '物料尚未发布';
  if (asset.canSend !== true) return '物料未允许发送';
  if (!asset.summary?.reviewed || !text(asset.summary.text) || asset.summary.baseRevision !== asset.revision) return '当前物料简介尚未人工审阅';
  return '';
}

export function materialAllowed(asset, agentId, date = today()) {
  return !materialIssue(asset, agentId, date);
}

export function materialSearch(state, query, { agentId = state.selectedAgentId, forAgent = false } = {}) {
  const words = text(query).toLocaleLowerCase().split(/\s+/).filter(Boolean);
  return (state.materials || []).filter(asset => {
    if (forAgent && !materialAllowed(asset, agentId)) return false;
    const content = [asset.title, asset.filename, ...(asset.tags || []), asset.summary?.text, asset.usage].join(' ').toLocaleLowerCase();
    return words.every(word => content.includes(word));
  });
}

function originalVariant(original) {
  return { id: 'original', label: '原件', blobKey: original.blobKey, size: original.size, available: original.available, simulated: false };
}

function variantIssue(asset, variantId) {
  const variant = asset?.variants?.find(item => item.id === variantId);
  if (!variant || variant.available !== true) return '所选文件版本不可用';
  if (!asset.original?.available || !text(asset.original.blobKey)) return '原件本地缓存缺失，请重新选择文件';
  if (variantId === 'original' && (variant.simulated || variant.blobKey !== asset.original.blobKey || !text(variant.blobKey))) return '原件引用无效，请重新选择文件';
  if (variantId === 'compressed-demo' && (asset.processing?.compression !== 'mock-ready' || variant.simulated !== true || variant.blobKey !== null || variant.size !== null)) return '压缩候选尚未就绪；本轮仅能记录模拟附件';
  if (!['original', 'compressed-demo'].includes(variantId)) return '不支持所选文件版本';
  return '';
}

function attachmentSnapshot(asset, variantId) {
  const variant = asset.variants.find(item => item.id === variantId);
  return { id: asset.id, revision: asset.revision, title: asset.title, name: asset.title, kind: asset.kind, type: asset.kind, filename: asset.filename, mimeType: asset.mimeType, variant: variant.id, variantLabel: variant.label, blobKey: variant.blobKey, size: variant.size, simulated: variant.simulated === true, summary: asset.summary.text, summaryOrigin: asset.summary.origin, status: 'local-recorded', delivery: 'unknown' };
}

export function materialPreferredVariant(asset, policy) {
  let variant = policy?.preferredVariant || 'original';
  if (variantIssue(asset, variant) && variant === 'compressed-demo' && policy?.allowOriginalFallback === true) variant = 'original';
  return variantIssue(asset, variant) ? null : variant;
}

export function materialAssetSendCheck(state, { agentId, attachments = [], actor = 'agent', explicitRequest, expectedRevision, date = today() } = {}) {
  const fail = message => ({ ok: false, message });
  const agent = state.agents?.find(item => item.id === agentId);
  if (!agent) return fail('专家已不存在');
  if (!['human', 'agent'].includes(actor)) return fail('发送者类型无效');
  if (expectedRevision !== undefined && Number(expectedRevision) !== agent.revision) return fail('当前草稿策略修订已变化，请重新准备发送');
  if (!Array.isArray(attachments)) return fail('附件选择格式无效');
  if (attachments.some(item => !item || typeof item !== 'object' || !text(item.id))) return fail('附件选择格式无效');
  if (new Set(attachments.map(item => item.id)).size !== attachments.length) return fail('同一物料不能在一条消息中重复发送');
  const policy = { ...POLICY_DEFAULTS, ...agent.config.materialPolicy };
  if (actor === 'agent') {
    if (policy.enabled !== true) return fail('Agent 自动发物料策略尚未启用');
    if (expectedRevision === undefined || Number(expectedRevision) !== agent.revision) return fail('缺少当前草稿策略修订，请重新检索');
    if (policy.requireExplicitRequest !== false && !yes(explicitRequest)) return fail('当前策略要求访客明确请求物料');
    if (!Number.isInteger(Number(policy.maxCount)) || Number(policy.maxCount) < 1 || Number(policy.maxCount) > 5 || attachments.length > Number(policy.maxCount)) return fail('物料数量超过当前策略限制或策略数量无效');
    if (!attachments.length) return fail('没有匹配到允许自动发送的物料');
  }
  const snapshots = [];
  for (const selection of attachments) {
    const asset = state.materials?.find(item => item.id === selection.id);
    if (!asset || Number(selection.revision) !== asset.revision) return fail('所选物料修订已变化或不存在，请重新选择');
    const issue = materialIssue(asset, agentId, date) || variantIssue(asset, selection.variant);
    if (issue) return fail(issue);
    if (actor === 'agent' && asset.autoSendAllowed !== true) return fail('该物料未授权 Agent 自动发送');
    if (actor === 'agent' && selection.variant !== policy.preferredVariant && !(selection.variant === 'original' && policy.preferredVariant === 'compressed-demo' && policy.allowOriginalFallback === true && variantIssue(asset, 'compressed-demo'))) return fail('所选文件版本不符合当前自动发送策略');
    snapshots.push(attachmentSnapshot(asset, selection.variant));
  }
  return { ok: true, attachments: snapshots, agent };
}

export function materialSendCheck(state, { agentId, conversationId, generation, attachments = [], actor = 'human', explicitRequest, expectedRevision } = {}) {
  const fail = message => ({ ok: false, message });
  if (state.ui?.readonly || state.ui?.previewVersionId) return fail('当前为只读预览，不能发送物料');
  if (!['human', 'agent'].includes(actor)) return fail('发送者类型无效');
  if (!agentId || !conversationId || generation === undefined || generation === null) return fail('缺少冻结的专家、会话或占用代次');
  if (agentId !== state.selectedAgentId || conversationId !== state.ui?.activeConversation) return fail('专家或会话已切换，请重新准备发送');
  const agent = state.agents.find(item => item.id === agentId);
  const conversation = agent?.conversations.find(item => item.id === conversationId);
  if (!conversation || Number(generation) !== conversation.generation) return fail('会话占用代次已失效，请重新准备发送');
  if ((conversation.ownership || conversation.status) !== (actor === 'human' ? 'human' : 'ai')) return fail(actor === 'human' ? '先明确承接当前会话再发送' : '当前会话不由 AI 接待，不能自动发送');
  if (expectedRevision !== undefined && Number(expectedRevision) !== agent.revision) return fail('当前草稿策略修订已变化，请重新准备发送');
  if (!Array.isArray(attachments)) return fail('附件选择格式无效');
  if (attachments.some(item => !item || typeof item !== 'object' || !text(item.id))) return fail('附件选择格式无效');
  const selectionContext = state.ui?.materials?.sendContext;
  if (actor === 'human' && state.ui?.materials?.selected?.length && selectionContext && (selectionContext.agentId !== agentId || selectionContext.conversationId !== conversationId || selectionContext.generation !== Number(generation))) return fail('附件选择时的占用代次已失效，请重新选择物料');
  const checked = materialAssetSendCheck(state, { agentId, attachments, actor, explicitRequest, expectedRevision });
  return checked.ok ? { ...checked, conversation } : checked;
}

function agentIds(value, fallback) {
  if (value === undefined) return fallback;
  if (typeof value === 'string') {
    try { value = JSON.parse(value); } catch { value = value.split(/[,，]/); }
  }
  if (!Array.isArray(value)) throw new Error('专家适用范围格式无效');
  return [...new Set(value.map(text).filter(Boolean))];
}

function touch(asset, action, stamp, preserveReview = true) {
  const reviewed = preserveReview && asset.summary.reviewed && asset.summary.baseRevision === asset.revision;
  asset.revision += 1;
  asset.summary.baseRevision = asset.revision;
  asset.summary.reviewed = reviewed;
  if (asset.summary.candidate) asset.summary.candidateBaseRevision = null;
  asset.history.unshift({ action, revision: asset.revision, time: stamp });
  asset.history = asset.history.slice(0, 100);
}

function checkedContext(state, agent) {
  const conversation = agent?.conversations?.find(item => item.id === state.ui.activeConversation);
  if (!agent || agent.id !== state.selectedAgentId || !conversation) throw new Error('请先选择当前专家的会话');
  return { agentId: agent.id, conversationId: conversation.id, generation: conversation.generation };
}

function automaticResults(state, query, agent) {
  const policy = agent.config.materialPolicy;
  return materialSearch(state, query, { agentId: agent.id, forAgent: true }).filter(asset => asset.autoSendAllowed === true).flatMap(asset => {
    let variant = policy.preferredVariant;
    if (variantIssue(asset, variant) && variant === 'compressed-demo' && policy.allowOriginalFallback === true) variant = 'original';
    if (variantIssue(asset, variant)) return [];
    return [{ id: asset.id, revision: asset.revision, variant, title: asset.title, summary: asset.summary.text }];
  });
}

export function handleMaterialAction(state, action, data = {}, context = {}) {
  if (!ACTIONS.has(action)) return { handled: false };
  const readonly = typeof context.readonly === 'function' ? context.readonly() : context.readonly;
  if (WRITE_ACTIONS.has(action) && (readonly || state.ui?.readonly || state.ui?.previewVersionId)) throw new Error('当前为只读预览，返回草稿后再修改或发送物料');
  ensureMaterialState(state);
  const ui = state.ui.materials;
  const agent = context.agent || state.agents?.find(item => item.id === state.selectedAgentId);
  const uid = context.uid || (prefix => `${prefix}-${Date.now().toString(36)}-${++sequence}`);
  const stamp = typeof context.now === 'function' ? context.now() : context.now || new Date().toISOString();
  const find = () => {
    const asset = state.materials.find(item => item.id === data.id);
    if (!asset) throw new Error('物料已不存在');
    return asset;
  };
  const editable = () => {
    const asset = find();
    if (asset.status === 'revoked') throw new Error('物料已撤回，请重新登记并确认授权');
    if (data.expectedRevision !== undefined && Number(data.expectedRevision) !== asset.revision) throw new Error('物料修订已变化，请重新操作');
    return asset;
  };
  let value;
  switch (action) {
    case 'material-form-toggle':
      if (!ui.form) ui.detailId = null;
      ui.form = !ui.form; ui.editingId = null; ui.upload = null; ui.uploadStatus = 'idle'; ui.error = ''; ui.session += 1; break;
    case 'material-edit':
      editable(); ui.detailId = data.id; ui.editingId = data.id; ui.form = true; ui.upload = null; ui.uploadStatus = 'idle'; ui.error = ''; ui.session += 1; break;
    case 'material-list':
      if (data.reset === true || data.reset === 'true') { ui.query = ''; ui.kind = 'all'; ui.status = 'all'; }
      ui.detailId = null; ui.form = false; ui.editingId = null; ui.upload = null; ui.uploadStatus = 'idle'; ui.error = ''; ui.session += 1; break;
    case 'material-detail':
      find(); ui.detailId = ui.detailId === data.id ? null : data.id; ui.form = false; ui.editingId = null; ui.upload = null; ui.uploadStatus = 'idle'; ui.error = ''; ui.session += 1; break;
    case 'material-filter':
      if (!['query', 'kind', 'status', 'pickerQuery', 'autoQuery'].includes(data.path)) throw new Error('不支持此物料筛选字段');
      ui[data.path] = text(data.value); break;
    case 'material-upload-ready': {
      if (Number(data.session) !== ui.session || !ui.form) break;
      const meta = data.meta;
      const kind = materialKind(meta?.filename, meta?.mimeType);
      if (!kind || !text(meta?.blobKey) || !Number.isFinite(meta?.size) || meta.size < 0 || meta?.available !== true) throw new Error('文件元数据无效，请重新选择支持的图片、视频或文档');
      ui.upload = { blobKey: meta.blobKey, filename: meta.filename, mimeType: meta.mimeType, size: meta.size, kind, available: true }; ui.uploadStatus = 'ready'; ui.error = ''; break;
    }
    case 'material-upload-failed':
      if (Number(data.session) !== ui.session || !ui.form) break;
      ui.uploadStatus = 'failed'; ui.error = text(data.error) || '文件读取失败，原有内容已保留'; break;
    case 'material-upsert': {
      const previous = data.id ? editable() : null;
      const upload = ui.upload;
      if (!previous && !upload) throw new Error('请先选择物料原文件');
      const title = text(data.title || upload?.filename || previous?.title);
      if (!title || title.length > 120) throw new Error('物料名称需为 1–120 个字符');
      const scope = data.scope || previous?.scope || 'selected';
      if (!['selected', 'workspace'].includes(scope)) throw new Error('物料适用范围无效');
      const ids = agentIds(data.agentIds, previous?.agentIds || (agent ? [agent.id] : []));
      if (scope === 'selected' && (!ids.length || ids.some(id => !state.agents.some(item => item.id === id)))) throw new Error('请至少选择一个现有专家的适用范围');
      const description = text(data.description ?? previous?.summary.text);
      if (description.length > 5000) throw new Error('物料简介请控制在 5000 字以内');
      const revision = (previous?.revision || 0) + 1;
      const original = upload ? { blobKey: upload.blobKey, size: upload.size, available: upload.available } : copy(previous.original);
      const asset = { id: previous?.id || uid('material'), revision, title, kind: upload?.kind || previous.kind, filename: upload?.filename || previous.filename, mimeType: upload?.mimeType || previous.mimeType, sourceRef: text(data.sourceRef ?? previous?.sourceRef), rights: yes(data.rights), expires: text(data.expires ?? previous?.expires), tags: Array.isArray(data.tags) ? data.tags.map(text).filter(Boolean) : text(data.tags).split(/[,，]/).map(text).filter(Boolean), usage: text(data.usage), scope, agentIds: ids, canSend: data.canSend === undefined ? true : yes(data.canSend), autoSendAllowed: yes(data.autoSendAllowed), status: 'draft', original, summary: { text: description, candidate: '', reviewed: false, origin: 'manual', baseRevision: revision }, processing: upload ? { compression: 'none', understanding: 'none' } : copy(previous.processing), variants: upload ? [originalVariant(original)] : copy(previous.variants), history: [{ action: previous ? 'updated' : 'created', revision, time: stamp }, ...(previous?.history || [])].slice(0, 100), fictional: previous?.fictional || false };
      if (previous) Object.assign(previous, asset); else state.materials.push(asset);
      ui.form = false; ui.editingId = null; ui.upload = null; ui.uploadStatus = 'idle'; ui.error = ''; ui.session += 1; ui.detailId = asset.id; value = asset.id; break;
    }
    case 'material-review-summary': {
      const asset = editable();
      if (!text(asset.summary.text)) throw new Error('请先填写或采用物料简介，再人工审阅');
      touch(asset, 'summary-reviewed', stamp, false); asset.summary.reviewed = true; value = asset.id; break;
    }
    case 'material-publish': {
      const asset = editable();
      if (!['selected', 'workspace'].includes(asset.scope) || (asset.scope === 'selected' && (!asset.agentIds.length || asset.agentIds.some(id => !state.agents.some(item => item.id === id))))) throw new Error('请确认物料的专家适用范围');
      const issue = authorizationIssue(asset, asset.scope === 'selected' ? asset.agentIds[0] : agent?.id, stamp.slice(0, 10));
      if (issue || !asset.summary.reviewed || !text(asset.summary.text) || asset.summary.baseRevision !== asset.revision || !asset.original.available || !text(asset.original.blobKey)) throw new Error(issue || '先确认原件可用并人工审阅当前简介');
      touch(asset, 'published', stamp); asset.status = 'published'; value = asset.id; break;
    }
    case 'material-revoke': {
      const asset = find();
      if (asset.status !== 'revoked') { touch(asset, 'revoked', stamp, false); asset.status = 'revoked'; }
      value = asset.id; break;
    }
    case 'material-summary-demo': {
      const asset = editable(); touch(asset, 'summary-candidate-simulation', stamp, false);
      asset.summary.candidate = `元数据模拟候选：“${asset.filename}”，${asset.kind === 'image' ? '图片' : asset.kind === 'video' ? '视频' : '文档'}物料${asset.tags.length ? `；标签：${asset.tags.join('、')}` : ''}。尚未读取或理解文件内容，请人工核实。`;
      asset.summary.candidateBaseRevision = asset.revision; asset.processing.understanding = 'candidate'; value = asset.id; break;
    }
    case 'material-apply-summary': {
      const asset = editable();
      const baseRevision = Object.hasOwn(asset.summary, 'candidateBaseRevision') ? asset.summary.candidateBaseRevision : asset.summary.baseRevision;
      if (!asset.summary.candidate || asset.processing.understanding !== 'candidate' || baseRevision !== asset.revision) throw new Error('简介候选已失效，请重新生成');
      const candidate = asset.summary.candidate; touch(asset, 'summary-candidate-applied', stamp, false);
      asset.summary.text = candidate; asset.summary.candidate = ''; asset.summary.candidateBaseRevision = null; asset.summary.origin = 'simulation'; value = asset.id; break;
    }
    case 'material-summary-fail': {
      const asset = editable(); touch(asset, 'summary-simulation-failed', stamp);
      asset.processing.understanding = 'failed'; asset.summary.candidate = ''; asset.summary.candidateBaseRevision = null; value = asset.id; break;
    }
    case 'material-compress-demo': {
      const asset = editable();
      if (!['image', 'video'].includes(asset.kind)) throw new Error('本轮仅提供图片与视频压缩状态模拟');
      if (!asset.original.available || !text(asset.original.blobKey)) throw new Error('请先选择可用原件');
      touch(asset, 'compression-simulation', stamp); asset.processing.compression = 'mock-ready';
      asset.variants = asset.variants.filter(item => item.id !== 'compressed-demo');
      asset.variants.push({ id: 'compressed-demo', label: '压缩候选（模拟，无实际文件）', blobKey: null, size: null, available: true, simulated: true }); value = asset.id; break;
    }
    case 'material-compress-fail': {
      const asset = editable(); touch(asset, 'compression-simulation-failed', stamp); asset.processing.compression = 'failed';
      for (const variant of asset.variants.filter(item => item.id === 'compressed-demo')) variant.available = false;
      value = asset.id; break;
    }
    case 'material-file-availability': {
      const asset = find(); asset.original.available = yes(data.available) && Boolean(text(asset.original.blobKey));
      for (const variant of asset.variants.filter(item => item.id === 'original')) variant.available = asset.original.available;
      break;
    }
    case 'material-picker-open':
      ui.sendContext = checkedContext(state, agent); ui.picker = true; ui.selected = []; ui.pickerQuery = ''; break;
    case 'material-picker-close': ui.picker = false; ui.selected = []; ui.sendContext = null; break;
    case 'material-picker-done': ui.picker = false; break;
    case 'material-pick': {
      const frozen = ui.sendContext;
      const current = checkedContext(state, agent);
      if (!frozen || ['agentId', 'conversationId', 'generation'].some(key => frozen[key] !== current[key])) throw new Error('物料选择上下文已变化，请重新打开选择器');
      const asset = find(); const variant = data.variant || 'original';
      const issue = materialIssue(asset, agent.id, stamp.slice(0, 10)) || variantIssue(asset, variant);
      if (issue) throw new Error(issue);
      ui.selected = ui.selected.filter(item => item.id !== asset.id);
      ui.selected.push({ id: asset.id, revision: asset.revision, variant }); break;
    }
    case 'material-unpick': ui.selected = ui.selected.filter(item => item.id !== data.id || (data.variant && item.variant !== data.variant)); break;
    case 'material-auto-retrieve':
      if (!agent) throw new Error('请先选择专家');
      ui.autoQuery = text(data.query ?? ui.autoQuery); ui.autoResults = automaticResults(state, ui.autoQuery, agent); value = copy(ui.autoResults); break;
    case 'material-send':
    case 'material-auto-send': {
      const actor = action === 'material-auto-send' ? 'agent' : data.actor || 'human';
      let attachments = data.attachments ?? ui.selected;
      if (actor === 'agent' && data.attachments === undefined) {
        if (!agent) throw new Error('请先选择专家');
        const results = automaticResults(state, text(data.query ?? ui.autoQuery), agent);
        attachments = results.slice(0, Number(agent.config.materialPolicy.maxCount));
      }
      const result = materialSendCheck(state, { ...data, actor, attachments, expectedRevision: data.expectedRevision ?? data.revision });
      if (!result.ok) throw new Error(result.message);
      const message = text(data.message);
      if (!message && !result.attachments.length) throw new Error('请填写回复或选择物料附件');
      const record = { id: uid('message'), role: actor === 'agent' ? 'assistant' : 'human', actor, text: message, time: stamp, createdAt: stamp, generation: result.conversation.generation, agentRevision: result.agent.revision, attachments: result.attachments, status: 'local-recorded', delivery: 'unknown', mode: 'simulation', policyScope: actor === 'agent' ? 'current-draft-isolated-simulation' : 'local-human-record' };
      if (actor === 'agent') {
        record.requestEvidence = { query: text(data.query ?? ui.autoQuery), explicitRequest: yes(data.explicitRequest), origin: 'operator-simulated-request' };
        record.materialPolicy = copy(result.agent.config.materialPolicy);
      }
      result.conversation.messages.push(record); result.conversation.unread = 0;
      if (ui.sendContext && ['agentId', 'conversationId', 'generation'].every(key => ui.sendContext[key] === data[key] || (key === 'generation' && ui.sendContext[key] === Number(data[key])))) {
        ui.selected = []; ui.picker = false; ui.sendContext = null;
      }
      value = record.id; break;
    }
    case 'material-preview': {
      const asset = find(); const variant = data.variant || 'original'; const issue = variantIssue(asset, variant);
      if (issue) throw new Error(issue);
      ui.preview = { id: asset.id, revision: asset.revision, variant, blobKey: asset.variants.find(item => item.id === variant).blobKey }; break;
    }
    case 'material-preview-close': ui.preview = null; break;
    case 'material-load-demo': {
      if (state.materials.some(item => item.id === 'material-demo-image')) break;
      for (const [kind, filename, mimeType, title] of [['image', 'fictional-course.png', 'image/png', '虚构课程图'], ['video', 'fictional-tour.mp4', 'video/mp4', '虚构介绍视频'], ['document', 'fictional-guide.pdf', 'application/pdf', '虚构资料手册']]) {
        state.materials.push({ id: `material-demo-${kind}`, revision: 1, title, kind, filename, mimeType, sourceRef: 'fictional:material-demo', rights: false, expires: '', tags: ['虚构演示'], usage: '仅展示元数据，请自行上传授权原件', scope: 'selected', agentIds: agent ? [agent.id] : [], canSend: false, autoSendAllowed: false, status: 'draft', original: { blobKey: null, size: null, available: false }, summary: { text: '虚构元数据示例，未读取文件内容。', candidate: '', reviewed: false, origin: 'simulation', baseRevision: 1 }, processing: { compression: 'none', understanding: 'none' }, variants: [originalVariant({ blobKey: null, size: null, available: false })], history: [], fictional: true });
      }
      break;
    }
  }
  if (WRITE_ACTIONS.has(action) && !['material-send', 'material-auto-send'].includes(action) || action === 'material-file-availability') ui.autoResults = [];
  return value === undefined ? { handled: true } : { handled: true, value };
}
