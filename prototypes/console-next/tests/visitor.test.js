import test from 'node:test';
import assert from 'node:assert/strict';
import { clone, initialState } from '../fixtures.js';
import { materialAssetSendCheck } from '../material-domain.js';
import { createStore, STORAGE_KEY } from '../store.js';
import { ensureVisitorState, visitorSession, handleVisitorAction, cancelVisitorSession } from '../visitor-domain.js';

const DATE = '2026-10-14T08:00:00.000Z';
const context = { now: () => DATE, uid: (() => { let sequence = 0; return prefix => `${prefix}-${++sequence}`; })() };

function material(kind = 'image', change = {}) {
  const titles = { image: '课程海报', video: '课程介绍视频', document: '服务手册' };
  const filename = { image: 'poster.png', video: 'intro.webm', document: 'guide.pdf' }[kind];
  const blobKey = `blob-${kind}`;
  return { id: `asset-${kind}`, revision: 3, title: titles[kind], kind, filename, mimeType: { image: 'image/png', video: 'video/webm', document: 'application/pdf' }[kind], rights: true, sourceRef: `fictional:${kind}`, expires: '2099-12-31', tags: ['课程', '服务'], usage: '服务说明', scope: 'selected', agentIds: ['course-demo'], canSend: true, autoSendAllowed: true, status: 'published', original: { blobKey, size: 1024, available: true }, summary: { text: `${titles[kind]}，用于介绍虚构课程与服务。`, reviewed: true, origin: 'manual', baseRevision: 3 }, processing: { compression: 'none', understanding: 'none' }, variants: [{ id: 'original', label: '原件', blobKey, size: 1024, available: true, simulated: false }], history: [], ...change };
}

function fresh() {
  const state = initialState();
  state.ui.page = 'trial';
  state.materials = [material('image'), material('video'), material('document')];
  const agent = state.agents[0];
  agent.config.materialPolicy.enabled = true;
  ensureVisitorState(state);
  const act = (action, data = {}, changes = {}) => handleVisitorAction(state, action, data, { ...context, ...changes });
  const start = (question, surface = 'trial') => act(surface === 'trial' ? 'trial-start' : 'widget-trial-start', { question }).value;
  const complete = (id, surface = 'trial', proof) => {
    const pending = visitorSession(state, surface).pending;
    return act(surface === 'trial' ? 'trial-complete' : 'widget-trial-complete', { id, availableFiles: proof === undefined ? pending?.fileRefs || [] : proof });
  };
  return { state, agent, act, start, complete };
}

test('旧 schema 默认补齐两入口，快照不暴露可写会话对象', () => {
  const state = initialState();
  ensureVisitorState(state);
  assert.equal(visitorSession(state).generation, 1);
  assert.equal(visitorSession(state, 'widget').ownership, 'ai');
  const snapshot = visitorSession(state);
  snapshot.messages.push({ text: '不能写回' });
  assert.equal(state.ui.trialMessages.length, 0);
  state.ui.widgetTrialInput = '独立内容';
  ensureVisitorState(state);
  assert.equal(visitorSession(state, 'widget').input, '独立内容');
  assert.throws(() => visitorSession(state, 'inbox'), /入口无效/);
  assert.deepEqual(handleVisitorAction(state, 'material-send'), { handled: false });
});

