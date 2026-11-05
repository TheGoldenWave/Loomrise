import test from 'node:test';
import assert from 'node:assert/strict';
import { createR1ConfigurationWorkspace } from '../r1-configuration.js';
import { renderR1Configuration } from '../views/r1-configuration.js';

test('reception settings pin source hashes and retain unknown configuration through shared draft save', async () => {
  let saved;
  const client = { origin: 'http://127.0.0.1:8766', request: async (action, payload) => {
    if (action === 'model.connection') return { configured: true, model_id: 'approved-model', tested: false };
    if (action === 'knowledge.source.list') return { items: [{ source_id: 'source-a', display_name: '授权问答', state: 'ready', content_hash: 'b'.repeat(64) }] };
    if (action === 'draft.save') { saved = payload; return { revision: 3, config: payload.config }; }
    throw new Error(action);
  } };
  const workspace = createR1ConfigurationWorkspace({ client });
  const config = { persona: {}, units: [], extension: 'preserved', ai_reception: { enabled: false, sources: [{ source_id: 'source-a', content_hash: 'a'.repeat(64) }] } };
  Object.assign(workspace.state, { agentId: 'a', status: 'ready', draft: { revision: 2, config: structuredClone(config) }, editorConfig: structuredClone(config), activeTab: 'reception' });
  await workspace.loadReceptionOptions();
  assert.equal(workspace.setReceptionSource('source-a', true), true);
  assert.deepEqual(workspace.state.editorConfig.ai_reception.sources, [{ source_id: 'source-a', content_hash: 'b'.repeat(64) }]);
  workspace.updateField('ai_reception.model_id', 'approved-model');
  workspace.updateField('ai_reception.enabled', true);
  const html = renderR1Configuration({ r1Configuration: workspace, agent: { name: '虚构专家' } });
  assert.match(html, /启用 AI 接待/);
  assert.match(html, /配置存在不代表连接测试通过/);
  await workspace.save(workspace.state.editorConfig);
  assert.equal(saved.expected_revision, 2);
  assert.equal(saved.config.extension, 'preserved');
  assert.equal(saved.config.ai_reception.enabled, true);
  workspace.state.readOnlySnapshot = { config };
  assert.equal(workspace.setReceptionSource('source-a', false), false);
});

test('late reception metadata cannot cross an expert switch', async () => {
  let resolve;
  const pending = new Promise(done => { resolve = done; });
  const workspace = createR1ConfigurationWorkspace({ client: { request: () => pending } });
  workspace.state.agentId = 'a';
  const loading = workspace.loadReceptionOptions();
  workspace.state.agentId = 'b';
  resolve({ configured: true, model_id: 'must-not-appear', items: [{ source_id: 'a-only' }] });
  await loading;
  assert.equal(workspace.state.receptionOptions.model, null);
});

test('handoff phrases edit as bounded lines in the shared draft and stay read-only in snapshots', async () => {
  let requests = 0;
  const workspace = createR1ConfigurationWorkspace({ client: { request: async () => { requests += 1; return {}; } } });
  const config = { persona: {}, units: [], ai_reception: { enabled: false, sources: [] } };
  Object.assign(workspace.state, { agentId: 'a', status: 'ready',
    draft: { revision: 2, config: structuredClone(config) },
    editorConfig: structuredClone(config), activeTab: 'reception' });
  assert.equal(workspace.updateField('ai_reception.handoff_phrases', ' 转人工\nTalk to a human\n'), true);
  assert.deepEqual(workspace.state.editorConfig.ai_reception.handoff_phrases, ['转人工', 'Talk to a human']);
  for (const value of ['a'.repeat(101), 'Straße\nSTRASSE', 'a\0b', Array.from({ length: 21 }, (_, i) => `短语${i}`).join('\n')]) {
    assert.equal(workspace.updateField('ai_reception.handoff_phrases', value), false);
    assert.ok(workspace.state.jsonErrors['ai_reception.handoff_phrases']);
    await workspace.save(workspace.state.editorConfig);
    assert.equal(requests, 0);
  }
  assert.equal(workspace.updateField('ai_reception.handoff_phrases', '🙂'.repeat(100)), true);
  const html = renderR1Configuration({ r1Configuration: workspace, agent: { name: '虚构专家' } });
  assert.match(html, /data-r1-bind="ai_reception\.handoff_phrases"/);
  assert.match(html, /显式转人工短语/);
  workspace.state.readOnlySnapshot = { config: { ...structuredClone(workspace.state.editorConfig),
    ai_reception: { ...workspace.state.editorConfig.ai_reception, handoff_phrases: ['冻结版本短语'] } } };
  const snapshotHtml = renderR1Configuration({ r1Configuration: workspace, agent: { name: '虚构专家' } });
  assert.match(snapshotHtml, />冻结版本短语<\/textarea>/);
  assert.doesNotMatch(snapshotHtml, /🙂{100}/u);
  assert.equal(workspace.updateField('ai_reception.handoff_phrases', '换一组'), false);
  assert.equal(workspace.state.draft.revision, 2);
});

