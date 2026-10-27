import test from 'node:test';
import assert from 'node:assert/strict';
import { createStore, STORAGE_KEY } from '../store.js';
import { initialState } from '../fixtures.js';
import * as domain from '../domain.js';
import { renderShell } from '../views/shell.js';
import { renderAgents, renderOverview } from '../views/editor.js';
import * as panels from '../views/config-panels.js';
import * as pages from '../views/config-pages.js';

const context = store => ({ state: store.state, agent: store.currentAgent(), ready: domain.readiness(store.currentAgent(), store.state.connections), readonly: store.readonly() });

test('config validation reports stable paths and pending items share one source', () => {
  const store = createStore();
  store.dispatch('update-config', { path: 'model.budget', value: 0 });
  const issues = domain.validateConfig(store.currentAgent().config);
  assert.ok(issues.some(issue => issue.path === 'model.budget' && issue.message));
  assert.equal(typeof domain.pendingItems, 'function');
  const pending = domain.pendingItems(store.currentAgent(), store.state);
  assert.ok(pending.some(item => item.page === 'settings' && item.level === 'block' && item.target === 'model.budget'));
  assert.ok(pending.every(item => item.id && item.fix && item.text));
  const count = pending.length;
  store.dispatch('navigate', { page: 'overview' });
  const shell = renderShell(context(store), '');
  assert.match(shell, new RegExp(`待处理 ${count}`));
  assert.match(renderAgents(context(store)), /模型预算/);
  assert.match(renderOverview(context(store)), /模型预算/);
});

test('selected expert has seven flat entries, settings and global trial', () => {
  const store = createStore();
  store.dispatch('navigate', { page: 'overview' });
  const html = renderShell(context(store), '');
  for (const label of ['首页', '知识库', '红线', '业务办理', '对话流程', '测试', '上线', '设置', '试一试']) assert.match(html, new RegExp(label));
  assert.equal((html.match(/class="nav-link"/g) || []).length, 8);
  assert.doesNotMatch(html, /配置深度|业务配置|详细配置|保存草稿/);
  assert.match(html, /已自动保存/);
});

test('new expert lands on a three-step intake without configuration form', () => {
  const store = createStore();
  store.dispatch('create', { name: '新专家' });
  assert.equal(store.state.ui.page, 'overview');
  const html = renderOverview(context(store));
  for (const label of ['放资料', '核对', '试一试', '选择文件', '从示例模板开始', '导入']) assert.match(html, new RegExp(label));
  assert.doesNotMatch(html, /data-bind="goal"/);
});

test('quick trial opens on every primary page and wrong answer enters the shared queue', () => {
  const store = createStore();
  for (const page of ['overview', 'knowledge', 'redlines', 'business', 'flow', 'test', 'versions']) {
    store.dispatch('navigate', { page });
    assert.equal(store.dispatch('open-trial', { question: '退费要多久？' }).ok, true);
    assert.equal(store.state.ui.page, page);
    assert.equal(store.state.ui.sidePanel, 'trial');
    assert.equal(store.state.ui.trialInput, '退费要多久？');
  }
  const count = domain.pendingItems(store.currentAgent(), store.state).length;
  assert.equal(store.dispatch('trial-feedback', { question: '退费要多久？', answer: '不知道', verdict: 'wrong' }).ok, true);
  assert.equal(domain.pendingItems(store.currentAgent(), store.state).length, count + 1);
  assert.equal(store.dispatch('feedback-to-case', { id: store.state.feedback[0].id }).ok, true);
  assert.equal(store.state.cases[0].status, 'draft');
});

test('batch intake keeps rights unselected and risks pending until human review', () => {
  const store = createStore();
  store.dispatch('create', { name: '资料审核' });
  const candidates = [
    { id: 'q1', kind: 'qa', question: '多少钱？', answer: '3980 元' },
    { id: 'q2', kind: 'qa', question: '什么时候上课？', answer: '星期二晚' },
  ];
  assert.equal(store.dispatch('batch-intake', { title: '价格.csv', candidates }).ok, true);
  const source = store.currentAgent().config.sources[0];
  assert.equal(source.rights, false);
  assert.equal(store.currentAgent().config.qaItems.length, 2);
  assert.equal(store.currentAgent().config.qaItems[0].reviewStatus, 'pending');
  assert.equal(store.state.ui.knowledgeTab, 'review');
  assert.ok(domain.pendingItems(store.currentAgent(), store.state).some(item => item.id.startsWith('rights:')));
  assert.ok(domain.pendingItems(store.currentAgent(), store.state).some(item => item.id.startsWith('review:')));
});

