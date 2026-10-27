import test from 'node:test';
import assert from 'node:assert/strict';
import { createStore } from '../store.js';
import * as flow from '../flow-model.js';
import { renderFlow } from '../views/flow.js';
import { readiness } from '../domain.js';

const context = store => ({ state: store.state, agent: store.currentAgent(), ready: readiness(store.currentAgent(), store.state.connections), readonly: store.readonly() });

const node = (id, type, title = id) => ({ id, type, title, instruction: '', ruleIds: [] });
const edge = (id, source, target, label = '') => ({ id, source, target, label, examples: label && label !== '其他' ? ['例句一', '例句二', '例句三'] : [], ruleIds: [] });
const branchedGraph = () => ({
  nodes: [node('answer-b', 'reply', '课程回答'), node('decision-b', 'decision', '选择课程'), node('start', 'start', '进入客服'), node('handoff', 'handoff', '人工接待'), node('decision-a', 'decision', '判断意图'), node('answer-a', 'reply', '价格回答'), node('orphan', 'reply', '待接入步骤')],
  edges: [edge('enter', 'start', 'decision-a'), edge('price', 'decision-a', 'answer-a', '问价格'), edge('course', 'decision-a', 'decision-b', '问课程'), edge('a-fallback', 'decision-a', 'handoff', '其他'), edge('details', 'decision-b', 'answer-b', '了解课程'), edge('b-fallback', 'decision-b', 'handoff', '其他'), edge('merge', 'answer-a', 'handoff')],
});

function graphContext(view = 'graph', filter = 'all') {
  const store = createStore();
  store.currentAgent().config.routeGraph = branchedGraph();
  store.state.ui.flowView = view;
  store.state.ui.flowBranchFilter = filter;
  return context(store);
}

test('legacy sequence migrates into one editable graph without losing descriptions', () => {
  const store = createStore();
  const config = store.currentAgent().config;
  assert.ok(config.routeGraph);
  assert.equal(config.routeGraph.nodes[0].type, 'start');
  assert.ok(config.routeGraph.nodes.some(node => node.instruction.includes('识别用户当前的问题')));
  assert.ok(config.routeGraph.nodes.some(node => node.instruction.includes('使用当前授权')));
  assert.ok(config.routeGraph.edges.length >= 2);
});

test('structured branch saves despite a missing fallback and shares graph/list data', () => {
  const store = createStore(), agent = store.currentAgent();
  const before = agent.config.routeGraph.nodes.length;
  const result = store.dispatch('flow-branch', { intent: '问课程安排', examples: '课什么时候上\n几点上课\n上课时间', then: 'answer' });
  assert.equal(result.ok, true);
  assert.equal(agent.config.routeGraph.nodes.length, before + 2);
  assert.ok(agent.config.routeGraph.edges.some(edge => edge.label === '问课程安排' && edge.examples.length === 3));
  const graph = renderFlow(context(store));
  assert.match(graph, /问课程安排/);
  store.dispatch('flow-view', { view: 'list' });
  assert.match(renderFlow(context(store)), /问课程安排/);
  assert.ok(flow.validateRouteGraph(agent.config.routeGraph, agent.config).some(issue => issue.path.startsWith('routeGraph')));
});

test('branch form disclosure survives rendering and successful save closes it', () => {
  const store = createStore();
  store.dispatch('flow-branch-disclosure', { open: true });
  assert.match(renderFlow(context(store)), /data-flow-branch-disclosure open/);
  assert.equal(store.dispatch('flow-branch', { intent: '问价格', examples: '多少钱/费用多少/价格是多少', then: 'answer' }).ok, true);
  assert.doesNotMatch(renderFlow(context(store)), /data-flow-branch-disclosure open/);
});

test('write branch cannot disable confirmation; graph errors block release but not save', () => {
  const store = createStore(), agent = store.currentAgent();
  store.dispatch('tool', { title: '预约', sideEffect: 'write', successField: '预约号' });
  const toolId = agent.config.tools[0].id;
  assert.equal(store.dispatch('flow-branch', { intent: '想报名', examples: '我要报名\n想听课\n安排试听', then: 'business', toolId }).ok, true);
  const node = agent.config.routeGraph.nodes.find(item => item.toolId === toolId);
  assert.equal(node.type, 'business');
  assert.equal(agent.config.tools[0].requiresConfirm, true);
  assert.equal(store.dispatch('update-config', { path: 'tools.0.requiresConfirm', value: false }).ok, false);
  assert.ok(store.state.ui.saveStatus === 'saved');
});

