import test from 'node:test';
import assert from 'node:assert/strict';
import { initialState } from '../fixtures.js';
import { renderKnowledge } from '../views/knowledge.js';

function context() {
  const state = initialState();
  const agent = state.agents[0];
  state.ui.knowledgeTab = 'qa';
  return { state, agent, ready: {}, readonly: false };
}

test('question list shows multiple answers from one source and keeps source as one record', () => {
  const ctx = context();
  const source = ctx.agent.config.sources[0];
  ctx.agent.config.qaItems = [
    { id: 'q1', sourceId: source.id, question: '学什么？', answer: '表格与 SQL。', reviewStatus: 'reviewed' },
    { id: 'q2', sourceId: source.id, question: '有作业吗？', answer: '有练习。', reviewStatus: 'pending' },
  ];
  let html = renderKnowledge(ctx);
  assert.match(html, /学什么？/);
  assert.match(html, /有作业吗？/);
  assert.match(html, /已审/);
  assert.match(html, /待审/);
  assert.match(html, /data-action="trial-open"[^>]*data-question="学什么？"/);
  ctx.state.ui.knowledgeTab = 'sources';
  html = renderKnowledge(ctx);
  assert.equal((html.match(new RegExp(`data-source-id="${source.id}"`, 'g')) || []).length, 1);
  assert.match(html, /data-action="knowledge-tab"[^>]*data-tab="qa"/);
});

test('batch intake accepts multiple files with one explicit, unchecked authorization declaration', () => {
  const ctx = context();
  const html = renderKnowledge(ctx);
  assert.match(html, /data-form="source-batch"/);
  assert.match(html, /type="file"[^>]*multiple/);
  assert.match(html, /accept="[^"]*\.csv[^"]*\.txt[^"]*\.md/);
  assert.match(html, /name="rights"/);
  assert.doesNotMatch(html, /name="rights"[^>]*checked/);
  assert.match(html, /name="sourceRef"/);
  assert.match(html, /name="expires"/);
});

test('review separates money from low risk and provides in-place decision and bulk confirmation', () => {
  const ctx = context();
  const source = ctx.agent.config.sources[0];
  ctx.state.ui.knowledgeTab = 'review';
  ctx.state.ui.reviewBatchId = source.id;
  ctx.agent.config.qaItems = [
    { id: 'risk', sourceId: source.id, question: '多少钱？', answer: '3980 元。', reviewStatus: 'pending' },
    { id: 'low', sourceId: source.id, question: '上课形式？', answer: '线上直播。', reviewStatus: 'pending' },
  ];
  const html = renderKnowledge(ctx);
  assert.match(html, /需要你逐条看（1）/);
  assert.match(html, /系统判断风险低（1）/);
  assert.match(html, /data-action="qa-decision"[^>]*data-id="risk"/);
  assert.match(html, /data-action="qa-edit"[^>]*data-id="risk"/);
  assert.match(html, /data-action="qa-low-confirm"/);
  assert.doesNotMatch(html, /name="rights"[^>]*checked/);
});

test('conflicting answer requires a submitted human choice before accepting it', () => {
  const ctx = context();
  const source = ctx.agent.config.sources[0];
  ctx.state.ui.knowledgeTab = 'review';
  ctx.state.ui.reviewBatchId = source.id;
  ctx.agent.config.qaItems = [{ id: 'conflict', sourceId: source.id, question: '多少钱？', answer: '3980 元起', reviewStatus: 'pending' }];
  ctx.agent.config.sources.push({ ...source, id: 'old-price', question: '多少钱？', answer: '3980 元', title: '旧话术' });
  const html = renderKnowledge(ctx);
  assert.match(html, /data-form="qa-save"[^>]*>[\s\S]*?name="choice"[^>]*required/);
  assert.match(html, /value="current"/);
  assert.match(html, /value="candidate"/);
  assert.match(html, /value="custom"/);
  assert.doesNotMatch(html, /data-action="qa-decision"[^>]*data-id="conflict"[^>]*data-decision="approve"/);
});

