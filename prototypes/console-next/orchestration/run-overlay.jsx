import React, { useState } from 'react';

export function RunOverlayControls({ workspace, mode, setMode }) {
  const state = workspace.state;
  const snapshot = state.readOnlySnapshot;
  const saved = state.orchestration;
  const [windowKind, setWindowKind] = useState(saved.overlayWindow || 'week');
  const [channel, setChannel] = useState(saved.overlayChannel || '');
  if (!snapshot?.version_id) return <p className="orch-caption">查看实际走向：在版本记录中打开稳定版本，再进入流程。</p>;
  const overlay = state.runOverlay?.version_id === snapshot.version_id ? state.runOverlay : null;
  const load = async event => {
    event.preventDefault();
    const end = new Date();
    const from = windowKind === 'release' ? snapshot.created_at : new Date(end.getTime() - 604800000).toISOString();
    setMode('count');
    await workspace.loadRunOverlay({ versionId: snapshot.version_id, from, to: end.toISOString(), channel });
  };
  return <section className="orch-overlay-controls" aria-label="实际走向">
    <form onSubmit={load}>
      <label>时间范围<select className="control input" value={windowKind} onChange={event => {
        saved.overlayWindow = event.target.value; setWindowKind(event.target.value);
      }}><option value="week">最近 7 天</option><option value="release" disabled={!snapshot.created_at}>此版本建立以来</option></select></label>
      <label>渠道<select className="control input" value={channel} onChange={event => {
        saved.overlayChannel = event.target.value; setChannel(event.target.value);
      }}><option value="">全部渠道</option><option value="text">文字</option><option value="voice">语音</option></select></label>
      <button className="btn btn-secondary" type="submit" disabled={state.runOverlayStatus === 'loading' || !workspace.loadRunOverlay}>{state.runOverlayStatus === 'loading' ? '正在查询…' : '查询实际走向'}</button>
      {overlay && <label>显示内容<select className="control input" value={mode} onChange={event => setMode(event.target.value)}>
        <option value="off">关闭</option><option value="count">进入数</option><option value="detail">执行时长与终止</option>
      </select></label>}
    </form>
    {state.runOverlayError && <p role="alert" className="field-error">{state.runOverlayError}。请核对范围后重试。</p>}
    {overlay && <div role="status">
      <p>版本 {overlay.version_id} · {overlay.channel === 'text' ? '文字' : overlay.channel === 'voice' ? '语音' : '全部渠道'} · {overlay.sample_count} 次运行</p>
      <p className="helper">{overlay.time_window?.from} 至 {overlay.time_window?.to}（不含结束时刻）。节点或边样本不足 30 时不显示比例。</p>
      {overlay.sample_count === 0 && <p>这个范围暂无可核对的路由记录，可切换时间范围或渠道。</p>}
      {mode === 'detail' && <p>{overlay.average_duration_ms == null ? '路由耗时暂无测量数据。' : `平均路由耗时 ${overlay.average_duration_ms}ms。`} 节点角标展示解释器执行时长均值与样本数，不代表访客等待或实际送达；终止数按已校验的最后有效步骤映射到对应层级节点。路由记录：{Object.entries(overlay.terminations || {}).map(([key, count]) => `${({ completed: '已走完', waiting: '等待中', fallback: '进入兜底', gated: '被拦截' })[key] || key} ${count}`).join(' · ') || '暂无'}。路由结束不等于业务完成。</p>}
    </div>}
  </section>;
}
