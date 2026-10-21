import test from 'node:test';
import assert from 'node:assert/strict';
import { initialState } from '../fixtures.js';
import {
  ensureMaterialState,
  handleMaterialAction,
  materialAllowed,
  materialKind,
  materialSearch,
  materialSendCheck,
} from '../material-domain.js';

const NOW = '2026-10-14T00:00:00.000Z';
const TODAY = NOW.slice(0, 10);
const copy = value => JSON.parse(JSON.stringify(value));

function setup(status = 'human') {
  const state = initialState();
  ensureMaterialState(state);
  const agent = state.agents[0];
  const conversation = agent.conversations[0];
  conversation.status = status;
  let sequence = 0;
  const context = {
    agent,
    readonly: false,
    uid: prefix => `${prefix || 'test'}-${++sequence}`,
    now: () => NOW,
    changed: () => {},
  };
  const act = (action, data = {}, overrides = {}) => handleMaterialAction(state, action, data, { ...context, ...overrides });
  return { state, agent, conversation, act };
}

function asset(agentId, overrides = {}) {
  return {
    id: 'material-image', revision: 3, title: '课程介绍图片', kind: 'image',
    filename: 'course.png', mimeType: 'image/png', sourceRef: 'fictional:course-image',
    rights: true, expires: '2099-12-31', tags: ['课表', '入门'], usage: '用户询问课程安排时使用',
    scope: 'selected', agentIds: [agentId], canSend: true, autoSendAllowed: true, status: 'published',
    original: { blobKey: 'blob-course-original', size: 2048, available: true },
    summary: { text: '虚构课程的时间安排图。', candidate: '', reviewed: true, origin: 'manual', baseRevision: 3 },
    processing: { compression: 'none', understanding: 'none' },
    variants: [{ id: 'original', label: '原件', blobKey: 'blob-course-original', size: 2048, available: true, simulated: false }],
    history: [], fictional: true, ...overrides,
  };
}

test('物料详情、编辑和录入互斥，返回不丢筛选且旧上传不能回写', () => {
  const { state, agent, act } = setup();
  const item = asset(agent.id); state.materials.push(item);
  act('material-filter', { path: 'query', value: '课程' });
  act('material-filter', { path: 'kind', value: 'image' });
  act('material-edit', { id: item.id });
  assert.equal(state.ui.materials.detailId, item.id);
  assert.equal(state.ui.materials.form, true);
  act('material-form-toggle');
  assert.equal(state.ui.materials.form, false);
  assert.equal(state.ui.materials.detailId, item.id);
  act('material-form-toggle');
  assert.equal(state.ui.materials.detailId, null);
  const session = state.ui.materials.session;
  act('material-list');
  assert.equal(state.ui.materials.form, false);
  assert.equal(state.ui.materials.editingId, null);
  assert.equal(state.ui.materials.query, '课程');
  assert.equal(state.ui.materials.kind, 'image');
  act('material-upload-ready', { session, meta: { blobKey: 'late', filename: 'late.png', mimeType: 'image/png', size: 10, available: true } });
  assert.equal(state.ui.materials.upload, null);
  act('material-detail', { id: item.id });
  assert.equal(state.ui.materials.detailId, item.id);
  assert.equal(state.ui.materials.form, false);
});
test('物料撤回或缓存证明变化使旧检索结果失效，清空筛选同时重置类型状态', () => {
  const { state, agent, act } = setup(); const item = asset(agent.id); state.materials.push(item);
  act('material-auto-retrieve', { query: '课程' });
  assert.ok(state.ui.materials.autoResults.length > 0);
  act('material-file-availability', { id: item.id, available: false });
  assert.deepEqual(state.ui.materials.autoResults, []);
  state.ui.materials.autoResults = [{ id: item.id }];
  act('material-revoke', { id: item.id });
  assert.deepEqual(state.ui.materials.autoResults, []);
  Object.assign(state.ui.materials, { query: '课程', kind: 'image', status: 'published' });
  act('material-list', { reset: 'true' });
  assert.equal(state.ui.materials.query, ''); assert.equal(state.ui.materials.kind, 'all'); assert.equal(state.ui.materials.status, 'all');
});