test('risk review stays separate from low-risk bulk confirmation and can be undone', () => {
  const store = createStore();
  store.dispatch('create', { name: '资料核对' });
  store.dispatch('batch-intake', { title: '政策.txt', candidates: [
    { kind: 'qa', question: '多少钱？', answer: '3980 元' },
    { kind: 'qa', question: '怎么联系？', answer: '可通过网站留言' },
  ] });
  const agent = store.currentAgent(), sourceId = agent.config.sources[0].id;
  assert.equal(store.dispatch('qa-low-confirm', { sourceId }).ok, true);
  assert.equal(agent.config.qaItems[0].reviewStatus, 'pending');
  assert.equal(agent.config.qaItems[1].reviewStatus, 'reviewed');
  assert.equal(store.dispatch('undo-batch').ok, true);
  assert.equal(agent.config.qaItems[1].reviewStatus, 'pending');
});

test('a reviewed conflicting answer requires a human winner and unchosen answer stops matching', () => {
  const store = createStore(), agent = store.currentAgent();
  const current = agent.config.sources.find(source => source.question === '什么时候上课？');
  store.dispatch('batch-intake', { title: '新课表.csv', rights: true, sourceRef: '授权课表', expires: '2027-12-31', candidates: [{ kind: 'qa', question: current.question, answer: '每周三晚开课' }] });
  const candidate = agent.config.qaItems[0];
  assert.ok(domain.pendingItems(agent, store.state).some(item => item.id.startsWith('review:')));
  assert.equal(store.dispatch('qa-save', { id: candidate.id, choice: 'candidate' }).ok, true);
  assert.equal(agent.config.sources.find(source => source.id === current.id).status, 'review');
  assert.equal(agent.config.qaItems[0].reviewStatus, 'reviewed');
  assert.equal(domain.simulateReply(agent.config, current.question, agent.revokedSourceIds || []).text, '每周三晚开课');
});

test('reviewed batch becomes usable only after explicit source authorization', () => {
  const store = createStore();
  store.dispatch('create', { name: '授权核对' });
  store.dispatch('batch-intake', { title: '课程.csv', candidates: [{ kind: 'qa', question: '在哪里上课？', answer: '线上教室' }] });
  const source = store.currentAgent().config.sources[0], qa = store.currentAgent().config.qaItems[0];
  store.dispatch('qa-decision', { id: qa.id, decision: 'approve' });
  assert.equal(source.status, 'review');
  assert.equal(store.dispatch('source-stage', { id: source.id, stage: 'indexed' }).ok, false);
  assert.equal(store.dispatch('source', { id: source.id, type: 'File', title: source.title, rights: 'on', sourceRef: '自有课程政策', expires: '2027-12-31' }).ok, true);
  assert.equal(source.status, 'indexed');
  assert.equal(domain.simulateReply(store.currentAgent().config, qa.question).text, qa.answer);
});

test('cross-batch same-question disagreement blocks trial and enters human review choice', async () => {
  const store = createStore(), agent = store.currentAgent();
  const old = agent.config.sources.find(source => source.question === '可以退款吗？');
  old.question = '课程多少钱？'; old.answer = '3980 元';
  store.dispatch('batch-intake', { title: '新价格.csv', rights: true, sourceRef: '新价格表', expires: '2027-12-31', candidates: [{ kind: 'qa', question: '课程多少钱？', answer: '4280 元' }] });
  const candidate = agent.config.qaItems.at(-1);
  assert.ok(domain.pendingItems(agent, store.state).some(item => item.id.startsWith('knowledge:conflict:')));
  assert.equal(domain.simulateReply(agent.config, candidate.question).status, 'unknown');
  const { renderKnowledge } = await import('../views/knowledge.js');
  assert.match(renderKnowledge({ state: store.state, agent, ready: {}, readonly: false }), /和已有资料说法不一致：3980 元/);
  assert.equal(store.dispatch('qa-save', { id: candidate.id, choice: 'candidate' }).ok, true);
  assert.equal(domain.simulateReply(agent.config, candidate.question).text, '4280 元');
  assert.ok(agent.config.sources.some(item => item.id === old.id));
  assert.equal(old.rights, true);
});

test('a legacy FAQ marked not for AI stops answering without deleting its source', () => {
  const store = createStore(), agent = store.currentAgent();
  const source = agent.config.sources.find(item => item.type === 'FAQ');
  assert.equal(store.dispatch('qa-decision', { id: `qa-${source.id}`, decision: 'no-answer' }).ok, true);
  assert.equal(source.status, 'review');
  assert.equal(agent.config.qaItems.find(item => item.sourceId === source.id)?.reviewStatus, 'rejected');
  assert.notEqual(domain.simulateReply(agent.config, source.question).text, source.answer);
});

