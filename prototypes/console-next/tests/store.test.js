import test from 'node:test';
import assert from 'node:assert/strict';
import { createStore, STORAGE_KEY } from '../store.js';
import { clone, initialState } from '../fixtures.js';
import { prepareAgentTask, readiness, sourceValid, versionValid } from '../domain.js';

const faq = { type: 'FAQ', title: '自有资料', question: '何时上课？', answer: '周末上午。', rights: true, sourceRef: 'authorized:test-v1', expires: '2099-12-31' };
function fresh() { return createStore(); }
function addFAQ(store, data = {}) {
  assert.equal(store.dispatch('source', { ...faq, ...data }).ok, true);
  const source = store.currentAgent().config.sources.at(-1);
  store.dispatch('source-stage', { id: source.id, stage: 'parsed' });
  store.dispatch('source-stage', { id: source.id, stage: 'review' });
  store.dispatch('source-stage', { id: source.id, stage: 'indexed' });
  return source;
}
function trial(store, question) {
  const started = store.dispatch('trial-start', { question });
  assert.equal(started.ok, true);
  store.dispatch('trial-complete', { id: started.value });
  return store.state.runs[0];
}

test('知识工作面返回保留筛选，切换资料类型清理旧详情和不相干搜索', () => {
  const store = fresh(); const source = store.currentAgent().config.sources[0];
  store.dispatch('update-ui', { path: 'search', value: source.question });
  store.dispatch('update-ui', { path: 'sourceFilter', value: 'ready' });
  store.dispatch('source-detail', { id: source.id });
  store.dispatch('source-list');
  assert.equal(store.state.ui.sourceDetail, null);
  assert.equal(store.state.ui.search, source.question);
  assert.equal(store.state.ui.sourceFilter, 'ready');
  store.dispatch('source-edit', { id: source.id });
  store.dispatch('source-tab', { tab: 'URL' });
  assert.equal(store.state.ui.sourceForm, false);
  assert.equal(store.state.ui.sourceEdit, null);
  assert.equal(store.state.ui.sourceDetail, null);
  assert.equal(store.state.ui.search, '');
  assert.equal(store.state.ui.sourceFilter, 'all');
});
test('知识编辑取消返回同一详情，新建取消返回列表，引用入口不残留旧表单', () => {
  const store = fresh(); const source = store.currentAgent().config.sources[0];
  store.dispatch('source-edit', { id: source.id });
  assert.equal(store.state.ui.sourceDetail, source.id);
  store.dispatch('source-form-toggle');
  assert.equal(store.state.ui.sourceForm, false);
  assert.equal(store.state.ui.sourceDetail, source.id);
  store.dispatch('source-form-toggle');
  assert.equal(store.state.ui.sourceDetail, null);
  store.dispatch('source-form-toggle');
  assert.equal(store.state.ui.sourceForm, false);
  assert.equal(store.state.ui.sourceDetail, null);
  store.dispatch('source-form-toggle');
  store.dispatch('source-open', { id: source.id });
  assert.equal(store.state.ui.page, 'knowledge');
  assert.equal(store.state.ui.sourceDetail, source.id);
  assert.equal(store.state.ui.sourceForm, false);
});
test('同路由重新载入保留搜索，切专家退出旧录入并让迟到文件失效', () => {
  const store = fresh(); const source = store.currentAgent().config.sources[0];
  store.dispatch('navigate', { page: 'knowledge' });
  store.dispatch('update-ui', { path: 'search', value: '标准解答' });
  store.dispatch('navigate', { page: 'knowledge' });
  assert.equal(store.state.ui.search, '标准解答');
  store.dispatch('source-edit', { id: source.id });
  store.dispatch('material-form-toggle');
  const session = store.state.ui.materials.session;
  store.dispatch('create', { name: '第二位专家' });
  assert.equal(store.state.ui.sourceForm, false);
  assert.equal(store.state.ui.search, '');
  assert.equal(store.state.ui.materials.form, false);
  assert.equal(store.state.ui.materials.editingId, null);
  assert.ok(store.state.ui.materials.session > session);
  store.dispatch('material-upload-ready', { session, meta: { blobKey: 'late', filename: 'late.png', mimeType: 'image/png', size: 10, available: true } });
  assert.equal(store.state.ui.materials.upload, null);
});
test('检索结果不跨专家、配置修订或浏览器重载保留', () => {
  const store = fresh();
  store.state.ui.materials.autoResults = [{ id: 'old-agent-material', title: '旧范围结果' }];
  store.state.ui.materials.autoQuery = '旧专家关键词';
  store.dispatch('update-config', { path: 'materialPolicy.enabled', value: true });
  assert.deepEqual(store.state.ui.materials.autoResults, []);
  store.state.ui.materials.autoResults = [{ id: 'old-agent-material' }];
  store.dispatch('create', { name: '另一专家' });
  assert.deepEqual(store.state.ui.materials.autoResults, []);
  assert.equal(store.state.ui.materials.autoQuery, '');
  store.state.ui.materials.autoResults = [{ id: 'expired-result' }];
  const restored = createStore({ getItem: () => JSON.stringify(store.state), setItem() {} });
  assert.deepEqual(restored.state.ui.materials.autoResults, []);
});

