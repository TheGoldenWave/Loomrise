import { projectOrchestration } from './model.js';

const list = value => Array.isArray(value) ? value : [];
const member = (path, key, value) => `${path}[${key}=${JSON.stringify(value)}]`;
const inside = (path, parent) => path === parent || path.startsWith(`${parent}.`) || path.startsWith(`${parent}[`);
const recognized = change => ['added', 'removed', 'changed', 'priority'].includes(change.operation);
const statusFor = changes => changes.some(change => ['added', 'removed', 'changed'].includes(change.operation)) ? 'changed' : null;

function uniqueIndex(items, identity) {
  const result = new Map();
  for (const item of items) {
    const key = identity(item);
    if (typeof key !== 'string' || !key) return null;
    if (result.has(key)) return null;
    result.set(key, item);
  }
  return result;
}

function layerInfo(config, layerPath) {
  if (config?.orchestration?.schema_version !== 'unit-graph-v1') return null;
  let graph = config.orchestration, path = '$.orchestration';
  const registry = uniqueIndex(list(config.units), unit => unit?.unit_id);
  if (!registry) return null;
  const visited = new Set();
  for (const id of layerPath) {
    const nodes = list(graph.nodes).filter(node => node?.id === id);
    const reference = nodes.length === 1 ? nodes[0].unit_ref : null;
    const unit = registry.get(reference?.unit_id);
    if (!unit || unit.version !== reference.version || unit.body?.kind !== 'graph' || visited.has(unit.unit_id)) return null;
    visited.add(unit.unit_id);
    graph = unit.body;
    path = `${member('$.units', 'unit_id', unit.unit_id)}.body`;
  }
  return { graph, path };
}

