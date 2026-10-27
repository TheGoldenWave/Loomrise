const tidy = value => String(value ?? '').trim();
export const normalizeQuestion = value => tidy(value).normalize('NFKC').toLowerCase().replace(/[\s\p{P}]/gu, '');
const normal = value => tidy(value).normalize('NFKC').toLowerCase().replace(/[\s？?。！!，,、:：；;（）()]/g, '');
const amount = value => tidy(value).match(/\d+(?:[.,]\d+)?/g)?.join(',') || '';
const qualifier = value => tidy(value).match(/(?:起|以上|以内|以下|约|大约|至少|最多|不超过|不低于|仅限|不含|含)/g)?.join(',') || '';

export const RULE_FIELDS = Object.freeze(['客户诉求', '客户情绪', '报价金额', '客户说了', '资料范围', '客户资料']);
export const RULE_OPERATORS = Object.freeze(['is', 'exact', 'contains', 'gt', 'missing']);
export const RULE_ACTIONS = Object.freeze(['handoff', 'confirm', 'refuse', 'end', 'later']);
export const RULE_OPERATOR_LABELS = Object.freeze({ is: '是', exact: '完全一致', contains: '包含', gt: '大于', missing: '没有' });
export const RULE_ACTION_LABELS = Object.freeze({ handoff: '转人工', confirm: '请客户确认', refuse: '不回答并说明', end: '结束对话', later: '稍后回复' });

export const RULE_TEMPLATES = [
  { id: 'refund', label: '退款转人工', condition: { field: '客户诉求', operator: 'is', value: '退款' }, action: 'handoff' },
  { id: 'complaint', label: '投诉转人工', condition: { field: '客户情绪', operator: 'is', value: '投诉' }, action: 'handoff' },
  { id: 'high-price', label: '报价超额需确认', condition: { field: '报价金额', operator: 'gt', value: '5000' }, action: 'confirm' },
  { id: 'no-price', label: '资料无价格不报价', condition: { field: '资料范围', operator: 'missing', value: '价格' }, action: 'refuse' },
  { id: 'personal-id', label: '不索要证件号', condition: { field: '客户资料', operator: 'is', value: '证件号' }, action: 'refuse' },
  { id: 'refund-time', label: '退款时效待核实', condition: { field: '客户诉求', operator: 'is', value: '退款时效' }, action: 'handoff' },
  { id: 'no-promises', label: '不作保底承诺', condition: { field: '客户诉求', operator: 'is', value: '保证结果' }, action: 'refuse' },
  { id: 'cancel', label: '客户要取消则转人工', condition: { field: '客户诉求', operator: 'is', value: '取消' }, action: 'handoff' },
];

export function ruleHitCount(runs, agentId, ruleId, currentTime = Date.now()) {
  const end = currentTime instanceof Date ? currentTime.getTime() : typeof currentTime === 'number' ? currentTime : Date.parse(currentTime);
  const start = end - 7 * 24 * 60 * 60 * 1000;
  return (runs || []).filter(run => {
    const time = Date.parse(run.createdAt);
    return run.agentId === agentId && time >= start && time <= end && Array.isArray(run.ruleHits) && run.ruleHits.includes(ruleId);
  }).length;
}

function csvRows(text, delimiter = ',') {
  const rows = [];
  let row = [], field = '', quoted = false;
  const source = String(text || '').replace(/^\uFEFF/, '');
  for (let i = 0; i < source.length; i += 1) {
    const char = source[i];
    if (char === '"') {
      if (quoted && source[i + 1] === '"') { field += '"'; i += 1; }
      else quoted = !quoted;
    } else if (char === delimiter && !quoted) { row.push(field); field = ''; }
    else if ((char === '\n' || char === '\r') && !quoted) {
      if (char === '\r' && source[i + 1] === '\n') i += 1;
      row.push(field); field = '';
      if (row.some(cell => tidy(cell))) rows.push(row);
      row = [];
    } else field += char;
  }
  row.push(field);
  if (row.some(cell => tidy(cell))) rows.push(row);
  return rows;
}

function identity(name, index) {
  let hash = 2166136261;
  for (const char of name) hash = Math.imul(hash ^ char.charCodeAt(0), 16777619);
  return `candidate-${(hash >>> 0).toString(36)}-${index + 1}`;
}