test('editing a key fact lists all affected uses and stays read-only when previewing', () => {
  const ctx = context();
  ctx.state.ui.knowledgeTab = 'facts';
  ctx.state.ui.factEditId = 'fact-price';
  ctx.agent.config.keyFacts = [{ id: 'fact-price', name: '课程价格', value: '3980', unit: '元', sourceRef: '价格表第 2 行' }];
  ctx.agent.config.qaItems = [{ id: 'q1', question: '多少钱？', answer: '价格 {课程价格}', reviewStatus: 'reviewed' }];
  ctx.agent.config.businessRules = [{ id: 'rule-1', condition: { field: '报价', operator: 'gt', value: '{课程价格}' }, action: 'confirm', enabled: true }];
  ctx.agent.config.tools = [{ id: 'tool-1', title: '按 {课程价格} 生成报价' }];
  const html = renderKnowledge(ctx);
  assert.match(html, /data-form="fact-save"/);
  assert.match(html, /以下 3 处会一起改/);
  assert.match(html, /问答「多少钱？」/);
  assert.match(html, /红线/);
  assert.match(html, /办理/);
  assert.match(html, /name="include:qa:q1"[^>]*checked/);
  ctx.readonly = true;
  assert.doesNotMatch(renderKnowledge(ctx), /data-form="fact-save"/);
});

test('redlines expose editable business rules and visible, immutable platform limits', async () => {
  const { renderRedlines } = await import('../views/knowledge.js');
  const ctx = context();
  ctx.agent.config.businessRules = [{ id: 'rule-refund', condition: { field: '客户诉求', operator: 'is', value: '退款' }, action: 'handoff', recipient: '售后组', enabled: true }];
  let html = renderRedlines(ctx);
  assert.match(html, /我的红线/);
  assert.match(html, /平台底线/);
  assert.match(html, /售后组/);
  assert.match(html, /data-action="rule-edit"[^>]*data-id="rule-refund"/);
  assert.ok((html.match(/data-action="rule-template"/g) || []).length >= 8);
  assert.doesNotMatch(html, /data-action="rule-edit"[^>]*data-id="rule-rights"/);
  ctx.state.ui.ruleEditId = 'rule-refund';
  html = renderRedlines(ctx);
  assert.match(html, /data-form="rule-save"/);
  assert.match(html, /转人工/);
  ctx.readonly = true;
  assert.doesNotMatch(renderRedlines(ctx), /data-form="rule-save"/);
});

test('a fact-only review batch uses fact decisions and fact fields for inline correction', () => {
  const ctx = context();
  const source = ctx.agent.config.sources[0];
  ctx.state.ui.knowledgeTab = 'review';
  ctx.state.ui.reviewBatchId = null;
  ctx.state.ui.factEditId = 'fact-new';
  ctx.agent.config.keyFacts = [{ id: 'fact-new', name: '课程价格', value: '3980', unit: '元', sourceId: source.id, sourceRef: '价格表第 2 行', reviewStatus: 'pending' }];
  const html = renderKnowledge(ctx);
  assert.match(html, /data-action="fact-decision"[^>]*data-id="fact-new"[^>]*data-decision="approve"/);
  assert.match(html, /data-action="fact-edit"[^>]*data-id="fact-new"/);
  assert.match(html, /data-form="fact-save"/);
  assert.match(html, /name="value"/);
  assert.match(html, /name="unit"/);
  assert.doesNotMatch(html, /data-action="qa-(?:decision|edit)"[^>]*data-id="fact-new"/);
  assert.doesNotMatch(html, /name="question"|name="answer"/);
});

test('fact conflicts submit a fact decision with correct value and unit fields', () => {
  const ctx = context();
  const source = ctx.agent.config.sources[0];
  ctx.state.ui.knowledgeTab = 'review';
  ctx.state.ui.reviewBatchId = source.id;
  ctx.agent.config.keyFacts = [
    { id: 'fact-old', name: '课程价格', value: '3980', unit: '元', reviewStatus: 'reviewed' },
    { id: 'fact-new', name: '课程价格', value: '4280', unit: '元', sourceId: source.id, sourceRef: '价格表第 2 行', reviewStatus: 'pending' },
  ];
  const html = renderKnowledge(ctx);
  assert.match(html, /data-form="fact-decision"/);
  assert.match(html, /name="choice"[^>]*required/);
  assert.match(html, /3980 元/);
  assert.match(html, /4280 元/);
  assert.match(html, /name="value"/);
  assert.match(html, /name="unit"/);
  assert.doesNotMatch(html, /name="question"|name="answer"/);
  assert.doesNotMatch(html, /data-action="fact-decision"[^>]*data-id="fact-new"[^>]*data-decision="approve"/);
});

