const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const nonempty = value => typeof value === 'string' && value.trim();

export function scopeForm(scope) {
  if (scope === undefined) return { mode: 'all', after: '', exclude: '' };
  if (!object(scope)) return null;
  if (Object.hasOwn(scope, 'after') && !nonempty(scope.after)) return null;
  if (Object.hasOwn(scope, 'exclude') && (!Array.isArray(scope.exclude) || !scope.exclude.length
    || !scope.exclude.every(nonempty) || new Set(scope.exclude).size !== scope.exclude.length)) return null;
  if (!Object.hasOwn(scope, 'after') && !Object.hasOwn(scope, 'exclude')) return null;
  return { mode: scope.after ? (scope.exclude ? 'both' : 'after') : 'exclude',
    after: scope.after || '', exclude: scope.exclude?.join('\n') || '' };
}

export function serializeScope(scope, form) {
  if (scopeForm(scope) === null) throw new Error('当前加载范围需先通过原始 JSON 修复');
  if (!['all', 'after', 'exclude', 'both'].includes(form.mode)) throw new Error('请选择加载范围');
  const next = structuredClone(scope || {});
  delete next.after;
  delete next.exclude;
  if (['after', 'both'].includes(form.mode)) {
    const after = String(form.after || '').trim();
    if (!after) throw new Error('请填写起始路由单元');
    next.after = after;
  }
  if (['exclude', 'both'].includes(form.mode)) {
    const exclude = String(form.exclude || '').split(/[\n,，]/).map(value => value.trim()).filter(Boolean);
    if (!exclude.length || new Set(exclude).size !== exclude.length) throw new Error('请填写不重复的排除单元');
    next.exclude = exclude;
  }
  return Object.keys(next).length ? next : undefined;
}
