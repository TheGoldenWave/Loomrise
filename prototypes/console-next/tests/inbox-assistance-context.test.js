import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { setImmediate } from 'node:timers/promises';
import vm from 'node:vm';

const html = readFileSync(new URL('../../../loomrise/customer_inbox.html', import.meta.url), 'utf8');
const inlineScript = [...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g)].map(match => match[1]).join('\n');
const scopeA = 'tenant-a:course-demo:actor-a';
const scopeB = 'tenant-b:course-demo:actor-b';

function conversation(id = 'thread-a', overrides = {}) {
  return { conversation_id: id, state: 'human', is_assigned_to_me: true,
    occupancy_generation: 1, release_version: 'version-1', latest_sequence: 2,
    read_sequence: 2, unread_count: 0, visitor_fields: { name: `Visitor ${id}` }, ...overrides };
}

function proposal(reply = '候选 A') {
  return { summary: `摘要：${reply}`, reply, citations: [], snapshot_hash: `hash-${reply}` };
}

async function makeInbox(items = [conversation()]) {
  const elements = new Map();
  class Element {
    constructor() {
      this.children = []; this.dataset = {}; this.style = {}; this.value = '';
      this.disabled = false; this.hidden = false; this.listeners = new Map();
      this.scrollTop = 0; this.scrollHeight = 100; this.clientHeight = 100;
      this.ownText = '';
    }
    get textContent() { return this.ownText + this.children.map(child => child.textContent).join(''); }
    set textContent(value) { this.ownText = String(value); this.children = []; }
    get options() { return this.children; }
    replaceChildren(...children) { this.ownText = ''; this.children = children; }
    append(...children) { this.children.push(...children); }
    setAttribute(name, value) { this[name] = value; }
    getClientRects() { return [{}]; }
    addEventListener(name, handler) { this.listeners.set(name, handler); }
    dispatchEvent(event) { this.listeners.get(event.type)?.(event); }
    focus() { document.activeElement = this; }
  }
  for (const match of html.matchAll(/\bid="([^"]+)"/g)) elements.set(match[1], new Element());
  elements.get('queueFilter').value = 'all';
  elements.get('assistanceProposal').hidden = true;
  const document = {
    body: { dataset: { agentId: 'course-demo' } }, activeElement: null, visibilityState: 'visible',
    querySelector: selector => elements.get(selector.slice(1)),
    createElement: () => new Element(), addEventListener() {},
  };
  const requests = [];
  const held = new Map();
  let listResult = { notification_scope: scopeA, can_mark_read: true, items };
  const reply = result => ({ ok: true, json: async () => ({ ok: true, result }) });
  const fetch = async (_url, options) => {
    const { action, payload } = JSON.parse(options.body);
    const request = { action, payload, signal: options.signal };
    requests.push(request);
    const pending = held.get(action)?.shift();
    if (pending) {
      pending.request = request;
      // Deliberately allow a response after abort to exercise the stale-result guard too.
      return reply(await pending.result);
    }
    switch (action) {
      case 'inbox.list': return reply(listResult);
      case 'inbox.messages': return reply({ items: [
        { sequence: 1, sender: 'visitor', text: `Question ${payload.conversation_id}` },
        { sequence: 2, sender: 'operator', text: `Answer ${payload.conversation_id}` },
      ] });
      case 'inbox.preferences': return reply({ can_edit: true, new_messages: false, handoff: false });
      case 'material.list': return reply({ items: [] });
      case 'inbox.consumer.cursor': return reply({ cursor: 0 });
      case 'inbox.events': return reply({ events: [], has_more: false });
      case 'inbox.assistance.generate': return reply(proposal());
      case 'inbox.assistance.check': return reply({ valid: true });
      default: throw new Error(`Unexpected request: ${action}`);
    }
  };
  const storage = new Map();
  const context = vm.createContext({ document, fetch, AbortController, Event,
    Option: class extends Element { constructor(text, value) { super(); this.textContent = text; this.value = value; } },
    window: { location: { origin: 'http://localhost' } },
    sessionStorage: { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value) },
    setInterval() {}, setTimeout() {}, clearTimeout() {},
  });
  vm.runInContext(inlineScript, context, { filename: 'customer_inbox.html' });
  await setImmediate();
  const run = code => vm.runInContext(code, context);
  const hold = action => {
    let resolve;
    const pending = { result: new Promise(done => { resolve = done; }), resolve: value => resolve(value) };
    if (!held.has(action)) held.set(action, []);
    held.get(action).push(pending);
    return pending;
  };
  return {
    element: id => elements.get(id), requests, run, hold,
    select: id => run(`select(conversations.find(item => item.conversation_id === ${JSON.stringify(id)}))`),
    async scope(scope, nextItems = []) {
      listResult = { ...listResult, notification_scope: scope, items: nextItems };
      await run('loadList()');
    },
    noSend: () => assert.equal(requests.some(request => request.action === 'inbox.reply'), false),
  };
}