test('自然中文索取图片、视频和文档，发送冻结快照与明确的本地匹配证据', () => {
  for (const [kind, question] of [['image', '请发课程海报'], ['video', '想看看介绍视频'], ['document', '把服务手册给我']]) {
    const env = fresh(); const id = env.start(question);
    const pending = visitorSession(env.state).pending;
    assert.equal(pending.intent.kind, kind);
    assert.deepEqual(pending.attachments, [{ id: `asset-${kind}`, revision: 3, variant: 'original' }]);
    assert.deepEqual(pending.fileRefs, [{ id: `asset-${kind}`, revision: 3, blobKey: `blob-${kind}`, size: 1024, filename: material(kind).filename }]);
    env.complete(id);
    const message = env.state.ui.trialMessages.at(-1);
    assert.equal(message.status, 'material_sent');
    assert.equal(message.attachments[0].kind, kind);
    assert.equal(message.attachments[0].delivery, 'unknown');
    assert.equal(message.delivery, 'unknown');
    assert.equal(message.materialEvidence.method, 'deterministic-local-preview');
    assert.ok(message.trace.some(item => item.stage === 'files' && item.status === 'complete'));
    assert.equal(env.state.runs[0].surface, 'trial');
    assert.equal(env.state.runs[0].messageId, message.id);
    assert.equal(env.state.runs[0].resultEvidence.resolved, 'unknown');
    assert.equal(env.agent.checks.testedRevision, null);
  }
});

test('简介仅检索物料，不成为知识答复事实或批准/发布证据', () => {
  const env = fresh(); const sources = clone(env.agent.config.sources);
  env.start('请发课程海报'); env.complete(visitorSession(env.state).pending.id);
  assert.deepEqual(env.agent.config.sources, sources);
  assert.equal(env.agent.checks.testedRevision, null);
  assert.equal(env.agent.checks.approvedRevision, null);
  assert.deepEqual(env.state.runs[0].sources, []);
});

test('物料可以独立体验，不要求先添加 FAQ，但普通 FAQ 保持已有准备校验', () => {
  const env = fresh(); env.agent.config.sources = [];
  const id = env.start('想看看介绍视频'); env.complete(id);
  assert.equal(env.state.ui.trialMessages.at(-1).status, 'material_sent');
  env.act('trial-clear');
  assert.throws(() => env.start('什么时候上课？'), /没有有效/);
});

test('否定索取与普通咨询不会因为包含物料名称触发附件', () => {
  for (const question of ['不要发课程海报', '不用给我服务手册', '别发介绍视频', '课程海报是什么？', '服务手册包含什么内容？', '给我介绍一下课程', '给我开课时间', '给我讲解课程海报', '课程海报要多少钱？', '服务手册如何下载？']) {
    const env = fresh(); const id = env.start(question); env.complete(id);
    assert.equal(env.state.ui.trialMessages.at(-1).attachments.length, 0, question);
    assert.notEqual(env.state.runs[0].status, 'material_sent', question);
  }
});

test('人工请求优先且等待人工后阻止后续自动发送，清空会话才明确恢复 AI', () => {
  const env = fresh(); const inbox = clone(env.agent.conversations);
  const id = env.start('转人工并请发课程海报'); env.complete(id);
  assert.equal(visitorSession(env.state).ownership, 'waiting');
  assert.equal(env.state.ui.trialMessages.at(-1).status, 'handoff');
  assert.equal(env.state.ui.trialMessages.at(-1).attachments.length, 0);
  const blocked = env.start('请发课程海报'); env.complete(blocked);
  assert.equal(env.state.ui.trialMessages.at(-1).attachments.length, 0);
  env.act('trial-clear');
  assert.equal(visitorSession(env.state).ownership, 'ai');
  const freshId = env.start('请发课程海报'); env.complete(freshId);
  assert.equal(env.state.ui.trialMessages.at(-1).attachments.length, 1);
  assert.deepEqual(env.agent.conversations, inbox);
});

test('默认策略关闭时给安全回复与诊断，不暴露未经授权的材料元数据', () => {
  const env = fresh(); env.agent.config.materialPolicy.enabled = false;
  env.state.materials[0].title = '私密材料标题';
  const id = env.start('请发图片'); const pending = visitorSession(env.state).pending;
  assert.equal(pending.attachments.length, 0); assert.equal(pending.fileRefs.length, 0);
  env.complete(id);
  assert.equal(env.state.ui.trialMessages.at(-1).status, 'material_blocked');
  assert.ok(env.state.ui.trialMessages.at(-1).trace.some(item => item.status === 'blocked'));
  assert.ok(!JSON.stringify(env.state.ui.trialMessages.at(-1)).includes('私密材料标题'));
});

