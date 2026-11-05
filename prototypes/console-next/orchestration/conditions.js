const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
export const conditionOperators = {
  eq: '等于', ne: '不等于', gt: '大于', gte: '大于等于', lt: '小于', lte: '小于等于',
  between: '位于区间', in: '属于列表', not_in: '不属于列表', matches: '匹配文本模式',
  exists: '字段存在', is_set: '值非空', is_unset: '值为空或不存在',
};
const unary = new Set(['exists', 'is_set', 'is_unset']);
const stateMetrics = new Set(['attempts', 'runs']);
const stateWindows = new Set(['cycle', '24h', 'forever']);
const stateOperators = new Set(['eq', 'ne', 'gt', 'gte', 'lt', 'lte']);
// Mirrors the shared configuration validator's known event vocabulary.
export const conditionEvents = {
  tool_call: '工具调用', route_step: '路由步骤', recall_hit: '检索命中', input_matched: '输入匹配',
  channel: '渠道事件', attempts: '尝试事件', user_hangup: '用户挂断', timeout: '超时',
  side_effect_unknown: '业务结果不明', human_takeover: '人工接管', handoff: '移交人工',
};

export function literalType(value) {
  if (value === null) return 'null';
  if (Array.isArray(value)) return 'array';
  if (['string', 'number', 'boolean'].includes(typeof value)) return typeof value;
  return null;
}

export function readCondition(value, depth = 0, allowModel = true) {
  if (!object(value)) return null;
  if (!Object.keys(value).length) return { kind: 'always' };
  if (Object.keys(value).length !== 1) return null;
  for (const key of ['all_of', 'any_of', 'none_of', 'all', 'any', 'not']) {
    if (!Object.hasOwn(value, key)) continue;
    if (depth >= 2 || !Array.isArray(value[key]) || !value[key].length
      || (['none_of', 'not'].includes(key) && value[key].length !== 1)) return null;
    const children = value[key].map(child => readCondition(child, depth + 1, allowModel && !['none_of', 'not'].includes(key)));
    return children.every(Boolean) ? { kind: key, children } : null;
  }
  if (Object.hasOwn(value, 'llm')) {
    const model = value.llm;
    if (!allowModel || !object(model) || Object.keys(model).length !== 1
      || typeof model.prompt !== 'string' || !model.prompt.trim()) return null;
    return { kind: 'llm', prompt: model.prompt };
  }
  if (Object.hasOwn(value, 'event')) {
    const event = value.event;
    if (!object(event) || !Object.hasOwn(conditionEvents, event.event)) return null;
    const keys = Object.keys(event);
    if (keys.some(key => !['event', 'attributes'].includes(key))) return null;
    if (Object.hasOwn(event, 'attributes') && !object(event.attributes)) return null;
    return { kind: 'event', event: event.event,
      attributesText: Object.hasOwn(event, 'attributes') ? JSON.stringify(event.attributes, null, 2) : '' };
  }
  if (Object.hasOwn(value, 'state')) {
    const state = value.state;
    if (!object(state) || Object.keys(state).some(key => !['metric', 'window', 'op', 'value'].includes(key))
      || !stateMetrics.has(state.metric) || !stateWindows.has(state.window) || !stateOperators.has(state.op)
      || !Object.hasOwn(state, 'value') || typeof state.value !== 'number' || !Number.isFinite(state.value)) return null;
    return { kind: 'state', metric: state.metric, window: state.window, op: state.op,
      value: String(state.value) };
  }
  const atom = value.fact;
  if (!object(atom) || typeof atom.field !== 'string' || !Object.hasOwn(conditionOperators, atom.op)
    || Object.keys(atom).some(key => !['field', 'op', 'value'].includes(key))) return null;
  if (atom.op === 'matches' && typeof atom.value !== 'string') return null;
  // Do not discard a legacy operator's unexpected value or coerce an object literal.
  if (unary.has(atom.op) && Object.hasOwn(atom, 'value')) return null;
  const type = unary.has(atom.op) || atom.op === 'matches' ? 'string' : atom.op === 'between' ? 'range' : literalType(atom.value);
  if (!type) return null;
  if (atom.op === 'between' && (!Array.isArray(atom.value) || atom.value.length !== 2
    || atom.value.some(value => typeof value !== 'number' || !Number.isFinite(value))
    || atom.value[0] > atom.value[1])) return null;
  return { kind: 'fact', field: atom.field, op: atom.op, type,
    value: type === 'string' ? atom.value ?? '' : JSON.stringify(atom.value) };
}

