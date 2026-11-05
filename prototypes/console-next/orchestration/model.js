// This is a projection of the persisted contract, never a second configuration.
import { scopeForm } from './concurrent-scope.js';
import { conditionSummary } from './condition-summary.js';
const array = value => Array.isArray(value) ? value : [];
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
export const unitKey = index => `unit:${index}`;

export function unitAuxiliaryTargets(config, unit) {
  if (!object(config) || !object(unit)) return [];
  const targets = [];
  if (unit.body?.kind === 'graph') {
    const units = array(config.units);
    const registry = new Map();
    units.forEach(candidate => {
      if (!object(candidate) || typeof candidate.unit_id !== 'string') return;
      if (registry.has(candidate.unit_id)) registry.set(candidate.unit_id, null);
      else registry.set(candidate.unit_id, candidate);
    });
    const nodes = array(unit.body.nodes);
    const localIdCounts = new Map();
    for (const node of nodes) {
      if (typeof node?.id === 'string') localIdCounts.set(node.id, (localIdCounts.get(node.id) || 0) + 1);
    }
    for (const node of nodes) {
      if (!object(node) || typeof node.id !== 'string' || !node.id || node.id.includes('.') || localIdCounts.get(node.id) !== 1) continue;
      const ref = node.unit_ref;
      const child = object(ref) ? registry.get(ref.unit_id) : null;
      if (!child || child.load_mode !== 'routed' || !Number.isSafeInteger(ref.version) || ref.version < 1 || child.version !== ref.version) continue;
      const portCounts = new Map();
      for (const port of array(child.entry_ports)) {
        if (typeof port?.port === 'string') portCounts.set(port.port, (portCounts.get(port.port) || 0) + 1);
      }
      for (const port of array(child.entry_ports)) {
        if (typeof port?.port !== 'string' || !port.port.trim() || port.port.includes('.') || portCounts.get(port.port) !== 1) continue;
        targets.push({ value: `${node.id}.${port.port}`, label: `${child.unit_id} · ${port.port}` });
      }
    }
  }
  const exitPortCounts = new Map();
  for (const port of array(unit.exit_ports)) {
    if (typeof port?.port === 'string') exitPortCounts.set(port.port, (exitPortCounts.get(port.port) || 0) + 1);
  }
  for (const port of array(unit.exit_ports)) {
    if (typeof port?.port !== 'string' || !port.port.trim() || port.port.includes('.') || exitPortCounts.get(port.port) !== 1) continue;
    targets.push({ value: `self.${port.port}`, label: `${unit.unit_id} · ${port.port}` });
  }
  return targets;
}

function concurrentLoadScope(scope) {
  if (scope === undefined) return { mode: 'all', label: '全池可召回' };
  if (scopeForm(scope) === null) return { mode: 'invalid', label: '加载范围结构待修复' };
  const after = typeof scope.after === 'string' && scope.after.trim() ? scope.after.trim() : null;
  const exclude = Array.isArray(scope.exclude) ? scope.exclude.filter(item => typeof item === 'string' && item.trim()) : [];
  const mode = after && exclude.length ? 'after_and_exclude' : after ? 'after' : exclude.length ? 'exclude' : 'invalid';
  if (mode === 'invalid') return { mode, label: '加载范围结构待修复' };
  const labels = [];
  if (after) labels.push(`第 ${after} 步之后`);
  if (exclude.length) labels.push(`排除 ${exclude.join('、')}`);
  return { mode, after, exclude, label: labels.join('；') };
}

const concurrentConfig = config => object(config?.concurrent_config) ? config.concurrent_config : null;

// The flat list has no edge records. This read-only projection exposes the same
// fields the graph layer does, so readers never have to guess. A candidate exit
// is gated by its source port's completion, re-encoded in the condition shape
// (no condition is invented); absent cycle bounds stay absent, so the canvas
// falls back to window/max_rounds/counter/exit being undefined. The id is derived
// from unit ids rather than array positions, so reordering the registry is not a
// topology change.
function candidateEdgeConfig(unit, port, target, id) {
  const completion = object(port.completion) ? port.completion : {};
  const condition = object(completion.deterministic) ? completion.deterministic
    : typeof completion.llm === 'string' && completion.llm.trim() ? { llm: { prompt: completion.llm } }
      : {};
  return Object.freeze({ id, from: `${unit.unit_id}.${port.port}`, to: target, condition });
}

