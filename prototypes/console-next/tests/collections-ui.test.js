import test from 'node:test';
import assert from 'node:assert/strict';
import { initialState } from '../fixtures.js';
import { renderRuns, renderCases, renderIterations, renderConnections } from '../views/surfaces.js';

function context(page, overrides = {}) {
  const state = initialState();
  const agent = state.agents[0];
  state.ui.collections = { [page]: { query: '', status: 'all', detailId: null, form: false, ...overrides } };
  state.runs = [{ id: 'run-one', agentId: agent.id, input: '固定访客输入', answer: '仅详情可见答复', status: 'unknown', revision: 2, sources: [{ id: 'source-one', title: '完整来源证据', version: 3 }] }];
  state.cases = [{ id: 'case-one', agentId: agent.id, title: '案例一', input: '固定输入', expected: 'unknown', must: '必须显式说明未知', forbid: '禁止承诺金额', status: 'pending', runId: 'run-one' }];
  state.proposals = [{ id: 'proposal-one', agentId: agent.id, title: '候选一', reason: '修正资料外答复', baseRevision: 1, status: 'pending', diff: [{ path: 'fallback', before: '仅详情旧值', after: '仅详情新值' }], comparison: [{ caseId: 'case-one', before: 'unknown', after: 'unknown', expected: 'unknown' }], evaluation: 'pass' }];
  state.connections = [{ id: 'connection-one', name: '答疑连接', provider: 'compatible', model: 'model-one', status: 'failed', error: '认证检查失败，请重试' }];
  return { state, agent, readonly: false };
}
const pages = { runs: renderRuns, cases: renderCases, iterations: renderIterations, connections: renderConnections };

test('专家集合不展示无归属或其他专家记录', () => {
  for (const [page, key] of [['runs', 'runs'], ['cases', 'cases'], ['iterations', 'proposals']]) {
    const ctx = context(page);
    const item = ctx.state[key][0];
    ctx.state[key] = [{ ...item, id: 'orphan-record', agentId: undefined }, { ...item, id: 'other-record', agentId: 'other-agent' }];
    const html = pages[page](ctx);
    assert.doesNotMatch(html, /data-id="(?:orphan-record|other-record)"/);
    assert.match(html, /还没有/);
  }
});

for (const [page, render] of Object.entries(pages)) {
  test(`${page}: 默认摘要列表、独立详情、搜索空态与清除入口`, () => {
    const ctx = context(page);
    const html = render(ctx);
    assert.match(html, new RegExp(`data-collection-page="${page}" data-collection-mode="list"`));
    assert.match(html, /<h1[^>]*data-collection-heading[^>]*tabindex="-1"/);
    assert.match(html, /class="data-table mobile-list/);
    assert.match(html, /data-action="collection-open"/);
    assert.doesNotMatch(html, /data-form="(?:case|proposal|connection)"/);
    ctx.state.ui.collections[page].query = '不存在的检索词';
    assert.match(render(ctx), /没有匹配/);
    assert.match(render(ctx), /data-action="collection-clear"/);
    ctx.state.ui.collections[page].query = '';
    ctx.state.ui.collections[page].detailId = `${{ runs: 'run', cases: 'case', iterations: 'proposal', connections: 'connection' }[page]}-one`;
    const detail = render(ctx);
    assert.match(detail, /data-collection-mode="detail"/);
    assert.doesNotMatch(detail, /data-action="collection-open"/);
    assert.match(detail, /data-action="collection-back"/);
    ctx.readonly = true;
    assert.match(render(ctx), /data-collection-mode="detail"/);
    ctx.state.ui.collections[page].detailId = null;
    assert.doesNotMatch(render(ctx).match(/<button[^>]*data-action="collection-open"[^>]*>/)?.[0] || '', /disabled/);
    ctx.state[{ runs: 'runs', cases: 'cases', iterations: 'proposals', connections: 'connections' }[page]] = [];
    assert.match(render(ctx), /还没有/);
    assert.doesNotMatch(render(ctx), /没有匹配的记录/);
  });
}
test('列表不展开真值与差异，详情显式保留；失败与过期原因列表可读', () => {
  const cases = context('cases');
  assert.doesNotMatch(renderCases(cases), /必须显式说明未知|禁止承诺金额/);
  cases.state.ui.collections.cases.detailId = 'case-one';
  assert.match(renderCases(cases), /必须显式说明未知/);
  assert.match(renderCases(cases), /禁止承诺金额/);
  const iterations = context('iterations');
  assert.match(renderIterations(iterations), /基线已过期/);
  assert.doesNotMatch(renderIterations(iterations), /仅详情旧值|仅详情新值/);
  iterations.state.ui.collections.iterations.detailId = 'proposal-one';
  assert.match(renderIterations(iterations), /仅详情旧值/);
  assert.match(renderIterations(iterations), /仅详情新值/);
  assert.match(renderConnections(context('connections')), /认证检查失败，请重试/);
  const runs = context('runs', { detailId: 'run-one' });
  assert.match(renderRuns(runs), /仅详情可见答复/);
  assert.match(renderRuns(runs), /完整来源证据/);
});
test('新建表单独占工作面且取消使用集合协议', () => {
  for (const page of ['cases', 'iterations', 'connections']) {
    const ctx = context(page, { form: true });
    if (page === 'cases') ctx.state.ui.caseForm = true;
    if (page === 'iterations') ctx.state.ui.proposalForm = true;
    const html = pages[page](ctx);
    assert.match(html, /data-collection-mode="form"/);
    assert.match(html, /data-action="collection-cancel"/);
    assert.doesNotMatch(html, /data-action="collection-open"/);
    assert.doesNotMatch(html, /type="password"|name="(?:key|token|apiKey)"/);
  }
});

test('候选采用按钮重现当前基线与固定真值签名门禁，文本不会注入标记', () => {
  const ctx = context('iterations', { detailId: 'proposal-one' });
  const proposal = ctx.state.proposals[0];
  const item = ctx.state.cases[0];
  item.status = 'reviewed';
  proposal.baseRevision = ctx.agent.revision;
  proposal.evaluatedSuite = JSON.stringify([{ id: item.id, input: item.input, expected: item.expected, must: item.must, forbid: item.forbid, status: item.status }]);
  const applyButton = () => renderIterations(ctx).match(/<button[^>]*data-action="proposal-apply"[^>]*>/)?.[0];
  assert.doesNotMatch(applyButton(), /disabled/);
  item.must = '已修改真值';
  assert.match(applyButton(), /disabled/);
  assert.match(renderIterations(ctx), /人工案例或真值已变化/);
  proposal.diff[0].path = 'rules.0.description';
  assert.match(applyButton(), /disabled/);
  assert.match(renderIterations(ctx), /受保护范围/);
  proposal.title = '<img src=x onerror=alert(1)>';
  assert.doesNotMatch(renderIterations(ctx), /<img src=x/);
  assert.match(renderIterations(ctx), /&lt;img/);
});