test('changing a key fact resolves selected references and preserves excluded ones', () => {
  const store = createStore(), agent = store.currentAgent();
  agent.config.keyFacts.push({ id: 'price', name: '课程价格', value: '3980', unit: '元', sourceRef: '价格表' });
  agent.config.qaItems.push({ id: 'qa-a', question: '现在多少钱？', answer: '{课程价格}', reviewStatus: 'reviewed' });
  agent.config.qaItems.push({ id: 'qa-b', question: '旧优惠多少钱？', answer: '{课程价格}', reviewStatus: 'reviewed' });
  assert.equal(store.dispatch('fact-save', { id: 'price', name: '课程价格', value: '4280', unit: '元', sourceRef: '新价格表', excluded: ['qa:qa-b'] }).ok, true);
  assert.equal(agent.config.qaItems[0].answer, '{课程价格}');
  assert.equal(agent.config.qaItems[1].answer, '3980 元');
  assert.equal(store.dispatch('undo-batch').ok, true);
  assert.equal(agent.config.keyFacts[0].value, '3980');
  assert.equal(agent.config.qaItems[1].answer, '{课程价格}');
});

test('renaming a key fact updates included placeholders and freezes excluded references', () => {
  const store = createStore(), agent = store.currentAgent();
  agent.config.keyFacts.push({ id: 'price', name: '旧价格', value: '3980', unit: '元', sourceRef: '价格表' });
  agent.config.qaItems.push({ id: 'included', question: '现价？', answer: '{旧价格}', reviewStatus: 'reviewed' });
  agent.config.qaItems.push({ id: 'excluded', question: '旧价？', answer: '{旧价格}', reviewStatus: 'reviewed' });
  assert.equal(store.dispatch('fact-save', { id: 'price', name: '课程价格', value: '4280', unit: '元', sourceRef: '新表', excluded: ['qa:excluded'] }).ok, true);
  assert.equal(agent.config.qaItems[0].answer, '{课程价格}');
  assert.equal(agent.config.qaItems[1].answer, '3980 元');
});

test('business redlines are editable and platform rules remain immutable', () => {
  const store = createStore(), agent = store.currentAgent();
  const frozen = JSON.stringify(agent.config.rules);
  assert.equal(store.dispatch('rule-template', { template: 'complaint' }).ok, true);
  const rule = agent.config.businessRules.find(item => item.id === store.state.ui.ruleEditId);
  assert.equal(rule.action, 'handoff');
  assert.equal(store.dispatch('rule-save', { id: rule.id, field: '客户情绪', operator: 'is', value: '投诉', action: 'handoff', recipient: '售后组', sourceRef: '客服政策' }).ok, true);
  assert.equal(agent.config.businessRules.find(item => item.id === rule.id).recipient, '售后组');
  assert.equal(store.dispatch('rule-toggle', { id: agent.config.rules[0].id }).ok, false);
  assert.equal(JSON.stringify(agent.config.rules), frozen);
});

test('legacy handoff phrases appear as editable business redlines after load', () => {
  const store = createStore(), agent = store.currentAgent();
  const rule = agent.config.businessRules.find(item => item.legacyHandoff);
  assert.ok(rule);
  assert.equal(rule.action, 'handoff');
  assert.equal(rule.condition.value, agent.config.handoff.phrases[0]);
  assert.equal(rule.recipient, agent.config.handoff.recipient);
});

test('legacy handoff migration is idempotent across persisted reloads', () => {
  const first = createStore();
  const count = first.currentAgent().config.businessRules.filter(item => item.legacyHandoff).length;
  const second = createStore(null, JSON.parse(JSON.stringify(first.state)));
  assert.equal(second.currentAgent().config.businessRules.filter(item => item.legacyHandoff).length, count);
});

test('zero-hit business rules appear as suggest items from recent local runs', () => {
  const store = createStore(), agent = store.currentAgent();
  agent.config.businessRules.push({ id: 'quiet-rule', title: '没有价格不报价', condition: { value: '价格' }, action: 'refuse', enabled: true });
  assert.ok(domain.pendingItems(agent, store.state).some(item => item.id === 'rule-unused:quiet-rule' && item.level === 'suggest'));
  store.state.runs.unshift({ id: 'rule-run', agentId: agent.id, createdAt: new Date().toISOString(), ruleHits: ['quiet-rule'] });
  assert.equal(domain.pendingItems(agent, store.state).some(item => item.id === 'rule-unused:quiet-rule'), false);
});

test('expired bulk undo is rejected by the state layer', () => {
  const store = createStore(), agent = store.currentAgent();
  store.dispatch('batch-intake', { title: '政策.txt', candidates: [{ kind: 'qa', question: '怎么联系？', answer: '网站留言' }] });
  store.dispatch('qa-low-confirm', { sourceId: agent.config.sources.at(-1).id });
  store.state.ui.undoBatch.expiresAt = Date.now() - 1;
  assert.equal(store.dispatch('undo-batch').ok, false);
});