function sendArgs(state, material, overrides = {}) {
  const agent = state.agents.find(item => item.id === state.selectedAgentId);
  const conversation = agent.conversations.find(item => item.id === state.ui.activeConversation);
  return {
    agentId: agent.id, conversationId: conversation.id, generation: conversation.generation,
    attachments: [{ id: material.id, revision: material.revision, variant: 'original' }],
    actor: 'human', explicitRequest: true, expectedRevision: agent.revision, ...overrides,
  };
}

function rejected(result, label) {
  assert.equal(result.ok, false, label);
  assert.equal(typeof result.message, 'string', label);
  assert.ok(result.message.length > 0, label);
}

function select(env, material, variant = 'original') {
  env.act('material-picker-open');
  env.act('material-pick', { id: material.id, variant });
  assert.deepEqual(env.state.ui.materials.selected, [{ id: material.id, revision: material.revision, variant }]);
}

test('旧 schema 1 补齐独立物料状态，保留资料、会话和已有策略', () => {
  const state = initialState();
  delete state.materials;
  delete state.ui.materials;
  for (const agent of state.agents) delete agent.config.materialPolicy;
  const sources = copy(state.agents[0].config.sources);
  const messages = copy(state.agents[0].conversations[0].messages);
  ensureMaterialState(state);
  assert.equal(state.schema, 1);
  assert.deepEqual(state.materials, []);
  assert.deepEqual(state.agents[0].config.sources, sources);
  assert.deepEqual(state.agents[0].conversations[0].messages, messages);
  assert.deepEqual(state.agents[0].config.materialPolicy, {
    enabled: false, requireExplicitRequest: true, preferredVariant: 'original', allowOriginalFallback: true, maxCount: 1,
  });
  assert.deepEqual(state.ui.materials.selected, []);
  assert.equal(state.ui.materials.upload, null);
  state.materials.push(asset(state.selectedAgentId));
  state.ui.materials.query = '保留检索';
  state.agents[0].config.materialPolicy.enabled = true;
  const restored = copy(state);
  ensureMaterialState(state);
  assert.deepEqual(state, restored);
});

test('识别图片、视频和常见文档，拒绝可执行网页与不支持文件', () => {
  for (const [filename, mimeType, expected] of [
    ['photo.PNG', 'image/png', 'image'], ['photo.jpg', '', 'image'],
    ['clip.mp4', 'video/mp4', 'video'], ['clip.webm', '', 'video'],
    ['guide.pdf', 'application/pdf', 'document'], ['guide.docx', '', 'document'],
    ['table.xlsx', '', 'document'], ['notes.txt', 'text/plain', 'document'],
    ['page.html', 'text/html', null], ['drawing.svg', 'image/svg+xml', null],
    ['program.exe', 'application/octet-stream', null], ['archive.zip', '', null],
  ]) assert.equal(materialKind(filename, mimeType), expected, filename);
});

test('Agent 物料可用性重验发布、授权、有效期、范围和当前简介审阅', () => {
  const item = asset('course-demo');
  assert.equal(materialAllowed(item, 'course-demo', TODAY), true);
  assert.equal(materialAllowed({ ...item, scope: 'workspace', agentIds: [] }, 'other-agent', TODAY), true);
  for (const [label, change] of [
    ['草稿', { status: 'draft' }], ['撤回', { status: 'revoked' }], ['无授权', { rights: false }],
    ['无来源', { sourceRef: '' }], ['过期', { expires: '2000-01-01' }],
    ['伪造日期', { expires: '2099-02-30' }], ['缺有效期', { expires: '' }],
    ['不允许发送', { canSend: false }], ['专家范围不匹配', { agentIds: ['other-agent'] }],
    ['未审简介', { summary: { ...item.summary, reviewed: false } }],
    ['简介审阅属于旧修订', { summary: { ...item.summary, baseRevision: 2 } }],
  ]) assert.equal(materialAllowed({ ...item, ...change }, 'course-demo', TODAY), false, label);
});