test('未审、过期、撤回、范围不匹配或未授予自动许可都不会召回附件', () => {
  for (const [label, mutate] of [
    ['未审', asset => { asset.summary.reviewed = false; }], ['旧简介', asset => { asset.summary.baseRevision = 2; }],
    ['撤回', asset => { asset.status = 'revoked'; }], ['过期', asset => { asset.expires = '2000-01-01'; }],
    ['无授权', asset => { asset.rights = false; }], ['无来源', asset => { asset.sourceRef = ''; }],
    ['范围不符', asset => { asset.agentIds = ['other']; }], ['未自动许可', asset => { asset.autoSendAllowed = false; }],
  ]) {
    const env = fresh(); mutate(env.state.materials[0]);
    const id = env.start('请发课程海报'); assert.equal(visitorSession(env.state).pending.attachments.length, 0, label);
    env.complete(id); assert.equal(env.state.ui.trialMessages.at(-1).status, 'material_blocked', label);
  }
});

test('缓存实际证明缺失、大小或文件名不符时不假造收件', () => {
  for (const proof of [[], [{ blobKey: 'wrong', size: 1024, filename: 'poster.png' }], [{ blobKey: 'blob-image', size: 3, filename: 'poster.png' }], [{ blobKey: 'blob-image', size: 1024, filename: 'different.png' }]]) {
    const env = fresh(); const id = env.start('请发课程海报'); env.complete(id, 'trial', proof);
    const message = env.state.ui.trialMessages.at(-1);
    assert.equal(message.attachments.length, 0); assert.equal(message.status, 'material_blocked');
    assert.equal(env.state.runs[0].resultEvidence.localReceived, false);
  }
});

test('缓存读取期间撤回、改版、权限或原件引用变化必须最终重验', () => {
  for (const mutate of [asset => { asset.status = 'revoked'; }, asset => { asset.revision += 1; }, asset => { asset.rights = false; }, asset => { asset.autoSendAllowed = false; }, asset => { asset.original.blobKey = 'changed'; asset.variants[0].blobKey = 'changed'; }, asset => { asset.original.available = false; }]) {
    const env = fresh(); const id = env.start('请发课程海报'); const frozen = visitorSession(env.state).pending.fileRefs;
    mutate(env.state.materials[0]); env.complete(id, 'trial', frozen);
    assert.equal(env.state.ui.trialMessages.at(-1).attachments.length, 0);
    assert.equal(env.state.ui.trialMessages.at(-1).status, 'material_blocked');
  }
});

test('草稿修订、未同步修订的策略变化、页面切换阻断旧回调', () => {
  for (const mutate of [env => { env.agent.revision += 1; }, env => { env.agent.config.materialPolicy.enabled = false; }, env => { env.state.ui.page = 'widget'; }]) {
    const env = fresh(); const id = env.start('请发课程海报'); const refs = visitorSession(env.state).pending.fileRefs;
    mutate(env); env.complete(id, 'trial', refs);
    assert.equal(env.state.ui.trialState, 'cancelled');
    assert.equal(env.state.ui.trialMessages.filter(item => item.role === 'assistant').length, 0);
    assert.equal(env.state.runs[0].status, 'cancelled');
  }
});

test('取消和清空提高代次，迟到回调不会写到重新开始的会话', () => {
  const env = fresh(); const id = env.start('请发课程海报'); const refs = visitorSession(env.state).pending.fileRefs;
  const generation = visitorSession(env.state).generation;
  env.act('trial-cancel');
  assert.equal(visitorSession(env.state).generation, generation + 1);
  env.complete(id, 'trial', refs);
  assert.equal(env.state.ui.trialMessages.filter(item => item.role === 'assistant').length, 0);
  env.act('trial-clear'); const next = env.start('把服务手册给我');
  env.complete(id, 'trial', refs);
  assert.equal(visitorSession(env.state).pending.id, next);
  env.complete(next); assert.equal(env.state.ui.trialMessages.at(-1).attachments[0].kind, 'document');
});

