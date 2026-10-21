import test from 'node:test';
import assert from 'node:assert/strict';
import { initialState } from '../fixtures.js';
import { renderMaterials } from '../views/materials.js';
import { renderVisitorConversation, renderVisitorEvidence } from '../views/visitor.js';

function context() {
  const state = initialState();
  const agent = state.agents[0];
  state.ui.materials = {};
  state.materials = [{
    id: 'localized-material', revision: 1, title: '原创课程手册', filename: 'course.pdf', kind: 'document',
    status: 'published', rights: true, sourceRef: 'fictional:handbook', expires: '2099-12-31', scope: 'workspace',
    canSend: true, autoSendAllowed: false, original: { available: true, blobKey: 'local-pdf', size: 100 },
    summary: { text: '虚构课程说明', reviewed: true, baseRevision: 1 },
  }];
  return { state, agent, readonly: false };
}

const visibleText = html => html.replace(/<[^>]*>/g, '');

test('物料列表、详情、表单以中文说明智能客服、网站客服窗和会话收件箱', () => {
  const ctx = context();
  let html = renderMaterials(ctx);
  assert.match(html, /智能客服未授权/);
  assert.match(html, /data-page="widget"[^>]*>网站客服窗访客预览/);
  assert.match(html, /data-page="inbox"[^>]*>会话收件箱发送模拟/);
  assert.match(html, /本轮无平台内智能体工作进程/);
  assert.doesNotMatch(visibleText(html), /\b(?:Agent|Widget|Inbox|Mock|FAQ)\b/);
  ctx.state.ui.materials.detailId = 'localized-material';
  html = renderMaterials(ctx);
  assert.match(html, /智能客服自动发送还需此物料授权与当前专家策略均开启/);
  assert.match(html, /<dt>智能客服自动发送<\/dt>/);
  assert.match(html, /未接服务端文件库或外部渠道/);
  assert.doesNotMatch(visibleText(html), /\b(?:Agent|Widget|Inbox|Mock|FAQ)\b/);
  ctx.state.ui.materials.form = true;
  ctx.state.ui.materials.editingId = 'localized-material';
  html = renderMaterials(ctx);
  assert.match(html, /允许智能客服按策略自动选择并发送/);
  assert.match(html, /name="autoSendAllowed"/);
  assert.doesNotMatch(visibleText(html), /\b(?:Agent|Widget|Inbox|Mock|FAQ)\b/);
});

test('访客对话无障碍名称与证据使用中文，入口及表单标识不变', () => {
  const ctx = context();
  const html = renderVisitorConversation(ctx, { surface: 'widget' });
  assert.match(html, /aria-label="网站客服窗访客预览对话"/);
  assert.match(html, /data-visitor-surface="widget"/);
  assert.match(html, /data-form="widget-trial"/);
  assert.match(html, /name="widgetQuestion"/);
  const evidence = renderVisitorEvidence(ctx, 'widget');
  assert.match(evidence, /查看网站客服窗试用证据/);
  assert.match(evidence, /外部送达与业务解决尚未验证/);
  assert.doesNotMatch(evidence, /Widget/);
});

test('中文化不替换用户提供的英文原文或文件协议', () => {
  const ctx = context();
  const original = 'Widget Agent Inbox Mock FAQ';
  ctx.state.materials[0].title = original;
  ctx.state.ui.widgetTrialMessages = [{ id: 'original-message', role: 'visitor', text: original }];
  assert.ok(renderMaterials(ctx).includes(original));
  assert.ok(renderVisitorConversation(ctx, { surface: 'widget' }).includes(original));
  ctx.state.ui.materials.form = true;
  assert.match(renderMaterials(ctx), /SVG 与 HTML 不作为可执行内容载入/);
});
