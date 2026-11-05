import test from 'node:test';
import assert from 'node:assert/strict';
import { createContactWorkspace } from '../contact-workspace.js';

const contact = () => ({ title: '课程咨询', description: '', blocks: [] });
function harness() {
  const calls = [];
  const client = {
    origin: 'http://127.0.0.1:8766',
    async request(action, payload) { calls.push({ action, payload }); return { revision: 3, config: { contact: contact(), protected: true } }; },
    async customerRequest(action, payload) {
      calls.push({ action, payload });
      if (action === 'contact.templates') return { items: [{ id: 'simple', name: '基础', contact: contact() }], schema: { block_types: [{ type: 'faq', label: '常见问题', item_fields: ['question', 'answer'], required_item_fields: ['question', 'answer'] }] } };
      if (action === 'contact.save') return { revision: payload.expected_revision + 1, contact: structuredClone(payload.contact) };
      throw new Error(`unexpected ${action}`);
    },
  };
  return { client, calls };
}

test('contact editor saves shared revision with typed blocks without publishing', async () => {
  const h = harness();
  const workspace = createContactWorkspace({ client: h.client });
  await workspace.load('expert-a');
  workspace.addBlock('faq');
  workspace.addItem(0);
  workspace.edit(['blocks', 0, 'items', 0, 'question'], '如何报名？');
  workspace.edit(['blocks', 0, 'items', 0, 'answer'], '请咨询客服。');
  await workspace.save();
  assert.equal(workspace.state.revision, 4);
  assert.equal(workspace.state.dirty, false);
  const last = h.calls.at(-1);
  assert.equal(last.action, 'contact.save');
  assert.equal(last.payload.expected_revision, 3);
  assert.deepEqual(last.payload.contact.blocks[0].items[0], { question: '如何报名？', answer: '请咨询客服。' });
  assert.equal(h.calls.some(call => call.action === 'contact.enable'), false);
});

test('conflicting contact save retains input and blocks another write until reloaded', async () => {
  const h = harness();
  const original = h.client.customerRequest;
  h.client.customerRequest = async (action, payload) => {
    if (action === 'contact.save') throw Object.assign(new Error('草稿已改变'), { code: 'revision_conflict' });
    return original(action, payload);
  };
  const workspace = createContactWorkspace({ client: h.client });
  await workspace.load('expert-a');
  workspace.edit(['title'], '本地待保留');
  await workspace.save();
  assert.equal(workspace.state.status, 'conflict');
  assert.equal(workspace.state.contact.title, '本地待保留');
  assert.equal(workspace.edit(['title'], '覆盖冲突'), false);
  assert.equal(workspace.state.dirty, true);
});

test('contact editor is inert in readonly mode and late load cannot switch experts', async () => {
  const h = harness();
  const workspace = createContactWorkspace({ client: h.client, isReadOnly: () => true });
  await workspace.load('expert-a');
  assert.equal(workspace.addBlock('faq'), false);
  assert.equal(workspace.edit(['title'], 'x'), false);
  assert.equal(await workspace.save(), false);
  const pending = {};
  h.client.request = (_action, payload) => new Promise(resolve => { pending[payload.agent_id] = resolve; });
  const first = workspace.load('one'); const second = workspace.load('two');
  pending.two({ revision: 2, config: { contact: { ...contact(), title: 'Two' } } });
  await second;
  pending.one({ revision: 1, config: { contact: { ...contact(), title: 'One' } } });
  await first;
  assert.equal(workspace.state.agentId, 'two');
  assert.equal(workspace.state.contact.title, 'Two');
});

test('contact fields follow the declared block schema and never write prototype paths', async () => {
  const h = harness(); const workspace = createContactWorkspace({ client: h.client });
  await workspace.load('expert-a');
  assert.equal(workspace.edit(['__proto__', 'polluted'], 'yes'), false);
  assert.equal(workspace.edit(['blocks', 0, 'items', 0, '__proto__'], 'yes'), false);
  assert.equal(workspace.addBlock('script'), false);
  workspace.addBlock('faq'); workspace.addItem(0);
  assert.equal(workspace.edit(['blocks', 0, 'items', 0, 'script'], 'yes'), false);
  assert.equal({}.polluted, undefined);
});

