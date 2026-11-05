const list = value => Array.isArray(value) ? value : [];

// Inspect contract target fields only; never match arbitrary prompt/condition strings.
// Registry paths are listed once even when a graph Unit has multiple instances.
export function findPortReferences(config, unitIndex, kind, port) {
  const units = list(config?.units), unit = units[unitIndex];
  const references = [], diagnostics = [];
  if (!unit || !['entry_ports', 'exit_ports'].includes(kind)) return { references, diagnostics };
  const entry = kind === 'entry_ports';
  const add = (path, value, label) => references.push({ path, value, label });
  const unique = units.filter(item => item?.unit_id === unit.unit_id).length === 1;
  if (!unique) diagnostics.push('单元标识重复，外部引用无法唯一归属；请先修复后运行服务端校验。');
  if (!config?.orchestration) {
    units.forEach((owner, index) => {
      list(owner?.exit_ports).forEach((exit, offset) => list(exit?.exits).forEach((target, targetIndex) => {
        if ((entry && unique && target === `${unit.unit_id}.${port}`)
          || (!entry && index === unitIndex && target === `self.${port}`)) {
          add(`$.units[${index}].exit_ports[${offset}].exits[${targetIndex}]`, target, '候选去处');
        }
      }));
    });
    diagnostics.push('R1 仅检查显式候选端口引用；省略端口的单元目标仍由服务端校验。');
    return { references, diagnostics };
  }
  if (config.orchestration.schema_version !== 'unit-graph-v1') {
    diagnostics.push('未知图版本，保留原文；引用影响须由服务端校验确认。');
    return { references, diagnostics };
  }
  const inspect = (graph, owner, ownerIndex, path) => {
    const nodes = list(graph?.nodes);
    const matching = unique ? nodes.filter(node => node?.unit_ref?.unit_id === unit.unit_id
      && node.unit_ref.version === unit.version && Number.isSafeInteger(node.unit_ref.version)) : [];
    const ids = matching.filter(node => typeof node.id === 'string'
      && nodes.filter(other => other?.id === node.id).length === 1).map(node => node.id);
    if (matching.length !== ids.length) diagnostics.push(`${path} 中节点标识不唯一，未猜测歧义引用。`);
    const targets = new Set(entry ? ids.map(id => `${id}.${port}`) : ownerIndex === unitIndex ? [`self.${port}`] : []);
    const sources = new Set(entry ? [] : ids.map(id => `${id}.${port}`));
    const target = (value, location, label) => { if (targets.has(value)) add(location, value, label); };
    if (owner) list(owner.entry_ports).forEach((item, i) => target(item?.goto, `$.units[${ownerIndex}].entry_ports[${i}].goto`, '内容层入口'));
    else target(graph?.entry, `${path}.entry`, '版本入口');
    list(graph?.edges).forEach((edge, i) => {
      if (sources.has(edge?.from)) add(`${path}.edges[${i}].from`, edge.from, '连线起点');
      target(edge?.to, `${path}.edges[${i}].to`, '连线目标');
      target(edge?.exit, `${path}.edges[${i}].exit`, '循环超限去处');
    });
    const contractPath = owner ? `$.units[${ownerIndex}]` : path;
    list((owner || graph)?.on_event).forEach((event, i) => target(event?.goto, `${contractPath}.on_event[${i}].goto`, '边界事件'));
    target((owner || graph)?.fallback?.target, `${contractPath}.fallback.target`, '兜底目标');
    // Wait timeout targets currently resolve in each containing graph, like the canvas projection.
    const visited = new Set();
    nodes.forEach(node => {
      if (!node?.unit_ref || typeof node.unit_ref.unit_id !== 'string') return;
      const candidates = units.map((item, i) => ({ item, i })).filter(({ item }) => item?.unit_id === node?.unit_ref?.unit_id);
      if (candidates.length !== 1) return;
      const { item, i } = candidates[0];
      if (item.version !== node.unit_ref.version || visited.has(i)) return;
      visited.add(i);
      list(item.waits).forEach((wait, offset) => {
        if (typeof wait?.timeoutTo === 'string' && wait.timeoutTo.startsWith('self.')) {
          target(wait.timeoutTo, `$.units[${i}].waits[${offset}].timeoutTo`, '等待超时去处');
        }
      });
    });
  };
  inspect(config.orchestration, null, -1, '$.orchestration');
  units.forEach((owner, i) => {
    if (owner?.body?.kind === 'graph') inspect(owner.body, owner, i, `$.units[${i}].body`);
    else if (!entry && i === unitIndex) list(owner?.on_event).forEach((event, offset) => {
      if (event?.goto === `self.${port}`) add(`$.units[${i}].on_event[${offset}].goto`, event.goto, '边界事件');
    });
  });
  return { references: references.filter((ref, i) => references.findIndex(other => other.path === ref.path) === i), diagnostics };
}