test('bulk undo never overwrites a later edit', () => {
  const store = createStore(), agent = store.currentAgent();
  store.dispatch('fact-save', { name: '学费', value: '3980', sourceRef: '授权价格表' });
  store.dispatch('update-config', { path: 'greeting', value: '后来人工填写的欢迎语' });
  assert.equal(store.dispatch('undo-batch').ok, false);
  assert.equal(agent.config.greeting, '后来人工填写的欢迎语');
  assert.equal(agent.config.keyFacts[0].value, '3980');
});

test('old local drafts are backed up before migration, without rewriting frozen versions', () => {
  const old = initialState();
  delete old.configurationUiVersion;
  const frozen = JSON.stringify(old.agents[0].versions);
  const raw = JSON.stringify(old), memory = new Map([[STORAGE_KEY, raw]]);
  const storage = { getItem: key => memory.get(key), setItem: (key, value) => memory.set(key, value) };
  const store = createStore(storage);
  store.save();
  assert.equal(memory.get(`${STORAGE_KEY}:before-config-ui-v2`), raw);
  assert.equal(JSON.stringify(store.currentAgent().versions), frozen);
  assert.equal(JSON.parse(memory.get(STORAGE_KEY)).configurationUiVersion, 2);
  const backup = memory.get(`${STORAGE_KEY}:before-config-ui-v2`);
  createStore(storage).save();
  assert.equal(memory.get(`${STORAGE_KEY}:before-config-ui-v2`), backup);
});

test('a failed migration backup leaves the old storage untouched until a retry succeeds', () => {
  const raw = JSON.stringify(initialState()), memory = new Map([[STORAGE_KEY, raw]]);
  let rejectBackup = true;
  const store = createStore({ getItem: key => memory.get(key), setItem(key, value) { if (rejectBackup && key !== STORAGE_KEY) throw new Error('quota'); memory.set(key, value); } });
  store.dispatch('update-config', { path: 'greeting', value: '内存中继续编辑' });
  assert.equal(memory.get(STORAGE_KEY), raw);
  assert.equal(store.state.ui.saveStatus, 'error');
  rejectBackup = false;
  assert.equal(store.dispatch('save-now').ok, true);
  assert.equal(memory.get(`${STORAGE_KEY}:before-config-ui-v2`), raw);
  assert.equal(JSON.parse(memory.get(STORAGE_KEY)).agents[0].config.greeting, '内存中继续编辑');
});

test('quick trial uses reviewed answers, current facts and business redlines', () => {
  const store = createStore(), agent = store.currentAgent();
  agent.config.keyFacts.push({ id: 'fee', name: '课程价格', value: '4280', unit: '元', sourceRef: '已核价格表' });
  agent.config.qaItems.push({ id: 'qa-price', question: '课程多少钱？', answer: '当前是{课程价格}。', sourceId: agent.config.sources[0].id, reviewStatus: 'reviewed' });
  assert.equal(store.dispatch('quick-trial', { question: '课程多少钱？' }).ok, true);
  assert.match(store.state.ui.quickTrial.answer, /4280 元/);
  assert.equal(store.state.runs[0].agentId, agent.id);
  store.dispatch('rule-save', { field: '客户情绪', operator: 'is', value: '投诉', action: 'handoff', recipient: '售后组', sourceRef: '接待规则' });
  assert.equal(store.dispatch('quick-trial', { question: '我要投诉' }).ok, true);
  assert.match(store.state.ui.quickTrial.answer, /售后组/);
  assert.ok(store.state.ui.quickTrial.ruleHits.length);
});

test('one shared side panel has a single answer and five evidence questions', () => {
  const store = createStore();
  store.dispatch('quick-trial', { question: '什么时候上课？' });
  const trial = panels.renderQuickTrial(context(store));
  assert.match(trial, /data-form="quick-trial"/);
  assert.match(trial, /答错了/);
  assert.match(trial, /看完整对话/);
  store.dispatch('open-evidence', { kind: 'qa', id: 'qa-source-schedule' });
  const evidence = panels.renderEvidencePanel(context(store));
  for (const heading of ['从哪来', '哪一版', '谁改的', '影响谁', '凭什么', '技术详情']) assert.match(evidence, new RegExp(heading));
});

test('business page keeps outcome, confirmation and technical details on one action', () => {
  const store = createStore();
  store.dispatch('tool', { title: '创建试听预约', sideEffect: 'write' });
  const html = pages.renderBusiness(context(store));
  for (const label of ['要问客户', '需客户确认', '办成标志', '办不成时', '结果不明时', '技术详情']) assert.match(html, new RegExp(label));
  assert.match(html, /data-bind="tools\.0\.successField"/);
  assert.match(html, /data-bind="tools\.0\.requiresConfirm"[^>]*disabled/);
});