test('malformed or future contact drafts remain intact rather than becoming empty editable pages', async () => {
  for (const value of [null, false, { schema_version: 'future', title: '保留', blocks: [] }]) {
    const h = harness();
    h.client.request = async () => ({ revision: 3, config: { contact: value } });
    const workspace = createContactWorkspace({ client: h.client });
    await workspace.load('a');
    assert.deepEqual(workspace.state.contact, value);
    assert.equal(workspace.edit(['title'], '覆盖'), false);
  }
});

test('contact save blocks duplicate writes and discards late responses after expert switch', async () => {
  const h = harness(); let complete;
  const original = h.client.customerRequest;
  h.client.customerRequest = (action, payload) => action === 'contact.save'
    ? new Promise(resolve => { complete = resolve; }) : original(action, payload);
  const workspace = createContactWorkspace({ client: h.client });
  await workspace.load('one'); workspace.edit(['title'], '保存中');
  const pending = workspace.save();
  assert.equal(workspace.edit(['title'], '重复编辑'), false);
  assert.equal(await workspace.save(), false);
  await workspace.load('two');
  complete({ revision: 4, contact: { ...contact(), title: '旧响应' } });
  await pending;
  assert.equal(workspace.state.agentId, 'two');
  assert.equal(workspace.state.contact.title, '课程咨询');
});

test('validation or network failure keeps the form editable and allows retry', async () => {
  const h = harness(); const original = h.client.customerRequest;
  let fail = true;
  h.client.customerRequest = (action, payload) => {
    if (action === 'contact.save' && fail) throw Object.assign(new Error('请补齐内容'), { code: 'invalid_request' });
    return original(action, payload);
  };
  const workspace = createContactWorkspace({ client: h.client });
  await workspace.load('one'); workspace.edit(['title'], '保存失败');
  assert.equal(await workspace.save(), false);
  assert.equal(workspace.edit(['title'], '已补齐'), true);
  fail = false;
  assert.equal(await workspace.save(), true);
});

test('contact activation uses the reviewed entry version and is independent of draft saving', async () => {
  const h = harness(); const original = h.client.request;
  h.client.request = (action, payload) => action === 'release.entry.resolve'
    ? { version_id: 'published-v2', entry_id: payload.entry_id } : original(action, payload);
  const customer = h.client.customerRequest;
  h.client.customerRequest = (action, payload) => {
    if (action === 'contact.get') throw Object.assign(new Error('未启用'), { code: 'not_found' });
    if (action === 'contact.enable') { h.calls.push({ action, payload }); return { state: 'active', version_id: 'published-v2', share_path: '/contact/expert-a/entry-a' }; }
    if (action === 'contact.disable') return { state: 'disabled', version_id: 'published-v2' };
    return customer(action, payload);
  };
  const workspace = createContactWorkspace({ client: h.client });
  await workspace.load('expert-a'); workspace.setEntryId('entry-a');
  assert.equal(await workspace.setEntryEnabled(true), false);
  await workspace.queryEntry();
  assert.equal(await workspace.setEntryEnabled(true), true);
  assert.equal(h.calls.at(-1).payload.expected_version_id, 'published-v2');
  assert.equal(workspace.state.revision, 3);
  assert.equal(await workspace.setEntryEnabled(false), true);
  assert.equal(workspace.state.livePage, null);
});

test('AI contact generation keeps current edits until explicit adoption and saving', async () => {
  const h = harness(); const original = h.client.customerRequest;
  const proposed = { ...contact(), title: '候选标题', schema_version: 'contact-page-v1' };
  h.client.customerRequest = async (action, payload) => {
    if (action === 'contact.generate') {
      h.calls.push({ action, payload });
      return { state: 'proposal', base_revision: 3, contact: proposed, model_evidence: { model: 'fixture-model' } };
    }
    return original(action, payload);
  };
  const workspace = createContactWorkspace({ client: h.client });
  await workspace.load('expert-a'); workspace.edit(['title'], '手动未保存');
  workspace.setGenerationBrief('只使用这份虚构课程资料。');
  assert.equal(await workspace.generate(), true);
  assert.equal(workspace.state.contact.title, '手动未保存');
  assert.equal(workspace.state.revision, 3);
  assert.equal(workspace.state.dirty, true);
  assert.deepEqual(h.calls.at(-1), { action: 'contact.generate', payload: {
    agent_id: 'expert-a', expected_revision: 3, brief: '只使用这份虚构课程资料。',
  } });
  assert.equal(h.calls.some(call => ['contact.save', 'contact.enable'].includes(call.action)), false);
  assert.equal(workspace.adoptProposal(), true);
  proposed.title = '外部对象变化';
  assert.equal(workspace.state.contact.title, '候选标题');
  assert.equal(workspace.state.proposal, null);
  assert.equal(workspace.state.dirty, true);
  assert.equal(await workspace.save(), true);
  assert.equal(workspace.state.revision, 4);
});