export function projectOrchestration(config, layerPath = []) {
  if (config && Object.hasOwn(config, 'orchestration')) return projectGraph(config, layerPath);
  const units = array(config?.units);
  const issues = [{ path: '$.orchestration', message: '当前草稿没有 unit-graph-v1 图合同，画布按旧清单的候选出口投影；无法解析的结构请展开原始 Unit 清单修复。' }];
  if (!Array.isArray(config?.units)) issues.push({ path: '$.units', message: '单元清单格式错误，请在原始清单中修复。' });
  const nodes = [], concurrent = [], edges = [], events = [];
  const indexById = new Map();
  units.forEach((unit, index) => {
    if (!object(unit) || typeof unit.unit_id !== 'string' || !unit.unit_id.trim()) {
      issues.push({ path: `$.units[${index}]`, message: '单元缺少有效标识，请在原始清单中修复。' });
      return;
    }
    if (indexById.has(unit.unit_id)) {
      issues.push({ path: `$.units[${index}].unit_id`, message: `单元标识 ${unit.unit_id} 重复，目标引用存在歧义。` });
      indexById.set(unit.unit_id, null);
    } else indexById.set(unit.unit_id, index);
    const node = { id: unitKey(index), index, unit, entry: array(config?.persona?.entry_unit_ids).includes(unit.unit_id),
      loadScope: concurrentLoadScope(unit.load_scope) };
    if (unit.load_mode === 'concurrent') concurrent.push(node);
    else if (unit.load_mode === 'routed') nodes.push(node);
    else issues.push({ path: `$.units[${index}].load_mode`, message: '未知加载方式，保留原文并阻止画成路由单元。' });
    if (unit.body && (!object(unit.body) || Object.keys(unit.body).length)) {
      issues.push({ path: `$.units[${index}].body`, message: '此首片尚不展开内容层；保留 body 原文，服务端仍决定能否冻结。' });
    }
    array(unit.on_event).forEach((event, eventIndex) => {
      if (object(event)) events.push({ ...event, owner: unit.unit_id, path: `$.units[${index}].on_event[${eventIndex}]` });
    });
  });
  nodes.forEach(({ unit, index, id }) => {
    array(unit.exit_ports).forEach((port, portIndex) => {
      if (!object(port) || typeof port.port !== 'string') return;
      array(port.exits).forEach((target, targetIndex) => {
        const path = `$.units[${index}].exit_ports[${portIndex}].exits[${targetIndex}]`;
        if (typeof target !== 'string') {
          issues.push({ path, message: '当前投影不识别此目标引用，已保留原文。' });
          return;
        }
        // A self.port is the unit's own completion endpoint, not an execution loop.
        if (target.startsWith('self.')) return;
        const exactIndex = indexById.get(target);
        let destination = exactIndex, entryPort = null;
        if (exactIndex === undefined) {
          const candidates = [...indexById].filter(([name, offset]) => offset !== null && target.startsWith(`${name}.`));
          if (candidates.length === 1) {
            destination = candidates[0][1];
            entryPort = target.slice(candidates[0][0].length + 1);
          }
        }
        if (destination === undefined || destination === null || units[destination]?.load_mode !== 'routed'
          || (entryPort && !array(units[destination]?.entry_ports).some(item => item?.port === entryPort))) {
          issues.push({ path, message: `目标 ${target} 无法唯一解析为本层路由单元或入口端口。` });
          return;
        }
        edges.push({ id: `exit:${index}:${portIndex}:${targetIndex}`, source: id, target: unitKey(destination),
          sourcePort: port.port, entryPort, portIndex, targetIndex, path,
          // exits is a candidate set. Its array order is NOT edge_order.
          label: `${port.port} → ${entryPort || '单元入口'} · 候选出口`,
          edgeConfig: candidateEdgeConfig(unit, port, target, `exit:${unit.unit_id}:${port.port}:${target}`) });
      });
    });
  });
  return { nodes, concurrent, concurrentConfig: concurrentConfig(config), edges, waitEdges: [], events, issues };
}

function graphUnitIndex(config, node) {
  const ref = node?.unit_ref;
  if (!object(ref) || typeof ref.unit_id !== 'string' || !Number.isSafeInteger(ref.version)) return null;
  const units = array(config?.units);
  const matches = units.map((unit, index) => ({ unit, index })).filter(item => item.unit?.unit_id === ref.unit_id);
  if (matches.length !== 1 || matches[0].unit.version !== ref.version || matches[0].unit.load_mode !== 'routed') return null;
  return matches[0].index;
}