// Highlight rows are supplied by the shared comparison API. Snapshot projection
// contributes only topology and deleted-object geometry, never a second field diff.
export function projectComparison(comparison, layerPath = []) {
  const beforeConfig = comparison.before.config, afterConfig = comparison.after.config;
  const before = projectOrchestration(beforeConfig, layerPath), after = projectOrchestration(afterConfig, layerPath);
  const beforeLayer = layerInfo(beforeConfig, layerPath), afterLayer = layerInfo(afterConfig, layerPath);
  const changes = list(comparison.object_diff?.changes);
  const rows = (type, path) => path ? changes.filter(change => change.object_type === type && recognized(change) && inside(change.path, path)) : [];
  const allRows = path => changes.filter(change => inside(change.path, path));
  const base = afterLayer || !beforeLayer ? after : before;
  const model = { ...base, comparison: true,
    issues: [...(beforeLayer || !layerPath.length ? before.issues : []), ...(afterLayer || !layerPath.length ? after.issues : []), ...list(comparison.object_diff?.diagnostics)],
    advisories: [], nodes: [], concurrent: [], edges: [], waitEdges: [],
  };
  const nodeIdentity = node => node.comparisonIdentity ?? (node.terminal ? `terminal:${node.id.split(':terminal:').at(-1)}` : node.localId || node.unit.unit_id);
  const makeNodes = (left, right) => {
    const leftMap = uniqueIndex(left, nodeIdentity), rightMap = uniqueIndex(right, nodeIdentity);
    if (!leftMap || !rightMap) {
      model.issues.push({ path: '$', message: '节点标识无法唯一对齐；画布保留目标版本，请查看字段差异。' });
      return right;
    }
    return [...new Set([...rightMap.keys(), ...leftMap.keys()])].map(identity => {
      const old = leftMap.get(identity), next = rightMap.get(identity), source = next || old;
      const node = { ...source, comparisonIdentity: identity, id: `comparison:${JSON.stringify([...layerPath, identity])}` };
      const oldUnitPath = old && !old.terminal ? member('$.units', 'unit_id', old.unit.unit_id) : null;
      const newUnitPath = next && !next.terminal ? member('$.units', 'unit_id', next.unit.unit_id) : null;
      const unitPaths = [...new Set([oldUnitPath, newUnitPath].filter(Boolean))];
      const nodePaths = [beforeLayer, afterLayer].filter(Boolean).map(layer => member(`${layer.path}.nodes`, 'id', source.localId));
      const ownChanges = [...new Set([...unitPaths.flatMap(path => rows('unit', path)), ...nodePaths.flatMap(path => rows('node', path))])];
      const details = [...new Set([...unitPaths.flatMap(allRows), ...nodePaths.flatMap(allRows)])];
      const status = !old ? 'added' : !next ? 'removed' : statusFor(ownChanges);
      node.comparison = { status, changes: details, before: old?.unit ?? null, after: next?.unit ?? null,
        ports: { entry_ports: {}, exit_ports: {} } };
      if (node.terminal) return node;
      node.unit = { ...source.unit };
      for (const kind of ['entry_ports', 'exit_ports']) {
        const oldPorts = uniqueIndex(list(old?.unit[kind]), port => port?.port);
        const newPorts = uniqueIndex(list(next?.unit[kind]), port => port?.port);
        if (!oldPorts || !newPorts) continue;
        node.unit[kind] = [...new Set([...newPorts.keys(), ...oldPorts.keys()])].map(id => {
          const previous = oldPorts.get(id), current = newPorts.get(id);
          const portChanges = [...new Set(unitPaths.flatMap(path => rows(kind === 'entry_ports' ? 'entry_port' : 'exit_port', member(`${path}.${kind}`, 'port', id))))];
          node.comparison.ports[kind][id] = { status: !previous ? 'added' : !current ? 'removed' : statusFor(portChanges), changes: portChanges };
          return structuredClone(current || previous);
        });
      }
      return node;
    });
  };
  model.nodes = makeNodes(before.nodes, after.nodes);
  model.concurrent = makeNodes(before.concurrent, after.concurrent);
  const nodeByIdentity = new Map(model.nodes.map(node => [nodeIdentity(node), node]));
  const oldNodes = new Map(before.nodes.map(node => [node.id, nodeByIdentity.get(nodeIdentity(node))]));
  const newNodes = new Map(after.nodes.map(node => [node.id, nodeByIdentity.get(nodeIdentity(node))]));
  const edgeIdentity = (edge, mapping) => edge.edgeConfig?.id || (edge.wait ? edge.id : JSON.stringify([
    mapping.get(edge.source)?.comparisonIdentity, edge.sourcePort,
    mapping.get(edge.target)?.comparisonIdentity, edge.entryPort,
  ]));
  const makeEdges = (left, right) => {
    const leftMap = uniqueIndex(left, edge => edgeIdentity(edge, oldNodes));
    const rightMap = uniqueIndex(right, edge => edgeIdentity(edge, newNodes));
    if (!leftMap || !rightMap) {
      model.issues.push({ path: '$', message: '连线标识无法唯一对齐；请查看对象与字段差异。' });
      return [];
    }
    return [...new Set([...rightMap.keys(), ...leftMap.keys()])].flatMap(identity => {
      const old = leftMap.get(identity), next = rightMap.get(identity), source = next || old;
      const mapping = next ? newNodes : oldNodes;
      const sourceNode = mapping.get(source.source), targetNode = mapping.get(source.target);
      if (!sourceNode || !targetNode) return [];
      const paths = [...new Set([beforeLayer, afterLayer].filter(Boolean).map(layer => `${layer.path}.edges`))];
      const ownChanges = [...new Set(paths.flatMap(path => rows('edge', member(path, 'id', identity))))];
      const priorityChanges = changes.filter(change => change.object_type === 'edge_order' && paths.includes(change.path));
      const status = !old ? 'added' : !next ? 'removed' : statusFor(ownChanges);
      const priority = Boolean(old && next && old.order !== next.order && priorityChanges.length);
      const id = `comparison-edge:${JSON.stringify([...layerPath, identity])}`;
      return [{ ...source, id, key: id, source: sourceNode.id, target: targetNode.id,
        portIndex: list(sourceNode.unit.exit_ports).findIndex(port => port.port === source.sourcePort),
        comparison: { status, priority, beforeOrder: old?.order === undefined ? null : old.order + 1,
          afterOrder: next?.order === undefined ? null : next.order + 1,
          changes: [...ownChanges, ...(priority ? priorityChanges : [])], before: old?.edgeConfig ?? null, after: next?.edgeConfig ?? null },
      }];
    });
  };
  model.edges = makeEdges(before.edges, after.edges);
  model.waitEdges = makeEdges(before.waitEdges, after.waitEdges);
  return model;
}

export function comparisonLabel(comparison) {
  if (!comparison) return '';
  const status = { added: '新增', removed: '删除', changed: '修改' }[comparison.status];
  const priority = comparison.priority ? `优先级 ${comparison.beforeOrder} → ${comparison.afterOrder}` : '';
  return [status, priority].filter(Boolean).join(' · ');
}

export function comparisonEdgeStyle(comparison) {
  if (!comparison) return {};
  const stroke = { added: '#247348', removed: '#b4232f', changed: '#825e13' }[comparison.status] || (comparison.priority ? '#825e13' : null);
  return stroke ? { stroke, strokeWidth: 2, ...(comparison.status === 'removed' ? { strokeDasharray: '5 4' } : {}) } : {};
}
