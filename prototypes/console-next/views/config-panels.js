import { attr, button, escapeHtml, formatTime } from '../helpers.js';
import { factReferences, legacyQaItems } from '../knowledge-model.js';
import { describeChange } from '../domain.js';

const e = escapeHtml;

export function renderQuickTrial({ state, agent, readonly }) {
  const result = state.ui.quickTrial;
  const current = result && result.question === state.ui.trialInput ? result : null;
  const sources = current?.sources || [];
  const latestFeedback = (state.feedback || []).find(item => item.agentId === agent.id && item.status === 'open' && item.question === current?.question);
  return `<div class="quick-trial"><h2>试一试</h2><form data-form="quick-trial" class="stack"><label for="quick-trial-question">你要问什么</label><textarea class="control textarea" id="quick-trial-question" name="question" data-ui-bind="trialInput" rows="3" ${readonly ? 'disabled' : ''}>${e(state.ui.trialInput || '')}</textarea><button class="btn btn-primary" type="submit" ${readonly ? 'disabled' : ''}>提问</button></form>${current ? `<div class="quick-trial-answer" aria-live="polite"><p><strong>你：</strong>${e(current.question)}</p><p><strong>本地脚本：</strong>${e(current.answer)}</p><div class="button-group">${button('trial-confirm', '对', { disabled: readonly })}${button('trial-feedback', '答错了', { question: current.question, answer: current.answer, verdict: 'wrong', disabled: readonly || Boolean(latestFeedback) })}</div><p class="helper">依据：${sources.length} 处知识库 · ${current.ruleHits.length ? `命中 ${current.ruleHits.length} 条红线` : '红线无命中'}</p>${latestFeedback ? `<p class="notice notice-warning">已加入待处理队列。${button('feedback-to-case', '转为测试题', { id: latestFeedback.id })}</p>` : ''}</div>` : '<p class="muted">还没有这次的答复。</p>'}<div class="button-group">${button('navigate', '看完整对话', { page: 'trial', variant: 'ghost' })}${button('quick-trial-clear', '清空重来', { variant: 'ghost' })}</div></div>`;
}

export function renderEvidencePanel({ state, agent }) {
  const target = state.ui.evidenceTarget || {};
  const config = agent.config;
  const source = config.sources.find(item => item.id === target.id);
  const qa = legacyQaItems(config).find(item => item.id === target.id);
  const fact = (config.keyFacts || []).find(item => item.id === target.id);
  const rule = (config.businessRules || []).find(item => item.id === target.id) || config.rules.find(item => item.id === target.id);
  const tool = config.tools.find(item => item.id === target.id);
  const node = config.routeGraph?.nodes?.find(item => item.id === target.id);
  const change = (agent.changeLog || []).find(item => item.id === target.id || item.objectId === target.id);
  const item = qa || fact || rule || tool || node || source || change;
  const origin = qa ? config.sources.find(entry => entry.id === qa.sourceId) : source;
  const label = qa?.question || fact?.name || rule?.title || tool?.title || node?.title || source?.title || (change && describeChange(change)) || '当前草稿';
  const from = origin?.sourceRef || origin?.title || item?.sourceRef || change?.source || '来源尚未记录';
  const affected = fact ? `${factReferences(agent, fact.name).length} 处直接引用` : qa ? `${state.cases.filter(test => test.agentId === agent.id && test.input === qa.question).length} 条测试题` : rule ? '红线和引用它的路径' : tool ? '办理路径与结果检查' : node ? '连接到此节点的流程路径' : '当前专家草稿';
  const run = state.runs.find(entry => entry.agentId === agent.id && (entry.sources || []).some(ref => ref.id === origin?.id || ref.id === item?.id)) || state.runs.find(entry => entry.agentId === agent.id && entry.id === target.id);
  const who = change?.origin ? `${change.origin} · ${formatTime(change.time)}` : '操作员身份未记录';
  return `<div class="evidence-panel"><h2>依据</h2><h3>${e(label)}</h3><dl class="evidence-questions"><div><dt>从哪来</dt><dd>${e(from)}</dd></div><div><dt>哪一版</dt><dd>${state.ui.previewVersionId ? '历史线上版（只读）' : '当前草稿'}</dd></div><div><dt>谁改的</dt><dd>${e(who)}</dd></div><div><dt>影响谁</dt><dd>${e(affected)}</dd></div><div><dt>凭什么</dt><dd>${run ? button('run-open', '打开这次运行记录', { id: run.id }) : '尚无关联运行记录'}</dd></div></dl><details><summary>技术详情</summary><dl class="detail-list"><div><dt>对象 ID</dt><dd><code>${e(item?.id || '未记录')}</code></dd></div><div><dt>草稿修订</dt><dd>r${e(agent.revision)}</dd></div><div><dt>运行 ID</dt><dd>${e(run?.id || '未记录')}</dd></div></dl></details></div>`;
}
