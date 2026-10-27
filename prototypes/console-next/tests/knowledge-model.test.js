import test from 'node:test';
import assert from 'node:assert/strict';
import * as model from '../knowledge-model.js';
import * as XLSX from '@e965/xlsx';
const { parseBatchText, detectCandidateConflicts, classifyCandidates, sampleLowRisk, resolveFactReferences, factReferences, RULE_TEMPLATES } = model;

test('XLSX workbook separates rows across sheets into review candidates', async () => {
  const book = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(book, XLSX.utils.aoa_to_sheet([['问题', '答案'], ['什么时候上课？', '周二晚上'], ['如何联系？', '网站留言']]), '问答');
  XLSX.utils.book_append_sheet(book, XLSX.utils.aoa_to_sheet([['名称', '价格', '单位'], ['数据分析课', 3980, '元']]), '价格');
  const buffer = XLSX.write(book, { bookType: 'xlsx', type: 'array' });
  assert.equal(typeof model.parseWorkbook, 'function');
  const items = await model.parseWorkbook({ name: '课程.xlsx', buffer });
  assert.equal(items.length, 3);
  assert.equal(items.filter(item => item.kind === 'qa').length, 2);
  assert.equal(items.find(item => item.kind === 'fact').value, '3980');
  assert.ok(items.every(item => item.sourceTitle === '课程.xlsx'));
});

test('price CSV and policy text create review candidates without per-row forms', () => {
  const rows = ['名称,价格,单位', ...Array.from({ length: 30 }, (_, i) => `课程 ${i + 1},${1000 + i},元`)];
  const prices = parseBatchText({ name: '价格.csv', text: rows.join('\n') });
  const policy = parseBatchText({ name: '政策.txt', text: Array.from({ length: 10 }, (_, i) => `第 ${i + 1} 项政策。\n适用于已付款访客。`).join('\n\n') });
  assert.equal(prices.length, 30);
  assert.equal(prices[0].kind, 'fact');
  assert.equal(prices[0].name, '课程 1');
  assert.equal(policy.length, 10);
  assert.equal(policy[0].kind, 'qa');
  assert.ok(policy[0].answer.includes('适用于已付款访客'));
});

test('CSV parser preserves quoted commas, embedded newlines and quoted double quotes', () => {
  const items = parseBatchText({ name: '问答.csv', text: '问题,答案\n"如何退费,或改期？","先联系人工，\n确认""原路退回""。"' });
  assert.equal(items.length, 1);
  assert.equal(items[0].question, '如何退费,或改期？');
  assert.equal(items[0].answer, '先联系人工，\n确认"原路退回"。');
});

test('same question, changed amount and changed numeric qualifier all surface as conflicts', () => {
  const existing = {
    qaItems: [{ id: 'old-qa', question: '课程多少钱？', answer: '3980 元。' }],
    keyFacts: [{ id: 'old-fact', name: '课程价格', value: '3980', unit: '元' }],
  };
  const examples = [
    { id: 'a', kind: 'qa', question: '课程多少钱', answer: '4280 元。' },
    { id: 'b', kind: 'fact', name: '课程价格', value: '4280', unit: '元' },
    { id: 'c', kind: 'qa', question: '课程多少钱？', answer: '3980 元起。' },
  ];
  const conflicts = examples.map(candidate => detectCandidateConflicts(candidate, existing));
  assert.ok(conflicts[0].some(item => item.kind === 'answer'));
  assert.ok(conflicts[1].some(item => item.kind === 'value'));
  assert.ok(conflicts[2].some(item => item.kind === 'qualifier'));
});