test('business try records separate local outcomes and no external result id', () => {
  const store = createStore(), agent = store.currentAgent();
  store.dispatch('tool', { title: '创建试听预约', sideEffect: 'write', successField: '预约号' });
  const tool = agent.config.tools[0];
  assert.equal(store.dispatch('business-try', { id: tool.id }).ok, true);
  assert.match(pages.renderBusiness(context(store)), /data-form="business-try-run"/);
  for (const result of ['success', 'failed', 'unknown']) assert.equal(store.dispatch('business-try-run', { id: tool.id, businessStatus: result }).ok, true);
  assert.deepEqual(store.state.runs.slice(0, 3).map(run => run.businessStatus).sort(), ['failed', 'success', 'unknown']);
  assert.ok(store.state.runs.slice(0, 3).every(run => run.resultEvidence.externalResultId === null));
  assert.match(pages.renderBusiness(context(store)), /成功 1 · 失败 1 · 结果不明 1/);
});

test('expert settings keep expert configuration and return to workspace resources', () => {
  const html = pages.renderSettings(context(createStore()));
  for (const page of ['agents', 'configuration']) assert.match(html, new RegExp(`data-page="${page}"`));
  assert.match(html, /专家设置[\s\S]*这些设置仅用于当前专家/);
  assert.doesNotMatch(html, /data-page="(?:materials|connections|deployment)"/);
  assert.doesNotMatch(html, /配置深度|role="tab"/);
});

test('regressed test needs a decision and an outdated truth returns to human review', () => {
  const store = createStore(), agent = store.currentAgent();
  store.dispatch('case', { title: '问退款', input: '能退款吗？', expected: 'answered', must: '给出依据', forbid: '补造承诺' });
  const item = store.state.cases[0];
  store.dispatch('case-review', { id: item.id });
  assert.equal(store.dispatch('case-evaluate', { id: item.id }).ok, true);
  assert.equal(item.result, 'fail');
  assert.equal(item.history.length, 1);
  assert.ok(domain.pendingItems(agent, store.state).some(entry => entry.id === `case:${item.id}`));
  assert.equal(store.dispatch('case-decide', { id: item.id, decision: 'outdated' }).ok, true);
  assert.equal(item.status, 'draft');
  assert.equal(item.expected, item.lastObserved.status);
  assert.ok(item.truthHistory.length);
});

test('answer-wrong release block survives config edits until a passing rerun', () => {
  const store = createStore(), agent = store.currentAgent();
  store.dispatch('case', { title: '价格问答', input: '多少钱？', expected: 'answered', must: '按资料回答', forbid: '编造优惠' });
  const item = store.state.cases[0];
  store.dispatch('case-review', { id: item.id }); store.dispatch('case-evaluate', { id: item.id });
  store.dispatch('case-decide', { id: item.id, decision: 'wrong' });
  assert.equal(store.dispatch('sandbox-deploy').ok, false);
  store.dispatch('update-config', { path: 'greeting', value: '改过欢迎语' });
  assert.equal(item.result, null);
  assert.equal(item.decision, 'wrong');
  assert.ok(domain.pendingItems(agent, store.state).some(entry => entry.id === `case:${item.id}`));
  assert.equal(store.dispatch('sandbox-deploy').ok, false);
  store.dispatch('source', { type: 'FAQ', title: '授权价格', question: '多少钱？', answer: '3980 元', rights: true, sourceRef: '原创价格表', expires: '2027-12-31' });
  const source = agent.config.sources.at(-1);
  store.dispatch('source-stage', { id: source.id, stage: 'indexed' });
  assert.equal(store.dispatch('case-evaluate', { id: item.id }).ok, true);
  assert.equal(item.result, 'pass');
  assert.equal(item.decision, 'pass');
  assert.equal(domain.pendingItems(agent, store.state).some(entry => entry.id === `case:${item.id}`), false);
});

test('test environment and release approval keep distinct versions; rollback does not touch draft', () => {
  const store = createStore(), agent = store.currentAgent();
  store.dispatch('case', { title: '课程内容', input: '数据分析课程学什么？', expected: 'answered', must: '依据已审资料回答', forbid: '补造未证实内容' });
  const checkCase = store.state.cases[0];
  store.dispatch('case-review', { id: checkCase.id });
  assert.equal(store.dispatch('sandbox-deploy').ok, true);
  assert.equal(checkCase.result, 'pass');
  assert.equal(agent.versions[0].status, 'sandbox');
  assert.equal(store.dispatch('release-request').ok, true);
  assert.equal(agent.bindings.widget, 'v1');
  assert.equal(store.dispatch('release-approve').ok, true);
  const newer = agent.bindings.widget;
  assert.notEqual(newer, 'v1');
  const revision = agent.revision;
  assert.equal(store.dispatch('release-rollback').ok, true);
  assert.equal(agent.bindings.widget, 'v1');
  assert.equal(agent.revision, revision);
});

