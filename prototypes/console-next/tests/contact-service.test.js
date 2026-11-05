import test from 'node:test';
import assert from 'node:assert/strict';
import { createStore } from '../store.js';
import { renderShell } from '../views/shell.js';
import { renderContactService } from '../views/contact-service.js';

test('server contact page uses real save state and keeps question before answer', () => {
  const store = createStore(); store.dispatch('navigate', { page: 'contact' });
  const agent = store.currentAgent();
  const contactWorkspace = { writable: () => true, client: { origin: 'http://127.0.0.1:8766' }, state: {
    agentId: agent.id, revision: 3, status: 'ready', dirty: true, templates: [],
    schema: { block_types: [{ type: 'faq', label: '常见问题', item_fields: ['answer', 'question'], required_item_fields: ['answer', 'question'] }] },
    contact: { title: '<unsafe>', description: '', blocks: [{ id: 'faq-1', type: 'faq', items: [{ question: 'Q', answer: 'A' }] }] },
  } };
  const ctx = { state: store.state, agent, readonly: false, contactWorkspace };
  const body = renderContactService(ctx);
  assert.ok(body.indexOf('问题（必填）') < body.indexOf('回答（必填）'));
  assert.ok(!body.includes('<unsafe>'));
  const html = renderShell(ctx, body);
  const header = html.match(/<section class="contextbar"[\s\S]*?<\/section>/)?.[0];
  assert.match(header, /有未保存修改/);
  assert.doesNotMatch(header, /已自动保存/);
  assert.match(html, /本机服务/);
});

test('AI drafting is optional and reviews escaped candidate content before adoption', () => {
  const state = { agentId: 'a', revision: 3, status: 'ready', dirty: false, templates: [],
    schema: { block_types: [{ type: 'faq', label: '常见问题', item_fields: ['answer', 'question'], required_item_fields: ['answer', 'question'] }] },
    contact: { title: '手动标题', description: '', blocks: [] }, generationBrief: '虚构资料',
    proposal: { base_revision: 3, model_evidence: { model: 'test-model', private: 'not-for-display' },
      contact: { title: '<script>标题</script>', description: '候选说明', blocks: [
        { id: 'faq', type: 'faq', title: '答疑', body: '仅供审阅', items: [{ question: '<img src=x>', answer: '候选回答' }] },
      ] } },
  };
  const workspace = { state, writable: () => state.status === 'ready', client: { origin: 'http://127.0.0.1:8766' } };
  const body = renderContactService({ agent: { id: 'a' }, contactWorkspace: workspace });
  assert.match(body, /AI 辅助起草（可选）/);
  assert.match(body, /data-contact-generation-brief/);
  assert.match(body, /使用当前模型连接/);
  assert.match(body, /候选回答/);
  assert.match(body, /采用并替换编辑内容/);
  assert.match(body, /maxlength="4000"/);
  assert.doesNotMatch(body, /<script>|<img src=x>|not-for-display/);
  assert.match(body, /&lt;script&gt;标题&lt;\/script&gt;/);
  assert.ok(body.indexOf('<dt>问题</dt>') < body.indexOf('<dt>回答</dt>'), '候选审阅应先显示问题再显示回答');
  state.status = 'generating'; state.proposal = null;
  const busy = renderContactService({ agent: { id: 'a' }, contactWorkspace: workspace });
  assert.match(busy, /正在起草/);
  assert.match(busy, /data-action="cs-contact-generate"[^>]*disabled/);
});
