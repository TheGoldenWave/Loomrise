import { attr, button, emptyState, escapeHtml, icon, pageHeading } from '../helpers.js';
import { projectRouteGraph, projectRouteGraphView, validateRouteGraph } from '../flow-model.js';

const typeName = { start: '开始', decision: '判断', business: '办理', reply: '回复', handoff: '转人工' };
const e = escapeHtml;
const a = attr;

function nodeButton(node, selected, rules, runs, state, detached = false) {
  const count = runs ? (state.runs || []).filter(run => run.flowNodeId === node.id).length : 0;
  return `<button type="button" class="flow-node flow-node-${node.type}${selected ? ' is-selected' : ''}" data-action="flow-select-node" data-id="${a(node.id)}" data-flow-node-id="${a(node.id)}" aria-pressed="${selected}"><span class="flow-node-type">${typeName[node.type] || '回复'}${detached ? ' · 待接入路径' : ''}</span><strong>${e(node.title)}</strong>${rules && node.ruleIds?.length ? `<small>红线 ${node.ruleIds.length}</small>` : ''}${runs ? `<small>实际走向 ${count} 次${count ? '' : '（无记录）'}</small>` : ''}</button>`;
}

function branchForm(ctx, graph) {
  if (ctx.readonly) return '';
  const tools = ctx.agent.config.tools || [];
  const decisions = graph.nodes.filter(node => node.type === 'decision');
  const selected = decisions.find(node => node.id === ctx.state.ui.selectedFlowNode);
  const destination = selected || decisions[0];
  const chooseDecision = selected || decisions.length < 2
    ? `<input type="hidden" name="decisionId" value="${a(destination?.id || '')}">${destination ? `<p class="helper">加到「${e(destination.title)}」下</p>` : ''}`
    : `<label class="field">加到哪处判断<select class="control input" name="decisionId">${decisions.map(node => `<option value="${a(node.id)}">${e(node.title)}</option>`).join('')}</select></label>`;
  return `<details class="flow-branch-add" data-flow-branch-disclosure ${ctx.state.ui.flowBranchOpen ? 'open' : ''}><summary>＋ 加一个分支</summary><form data-form="flow-branch" class="stack compact-form">${chooseDecision}<label class="field">客户想做什么<input class="control input" name="intent" required placeholder="例如：问课程安排"></label><label class="field">例句（至少 3 句，每行一句）<textarea class="control textarea" name="examples" required rows="3" placeholder="课什么时候上&#10;几点上课&#10;上课时间"></textarea></label><fieldset class="flow-then"><legend>然后</legend><label><input type="radio" name="then" value="answer" checked>用知识库回答</label><label><input type="radio" name="then" value="business">办理一件事</label><label><input type="radio" name="then" value="handoff">转人工</label></fieldset>${tools.length ? `<label class="field">办理事项（选办理时）<select class="control input" name="toolId"><option value="">选择办理事项</option>${tools.map(tool => `<option value="${a(tool.id)}">${e(tool.title)}</option>`).join('')}</select></label>` : ''}<div class="button-group"><button class="btn btn-primary" type="submit">加上</button>${button('flow-branch-cancel', '取消', { variant: 'ghost' })}</div></form></details>`;
}