test('AI contact generation blocks duplicate edits and ignores responses for an old expert', async () => {
  const h = harness(); const original = h.client.customerRequest; let complete;
  h.client.customerRequest = (action, payload) => action === 'contact.generate'
    ? new Promise(resolve => { complete = resolve; }) : original(action, payload);
  const workspace = createContactWorkspace({ client: h.client });
  await workspace.load('one'); workspace.setGenerationBrief('虚构资料');
  const pending = workspace.generate();
  assert.equal(workspace.state.status, 'generating');
  assert.equal(workspace.edit(['title'], '覆盖'), false);
  assert.equal(workspace.setGenerationBrief('改成其他素材'), false);
  assert.equal(await workspace.generate(), false);
  await workspace.load('two');
  complete({ state: 'proposal', base_revision: 3, contact: { ...contact(), title: '旧专家候选' } });
  assert.equal(await pending, false);
  assert.equal(workspace.state.contact.title, '课程咨询');
  assert.equal(workspace.state.proposal, null);
  assert.equal(workspace.state.generationBrief, '');
  assert.equal(workspace.state.status, 'ready');
});

test('AI contact candidates cannot overwrite later local edits or a new saved revision', async () => {
  const h = harness(); const original = h.client.customerRequest;
  h.client.customerRequest = (action, payload) => action === 'contact.generate'
    ? { state: 'proposal', base_revision: payload.expected_revision, contact: { ...contact(), title: '候选' } }
    : original(action, payload);
  const workspace = createContactWorkspace({ client: h.client });
  await workspace.load('a'); workspace.setGenerationBrief('虚构资料');
  await workspace.generate(); workspace.edit(['title'], '新编辑');
  assert.equal(workspace.adoptProposal(), false);
  assert.equal(workspace.state.contact.title, '新编辑');
  await workspace.generate(); await workspace.save();
  assert.equal(workspace.state.revision, 4);
  assert.equal(workspace.adoptProposal(), false);
  assert.equal(workspace.state.contact.title, '新编辑');
});

test('failed or malformed AI generation preserves manual work and readonly mode cannot call it', async () => {
  const h = harness(); const original = h.client.customerRequest; let calls = 0;
  let response = Object.assign(new Error('模型暂不可用'), { code: 'model_unavailable' });
  h.client.customerRequest = async (action, payload) => {
    if (action !== 'contact.generate') return original(action, payload);
    calls += 1;
    if (response instanceof Error) throw response;
    return response;
  };
  let readonly = false;
  const workspace = createContactWorkspace({ client: h.client, isReadOnly: () => readonly });
  await workspace.load('a'); workspace.edit(['title'], '手动内容');
  assert.equal(await workspace.generate(), false);
  assert.equal(calls, 0);
  workspace.setGenerationBrief('虚构资料');
  assert.equal(await workspace.generate(), false);
  assert.equal(workspace.state.status, 'ready');
  assert.equal(workspace.state.contact.title, '手动内容');
  assert.equal(workspace.state.generationError.code, 'model_unavailable');
  for (const value of [{ state: 'proposal', base_revision: 2, contact: contact() },
    { state: 'proposal', base_revision: 3, contact: null }]) {
    response = value;
    assert.equal(await workspace.generate(), false);
    assert.equal(workspace.state.proposal, null);
  }
  response = { state: 'proposal', base_revision: 3, contact: contact() };
  readonly = true;
  assert.equal(await workspace.generate(), false);
  assert.equal(workspace.setGenerationBrief('只读改动'), false);
  assert.equal(workspace.adoptProposal(), false);
  assert.equal(workspace.edit(['title'], '只读'), false);
  assert.equal(workspace.state.contact.title, '手动内容');
});