test('完整手动创建不需要助手、资料或写工具；空草稿能保存', () => {
  const store = fresh();
  store.dispatch('create', { name: '售后专员', goal: '根据授权资料回答售后问题。', mode: 'manual' });
  assert.equal(store.currentAgent().name, '售后专员');
  assert.equal(store.state.ui.assistantOpen, false);
  assert.equal(store.currentAgent().config.tools.length, 0);
  assert.equal(readiness(store.currentAgent(), store.state.connections).canTrial, false);
  assert.equal(store.dispatch('save-now').ok, true);
});
test('Agent协助只是可选说明，不自动弹面板；手动内容持续可用', () => {
  const store = fresh(); store.dispatch('create', { name: '咨询客服', mode: 'assistant' });
  assert.equal(store.state.ui.assistantOpen, false);
  store.dispatch('toggle-assistant');
  assert.equal(store.state.ui.assistantOpen, true);
  store.dispatch('update-config', { path: 'greeting', value: '手动欢迎语' });
  store.dispatch('toggle-assistant');
  assert.equal(store.state.ui.assistantOpen, false);
  assert.equal(store.currentAgent().config.greeting, '手动欢迎语');
});
test('自有FAQ未经授权不能标为可用，合法资料可用于真实本地登记与脚本匹配', () => {
  const store = fresh(); store.dispatch('create', { name: '我的客服' });
  store.dispatch('source', { ...faq, rights: false });
  const unauthorized = store.currentAgent().config.sources[0];
  assert.equal(store.dispatch('source-stage', { id: unauthorized.id, stage: 'indexed' }).ok, false);
  const source = addFAQ(store);
  const run = trial(store, faq.question);
  assert.equal(run.answer, faq.answer);
  assert.equal(run.sources[0].id, source.id);
  assert.equal(run.resultEvidence.delivered, false);
  assert.equal(run.resultEvidence.resolved, 'unknown');
  assert.equal(run.mode, 'simulation');
});
test('修订资料产生新版本并失效当前检查，不改写历史版本', () => {
  const store = fresh(); const agent = store.currentAgent();
  const frozen = clone(agent.versions[0]); const source = agent.config.sources[0];
  trial(store, source.question);
  assert.equal(agent.checks.testedRevision, agent.revision);
  store.dispatch('source', { ...source, id: source.id, answer: '人工修订的新答案' });
  assert.equal(source.version, 2); assert.equal(source.status, 'received');
  assert.equal(agent.checks.testedRevision, null);
  assert.deepEqual(agent.versions[0], frozen);
});
test('撤回来源阻断后续脚本与绑定，回滚不恢复授权', () => {
  const store = fresh(); const agent = store.currentAgent();
  for (const source of [...agent.config.sources]) store.dispatch('source-revoke', { id: source.id });
  assert.equal(readiness(agent, store.state.connections).canTrial, false);
  assert.equal(versionValid(agent, agent.versions[0], store.state.connections), false);
  store.dispatch('version-restore', { id: 'v1' });
  assert.equal(agent.config.sources.every(source => !source.rights && source.status === 'revoked'), true);
  assert.equal(agent.bindings.widget, 'v1');
  assert.equal(store.dispatch('source-stage', { id: agent.config.sources[0].id, stage: 'indexed' }).ok, false);
});
test('URL与不可解析文件不能以模拟状态冒充可用知识', () => {
  const store = fresh();
  store.dispatch('source', { ...faq, type: 'URL', url: 'https://example.invalid/page', question: '', answer: '' });
  let source = store.currentAgent().config.sources.at(-1);
  assert.equal(source.metadataOnly, true); assert.equal(source.status, 'failed');
  assert.equal(store.dispatch('source-stage', { id: source.id, stage: 'indexed' }).ok, false);
  store.dispatch('source', { ...faq, type: 'File', metadataOnly: true, filename: 'guide.pdf', body: '' });
  source = store.currentAgent().config.sources.at(-1);
  assert.equal(sourceValid(source), false);
  assert.equal(store.dispatch('source-retry', { id: source.id }).ok, false);
});
test('空文本与超限文本不伪造解析成功或静默截断', () => {
  const store = fresh();
  store.dispatch('source', { ...faq, type: 'File', body: '' });
  const source = store.currentAgent().config.sources.at(-1);
  assert.equal(store.dispatch('source-stage', { id: source.id, stage: 'indexed' }).ok, false);
  const count = store.currentAgent().config.sources.length;
  assert.equal(store.dispatch('source', { ...faq, type: 'File', body: 'A'.repeat(50001) }).ok, false);
  assert.equal(store.currentAgent().config.sources.length, count);
});
test('保存草稿不会改变入口和冻结配置；绑定需要显式批准', () => {
  const store = fresh(); const agent = store.currentAgent(); const frozen = clone(agent.versions[0]);
  store.dispatch('update-config', { path: 'greeting', value: '新的欢迎语' });
  store.dispatch('save-now');
  assert.equal(agent.bindings.widget, 'v1'); assert.deepEqual(agent.versions[0], frozen);
  assert.equal(store.dispatch('sandbox-publish', { target: 'widget' }).ok, false);
  trial(store, agent.config.sources[0].question);
  assert.equal(store.dispatch('sandbox-approve').ok, true);
  assert.equal(store.dispatch('sandbox-publish', { target: 'widget' }).ok, true);
  assert.equal(agent.bindings.widget, 'v2');
  store.dispatch('update-config', { path: 'tone', value: '亲切专业' });
  assert.equal(agent.bindings.widget, 'v2'); assert.equal(agent.checks.approvedRevision, null);
});
test('历史版本预览跨配置深度仍只读，返回草稿不改历史', () => {
  const store = fresh(); const frozen = clone(store.currentAgent().versions[0]);
  store.dispatch('version-preview', { id: 'v1' });
  store.dispatch('set-depth', { depth: 'business' });
  assert.equal(store.readonly(), true);
  assert.equal(store.dispatch('update-config', { path: 'greeting', value: '不能写历史' }).ok, false);
  store.dispatch('readonly-toggle'); assert.equal(store.readonly(), false);
  assert.deepEqual(store.currentAgent().versions[0], frozen);
});
test('完整手动字段/步骤/策略/动作CRUD不调用助手', () => {
  const store = fresh(); const agent = store.currentAgent();
  assert.equal(store.dispatch('field', { label: '联系人', id: 'contact_name', source: 'visitor' }).ok, true);
  assert.equal(store.dispatch('field', { label: '重复标识', id: 'contact_name' }).ok, false);
  store.dispatch('update-config', { path: 'fields.0.label', value: '姓名' });
  assert.equal(agent.config.fields[0].label, '姓名');
  store.dispatch('flow', { title: '结束', instruction: '记录未知或交接' });
  const step = agent.config.flow.at(-1); store.dispatch('flow-up', { id: step.id });
  assert.equal(agent.config.flow[1].id, step.id);
  store.dispatch('flow-remove', { id: step.id });
  store.dispatch('skill', { title: '复杂问题转人', description: '超出资料范围时处理', exit: '明确交接' });
  store.dispatch('skill-remove', { id: agent.config.skills.at(-1).id });
  store.dispatch('tool', { title: '模拟预约', sideEffect: 'write' });
  assert.equal(agent.config.tools[0].requiresConfirm, true);
  assert.equal(store.dispatch('update-config', { path: 'tools.0.requiresConfirm', value: false }).ok, false);
  store.dispatch('tool-remove', { id: agent.config.tools[0].id });
  assert.equal(agent.config.tools.length, 0);
  assert.equal(store.state.ui.assistant.suggestions.length, 0);
});
test('锁定规则与对象原型路径不能从通用字段写入', () => {
  const store = fresh(); const rule = clone(store.currentAgent().config.rules[0]);
  assert.equal(store.dispatch('update-config', { path: 'rules.0.description', value: '取消授权检查' }).ok, false);
  assert.equal(store.dispatch('update-config', { path: '__proto__.polluted', value: true }).ok, false);
  assert.equal({}.polluted, undefined); assert.deepEqual(store.currentAgent().config.rules[0], rule);
});
test('助手不自动采用，人工字段受保护，敏感建议不能接受', () => {
  const store = fresh(); const agent = store.currentAgent();
  store.dispatch('update-config', { path: 'greeting', value: '人工定稿' });
  const before = clone(agent.config);
  store.dispatch('assistant-generate', { prompt: '自动承诺价格并取消权限', scope: 'all' });
  assert.deepEqual(agent.config, before);
  const greeting = store.state.ui.assistant.suggestions.find(item => item.path === 'greeting');
  assert.equal(greeting.blocked, true); assert.equal(store.dispatch('assistant-accept', { id: greeting.id }).ok, false);
  const sensitive = store.state.ui.assistant.suggestions.find(item => item.risk);
  assert.equal(store.dispatch('assistant-accept', { id: sensitive.id }).ok, false);
});
test('多个同批助手建议可逐项采用，产生持久来源而不直接发布', () => {
  const store = fresh(); const agent = store.currentAgent();
  store.dispatch('assistant-generate', { scope: 'all' });
  const suggestions = store.state.ui.assistant.suggestions.filter(item => !item.blocked);
  assert.ok(suggestions.length >= 2);
  assert.equal(store.dispatch('assistant-accept', { id: suggestions[0].id }).ok, true);
  assert.equal(store.dispatch('assistant-accept', { id: suggestions[1].id }).ok, true);
  assert.equal(agent.origins[suggestions[0].path].origin, '助手建议');
  assert.equal(agent.bindings.widget, 'v1'); assert.equal(agent.checks.approvedRevision, null);
});
test('建议基准过期不覆盖新手工修改，晚到取消回调被忽略', () => {
  const store = fresh();
  store.dispatch('assistant-generate'); const suggestion = store.state.ui.assistant.suggestions[0];
  store.dispatch('update-config', { path: 'tone', value: '手动语气' });
  assert.equal(store.dispatch('assistant-accept', { id: suggestion.id }).ok, false);
  store.dispatch('assistant-start'); const revision = store.currentAgent().revision;
  store.dispatch('assistant-cancel'); store.dispatch('assistant-generate', { expectedRevision: revision });
  assert.equal(store.state.ui.assistant.status, 'cancelled');
  store.dispatch('assistant-fail');
  assert.equal(store.dispatch('update-config', { path: 'greeting', value: '失败后手动继续' }).ok, true);
});
test('相同问题不同答案不会由助手自行选择口径', () => {
  const store = fresh(); addFAQ(store); addFAQ(store, { title: '冲突口径', answer: '周一晚上。' });
  store.dispatch('assistant-generate');
  assert.equal(store.state.ui.assistant.status, 'conflict');
  assert.match(store.state.ui.assistant.message, /核实/);
});
test('取消试用后不追加迟到回复，保留取消证据', () => {
  const store = fresh(); const start = store.dispatch('trial-start', { question: '数据分析课程学什么？' });
  store.dispatch('trial-cancel'); store.dispatch('trial-complete', { id: start.value });
  assert.equal(store.state.runs[0].status, 'cancelled');
  assert.equal(store.state.ui.trialMessages.filter(item => item.role === 'assistant').length, 0);
  assert.equal(store.currentAgent().checks.testedRevision, null);
});
test('配置中途变更使旧试用中止，专家切换不混入回复', () => {
  const store = fresh(); const start = store.dispatch('trial-start', { question: '什么时候上课？' });
  store.dispatch('update-config', { path: 'tone', value: '亲切专业' }); store.dispatch('trial-complete', { id: start.value });
  assert.equal(store.state.ui.trialState, 'cancelled');
  store.dispatch('trial-clear'); const next = store.dispatch('trial-start', { question: '什么时候上课？' });
  store.dispatch('create', { name: '新客服' }); store.dispatch('trial-complete', { id: next.value });
  assert.equal(store.state.ui.trialMessages.length, 0);
  assert.equal(store.state.runs.every(run => run.agentId === 'course-demo'), true);
});
test('人工承接和回复不改变业务请求终态，释放使旧占用失效', () => {
  const store = fresh(); const conversation = store.currentAgent().conversations[0];
  assert.equal(store.dispatch('inbox', { message: '未接管直接发送' }).ok, false);
  store.dispatch('inbox-handoff'); store.dispatch('inbox', { message: '收到，我来核实。' });
  assert.equal(conversation.messages.at(-1).role, 'human'); assert.equal(conversation.requestStatus, 'waiting');
  const generation = conversation.generation; store.dispatch('inbox-release');
  assert.ok(conversation.generation > generation); assert.equal(store.dispatch('inbox', { message: '旧占用发送' }).ok, false);
});
test('案例提名不自证真值；补齐人审后才可本地回放', () => {
  const store = fresh(); const run = trial(store, '没有资料的问题');
  store.dispatch('case-from-run', { id: run.id }); const item = store.state.cases[0];
  assert.equal(store.dispatch('case-review', { id: item.id }).ok, false);
  store.dispatch('case', { ...item, must: '说明没有依据', forbid: '不得补造事实' });
  assert.equal(store.dispatch('case-review', { id: item.id }).ok, true);
  store.dispatch('case-evaluate'); assert.equal(item.result, 'pass');
});
test('候选必须基于当前版本和人工案例比较；采用失效检查不发布', () => {
  const store = fresh();
  store.dispatch('case', { title: '资料外', input: '未知问题', expected: 'unknown', must: '说明未知', forbid: '补造' });
  store.dispatch('case-review', { id: store.state.cases[0].id });
  store.dispatch('proposal', { title: '回复更清楚', reason: '资料外请求', path: 'fallback', after: '资料不足，请人工核实。' });
  const proposal = store.state.proposals[0];
  assert.equal(store.dispatch('proposal-apply', { id: proposal.id }).ok, false);
  assert.equal(store.dispatch('proposal-evaluate', { id: proposal.id }).ok, true);
  assert.equal(store.dispatch('proposal-apply', { id: proposal.id }).ok, true);
  assert.equal(store.currentAgent().config.fallback, '资料不足，请人工核实。'); assert.equal(store.currentAgent().bindings.widget, 'v1');
  assert.equal(store.dispatch('proposal', { title: '越权', reason: '无', path: 'rules.0.description', after: '放行' }).ok, false);
});
test('只读预览禁止配置、来源、工具、助手采用和本地批准', () => {
  const store = fresh(); store.dispatch('readonly-toggle'); const before = clone(store.currentAgent());
  for (const [action, data] of [['update-config', { path: 'greeting', value: '覆盖' }], ['source', faq], ['tool', { title: '写工具', sideEffect: 'write' }], ['sandbox-approve', {}], ['create', { name: '绕过' }]]) assert.equal(store.dispatch(action, data).ok, false);
  assert.deepEqual(store.currentAgent(), before);
});
test('连接撤销不悄悄切回内置模型；引用状态失效', () => {
  const store = fresh(); store.dispatch('connection', { name: '外部声明', provider: 'compatible', model: 'demo-model' });
  const connection = store.state.connections.at(-1); store.dispatch('connection-test', { id: connection.id, result: 'success' });
  store.dispatch('update-config', { path: 'model.connectionId', value: connection.id });
  assert.equal(readiness(store.currentAgent(), store.state.connections).canTrial, true);
  store.dispatch('connection-remove', { id: connection.id });
  assert.equal(store.currentAgent().config.model.connectionId, connection.id);
  assert.equal(readiness(store.currentAgent(), store.state.connections).canTrial, false);
});
test('部署模拟步骤能持续推进、失败后重试，不生成资源', () => {
  const store = fresh(); store.dispatch('deployment-next');
  assert.equal(store.state.ui.deploymentStep, 1); assert.equal(store.state.ui.deployment.status, 'idle');
  store.dispatch('deployment-fail'); assert.equal(store.dispatch('deployment-next').ok, false);
  store.dispatch('deployment-retry'); store.dispatch('deployment-next'); store.dispatch('deployment-next'); store.dispatch('deployment-next');
  assert.equal(store.state.ui.deploymentStep, 4); assert.equal(store.state.ui.deployment.status, 'complete');
  assert.equal(store.state.ui.deployment.history.every(row => row.text.includes('不创建云资源')), true);
  store.dispatch('deployment-backup'); store.dispatch('deployment-restore');
  assert.equal(store.state.ui.deployment.restore.status, 'simulation');
});
test('浏览器本地恢复保留同一草稿和版本，损坏数据有可恢复提示', () => {
  const memory = new Map(); const storage = { getItem: key => memory.get(key), setItem: (key, value) => memory.set(key, value) };
  const store = createStore(storage); store.dispatch('create', { name: '持续编辑' }); store.dispatch('update-config', { path: 'greeting', value: '恢复后的欢迎语' });
  const restored = createStore(storage); assert.equal(restored.currentAgent().config.greeting, '恢复后的欢迎语');
  memory.set(STORAGE_KEY, '{broken'); const damaged = createStore(storage);
  assert.match(damaged.state.ui.toast.text, /无法读取/); assert.equal(damaged.state.ui.saveStatus, 'error');
  memory.set(STORAGE_KEY, JSON.stringify({ ...initialState(), agents: [{ config: { sources: [] } }] }));
  assert.equal(createStore(storage).state.ui.saveStatus, 'error');
});
test('存储失败不丢当前内存草稿，并提供导出/重试说明', () => {
  const store = createStore({ getItem() { return null; }, setItem() { throw new Error('quota'); } });
  store.dispatch('update-config', { path: 'greeting', value: '存储失败时保留的内容' });
  assert.equal(store.currentAgent().config.greeting, '存储失败时保留的内容');
  assert.equal(store.state.ui.saveStatus, 'error'); assert.match(store.state.ui.toast.text, /导出/);
});
test('人工保护随稳定步骤迁移，重排/删除不会让候选覆盖人工内容', () => {
  const store = fresh(); const agent = store.currentAgent();
  store.dispatch('update-config', { path: 'flow.1.instruction', value: '人工确认的关键顺序' });
  const id = agent.config.flow[1].id; store.dispatch('flow-up', { id });
  store.dispatch('assistant-generate', { scope: 'flow' });
  const suggestion = store.state.ui.assistant.suggestions.find(item => item.path === 'flow.0.instruction');
  assert.equal(suggestion.blocked, true);
  assert.equal(store.dispatch('assistant-accept', { id: suggestion.id }).ok, false);
  assert.equal(agent.config.flow[0].instruction, '人工确认的关键顺序');
});
test('未裁决的相同问题口径冲突阻断试用/批准，而不随便选第一条', () => {
  const store = fresh(); addFAQ(store); const other = addFAQ(store, { answer: '与前一口径相反。' });
  assert.equal(readiness(store.currentAgent(), store.state.connections).canTrial, false);
  assert.equal(store.dispatch('trial-start', { question: faq.question }).ok, false);
  assert.equal(store.dispatch('sandbox-check').ok, false);
  store.dispatch('source-revoke', { id: other.id });
  assert.equal(readiness(store.currentAgent(), store.state.connections).canTrial, true);
});
test('回放证据在改稿后明确待重验，不能把旧通过当成本版通过', () => {
  const store = fresh(); store.dispatch('case', { title: '未知', input: '未知问题', expected: 'unknown', must: '说明未知', forbid: '补造' });
  const item = store.state.cases[0]; store.dispatch('case-review', { id: item.id }); store.dispatch('case-evaluate', { id: item.id });
  const evaluatedRevision = store.currentAgent().revision; assert.equal(item.result, 'pass');
  store.dispatch('update-config', { path: 'handoff.phrases', value: ['未知问题'] });
  assert.equal(item.result, null); assert.equal(item.stale, true); assert.deepEqual(item.lastResult, { result: 'pass', revision: evaluatedRevision });
  store.dispatch('case-evaluate', { id: item.id }); assert.equal(item.result, 'fail'); assert.equal(item.stale, false);
});
test('损坏存储不被通知消失/编辑/退出保存覆盖，显式恢复先备份原文', () => {
  const raw = JSON.stringify({ schema: 0, important: '原始人工资料（虚构）' });
  const memory = new Map([[STORAGE_KEY, raw]]); const storage = { getItem: key => memory.get(key), setItem: (key, value) => memory.set(key, value) };
  const store = createStore(storage); store.dispatch('dismiss-toast'); store.dispatch('navigate', { page: 'configuration' }); store.dispatch('update-config', { path: 'greeting', value: '内存草稿' }); store.save();
  assert.equal(memory.get(STORAGE_KEY), raw);
  store.dispatch('save-now'); assert.equal(memory.get(store.state.ui.recoveryKey), raw);
  assert.equal(JSON.parse(memory.get(STORAGE_KEY)).schema, 1);
});
test('删除中间字段后留空自动标识仍能继续人工创建', () => {
  const store = fresh(); store.dispatch('field', { label: '姓名' }); store.dispatch('field', { label: '电话' });
  const agent = store.currentAgent(); const removed = agent.config.fields[0].id; store.dispatch('field-remove', { id: removed });
  assert.equal(store.dispatch('field', { label: '时间' }).ok, true);
  assert.equal(new Set(agent.config.fields.map(field => field.id)).size, 2);
  assert.equal(agent.config.fields.some(field => field.id === removed), false);
});
test('文件选择信息在完成/修订时清空，不污染另一条文本资料', () => {
  const store = fresh(); store.dispatch('file-selected', { body: '已读取的文本', meta: { name: 'first.txt', metadataOnly: false } });
  store.dispatch('source', { ...faq, type: 'File', title: 'first.txt', filename: 'first.txt', body: '已读取的文本' });
  const original = store.currentAgent().config.sources.at(-1); assert.equal(store.state.ui.sourceFileMeta, null);
  store.dispatch('file-selected', { body: '', meta: { name: 'later.pdf', metadataOnly: true } });
  store.dispatch('source', { ...faq, type: 'File', title: 'later.pdf', filename: 'later.pdf', metadataOnly: true });
  store.dispatch('source-edit', { id: original.id });
  assert.equal(store.state.ui.sourceFileMeta, null);
  store.dispatch('source', { ...original, id: original.id, body: '修订文本' });
  assert.equal(original.filename, 'first.txt'); assert.equal(original.metadataOnly, false); assert.equal(original.body, '修订文本');
});
test('行级回放不评另一条案例，草稿案例不能借别人的审定结果', () => {
  const store = fresh();
  store.dispatch('case', { title: '已审', input: '未知', expected: 'unknown', must: '说明未知', forbid: '补造' }); const reviewed = store.state.cases[0];
  store.dispatch('case-review', { id: reviewed.id });
  store.dispatch('case', { title: '未审', input: '另一个问题', expected: 'unknown', must: '说明未知', forbid: '补造' }); const draft = store.state.cases[0];
  assert.equal(store.dispatch('case-evaluate', { id: draft.id }).ok, false); assert.equal(reviewed.result, null);
  store.dispatch('case-evaluate', { id: reviewed.id }); assert.equal(reviewed.result, 'pass'); assert.equal(draft.result, null);
});
test('受限Agent任务摘要只有目标/来源元数据，不含全文或客户会话', () => {
  const store = fresh(); const agent = store.currentAgent(); agent.config.sources[0].body = '不可复制的原文'; agent.conversations[0].messages[0].text = '不可复制的客户会话';
  const task = prepareAgentTask(agent); const encoded = JSON.stringify(task);
  assert.equal(task.target.baseRevision, agent.revision); assert.ok(task.sources.length > 0);
  assert.equal(encoded.includes('不可复制'), false); assert.equal(encoded.includes('MCP/Skills 桥接尚未接入'), true);
});
test('切换专家清除已选文件上下文，旧内容不会作为新对象默认资料', () => {
  const store = fresh(); store.dispatch('file-selected', { body: '旧专家文本', meta: { name: 'old.txt', metadataOnly: false } });
  store.dispatch('create', { name: '另一客服' });
  assert.equal(store.state.ui.sourceFileMeta, null); assert.equal(store.state.ui.sourceFileBody, ''); assert.equal(store.state.ui.sourceForm, false);
});
test('案例真值变更使候选比较待重验，不能沿用旧通过证据', () => {
  const store = fresh(); store.dispatch('case', { title: '资料外', input: '未知问题', expected: 'unknown', must: '说明未知', forbid: '补造' });
  const item = store.state.cases[0]; store.dispatch('case-review', { id: item.id });
  store.dispatch('proposal', { title: '回复', reason: '澄清出口', path: 'fallback', after: '请人工核实。' }); const proposal = store.state.proposals[0];
  store.dispatch('proposal-evaluate', { id: proposal.id }); assert.equal(proposal.evaluation, 'pass');
  store.dispatch('case', { ...item, expected: 'answered' });
  assert.equal(proposal.evaluation, null); assert.equal(proposal.stale, true);
  assert.equal(store.dispatch('proposal-apply', { id: proposal.id }).ok, false);
});
test('人工采用提案按真实差异字段保护与留证，不记录虚构proposal字段', () => {
  const store = fresh(); const agent = store.currentAgent(); const before = agent.config.fallback;
  store.dispatch('case', { title: '资料外', input: '未知问题', expected: 'unknown', must: '说明未知', forbid: '补造' }); store.dispatch('case-review', { id: store.state.cases[0].id });
  store.dispatch('proposal', { title: '人工回复', reason: '人工确定的新口径', path: 'fallback', after: '这是人工决定的未知回复。' });
  const proposal = store.state.proposals[0]; store.dispatch('proposal-evaluate', { id: proposal.id }); store.dispatch('proposal-apply', { id: proposal.id });
  assert.equal(agent.manualPaths.fallback.origin, '人工修改');
  assert.equal(agent.changeLog[0].path, 'fallback'); assert.equal(agent.changeLog[0].before, before); assert.equal(agent.changeLog[0].after, '这是人工决定的未知回复。');
  assert.match(agent.changeLog[0].source, /人工采用提案/);
  store.dispatch('assistant-generate', { scope: 'handoff' }); assert.equal(store.state.ui.assistant.suggestions.find(item => item.path === 'fallback').blocked, true);
});

 test('损坏物料条目走原文恢复路径，页面可初始化且暂停覆盖保存', () => {
  for (const materials of [[null], [{ id: 'broken', filename: 'broken.png', variants: {} }], [{ id: 'broken', filename: 'broken.png', variants: [null] }], { invalid: true }]) {
    const seed = initialState(); seed.materials = materials;
    const raw = JSON.stringify(seed); const memory = new Map([[STORAGE_KEY, raw]]);
    const storage = { getItem: key => memory.get(key), setItem: (key, value) => memory.set(key, value) };
    const store = createStore(storage);
    assert.match(store.state.ui.toast.text, /原文已保留/);
    assert.equal(store.state.ui.saveStatus, 'error');
    assert.deepEqual(store.state.materials, []);
    store.dispatch('update-config', { path: 'greeting', value: '恢复示例编辑' });
    assert.equal(memory.get(STORAGE_KEY), raw);
  }
});

test('损坏访客消息保留原文，不用空对话静默覆盖历史', () => {
  for (const key of ['trialMessages', 'widgetTrialMessages']) {
    const seed = initialState(); seed.ui[key] = { malformed: '保留原始记录' };
    const raw = JSON.stringify(seed); const memory = new Map([[STORAGE_KEY, raw]]);
    const storage = { getItem: name => memory.get(name), setItem: (name, value) => memory.set(name, value) };
    const store = createStore(storage);
    assert.equal(store.state.ui.saveStatus, 'error');
    assert.match(store.state.ui.toast.text, /原文已保留/);
    store.dispatch('update-config', { path: 'greeting', value: '只编辑恢复示例' });
    assert.equal(memory.get(STORAGE_KEY), raw);
  }
});
