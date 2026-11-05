import React, { useState } from 'react';
import { ConditionEditor } from './condition-editor.jsx';
import {
  readUnitEventRows, serializeUnitEventRows,
  readUnitWaitRows, serializeUnitWaitRows,
} from './unit-auxiliary.js';

const eventOptions = [
  ['user_hangup', '用户挂断'], ['side_effect_unknown', '业务结果不明'],
  ['timeout', '超时'], ['handoff', '人工移交'],
];
const scopeOptions = [['self', '本单元'], ['subtree', '本单元子树']];
const json = value => JSON.stringify(value ?? [], null, 2);
const valueOf = item => typeof item === 'string' ? item : item?.value;
const labelOf = (item, value) => typeof item === 'string' ? item : item?.label || value;

function RawJson({ name, title, value }) {
  const [text, setText] = useState(() => json(value));
  return <details className="orch-aux-raw">
    <summary>{title} JSON</summary>
    <label>{title}原文<textarea className="control textarea" name={name} value={text}
      onChange={event => setText(event.target.value)} rows="5" spellCheck={false} /></label>
    <p className="helper">当前结构无法用表单安全表示；原文保持不变，可在此修复。</p>
  </details>;
}

function EventRows({ value, targets }) {
  const [rows, setRows] = useState(() => readUnitEventRows(value, targets));
  if (rows === null) return <RawJson name="on_event" title="边界事件" value={value} />;
  let serialized = '', error = '';
  try { serialized = JSON.stringify(serializeUnitEventRows(rows, targets)); }
  catch (cause) { error = cause.message; }
  const update = (index, patch) => setRows(current => current.map((row, offset) => offset === index ? { ...row, ...patch } : row));
  return <section className="orch-aux-editor" aria-label="边界事件与作用域">
    <input type="hidden" name="on_event" value={serialized} />
    <h4>边界事件与作用域</h4>
    {rows.map((row, index) => <fieldset className="orch-aux-row" key={index}>
      <legend>事件 {index + 1}</legend>
      <label>事件<select className="control input" value={row.event} onChange={event => update(index, { event: event.target.value })}>
        {eventOptions.map(([event, label]) => <option value={event} key={event}>{label} · {event}</option>)}
      </select></label>
      <label>作用域<select className="control input" value={row.scope} onChange={event => update(index, { scope: event.target.value })}>
        {scopeOptions.map(([scope, label]) => <option value={scope} key={scope}>{label}</option>)}
      </select></label>
      <label>去处<select className="control input" value={row.goto} onChange={event => update(index, { goto: event.target.value })}>
        <option value="">请选择当前层去处</option>
        {targets.map(item => { const value = valueOf(item); return value && <option key={value} value={value}>{labelOf(item, value)}</option>; })}
      </select></label>
      <label className="orch-aux-toggle"><input type="checkbox" checked={row.whenEnabled}
        onChange={event => update(index, { whenEnabled: event.target.checked })} />附加确定性条件</label>
      {row.whenEnabled && <ConditionEditor label="事件条件" name={`unit-event-when-${index}`}
        value={row.whenText} onChange={whenText => update(index, { whenText })} />}
      <button className="btn btn-ghost" type="button" aria-label={`删除事件 ${index + 1}`}
        onClick={() => setRows(current => current.filter((_, offset) => offset !== index))}>删除事件</button>
    </fieldset>)}
    {!rows.length && <p className="helper">尚未声明边界事件。</p>}
    <button className="btn btn-secondary" type="button" onClick={() => setRows(current => [...current,
      { source: {}, event: eventOptions[0][0], scope: 'self', goto: valueOf(targets[0]) || '', whenEnabled: false, whenText: '{}' }])}>添加边界事件</button>
    {error && <p className="field-error" role="alert">{error}</p>}
  </section>;
}

function WaitRows({ value, targets }) {
  const [rows, setRows] = useState(() => readUnitWaitRows(value, targets));
  if (rows === null) return <RawJson name="waits" title="等待" value={value} />;
  let serialized = '', error = '';
  try { serialized = JSON.stringify(serializeUnitWaitRows(rows, targets)); }
  catch (cause) { error = cause.message; }
  const update = (index, patch) => setRows(current => current.map((row, offset) => offset === index ? { ...row, ...patch } : row));
  return <section className="orch-aux-editor" aria-label="等待与超时去处">
    <input type="hidden" name="waits" value={serialized} />
    <h4>等待与超时去处</h4>
    {rows.map((row, index) => <fieldset className="orch-aux-row" key={index}>
      <legend>等待 {index + 1}</legend>
      <label>事件名称<input className="control input" value={row.on}
        onChange={event => update(index, { on: event.target.value })} placeholder="例如 approval.received" /></label>
      <label className="orch-aux-toggle"><input type="checkbox" checked={row.timeoutEnabled}
        onChange={event => update(index, { timeoutEnabled: event.target.checked })} />设置超时去处</label>
      {row.timeoutEnabled && <>
        <label>超时毫秒<input className="control input" type="number" min="1" step="1" value={row.timeoutMs}
          onChange={event => update(index, { timeoutMs: event.target.value })} /></label>
        <label>超时后去处<select className="control input" value={row.timeoutTo} onChange={event => update(index, { timeoutTo: event.target.value })}>
          <option value="">请选择当前层去处</option>
          {targets.map(item => { const value = valueOf(item); return value && <option key={value} value={value}>{labelOf(item, value)}</option>; })}
        </select></label>
      </>}
      <button className="btn btn-ghost" type="button" aria-label={`删除等待 ${index + 1}`}
        onClick={() => setRows(current => current.filter((_, offset) => offset !== index))}>删除等待</button>
    </fieldset>)}
    {!rows.length && <p className="helper">尚未声明等待事件。</p>}
    <button className="btn btn-secondary" type="button" onClick={() => setRows(current => [...current,
      { source: {}, on: '', timeoutEnabled: false, timeoutMs: '', timeoutTo: '' }])}>添加等待</button>
    {error && <p className="field-error" role="alert">{error}</p>}
  </section>;
}

export function UnitAuxiliaryEditor({ unit, eventTargets = [], waitTargets = eventTargets }) {
  const eventValue = Object.hasOwn(unit || {}, 'on_event') ? unit.on_event : [];
  const waitValue = Object.hasOwn(unit || {}, 'waits') ? unit.waits : [];
  return <>
    <EventRows value={eventValue} targets={eventTargets} />
    <WaitRows value={waitValue} targets={waitTargets} />
  </>;
}