export function writeCondition(node, depth = 0, allowModel = true) {
  if (node.kind === 'always') return {};
  if (['all_of', 'any_of', 'none_of', 'all', 'any', 'not'].includes(node.kind)) {
    if (depth >= 2) throw new Error('组合条件最多嵌套两层');
    if (!node.children?.length || (['none_of', 'not'].includes(node.kind) && node.children.length !== 1)) throw new Error('组合条件缺少子条件');
    const negative = ['none_of', 'not'].includes(node.kind);
    return { [node.kind]: node.children.map(child => writeCondition(child, depth + 1, allowModel && !negative)) };
  }
  if (node.kind === 'llm') {
    if (!allowModel) throw new Error('模型判据仅允许用于正向图边条件');
    if (typeof node.prompt !== 'string' || !node.prompt.trim()) throw new Error('请填写模型判据');
    return { llm: { prompt: node.prompt } };
  }
  if (node.kind === 'event') {
    if (!Object.hasOwn(conditionEvents, node.event)) throw new Error('请选择已支持的事件名称');
    if (!node.attributesText?.trim()) return { event: { event: node.event } };
    let attributes;
    try { attributes = JSON.parse(node.attributesText); }
    catch { throw new Error('事件属性必须是有效的 JSON 对象'); }
    if (!object(attributes)) throw new Error('事件属性必须是 JSON 对象');
    if (Object.keys(attributes).some(key => !key.trim())) throw new Error('事件属性名不能为空');
    return { event: { event: node.event, attributes } };
  }
  if (node.kind === 'state') {
    if (!stateMetrics.has(node.metric) || !stateWindows.has(node.window) || !stateOperators.has(node.op)) {
      throw new Error('请选择已支持的状态窗口、指标和比较方式');
    }
    if (typeof node.value !== 'string' || !node.value.trim()) throw new Error('状态窗口比较值必须是有限数字');
    const value = Number(node.value);
    if (!Number.isFinite(value)) throw new Error('状态窗口比较值必须是有限数字');
    return { state: { metric: node.metric, window: node.window, op: node.op, value } };
  }
  if (node.kind !== 'fact' || !node.field?.trim() || !Object.hasOwn(conditionOperators, node.op)) throw new Error('请填写字段并选择比较方式');
  const fact = { field: node.field, op: node.op };
  if (node.op === 'matches') {
    if (node.type !== 'string' || typeof node.value !== 'string') throw new Error('匹配模式必须是文本');
    fact.value = node.value;
  } else if (!unary.has(node.op)) {
    if (node.op === 'between') {
      try { fact.value = JSON.parse(node.value); }
      catch { throw new Error('区间需要两个有限数字且下限不大于上限'); }
      if (!Array.isArray(fact.value) || fact.value.length !== 2
        || fact.value.some(value => typeof value !== 'number' || !Number.isFinite(value))
        || fact.value[0] > fact.value[1]) throw new Error('区间需要两个有限数字且下限不大于上限');
    } else if (node.type === 'string') fact.value = node.value;
    else if (node.type === 'null') fact.value = null;
    else {
      try { fact.value = JSON.parse(node.value); }
      catch { throw new Error('比较值与所选类型不符'); }
      if (literalType(fact.value) !== node.type || (node.type === 'number' && !Number.isFinite(fact.value))) throw new Error('比较值与所选类型不符');
    }
    if (['in', 'not_in'].includes(node.op) && !Array.isArray(fact.value)) throw new Error('列表比较需要数组值');
    if (['gt', 'gte', 'lt', 'lte'].includes(node.op) && typeof fact.value !== 'number') throw new Error('数值比较需要数字值');
  }
  return { fact };
}

export function newCondition(kind) {
  if (kind === 'llm') return { kind, prompt: '' };
  if (kind === 'event') return { kind, event: '' };
  if (kind === 'state') return { kind, metric: 'attempts', window: '24h', op: 'gt', value: '0' };
  if (kind === 'fact') return { kind, field: '', op: 'eq', type: 'string', value: '' };
  if (kind === 'always') return { kind };
  return { kind, children: [{ kind: 'fact', field: '', op: 'exists', type: 'string', value: '' }] };
}