test('raw reception edits preserve invalid input and synchronize handoff forms before saving', async () => {
  const saves = [];
  const workspace = createR1ConfigurationWorkspace({ client: { request: async (action, payload) => {
    assert.equal(action, 'draft.save');
    saves.push(structuredClone(payload));
    return { revision: payload.expected_revision + 1, config: payload.config };
  } } });
  const config = { persona: {}, units: [], ai_reception: { enabled: false, sources: [] } };
  Object.assign(workspace.state, { agentId: 'a', status: 'ready',
    draft: { revision: 2, config: structuredClone(config) }, editorConfig: structuredClone(config), activeTab: 'reception' });
  for (const { input, valid } of [{ input: '旧表单短语\n', valid: true }, { input: 'DUP\ndup', valid: false }]) {
    assert.equal(workspace.updateField('ai_reception.handoff_phrases', input), valid);
    const appliedConfig = structuredClone(workspace.state.editorConfig);
    const phraseError = workspace.state.jsonErrors['ai_reception.handoff_phrases'];
    const invalidJson = '{"handoff_phrases":[';
    workspace.updateJsonField('ai_reception', invalidJson);
    assert.equal(workspace.state.jsonInputs.ai_reception, invalidJson);
    assert.ok(workspace.state.jsonErrors.ai_reception);
    assert.equal(workspace.state.jsonInputs['ai_reception.handoff_phrases'], input);
    assert.equal(workspace.state.jsonErrors['ai_reception.handoff_phrases'], phraseError);
    assert.deepEqual(workspace.state.editorConfig, appliedConfig);
    const saveCount = saves.length;
    await workspace.save(workspace.state.editorConfig);
    assert.equal(saves.length, saveCount);

    const policy = { ...workspace.state.editorConfig.ai_reception, handoff_phrases: ['原文修正后的短语'] };
    workspace.updateJsonField('ai_reception', JSON.stringify(policy));
    assert.equal(workspace.state.jsonErrors.ai_reception, undefined);
    assert.equal(workspace.state.jsonInputs['ai_reception.handoff_phrases'], undefined);
    assert.equal(workspace.state.jsonErrors['ai_reception.handoff_phrases'], undefined);
    const html = renderR1Configuration({ r1Configuration: workspace, agent: { name: '虚构专家' } });
    assert.match(html, />原文修正后的短语<\/textarea>/);
    const revision = workspace.state.draft.revision;
    await workspace.save(workspace.state.editorConfig);
    assert.equal(saves.length, saveCount + 1);
    assert.equal(saves.at(-1).expected_revision, revision);
    assert.deepEqual(saves.at(-1).config.ai_reception.handoff_phrases, ['原文修正后的短语']);
    assert.deepEqual(workspace.state.draft.config.ai_reception.handoff_phrases, ['原文修正后的短语']);
    assert.equal(workspace.state.error, null);
  }
});