test('人工可搜索草稿及元数据，Agent 检索只返回当前允许的物料', () => {
  const { state, agent } = setup();
  const valid = asset(agent.id, { autoSendAllowed: false });
  const draft = asset(agent.id, { id: 'draft', status: 'draft', title: '草稿图片' });
  const revoked = asset(agent.id, { id: 'revoked', status: 'revoked' });
  const unreviewed = asset(agent.id, { id: 'unreviewed', summary: { ...valid.summary, reviewed: false } });
  const wrongScope = asset(agent.id, { id: 'wrong-scope', agentIds: ['another-agent'] });
  state.materials.push(valid, draft, revoked, unreviewed, wrongScope);
  assert.ok(materialSearch(state, '草稿', { agentId: agent.id }).some(item => item.id === draft.id));
  for (const term of ['课程介绍', 'course.png', '课表', '时间安排图', '课程安排']) {
    assert.ok(materialSearch(state, term, { agentId: agent.id }).some(item => item.id === valid.id), term);
  }
  assert.deepEqual(materialSearch(state, '', { agentId: agent.id, forAgent: true }).map(item => item.id), [valid.id]);
  assert.deepEqual(materialSearch(state, '没有匹配的内容', { agentId: agent.id, forAgent: true }), []);
});

test('上传代次失效忽略，保存原件元数据与人工简介后仍需审阅发布', () => {
  const { state, agent, act } = setup();
  const sources = copy(agent.config.sources);
  const secondAgent = { ...copy(agent), id: 'second-agent' };
  state.agents.push(secondAgent);
  act('material-form-toggle');
  const session = state.ui.materials.session;
  const meta = { blobKey: 'blob-uploaded', filename: 'uploaded.pdf', mimeType: 'application/pdf', size: 4096, kind: 'document', available: true };
  act('material-upload-ready', { meta, session: session - 1 });
  assert.equal(state.ui.materials.upload, null);
  act('material-upload-failed', { error: '过时错误', session: session - 1 });
  assert.equal(state.ui.materials.error, '');
  act('material-upload-ready', { meta, session });
  assert.deepEqual(state.ui.materials.upload, meta);
  act('material-upsert', { title: '上传文档', description: '已核实的说明', tags: '课程,说明', usage: '课程咨询', sourceRef: 'fictional:uploaded', rights: true, expires: '2099-12-31', scope: 'selected', agentIds: [secondAgent.id], canSend: true, autoSendAllowed: true });
  assert.equal(state.materials.length, 1);
  const saved = state.materials[0];
  assert.equal(saved.kind, 'document');
  assert.deepEqual(saved.original, { blobKey: meta.blobKey, size: meta.size, available: true });
  assert.equal(saved.summary.text, '已核实的说明');
  assert.equal(saved.summary.reviewed, false);
  assert.deepEqual(saved.tags, ['课程', '说明']);
  assert.deepEqual(saved.agentIds, [secondAgent.id]);
  assert.equal(saved.status, 'draft');
  assert.throws(() => act('material-publish', { id: saved.id }), Error);
  act('material-review-summary', { id: saved.id });
  act('material-publish', { id: saved.id });
  assert.equal(state.selectedAgentId, agent.id);
  assert.equal(materialAllowed(saved, secondAgent.id, TODAY), true);
  assert.equal(materialAllowed(saved, agent.id, TODAY), false);
  assert.deepEqual(agent.config.sources, sources);
});