test('nine injected examples distinguish answer, numeric value, and qualifier conflicts', () => {
  const existing = {
    qaItems: [
      { id: 'a1', question: '学费多少？', answer: '3980 元。' },
      { id: 'a2', question: '退费多久？', answer: '7 个工作日。' },
      { id: 'a3', question: '有试听吗？', answer: '有试听。' },
    ],
    keyFacts: [
      { id: 'f1', name: '学费', value: '3980', unit: '元' },
      { id: 'f2', name: '退费时效', value: '7', unit: '工作日' },
      { id: 'f3', name: '手续费', value: '0', unit: '元' },
    ],
  };
  const cases = [
    [{ kind: 'qa', question: '学费多少', answer: '4280 元' }, 'answer'],
    [{ kind: 'qa', question: '退费多久？', answer: '10 个工作日' }, 'answer'],
    [{ kind: 'qa', question: '有试听吗', answer: '没有试听' }, 'answer'],
    [{ kind: 'fact', name: '学费', value: '4280', unit: '元' }, 'value'],
    [{ kind: 'fact', name: '退费时效', value: '10', unit: '工作日' }, 'value'],
    [{ kind: 'fact', name: '手续费', value: '8', unit: '元' }, 'value'],
    [{ kind: 'qa', question: '学费多少？', answer: '3980 元起' }, 'qualifier'],
    [{ kind: 'fact', name: '学费', value: '3980 起', unit: '元' }, 'qualifier'],
    [{ kind: 'fact', name: '退费时效', value: '至少 7', unit: '工作日' }, 'qualifier'],
  ];
  const matched = cases.filter(([candidate, kind]) => detectCandidateConflicts(candidate, existing).some(conflict => conflict.kind === kind));
  assert.ok(matched.length >= 8, `${matched.length}/9 matched`);
});

test('money and promises always require individual review; low-risk sample is stable and distinct', () => {
  const candidates = [
    { id: 'price', kind: 'qa', question: '多少钱', answer: '3980 元' },
    { id: 'promise', kind: 'qa', question: '可以退款吗', answer: '保证全额退费' },
    ...Array.from({ length: 8 }, (_, i) => ({ id: `low-${i}`, kind: 'qa', question: `问题 ${i}`, answer: `普通说明 ${i}` })),
  ];
  const groups = classifyCandidates(candidates, { qaItems: [], keyFacts: [] });
  assert.deepEqual(groups.risky.map(item => item.id), ['price', 'promise']);
  assert.equal(groups.lowRisk.length, 8);
  const first = sampleLowRisk(groups.lowRisk, 2, 'review-1');
  assert.equal(first.length, 2);
  assert.notEqual(first[0].id, first[1].id);
  assert.deepEqual(first, sampleLowRisk(groups.lowRisk, 2, 'review-1'));
});

test('a key fact supplies the same latest value to referenced answers, rules and tool text', () => {
  const agent = { config: {
    qaItems: [{ id: 'qa', answer: '售价 {课程价格}，明天可以报名。' }],
    businessRules: [{ id: 'rule', condition: { value: '{课程价格}' } }],
    tools: [{ id: 'tool', title: '按 {课程价格} 创建订单' }],
  } };
  const facts = [{ id: 'fact', name: '课程价格', value: '4280', unit: '元' }];
  assert.equal(resolveFactReferences(agent.config.qaItems[0].answer, facts), '售价 4280 元，明天可以报名。');
  assert.deepEqual(factReferences(agent, '课程价格').map(item => item.kind), ['qa', 'rule', 'tool']);
  assert.equal(resolveFactReferences('未知 {缺失值}', facts), '未知 {缺失值}');
});

test('unreviewed facts do not replace answers and rejected answers do not count as affected uses', () => {
  const facts = [
    { id: 'current', name: '课程价格', value: '3980', unit: '元', reviewStatus: 'reviewed' },
    { id: 'pending', name: '课程价格', value: '4280', unit: '元', reviewStatus: 'pending' },
    { id: 'rejected', name: '退费时效', value: '10', unit: '天', reviewStatus: 'rejected' },
  ];
  assert.equal(resolveFactReferences('价格 {课程价格}，时效 {退费时效}', facts), '价格 3980 元，时效 {退费时效}');
  const refs = factReferences({ config: { qaItems: [
    { id: 'current', question: '多少钱？', answer: '{课程价格}', reviewStatus: 'reviewed' },
    { id: 'rejected', question: '旧问答', answer: '{课程价格}', reviewStatus: 'rejected' },
  ] } }, '课程价格');
  assert.deepEqual(refs.map(item => item.id), ['current']);
});