test('diagram shows every decision, joined path and disconnected step', () => {
  const ctx = graphContext();
  const html = renderFlow(ctx);
  for (const item of ctx.agent.config.routeGraph.nodes) {
    assert.equal((html.match(new RegExp(`class="flow-node [^"]*"[^>]*data-id="${item.id}"`, 'g')) || []).length, 1, `diagram is missing or repeats ${item.title}`);
  }
  for (const item of ctx.agent.config.routeGraph.edges) assert.ok(html.includes(`data-flow-edge-id="${item.id}"`), `diagram is missing connection ${item.id}`);
  assert.match(html, /待接入路径/);
});

test('list follows connected paths instead of storage order and shows nested branch depth', () => {
  const html = renderFlow(graphContext('list'));
  const ids = [...html.matchAll(/<button[^>]*data-id="([^"]+)"[^>]*data-flow-row/g)].map(match => match[1]);
  assert.deepEqual(ids, ['start', 'decision-a', 'answer-a', 'handoff', 'decision-b', 'answer-b', 'orphan']);
  assert.match(html, /data-flow-node-id="decision-b"[^>]*data-depth="1"/);
  assert.match(html, /data-flow-node-id="answer-b"[^>]*data-depth="2"/);
  assert.match(html, /问课程/);
  assert.match(html, /了解课程/);
});

test('branch filter retains the path to a nested decision and hides sibling branches in both views', () => {
  for (const view of ['graph', 'list']) {
    const html = renderFlow(graphContext(view, 'details'));
    assert.match(html, /进入客服/);
    assert.match(html, /判断意图/);
    assert.match(html, /选择课程/);
    assert.match(html, /课程回答/);
    assert.doesNotMatch(html, /data-flow-node-id="answer-a"/);
    assert.doesNotMatch(html, /data-flow-node-id="handoff"/);
    assert.doesNotMatch(html, /data-flow-node-id="orphan"/);
    assert.match(html, /data-action="flow-filter" data-id="all"/);
  }
});

test('decision branch editor exposes intent, examples and deletion without blocking incomplete drafts', () => {
  const ctx = graphContext();
  ctx.state.ui.selectedFlowNode = 'decision-b';
  const html = renderFlow(ctx);
  assert.match(html, /data-form="flow-edge-update"[^>]*data-id="details"/);
  assert.match(html, /name="id" value="details"/);
  assert.match(html, /name="label" value="了解课程"/);
  assert.match(html, /name="examples"[^>]*>例句一\n例句二\n例句三/);
  assert.match(html, /data-action="flow-edge-delete"[^>]*data-id="details"/);
  assert.match(html, /data-form="flow-branch"[^>]*>[\s\S]*?name="decisionId" value="decision-b"/);
});

test('projection and traversal are pure and accept arbitrary start identifiers', () => {
  const graph = branchedGraph(), snapshot = JSON.stringify(graph);
  const config = { routeGraph: graph, tools: [] };
  assert.equal(flow.projectRouteGraph(config), graph);
  assert.equal(typeof flow.projectRouteGraphView, 'function');
  const view = flow.projectRouteGraphView(graph, 'details');
  assert.deepEqual(view.rows.map(row => row.node.id), ['start', 'decision-a', 'decision-b', 'answer-b']);
  assert.deepEqual(view.edges.map(item => item.id), ['enter', 'course', 'details']);
  assert.equal(JSON.stringify(graph), snapshot);
  assert.deepEqual(flow.validateRouteGraph({ nodes: [node('my-start', 'start'), node('reply', 'reply')], edges: [edge('continue', 'my-start', 'reply')] }), []);
});

test('incomplete branch intent is a release issue even when examples are present', () => {
  const graph = { nodes: [node('start', 'start'), node('choice', 'decision'), node('answer', 'reply'), node('human', 'handoff')], edges: [edge('enter', 'start', 'choice'), { ...edge('question', 'choice', 'answer'), examples: ['第一句', '第二句', '第三句'] }, edge('other', 'choice', 'human', '其他')] };
  assert.ok(flow.validateRouteGraph(graph).some(issue => issue.path === 'routeGraph.edges.1.label'));
});

test('cyclic connections remain visible without repeating list nodes', () => {
  const graph = branchedGraph();
  graph.edges.push(edge('return', 'answer-b', 'decision-b'));
  const view = flow.projectRouteGraphView(graph);
  assert.equal(view.rows.length, graph.nodes.length);
  assert.ok(view.edges.some(item => item.id === 'return'));
});