test('reception settings edit bounded FAQ questions against selected source versions', async () => {
  const sourceRef = { source_id: 'source-a', content_hash: 'b'.repeat(64) };
  const workspace = createR1ConfigurationWorkspace({ client: { request: async action => {
    if (action === 'model.connection') return { configured: true, model_id: 'approved-model', tested: true };
    if (action === 'knowledge.source.list') return { items: [
      { ...sourceRef, display_name: '授权问答', state: 'ready' },
      { source_id: 'source-b', content_hash: 'c'.repeat(64), display_name: '其他资料', state: 'ready' },
    ] };
    throw new Error(action);
  } } });
  const config = { persona: {}, units: [], ai_reception: {
    enabled: true, model_id: 'approved-model', sources: [sourceRef], faq_suggestions: [],
  } };
  Object.assign(workspace.state, {
    agentId: 'a', status: 'ready',
    draft: { revision: 2, config: structuredClone(config) },
    editorConfig: structuredClone(config), activeTab: 'reception',
  });
  await workspace.loadReceptionOptions();

  assert.equal(workspace.addReceptionFaqSuggestion(' 体验课多少钱？ ', 'source-a'), true);
  assert.deepEqual(workspace.state.editorConfig.ai_reception.faq_suggestions, [
    { question: '体验课多少钱？', ...sourceRef },
  ]);
  assert.equal(workspace.addReceptionFaqSuggestion('体验课多少钱？', 'source-a'), false);
  assert.equal(workspace.addReceptionFaqSuggestion('别的资料问题', 'source-b'), false);
  assert.equal(workspace.addReceptionFaqSuggestion('   ', 'source-a'), false);
  assert.equal(workspace.addReceptionFaqSuggestion('Q'.repeat(161), 'source-a'), false);

  for (let index = 1; index < 8; index += 1) {
    assert.equal(workspace.addReceptionFaqSuggestion(`问题 ${index}`, 'source-a'), true);
  }
  assert.equal(workspace.addReceptionFaqSuggestion('第九个问题', 'source-a'), false);

  const html = renderR1Configuration({ r1Configuration: workspace, agent: { name: '虚构专家' } });
  assert.match(html, /data-r1-faq-question/);
  assert.match(html, /data-r1-faq-source/);
  assert.match(html, /data-action="r1-add-faq-suggestion"/);
  assert.match(html, /data-action="r1-remove-faq-suggestion"/);
  assert.match(html, /data-r1-bind="ai_reception\.faq_suggestions\.0\.question"/);
  assert.match(html, /体验课多少钱？/);
  assert.match(html, /授权问答/);

  assert.equal(workspace.updateField('ai_reception.faq_suggestions.0.question', '调整后的问题'), true);
  assert.equal(workspace.state.editorConfig.ai_reception.faq_suggestions[0].question, '调整后的问题');
  assert.equal(workspace.removeReceptionFaqSuggestion(0), true);
  assert.equal(workspace.state.editorConfig.ai_reception.faq_suggestions.length, 7);
});

test('FAQ suggestion duplicate matching follows full case folding for sharp s', async () => {
  const sourceRef = { source_id: 'source-a', content_hash: 'b'.repeat(64) };
  const workspace = createR1ConfigurationWorkspace({ client: { request: async action => {
    if (action === 'model.connection') return { configured: true, model_id: 'approved-model', tested: true };
    if (action === 'knowledge.source.list') return { items: [{ ...sourceRef, display_name: '授权问答', state: 'ready' }] };
    throw new Error(action);
  } } });
  const config = { persona: {}, units: [], ai_reception: {
    enabled: true, model_id: 'approved-model', sources: [sourceRef], faq_suggestions: [],
  } };
  Object.assign(workspace.state, {
    agentId: 'a', status: 'ready', draft: { revision: 2, config: structuredClone(config) },
    editorConfig: structuredClone(config), activeTab: 'reception',
  });
  await workspace.loadReceptionOptions();

  assert.equal(workspace.addReceptionFaqSuggestion('Straße', 'source-a'), true);
  assert.equal(workspace.addReceptionFaqSuggestion('STRASSE', 'source-a'), false);
  assert.equal(workspace.addReceptionFaqSuggestion('Different question', 'source-a'), true);
  assert.equal(workspace.updateField('ai_reception.faq_suggestions.1.question', 'STRASSE'), false);
  assert.deepEqual(workspace.state.editorConfig.ai_reception.faq_suggestions.map(item => item.question), ['Straße', 'Different question']);
});

