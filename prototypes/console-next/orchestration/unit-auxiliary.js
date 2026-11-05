import { readCondition } from './conditions.js';

const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const supportedEvents = new Set(['user_hangup', 'side_effect_unknown', 'timeout', 'handoff']);
const supportedScopes = new Set(['self', 'subtree']);

function targetSet(targets) {
  return new Set(Array.isArray(targets) ? targets.map(target => typeof target === 'string' ? target : target?.value)
    .filter(value => typeof value === 'string' && value) : []);
}

export function readUnitEventRows(value, targets) {
  if (!Array.isArray(value)) return null;
  const allowedTargets = targetSet(targets);
  const rows = value.map(source => {
    if (!object(source) || !supportedEvents.has(source.event) || !supportedScopes.has(source.scope)
      || !allowedTargets.has(source.goto)) return null;
    let whenText = '{}';
    if (Object.hasOwn(source, 'when')) {
      if (!readCondition(source.when, 0, false)) return null;
      whenText = JSON.stringify(source.when);
    }
    return { source: structuredClone(source), event: source.event, scope: source.scope,
      goto: source.goto, whenEnabled: Object.hasOwn(source, 'when'), whenText };
  });
  return rows.every(Boolean) ? rows : null;
}

export function serializeUnitEventRows(rows, targets) {
  if (!Array.isArray(rows)) throw new Error('边界事件表单已失效');
  const allowedTargets = targetSet(targets);
  return rows.map(row => {
    if (!supportedEvents.has(row.event)) throw new Error('请选择支持的边界事件');
    if (!supportedScopes.has(row.scope)) throw new Error('请选择当前 Unit 支持的事件作用域');
    if (!allowedTargets.has(row.goto)) throw new Error('请选择当前 Unit 可用的事件去处');
    const result = { ...structuredClone(row.source || {}), event: row.event, scope: row.scope, goto: row.goto };
    if (row.whenEnabled) {
      let when;
      try { when = JSON.parse(row.whenText); }
      catch { throw new Error('事件条件必须是有效的 JSON'); }
      if (!readCondition(when, 0, false)) throw new Error('事件条件须为可编辑的确定性条件');
      result.when = when;
    } else delete result.when;
    return result;
  });
}

export function readUnitWaitRows(value, targets) {
  if (!Array.isArray(value)) return null;
  const allowedTargets = targetSet(targets);
  const rows = value.map(source => {
    if (!object(source) || typeof source.on !== 'string' || !source.on.trim()) return null;
    const hasTimeoutMs = Object.hasOwn(source, 'timeoutMs');
    const hasTimeoutTo = Object.hasOwn(source, 'timeoutTo');
    if (hasTimeoutMs !== hasTimeoutTo) return null;
    if (hasTimeoutMs && (!Number.isSafeInteger(source.timeoutMs) || source.timeoutMs < 1
      || !allowedTargets.has(source.timeoutTo))) return null;
    return { source: structuredClone(source), on: source.on,
      timeoutEnabled: hasTimeoutMs, timeoutMs: hasTimeoutMs ? String(source.timeoutMs) : '',
      timeoutTo: hasTimeoutTo ? source.timeoutTo : '' };
  });
  return rows.every(Boolean) ? rows : null;
}

export function serializeUnitWaitRows(rows, targets) {
  if (!Array.isArray(rows)) throw new Error('等待表单已失效');
  const allowedTargets = targetSet(targets);
  return rows.map(row => {
    const on = typeof row.on === 'string' ? row.on.trim() : '';
    if (!on) throw new Error('等待事件名称不能为空');
    const result = { ...structuredClone(row.source || {}), on };
    if (row.timeoutEnabled) {
      const timeoutMs = Number(row.timeoutMs);
      const timeoutTo = String(row.timeoutTo || '');
      if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1 || !allowedTargets.has(timeoutTo)) {
        throw new Error('超时毫秒与去处必须同时填写为有效值');
      }
      result.timeoutMs = timeoutMs;
      result.timeoutTo = timeoutTo;
    } else {
      delete result.timeoutMs;
      delete result.timeoutTo;
    }
    return result;
  });
}
