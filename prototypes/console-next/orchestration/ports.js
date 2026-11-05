const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const lines = text => String(text).split('\n').map(value => value.trim()).filter(Boolean);

// Form-only state. Unknown contract fields remain in value and never enter a UI schema migration.
export function portRows(value, kind) {
  if (!Array.isArray(value) || value.some(port => !object(port) || typeof port.port !== 'string' || port.port.includes('.')
    || (kind === 'entry_ports' ? !Array.isArray(port.requires) || port.requires.some(field => typeof field !== 'string' || field.trim() !== field || field.includes('\n'))
      || (port.goto !== undefined && typeof port.goto !== 'string')
      : !object(port.completion) || (port.completion.llm !== undefined && typeof port.completion.llm !== 'string')
      || (Object.hasOwn(port.completion || {}, 'deterministic') && !object(port.completion.deterministic))
      || (port.exits !== undefined && !Array.isArray(port.exits))))) return null;
  return value.map(port => ({ value: structuredClone(port), port: port.port,
    requires: (port.requires || []).join('\n'), goto: port.goto ?? '',
    deterministicEnabled: Object.hasOwn(port.completion || {}, 'deterministic'),
    deterministic: JSON.stringify(port.completion?.deterministic ?? {}, null, 2),
    llmEnabled: Object.hasOwn(port.completion || {}, 'llm'), llm: port.completion?.llm ?? '',
    exits: JSON.stringify(port.exits ?? [], null, 2),
  }));
}

export function serializePortRows(rows, kind, { graph = false } = {}) {
  if (!Array.isArray(rows) || !['entry_ports', 'exit_ports'].includes(kind)) throw new Error('端口表单已失效');
  const seen = new Set();
  return rows.map(row => {
    const port = String(row.port).trim();
    if (!port || port.includes('.')) throw new Error('端口标识不能为空或包含句点');
    if (seen.has(port)) throw new Error(`端口标识重复：${port}`);
    seen.add(port);
    const result = { ...structuredClone(row.value), port };
    if (kind === 'entry_ports') {
      result.requires = [...new Set(lines(row.requires))];
      if (graph) {
        if (row.goto) result.goto = String(row.goto).trim();
        else delete result.goto;
      }
    } else {
      const completion = { ...result.completion };
      delete completion.deterministic;
      delete completion.llm;
      if (row.deterministicEnabled) {
        const condition = JSON.parse(row.deterministic);
        if (!object(condition)) throw new Error(`${port} 的确定性完成条件必须是 JSON 对象`);
        completion.deterministic = condition;
      }
      if (row.llmEnabled) {
        if (typeof row.llm !== 'string' || !row.llm.trim()) throw new Error(`${port} 的模型完成判据不能为空`);
        completion.llm = row.llm;
      }
      if (!row.deterministicEnabled && !row.llmEnabled) throw new Error(`${port} 至少需要一种完成条件`);
      result.completion = completion;
      // Preserve absence: graph contracts do not require R1 candidate exits.
      if (Object.hasOwn(result, 'exits') || row.exits !== '[]') {
        const exits = JSON.parse(row.exits);
        if (!Array.isArray(exits)) throw new Error(`${port} 的候选去处必须是数组`);
        result.exits = exits;
      }
    }
    return result;
  });
}