test('FAQ question limits count Unicode code points without truncating add or edit input', async () => {
  const sourceRef = { source_id: 'source-a', content_hash: 'b'.repeat(64) };
  const workspace = createR1ConfigurationWorkspace({ client: { request: async action => {
    if (action === 'model.connection') return { configured: true, model_id: 'approved-model', tested: true };
    if (action === 'knowledge.source.list') return { items: [{ ...sourceRef, display_name: '授权问答', state: 'ready' }] };
    throw new Error(action);
  } } });
  const config = { persona: {}, units: [], ai_reception: {
    enabled: true, model_id: 'approved-model', sources: [sourceRef], faq_suggestions: [],
  } };
  Object.assign(workspace.state, {
    agentId: 'a', status: 'ready', draft: { revision: 2, config: structuredClone(config) },
    editorConfig: structuredClone(config), activeTab: 'reception',
  });
  await workspace.loadReceptionOptions();
  const maximum = '🙂'.repeat(160);

  assert.equal(workspace.addReceptionFaqSuggestion(maximum, 'source-a'), true);
  assert.equal(workspace.addReceptionFaqSuggestion(`${maximum}🙂`, 'source-a'), false);
  assert.equal(workspace.addReceptionFaqSuggestion(` ${maximum}`, 'source-a'), false);
  assert.equal(workspace.state.editorConfig.ai_reception.faq_suggestions[0].question, maximum);
  assert.equal(workspace.updateField('ai_reception.faq_suggestions.0.question', `${maximum}🙂`), false);
  assert.equal(workspace.state.editorConfig.ai_reception.faq_suggestions[0].question, maximum);

  const html = renderR1Configuration({ r1Configuration: workspace, agent: { name: '虚构专家' } });
  assert.doesNotMatch(html, /maxlength\s*=\s*["']?160/i);
  assert.match(html, /data-r1-faq-question/);
  assert.match(html, /data-r1-faq-edit-error/);
});

test('FAQ suggestions reject add, edit and remove in stable, candidate and comparison views', async () => {
  const sourceRef = { source_id: 'source-a', content_hash: 'b'.repeat(64) };
  const config = { persona: {}, units: [], ai_reception: {
    enabled: true, model_id: 'approved-model', sources: [sourceRef],
    faq_suggestions: [{ question: '现有问题', ...sourceRef }],
  } };
  const client = { request: async (action, payload) => {
    if (action === 'model.connection') return { configured: true, model_id: 'approved-model', tested: true };
    if (action === 'knowledge.source.list') return { items: [{ ...sourceRef, display_name: '授权问答', state: 'ready' }] };
    if (action === 'stable.get') return { version_id: payload.version_id, config: structuredClone(config) };
    if (action === 'candidate.get') return { candidate_id: payload.candidate_id, config: structuredClone(config) };
    if (action === 'release.checklist') return { candidate_id: payload.candidate_id, checks: [], progress: {} };
    if (action === 'configuration.compare') return {
      before: { ...payload.before, config: structuredClone(config) },
      after: { ...payload.after, config: structuredClone(config) },
      diff: [], object_diff: { changes: [], diagnostics: [] },
    };
    throw new Error(action);
  } };
  const workspace = createR1ConfigurationWorkspace({ client });
  Object.assign(workspace.state, {
    agentId: 'a', status: 'ready',
    draft: { revision: 2, config: structuredClone(config) },
    editorConfig: structuredClone(config), activeTab: 'reception',
  });
  await workspace.loadReceptionOptions();

  const assertFaqReadOnly = () => {
    const before = structuredClone(workspace.state.editorConfig);
    assert.equal(workspace.addReceptionFaqSuggestion('有效新问题', 'source-a'), false);
    assert.equal(workspace.updateField('ai_reception.faq_suggestions.0.question', '有效修改'), false);
    assert.equal(workspace.removeReceptionFaqSuggestion(0), false);
    assert.deepEqual(workspace.state.editorConfig, before);
  };

  await workspace.openStable('v1');
  assert.ok(workspace.state.readOnlySnapshot);
  assertFaqReadOnly();
  workspace.closeSnapshot();

  await workspace.openCandidate('c1');
  assert.ok(workspace.state.selectedCandidate);
  assertFaqReadOnly();
  workspace.closeSnapshot();

  assert.equal(await workspace.compareVersions({ kind: 'stable', id: 'v1' }, { kind: 'candidate', id: 'c1' }), true);
  assert.ok(workspace.state.comparison);
  assertFaqReadOnly();
});
