async (page) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const check = (condition, message) => { if (!condition) throw new Error(message); };
  await page.addInitScript(() => { window.__LOOMRISE_CONFIG_API__ = 'http://127.0.0.1:8783'; });
  await page.goto('about:blank');
  await page.goto('http://127.0.0.1:18765/#/configuration?agent=course-demo&section=r1-server');
  const candidates = await page.evaluate(async () => {
    const { createConfigurationClient } = await import('/r1-configuration.js');
    const client = createConfigurationClient();
    const draft = await client.request('draft.get', { agent_id: 'course-demo' });
    const config = { ...draft.config, units: [{ unit_id: '接待', version: 1, load_mode: 'routed', reads: [], writes: [],
      entry_ports: [{ port: 'in', requires: [] }], exit_ports: [{ port: 'done', completion: { deterministic: {} }, exits: ['self.done'] }],
      on_event: [], fallback: { kind: 'human' }, max_rounds: 3,
      body: { kind: 'say', text: '虚构服务说明', verbatim_reason: '范围披露' } }],
      orchestration: { schema_version: 'unit-graph-v1', kind: 'graph', routing: { mode: 'deterministic' },
        nodes: [{ id: 'reception', unit_ref: { unit_id: '接待', version: 1 } }], entry: 'reception.in', input_fields: [],
        edges: ['first', 'second'].map(id => ({ id, from: 'reception.done', to: 'end', condition: {} })),
        on_event: [], fallback: { kind: 'human' } } };
    const freeze = async revision => client.request('candidate.freeze', { agent_id: 'course-demo', expected_revision: revision, idempotency_key: `history-check-${revision}` });
    const first = await client.request('draft.save', { agent_id: 'course-demo', expected_revision: draft.revision, config });
    const before = await freeze(first.revision);
    config.units[0].exit_ports[0].port = 'approved';
    config.units[0].exit_ports[0].exits = ['self.approved'];
    config.units[0].body.text = '新版虚构服务说明';
    config.orchestration.edges = [{ id: 'first', from: 'reception.approved', to: 'end', condition: {} }];
    const second = await client.request('draft.save', { agent_id: 'course-demo', expected_revision: first.revision, config });
    const after = await freeze(second.revision);
    return { before: before.candidate_id, after: after.candidate_id };
  });
  await page.reload();
  await page.locator('[data-r1-bind="persona.goal"]').fill('浏览比较时保留的未保存目标');
  await page.locator('[data-action="r1-tab"][data-tab="flow"]').click();
  await page.getByRole('button', { name: '单元清单', exact: true }).click();
  await page.locator('.orch-list').getByRole('button', { name: '接待', exact: true }).click();
  await page.getByLabel('进入上限', { exact: true }).fill('5');
  await page.getByRole('button', { name: '应用单元修改', exact: true }).click();
  await page.getByRole('button', { name: '撤销修改', exact: true }).click();
  check(await page.getByLabel('进入上限', { exact: true }).inputValue() === '3', '应用后的端口检视器修改未撤销');
  await page.getByRole('button', { name: '重做修改', exact: true }).click();
  check(await page.getByLabel('进入上限', { exact: true }).inputValue() === '5', '应用后修改未重做');
  await page.evaluate(() => { location.hash = '#/agents'; });
  await page.getByRole('heading', { name: '专家列表', exact: true }).first().waitFor();
  await page.evaluate(() => { location.hash = '#/configuration?agent=course-demo&section=r1-server'; });
  await page.locator('[data-action="r1-tab"][data-tab="persona"]').click();
  check(await page.locator('[data-r1-bind="persona.goal"]').inputValue() === '浏览比较时保留的未保存目标', '跨页返回丢失草稿');
  await page.locator('[data-action="r1-tab"][data-tab="history"]').click();
  await page.locator('[data-r1-comparison="before"]').selectOption(`candidate:${candidates.before}`);
  await page.locator('[data-r1-comparison="after"]').selectOption(`candidate:${candidates.after}`);
  await page.getByRole('button', { name: '查看差异', exact: true }).click();
  await page.getByLabel('版本差异图例', { exact: true }).waitFor();
  check(await page.getByRole('button', { name: '保存草稿', exact: true }).count() === 0, '版本比较允许写入');
  check(await page.locator('.orch-port.is-diff-removed').count() === 1, '删除端口未单独显示');
  check(await page.locator('.orch-port.is-diff-added').count() === 1, '新增端口未单独显示');
  check(await page.locator('.orch-edge-list').getByText(/second.*删除/).count() > 0, '删除连线未保留');
  await page.getByRole('button', { name: '单元清单', exact: true }).click();
  await page.locator('.orch-list').getByRole('button', { name: '接待', exact: true }).click();
  await page.getByLabel('对象差异检视器', { exact: true }).waitFor();
  check(await page.getByRole('button', { name: '应用单元修改', exact: true }).count() === 0, '差异检视器存在写入口');
  await page.getByRole('button', { name: '编排图', exact: true }).click();
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.locator('.orch-canvas').scrollIntoViewIfNeeded();
    await page.getByRole('button', { name: '适应画布', exact: true }).click();
    await page.locator('.react-flow__node').first().waitFor({ state: 'visible' });
    await page.waitForFunction(() => {
      const canvas = document.querySelector('.orch-canvas').getBoundingClientRect();
      return [...document.querySelectorAll('.react-flow__node')].every(node => {
        const rect = node.getBoundingClientRect();
        return rect.left >= canvas.left - 1 && rect.right <= canvas.right + 1;
      });
    });
    check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${width}px 比较页面横向溢出`);
    await page.locator('.orch-workspace').screenshot({ path: `output/playwright/r3-version-comparison-${width}.png` });
  }
  await page.getByRole('button', { name: '退出比较', exact: true }).click();
  await page.locator('[data-action="r1-tab"][data-tab="persona"]').click();
  check(await page.locator('[data-r1-bind="persona.goal"]').inputValue() === '浏览比较时保留的未保存目标', '退出比较丢失未保存草稿');
  await page.getByRole('button', { name: '重新读取', exact: true }).click();
  await page.getByText('未保存内容已保留', { exact: true }).waitFor();
  await page.getByRole('button', { name: '继续编辑', exact: true }).click();
  check(await page.locator('[data-r1-bind="persona.goal"]').inputValue() === '浏览比较时保留的未保存目标', '取消重读丢失输入');
  check(!errors.length, errors.join('; '));
  return { passed: true, appliedUndoRedo: true, navigationPreservesDraft: true, immutableComparison: true, portsAndDeletedEdges: true, widths: [1440, 390], errors };
}