test('压缩和简介只生成模拟候选，失败保留原件，人工审阅后 Agent 才能召回', () => {
  const { state, agent, act } = setup();
  const item = asset(agent.id);
  state.materials.push(item);
  const original = copy(item.original);
  act('material-compress-demo', { id: item.id });
  const compressed = item.variants.find(variant => variant.id === 'compressed-demo');
  assert.ok(compressed);
  assert.equal(compressed.simulated, true);
  assert.equal(compressed.blobKey, null);
  assert.equal(compressed.size, null);
  assert.deepEqual(item.original, original);
  act('material-compress-fail', { id: item.id });
  assert.equal(item.processing.compression, 'failed');
  assert.deepEqual(item.original, original);
  assert.ok(item.variants.some(variant => variant.id === 'original' && variant.blobKey === original.blobKey));
  act('material-summary-demo', { id: item.id });
  assert.equal(item.summary.reviewed, false);
  assert.ok(item.summary.candidate.length > 0);
  assert.deepEqual(materialSearch(state, '', { agentId: agent.id, forAgent: true }), []);
  const candidateBaseRevision = item.summary.candidateBaseRevision;
  const textBeforeApplying = item.summary.text;
  act('material-compress-demo', { id: item.id });
  assert.ok(item.revision > candidateBaseRevision);
  assert.throws(() => act('material-apply-summary', { id: item.id }), Error);
  assert.equal(item.summary.text, textBeforeApplying);
  act('material-summary-demo', { id: item.id });
  const currentCandidate = item.summary.candidate;
  act('material-apply-summary', { id: item.id });
  assert.equal(item.summary.text, currentCandidate);
  assert.equal(item.summary.reviewed, false);
  assert.deepEqual(materialSearch(state, '', { agentId: agent.id, forAgent: true }), []);
  act('material-review-summary', { id: item.id });
  if (item.status !== 'published') act('material-publish', { id: item.id });
  assert.equal(materialAllowed(item, agent.id, TODAY), true);
  act('material-summary-fail', { id: item.id });
  assert.equal(item.processing.understanding, 'failed');
  assert.deepEqual(item.original, original);
});

test('选择器冻结会话代次并按物料修订记录选择，关闭后清理当前选择', () => {
  const env = setup();
  const item = asset(env.agent.id);
  env.state.materials.push(item);
  select(env, item);
  assert.equal(env.state.ui.materials.picker, true);
  assert.deepEqual(env.state.ui.materials.sendContext, { agentId: env.agent.id, conversationId: env.conversation.id, generation: env.conversation.generation });
  env.act('material-unpick', { id: item.id, variant: 'original' });
  assert.deepEqual(env.state.ui.materials.selected, []);
  env.act('material-pick', { id: item.id, variant: 'original' });
  const selected = copy(env.state.ui.materials.selected);
  const sendContext = copy(env.state.ui.materials.sendContext);
  env.act('material-picker-done');
  assert.equal(env.state.ui.materials.picker, false);
  assert.deepEqual(env.state.ui.materials.selected, selected);
  assert.deepEqual(env.state.ui.materials.sendContext, sendContext);
  env.act('material-picker-open');
  assert.equal(env.state.ui.materials.picker, true);
  env.act('material-pick', { id: item.id, variant: 'original' });
  env.act('material-picker-close');
  assert.equal(env.state.ui.materials.picker, false);
  assert.deepEqual(env.state.ui.materials.selected, []);
});

test('人工纯附件发送检查不改状态，实际发送只记录本地快照和未知送达', () => {
  const env = setup();
  const item = asset(env.agent.id);
  env.state.materials.push(item);
  select(env, item);
  const before = copy(env.state);
  const args = sendArgs(env.state, item);
  const check = materialSendCheck(env.state, args);
  assert.equal(check.ok, true);
  assert.deepEqual(env.state, before);
  assert.equal(check.agent.id, env.agent.id);
  assert.equal(check.conversation.id, env.conversation.id);
  assert.equal(check.attachments.length, 1);
  env.act('material-send', { ...args, message: '' });
  const message = env.conversation.messages.at(-1);
  assert.equal(message.status, 'local-recorded');
  assert.equal(message.delivery, 'unknown');
  assert.equal(message.actor, 'human');
  assert.equal(message.generation, args.generation);
  assert.equal(env.conversation.requestStatus, before.agents[0].conversations[0].requestStatus);
  assert.deepEqual(env.state.ui.materials.selected, []);
  const snapshot = copy(message.attachments[0]);
  assert.equal(snapshot.name, item.title);
  assert.equal(snapshot.kind || snapshot.type, item.kind);
  assert.equal(snapshot.mimeType, item.mimeType);
  assert.equal(snapshot.revision, item.revision);
  assert.equal(snapshot.variant, 'original');
  assert.equal(typeof snapshot.summary === 'string' ? snapshot.summary : snapshot.summary.text, item.summary.text);
  item.title = '后续修改名称';
  item.summary.text = '后续修改说明';
  item.revision += 1;
  assert.deepEqual(message.attachments[0], snapshot);
});