function findUnitOccurrence(config, targetIndex) {
  const units = array(config?.units), found = [];
  const visit = (graph, layerPath, ancestors) => {
    array(graph?.nodes).forEach((node, configIndex) => {
      if (typeof node?.id !== 'string' || !node.id || node.id.includes('.')
        || array(graph.nodes).filter(candidate => candidate?.id === node.id).length !== 1) return;
      const unitIndex = graphUnitIndex(config, node);
      if (unitIndex === null) return;
      if (unitIndex === targetIndex) found.push({ layerPath, localId: node.id, configIndex });
      const unit = units[unitIndex];
      if (unit?.body?.kind === 'graph' && !ancestors.has(unitIndex)) {
        visit(unit.body, [...layerPath, node.id], new Set([...ancestors, unitIndex]));
      }
    });
  };
  if (config?.orchestration?.schema_version === 'unit-graph-v1') visit(config.orchestration, [], new Set());
  return found.length === 1 ? found[0] : null;
}

function graphAtLayer(config, layerPath) {
  let graph = config?.orchestration;
  for (const localId of layerPath) {
    const matches = array(graph?.nodes).filter(node => node?.id === localId);
    if (matches.length !== 1) return null;
    const unitIndex = graphUnitIndex(config, matches[0]);
    const body = unitIndex === null ? null : array(config?.units)[unitIndex]?.body;
    if (body?.kind !== 'graph') return null;
    graph = body;
  }
  return graph;
}

function locateGraphEntry(config, layerPath, relativePath, fieldPath) {
  const match = /^(nodes|edges)\[(0|[1-9]\d*)\](?:\.(.*))?$/.exec(relativePath);
  if (!match) return null;
  const configIndex = Number(match[2]);
  if (!Number.isSafeInteger(configIndex)) return null;
  const graph = graphAtLayer(config, layerPath);
  if (!graph) return null;
  if (match[1] === 'edges') {
    if (!object(array(graph.edges)[configIndex])) return null;
    return { layerPath, kind: 'edge', configIndex, fieldPath };
  }
  const node = array(graph.nodes)[configIndex];
  if (!object(node) || typeof node.id !== 'string' || !node.id
    || array(graph.nodes).filter(candidate => candidate?.id === node.id).length !== 1) return null;
  const unitIndex = graphUnitIndex(config, node);
  return { layerPath, kind: 'node', localId: node.id, configIndex, ...(unitIndex === null ? {} : { unitIndex }), fieldPath };
}

export function locateValidationIssue(config, path) {
  if (typeof path !== 'string') return null;
  const rootGraph = /^\$\.orchestration\.(.+)$/.exec(path);
  if (rootGraph) return locateGraphEntry(config, [], rootGraph[1], path);

  const unitPath = /^\$\.units\[(0|[1-9]\d*)\](?:\.(.*))?$/.exec(path);
  if (!unitPath) return null;
  const unitIndex = Number(unitPath[1]), unit = array(config?.units)[unitIndex];
  if (!Number.isSafeInteger(unitIndex) || !object(unit)) return null;
  const rest = unitPath[2] || '';

  if (config?.orchestration?.schema_version !== 'unit-graph-v1') {
    if (unit.load_mode === 'concurrent') return { layerPath: [], kind: 'concurrent', localId: unitKey(unitIndex), unitIndex, fieldPath: path };
    if (unit.load_mode === 'routed') return { layerPath: [], kind: 'node', localId: unitKey(unitIndex), configIndex: unitIndex, unitIndex, fieldPath: path };
    return null;
  }

  const occurrence = findUnitOccurrence(config, unitIndex);
  if (!occurrence) {
    if (unit.load_mode === 'concurrent') return { layerPath: [], kind: 'concurrent', localId: unitKey(unitIndex), unitIndex, fieldPath: path };
    return null;
  }
  if (rest.startsWith('body.')) {
    const bodyPath = rest.slice('body.'.length);
    const nested = locateGraphEntry(config, [...occurrence.layerPath, occurrence.localId], bodyPath, path);
    if (nested) return nested;
  }
  const port = /(?:^|\.)(entry_ports|exit_ports)\[(0|[1-9]\d*)\](?:\.([A-Za-z_$][\w$]*))?/.exec(rest);
  return { ...occurrence, kind: 'node', unitIndex, fieldPath: path,
    ...(port ? { portKind: port[1], portIndex: Number(port[2]), portField: port[3] || null } : {}) };
}

