import test from 'node:test';
import assert from 'node:assert/strict';
import { initialState } from '../fixtures.js';
import { renderWidget } from '../views/surfaces.js';

function context({ entries = [], selectedEntryId = '', status = 'ready', origin = 'http://127.0.0.1:8766' } = {}) {
  const state = initialState();
  const agent = state.agents[0];
  return {
    state,
    agent,
    readonly: false,
    configurationApiOrigin: origin,
    widgetInstall: { agentId: agent.id, status, entries, selectedEntryId, error: null },
  };
}

test('widget installer withholds code until a published ready sandbox entry is selected', () => {
  const html = renderWidget(context({
    entries: [{ entry_id: 'published-entry', version_id: 'sandbox-v2', knowledge_state: 'ready' }],
  }));

  assert.match(html, /选择已发布的沙盒入口/);
  assert.match(html, /data-action="widget-copy"[^>]*disabled/);
  assert.doesNotMatch(html, /data-copyable="true"/);
  assert.doesNotMatch(html, /example\.invalid/);
});

test('widget installer embeds the selected entry id and not the widget version binding', () => {
  const html = renderWidget(context({
    entries: [{ entry_id: 'published-entry', version_id: 'sandbox-v2', knowledge_state: 'ready' }],
    selectedEntryId: 'published-entry',
  }));

  assert.match(html, /widget\.js\?agent_id=course-demo&amp;entry_id=published-entry/);
  assert.match(html, /data-copyable="true"/);
  assert.doesNotMatch(html, /data-version="v1"/);
});

test('widget installer never emits code for stale entries or non-loopback service origins', () => {
  const stale = renderWidget(context({
    entries: [{ entry_id: 'stale-entry', version_id: 'sandbox-v1', knowledge_state: 'stale' }],
    selectedEntryId: 'stale-entry',
  }));
  const remote = renderWidget(context({
    entries: [{ entry_id: 'published-entry', version_id: 'sandbox-v2', knowledge_state: 'ready' }],
    selectedEntryId: 'published-entry', origin: 'https://service.example.test',
  }));

  assert.doesNotMatch(stale, /data-copyable="true"/);
  assert.match(stale, /待重新验收/);
  assert.doesNotMatch(remote, /data-copyable="true"/);
});

test('widget installer disables public identifiers the loader will reject', () => {
  const badEntry = renderWidget(context({
    entries: [{ entry_id: 'entry/unsafe', version_id: 'sandbox-v2', knowledge_state: 'ready' }],
    selectedEntryId: 'entry/unsafe',
  }));
  const badAgentContext = context({
    entries: [{ entry_id: 'published-entry', version_id: 'sandbox-v2', knowledge_state: 'ready' }],
    selectedEntryId: 'published-entry',
  });
  badAgentContext.agent.id = 'agent/unsafe';
  const badAgent = renderWidget(badAgentContext);

  assert.match(badEntry, /value="entry\/unsafe"[^>]*disabled/);
  assert.doesNotMatch(badEntry, /data-copyable="true"/);
  assert.doesNotMatch(badAgent, /data-copyable="true"/);
});
