import test from 'node:test';
import assert from 'node:assert/strict';
import { initialState } from '../fixtures.js';
import { readiness } from '../domain.js';
import { renderKnowledge } from '../views/knowledge.js';

function context() {
  const state = initialState();
  state.ui.knowledgeTab = 'sources';
  const agent = state.agents[0];
  return { state, agent, ready: readiness(agent, state.connections), readonly: false };
}

const visibleText = html => html.replace(/<[^>]*>/g, '');

test('全部资料汇总、类型数量与筛选结果分别标明范围', () => {
  const ctx = context();
  for (const [type, label, total] of [['FAQ', '问答', 3], ['URL', '网页', 0], ['File', '文件', 0]]) {
    ctx.state.ui.sourceTab = type;
    const html = renderKnowledge(ctx);
    assert.match(html, /全部资料[\s\S]*?3 条资料[\s\S]*?3 条可试用/);
    assert.match(html, new RegExp(`当前类型：${label} · 共 ${total} 条`));
    assert.match(html, new RegExp(`筛选结果：${total} 条`));
    assert.match(html, new RegExp(`data-tab="${type}">${label} <span>${total}</span>`));
  }
  ctx.state.ui.sourceTab = 'FAQ';
  ctx.state.ui.search = ctx.agent.config.sources[0].answer;
  assert.match(renderKnowledge(ctx), /当前类型：问答 · 共 3 条[\s\S]*?筛选结果：1 条/);
});

test('筛选无结果可清除条件，不引导重复添加资料，只读仍可恢复筛选', () => {
  const ctx = context();
  ctx.state.ui.sourceFilter = 'pending';
  ctx.state.ui.search = '未命中的搜索内容';
  ctx.readonly = true;
  const html = renderKnowledge(ctx);
  const empty = html.slice(html.indexOf('<div class="library-empty">'));
  assert.match(empty, /没有匹配的资料/);
  assert.match(empty, /data-action="source-clear"[^>]*>清除筛选/);
  assert.doesNotMatch(empty, /data-action="source-clear"[^>]*disabled/);
  assert.doesNotMatch(empty, /data-action="source-form-toggle"|load-demo-sources/);
});

test('只读零记录说明限制并提供返回草稿入口', () => {
  for (const historical of [false, true]) {
    const ctx = context();
    ctx.agent.config.sources = [];
    ctx.readonly = true;
    ctx.state.ui.previewVersionId = historical ? 'v1' : null;
    const html = renderKnowledge(ctx);
    const empty = html.slice(html.indexOf('<div class="library-empty">'));
    assert.match(empty, /还没有问答资料/);
    assert.match(empty, historical ? /冻结版本.*不能添加资料/ : /只读预览.*不能添加资料/);
    assert.match(empty, /data-action="readonly-toggle"[^>]*>返回可编辑草稿/);
    assert.doesNotMatch(empty, /data-action="source-form-toggle"|load-demo-sources/);
  }
});

test('类型零记录与无匹配分开，可编辑空态保留添加及虚构示例', () => {
  const ctx = context();
  ctx.state.ui.sourceTab = 'URL';
  ctx.state.ui.search = '旧条件';
  const html = renderKnowledge(ctx);
  assert.match(html, /还没有网页资料/);
  assert.doesNotMatch(html, /没有匹配的资料/);
  assert.match(html, /data-action="source-form-toggle"[^>]*>添加网页资料/);
  ctx.agent.config.sources = [];
  ctx.state.ui.sourceTab = 'FAQ';
  ctx.state.ui.search = '';
  assert.match(renderKnowledge(ctx), /data-action="load-demo-sources"/);
});

test('可见问答与网页地址使用中文，枚举、字段和动作保持不变', () => {
  const ctx = context();
  assert.doesNotMatch(visibleText(renderKnowledge(ctx)), /\bFAQ\b|\bURL\b|\bAgent\b/);
  ctx.state.ui.sourceTab = 'URL';
  ctx.state.ui.sourceForm = true;
  const form = renderKnowledge(ctx);
  assert.match(form, /授权网页地址/);
  assert.match(form, /name="type" value="URL"/);
  assert.match(form, /name="url"[^>]*type="url"/);
  assert.doesNotMatch(visibleText(form), /\bFAQ\b|\bURL\b|\bAgent\b/);
  ctx.state.ui.sourceForm = false;
  ctx.agent.config.sources.push({ ...ctx.agent.config.sources[0], id: 'file-metadata', type: 'File', body: '', metadataOnly: true, filename: '资料.pdf' });
  ctx.state.ui.sourceDetail = 'file-metadata';
  assert.doesNotMatch(visibleText(renderKnowledge(ctx)), /\bFAQ\b|\bURL\b|\bAgent\b/);
});

test('问答直接可读，长解答保留原生展开与行内快编和详情', () => {
  const ctx = context();
  const source = ctx.agent.config.sources[0];
  source.answer = '长解答内容。'.repeat(50);
  const html = renderKnowledge(ctx);
  assert.match(html, new RegExp(source.question));
  assert.match(html, /<details class="knowledge-answer-disclosure"/);
  assert.ok(html.includes(source.answer));
  assert.match(html, /data-action="source-edit"[^>]*>编辑问答/);
  assert.match(html, /data-action="source-detail"[^>]*>详情/);
  assert.match(html, /role="tab"[^>]*tabindex="0"[^>]*aria-selected="true"/);
});

test('不按字符数猜测三行高度，短于190字和多行解答仍可原生展开全文', () => {
  const ctx = context();
  ctx.agent.config.sources = ctx.agent.config.sources.slice(0, 1);
  for (const answer of ['中'.repeat(180), '第一行\n第二行\n第三行\n第四行', '短解答']) {
    ctx.agent.config.sources[0].answer = answer;
    const html = renderKnowledge(ctx);
    assert.match(html, /<details class="knowledge-answer-disclosure"[^>]*><summary>/);
    assert.ok(html.includes(`<p class="knowledge-answer-full source-text">${answer}</p>`));
    assert.ok(html.includes(`<span class="knowledge-answer-excerpt source-text">${answer}</span>`));
    assert.doesNotMatch(html, /<details class="knowledge-answer-disclosure"[^>]*\bopen/);
  }
});

test('不可用与待处理原因保留在列表首层，不误报为可试用', () => {
  const ctx = context();
  const sources = ctx.agent.config.sources;
  sources[0].rights = false;
  sources[1].status = 'failed';
  sources[2].metadataOnly = true;
  const html = renderKnowledge(ctx);
  for (const reason of ['先确认该资料的客服使用授权。', '可重试本地处理，再审阅内容。', '文件信息已保存，此格式解析待接后端。']) assert.ok(html.includes(reason));
  assert.match(html, /0 条可试用/);
  assert.match(html, /2 条待处理/);
  assert.match(html, /1 条不可用/);
  assert.match(html, /网页抓取、文档解析与真实检索待接入/);
});

test('列表、详情与编辑工作面互斥且保留焦点标题合同', () => {
  const ctx = context();
  ctx.state.ui.sourceDetail = ctx.agent.config.sources[0].id;
  let html = renderKnowledge(ctx);
  assert.match(html, /knowledge-source-detail/);
  assert.doesNotMatch(html, /knowledge-table|data-form="source"/);
  assert.match(html, /data-library-heading tabindex="-1"/);
  ctx.state.ui.sourceForm = true;
  ctx.state.ui.sourceEdit = ctx.state.ui.sourceDetail;
  html = renderKnowledge(ctx);
  assert.match(html, /data-form="source"/);
  assert.doesNotMatch(html, /knowledge-table|knowledge-source-detail/);
});
