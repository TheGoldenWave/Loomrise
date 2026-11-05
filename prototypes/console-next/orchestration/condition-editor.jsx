import React, { useEffect, useId, useState } from 'react';
import { conditionEvents, conditionOperators, newCondition, readCondition, writeCondition } from './conditions.js';

function ConditionTree({ node, onChange, depth = 0, fields, listId, allowModel, validationPath }) {
  const kind = node.kind === 'not' ? 'none_of' : ['all', 'any'].includes(node.kind) ? `${node.kind}_of` : node.kind;
  const update = patch => onChange({ ...node, ...patch });
  const comparisonNeedsValue = !['exists', 'is_set', 'is_unset'].includes(node.op);
  return <div className="orch-condition-tree">
    <label>判断类型<select className="control input" value={kind} onChange={event => {
      const next = event.target.value;
      onChange(['all_of', 'any_of', 'none_of'].includes(next)
        ? { kind: next, children: node.children || (node.kind === 'always' ? newCondition(next).children : [node]) }
        : newCondition(next));
    }}>
      <option value="always">无条件</option><option value="fact">字段比较</option><option value="event">事件发生</option><option value="state">状态窗口</option>
      {allowModel && <option value="llm">模型判据</option>}
      {(depth < 2 || node.children) && <><option value="all_of">全部满足</option><option value="any_of">任一满足</option><option value="none_of" disabled={node.children?.length > 1}>不满足（一个子条件）</option></>}
    </select></label>
    {node.kind === 'llm' && <>
      <label>模型判据<textarea className="control textarea" data-condition-path={`${validationPath}.llm.prompt`} value={node.prompt} onChange={event => update({ prompt: event.target.value })} rows="3" /></label>
      <p className="helper">模型叶仅可正向参与图边路由，不可放入否定条件；路由模式仍须由服务端校验。</p>
    </>}
    {node.kind === 'event' && <>
      <label>事件名称<select className="control input" data-condition-path={`${validationPath}.event.event`} value={node.event} onChange={event => update({ event: event.target.value })}>
        <option value="">请选择事件</option>
        {Object.entries(conditionEvents).map(([value, label]) => <option key={value} value={value}>{label} · {value}</option>)}
      </select></label>
      <details open={Boolean(node.attributesText)}><summary>附加属性（可选）</summary>
        <label>事件属性 JSON<textarea className="control textarea" data-condition-path={`${validationPath}.event.attributes`} value={node.attributesText ?? ''} onChange={event => update({ attributesText: event.target.value })} rows="4" spellCheck={false} placeholder={'例如：{"tool_id":"lookup"}'} /></label>
      </details>
      <p className="helper">属性会与本次事件的结构化属性逐项比较；未知事件来源仍须由服务端接入验证。</p>
    </>}
    {node.kind === 'state' && <>
      <label>统计指标<select className="control input" data-condition-path={`${validationPath}.state.metric`} value={node.metric} onChange={event => update({ metric: event.target.value })}>
        <option value="attempts">尝试次数 · attempts</option><option value="runs">运行次数 · runs</option>
      </select></label>
      <label>统计窗口<select className="control input" data-condition-path={`${validationPath}.state.window`} value={node.window} onChange={event => update({ window: event.target.value })}>
        <option value="cycle">本服务周期 · cycle</option><option value="24h">最近 24 小时 · 24h</option><option value="forever">累计 · forever</option>
      </select></label>
      <label>比较方式<select className="control input" data-condition-path={`${validationPath}.state.op`} value={node.op} onChange={event => update({ op: event.target.value })}>
        {Object.entries({ eq: '等于', ne: '不等于', gt: '大于', gte: '大于等于', lt: '小于', lte: '小于等于' }).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select></label>
      <label>比较值<input className="control input" data-condition-path={`${validationPath}.state.value`} type="number" value={node.value} onChange={event => update({ value: event.target.value })} step="any" /></label>
      <p className="helper">attempts 统计持久工具尝试，runs 统计持久运行；周期统计只读取服务端绑定周期。数据不可用时停止判定，不将缺失当作零。</p>
    </>}
    {node.kind === 'fact' && <>
      <label>比较字段<input className="control input" data-condition-path={`${validationPath}.fact.field`} list={listId} value={node.field} onChange={event => update({ field: event.target.value })} placeholder="选择已声明字段或填写系统字段" /></label>
      <label>比较方式<select className="control input" data-condition-path={`${validationPath}.fact.op`} value={node.op} onChange={event => {
        const op = event.target.value;
        update({ op, ...(['in', 'not_in'].includes(op) ? { type: 'array', value: '[]' }
          : op === 'between' ? { type: 'range', value: '[0,0]' }
            : op === 'matches' ? { type: 'string', value: typeof node.value === 'string' ? node.value : '' }
              : node.op === 'between' ? { type: 'string', value: '' } : {}) });
      }}>{Object.entries(conditionOperators).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      {comparisonNeedsValue && <div className="orch-condition-value">
        {node.op === 'between' ? (() => {
          let bounds = [];
          try { const parsed = JSON.parse(node.value); if (Array.isArray(parsed)) bounds = parsed; } catch { /* keep incomplete range editable */ }
          const changeBound = (index, raw) => {
            const next = [bounds[0] ?? null, bounds[1] ?? null];
            next[index] = raw === '' ? null : Number(raw);
            update({ value: JSON.stringify(next) });
          };
          return <>
            <label>最小值<input className="control input" data-condition-path={`${validationPath}.fact.value[0]`} type="number" step="any" value={typeof bounds[0] === 'number' ? bounds[0] : ''} onChange={event => changeBound(0, event.target.value)} /></label>
            <label>最大值<input className="control input" data-condition-path={`${validationPath}.fact.value[1]`} type="number" step="any" value={typeof bounds[1] === 'number' ? bounds[1] : ''} onChange={event => changeBound(1, event.target.value)} /></label>
          </>;
        })() : node.op === 'matches' ? <>
          <label>正则模式<input className="control input" data-condition-path={`${validationPath}.fact.value`} maxLength={128} value={node.value} onChange={event => update({ value: event.target.value })} /></label>
          <p className="helper">仅支持受限正则子集；模式最多 128 个字符，被匹配字段值最多 1024 个字符。</p>
        </> : <>
          <label>值类型<select className="control input" value={node.type} onChange={event => {
            const type = event.target.value;
            update({ type, value: { string: '', number: '0', boolean: 'true', null: 'null', array: '[]' }[type] });
          }}>{[['string', '文本'], ['number', '数字'], ['boolean', '布尔'], ['null', '空值'], ['array', '列表']].map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          {node.type === 'boolean' ? <label>比较值<select className="control input" data-condition-path={`${validationPath}.fact.value`} value={node.value} onChange={event => update({ value: event.target.value })}><option value="true">true</option><option value="false">false</option></select></label>
          : node.type === 'null' ? <p className="helper">比较 JSON 空值 null</p>
            : <label>{node.type === 'array' ? '比较列表 JSON' : '比较值'}<input className="control input" data-condition-path={`${validationPath}.fact.value`} value={node.value} onChange={event => update({ value: event.target.value })} inputMode={node.type === 'number' ? 'decimal' : undefined} /></label>}
        </>}
      </div>}
    </>}
    {node.children && <div className="orch-condition-children">
      {node.children.map((child, index) => <fieldset key={index}><legend>子条件 {index + 1}</legend>
        <ConditionTree node={child} depth={depth + 1} fields={fields} listId={listId} allowModel={allowModel && kind !== 'none_of'}
          validationPath={`${validationPath}.${node.kind}[${index}]`} onChange={value => update({ children: node.children.map((item, offset) => offset === index ? value : item) })} />
        {kind !== 'none_of' && <button className="btn btn-ghost" type="button" disabled={node.children.length <= 1} onClick={() => update({ children: node.children.filter((_, offset) => offset !== index) })}>删除子条件 {index + 1}</button>}
      </fieldset>)}
      {kind !== 'none_of' && <button className="btn btn-secondary" type="button" onClick={() => update({ children: [...node.children, newCondition('fact')] })}>添加子条件</button>}
    </div>}
  </div>;
}

export function ConditionEditor({ value, name, label = '条件', onChange, fields = [], validationPath = '$.condition' }) {
  const listId = useId();
  const allowModel = name === 'condition';
  const [tree, setTree] = useState(() => { try { return readCondition(JSON.parse(value), 0, allowModel); } catch { return null; } });
  const [mode, setMode] = useState(tree ? 'form' : 'json');
  useEffect(() => {
    let next = null;
    try { next = readCondition(JSON.parse(value), 0, allowModel); } catch { /* malformed conditions stay in JSON mode */ }
    setTree(next);
    setMode(next ? 'form' : 'json');
  }, [value, allowModel]);
  let output = value, error = '';
  if (mode === 'form') {
    try { output = JSON.stringify(writeCondition(tree, 0, allowModel)); }
    catch (cause) { output = ''; error = cause.message; }
  }
  const changeTree = next => {
    setTree(next);
    try { onChange(JSON.stringify(writeCondition(next, 0, allowModel))); }
    catch { onChange(''); }
  };
  const switchMode = event => {
    const next = event.target.value;
    if (next === 'form') {
      try {
        const parsed = readCondition(JSON.parse(value), 0, allowModel);
        if (!parsed) return;
        setTree(parsed);
      } catch { return; }
    } else onChange(output || value);
    setMode(next);
  };
  let canBuild = false;
  try { canBuild = Boolean(readCondition(JSON.parse(value), 0, allowModel)); } catch { /* keep raw draft */ }
  return <section className="orch-condition-editor" aria-label={label}>
    <label>{label}编辑方式<select className="control input" value={mode} onChange={switchMode}>
      <option value="form" disabled={mode === 'json' && !canBuild}>表达式构造器</option><option value="json" disabled={mode === 'form' && Boolean(error)}>原始 JSON</option>
    </select></label>
    {mode === 'form' ? <><input type="hidden" name={name} value={output} />
      <datalist id={listId}>{fields.map(field => <option key={field} value={field} />)}</datalist>
      <ConditionTree node={tree} fields={fields} listId={listId} allowModel={allowModel} validationPath={validationPath} onChange={changeTree} />
      {error && <p className="field-error" role="alert">{error}。修正后可应用或切换原始 JSON。</p>}
    </> : <><label>{label} JSON<textarea className="control textarea" name={name} value={value} onChange={event => onChange(event.target.value)} rows="5" spellCheck={false} /></label>
      {!canBuild && <p className="helper">当前为旧格式、未支持的状态窗口、上下文不允许的模型叶或未支持结构，保留原始 JSON。可修复后切换构造器。</p>}</>}
    <p className="helper">字段声明、类型与可达路径仍须通过服务端校验。</p>
  </section>;
}