test('test environment does not claim tests passed without a reviewed suite', () => {
  const store = createStore(), agent = store.currentAgent();
  assert.equal(store.dispatch('sandbox-deploy').ok, false);
  assert.notEqual(agent.checks.testedRevision, agent.revision);
  assert.equal(store.dispatch('release-request').ok, false);
});

test('test and release pages expose decisions and the same pending count', () => {
  const store = createStore(), agent = store.currentAgent();
  store.dispatch('case', { title: '价格问答', input: '多少钱？', expected: 'answered', must: '回答有依据', forbid: '不补造优惠' });
  const item = store.state.cases[0];
  store.dispatch('case-review', { id: item.id });
  store.dispatch('case-evaluate', { id: item.id });
  store.dispatch('test-open', { id: item.id });
  const testPage = pages.renderTest(context(store));
  for (const label of ['测试题', '最近 5 次', '输入', '期望', '这次答', '答案错了', '测试题过时了']) assert.match(testPage, new RegExp(label));
  const release = pages.renderRelease(context(store));
  const count = domain.pendingItems(agent, store.state).length;
  assert.match(release, new RegExp(`待处理 ${count}`));
  assert.match(release, /发到测试环境/);
  assert.match(release, /申请上线/);
  assert.match(release, /回到上一线上版/);
  assert.doesNotMatch(release, /保存草稿|运行沙盒检查/);
});

test('fact review approves, corrects and resolves a changed value before answering', () => {
  const store = createStore();
  store.dispatch('create', { name: '关键信息核对' });
  const agent = store.currentAgent();
  const intake = value => store.dispatch('batch-intake', { title: '学费.csv', sourceRef: '原创价格表', rights: true, expires: '2027-12-31', candidates: [{ kind: 'fact', name: '学费', value, unit: '元' }] });
  intake('3980');
  const old = agent.config.keyFacts[0];
  assert.equal(store.dispatch('fact-decision', { id: old.id, decision: 'approve' }).ok, true);
  assert.equal(agent.config.sources[0].status, 'indexed');
  intake('4980');
  const candidate = agent.config.keyFacts[1];
  assert.equal(store.dispatch('fact-decision', { id: candidate.id, decision: 'approve' }).ok, false);
  assert.ok(domain.pendingItems(agent, store.state).some(item => item.id.startsWith('knowledge:conflict:fact:')));
  store.dispatch('fact-edit', { id: candidate.id, review: true });
  assert.equal(store.state.ui.knowledgeTab, 'review');
  assert.equal(store.dispatch('fact-save', { id: candidate.id, name: '学费', value: '5080', unit: '元', sourceRef: '原创价格表', review: true }).ok, true);
  assert.equal(candidate.reviewStatus, 'pending');
  assert.equal(store.dispatch('fact-decision', { id: candidate.id, conflictId: old.id, choice: 'candidate' }).ok, true);
  assert.equal(old.reviewStatus, 'rejected');
  assert.equal(candidate.reviewStatus, 'reviewed');
  assert.equal(domain.pendingItems(agent, store.state).some(item => item.id.startsWith('knowledge:conflict:fact:')), false);
});

test('normalized conflicts need one explicit winner across every disagreeing batch', () => {
  const store = createStore();
  store.dispatch('create', { name: '多批资料' });
  const agent = store.currentAgent();
  for (const [question, answer] of [['课程 时间？', '周一'], ['课程时间?', '周二'], ['课程时间！', '周三']]) {
    store.dispatch('batch-intake', { title: '课表.csv', sourceRef: '原创课表', rights: true, expires: '2027-12-31', candidates: [{ kind: 'qa', question, answer }] });
  }
  assert.equal(store.dispatch('qa-decision', { id: agent.config.qaItems[0].id, decision: 'approve' }).ok, true);
  const candidate = agent.config.qaItems[2];
  assert.equal(store.dispatch('qa-decision', { id: candidate.id, decision: 'approve' }).ok, false);
  assert.equal(store.dispatch('qa-save', { id: candidate.id, choice: 'candidate' }).ok, true);
  assert.deepEqual(agent.config.qaItems.map(item => item.reviewStatus), ['rejected', 'rejected', 'reviewed']);
  assert.equal(domain.simulateReply(agent.config, '课程时间？').text, '周三');
});

