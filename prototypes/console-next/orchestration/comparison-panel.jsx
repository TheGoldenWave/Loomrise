import React from 'react';
import { comparisonLabel } from './comparison.js';
import './comparison.css';

const json = value => JSON.stringify(value, null, 2) ?? 'null';
const kinds = { unit: 'Unit', node: '节点', entry_port: '入口端口', exit_port: '出口端口', edge: '边', edge_order: '边优先级', configuration: '配置' };
const operations = { added: '新增', removed: '删除', changed: '修改', priority: '优先级变化', positional: '按位置比较' };

export function ComparisonLegend() {
  return <p className="orch-comparison-legend" aria-label="版本差异图例">
    <span className="orch-diff-added">新增</span><span className="orch-diff-removed">删除</span><span className="orch-diff-changed">修改 / 优先级变化</span>
    <span>只读比较 · 删除对象保留在原层级</span>
  </p>;
}

export function ComparisonInspector({ node, edge, onEnter }) {
  const item = edge || node, diff = item?.comparison;
  if (!item) return <aside className="orch-inspector"><h3>版本差异</h3><p>选择节点、端口所在单元或连线，查看各字段的前后值。端口变更与节点变更分别标注。</p></aside>;
  const name = edge ? `边 ${edge.edgeConfig?.id || ''}` : `单元 ${node.unit.unit_id}`;
  const expandable = node && [diff?.before, diff?.after].some(unit => unit?.body?.kind === 'graph');
  return <aside className="orch-inspector orch-comparison-inspector" aria-label="对象差异检视器">
    <div className="orch-inspector-title"><h3>{name}</h3><span>{comparisonLabel(diff) || '本对象无直接字段变化'} · 只读</span></div>
    {expandable && onEnter && <button className="btn btn-secondary" type="button" onClick={() => onEnter(node.localId)}>展开内容层差异</button>}
    {diff?.priority && <p className="orch-diff-changed">优先级 {diff.beforeOrder} → {diff.afterOrder}</p>}
    {(diff?.changes || []).map((change, index) => <section key={`${change.path}:${index}`} className="orch-comparison-change">
      <h4>{kinds[change.object_type] || change.object_type} {change.object_id} · {operations[change.operation] || change.operation}</h4>
      <code>{change.path}</code>
      <p>之前</p><pre>{change.before_exists === false ? '不存在' : json(change.before)}</pre>
      <p>之后</p><pre>{change.after_exists === false ? '不存在' : json(change.after)}</pre>
    </section>)}
    {!diff?.changes?.length && <p>没有独立字段差异；新增或删除状态由对象在所选版本中的存在情况决定。</p>}
    <details><summary>对象快照</summary><p>之前</p><pre>{json(diff?.before)}</pre><p>之后</p><pre>{json(diff?.after)}</pre></details>
  </aside>;
}