test('选中后撤回、过期或修改修订会阻断发送并保留选择和会话', () => {
  for (const [label, mutate] of [
    ['撤回', item => { item.status = 'revoked'; }],
    ['过期', item => { item.expires = '2000-01-01'; }],
    ['修订已变化', item => { item.revision += 1; }],
    ['授权已撤销', item => { item.rights = false; }],
    ['原件已不可用', item => { item.original.available = false; item.variants[0].available = false; }],
  ]) {
    const env = setup();
    const item = asset(env.agent.id);
    env.state.materials.push(item);
    select(env, item);
    const args = sendArgs(env.state, item);
    const selected = copy(env.state.ui.materials.selected);
    const messages = copy(env.conversation.messages);
    mutate(item);
    rejected(materialSendCheck(env.state, args), label);
    assert.throws(() => env.act('material-send', { ...args, message: '待发送说明' }), Error, label);
    assert.deepEqual(env.state.ui.materials.selected, selected, label);
    assert.deepEqual(env.conversation.messages, messages, label);
  }
});

test('人工发送必须持有当前人工会话，并显式匹配专家、会话与 generation', () => {
  for (const [label, change] of [
    ['AI 占用', env => { env.conversation.status = 'ai'; }],
    ['只读', env => { env.state.ui.readonly = true; }],
    ['专家已切换', env => { env.state.selectedAgentId = 'another-agent'; }],
    ['会话已切换', env => { env.state.ui.activeConversation = 'another-conversation'; }],
    ['任务代次已变化', env => { env.conversation.generation += 1; }],
    ['选择器旧代次用新表单代次', (env, request) => {
      env.conversation.generation += 1;
      request.generation = env.conversation.generation;
    }],
  ]) {
    const env = setup();
    const item = asset(env.agent.id);
    env.state.materials.push(item);
    select(env, item);
    const args = sendArgs(env.state, item);
    const selected = copy(env.state.ui.materials.selected);
    change(env, args);
    rejected(materialSendCheck(env.state, args), label);
    assert.throws(() => env.act('material-send', { ...args, message: '' }, { readonly: env.state.ui.readonly }), Error, label);
    assert.deepEqual(env.state.ui.materials.selected, selected, label);
  }
  for (const field of ['agentId', 'conversationId', 'generation']) {
    const env = setup();
    const item = asset(env.agent.id);
    env.state.materials.push(item);
    const args = sendArgs(env.state, item);
    delete args[field];
    rejected(materialSendCheck(env.state, args), `缺少 ${field}`);
  }
});

test('Agent 发送要求策略启用、物料自动权限、明确请求、当前策略修订及数量上限', () => {
  const env = setup('ai');
  const item = asset(env.agent.id);
  env.state.materials.push(item);
  const args = sendArgs(env.state, item, { actor: 'agent' });
  rejected(materialSendCheck(env.state, args), '默认关闭');
  env.agent.config.materialPolicy.enabled = true;
  assert.equal(materialSendCheck(env.state, args).ok, true);
  for (const [label, change] of [
    ['物料未授权自动发', ({ material }) => { material.autoSendAllowed = false; }],
    ['请求不明确', ({ request }) => { request.explicitRequest = false; }],
    ['缺少策略修订', ({ request }) => { delete request.expectedRevision; }],
    ['策略修订过时', ({ request }) => { request.expectedRevision -= 1; }],
    ['超出数量', ({ state, agent, request }) => {
      const second = asset(agent.id, { id: 'material-second' });
      state.materials.push(second);
      request.attachments.push({ id: second.id, revision: second.revision, variant: 'original' });
    }],
  ]) {
    const isolated = setup('ai');
    isolated.agent.config.materialPolicy.enabled = true;
    const material = asset(isolated.agent.id);
    isolated.state.materials.push(material);
    const request = sendArgs(isolated.state, material, { actor: 'agent' });
    change({ ...isolated, material, request });
    rejected(materialSendCheck(isolated.state, request), label);
  }
});