function graphView(ctx, graph, view) {
  const { state } = ctx;
  const nodes = new Map(graph.nodes.map(node => [node.id, node]));
  const selected = state.ui.selectedFlowNode;
  const layers = state.ui.flowLayers || {};
  const levels = new Map(), pending = [];
  const visit = (id, level) => { if (!levels.has(id)) { levels.set(id, level); pending.push(id); } };
  for (const node of view.nodes.filter(node => node.type === 'start')) visit(node.id, 0);
  const placePending = () => {
    for (let index = 0; index < pending.length; index += 1) for (const edge of view.edges.filter(edge => edge.source === pending[index])) {
      if (nodes.has(edge.target)) visit(edge.target, levels.get(edge.source) + 1);
    }
  };
  placePending();
  for (const row of view.rows) if (!levels.has(row.node.id)) { visit(row.node.id, 0); placePending(); }
  const maxLevel = Math.max(0, ...levels.values()), columns = Math.min(4, maxLevel + 1);
  const cardWidth = 190, cardHeight = layers.rules || layers.runs ? 82 : 58, rowHeight = cardHeight + 18;
  const width = 1000, positions = new Map();
  let height = 0;
  for (let band = 0; band <= Math.floor(maxLevel / columns); band += 1) {
    const groups = Array.from({ length: columns }, (_, column) => view.rows.filter(row => levels.get(row.node.id) === band * columns + column));
    const bandHeight = Math.max(1, ...groups.map(group => group.length)) * rowHeight;
    groups.forEach((group, column) => group.forEach((row, index) => positions.set(row.node.id, {
      x: (column + .5) * width / columns,
      y: height + bandHeight / 2 + (index - (group.length - 1) / 2) * rowHeight + 16,
      band,
    })));
    height += bandHeight + 20;
  }
  const connections = view.edges.map(edge => {
    const source = positions.get(edge.source), target = positions.get(edge.target);
    if (!source || !target) return '';
    let path, labelX, labelY;
    if (source.band === target.band && target.x > source.x) {
      const from = source.x + cardWidth / 2, to = target.x - cardWidth / 2, mid = (from + to) / 2;
      path = `M ${from} ${source.y} C ${mid} ${source.y}, ${mid} ${target.y}, ${to} ${target.y}`;
      labelX = mid; labelY = (source.y + target.y) / 2 - 7;
    } else {
      const from = source.y + cardHeight / 2, to = target.y - cardHeight / 2;
      const mid = source.band === target.band ? Math.max(source.y, target.y) + rowHeight / 2 : (from + to) / 2;
      path = `M ${source.x} ${from} V ${mid} H ${target.x} V ${to}`;
      labelX = (source.x + target.x) / 2; labelY = mid - 7;
    }
    const title = `${nodes.get(edge.source).title} → ${edge.label ? `${edge.label} → ` : ''}${nodes.get(edge.target).title}`;
    return `<g class="flow-diagram-edge" data-flow-edge-id="${a(edge.id)}" aria-label="${a(title)}"><title>${e(title)}</title><path d="${path}" fill="none" stroke="currentColor" stroke-width="1.3" marker-end="url(#flow-arrow)"/>${edge.label ? `<text x="${labelX}" y="${labelY}" text-anchor="middle" font-size="12">${e(edge.label)}${layers.rules && edge.ruleIds?.length ? ` · 红线 ${edge.ruleIds.length}` : ''}</text>` : ''}</g>`;
  }).join('');
  const cards = view.rows.map(row => {
    const position = positions.get(row.node.id);
    return `<foreignObject class="flow-diagram-node" x="${position.x - cardWidth / 2}" y="${position.y - cardHeight / 2}" width="${cardWidth}" height="${cardHeight}">${nodeButton(row.node, selected === row.node.id, layers.rules, layers.runs, state, row.detached)}</foreignObject>`;
  }).join('');
  return `<div class="flow-canvas" aria-label="对话路径图"><div class="flow-diagram-frame"><div class="flow-diagram-scroll" role="region" aria-label="对话路径图，可横向滚动查看后续步骤" tabindex="0"><svg class="flow-diagram" viewBox="0 0 ${width} ${height}" width="100%" aria-label="${view.nodes.length} 个步骤，${view.edges.length} 条连接"><defs><marker id="flow-arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M 0 0 L 7 3.5 L 0 7" fill="currentColor"/></marker></defs>${connections}${cards}</svg></div><span class="flow-scroll-cue" aria-hidden="true">${icon('arrow', 16)}</span></div>${branchForm(ctx, graph)}</div>`;
}

