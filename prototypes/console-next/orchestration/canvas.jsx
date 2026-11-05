import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ReactFlow, Background, Controls, Handle, Position, MarkerType } from '@xyflow/react';
import dagre from '@dagrejs/dagre';
import { configurationReadOnly, locateValidationIssue, projectOrchestration, unitAuxiliaryTargets } from './model.js';
import { portRows, serializePortRows } from './ports.js';
import { findPortReferences } from './port-references.js';
import { ConditionEditor } from './condition-editor.jsx';
import { overlayForNode, overlayForEdge, overlayLabel } from './overlay.js';
import { RunOverlayControls } from './run-overlay.jsx';
import { scopeForm, serializeScope } from './concurrent-scope.js';
import { projectComparison, comparisonLabel, comparisonEdgeStyle } from './comparison.js';
import { ComparisonLegend, ComparisonInspector } from './comparison-panel.jsx';
import { conditionSummary } from './condition-summary.js';
import { UnitAuxiliaryEditor } from './unit-auxiliary-editor.jsx';
import '@xyflow/react/dist/style.css';
import './canvas.css';

const list = value => Array.isArray(value) ? value : [];
const json = value => JSON.stringify(value, null, 2);
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
// A projection may omit edgeConfig (legacy drafts). Readers degrade to an empty
// read-only config instead of throwing and taking the whole canvas down.
const emptyEdgeConfig = Object.freeze({});
const edgeConfigOf = edge => object(edge?.edgeConfig) ? edge.edgeConfig : emptyEdgeConfig;
const atomSummary = unit => {
  const body = unit?.body;
  if (!body || typeof body !== 'object') return null;
  if (body.kind === 'tool') {
    const ref = body.tool_ref;
    if (ref && typeof ref === 'object') return `工具 ${String(ref.tool_id || '未填')} · v${String(ref.version || '未填')}`;
    return '工具 · 未冻结引用';
  }
  if (body.kind === 'speak') return '自由表达 · 资源待接入';
  if (body.kind === 'say') return '逐字话术';
  if (body.kind === 'judge') return '确定性判定';
  if (body.kind === 'graph') return '内容子图';
  return `内容 ${String(body.kind || '未知')}`;
};

function UnitNode({ data, selected }) {
  const { unit, entry, overlay, overlayAggregate, overlayMode, validationIssues = [] } = data;
  if (data.terminal) return <div className="orch-node"><Handle type="target" id="in:0" position={Position.Left} isConnectable={false} /><strong>{unit.unit_id}</strong><p>当前层边界</p></div>;
  return <div className={`orch-node ${selected ? 'is-selected' : ''} ${validationIssues.length ? 'has-validation-error' : ''} ${data.comparison?.status ? `is-diff-${data.comparison.status}` : ''}`}
    aria-label={`${unit.unit_id}${validationIssues.length ? `，${validationIssues.length} 项服务端校验问题` : ''}`}>
    <div className="orch-node-caption">{entry ? '入口单元' : '路由单元'}<span>v{String(unit.version ?? '未填')}</span></div>
    <strong>{unit.unit_id}</strong>
    {validationIssues.length > 0 && <small className="orch-validation-mark" role="status">服务端校验问题 · {validationIssues.length} 项</small>}
    {comparisonLabel(data.comparison) && <small className="orch-diff-status">{comparisonLabel(data.comparison)}</small>}
    {atomSummary(unit) && <small className="orch-atom-summary">{atomSummary(unit)}</small>}
    {data.routeSummaries?.map((summary, index) => <small className="orch-condition-summary" key={index}>{summary}</small>)}
    <div className="orch-run-slot">{overlay && <small className="orch-run-overlay" aria-label={`实际走向：${overlayLabel(overlay, overlayAggregate, overlayMode)}`}>{overlayLabel(overlay, overlayAggregate, overlayMode)}</small>}</div>
    <div className="orch-port-columns">
      <div>{list(unit.entry_ports).map((port, index) => port && <div className={`orch-port is-diff-${data.comparison?.ports.entry_ports[port.port]?.status || 'none'}`} key={index} title={`进入前须就绪：${list(port.requires).join('、') || '无额外字段'}`}>
        <Handle type="target" id={`in:${index}`} position={Position.Left} isConnectable={false} />
        <span>{String(port.port || '未命名入口')}<small>{comparisonLabel(data.comparison?.ports.entry_ports[port.port])}</small></span>
      </div>)}</div>
      <div>{list(unit.exit_ports).map((port, index) => port && <div className={`orch-port orch-output is-diff-${data.comparison?.ports.exit_ports[port.port]?.status || 'none'}`} key={index} title={`完成条件：${json(port.completion)}`}>
        <span>{String(port.port || '未命名出口')}<small>{comparisonLabel(data.comparison?.ports.exit_ports[port.port])}</small></span>
        <Handle type="source" id={`out:${index}`} position={Position.Right} isConnectable={false} />
      </div>)}</div>
    </div>
    <footer>{list(unit.on_event).length ? `事件 ${unit.on_event.length} · ` : ''}{list(unit.waits).map(wait => `等待 ${wait?.on || '未命名'}${wait?.timeoutMs ? ` ≤${wait.timeoutMs}ms` : ''}`).join(' · ')}{list(unit.waits).length ? ' · ' : ''}进入上限 {String(unit.max_rounds ?? '未填')} 次</footer>
  </div>;
}
const nodeTypes = { unit: UnitNode };

function layout(model) {
  const graph = new dagre.graphlib.Graph({ multigraph: true });
  graph.setGraph({ rankdir: 'LR', ranksep: 150, nodesep: 55, marginx: 30, marginy: 30 });
  graph.setDefaultEdgeLabel(() => ({}));
  for (const node of model.nodes) graph.setNode(node.id, { width: 254, height: 184 + Math.max(list(node.unit.entry_ports).length, list(node.unit.exit_ports).length) * 26 });
  for (const edge of [...model.edges, ...model.waitEdges]) graph.setEdge(edge.source, edge.target, {}, edge.id);
  dagre.layout(graph);
  return model.nodes.map(node => {
    const { x, y, width, height } = graph.node(node.id);
    return { id: node.id, type: 'unit', position: { x: x - width / 2, y: y - height / 2 }, data: node,
      initialWidth: width, initialHeight: height,
      ariaLabel: `${node.unit.unit_id}，版本 ${node.unit.version}，${node.entry ? '入口' : '路由'}单元` };
  });
}