test('专家切换与会话代次变化不会发送旧附件', () => {
  for (const mutate of [env => { env.state.selectedAgentId = 'another'; }, env => { env.state.ui.trialGeneration += 1; }]) {
    const env = fresh(); const id = env.start('请发课程海报'); const refs = visitorSession(env.state).pending.fileRefs;
    mutate(env); env.complete(id, 'trial', refs);
    assert.equal(env.state.ui.trialMessages.filter(item => item.role === 'assistant').length, 0);
  }
});

test('试用台和 Widget 可独立运行与取消，不写入 Inbox 会话', () => {
  const env = fresh(); const inbox = clone(env.agent.conversations);
  const trial = env.start('请发课程海报'); const widget = env.start('想看看介绍视频', 'widget');
  env.act('trial-cancel'); env.complete(widget, 'widget');
  assert.equal(visitorSession(env.state).status, 'cancelled');
  assert.equal(visitorSession(env.state, 'widget').status, 'complete');
  assert.equal(visitorSession(env.state, 'widget').messages.at(-1).attachments[0].kind, 'video');
  env.complete(trial);
  assert.deepEqual(env.agent.conversations, inbox);
});

test('模拟压缩附件保持无字节事实，仍要求实际原件缓存证明', () => {
  const env = fresh(); const asset = env.state.materials[0];
  asset.processing.compression = 'mock-ready';
  asset.variants.push({ id: 'compressed-demo', label: '模拟压缩', blobKey: null, size: null, available: true, simulated: true });
  env.agent.config.materialPolicy.preferredVariant = 'compressed-demo';
  const id = env.start('请发课程海报');
  assert.equal(visitorSession(env.state).pending.fileRefs[0].blobKey, 'blob-image');
  env.complete(id);
  const attachment = env.state.ui.trialMessages.at(-1).attachments[0];
  assert.equal(attachment.variant, 'compressed-demo'); assert.equal(attachment.blobKey, null); assert.equal(attachment.size, null); assert.equal(attachment.simulated, true);
  assert.match(env.state.ui.trialMessages.at(-1).text, /没有实际文件/);
});

test('版本偏好不可用时只按已配置许可回退原件', () => {
  const env = fresh(); env.agent.config.materialPolicy.preferredVariant = 'compressed-demo';
  env.agent.config.materialPolicy.allowOriginalFallback = false;
  let id = env.start('请发课程海报'); env.complete(id);
  assert.equal(env.state.ui.trialMessages.at(-1).status, 'material_blocked');
  env.act('trial-clear'); env.agent.config.materialPolicy.allowOriginalFallback = true;
  id = env.start('请发课程海报'); env.complete(id);
  assert.equal(env.state.ui.trialMessages.at(-1).attachments[0].variant, 'original');
});

test('附件收件、查看和下载发起是独立观察事实，不改变资产快照或未知外部结果', () => {
  const env = fresh(); const id = env.start('请发课程海报'); env.complete(id);
  const message = env.state.ui.trialMessages.at(-1); const frozen = clone(message.attachments);
  const actionData = { surface: 'trial', messageId: message.id, id: frozen[0].id, revision: frozen[0].revision, variant: frozen[0].variant };
  env.act('visitor-received', { surface: 'widget', messageId: message.id });
  assert.equal(message.localReceipt.status, 'pending');
  env.act('visitor-received', actionData);
  env.act('visitor-opened', { ...actionData, revision: 2 });
  assert.deepEqual(message.attachmentInteractions, {});
  env.act('visitor-opened', actionData); env.act('visitor-downloaded', actionData);
  assert.deepEqual(message.attachmentInteractions['asset-image:3:original'], { openedAt: DATE, downloadStartedAt: DATE });
  assert.equal(message.localReceipt.status, 'received'); assert.deepEqual(message.attachments, frozen);
  assert.equal(env.state.runs[0].resultEvidence.localReceived, true);
  assert.equal(env.state.runs[0].localReceipt.status, 'received');
  assert.deepEqual(env.state.runs[0].attachmentInteractions, message.attachmentInteractions);
  assert.equal(env.state.runs[0].resultEvidence.delivered, false); assert.equal(env.state.runs[0].resultEvidence.resolved, 'unknown');
  env.state.materials[0].title = '后续名称'; env.state.materials[0].summary.text = '后续简介';
  assert.deepEqual(message.attachments, frozen);
});