function listView(ctx, graph, view) {
  const { state, agent, readonly } = ctx;
  const rules = [...(agent.config.businessRules || []), ...(agent.config.rules || [])];
  const nodes = new Map(graph.nodes.map(node => [node.id, node]));
  const rows = view.rows.map(row => {
    const { node, incomingEdge: edge } = row;
    const tool = (agent.config.tools || []).find(item => item.id === node.toolId);
    const labels = (node.ruleIds || []).map(id => rules.find(rule => rule.id === id)?.title).filter(Boolean).join('、');
    const otherEntries = row.incomingEdges.filter(item => item.id !== edge?.id);
    return `<tr data-flow-node-id="${a(node.id)}" data-depth="${row.depth}"${row.detached ? ' class="flow-detached"' : ''}><td data-label="选择"><input type="checkbox" data-action="flow-select" data-id="${a(node.id)}" aria-label="选择${a(node.title)}" ${state.ui.flowSelection?.includes(node.id) ? 'checked' : ''} ${readonly ? 'disabled' : ''}></td><td data-label="步骤"><div class="flow-list-step" style="--flow-depth:${row.depth}"><button class="button-link flow-list-focus" type="button" data-action="flow-select-node" data-id="${a(node.id)}" data-flow-row>${row.depth ? '└ ' : ''}${e(edge?.label ? `${edge.label} · ${node.title}` : node.title)}</button>${row.detached ? '<small>待接入路径</small>' : ''}${otherEntries.length ? `<small>也从 ${otherEntries.map(item => e(`${nodes.get(item.source)?.title || '待修复步骤'}${item.label ? ` · ${item.label}` : ''}`)).join('、')} 进入</small>` : ''}</div></td><td data-label="做什么">${typeName[node.type] || '待修复'}</td><td data-label="用到的知识或办理">${e(tool?.title || (node.type === 'reply' ? '知识库' : '—'))}</td><td data-label="红线">${e(labels || '—')}</td><td data-label="办成标志">${e(tool?.successField || '—')}</td></tr>`;
  }).join('');
  return `<p class="helper">可用键盘 ↑ ↓ 选择步骤，Enter 查看详情。</p><div class="table-wrap"><table class="data-table mobile-list flow-list"><thead><tr><th>选择</th><th>步骤</th><th>做什么</th><th>用到的知识或办理</th><th>红线</th><th>办成标志</th></tr></thead><tbody>${rows}</tbody></table></div><div class="flow-bulk"><form data-form="flow-bulk-rule"><label>批量加红线<select class="control input" name="ruleId" required><option value="">选择红线</option>${rules.map(rule => `<option value="${a(rule.id)}">${e(rule.title)}</option>`).join('')}</select></label><button class="btn btn-secondary" type="submit" ${readonly ? 'disabled' : ''}>加到所选步骤</button></form>${button('flow-bulk-confirm', '批量改确认要求', { disabled: readonly })}</div>${branchForm(ctx, graph)}`;
}

function branchEditors(ctx, graph, node) {
  const remove = node.type === 'start' ? '' : button('flow-node-delete', '删除步骤', { id: node.id, disabled: ctx.readonly, variant: 'ghost' });
  const nodes = new Map(graph.nodes.map(item => [item.id, item]));
  const edges = graph.edges.filter(edge => node.type === 'decision' && edge.source === node.id || edge.target === node.id && nodes.get(edge.source)?.type === 'decision');
  if (!edges.length) return remove;
  return `<div class="flow-edge-editors">${edges.map(edge => `<details class="flow-edge-editor"><summary>分支「${e(edge.label || '未命名')}」 → ${e(nodes.get(edge.target)?.title || '待修复步骤')}</summary>${ctx.readonly ? `<p>${(edge.examples || []).map(e).join(' / ') || '还没有例句'}</p>` : `<form data-form="flow-edge-update" data-id="${a(edge.id)}" class="stack compact-form"><input type="hidden" name="id" value="${a(edge.id)}"><label class="field">客户想做什么<input class="control input" name="label" value="${a(edge.label || '')}"></label><label class="field">例句（每行一句，上线前至少 3 句）<textarea class="control textarea" name="examples" rows="3">${e((edge.examples || []).join('\n'))}</textarea></label><div class="button-group"><button class="btn btn-primary" type="submit">保存分支</button>${button('flow-edge-delete', '删除这个分支', { id: edge.id, variant: 'ghost' })}</div><p class="helper">删除分支后，步骤会保留为待接入路径。例句未补齐也可先存草稿。</p></form>`}</details>`).join('')}</div>`;
}