// Local node instances reference the same Unit; selecting/editing either
// instance updates its registry index, never an inlined copy of the contract.
function projectGraph(config, layerPath) {
  const issues = [], nodes = [], edges = [], waitEdges = [], events = [], concurrent = [];
  const result = { nodes, edges, waitEdges, events, concurrent, concurrentConfig: concurrentConfig(config), issues, advisories: [], versioned: true, breadcrumbs: [{ label: '版本路由', path: [] }] };
  if (config.orchestration?.schema_version !== 'unit-graph-v1') {
    issues.push({ path: '$.orchestration.schema_version', message: '无法识别图合同版本；保留原文，不按旧候选出口绘图。' });
    return result;
  }
  const units = array(config.units), registry = new Map();
  units.forEach((unit, index) => {
    if (!object(unit) || typeof unit.unit_id !== 'string') return;
    if (registry.has(unit.unit_id)) registry.set(unit.unit_id, null);
    else registry.set(unit.unit_id, { unit, index });
    if (unit.load_mode === 'concurrent') concurrent.push({ id: unitKey(index), index, unit, loadScope: concurrentLoadScope(unit.load_scope) });
  });
  const resolve = node => {
    if (!object(node?.unit_ref)) return null;
    const found = registry.get(node.unit_ref.unit_id);
    return found && Number.isSafeInteger(node.unit_ref.version) && node.unit_ref.version > 0
      && node.unit_ref.version === found.unit.version && found.unit.load_mode === 'routed' ? found : null;
  };
  let graph = config.orchestration, owner = null, base = '$.orchestration';
  const visited = new Set();
  for (const [depth, localId] of layerPath.entries()) {
    const matches = array(graph.nodes).filter(node => node?.id === localId);
    const found = matches.length === 1 ? resolve(matches[0]) : null;
    if (!found || found.unit.body?.kind !== 'graph' || visited.has(found.index)) {
      issues.push({ path: base, message: '当前下钻路径失效或存在组合环，请返回上层修复。' });
      return result;
    }
    visited.add(found.index);
    owner = found.unit; graph = found.unit.body; base = `$.units[${found.index}].body`;
    result.breadcrumbs.push({ label: owner.unit_id, path: layerPath.slice(0, depth + 1) });
  }
  const byLocalId = new Map();
  const prefix = JSON.stringify(layerPath);
  array(graph.nodes).forEach((node, index) => {
    const path = `${base}.nodes[${index}]`;
    if (!object(node) || typeof node.id !== 'string' || !node.id || node.id.includes('.') || byLocalId.has(node.id)) {
      issues.push({ path, message: '本层节点标识无效或重复，保留原文。' });
      if (typeof node?.id === 'string') byLocalId.set(node.id, null);
      return;
    }
    const found = resolve(node);
    if (!found) {
      issues.push({ path: `${path}.unit_ref`, message: '单元引用缺失、版本不匹配或不是路由单元。' });
      return;
    }
    const entries = owner ? array(owner.entry_ports).map(port => port?.goto) : [graph.entry];
    const projected = { ...found, id: `${prefix}:node:${node.id}`, localId: node.id, configIndex: index,
      entry: entries.some(target => typeof target === 'string' && target.split('.')[0] === node.id) };
    byLocalId.set(node.id, projected); nodes.push(projected);
  });
  // Remove ambiguous instances, rather than drawing the first one as truth.
  for (let i = nodes.length - 1; i >= 0; i--) if (!byLocalId.get(nodes[i].localId)) nodes.splice(i, 1);
  const terminal = target => {
    if (owner ? !array(owner.exit_ports).some(port => target === `self.${port?.port}`) : target !== 'end') return null;
    const id = `${prefix}:terminal:${target}`;
    if (!nodes.some(node => node.id === id)) nodes.push({ id, terminal: true, unit: { unit_id: target === 'end' ? '结束路由' : `出口 ${target.slice(5)}`, entry_ports: [{ port: 'in' }], exit_ports: [] } });
    return { id, entryPort: 'in' };
  };
  const edgeKeyCounts = new Map();
  array(graph.edges).forEach((edge, index) => {
    const path = `${base}.edges[${index}]`;
    const parts = value => typeof value === 'string' && value.split('.').length === 2 ? value.split('.') : [];
    const [sourceId, sourcePort] = parts(edge?.from), [targetId, entryPort] = parts(edge?.to);
    const source = byLocalId.get(sourceId), target = byLocalId.get(targetId);
    const portIndex = array(source?.unit.exit_ports).findIndex(port => port?.port === sourcePort);
    const destination = target && array(target.unit.entry_ports).some(port => port?.port === entryPort)
      ? { id: target.id, entryPort } : terminal(edge?.to);
    if (!source || portIndex < 0 || !destination) {
      issues.push({ path, message: '连接无法解析为本层出口与入口，未绘制此边。' }); return;
    }
    const contractId = typeof edge.id === 'string' && edge.id ? edge.id : `index-${index}`;
    const duplicate = edgeKeyCounts.get(contractId) || 0;
    edgeKeyCounts.set(contractId, duplicate + 1);
    edges.push({ id: `${prefix}:edge:${index}`, key: `${prefix}:edge-key:${contractId}${duplicate ? `:${duplicate}` : ''}`,
      source: source.id, target: destination.id, portIndex, entryPort: destination.entryPort, sourcePort,
      path, configIndex: index, layerPath: [...layerPath], edgeConfig: edge, order: index, candidate: false,
      label: `${index + 1} · ${sourcePort} → ${destination.entryPort}${edge.max_rounds ? ` · 循环≤${edge.max_rounds}` : ''} · ${conditionSummary(edge.condition)}` });
  });
  for (const source of nodes.filter(node => !node.terminal)) {
    array(source.unit.waits).forEach((wait, index) => {
      if (!object(wait) || typeof wait.timeoutTo !== 'string' || !wait.timeoutTo.trim()) return;
      const targetText = wait.timeoutTo;
      let destination = null;
      if (targetText === 'end' || targetText.startsWith('self.')) destination = terminal(targetText);
      else {
        const exact = byLocalId.get(targetText);
        const candidates = exact ? [exact] : nodes.filter(node => !node.terminal && node.unit.unit_id === targetText);
        if (candidates.length === 1) destination = { id: candidates[0].id };
      }
      if (!destination) {
        issues.push({ path: `$.units[${source.index}].waits[${index}].timeoutTo`, message: `超时目标 ${targetText} 无法唯一解析为当前层节点或本层出口，未绘制此连接。` });
        return;
      }
      waitEdges.push({ id: `${prefix}:wait:${source.localId}:${index}`, source: source.id, target: destination.id,
        wait: true, timeoutMs: wait.timeoutMs, path: `$.units[${source.index}].waits[${index}]`,
        label: `超时${wait.timeoutMs ? ` ≤${wait.timeoutMs}ms` : ''} → ${targetText}` });
    });
  }
  result.edgeCount = array(graph.edges).length;
  result.edgeSources = nodes.filter(node => !node.terminal).flatMap(node =>
    array(node.unit.exit_ports).filter(port => typeof port?.port === 'string')
      .map(port => ({ value: `${node.localId}.${port.port}`, label: `${node.unit.unit_id} · ${port.port}` })));
  result.edgeTargets = nodes.filter(node => !node.terminal).flatMap(node =>
    array(node.unit.entry_ports).filter(port => typeof port?.port === 'string')
      .map(port => ({ value: `${node.localId}.${port.port}`, label: `${node.unit.unit_id} · ${port.port}` })));
  if (owner) {
    result.edgeTargets.push(...array(owner.exit_ports).filter(port => typeof port?.port === 'string')
      .map(port => ({ value: `self.${port.port}`, label: `本单元出口 · ${port.port}` })));
  } else {
    result.edgeTargets.push({ value: 'end', label: '结束路由' });
  }
  array(owner?.on_event ?? graph.on_event).forEach((event, index) => {
    if (object(event)) events.push({ ...event, owner: owner?.unit_id || '版本全局', path: `${base}.on_event[${index}]` });
  });
  result.routingMode = graph.routing?.mode;
  const targets = new Set(edges.map(edge => edge.target).filter(Boolean));
  const closedSetSize = targets.size;
  const mode = result.routingMode;
  const threshold = mode === 'deterministic' ? 8 : 5;
  if (mode && closedSetSize > threshold) {
    const strong = mode === 'llm' && closedSetSize > 8;
    result.advisories.push({ key: `closed-set:${JSON.stringify(layerPath)}`, level: strong ? 'strong' : 'notice', closedSetSize, edgeCount: edges.length,
      message: mode === 'deterministic'
        ? `分支已多（闭集 ${closedSetSize}），确认条件互斥与兜底仍可读。`
        : mode === 'hybrid'
          ? `筛前闭集 ${closedSetSize} 个候选，确认筛选后仍不会过宽。`
          : `本层由模型选择，${closedSetSize} 个候选已超出稳定区间。`,
      alternatives: '可合并入口、拆包、改用确定性路由，或先分大类再在类内选择。' });
  }
  return result;
}

export function configurationReadOnly(state) {
  return state.status !== 'ready' || state.busy || Boolean(state.readOnlySnapshot || state.selectedCandidate || state.comparison);
}