test('FAQ 答案、来源修订、testedRevision 与 Run 链保持兼容', () => {
  const env = fresh(); const source = env.agent.config.sources[0];
  const id = env.start(source.question); env.complete(id);
  const message = env.state.ui.trialMessages.at(-1);
  assert.equal(message.text, source.answer); assert.equal(message.status, 'answered');
  assert.deepEqual(message.sources, [{ id: source.id, title: source.title, version: source.version }]);
  assert.equal(env.agent.checks.testedRevision, env.agent.revision);
  assert.equal(env.state.runs[0].id, id); assert.equal(env.state.runs[0].resultEvidence.delivered, false);
  assert.equal(env.state.runs[0].cost, null);
});

test('只读模式阻断开始，在缓存处理期间切到只读也取消旧发送', () => {
  const env = fresh(); env.state.ui.readonly = true;
  assert.throws(() => env.start('请发课程海报'), /只读/);
  env.state.ui.readonly = false; const id = env.start('请发课程海报');
  env.state.ui.readonly = true; env.complete(id);
  assert.equal(visitorSession(env.state).status, 'cancelled');
  assert.equal(env.state.ui.trialMessages.filter(item => item.role === 'assistant').length, 0);
});

test('共享资产校验不依赖 Inbox，仍校验当前草稿策略与冻结资产选择', () => {
  const env = fresh(); env.state.ui.activeConversation = null;
  const args = { agentId: env.agent.id, attachments: [{ id: 'asset-image', revision: 3, variant: 'original' }], actor: 'agent', explicitRequest: true, expectedRevision: env.agent.revision, date: '2026-10-14' };
  assert.equal(materialAssetSendCheck(env.state, args).ok, true);
  assert.equal(materialAssetSendCheck(env.state, { ...args, expectedRevision: 1 }).ok, false);
  assert.equal(materialAssetSendCheck(env.state, { ...args, attachments: args.attachments.concat(args.attachments) }).ok, false);
});

test('文件读取阶段事件只记入有效 pending，cancel 公共方法记录取消 Run', () => {
  const env = fresh(); const id = env.start('请发课程海报');
  env.act('trial-stage', { id: 'stale', stage: 'files', detail: '旧回调' });
  assert.ok(!JSON.stringify(visitorSession(env.state).pending.trace).includes('旧回调'));
  env.act('trial-stage', { id, stage: 'files', detail: '正在核对浏览器缓存' });
  assert.equal(visitorSession(env.state).pending.trace.at(-1).detail, '正在核对浏览器缓存');
  cancelVisitorSession(env.state, 'trial', context);
  assert.equal(env.state.runs[0].status, 'cancelled');
  assert.equal(env.state.runs[0].resultEvidence.generated, false);
});

test('快捷索取优先使用实际物料标题，Run 保留本地访客输入和策略快照', () => {
  const env = fresh();
  env.act('trial-example', { kind: 'image', question: '请发课程海报' });
  assert.equal(visitorSession(env.state).input, '请发课程海报');
  env.act('widget-trial-example', { kind: 'video', question: '请发新生欢迎视频' });
  assert.equal(visitorSession(env.state, 'widget').input, '请发新生欢迎视频');
  const policy = clone(env.agent.config.materialPolicy);
  const id = env.start('请发课程海报'); env.complete(id);
  const run = env.state.runs[0];
  assert.deepEqual(run.requestEvidence, { query: '请发课程海报', explicitRequest: true, origin: 'local-visitor-input', surface: 'trial' });
  assert.deepEqual(run.materialPolicy, policy);
  assert.equal(run.materialEvidence.trace.at(-1).stage, 'send');
  env.agent.config.materialPolicy.enabled = false;
  assert.deepEqual(run.materialPolicy, policy);
});