test('reviewed questions and facts with cross-batch conflicts return to the review queue', () => {
  const ctx = context();
  const [source, otherSource] = ctx.agent.config.sources;
  ctx.state.ui.knowledgeTab = 'review';
  ctx.state.ui.reviewBatchId = source.id;
  ctx.agent.config.qaItems = [
    { id: 'qa-first', sourceId: source.id, question: '课程价格？', answer: '3980 元', reviewStatus: 'reviewed' },
    { id: 'qa-second', sourceId: otherSource.id, question: '课程价格？', answer: '4280 元', reviewStatus: 'reviewed' },
  ];
  ctx.agent.config.keyFacts = [
    { id: 'fact-first', sourceId: source.id, name: '课程价格', value: '3980', unit: '元', reviewStatus: 'reviewed' },
    { id: 'fact-second', sourceId: otherSource.id, name: '课程价格', value: '4280', unit: '元', reviewStatus: 'reviewed' },
  ];
  const html = renderKnowledge(ctx);
  assert.match(html, /2 条待核对/);
  assert.match(html, /data-form="qa-save"/);
  assert.match(html, /data-form="fact-decision"/);
  ctx.state.ui.knowledgeTab = 'qa';
  assert.match(renderKnowledge(ctx), /data-action="source-review-open"/);
});

test('each conflict correction control has a unique label target', () => {
  const ctx = context();
  const source = ctx.agent.config.sources[0];
  ctx.state.ui.knowledgeTab = 'review';
  ctx.state.ui.reviewBatchId = source.id;
  ctx.agent.config.keyFacts = [
    { id: 'old-price', name: '课程价格', value: '3980', unit: '元', reviewStatus: 'reviewed' },
    { id: 'new-price', name: '课程价格', value: '4280', unit: '元', sourceId: source.id, reviewStatus: 'pending' },
    { id: 'old-fee', name: '手续费', value: '0', unit: '元', reviewStatus: 'reviewed' },
    { id: 'new-fee', name: '手续费', value: '80', unit: '元', sourceId: source.id, reviewStatus: 'pending' },
  ];
  const html = renderKnowledge(ctx);
  const ids = [...html.matchAll(/\sid="([^"]+)"/g)].map(match => match[1]);
  assert.equal(new Set(ids).size, ids.length);
});

test('redline edit preserves customer-data and exact legacy options and counts recent rule hits', async () => {
  const { renderRedlines } = await import('../views/knowledge.js');
  const ctx = context();
  const now = Date.now();
  ctx.state.ui.ruleEditId = 'rule-private';
  ctx.agent.config.businessRules = [{ id: 'rule-private', condition: { field: '客户资料', operator: 'exact', value: '证件号' }, action: 'refuse', enabled: true }];
  ctx.state.runs = [
    { agentId: ctx.agent.id, createdAt: new Date(now - 60000).toISOString(), ruleHits: ['rule-private'] },
    { agentId: ctx.agent.id, createdAt: new Date(now - 2 * 86400000).toISOString(), ruleHits: ['rule-private'] },
    { agentId: ctx.agent.id, createdAt: new Date(now - 8 * 86400000).toISOString(), ruleHits: ['rule-private'] },
    { agentId: 'other', createdAt: new Date(now - 60000).toISOString(), ruleHits: ['rule-private'] },
    { agentId: ctx.agent.id, createdAt: new Date(now - 60000).toISOString(), ruleIds: ['rule-private'] },
  ];
  const html = renderRedlines(ctx);
  assert.match(html, /value="客户资料" selected/);
  assert.match(html, /value="exact" selected/);
  assert.match(html, /近 7 天 2 次/);
});
