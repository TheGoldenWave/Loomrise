export function projectRouteGraph(config) {
  if (Array.isArray(config.routeGraph?.nodes) && Array.isArray(config.routeGraph?.edges)) return config.routeGraph;
  const steps = (config.flow || []).map(step => ({ id: `route-${step.id}`, legacyId: step.id, type: 'reply', title: step.title, instruction: step.instruction, ruleIds: [] }));
  const skills = (config.skills || []).map(skill => ({ id: `route-${skill.id}`, legacyId: skill.id, type: 'reply', title: skill.title, instruction: `${skill.description}\n退出：${skill.exit}`, ruleIds: [] }));
  const nodes = [{ id: 'route-start', type: 'start', title: '客户进入', instruction: '', ruleIds: [] }, ...steps, ...skills];
  const edges = nodes.slice(1).map((node, index) => ({ id: `edge-${nodes[index].id}-${node.id}`, source: nodes[index].id, target: node.id, label: '', examples: [], ruleIds: [] }));
  return { nodes, edges, migratedFrom: 'linear-flow' };
}

export function migrateRouteGraph(config) {
  config.routeGraph = projectRouteGraph(config);
  return config.routeGraph;
}

export function projectRouteGraphView(graph, branchId = 'all') {
  const nodeById = new Map(graph.nodes.map(node => [node.id, node]));
  const branches = graph.edges.filter(edge => nodeById.get(edge.source)?.type === 'decision');
  const branch = branches.find(edge => edge.id === branchId);
  let edges = graph.edges;
  let visibleIds = new Set(graph.nodes.map(node => node.id));
  if (branch) {
    const edgeIds = new Set([branch.id]);
    const collect = (initial, reverse) => {
      const visited = new Set([initial]), pending = [initial];
      for (let index = 0; index < pending.length; index += 1) {
        const id = pending[index];
        if (!reverse && id === branch.source) continue;
        for (const edge of graph.edges) {
          if ((reverse ? edge.target : edge.source) !== id) continue;
          edgeIds.add(edge.id);
          const next = reverse ? edge.source : edge.target;
          if (!visited.has(next)) { visited.add(next); pending.push(next); }
        }
      }
    };
    collect(branch.source, true);
    collect(branch.target, false);
    edges = graph.edges.filter(edge => edgeIds.has(edge.id));
    visibleIds = new Set(edges.flatMap(edge => [edge.source, edge.target]));
  }
  const nodes = graph.nodes.filter(node => visibleIds.has(node.id));
  const outgoing = new Map(nodes.map(node => [node.id, edges.filter(edge => edge.source === node.id)]));
  const incoming = new Map(nodes.map(node => [node.id, edges.filter(edge => edge.target === node.id)]));
  const reachable = new Set(nodes.filter(node => node.type === 'start').map(node => node.id));
  const pending = [...reachable];
  for (let index = 0; index < pending.length; index += 1) for (const edge of outgoing.get(pending[index]) || []) {
    if (nodeById.has(edge.target) && !reachable.has(edge.target)) { reachable.add(edge.target); pending.push(edge.target); }
  }
  const rows = [], visited = new Set();
  const visit = (node, incomingEdge = null, depth = 0, level = 0) => {
    if (!node || visited.has(node.id)) return;
    visited.add(node.id);
    rows.push({ node, incomingEdge, incomingEdges: incoming.get(node.id) || [], depth, level, detached: !reachable.has(node.id) });
    const exits = outgoing.get(node.id) || [];
    for (const edge of exits) visit(nodeById.get(edge.target), edge, depth + (node.type === 'decision' || exits.length > 1 ? 1 : 0), level + 1);
  };
  for (const node of nodes.filter(node => node.type === 'start')) visit(node);
  for (const node of nodes.filter(node => !incoming.get(node.id)?.length)) visit(node);
  for (const node of nodes) visit(node);
  return { nodes, edges, rows, branches, filterId: branch?.id || 'all' };
}

export function validateRouteGraph(graph, config = {}) {
  const issues = [];
  if (!graph?.nodes?.length || !graph?.edges) return [{ path: 'routeGraph', message: '对话流程还没有开始节点', page: 'flow' }];
  const nodes = new Map(graph.nodes.map(node => [node.id, node]));
  const add = (path, message) => issues.push({ path, message, page: 'flow' });
  if (graph.nodes.filter(node => node.type === 'start').length !== 1) add('routeGraph.nodes', '流程需要且只需要一个开始节点');
  if (graph.nodes.length > 12) add('routeGraph.nodes', '同层超过 12 个节点，请拆分为更清楚的路径');
  for (const [index, edge] of graph.edges.entries()) {
    if (!nodes.has(edge.source) || !nodes.has(edge.target)) add(`routeGraph.edges.${index}`, '有连接指向不存在的步骤');
    if (nodes.get(edge.source)?.type === 'decision' && !String(edge.label || '').trim()) add(`routeGraph.edges.${index}.label`, '判断分支还没写客户想做什么');
    if (nodes.get(edge.source)?.type === 'decision' && edge.label !== '其他' && (edge.examples || []).filter(Boolean).length < 3) add(`routeGraph.edges.${index}.examples`, `“${edge.label || '未命名'}”分支至少提供 3 句例句`);
  }
  const reachable = new Set(graph.nodes.filter(node => node.type === 'start').map(node => node.id));
  for (let pass = 0; pass < graph.nodes.length; pass += 1) for (const edge of graph.edges) if (reachable.has(edge.source)) reachable.add(edge.target);
  for (const node of graph.nodes) if (!reachable.has(node.id)) add(`routeGraph.nodes.${node.id}`, `“${node.title}”没有从开始到达的路径`);
  for (const decision of graph.nodes.filter(node => node.type === 'decision')) {
    const exits = graph.edges.filter(edge => edge.source === decision.id);
    if (!exits.some(edge => edge.label === '其他' && nodes.get(edge.target)?.type === 'handoff')) add(`routeGraph.nodes.${decision.id}.fallback`, '其他问题没有转人工出口');
    if (exits.length > 5) add(`routeGraph.nodes.${decision.id}.branches`, '一处判断最多 5 个分支');
  }
  for (const node of graph.nodes.filter(node => node.type === 'business')) {
    const tool = (config.tools || []).find(item => item.id === node.toolId);
    if (!tool) add(`routeGraph.nodes.${node.id}.toolId`, `“${node.title}”还没选择办理事项`);
    else {
      if (tool.sideEffect === 'write' && !tool.requiresConfirm) add(`routeGraph.nodes.${node.id}.confirm`, `“${tool.title}”需要客户确认后才能办理`);
      if (tool.sideEffect === 'write' && !tool.successField) add(`routeGraph.nodes.${node.id}.successField`, `“${tool.title}”缺办成标志`);
    }
  }
  return issues;
}