test('清空会话后仍可查看当前专家的历史 Run 附件，错入口或专家不能记录交互', () => {
  const env = fresh(); const id = env.start('请发课程海报'); env.complete(id);
  const run = env.state.runs[0]; const snapshot = clone(run.attachments);
  env.act('trial-clear');
  const data = { surface: 'trial', runId: run.id, messageId: run.messageId, id: 'asset-image', revision: 3, variant: 'original' };
  env.act('visitor-opened', { ...data, surface: 'widget' });
  assert.deepEqual(run.attachmentInteractions, {});
  env.act('visitor-opened', data);
  env.act('visitor-downloaded', data);
  assert.deepEqual(run.attachmentInteractions['asset-image:3:original'], { openedAt: DATE, downloadStartedAt: DATE });
  assert.deepEqual(run.attachments, snapshot);
  assert.equal(env.state.ui.trialMessages.length, 0);
  delete run.attachmentInteractions['asset-image:3:original'];
  env.state.selectedAgentId = 'other';
  env.act('visitor-opened', data);
  assert.deepEqual(run.attachmentInteractions, {});
});

test('中文否定索取不会发送匹配附件，包括后置否定和含糊双重否定', () => {
  for (const question of ['课程海报不给我发', '课程海报不发给我', '不发送课程海报', '不是想看课程海报', '没必要发送课程海报', '没必要把课程海报发给我', '不是不能发课程海报']) {
    const env = fresh(); const id = env.start(question);
    assert.equal(visitorSession(env.state).pending.intent.type, 'declined', question);
    env.complete(id);
    assert.equal(env.state.ui.trialMessages.at(-1).attachments.length, 0, question);
    assert.notEqual(env.state.runs[0].status, 'material_sent', question);
  }
});

test('旧 schema 正在运行的试用结构可恢复启动并取消，保留问题且不伪造附件或收件', () => {
  const seed = initialState(); const agent = seed.agents[0];
  seed.ui.page = 'trial'; seed.ui.trialState = 'running';
  seed.ui.trialInput = '未提交输入也应保留';
  seed.ui.trialMessages = [{ role: 'user', text: '什么时候上课？', revision: agent.revision }];
  seed.ui.pendingTrial = { id: 'legacy-running', agentId: agent.id, revision: agent.revision, config: clone(agent.config), question: '什么时候上课？' };
  delete seed.ui.pendingTrial.config.materialPolicy;
  delete agent.config.materialPolicy;
  let raw = JSON.stringify(seed);
  const storage = { getItem: key => key === STORAGE_KEY ? raw : null, setItem: (key, value) => { if (key === STORAGE_KEY) raw = value; } };
  const store = createStore(storage);
  assert.equal(store.state.ui.trialState, 'cancelled');
  assert.equal(store.state.ui.pendingTrial, null);
  assert.equal(store.state.ui.trialInput, '未提交输入也应保留');
  assert.equal(store.state.ui.trialMessages[0].text, '什么时候上课？');
  assert.equal(store.state.runs[0].id, 'legacy-running');
  assert.equal(store.state.runs[0].input, '什么时候上课？');
  assert.equal(store.state.runs[0].surface, 'trial');
  assert.equal(store.state.runs[0].status, 'cancelled');
  assert.deepEqual(store.state.runs[0].attachments, []);
  assert.deepEqual(store.state.runs[0].resultEvidence, { generated: false, delivered: false, resolved: 'unknown', localReceived: false });
  assert.equal(store.state.runs[0].localReceipt.status, 'pending');
  assert.equal(store.state.runs[0].materialEvidence, null);
  assert.equal(store.currentAgent().checks.testedRevision, null);
  const started = store.dispatch('trial-start', { question: '什么时候上课？' });
  assert.equal(started.ok, true);
  assert.equal(store.dispatch('trial-complete', { id: started.value }).ok, true);
  assert.equal(store.state.ui.trialMessages.at(-1).status, 'answered');
});