test('local redline conditions distinguish fields, equality, amounts and missing prices', () => {
  const store = createStore(); store.dispatch('create', { name: '红线语义' });
  const config = store.currentAgent().config;
  store.dispatch('rule-template', { template: 'no-price' });
  const priceRule = config.businessRules.at(-1);
  assert.deepEqual(domain.simulateReply(config, '在哪里上课？').ruleHits, []);
  assert.deepEqual(domain.simulateReply(config, '请问多少钱？').ruleHits, [priceRule.id]);
  store.dispatch('fact-save', { name: '学费', value: '3980', unit: '元', sourceRef: '原创价格表' });
  assert.deepEqual(domain.simulateReply(config, '请问多少钱？').ruleHits, []);
  store.dispatch('rule-save', { field: '客户说了', operator: 'is', value: '投诉', action: 'handoff' });
  assert.deepEqual(domain.simulateReply(config, '我投诉服务').ruleHits, []);
  store.dispatch('rule-save', { field: '客户说了', operator: 'contains', value: '投诉', action: 'handoff' });
  assert.equal(domain.simulateReply(config, '我投诉服务').status, 'handoff');
  store.dispatch('rule-template', { template: 'high-price' });
  assert.deepEqual(domain.simulateReply(config, '编号 6000 的教室在哪里？').ruleHits, []);
  assert.equal(domain.simulateReply(config, '报价 6000 元是否可以？').ruleHits[0], config.businessRules.at(-1).id);
});

test('pending actions select the exact case, setting and expert next step', () => {
  const store = createStore(), agent = store.currentAgent();
  store.dispatch('update-config', { path: 'model.budget', value: 0 });
  store.dispatch('agent-next', { id: agent.id });
  assert.equal(store.state.ui.page, 'settings');
  assert.equal(store.state.ui.focusTarget, 'model.budget');
  store.dispatch('case', { title: '变差题', input: '未知问法', expected: 'answered', must: '有依据', forbid: '编造' });
  const item = store.state.cases[0];
  store.dispatch('case-review', { id: item.id }); store.dispatch('case-evaluate', { id: item.id });
  store.dispatch('pending-open', { id: `case:${item.id}` });
  assert.equal(store.state.ui.testDetailId, item.id);
  assert.equal(store.state.ui.page, 'test');
});

test('legacy edits and graph edits keep the same description and protected stable step', () => {
  const store = createStore(), agent = store.currentAgent();
  store.dispatch('update-config', { path: 'flow.0.instruction', value: '人工确认的流程说明' });
  const step = agent.config.flow[0];
  const node = agent.config.routeGraph.nodes.find(item => item.legacyId === step.id);
  assert.equal(node.instruction, step.instruction);
  store.dispatch('flow-node-update', { id: node.id, title: '新步骤名', instruction: '流程图修改的同一份说明' });
  assert.equal(agent.config.flow[0].instruction, node.instruction);
  assert.equal(agent.config.flow[0].title, node.title);
  assert.ok(agent.manualPaths['flow.0.instruction']);
});

test('test truth edits invalidate an existing request before human approval', () => {
  const store = createStore();
  store.dispatch('case', { title: '课程', input: '数据分析课程学什么？', expected: 'answered', must: '资料内回答', forbid: '编造' });
  const item = store.state.cases[0]; store.dispatch('case-review', { id: item.id });
  assert.equal(store.dispatch('sandbox-deploy').ok, true);
  assert.equal(store.dispatch('release-request').ok, true);
  store.dispatch('case', { id: item.id, title: item.title, input: item.input, expected: 'unknown', must: '说明未知', forbid: '编造' });
  assert.equal(store.dispatch('release-approve').ok, false);
  assert.equal(store.dispatch('release-request').ok, false);
});

test('rejecting previously approved content cannot fall back to its original source body', () => {
  const store = createStore(), agent = store.currentAgent();
  const source = agent.config.sources.find(item => item.type === 'FAQ');
  const id = `qa-${source.id}`;
  store.dispatch('qa-decision', { id, decision: 'approve' });
  store.dispatch('qa-decision', { id, decision: 'no-answer' });
  assert.equal(domain.simulateReply(agent.config, source.question).status, 'unknown');
  store.dispatch('batch-intake', { title: '虚构政策.txt', body: '不能用于回答的退款保证', rights: true, sourceRef: '原创文本', expires: '2027-12-31', candidates: [{ kind: 'qa', question: '退款保证', answer: '不能用于回答的退款保证' }] });
  store.dispatch('qa-decision', { id: agent.config.qaItems.at(-1).id, decision: 'no-answer' });
  assert.equal(domain.simulateReply(agent.config, '退款保证').status, 'unknown');
});

test('disagreeing rows in one new batch cannot be accepted as a low-risk group', () => {
  const store = createStore(); store.dispatch('create', { name: '同批说法核对' });
  store.dispatch('batch-intake', { title: '课表.csv', candidates: [{ kind: 'qa', question: '上课时间', answer: '周一' }, { kind: 'qa', question: '上课时间？', answer: '周二' }] });
  const agent = store.currentAgent();
  assert.equal(store.dispatch('qa-low-confirm', { sourceId: agent.config.sources[0].id }).ok, false);
  assert.ok(agent.config.qaItems.every(item => item.reviewStatus === 'pending'));
  assert.equal(store.dispatch('qa-save', { id: agent.config.qaItems[1].id, choice: 'candidate' }).ok, true);
  assert.deepEqual(agent.config.qaItems.map(item => item.reviewStatus), ['rejected', 'reviewed']);
});