test('scope transition discards pending generation and clears the previous identity from the page', async () => {
  const inbox = await makeInbox();
  await inbox.select('thread-a');
  inbox.element('text').value = 'A 的人工草稿';
  const pending = inbox.hold('inbox.assistance.generate');
  const generating = inbox.element('generateAssistance').onclick();
  await inbox.scope(scopeB);
  pending.resolve(proposal('旧身份候选'));
  await generating;
  assert.equal(inbox.element('assistanceProposal').hidden, true);
  assert.equal(inbox.element('assistanceReply').textContent, '');
  assert.equal(inbox.element('text').value, '');
  assert.equal(inbox.element('messages').textContent, '');
  assert.equal(inbox.element('visitorInfo').textContent, '');
  assert.equal(inbox.element('conversationSummary').textContent, '选择会话查看');
  assert.equal(inbox.element('status').textContent, '选择一条会话');
  assert.equal(inbox.run('selected'), null);
  assert.equal(inbox.run('displayedConversation'), null);
  assert.equal(inbox.element('send').disabled, true);
  assert.equal(pending.request.signal?.aborted, true);
  inbox.noSend();
});

test('scope transition cannot adopt an old proposal into the new identity draft', async () => {
  const inbox = await makeInbox();
  await inbox.select('thread-a');
  await inbox.element('generateAssistance').onclick();
  const pending = inbox.hold('inbox.assistance.check');
  const adopting = inbox.element('adoptAssistance').onclick();
  await inbox.scope(scopeB);
  pending.resolve({ valid: true });
  await adopting;
  assert.equal(inbox.element('text').value, '');
  assert.equal(inbox.element('assistanceProposal').hidden, true);
  assert.equal(inbox.element('adoptAssistance').disabled, true);
  assert.equal(pending.request.signal?.aborted, true);
  inbox.noSend();
});

test('scope transition invalidates a pending detail read even when the new identity has no conversations', async () => {
  const inbox = await makeInbox();
  const pending = inbox.hold('inbox.messages');
  const selecting = inbox.select('thread-a');
  await inbox.scope(scopeB);
  pending.resolve({ items: [{ sequence: 2, sender: 'visitor', text: '旧身份消息' }] });
  await selecting;
  assert.equal(inbox.element('messages').textContent, '');
  assert.equal(inbox.element('visitorInfo').textContent, '');
  assert.equal(inbox.run('selected'), null);
  assert.equal(inbox.element('generateAssistance').disabled, true);
});

for (const action of ['inbox.assistance.generate', 'inbox.assistance.check']) {
  test(`switching thread cancels ${action} and its completion cannot unlock a newer generation`, async () => {
    const inbox = await makeInbox([conversation(), conversation('thread-b')]);
    await inbox.select('thread-a');
    if (action.endsWith('.check')) await inbox.element('generateAssistance').onclick();
    const previous = inbox.hold(action);
    const previousWork = inbox.element(action.endsWith('.check') ? 'adoptAssistance' : 'generateAssistance').onclick();
    await inbox.select('thread-b');
    assert.equal(inbox.element('generateAssistance').disabled, false, 'obsolete work must not block this thread');
    assert.equal(previous.request.signal?.aborted, true);
    const current = inbox.hold('inbox.assistance.generate');
    const currentWork = inbox.element('generateAssistance').onclick();
    assert.equal(inbox.element('generateAssistance').disabled, true);
    previous.resolve(action.endsWith('.check') ? { valid: true } : proposal('迟到候选 A'));
    await previousWork;
    assert.equal(inbox.element('generateAssistance').disabled, true, 'old finally must not unlock the new request');
    assert.equal(inbox.element('assistanceProposal').hidden, true);
    assert.equal(inbox.element('text').value, '');
    current.resolve(proposal('当前候选 B'));
    await currentWork;
    assert.equal(inbox.element('assistanceReply').textContent, '当前候选 B');
    assert.equal(inbox.element('generateAssistance').disabled, false);
    assert.equal(inbox.element('adoptAssistance').disabled, false);
    inbox.noSend();
  });
}

test('manual edits made during adoption validation are preserved', async () => {
  const inbox = await makeInbox();
  await inbox.select('thread-a');
  await inbox.element('generateAssistance').onclick();
  inbox.element('text').value = '校验前的草稿';
  const pending = inbox.hold('inbox.assistance.check');
  const adopting = inbox.element('adoptAssistance').onclick();
  inbox.element('text').value = '校验期间人工修改';
  inbox.element('text').dispatchEvent(new Event('input'));
  pending.resolve({ valid: true });
  await adopting;
  assert.equal(inbox.element('text').value, '校验期间人工修改');
  assert.equal(inbox.element('adoptAssistance').disabled, false);
  assert.match(inbox.element('assistanceStatus').textContent, /已保留输入/);
  inbox.noSend();
});

test('ordinary queue filtering preserves the selected thread, draft and usable proposal', async () => {
  const inbox = await makeInbox();
  await inbox.select('thread-a');
  await inbox.element('generateAssistance').onclick();
  inbox.element('text').value = '筛选时保留的人工草稿';
  inbox.element('queueFilter').value = 'waiting';
  inbox.element('queueFilter').onchange();
  await inbox.scope(scopeA, [conversation()]);
  assert.equal(inbox.element('text').value, '筛选时保留的人工草稿');
  assert.equal(inbox.run('selected.conversation_id'), 'thread-a');
  assert.equal(inbox.element('queueSelectionNote').hidden, false);
  assert.equal(inbox.element('assistanceProposal').hidden, false);
  assert.equal(inbox.element('adoptAssistance').disabled, false);
  inbox.noSend();
});