test('redline templates expose stable condition and closed handling values to the state layer', () => {
  assert.ok(RULE_TEMPLATES.length >= 8);
  assert.equal(new Set(RULE_TEMPLATES.map(item => item.id)).size, RULE_TEMPLATES.length);
  assert.ok(RULE_TEMPLATES.every(item => item.condition.field && item.condition.operator && item.condition.value));
  assert.ok(RULE_TEMPLATES.every(item => ['handoff', 'confirm', 'refuse', 'end', 'later'].includes(item.action)));
});

test('question normalization is shared and unstated legacy review status remains usable', () => {
  assert.equal(typeof model.normalizeQuestion, 'function');
  assert.equal(model.normalizeQuestion(' 课程多少钱？！ '), model.normalizeQuestion('课程多少钱'));
  const candidate = { id: 'candidate', kind: 'qa', question: '课程多少钱？', answer: '4280 元。' };
  const legacy = { id: 'legacy', question: ' 课程 多少钱！ ', answer: '3980 元。' };
  assert.equal(detectCandidateConflicts(candidate, { qaItems: [legacy] }).length, 1);
  assert.equal(detectCandidateConflicts(candidate, { qaItems: [{ ...legacy, reviewStatus: 'pending' }] }).length, 0);
  assert.equal(detectCandidateConflicts(candidate, { qaItems: [{ ...legacy, reviewStatus: 'rejected' }] }).length, 0);
  assert.equal(detectCandidateConflicts({ kind: 'fact', name: '手续费', value: '39.80', unit: '元' }, { keyFacts: [{ name: '手续费', value: '3980', unit: '元' }] }).length, 1);
});

test('all editable redline options and templates use one closed field and operator vocabulary', () => {
  assert.ok(Array.isArray(model.RULE_FIELDS));
  assert.ok(Array.isArray(model.RULE_OPERATORS));
  assert.ok(Array.isArray(model.RULE_ACTIONS));
  assert.ok(model.RULE_FIELDS.includes('客户资料'));
  assert.ok(model.RULE_OPERATORS.includes('exact'));
  assert.ok(RULE_TEMPLATES.every(item => model.RULE_FIELDS.includes(item.condition.field)));
  assert.ok(RULE_TEMPLATES.every(item => model.RULE_OPERATORS.includes(item.condition.operator)));
  assert.ok(RULE_TEMPLATES.every(item => model.RULE_ACTIONS.includes(item.action)));
});

test('redline hit count uses this expert and the last seven days of run ruleHits only', () => {
  assert.equal(typeof model.ruleHitCount, 'function');
  const current = Date.parse('2026-10-26T12:00:00Z');
  const run = (id, createdAt, extra = {}) => ({ id, agentId: 'agent-1', ruleHits: ['rule-1'], createdAt, ...extra });
  const runs = [
    run('now', '2026-10-26T12:00:00Z'),
    run('recent', '2026-10-23T12:00:00Z', { ruleHits: ['rule-1', 'rule-1'] }),
    run('boundary', '2026-10-19T12:00:00Z'),
    run('old', '2026-10-19T11:59:59Z'),
    run('future', '2026-10-26T12:00:01Z'),
    run('other-expert', '2026-10-23T12:00:00Z', { agentId: 'agent-2' }),
    run('other-rule', '2026-10-23T12:00:00Z', { ruleHits: ['rule-2'] }),
    run('legacy-field', '2026-10-23T12:00:00Z', { ruleHits: [], ruleIds: ['rule-1'] }),
    run('invalid-time', 'not-a-time'),
  ];
  assert.equal(model.ruleHitCount(runs, 'agent-1', 'rule-1', current), 3);
});