function EdgeInspector({ edge, model, readOnly, workspace, config, isNew = false }) {
  const edgeConfig = edgeConfigOf(edge);
  const [error, setError] = useState('');
  const [condition, setCondition] = useState(() => json(edgeConfig.condition ?? {}));
  const [bounded, setBounded] = useState(Boolean(edgeConfig.window || edgeConfig.max_rounds || edgeConfig.exit));
  const [from, setFrom] = useState(edgeConfig.from);
  const [to, setTo] = useState(edgeConfig.to);
  const [maxRounds, setMaxRounds] = useState(edgeConfig.max_rounds ?? 1);
  const [counter, setCounter] = useState(edgeConfig.counter ?? '');
  const [exit, setExit] = useState(edgeConfig.exit || list(model.edgeTargets)[0]?.value || '');
  useEffect(() => {
    setCondition(json(edgeConfig.condition ?? {}));
    setBounded(Boolean(edgeConfig.window || edgeConfig.max_rounds || edgeConfig.exit));
    setFrom(edgeConfig.from);
    setTo(edgeConfig.to);
    setMaxRounds(edgeConfig.max_rounds ?? 1);
    setCounter(edgeConfig.counter ?? '');
    setExit(edgeConfig.exit || list(model.edgeTargets)[0]?.value || '');
  }, [edgeConfig, model.edgeTargets]);
  const submit = event => {
    event.preventDefault();
    if (readOnly) return;
    const form = new FormData(event.currentTarget);
    try {
      const from = String(form.get('from') || '');
      const to = String(form.get('to') || '');
      let condition;
      try { condition = JSON.parse(String(form.get('condition'))); }
      catch { throw new Error('请补全条件表达式，或修正边条件 JSON'); }
      if (!condition || typeof condition !== 'object' || Array.isArray(condition)) throw new Error('条件必须是 JSON 对象');
      const patch = { from, to, condition };
      if (isNew) {
        patch.id = String(form.get('id') || '').trim();
        if (!patch.id || patch.id.includes('.')) throw new Error('边 ID 不能为空或包含句点');
        if (model.edges.some(item => edgeConfigOf(item).id === patch.id)) throw new Error('当前层已有同名边，请更换 ID');
      }
      if (form.get('bounded')) {
        const maxRounds = Number(form.get('max_rounds'));
        const counter = String(form.get('counter') || '').trim();
        const exit = String(form.get('exit') || '');
        if (!Number.isSafeInteger(maxRounds) || maxRounds < 1) throw new Error('循环上限必须是正整数');
        if (!counter || !exit) throw new Error('循环边需要计数字段和超限去处');
        Object.assign(patch, { max_rounds: maxRounds, counter, exit, window: 'cycle' });
      } else {
        Object.assign(patch, { max_rounds: undefined, counter: undefined, exit: undefined, window: undefined });
      }
      const applied = isNew
        ? workspace.addGraphEdge(edge.layerPath, Object.fromEntries(Object.entries(patch).filter(([, value]) => value !== undefined)))
        : workspace.patchGraphEdge(edge.layerPath, edge.configIndex, patch);
      if (!applied) throw new Error('边已失效、ID 重复或当前配置不可编辑，请重新核对');
      setError('');
    } catch (cause) { setError(cause.message); }
  };
  return <aside className="orch-inspector" aria-label="边检视器" tabIndex={-1}>
    <div className="orch-inspector-title"><h3>{isNew ? '新增连线' : `边 · ${edgeConfig.id || '未命名'}`}</h3><span>{isNew ? '追加至当前层末尾' : Number.isSafeInteger(edge.order) ? `优先级 ${edge.order + 1}` : '候选出口'} · {readOnly ? '只读' : '草稿'}</span></div>
    <p>当前层数组顺序就是路由优先级。修改后需保存草稿。</p>
    {!isNew && <div className="orch-edge-order">
      <button className="btn btn-ghost" type="button" aria-label="优先级上移" title="优先级上移" disabled={readOnly || edge.configIndex === 0}
        onClick={() => workspace.moveGraphEdge(edge.layerPath, edge.configIndex, -1)}>↑</button>
      <button className="btn btn-ghost" type="button" aria-label="优先级下移" title="优先级下移" disabled={readOnly || edge.configIndex >= model.edgeCount - 1}
        onClick={() => workspace.moveGraphEdge(edge.layerPath, edge.configIndex, 1)}>↓</button>
    </div>}
    <form onSubmit={submit}>
      <fieldset disabled={readOnly}>
        {isNew ? <label>边 ID<input className="control input" name="id" required autoFocus /></label>
          : <p className="orch-edge-id">边 ID <code>{edgeConfig.id || '未命名'}</code></p>}
        <label>起点出口<select className="control input" name="from" value={from} onChange={event => setFrom(event.target.value)} required>
          {list(model.edgeSources).map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
        </select></label>
        <label>目标入口<select className="control input" name="to" value={to} onChange={event => setTo(event.target.value)} required>
          {list(model.edgeTargets).map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
        </select></label>
        <ConditionEditor value={condition} name="condition" label="边条件" onChange={setCondition} fields={Object.keys(config?.persona?.fields || {})}
          validationPath={edge.validationPath} />
        <label className="orch-checkbox"><input type="checkbox" name="bounded" checked={bounded} onChange={event => setBounded(event.currentTarget.checked)} />执行环</label>
        {bounded && <div className="orch-cycle-fields">
          <label>最大轮数<input className="control input" type="number" name="max_rounds" min="1" step="1" value={maxRounds} onChange={event => setMaxRounds(event.target.value)} required /></label>
          <label>计数字段<input className="control input" name="counter" value={counter} onChange={event => setCounter(event.target.value)} required /></label>
          <label>超限去处<select className="control input" name="exit" value={exit} onChange={event => setExit(event.target.value)} required>
            {list(model.edgeTargets).map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select></label>
        </div>}
        {!readOnly && <button className="btn btn-primary" type="submit">{isNew ? '添加连线' : '应用边修改'}</button>}
      </fieldset>
      {error && <p className="field-error" role="alert">{error}</p>}
    </form>
    {!isNew && !readOnly && <button className="btn btn-ghost" type="button" onClick={() => {
      if (!workspace.removeGraphEdge(edge.layerPath, edge.configIndex, edgeConfig.id)) setError('连线已变化，请重新选择后删除');
    }}>删除此连线</button>}
  </aside>;
}

function PortFields({ kind, value, graph, atomic, fields, config, unitIndex, validationIssues = [] }) {
  const nextKey = useRef(0);
  const [rows, setRows] = useState(() => portRows(value, kind)?.map(row => ({ ...row, formKey: nextKey.current++ })) ?? null);
  const [undo, setUndo] = useState(null);
  useEffect(() => {
    const nextRows = portRows(value, kind);
    setRows(nextRows?.map(row => ({ ...row, formKey: nextKey.current++ })) ?? null);
    setUndo(null);
  }, [value, kind]);
  const entry = kind === 'entry_ports';
  const title = entry ? '入口端口' : '出口端口';
  if (rows === null) return <label>{title} · 原始 JSON 修复<textarea className="control textarea" name={kind} defaultValue={json(value)} rows="8" spellCheck={false} /><small>当前结构无法表单化；保留原文，修复后重新应用。</small></label>;
  const change = (index, patch) => {
    setUndo(null);
    setRows(current => current.map((row, offset) => offset === index ? { ...row, ...patch } : row));
  };
  const removed = value.filter(port => !rows.some(row => row.port.trim() === port.port));
  const impacts = removed.map(port => ({ port: port.port, ...findPortReferences(config, unitIndex, kind, port.port) }));
  return <section className="orch-port-editor" aria-label={`${title}配置`}>
    <h4>{title} <span>{rows.length}</span></h4>
    <input type="hidden" name={`${kind}_mode`} value="form" />
    <input type="hidden" name={kind} value={JSON.stringify(rows)} />
    {rows.map((row, index) => {
      const rowIssues = validationIssues.filter(issue => issue.target?.portKind === kind && issue.target.portIndex === index);
      const conditionIssue = rowIssues.find(issue => issue.path?.includes('.completion.deterministic'));
      const conditionPath = conditionIssue?.path.match(/^(.*?)(?:\.(?:fact|event|state|llm)\.)/)?.[1];
      return <fieldset className={`orch-port-row ${rowIssues.length ? 'has-validation-error' : ''}`} key={row.formKey}
        data-port-index={index} aria-invalid={rowIssues.length ? 'true' : undefined}>
      <legend>{title} {index + 1}</legend>
      <label>端口标识<input className="control input" data-validation-field="port" value={row.port} onChange={event => change(index, { port: event.target.value })} required /></label>
      {entry ? <>
        <label>进入前须就绪的字段<textarea className="control textarea" data-validation-field="requires" value={row.requires} onChange={event => change(index, { requires: event.target.value })} rows="2" placeholder="每行一个字段；留空表示无前提" /></label>
        {graph && <label>内容层入口<input className="control input" value={row.goto} onChange={event => change(index, { goto: event.target.value })} placeholder="子节点 ID.入口端口" /></label>}
      </> : <>
        <label className="orch-checkbox"><input type="checkbox" checked={row.deterministicEnabled} onChange={event => change(index, { deterministicEnabled: event.target.checked })} />确定性完成条件</label>
        {row.deterministicEnabled && <ConditionEditor value={row.deterministic} label="完成条件" onChange={value => change(index, { deterministic: value })} fields={fields}
          validationPath={conditionPath || '$.completion.deterministic'} />}
        <label className="orch-checkbox"><input type="checkbox" checked={row.llmEnabled} onChange={event => change(index, { llmEnabled: event.target.checked })} />模型完成判据</label>
        {row.llmEnabled && <label>模型判据<textarea className="control textarea" value={row.llm} onChange={event => change(index, { llm: event.target.value })} rows="2" /></label>}
        {Object.hasOwn(row.value, 'exits') && <details><summary>候选去处（R1）</summary><label>候选去处 JSON<textarea className="control textarea" value={row.exits} onChange={event => change(index, { exits: event.target.value })} rows="3" spellCheck={false} /></label></details>}
      </>}
      {rowIssues.map((issue, issueIndex) => <small className="orch-validation-port-error" key={`${issue.path}:${issueIndex}`}>
        {issue.path} · {issue.message || issue.code || '校验失败'}
      </small>)}
      <button className="btn btn-ghost" type="button" disabled={atomic && rows.length <= 1} onClick={() => {
        setUndo(rows);
        setRows(current => current.filter((_, offset) => offset !== index));
      }}>删除{title} {index + 1}</button>
    </fieldset>;
    })}
    {!rows.length && <p className="helper">尚无{title}。添加后声明本单元的公开接口。</p>}
    <button className="btn btn-secondary" type="button" disabled={atomic && rows.length >= 1} onClick={() => {
      setUndo(null);
      const row = portRows([entry ? { port: '', requires: [], ...(graph ? { goto: '' } : {}) } : { port: '', completion: { deterministic: {} } }], kind)[0];
      setRows(current => [...current, { ...row, formKey: nextKey.current++ }]);
    }}>添加{title}</button>
    {undo && <button className="btn btn-ghost" type="button" onClick={() => { setRows(undo); setUndo(null); }}>撤销删除{title}（应用前）</button>}
    {impacts.length > 0 && <section className="orch-port-impact" aria-label={`${title}引用影响`}>
      <h4>应用前检查引用</h4>
      <p className="helper">以下原端口将不再存在；引用保持原样，请逐项修复并运行服务端校验。</p>
      {impacts.map(impact => <div key={impact.port}>
        <strong>{impact.port} · {impact.references.length} 处已识别引用</strong>
        {impact.references.length > 0 && <ul>{impact.references.map(ref => <li key={ref.path}>{ref.label} · {ref.value}<code>{ref.path}</code></li>)}</ul>}
        {impact.diagnostics.map(message => <p className="helper" key={message}>{message}</p>)}
      </div>)}
    </section>}
    {atomic && <p className="helper">原子单元固定一个入口、一个出口。</p>}
  </section>;
}

function Inspector({ node, edge, model, readOnly, workspace, config, onEnter, isNew, validationIssues = [] }) {
  const [error, setError] = useState('');
  if (edge) return <EdgeInspector key={edge.key} edge={edge} model={model} readOnly={readOnly} workspace={workspace} config={config} isNew={isNew} />;
  if (!node) return <aside className="orch-inspector"><h3>单元详情</h3><p>在图或清单中选择一个单元，核对入口前提、出口完成条件和异常去处。</p></aside>;
  const { unit, index } = node;
  const concurrent = unit.load_mode === 'concurrent';
  const initialScope = scopeForm(unit.load_scope);
  const auxiliaryTargets = unitAuxiliaryTargets(config, unit);
  const submit = event => {
    event.preventDefault();
    if (readOnly) return;
    const form = new FormData(event.currentTarget);
    try {
      const patch = Object.fromEntries(['entry_ports', 'exit_ports', 'on_event', 'waits'].map(key => {
        const raw = JSON.parse(form.get(key));
        const value = form.get(`${key}_mode`) === 'form'
          ? serializePortRows(raw, key, { graph: unit.body?.kind === 'graph' }) : raw;
        if (!Array.isArray(value)) throw new Error(`${key} 必须是数组`);
        return [key, value];
      }));
      if (!Object.hasOwn(unit, 'waits') && !patch.waits.length) delete patch.waits;
      patch.max_rounds = Number(form.get('max_rounds'));
      if (!Number.isSafeInteger(patch.max_rounds) || patch.max_rounds < 1) throw new Error('进入上限必须是正整数');
      let nextLoadScope;
      if (concurrent && initialScope) {
        nextLoadScope = serializeScope(unit.load_scope, { mode: form.get('load_scope_mode'),
          after: form.get('load_scope_after'), exclude: form.get('load_scope_exclude') });
      }
      if (unit.body?.kind === 'tool') {
        const toolId = String(form.get('tool_id') || '').trim();
        const version = String(form.get('tool_version') || '').trim();
        if (!toolId || !version) throw new Error('工具 ID 和版本不能为空');
        patch.body = { ...unit.body, tool_ref: { ...unit.body.tool_ref, tool_id: toolId, version } };
      }
      if (concurrent && initialScope) patch.load_scope = nextLoadScope;
      if (!workspace.patchUnit(index, patch)) throw new Error('单元或编辑状态已变化，请重新选择后修改');
    } catch (cause) { setError(cause.message); }
  };
  return <aside className="orch-inspector" aria-label="单元检视器" tabIndex={-1}>
    <div className="orch-inspector-title"><h3>{unit.unit_id}</h3><span>v{String(unit.version ?? '未填')} · {readOnly ? '只读' : '草稿'}</span></div>
    {atomSummary(unit) && <p className="orch-atom-summary" aria-label="内容层类型">{atomSummary(unit)}</p>}
    <p>配置修改先应用到草稿，再通过页面下方的“保存草稿”提交。</p>
    <p>端口改名或删除不会自动修改连线引用；请同步调整连线，再运行服务端校验。</p>
    {unit.body?.kind === 'graph' && onEnter && <button className="btn btn-secondary" type="button" onClick={() => onEnter(node.localId)}>展开内容层</button>}
    <form onSubmit={submit}>
      <fieldset disabled={readOnly}>
        <label>进入上限<input className="control input" type="number" name="max_rounds" min="1" step="1" defaultValue={unit.max_rounds} required /></label>
        {concurrent && <section className="orch-concurrent-scope" aria-label="加载范围">
          <h4>加载范围</h4>
          <p className="helper">默认全池可召回；可按当前路由步骤收窄。</p>
          {initialScope ? <><label>范围模式<select className="control input" name="load_scope_mode" defaultValue={initialScope.mode}>
            <option value="all">全池可召回</option>
            <option value="after">仅某步骤之后</option>
            <option value="exclude">排除指定步骤</option>
            <option value="both">步骤之后，并排除指定步骤</option>
          </select></label>
          <label>起始路由单元<input className="control input" name="load_scope_after" defaultValue={initialScope.after} placeholder="例如 U-咨询" /></label>
          <label>排除路由单元<textarea className="control textarea" name="load_scope_exclude" defaultValue={initialScope.exclude} rows="3" placeholder="每行一个 unit_id" /></label></>
          : <p className="field-error" role="alert">当前加载范围结构无法表单化，原文保持不变，请在原始 Unit 清单修复。</p>}
        </section>}
        {['entry_ports', 'exit_ports'].map(kind => <PortFields key={kind} kind={kind} value={unit[kind]} graph={unit.body?.kind === 'graph'} atomic={model.versioned && unit.body?.kind !== 'graph'} fields={Object.keys(config?.persona?.fields || {})} config={config} unitIndex={index}
          validationIssues={validationIssues.filter(issue => issue.target?.unitIndex === index)} />)}
        {unit.body?.kind === 'tool' && <section className="orch-atom-form" aria-label="工具资源引用">
          <h4>工具资源引用</h4>
          <p className="helper">必须匹配场景包中冻结的 ToolManifest；保存草稿不会授予执行权限。</p>
          <label>工具 ID<input className="control input" name="tool_id" defaultValue={unit.body.tool_ref?.tool_id || ''} required /></label>
          <label>工具版本<input className="control input" name="tool_version" defaultValue={unit.body.tool_ref?.version || ''} required /></label>
        </section>}
        <UnitAuxiliaryEditor unit={unit} eventTargets={auxiliaryTargets} waitTargets={auxiliaryTargets} />
        {!readOnly && <button className="btn btn-primary" type="submit">应用单元修改</button>}
      </fieldset>
      {error && <p className="field-error" role="alert">{error}</p>}
    </form>
    <details><summary>字段、回退与内容层</summary><dl>
      <dt>读取字段</dt><dd>{list(unit.reads).join('、') || '无'}</dd>
      <dt>写入字段</dt><dd>{list(unit.writes).join('、') || '无'}</dd>
      <dt>兜底</dt><dd><pre>{json(unit.fallback)}</pre></dd>
      <dt>内容层</dt><dd><pre>{json(unit.body)}</pre></dd>
    </dl></details>
  </aside>;
}

function RuleProjection({ config, events }) {
  return <section className="orch-rule-view" aria-label="判定规则投影">
    <h3>G0 确定性闸门</h3>
    {list(config.g0_gates).length ? list(config.g0_gates).map((gate, index) => <pre key={index}>{json(gate)}</pre>) : <p>尚未声明闸门。</p>}
    <h3>硬规则</h3>
    {list(config.hard_rules).length ? list(config.hard_rules).map((rule, index) => <pre key={index}>{json(rule)}</pre>) : <p>尚未声明硬规则。</p>}
    <h3>边界事件</h3>
    {events.length ? events.map((event, index) => <p key={index}><strong>{event.owner}</strong> · {String(event.event)} → {String(event.goto)} · {String(event.scope)}</p>) : <p>尚未声明边界事件。</p>}
    <p className="helper">事件独立列出，不画成普通连线。规则的修改入口在“边界”分区。</p>
  </section>;
}

function UnitList({ model, selected, choose }) {
  const nodes = model.nodes.filter(node => !node.terminal);
  return <div className="orch-list"><table className="data-table"><thead><tr><th>单元</th><th>入口</th><th>{model.versioned ? '当前层出边' : '出口与候选去处'}</th></tr></thead><tbody>{nodes.map(node => <tr key={node.id} className={node.id === selected ? 'is-selected' : ''}>
    <td><button className="button-link" type="button" aria-pressed={node.id === selected} onClick={() => choose(node.id)}>{node.unit.unit_id}</button><small>v{String(node.unit.version ?? '未填')}{node.entry ? ' · 入口单元' : ''} · {comparisonLabel(node.comparison)}</small></td>
    <td>{list(node.unit.entry_ports).map(port => port?.port).join('、')}</td>
    <td>{model.versioned ? [...model.edges, ...model.waitEdges].filter(edge => edge.source === node.id).map(edge => <p key={edge.id}>{edge.label} · {model.nodes.find(target => target.id === edge.target)?.unit.unit_id}</p>) : list(node.unit.exit_ports).map((port, index) => <p key={index}>{String(port?.port || '')} → {list(port?.exits).map(target => typeof target === 'string' ? target : json(target)).join('、')}</p>)}</td>
  </tr>)}</tbody></table>{!nodes.length && <p>当前没有可显示的路由单元。</p>}</div>;
}

function ConcurrentTray({ model, selected, choose, readOnly, workspace }) {
  const configuredLimit = model.concurrentConfig?.max_units;
  const [limit, setLimit] = useState(configuredLimit == null ? '' : String(configuredLimit));
  const scopeChanged = event => {
    const value = event.currentTarget.value;
    setLimit(value);
    const parsed = Number(value);
    if (Number.isSafeInteger(parsed) && parsed > 0) workspace.updateField('concurrent_config.max_units', parsed);
  };
  return <section className="orch-tray" aria-label="并发加载配置">
    <div className="orch-tray-header">
      <div><h3>并发能力 <span>{model.concurrent.length}</span></h3><p className="helper">不参与路由；仅在当前轮作为应答能力候选。</p></div>
      <label>并发加载上限<input className="control input orch-concurrent-limit" type="number" min="1" step="1" value={limit}
        disabled={readOnly} onChange={scopeChanged} aria-describedby="orch-concurrent-limit-help" /></label>
    </div>
    <p id="orch-concurrent-limit-help" className="helper">每轮最多同时加载 N 个并发单元；缺省或非法值会由服务端校验提示。</p>
    {model.concurrent.length ? <div className="orch-concurrent-items">{model.concurrent.map(node => <button key={node.id} className={`orch-concurrent-item ${selected === node.id ? 'is-selected' : ''}`} type="button" aria-pressed={selected === node.id} onClick={() => choose(node.id)}>
      <strong>{node.unit.unit_id}</strong><span>{node.loadScope?.label || '全池可召回'}</span>
    </button>)}</div> : <p>暂无并发单元。</p>}
    <p className="helper">加载范围默认全池；选中单元后可按步骤收窄。范围修改写回同一份草稿。</p>
  </section>;
}

function EdgeList({ model, selected, choose, readOnly, workspace, validationIssues = [] }) {
  const [error, setError] = useState('');
  return <section className="orch-edge-list" aria-label="当前层边清单"><h3>当前层连线优先级</h3>
    {!readOnly && <button className="btn btn-secondary" type="button" disabled={!model.edgeSources?.length || !model.edgeTargets?.length}
      onClick={() => choose('new-edge')}>新增连线</button>}
    {workspace.state.orchestration.deletedEdge && <p role="status">已删除连线。<button className="button-link" type="button" disabled={readOnly} onClick={() => {
      if (!workspace.restoreGraphEdge()) setError('连线或编辑状态已变化，无法撤销；当前配置已保留。');
    }}>撤销删除连线</button></p>}
    {error && <p className="field-error" role="alert">{error}</p>}
    {model.edges.length ? <ol>{model.edges.map(edge => {
      const edgeConfig = edgeConfigOf(edge);
      const foundIssues = validationIssues.filter(issue => issue.target?.kind === 'edge'
        && JSON.stringify(issue.target.layerPath || []) === JSON.stringify(edge.layerPath || []) && issue.target.configIndex === edge.configIndex);
      return <li key={edge.key} className={selected === edge.key ? 'is-selected' : ''}>
      <button className="button-link" type="button" aria-pressed={selected === edge.key} aria-label={`${edgeConfig.id || '未命名'} · ${edgeConfig.from} → ${edgeConfig.to}${foundIssues.length ? `，${foundIssues.length} 项服务端校验问题` : ''}`} onClick={() => choose(edge.key)}>
        <span>{edge.order + 1}</span> {edgeConfig.id || '未命名'} · {edgeConfig.from} → {edgeConfig.to} {comparisonLabel(edge.comparison)}{foundIssues.length ? ` · 服务端校验问题 ${foundIssues.length} 项` : ''}
      </button>
    </li>;
    })}</ol> : <p>当前层没有可编辑的有效连线。</p>}
  </section>;
}

function Orchestration({ workspace }) {
  const state = workspace.state;
  const config = state.comparison?.after.config || state.readOnlySnapshot?.config || state.selectedCandidate?.config || state.editorConfig;
  const viewState = state.orchestration;
  const [layerPath, setLayerPath] = useState(viewState.layerPath || []);
  const workspaceRef = useRef(null);
  const restoreBreadcrumbFocus = useRef(false);
  const canvasRef = useRef(null);
  const flowRef = useRef(null);
  const model = useMemo(() => state.comparison ? projectComparison(state.comparison, layerPath) : projectOrchestration(config, layerPath), [config, layerPath, state.comparison]);
  const validationIssues = list(state.validation?.issues).map(issue => ({ ...issue, target: locateValidationIssue(config, issue.path) }));
  const advisoryDismissals = state.selectedCandidate
    ? list(state.selectedCandidate.review_summary) : list(state.draft?.advisory_dismissals);
  const [overlayMode, setOverlayMode] = useState(viewState.overlayMode || 'off');
  const changeOverlayMode = value => { viewState.overlayMode = value; setOverlayMode(value); };
  const overlay = overlayMode !== 'off' && state.readOnlySnapshot?.version_id === state.runOverlay?.version_id
    ? state.runOverlay : null;
  const [view, setView] = useState(viewState.view);
  useEffect(() => {
    if (!canvasRef.current) return;
    let frame;
    const observer = new ResizeObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => flowRef.current?.fitView({ padding: 0.15, maxZoom: 1, duration: 0 }));
    });
    observer.observe(canvasRef.current);
    return () => { observer.disconnect(); cancelAnimationFrame(frame); };
  }, [view, layerPath]);
  useEffect(() => {
    if (!restoreBreadcrumbFocus.current) return;
    restoreBreadcrumbFocus.current = false;
    workspaceRef.current?.querySelector('nav[aria-label="编排层级"] [aria-current="page"]')?.focus();
  }, [layerPath]);
  const [selected, setSelected] = useState(viewState.selected);
  useEffect(() => { setSelected(viewState.selected); }, [viewState.selected]);
  const [sessionPositions, setSessionPositions] = useState({});
  const [focusMode, setFocusMode] = useState(false);
  const [validationFocus, setValidationFocus] = useState(null);
  const [repairPath, setRepairPath] = useState('');
  const readOnly = configurationReadOnly(state) || Boolean(state.jsonErrors.units);
  const choose = id => { viewState.selected = id; setSelected(id); };
  const repairOriginal = path => {
    if (typeof path !== 'string') return false;
    if (path.startsWith('$.units[')) {
      const editor = document.querySelector('[data-r1-json="units"]');
      const details = editor?.closest('details');
      if (!editor || !details) return false;
      details.open = true;
      requestAnimationFrame(() => { editor.focus({ preventScroll: true }); editor.scrollIntoView({ block: 'center' }); });
      return true;
    }
    if (path.startsWith('$.orchestration')) {
      setRepairPath('orchestration');
      workspace.setTab('flow');
      return true;
    }
    const [, root] = /^\$\.([A-Za-z_$][\w$]*)/.exec(path) || [];
    const tabs = { persona: 'persona', g0_gates: 'boundary', hard_rules: 'boundary', task_blueprints: 'task', ai_reception: 'reception' };
    if (!root || !tabs[root]) return false;
    workspace.setTab(tabs[root]);
    requestAnimationFrame(() => {
      const name = path.slice(2).split(/[.[]/, 1)[0];
      const target = document.querySelector(`[data-r1-json="${name}"]`) || document.querySelector(`[data-r1-bind="${path.slice(2)}"]`);
      target?.focus({ preventScroll: true });
      target?.scrollIntoView({ block: 'center' });
    });
    return true;
  };
  const locateIssue = issue => {
    const target = issue.target;
    if (!target) { repairOriginal(issue.path); return; }
    if (state.comparison) { repairOriginal(issue.path); return; }
    const targetLayer = target.layerPath || [];
    const targetModel = projectOrchestration(config, targetLayer);
    let selectedId = null;
    if (target.kind === 'edge') selectedId = targetModel.edges.find(edge => edge.configIndex === target.configIndex)?.key || null;
    else selectedId = targetModel.nodes.find(node => node.localId === target.localId || node.id === target.localId)?.id || null;
    viewState.layerPath = targetLayer;
    setLayerPath(targetLayer);
    viewState.view = 'graph';
    setView('graph');
    choose(selectedId);
    setValidationFocus({ target, path: issue.path, revision: state.validation?.revision });
  };
  useEffect(() => {
    if (!validationFocus || JSON.stringify(validationFocus.target.layerPath || []) !== JSON.stringify(layerPath)) return;
    const frame = requestAnimationFrame(() => {
      const inspector = workspaceRef.current?.querySelector('.orch-inspector');
      let field = null;
      const target = validationFocus.target;
      if (target.kind === 'edge') {
        const leaf = /\.([A-Za-z_$][\w$]*)$/.exec(validationFocus.path)?.[1];
        if (leaf === 'from' || leaf === 'to' || leaf === 'max_rounds' || leaf === 'counter' || leaf === 'exit') {
          field = inspector?.querySelector(`[name="${leaf}"]`);
        } else if (leaf === 'condition' || validationFocus.path.includes('.condition.')) {
          field = [...(inspector?.querySelectorAll('[data-condition-path]') || [])]
            .find(control => control.dataset.conditionPath === validationFocus.path)
            || inspector?.querySelector('.orch-condition-editor textarea')
            || inspector?.querySelector('.orch-condition-editor select');
        }
      } else if (target.portKind && Number.isSafeInteger(target.portIndex)) {
        const region = inspector?.querySelector(`[aria-label="${target.portKind === 'entry_ports' ? '入口' : '出口'}端口配置"]`);
        const row = region?.querySelectorAll('.orch-port-row')[target.portIndex];
        if (validationFocus.path.includes('.completion.deterministic')) {
          field = [...(row?.querySelectorAll('[data-condition-path]') || [])]
            .find(control => control.dataset.conditionPath === validationFocus.path)
            || row?.querySelector('.orch-condition-editor textarea')
            || row?.querySelector('.orch-condition-editor select');
        }
        field ||= row?.querySelector(`[data-validation-field="${target.portField || 'port'}"]`) || row?.querySelector('input, textarea, select');
      }
      field ||= inspector;
      if (field) {
        field.focus?.({ preventScroll: true });
        field.scrollIntoView?.({ block: 'center' });
      }
    });
    return () => cancelAnimationFrame(frame);
  }, [validationFocus, layerPath, selected]);
  const selectCanvasNode = changes => {
    const change = changes.filter(item => item.type === 'select' && item.selected).at(-1);
    if (change && model.nodes.some(node => node.id === change.id && !node.terminal)) choose(change.id);
  };
  const selectCanvasEdge = changes => {
    const change = changes.filter(item => item.type === 'select' && item.selected).at(-1);
    const edge = model.edges.find(item => item.id === change?.id);
    if (edge) choose(edge.key);
  };
  const switchView = next => { viewState.view = next; setView(next); };
  const navigate = (path, selectedLocalId = null, focusBreadcrumb = false) => {
    restoreBreadcrumbFocus.current = focusBreadcrumb;
    viewState.layerPath = path;
    setLayerPath(path);
    choose(selectedLocalId === null ? null : `${JSON.stringify(path)}:node:${selectedLocalId}`);
  };
  const handleNodeEnter = event => {
    if (event.key !== 'Enter' || event.isComposing) return;
    const element = event.target.closest?.('.react-flow__node[data-id]');
    const node = model.nodes.find(item => item.id === element?.getAttribute('data-id'));
    if (!node || node.unit.body?.kind !== 'graph') return;
    event.preventDefault();
    event.stopPropagation();
    navigate([...layerPath, node.localId]);
  };
  const handleEscape = event => {
    if (event.key !== 'Escape' || event.isComposing || !layerPath.length) return;
    event.preventDefault();
    event.stopPropagation();
    navigate(layerPath.slice(0, -1), layerPath.at(-1), true);
  };
  useEffect(() => {
    window.addEventListener('keydown', handleEscape);
    return () => window.removeEventListener('keydown', handleEscape);
  }, [layerPath]);
  const selectedNode = [...model.nodes, ...model.concurrent].find(node => node.id === selected && !node.terminal);
  const isNew = selected === 'new-edge' && model.versioned && !readOnly;
  const selectedEdge = isNew ? { key: 'new-edge', layerPath, edgeConfig: {
    from: model.edgeSources?.[0]?.value, to: model.edgeTargets?.[0]?.value, condition: {},
  } } : model.edges.find(edge => edge.key === selected);
  if (selectedEdge && !isNew) {
    const issuePath = validationFocus?.target?.kind === 'edge'
      && validationFocus.target.configIndex === selectedEdge.configIndex
      && JSON.stringify(validationFocus.target.layerPath || []) === JSON.stringify(selectedEdge.layerPath || [])
      ? validationFocus.path : null;
    const conditionRoot = typeof issuePath === 'string' ? issuePath.indexOf('.condition') : -1;
    selectedEdge.validationPath = conditionRoot >= 0 ? issuePath.slice(0, conditionRoot + '.condition'.length) : null;
  }
  const positions = useMemo(() => {
    const saved = sessionPositions[JSON.stringify(layerPath)] || {};
    return layout(model).map(node => ({ ...node, position: saved[node.id] || node.position }));
  }, [model, sessionPositions, layerPath]);
  const issuesForNode = node => {
    const data = node.data || node;
    return validationIssues.filter(issue => issue.target?.kind === 'node'
      && ((issue.target.unitIndex != null && issue.target.unitIndex === data.index)
        || issue.target.localId === data.localId || issue.target.localId === data.id));
  };
  const issuesForEdge = edge => validationIssues.filter(issue => issue.target?.kind === 'edge'
    && JSON.stringify(issue.target.layerPath || []) === JSON.stringify(layerPath) && issue.target.configIndex === edge.configIndex);
  const nodes = positions.map(node => {
    const foundIssues = issuesForNode(node);
    const routeSummaries = model.edges.filter(edge => edge.source === node.id).slice(0, 2).map(edge => {
      const edgeConfig = edgeConfigOf(edge);
      const target = model.nodes.find(item => item.id === edge.target)?.unit.unit_id || edgeConfig.to;
      return `${edge.sourcePort} · ${conditionSummary(edgeConfig.condition)} → ${target}`;
    });
    return { ...node, selected: node.id === selected,
      data: { ...node.data, routeSummaries, validationIssues: foundIssues,
        overlay: overlayForNode(node.data, overlay, layerPath), overlayAggregate: overlay, overlayMode } };
  });
  const edges = [...model.edges, ...model.waitEdges].map(edge => {
    const foundIssues = issuesForEdge(edge);
    return { ...edge,
    ...(edge.wait ? {} : { sourceHandle: `out:${edge.portIndex}`,
      targetHandle: `in:${Math.max(0, list(model.nodes.find(node => node.id === edge.target)?.unit.entry_ports).findIndex(port => port?.port === edge.entryPort))}` }),
    markerEnd: { type: MarkerType.ArrowClosed }, style: { ...(edge.wait ? { stroke: '#c27619', strokeDasharray: '3 5' } : { stroke: '#9ba3ad', strokeDasharray: model.versioned ? undefined : '5 4' }), ...comparisonEdgeStyle(edge.comparison), ...(foundIssues.length ? { stroke: '#a73528', strokeWidth: 2.5, strokeDasharray: '4 3' } : {}) },
    selected: edge.key === selected, validationIssues: foundIssues,
    label: [edge.label, foundIssues.length ? `服务端校验问题 ${foundIssues.length} 项` : '', comparisonLabel(edge.comparison), overlayLabel(overlayForEdge(edge, overlay, layerPath), overlay, overlayMode)].filter(Boolean).join(' · '),
    labelStyle: { fontSize: 11, fill: '#424245' }, labelBgPadding: [5, 4], focusable: true,
    ariaLabel: `${edge.label}${foundIssues.length ? `，${foundIssues.length} 项服务端校验问题：${foundIssues.map(issue => issue.message).join('；')}` : ''}` };
  });
  return <div ref={workspaceRef} className={`orch-workspace ${focusMode ? 'is-focus-mode' : ''}`} onKeyDownCapture={handleNodeEnter}>
    <header className="orch-toolbar">
      <div role="group" aria-label="流程投影">{[['graph', '编排图'], ['list', '单元清单'], ['rules', '判定规则']].map(([key, label]) => <button className={`btn ${view === key ? 'btn-primary' : 'btn-ghost'}`} type="button" key={key} aria-pressed={view === key} onClick={() => switchView(key)}>{label}</button>)}</div>
      <div className="orch-toolbar-meta"><span>{model.nodes.filter(node => !node.terminal).length} 个路由单元 · {readOnly ? '只读快照' : '草稿编辑'}</span>
        {model.versioned && view === 'graph' && <>
          <button className="btn btn-ghost" type="button" aria-label="自动布局" title="恢复拓扑自动布局" onClick={() => setSessionPositions(current => ({ ...current, [JSON.stringify(layerPath)]: {} }))}>自动布局</button>
          <button className="btn btn-ghost" type="button" aria-label={focusMode ? '退出专注' : '专注画布'} onClick={() => setFocusMode(value => !value)}>{focusMode ? '退出专注' : '专注画布'}</button>
        </>}
      </div>
    </header>
    {model.versioned && <nav aria-label="编排层级">{model.breadcrumbs.map((crumb, index) => <React.Fragment key={index}>{index > 0 && ' / '}<button className="button-link" type="button" aria-current={index === model.breadcrumbs.length - 1 ? 'page' : undefined} onClick={() => navigate(crumb.path)}>{crumb.label}</button></React.Fragment>)}</nav>}
    <p className="orch-caption">{model.versioned ? `当前层路由：${model.routingMode || '未声明'}。实线与编号来自边清单顺序。新图冻结仍受运行能力检查限制。` : '连线表示契约中的候选出口，虚线不代表已执行路径，也不代表优先级。'}</p>
    {validationIssues.length > 0 && <section className="orch-validation-results" aria-label="服务端校验结果" role="region">
      <h3>服务端校验问题 · r{String(state.validation.revision)}</h3>
      <ul>{validationIssues.map((issue, index) => <li key={`${issue.path}:${index}`} data-validation-path={issue.path}>
        <div><code>{issue.path || '$'}</code><span>{issue.message || issue.code || '校验失败'}</span></div>
        {issue.target ? <button className="button-link" type="button" onClick={() => locateIssue(issue)}>定位到对象</button>
          : /^\$\.(?:units|orchestration|persona|g0_gates|hard_rules|task_blueprints|ai_reception)(?:\.|\[)/.test(String(issue.path || ''))
            ? <button className="button-link" type="button" onClick={() => repairOriginal(issue.path)}>转到原始配置修复</button>
            : <small>无法安全映射；请按完整路径在对应配置分区修复。</small>}
      </li>)}</ul>
      <p className="helper">问题来自服务端当前 revision；保存草稿仍可继续，候选冻结以服务端校验为准。未能安全映射的路径保留原样，不猜测对象。</p>
    </section>}
    {repairPath === 'orchestration' && <details className="orch-validation-raw" open>
      <summary>原始 orchestration 配置修复 · 服务器校验路径保留</summary>
      <label>orchestration JSON<textarea className="control textarea" rows="12" spellCheck={false}
        value={workspace.state.jsonInputs?.orchestration ?? json(config?.orchestration ?? {})}
        onChange={event => workspace.updateJsonField('orchestration', event.currentTarget.value)} />
      </label>
      {workspace.state.jsonErrors?.orchestration && <p className="field-error" role="alert">JSON 格式错误：{workspace.state.jsonErrors.orchestration}</p>}
    </details>}
    {state.comparison && <ComparisonLegend />}
    {model.versioned && !state.comparison && <RunOverlayControls workspace={workspace} mode={overlayMode} setMode={changeOverlayMode} />}
    {list(model.advisories).map(advisory => {
      const dismissal = advisoryDismissals.find(item => item.advisory_key === advisory.key);
      const busy = state.advisoryBusyKey === advisory.key;
      return <aside className={`orch-advisory is-${advisory.level}`} role="status" key={advisory.key}>
        <strong>{advisory.level === 'strong' ? '闭集强提示' : '闭集提示'} · {advisory.closedSetSize} 个候选</strong>
        <span>{advisory.message}</span><small>{advisory.alternatives}</small>
        {dismissal ? <small>已记录忽略 · {dismissal.actor_id} · r{dismissal.source_revision}</small>
          : <button className="btn btn-secondary" type="button" disabled={!workspace.canDismissAdvisory?.(layerPath) || busy}
            onClick={() => void workspace.dismissAdvisory?.(layerPath)}>{busy ? '记录中…' : '忽略并留痕'}</button>}
      </aside>;
    })}
    <div className={`orch-layout ${focusMode ? 'is-focused' : ''}`}>
      <div className="orch-main">
        {view === 'graph' && (nodes.length ? <div ref={canvasRef} className="orch-canvas" aria-label="单元编排图">
          <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} onNodeClick={(_, node) => choose(node.id)}
            onNodesChange={changes => {
              selectCanvasNode(changes);
              const moved = changes.filter(change => change.type === 'position' && change.position);
              if (moved.length) setSessionPositions(current => ({ ...current, [JSON.stringify(layerPath)]: {
                ...(current[JSON.stringify(layerPath)] || {}), ...Object.fromEntries(moved.map(change => [change.id, change.position])),
              } }));
            }} onEdgesChange={selectCanvasEdge}
            onInit={instance => { flowRef.current = instance; }}
            onEdgeClick={(_, edge) => edge.key && choose(edge.key)}
            onPaneClick={() => choose(null)}
            nodesDraggable nodesConnectable={false} edgesReconnectable={false} deleteKeyCode={null}
            fitView fitViewOptions={{ padding: 0.15, maxZoom: 1 }} minZoom={0.2} maxZoom={1.5} autoPanOnNodeFocus={false} proOptions={{ hideAttribution: false }}
            ariaLabelConfig={{ 'controls.zoomIn.ariaLabel': '放大', 'controls.zoomOut.ariaLabel': '缩小', 'controls.fitView.ariaLabel': '适应画布' }}>
            <Background color="#d8dce2" gap={20} size={1} />
            <Controls showInteractive={false} />
          </ReactFlow>
        </div> : <div className="orch-empty"><h3>还没有路由单元</h3><p>可在下方原始清单添加 Unit。不会自动导入本地演示或写入服务端。</p></div>)}
        {view === 'list' && <UnitList model={model} selected={selected} choose={choose} />}
        {model.versioned && view !== 'rules' && <EdgeList model={model} selected={selected} choose={choose} readOnly={readOnly} workspace={workspace} validationIssues={validationIssues} />}
        {view === 'rules' && <RuleProjection config={config || {}} events={model.events} />}
        <ConcurrentTray model={model} selected={selected} choose={choose} readOnly={readOnly} workspace={workspace} />
        {model.issues.length > 0 && <section className="orch-projection-issues" role="status"><h3>投影提示</h3>{model.issues.map((issue, index) => <p key={index}><code>{issue.path}</code> {issue.message}</p>)}<p>原文保留在下方清单；这些提示不能代替服务端校验。</p></section>}
      </div>
      {state.comparison ? <ComparisonInspector node={selectedNode} edge={selectedEdge} onEnter={id => navigate([...layerPath, id])} />
        : <Inspector key={selectedEdge?.key || selectedNode?.id || 'empty'} node={selectedNode} edge={selectedEdge} model={model}
          readOnly={readOnly} workspace={workspace} config={config} isNew={isNew} validationIssues={selectedNode ? issuesForNode(selectedNode) : selectedEdge ? issuesForEdge(selectedEdge) : []}
          onEnter={model.versioned ? id => navigate([...layerPath, id]) : null} />}
    </div>
  </div>;
}

class ProjectionBoundary extends React.Component {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    return this.state.failed ? <p role="alert">画布无法解析当前草稿。请展开下方原始 Unit 清单修复，原文尚未改变。</p> : this.props.children;
  }
}

export function mountOrchestration(container, workspace) {
  const root = createRoot(container);
  const update = nextWorkspace => root.render(<ProjectionBoundary><Orchestration workspace={nextWorkspace} /></ProjectionBoundary>);
  update(workspace);
  const unmount = () => root.unmount();
  unmount.update = update;
  return unmount;
}