export function parseBatchText({ name = '文本资料', text = '' } = {}) {
  const filename = tidy(name);
  const extension = filename.split('.').pop()?.toLowerCase();
  if (extension === 'csv' || extension === 'tsv') {
    const rows = csvRows(text, extension === 'tsv' ? '\t' : ',');
    if (!rows.length) return [];
    const headers = rows[0].map(normal);
    const index = aliases => headers.findIndex(header => aliases.some(alias => normal(alias) === header));
    const questionIndex = index(['问题', '问', 'question', 'query']);
    const answerIndex = index(['答案', '答', '标准解答', 'answer', 'response']);
    const nameIndex = index(['名称', '关键信息', '项目', '课程', 'name', 'item']);
    const valueIndex = index(['价格', '数值', '值', '金额', 'value', 'price']);
    const unitIndex = index(['单位', 'unit']);
    return rows.slice(1).map((row, offset) => {
      const base = { id: identity(filename, offset), sourceTitle: filename, sourceRow: offset + 2, reviewStatus: 'pending' };
      if (questionIndex >= 0 && answerIndex >= 0) return { ...base, kind: 'qa', question: tidy(row[questionIndex]), answer: tidy(row[answerIndex]) };
      if (nameIndex >= 0 && valueIndex >= 0) return { ...base, kind: 'fact', name: tidy(row[nameIndex]), value: tidy(row[valueIndex]), unit: unitIndex < 0 ? '' : tidy(row[unitIndex]) };
      return { ...base, kind: 'qa', question: tidy(row[0]) || `${filename}第 ${offset + 2} 行`, answer: row.slice(1).map(tidy).filter(Boolean).join(' · ') };
    }).filter(item => item.kind === 'fact' ? item.name && item.value : item.question && item.answer);
  }
  if (!['txt', 'md', 'markdown'].includes(extension)) return [];
  const paragraphs = String(text).replace(/^\uFEFF/, '').split(/\n\s*\n/).map(tidy).filter(Boolean);
  return paragraphs.map((answer, index) => ({
    id: identity(filename, index), kind: 'qa', sourceTitle: filename, sourceRow: index + 1,
    question: answer.split(/[。！？!?\n]/).find(Boolean)?.trim().slice(0, 60) || `${filename}第 ${index + 1} 段`,
    answer, reviewStatus: 'pending',
  }));
}

export async function parseWorkbook({ name = '表格.xlsx', buffer } = {}) {
  if (!buffer) throw new Error('没有收到工作簿内容');
  const XLSX = await import('./node_modules/@e965/xlsx/xlsx.mjs');
  const book = XLSX.read(buffer, { type: 'array', cellDates: false });
  const candidates = [];
  for (const sheetName of book.SheetNames) {
    const sheet = book.Sheets[sheetName];
    if (!sheet?.['!ref']) continue;
    const range = XLSX.utils.decode_range(sheet['!ref']);
    if (range.e.r - range.s.r + candidates.length > 501) throw new Error('工作簿超过 500 条本地核对上限，请拆分后再导入');
    const csv = XLSX.utils.sheet_to_csv(sheet, { FS: ',', RS: '\n', blankrows: false });
    const parsed = parseBatchText({ name: `${sheetName}.csv`, text: csv });
    candidates.push(...parsed.map(item => ({ ...item, id: `${sheetName}:${item.id}`, sourceTitle: name, sourceSheet: sheetName })));
  }
  return candidates;
}

export function legacyQaItems(config) {
  const explicit = Array.isArray(config.qaItems) ? config.qaItems : [];
  const sourced = new Set(explicit.map(item => item.sourceId).filter(Boolean));
  return [
    ...explicit,
    ...(config.sources || []).filter(source => source.type === 'FAQ' && !sourced.has(source.id)).map(source => ({
      id: `qa-${source.id}`, sourceId: source.id, question: source.question, answer: source.answer,
      reviewStatus: source.status === 'indexed' ? 'reviewed' : 'pending', legacy: true,
    })),
  ];
}

