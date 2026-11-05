const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);

const keyFor = (layerPath, id) => JSON.stringify([...(Array.isArray(layerPath) ? layerPath : []), id]);

export function overlayForNode(node, aggregate, layerPath = []) {
  if (!object(aggregate?.nodes) || !node) return null;
  const localId = typeof node.localId === 'string' ? node.localId : '';
  if (!localId) return null;
  const key = keyFor(layerPath, localId);
  const stat = aggregate.nodes[key];
  if (!object(stat)) return null;
  const terminated = aggregate.termination_targets?.[key];
  return Number.isSafeInteger(terminated) && terminated >= 0 ? { ...stat, terminated } : stat;
}

export function overlayForEdge(edge, aggregate, layerPath = []) {
  if (!object(aggregate?.edges)) return null;
  const id = edge?.edgeConfig?.id;
  return typeof id === 'string' ? aggregate.edges[keyFor(layerPath, id)] || null : null;
}

export function overlayLabel(stat, aggregate, mode = 'count') {
  if (!object(stat)) return '';
  const parts = [];
  if (Number.isFinite(stat.entered)) parts.push(`进入 ${stat.entered}`);
  if (Number.isFinite(stat.traversed)) parts.push(`经过 ${stat.traversed}`);
  if (mode === 'detail' && Number.isFinite(stat.dwell_ms) && stat.dwell_ms >= 0
      && Number.isSafeInteger(stat.dwell_sample_count) && stat.dwell_sample_count > 0) {
    const duration = stat.dwell_ms >= 1000 ? `${(stat.dwell_ms / 1000).toFixed(1)}s` : `${Math.round(stat.dwell_ms)}ms`;
    parts.push(`执行 ${duration} (n=${stat.dwell_sample_count})`);
  }
  if (mode === 'detail' && Number.isSafeInteger(stat.terminated) && stat.terminated >= 0) parts.push(`终止 ${stat.terminated}`);
  if (!stat.low_sample && !aggregate?.low_sample && Number.isFinite(stat.percentage)) parts.push(`${stat.percentage}%`);
  return parts.join(' · ');
}