test('a missing or revoked model connection enters the queue and blocks final approval', () => {
  const store = createStore(), agent = store.currentAgent();
  store.dispatch('update-config', { path: 'model.connectionId', value: 'not-connected' });
  assert.ok(domain.pendingItems(agent, store.state).some(item => item.id === 'connection:ready'));
  assert.equal(store.dispatch('sandbox-deploy').ok, false);
  store.dispatch('pending-open', { id: 'connection:ready' });
  assert.equal(store.state.ui.section, 'model');
  store.dispatch('update-config', { path: 'model.connectionId', value: 'simulation' });
  store.dispatch('case', { title: '课程', input: '数据分析课程学什么？', expected: 'answered', must: '资料内回答', forbid: '编造' });
  store.dispatch('case-review', { id: store.state.cases[0].id });
  assert.equal(store.dispatch('sandbox-deploy').ok, true);
  assert.equal(store.dispatch('release-request').ok, true);
  const before = agent.bindings.widget;
  store.state.connections[0].status = 'failed';
  assert.equal(store.dispatch('release-approve').ok, false);
  assert.equal(agent.bindings.widget, before);
});

test('a disputed key fact blocks only the answers that reference it', () => {
  const store = createStore(), agent = store.currentAgent();
  store.dispatch('fact-save', { name: '学费', value: '3980', unit: '元', sourceRef: '原创价格表' });
  store.dispatch('source', { type: 'FAQ', title: '价格答复', question: '学费多少', answer: '学费是 {学费}', rights: true, sourceRef: '原创答复', expires: '2027-12-31' });
  store.dispatch('source-stage', { id: agent.config.sources.at(-1).id, stage: 'indexed' });
  store.dispatch('batch-intake', { title: '新价格.csv', sourceRef: '原创新价格', rights: true, expires: '2027-12-31', candidates: [{ kind: 'fact', name: '学费', value: '4280', unit: '元' }] });
  assert.equal(domain.simulateReply(agent.config, '学费多少').status, 'unknown');
  assert.equal(domain.simulateReply(agent.config, '数据分析课程学什么？').status, 'answered');
  store.dispatch('fact-decision', { id: agent.config.keyFacts.at(-1).id, choice: 'candidate' });
  assert.equal(domain.simulateReply(agent.config, '学费多少').text, '学费是 4280 元');
});

test('editing a graph step protects legacy suggestions and deletion retains the remaining chain', () => {
  const store = createStore(), agent = store.currentAgent();
  const node = agent.config.routeGraph.nodes.find(item => item.legacyId === agent.config.flow[0].id);
  store.dispatch('flow-node-update', { id: node.id, title: node.title, instruction: '人工确定的处理说明' });
  store.dispatch('assistant-generate', { scope: 'flow' });
  const suggestion = store.state.ui.assistant.suggestions.find(item => item.path === 'flow.0.instruction');
  assert.equal(suggestion.blocked, true);
  assert.equal(store.dispatch('assistant-accept', { id: suggestion.id }).ok, false);
  assert.equal(store.dispatch('flow-node-delete', { id: node.id }).ok, true);
  assert.equal(domain.pendingItems(agent, store.state).some(item => item.text.includes('没有从开始到达')), false);
});

test('incomplete edge edits save to the same graph; deleting a branch retains a removable step', () => {
  const store = createStore(), agent = store.currentAgent();
  store.dispatch('flow-branch', { intent: '问上课时间', examples: '什么时候上课/几点开课/上课日期', then: 'answer' });
  const graph = agent.config.routeGraph, edge = graph.edges.at(-1), target = edge.target;
  assert.equal(store.dispatch('flow-edge-update', { id: edge.id, label: '', examples: '仅一句' }).ok, true);
  assert.ok(domain.pendingItems(agent, store.state).some(item => item.id.startsWith('flow:')));
  store.dispatch('flow-filter', { id: edge.id });
  assert.equal(store.dispatch('flow-edge-delete', { id: edge.id }).ok, true);
  assert.equal(store.state.ui.flowBranchFilter, 'all');
  assert.ok(graph.nodes.some(item => item.id === target));
  assert.equal(store.dispatch('flow-node-delete', { id: target }).ok, true);
  store.state.ui.readonly = true;
  assert.equal(store.dispatch('flow-edge-update', { id: graph.edges[0].id, label: '只读不能改', examples: '' }).ok, false);
});