function inspector(ctx, graph) {
  const node = graph.nodes.find(item => item.id === ctx.state.ui.selectedFlowNode);
  if (!node) return '';
  const tool = (ctx.agent.config.tools || []).find(item => item.id === node.toolId);
  return `<section class="flow-inspector"><div><strong>选中「${typeName[node.type]}：${e(node.title)}」</strong><p>要问：${e(tool?.input || '按当前问题澄清')} · 办成标志：${e(tool?.successField || '不涉及办理')}</p></div><div class="button-group">${button('flow-edit-node', '编辑', { id: node.id, disabled: ctx.readonly })}${button('evidence-open', '依据', { kind: 'flow', id: node.id, variant: 'ghost' })}</div>${ctx.state.ui.flowEditId === node.id && !ctx.readonly ? `<form data-form="flow-node-update" class="stack compact-form"><input type="hidden" name="id" value="${a(node.id)}"><label>步骤名称<input class="control input" name="title" value="${a(node.title)}" required></label><label>处理说明<textarea class="control textarea" name="instruction">${e(node.instruction || '')}</textarea></label><button class="btn btn-primary" type="submit">保存修改</button></form>` : ''}${branchEditors(ctx, graph, node)}</section>`;
}

function branchFilter(graph, view) {
  if (!view.branches.length) return '';
  const nodes = new Map(graph.nodes.map(node => [node.id, node]));
  const active = view.branches.find(edge => edge.id === view.filterId);
  return `<details class="flow-branch-filter"><summary>按分支筛选 · ${e(active?.label || '全部路径')}</summary><div class="flow-filter-options"><button type="button" class="btn btn-ghost" data-action="flow-filter" data-id="all" aria-pressed="${!active}">全部路径</button>${view.branches.map(edge => `<button type="button" class="btn btn-ghost" data-action="flow-filter" data-id="${a(edge.id)}" aria-pressed="${active?.id === edge.id}">${e(nodes.get(edge.source).title)} · ${e(edge.label || '未命名分支')}</button>`).join('')}</div></details>`;
}

export function renderFlow(ctx) {
  if (!ctx.agent) return emptyState('先选择专家', '流程属于具体专家的草稿。', button('navigate', '专家列表', { page: 'agents' }));
  const graph = projectRouteGraph(ctx.agent.config);
  if (!graph) return emptyState('流程尚未载入', '旧步骤仍在草稿中，请重新载入。');
  const errors = validateRouteGraph(graph, ctx.agent.config);
  const view = projectRouteGraphView(graph, ctx.state.ui.flowBranchFilter);
  const list = ctx.state.ui.flowView === 'list';
  const controls = `<div class="flow-controls"><div class="button-group" role="group" aria-label="对话流程视图"><button class="btn ${list ? 'btn-ghost' : 'btn-primary'}" data-action="flow-view" data-view="graph" aria-pressed="${!list}">流程图</button><button class="btn ${list ? 'btn-primary' : 'btn-ghost'}" data-action="flow-view" data-view="list" aria-pressed="${list}">列表</button></div><div class="button-group"><button class="btn btn-ghost" data-action="flow-toggle-layer" data-layer="runs" aria-pressed="${Boolean(ctx.state.ui.flowLayers?.runs)}">显示实际走向</button><button class="btn btn-ghost" data-action="flow-toggle-layer" data-layer="rules" aria-pressed="${Boolean(ctx.state.ui.flowLayers?.rules)}">显示红线</button></div></div>`;
  return `${pageHeading('对话流程', '', '')}${controls}${branchFilter(graph, view)}${list ? listView(ctx, graph, view) : graphView(ctx, graph, view)}${inspector(ctx, graph)}${errors.length ? `<section class="flow-issues"><h2>上线前要处理 ${errors.length} 处</h2><p class="helper">草稿照常自动保存；处理完这些问题后才能上线。</p>${errors.map(issue => `<p>${e(issue.message)}${issue.path.endsWith('.fallback') ? button('flow-add-fallback', '加转人工', { id: issue.path.slice('routeGraph.nodes.'.length, -'.fallback'.length), disabled: ctx.readonly }) : ''}</p>`).join('')}</section>` : '<p class="helper">目前没有流程结构问题。</p>'}`;
}
