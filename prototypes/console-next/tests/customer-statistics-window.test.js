import test from 'node:test';
import assert from 'node:assert/strict';
import { renderCustomerStatistics } from '../views/surfaces.js';

const render = (reception, filters = { period: 'all', channel: 'all' }) => renderCustomerStatistics({
  agent: { id: 'agent-a' },
  customerStatisticsFilters: filters,
  customerStatistics: {
    status: 'ready',
    data: {
      conversation_count: 12,
      message_count: 21,
      response_latency_ms: null,
      states: { bot: 9, human_requested: 2, human: 1 },
      messages_by_sender: { visitor: 12, assistant: 8, operator: 1 },
      channel_messages: { telegram: 3 },
      reception,
    },
  },
});

const sample = {
  schema_version: 'customer-statistics-window-v1',
  scope: {
    agent_id: 'agent-a', from: '2026-11-01T00:00:00+00:00', to: '2026-11-02T00:00:00+00:00',
    channel: 'text', version_id: null, basis: 'customer.reception.started', as_of: '2026-11-02T01:00:00+00:00',
  },
  request_count: 2,
  run_count: 3,
  entries: { 'web-entry': 2 },
  versions: { 'version-1': 2 },
  reception_outcomes: { answered: 2 },
  generated_count: 2,
  published_count: 1,
  handoff: { requested_count: null, claimed_count: null, reason: '<img src=x onerror=alert(1)>' },
  processing_latency: {
    mean_ms: 12.5, sample_count: 2, missing_count: 1,
    boundary: 'customer.reception.started -> customer.reception.finished', clock: 'server_event_wall_clock',
  },
  model_usage: {
    by_model: [{ model: null, input_tokens: 0, output_tokens: null, run_count: 1 }],
    input_tokens: 0, output_tokens: null,
    input_sample_count: 1, output_sample_count: 0,
    input_missing_count: 2, output_missing_count: 3,
    runs_without_usage: 2,
    basis: 'validated customer.reception.generated provider usage only',
  },
  visitor_latency_ms: null,
  delivery: 'unknown',
  coverage: { source: 'retained customer reception records', supported_channels: ['text'], ignored_record_count: 1 },
};

test('renders server scope, decimals, explicit zero, unknowns and escaped reasons separately from cumulative totals', () => {
  const html = render(sample, { period: '24h', channel: 'text' });
  assert.match(html, /窗口 \[2026-11-01T00:00:00\+00:00, 2026-11-02T00:00:00\+00:00\) UTC/);
  assert.match(html, /12\.5 ms/);
  assert.match(html, /输入用量（Token）<\/dt><dd>0<\/dd>/);
  assert.match(html, /输出用量（Token）<\/dt><dd>未知<\/dd>/);
  assert.match(html, /测量边界<\/dt><dd>从接待开始到接待结束<\/dd>/);
  assert.match(html, /时钟依据<\/dt><dd>服务端事件时间<\/dd>/);
  assert.match(html, /customer\.reception\.started -&gt; customer\.reception\.finished/);
  assert.match(html, /server_event_wall_clock/);
  assert.match(html, /未知 · 已保存不等于送达/);
  assert.match(html, /&lt;img src=x onerror=alert\(1\)&gt;/);
  assert.doesNotMatch(html, /<img src=x onerror=alert\(1\)>/);
  assert.match(html, /会话记录<\/dt><dd>12<\/dd>/);
  assert.match(html, /不随上方时间和渠道筛选变化/);
  const historicalHandoff = render({ ...sample, handoff: { ...sample.handoff, reason: 'historical_transition_events_not_recorded' } });
  assert.match(historicalHandoff, /<dt>曾人工承接的请求<\/dt><dd>未知 · 历史接管变化未作为事件保存<\/dd>/);
});

test('labels claimed handoff requests as distinct requests ever handled manually', () => {
  const html = render({ ...sample, handoff: { requested_count: 2, claimed_count: 1,
    claim_sample_count: 3, claim_missing_count: 0, reason: null } });
  assert.match(html, /<dt>曾人工承接的请求<\/dt><dd>1<\/dd>/);
  assert.doesNotMatch(html, /历史人工认领/);
});

test('renders unsupported voice coverage without labeling the whole service voice-free', () => {
  const voice = { ...sample, scope: { ...sample.scope, channel: 'voice' }, request_count: 0, run_count: 0,
    coverage: { ...sample.coverage, requested_channel_supported: false } };
  const html = render(voice, { period: '7d', channel: 'voice' });
  assert.match(html, /当前客服接待数据源尚未接入语音/);
  assert.match(html, /此范围的空结果不代表全站无语音接待/);
  assert.match(html, /name="customer-statistics-period"/);
  assert.match(html, /data-customer-statistics-filter="period"/);
  assert.match(html, /data-customer-statistics-filter="channel"/);
});

test('does not render a stale scope alongside a pending request or a failed request', () => {
  const loading = renderCustomerStatistics({ agent: { id: 'agent-a' }, customerStatisticsFilters: { period: '7d', channel: 'voice' },
    customerStatistics: { status: 'loading', data: null } });
  assert.match(loading, /正在读取统计数据/);
  assert.doesNotMatch(loading, /data-statistics-scope/);
  const failed = renderCustomerStatistics({ agent: { id: 'agent-a' }, customerStatisticsFilters: { period: '7d', channel: 'voice' },
    customerStatistics: { status: 'error', data: null, error: 'fixture unavailable' } });
  assert.match(failed, /fixture unavailable/);
  assert.doesNotMatch(failed, /data-statistics-scope/);
});