export function detectCandidateConflicts(candidate, { qaItems = [], keyFacts = [], sources = [] } = {}) {
  const eligible = item => item.reviewStatus !== 'rejected' && (item.reviewStatus !== 'pending' || candidate.sourceId && candidate.sourceId === item.sourceId);
  if (candidate.kind === 'fact') return keyFacts.filter(fact => (!candidate.id || fact.id !== candidate.id) && eligible(fact) && normal(fact.name) === normal(candidate.name) && (normal(fact.value) !== normal(candidate.value) || normal(fact.unit) !== normal(candidate.unit))).map(fact => ({
    kind: amount(fact.value) && amount(fact.value) === amount(candidate.value) && qualifier(fact.value) !== qualifier(candidate.value) ? 'qualifier' : 'value',
    current: [tidy(fact.value), tidy(fact.unit)].filter(Boolean).join(' '), candidate: [tidy(candidate.value), tidy(candidate.unit)].filter(Boolean).join(' '), currentId: fact.id,
    currentValue: fact.value, currentUnit: fact.unit || '',
  }));
  if (candidate.kind !== 'qa') return [];
  const explicit = qaItems.filter(item => (!candidate.id || item.id !== candidate.id) && eligible(item));
  const explicitSources = new Set(explicit.map(item => item.sourceId).filter(Boolean));
  const current = [
    ...explicit,
    ...(sources || []).filter(source => source.type === 'FAQ' && !explicitSources.has(source.id) && source.status === 'indexed' && source.rights).map(source => ({ id: source.id, question: source.question, answer: source.answer, status: source.status })),
  ].filter(item => (!candidate.id || item.id !== candidate.id) && normalizeQuestion(item.question) === normalizeQuestion(candidate.question) && normal(item.answer) !== normal(candidate.answer));
  return current.map(item => ({
    kind: amount(item.answer) && amount(item.answer) === amount(candidate.answer) && qualifier(item.answer) !== qualifier(candidate.answer) ? 'qualifier' : 'answer',
    current: item.answer, candidate: candidate.answer, currentId: item.id,
  }));
}

export function classifyCandidates(candidates, existing = {}) {
  const risky = [], lowRisk = [];
  for (const candidate of candidates) {
    const peers = candidates.filter(other => candidate.sourceId && other.sourceId === candidate.sourceId && other.id !== candidate.id);
    const conflicts = detectCandidateConflicts(candidate, { ...existing, qaItems: [...(existing.qaItems || []), ...peers.filter(item => item.kind === 'qa')], keyFacts: [...(existing.keyFacts || []), ...peers.filter(item => item.kind === 'fact')] });
    const value = [candidate.question, candidate.answer, candidate.name, candidate.value, candidate.unit].join(' ');
    const needsReview = conflicts.length || candidate.kind === 'fact' && Boolean(amount(candidate.value)) || /(?:价格|金额|费用|报价|元|￥|¥|保证|一定|全额|免费|承诺)/.test(value) || /\d+(?:\.\d+)?\s*(?:元|块|万|%)/.test(value);
    (needsReview ? risky : lowRisk).push({ ...candidate, conflicts });
  }
  return { risky, lowRisk };
}

export function sampleLowRisk(candidates, count = 2, seed = '') {
  const scored = candidates.map((item, index) => ({ item, index, score: identity(`${seed}:${item.id}`, index) }));
  return scored.sort((a, b) => a.score.localeCompare(b.score)).slice(0, count).map(entry => entry.item);
}

export function resolveFactReferences(value, facts = []) {
  const values = new Map(facts.filter(fact => !['pending', 'rejected'].includes(fact.reviewStatus)).map(fact => [fact.name, [tidy(fact.value), tidy(fact.unit)].filter(Boolean).join(' ')]));
  return String(value ?? '').replace(/\{([^{}]+)\}/g, (match, name) => values.get(name) ?? match);
}

export function factReferences(agent, name) {
  const config = agent.config || {};
  const mark = `{${name}}`;
  const found = [];
  for (const item of legacyQaItems(config)) if (item.reviewStatus !== 'rejected' && String(item.answer || '').includes(mark)) found.push({ kind: 'qa', id: item.id, title: item.question });
  for (const item of config.businessRules || []) if ([item.condition?.value, item.condition?.field, item.action].some(value => String(value || '').includes(mark))) found.push({ kind: 'rule', id: item.id, title: item.title || item.condition?.value || '红线' });
  for (const item of config.tools || []) if ([item.title, item.description, item.input].some(value => String(value || '').includes(mark))) found.push({ kind: 'tool', id: item.id, title: item.title });
  return found;
}
