import { conditionEvents, conditionOperators, readCondition } from './conditions.js';

const operators = {
  eq: '=', ne: '≠', gt: '>', gte: '≥', lt: '<', lte: '≤',
  between: '位于', in: '属于', not_in: '不属于', matches: '匹配',
  exists: '存在', is_set: '非空', is_unset: '为空或未设置',
};
const stateMetrics = { attempts: '尝试次数', runs: '运行次数' };
const stateWindows = { cycle: '本周期', '24h': '24h', forever: '累计' };
const stateOperators = { eq: '=', ne: '≠', gt: '>', gte: '≥', lt: '<', lte: '≤' };
const fallback = '条件结构未识别';

function text(value) {
  return String(value).replace(/\s+/g, ' ').trim();
}

function literal(value) {
  const result = JSON.stringify(value);
  return result ?? String(value);
}

function render(node) {
  if (node.kind === 'always') return '无条件';
  if (node.kind === 'fact') {
    const operator = operators[node.op] || conditionOperators[node.op];
    if (['exists', 'is_set', 'is_unset'].includes(node.op)) return `${text(node.field)} ${operator}`;
    const value = node.op === 'matches' ? `/${text(node.value)}/`
      : node.op === 'between' ? `[${JSON.parse(node.value).join(', ')}]`
        : literal(node.type === 'string' ? node.value : JSON.parse(node.value));
    return `${text(node.field)} ${operator} ${value}`;
  }
  if (node.kind === 'event') {
    let summary = `事件：${conditionEvents[node.event] || node.event}`;
    if (node.attributesText) {
      const attributes = JSON.parse(node.attributesText);
      const details = Object.entries(attributes).slice(0, 3)
        .map(([key, value]) => `${text(key)}=${literal(value)}`).join(', ');
      if (details) summary += ` · ${details}`;
    }
    return summary;
  }
  if (node.kind === 'state') {
    return `${stateMetrics[node.metric]} / ${stateWindows[node.window]} ${stateOperators[node.op]} ${node.value}`;
  }
  if (node.kind === 'llm') return `模型判据：${text(node.prompt)}`;
  if (['all_of', 'all'].includes(node.kind)) return `全部：${node.children.map(render).join(' 且 ')}`;
  if (['any_of', 'any'].includes(node.kind)) return `任一：${node.children.map(render).join(' 或 ')}`;
  if (['none_of', 'not'].includes(node.kind)) return `不满足：${render(node.children[0])}`;
  return fallback;
}

export function conditionSummary(condition) {
  try {
    const parsed = typeof condition === 'string' ? JSON.parse(condition) : condition;
    const node = readCondition(parsed);
    if (!node) return fallback;
    const summary = text(render(node));
    const characters = Array.from(summary);
    return characters.length > 80 ? `${characters.slice(0, 79).join('')}…` : summary;
  } catch {
    return fallback;
  }
}
