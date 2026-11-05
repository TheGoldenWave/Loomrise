async (page) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const check = (value, message) => { if (!value) throw new Error(message); };
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto('http://127.0.0.1:18765/orchestration/');
  await page.evaluate(async () => {
    const unit = id => ({ unit_id: id, version: 1, load_mode: 'routed', reads: [], writes: [],
      entry_ports: [{ port: 'from_start', requires: [] }], exit_ports: [{ port: 'done', completion: { deterministic: {} }, exits: ['self.done'] }],
      on_event: [], fallback: { kind: 'clarify' }, max_rounds: 3,
      body: { kind: 'say', text: '服务范围披露', verbatim_reason: '必须原文展示' } });
    const child = unit('范围披露'), parent = unit('接待包'), concurrent = unit('政策补充');
    concurrent.load_mode = 'concurrent';
    concurrent.load_scope = { after: parent.unit_id, exclude: [child.unit_id] };
    parent.entry_ports[0].goto = 'intro.from_start';
    parent.body = { kind: 'graph', routing: { mode: 'deterministic' }, nodes: [{ id: 'intro', unit_ref: { unit_id: child.unit_id, version: 1 } }],
      edges: [
        { id: 'done', from: 'intro.done', to: 'self.done', condition: {} },
        { id: 'done-second', from: 'intro.done', to: 'self.done', condition: {} },
      ] };
    const config = { units: [parent, child, concurrent], concurrent_config: { max_units: 2 }, orchestration: { schema_version: 'unit-graph-v1', kind: 'graph', routing: { mode: 'deterministic' },
      nodes: [{ id: 'reception', unit_ref: { unit_id: parent.unit_id, version: 1 } }], entry: 'reception.from_start',
      edges: [{ id: 'finish', from: 'reception.done', to: 'end', condition: {} }], on_event: [], fallback: { kind: 'human' } } };
    await Promise.all(['/styles.css', '/dist/orchestration.css'].map(href => new Promise((resolve, reject) => {
      const link = document.createElement('link'); link.rel = 'stylesheet'; link.href = href;
      link.onload = resolve; link.onerror = () => reject(new Error(`测试样式加载失败：${href}`)); document.head.append(link);
    })));
    document.body.replaceChildren();
    const container = document.createElement('main'); document.body.append(container);
    const { mountOrchestration } = await import('/dist/orchestration.js');
    // Test fixture only: no application state or SQLite endpoint is modified.
    const { createR1ConfigurationWorkspace } = await import('/r1-configuration.js');
    let unmount;
    const workspace = createR1ConfigurationWorkspace({ client: {}, onChange() {
      unmount?.update(workspace);
    } });
    Object.assign(workspace.state, { status: 'ready', editorConfig: config });
    window.edgeFixtureWorkspace = workspace;
    unmount = mountOrchestration(container, workspace);
  });
  await page.getByRole('button', { name: '单元清单', exact: true }).waitFor();
  await page.getByRole('button', { name: '政策补充', exact: false }).click();
  check(await page.getByRole('combobox', { name: '范围模式' }).inputValue() === 'both', '组合范围没有完整呈现');
  await page.getByRole('button', { name: '应用单元修改', exact: true }).click();
  check(await page.evaluate(() => window.edgeFixtureWorkspace.state.editorConfig.units[2].load_scope.exclude[0] === '范围披露'), '应用未修改的组合范围时丢失排除限制');
  check(await page.locator('.react-flow__node').filter({ hasText: '政策补充' }).count() === 0, '并发单元错误进入路由图');
  await page.getByRole('button', { name: '单元清单', exact: true }).click();
  await page.getByRole('button', { name: '接待包', exact: true }).click();
  const entries = page.getByRole('region', { name: '入口端口配置', exact: true });
  const exits = page.getByRole('region', { name: '出口端口配置', exact: true });
  await entries.getByLabel('端口标识', { exact: true }).fill('renamed');
  const entryImpact = page.getByRole('region', { name: '入口端口引用影响', exact: true });
  await entryImpact.getByText('$.orchestration.entry', { exact: true }).waitFor();
  check(await page.evaluate(() => window.edgeFixtureWorkspace.state.editorConfig.units[0].entry_ports[0].port === 'from_start'), '影响预览不应提前改写草稿');
  await entries.getByLabel('端口标识', { exact: true }).fill('from_start');
  check(await entryImpact.count() === 0, '恢复端口名应清除失效引用提示');
  await exits.getByLabel('端口标识', { exact: true }).fill('renamed');
  const exitImpact = page.getByRole('region', { name: '出口端口引用影响', exact: true });
  await exitImpact.getByText('$.orchestration.edges[0].from', { exact: true }).waitFor();
  await exitImpact.getByText('$.units[0].body.edges[0].to', { exact: true }).waitFor();
  await page.setViewportSize({ width: 390, height: 960 });
  check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), '引用影响路径在手机端横向溢出');
  await exitImpact.screenshot({ path: 'output/playwright/r3-port-impact-mobile.png' });
  await page.setViewportSize({ width: 1440, height: 960 });
  await exits.getByLabel('端口标识', { exact: true }).fill('done');
  await entries.getByRole('button', { name: '添加入口端口', exact: true }).click();
  await entries.getByLabel('端口标识', { exact: true }).nth(1).fill('verified');
  await entries.getByLabel('进入前须就绪的字段', { exact: true }).nth(1).fill('user.verified');
  await entries.getByLabel('内容层入口', { exact: true }).nth(1).fill('intro.from_start');
  await exits.getByRole('button', { name: '添加出口端口', exact: true }).click();
  await exits.getByLabel('端口标识', { exact: true }).nth(1).fill('reviewed');
  const firstCompletion = exits.locator('.orch-port-row').first();
  await firstCompletion.locator('.orch-condition-tree select').first().selectOption('fact');
  await firstCompletion.locator('.orch-condition-tree input').first().fill('verified');
  await firstCompletion.locator('.orch-condition-value input').fill('yes');
  await exits.getByLabel('模型完成判据', { exact: true }).nth(1).check();
  await exits.getByLabel('模型判据', { exact: true }).fill('审阅完成');
  await page.getByRole('button', { name: '应用单元修改', exact: true }).click();
  check(await page.evaluate(() => window.edgeFixtureWorkspace.state.editorConfig.units[0].entry_ports[1].goto === 'intro.from_start'), '新增端口未映射内容层入口');
  check(await page.evaluate(() => window.edgeFixtureWorkspace.state.editorConfig.units[0].exit_ports[1].completion.llm === '审阅完成'), '出口模型完成判据未写回草稿');
  check(await page.evaluate(() => window.edgeFixtureWorkspace.state.editorConfig.units[0].exit_ports[0].completion.deterministic.fact.field === 'verified'), '条件树修改未写回草稿');
  await page.evaluate(() => window.edgeFixtureWorkspace.undo());
  await page.waitForFunction(() => document.querySelectorAll('[aria-label="入口端口配置"] .orch-port-row').length === 1
    && document.querySelectorAll('[aria-label="出口端口配置"] .orch-port-row').length === 1);
  check(await entries.getByLabel('端口标识', { exact: true }).count() === 1, '撤销没有恢复入口端口行');
  check(await exits.getByLabel('端口标识', { exact: true }).count() === 1, '撤销没有恢复出口端口行');
  check(await exits.locator('.orch-port-row').first().locator('.orch-condition-tree select').first().inputValue() === 'always', '撤销没有恢复完成条件树');
  await page.evaluate(() => window.edgeFixtureWorkspace.redo());
  await page.waitForFunction(() => document.querySelectorAll('[aria-label="入口端口配置"] .orch-port-row').length === 2
    && document.querySelector('[aria-label="出口端口配置"] .orch-port-row .orch-condition-tree select')?.value === 'fact');
  check(await entries.getByLabel('端口标识', { exact: true }).count() === 2, '重做没有恢复入口端口行');
  check(await exits.locator('.orch-port-row').first().locator('.orch-condition-tree select').first().inputValue() === 'fact', '重做没有恢复完成条件树');
  check(await exits.locator('.orch-port-row').first().locator('.orch-condition-tree input').first().inputValue() === 'verified', '重做没有恢复完成条件字段');
  await page.evaluate(() => window.edgeFixtureWorkspace.undo());
  await page.waitForFunction(() => document.querySelectorAll('[aria-label="入口端口配置"] .orch-port-row').length === 1
    && document.querySelectorAll('[aria-label="出口端口配置"] .orch-port-row').length === 1);
  await page.getByRole('button', { name: '应用单元修改', exact: true }).click();
  check(await page.evaluate(() => window.edgeFixtureWorkspace.state.editorConfig.units[0].entry_ports.length === 1
    && window.edgeFixtureWorkspace.state.editorConfig.units[0].exit_ports.length === 1
    && Object.keys(window.edgeFixtureWorkspace.state.editorConfig.units[0].exit_ports[0].completion.deterministic).length === 0), '撤销后直接应用又写回了旧端口或旧条件');
  await page.evaluate(() => window.edgeFixtureWorkspace.redo());
  await exits.getByRole('button', { name: '删除出口端口 1', exact: true }).click();
  check(await exits.getByLabel('端口标识', { exact: true }).inputValue() === 'reviewed', '删除首端口后行身份错误');
  check(await exits.getByRole('textbox', { name: '模型判据', exact: true }).inputValue() === '审阅完成', '删除首行丢失后续行判据');
  await exits.getByRole('button', { name: '撤销删除出口端口（应用前）', exact: true }).click();
  check(await exits.getByLabel('端口标识', { exact: true }).first().inputValue() === 'done', '撤销未恢复端口原位置');
  check(await exits.getByRole('textbox', { name: '模型判据', exact: true }).inputValue() === '审阅完成', '撤销丢失其他端口判据');
  await entries.getByRole('button', { name: '删除入口端口 2', exact: true }).click();
  await entries.getByLabel('进入前须就绪的字段', { exact: true }).fill('ready');
  check(await entries.getByRole('button', { name: '撤销删除入口端口（应用前）', exact: true }).count() === 0, '后续编辑应清除旧撤销');
  await entries.getByRole('textbox', { name: '进入前须就绪的字段', exact: true }).fill('');
  await entries.getByRole('button', { name: '添加入口端口', exact: true }).click();
  await entries.getByLabel('端口标识', { exact: true }).nth(1).fill('verified');
  await entries.getByRole('button', { name: '删除入口端口 2', exact: true }).click();
  await exits.getByRole('button', { name: '删除出口端口 2', exact: true }).click();
  await page.getByRole('button', { name: '应用单元修改', exact: true }).click();
  check(await page.evaluate(() => window.edgeFixtureWorkspace.state.editorConfig.units[0].entry_ports.length === 1 && window.edgeFixtureWorkspace.state.editorConfig.units[0].exit_ports.length === 1), '删除端口未写回草稿');
  await page.getByRole('button', { name: '展开内容层', exact: true }).click();
  await page.getByRole('navigation', { name: '编排层级' }).getByRole('button', { name: '接待包', exact: true }).waitFor();
  check(await page.getByRole('button', { name: '范围披露', exact: true }).count() === 1, '下钻后未显示子单元清单');
  await page.getByRole('button', { name: '范围披露', exact: true }).click();
  await page.getByRole('button', { name: '编排图', exact: true }).click();
  check(await page.locator('.orch-node.is-selected').count() === 1, '子层投影选中态丢失');
  check(await page.locator('.react-flow__node').count() === 2, '子层未显示单元与出口');
  await page.locator('.react-flow__edge').first().waitFor();
  check(await page.locator('.react-flow__edge').count() === 2, '子层端口边未显示');
  await page.locator('.orch-edge-list ol button').first().click();
  check(await page.getByRole('complementary', { name: '边检视器' }).count() === 1, '边清单未打开边检视器');
  await page.getByRole('combobox', { name: '边条件编辑方式', exact: true }).selectOption('json');
  await page.locator('.orch-inspector textarea[name="condition"]').fill('{"fact":{"field":"ready","op":"eq","value":true}}');
  await page.locator('.orch-inspector select[name="to"]').selectOption('self.done');
  await page.getByLabel('执行环').check();
  await page.getByLabel('最大轮数').fill('3');
  await page.getByLabel('计数字段').fill('attempt_count');
  await page.getByRole('button', { name: '应用边修改', exact: true }).click();
  await page.evaluate(() => window.edgeFixtureWorkspace.undo());
  await page.waitForFunction(() => !document.querySelector('[aria-label="边检视器"] input[name="max_rounds"]')
    && document.querySelector('[aria-label="边检视器"] .orch-condition-tree select')?.value === 'always');
  check(!(await page.getByLabel('执行环').isChecked()), '撤销没有恢复边界条件开关');
  check(await page.locator('.orch-inspector .orch-condition-tree select').first().inputValue() === 'always', '撤销没有恢复边条件表单');
  await page.evaluate(() => window.edgeFixtureWorkspace.redo());
  await page.waitForFunction(() => document.querySelector('[aria-label="边检视器"] input[name="max_rounds"]')?.value === '3'
    && document.querySelector('[aria-label="边检视器"] .orch-condition-tree select')?.value === 'fact'
    && document.querySelector('[aria-label="边检视器"] .orch-condition-tree input')?.value === 'ready');
  check(await page.getByLabel('执行环').isChecked(), '重做没有恢复边界条件开关');
  check(await page.locator('.orch-inspector .orch-condition-tree input').first().inputValue() === 'ready', '重做没有恢复边条件表单');
  await page.evaluate(() => window.edgeFixtureWorkspace.undo());
  await page.waitForFunction(() => !document.querySelector('[aria-label="边检视器"] input[name="max_rounds"]'));
  await page.getByRole('button', { name: '应用边修改', exact: true }).click();
  check(await page.evaluate(() => Object.keys(window.edgeFixtureWorkspace.state.editorConfig.units[0].body.edges[0].condition).length === 0
    && !Object.hasOwn(window.edgeFixtureWorkspace.state.editorConfig.units[0].body.edges[0], 'max_rounds')), '撤销后直接应用又写回了旧边条件');
  await page.evaluate(() => window.edgeFixtureWorkspace.redo());
  check(await page.evaluate(() => window.edgeFixtureWorkspace.state.editorConfig.units[0].body.edges[0].window === 'cycle'), '循环边设置未写回当前 Unit 图');
  check(await page.evaluate(() => window.edgeFixtureWorkspace.state.editorConfig.units[0].body.edges[0].condition.fact.field === 'ready'), '边条件未写回当前 Unit 图');
  await page.locator('.orch-edge-list ol button').nth(1).click();
  await page.getByRole('button', { name: '优先级上移' }).click();
  check(await page.evaluate(() => window.edgeFixtureWorkspace.state.editorConfig.units[0].body.edges[0].id === 'done-second'), '边优先级未按数组位置调整');
  check((await page.locator('.orch-edge-list ol button').first().textContent()).includes('done-second'), '清单未重绘调整后的边顺序');
  await page.getByRole('button', { name: '新增连线', exact: true }).click();
  await page.getByLabel('边 ID', { exact: true }).fill('new-branch');
  await page.locator('.orch-inspector select[name="to"]').selectOption('self.done');
  await page.getByRole('button', { name: '添加连线', exact: true }).click();
  check(await page.locator('.orch-edge-list ol button').count() === 3, '新增连线未加入清单');
  check(await page.getByRole('heading', { name: '边 · new-branch', exact: true }).count() === 1, '新增后检视器仍停留在临时新边表单');
  check(await page.getByRole('button', { name: '应用边修改', exact: true }).count() === 1, '新增后没有切换到已保存边的检视器');
  check(await page.evaluate(() => window.edgeFixtureWorkspace.state.editorConfig.units[0].body.edges.at(-1).id === 'new-branch'), '新增未追加当前层末尾');
  await page.getByRole('button', { name: '删除此连线', exact: true }).click();
  check(await page.locator('.orch-edge-list ol button').count() === 2, '删除连线未更新清单');
  await page.getByRole('button', { name: '撤销删除连线', exact: true }).click();
  check(await page.locator('.orch-edge-list ol button').count() === 3, '撤销未恢复连线');
  check(await page.evaluate(() => window.edgeFixtureWorkspace.state.editorConfig.units[0].body.edges.at(-1).id === 'new-branch'), '撤销未恢复原位置');
  await page.getByRole('navigation', { name: '编排层级' }).getByRole('button', { name: '版本路由', exact: true }).click();
  check(await page.locator('.orch-node').filter({ hasText: '接待包' }).count() === 1, '未返回根层');
  check(await page.getByText('新图冻结仍受运行能力检查限制。', { exact: false }).count() === 1, '缺少运行接入状态说明');
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 960 });
    check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${width}px 页面横向溢出`);
  }
  await page.getByRole('button', { name: '单元清单', exact: true }).click();
  await page.locator('.orch-list').getByRole('button', { name: '接待包', exact: true }).click();
  await page.getByRole('button', { name: '展开内容层', exact: true }).click();
  await page.getByRole('button', { name: '编排图', exact: true }).click();
  await page.getByRole('navigation', { name: '编排层级' }).getByRole('button', { name: '接待包', exact: true }).click();
  await page.locator('.orch-edge-list ol button').first().click();
  await page.setViewportSize({ width: 390, height: 844 });
  const [edgeListBox, inspectorBox] = await Promise.all([
    page.locator('.orch-edge-list').boundingBox(), page.getByRole('complementary', { name: '边检视器' }).boundingBox(),
  ]);
  check(edgeListBox.y + edgeListBox.height <= inspectorBox.y + 1, '手机端边清单与检视器发生交叠');
  check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), '手机端边检视器发生横向溢出');
  check(!errors.length, `浏览器错误：${errors.join('；')}`);
  return { passed: true, nestedNavigation: true, sharedSelection: true, portEndpoints: true, portCreateEditDelete: true, portReferenceImpact: true, portDeleteUndoBeforeApply: true, edgeEditing: true, edgeCreateDeleteUndo: true, priorityOrder: true, mobileInspector: true, errors };
}
