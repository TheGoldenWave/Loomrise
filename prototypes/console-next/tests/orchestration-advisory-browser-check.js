async page => {
  const check = (value, message) => { if (!value) throw new Error(message); };
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const origin = await page.evaluate(() => window.__LOOMRISE_CONFIG_API__ || 'http://127.0.0.1:8767');
  await page.goto('http://127.0.0.1:18765/#/configuration?agent=course-demo&section=r1-server');
  const request = (action, payload) => page.evaluate(async ({ origin, action, payload }) => {
    const response = await fetch(`${origin}/api/configuration`, { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action, payload }) });
    const value = await response.json();
    if (!response.ok || !value.ok) throw new Error(value.error?.message || action);
    return value.result;
  }, { origin, action, payload });

  const draft = await request('draft.get', { agent_id: 'course-demo' });
  const units = [], nodes = [], edges = [];
  for (let index = 0; index <= 6; index++) {
    const id = `advisory-unit-${index}`;
    units.push({ unit_id: id, version: 1, load_mode: 'routed',
      entry_ports: [{ port: 'from_start', requires: [] }], reads: [], writes: [],
      exit_ports: [{ port: 'done', completion: { deterministic: {} }, exits: ['self.done'] }],
      on_event: [], fallback: { kind: 'human' }, max_rounds: 1,
      body: { kind: 'say', text: '本机虚构固定内容', verbatim_reason: '浏览器验收 fixture' } });
    nodes.push({ id: `advisory-node-${index}`, unit_ref: { unit_id: id, version: 1 } });
  }
  for (let index = 1; index <= 6; index++) {
    edges.push({ id: `route-${index}`, from: 'advisory-node-0.done', to: `advisory-node-${index}.from_start`, condition: {} });
    edges.push({ id: `finish-${index}`, from: `advisory-node-${index}.done`, to: 'end', condition: {} });
  }
  const config = { persona: { fields: {} }, units, g0_gates: [], hard_rules: [], task_blueprints: [],
    orchestration: { schema_version: 'unit-graph-v1', kind: 'graph', routing: { mode: 'llm' },
      nodes, entry: 'advisory-node-0.from_start', input_fields: [], edges, on_event: [], fallback: { kind: 'human' } } };
  await request('draft.save', { agent_id: 'course-demo', expected_revision: draft.revision, config });
  await page.reload();
  await page.locator('[data-action="r1-tab"][data-tab="flow"]').click();
  await page.getByText('闭集提示', { exact: false }).waitFor();
  const dismiss = page.getByRole('button', { name: '忽略并留痕', exact: true });
  check(await dismiss.isEnabled(), '已保存草稿的忽略动作未启用');
  await dismiss.click();
  await page.getByText(/已记录忽略/).waitFor();
  const current = await request('draft.get', { agent_id: 'course-demo' });
  check(current.advisory_dismissals?.[0]?.closed_set_size === 7, '服务端未记录重算后的闭集大小');
  check(current.advisory_dismissals?.[0]?.actor_id, '服务端未绑定可信操作者');

  await page.getByRole('button', { name: '冻结候选', exact: true }).click();
  await page.getByRole('region', { name: '画布提示忽略记录', exact: true }).waitFor();
  const summary = await page.getByRole('region', { name: '画布提示忽略记录', exact: true }).textContent();
  check(summary.includes(current.advisory_dismissals[0].actor_id) && summary.includes('闭集 7'), '候选详情未显示操作者或闭集数');
  check(summary.includes(current.advisory_dismissals[0].created_at), '候选详情未显示留痕时间');
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 960 });
    check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${width}px 评审摘要横向溢出`);
  }
  check(!errors.length, `浏览器错误：${errors.join('；')}`);
  return { passed: true, closedSetSize: 7, serverActorRecorded: true, candidateSummary: true, widths: [1440, 390], errors };
}