test('明确请求且当前 AI 占用时可模拟自动发送，消息保留附件并不标记已解决', () => {
  const env = setup('ai');
  const item = asset(env.agent.id);
  env.state.materials.push(item);
  env.agent.config.materialPolicy.enabled = true;
  const beforeCount = env.conversation.messages.length;
  const requestStatus = env.conversation.requestStatus;
  const policyAtSend = copy(env.agent.config.materialPolicy);
  env.act('material-auto-retrieve', { query: '课程介绍' });
  assert.equal(env.state.ui.materials.autoResults.length, 1);
  env.act('material-auto-send', { ...sendArgs(env.state, item, { actor: 'agent' }), query: '课程介绍', explicitRequest: true });
  assert.equal(env.conversation.messages.length, beforeCount + 1);
  const message = env.conversation.messages.at(-1);
  assert.equal(message.actor, 'agent');
  assert.equal(message.status, 'local-recorded');
  assert.equal(message.delivery, 'unknown');
  assert.equal(message.attachments.length, 1);
  assert.equal(message.attachments[0].revision, item.revision);
  assert.equal(env.conversation.requestStatus, requestStatus);
  assert.deepEqual(message.requestEvidence, {
    query: '课程介绍', explicitRequest: true, origin: 'operator-simulated-request',
  });
  assert.deepEqual(message.materialPolicy, policyAtSend);
  env.agent.config.materialPolicy.enabled = false;
  env.agent.config.materialPolicy.maxCount = 3;
  assert.deepEqual(message.materialPolicy, policyAtSend);
});

test('自动发送在人工占用、只读、旧代次及上下文切换后阻断并保留消息', () => {
  for (const [label, change] of [
    ['人工占用', env => { env.conversation.status = 'human'; }],
    ['只读', env => { env.state.ui.readonly = true; }],
    ['旧代次', env => { env.conversation.generation += 1; }],
    ['专家切换', env => { env.state.selectedAgentId = 'different-agent'; }],
    ['会话切换', env => { env.state.ui.activeConversation = 'different-conversation'; }],
  ]) {
    const env = setup('ai');
    const item = asset(env.agent.id);
    env.state.materials.push(item);
    env.agent.config.materialPolicy.enabled = true;
    const args = { ...sendArgs(env.state, item, { actor: 'agent' }), query: '课程介绍' };
    const messages = copy(env.conversation.messages);
    change(env);
    rejected(materialSendCheck(env.state, args), label);
    assert.throws(() => env.act('material-auto-send', args, { readonly: env.state.ui.readonly }), Error, label);
    assert.deepEqual(env.conversation.messages, messages, label);
  }
});

test('只读阻断物料变更，未知 action 不被吞掉', () => {
  for (const action of ['material-upsert', 'material-publish', 'material-revoke', 'material-review-summary', 'material-summary-demo', 'material-summary-fail', 'material-compress-demo', 'material-compress-fail', 'material-load-demo']) {
    const env = setup();
    const item = asset(env.agent.id);
    env.state.materials.push(item);
    const before = copy(env.state.materials);
    assert.throws(() => env.act(action, { id: item.id, title: '只读改动' }, { readonly: true }), Error, action);
    assert.deepEqual(env.state.materials, before, action);
  }
  const env = setup();
  assert.deepEqual(env.act('unrelated-action'), { handled: false });
});
