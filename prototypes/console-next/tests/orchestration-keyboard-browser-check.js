async (page) => {
  const check = (value, message) => { if (!value) throw new Error(message); };
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto('http://127.0.0.1:18765/orchestration/');
  await page.evaluate(async () => {
    await Promise.all(['/styles.css', '/dist/orchestration.css'].map(href => new Promise((resolve, reject) => {
      const link = document.createElement('link'); link.rel = 'stylesheet'; link.href = href;
      link.onload = resolve; link.onerror = () => reject(new Error(`测试样式加载失败：${href}`)); document.head.append(link);
    })));
    document.body.replaceChildren();
    const container = document.createElement('main'); document.body.append(container);
    const { mountOrchestration } = await import('/dist/orchestration.js');
    const { createR1ConfigurationWorkspace } = await import('/r1-configuration.js');
    const child = { unit_id: 'U-接待', version: 1, load_mode: 'routed',
      entry_ports: [{ port: 'from_start', requires: [] }], reads: [], writes: [],
      exit_ports: [{ port: 'done', completion: { deterministic: {} }, exits: ['self.done'] }],
      on_event: [], fallback: { kind: 'clarify' }, max_rounds: 2, body: {},
    };
    const review = { ...child, unit_id: 'U-转人工', entry_ports: [{ port: 'from_start', requires: [] }] };
    const parent = { unit_id: 'U-培训流程', version: 1, load_mode: 'routed',
      entry_ports: [{ port: 'from_start', requires: [], goto: 'child.from_start' }], reads: [], writes: [],
      exit_ports: [{ port: 'done', completion: { deterministic: {} }, exits: ['self.done'] }],
      on_event: [{ event: 'handoff', scope: 'subtree', goto: 'review.from_start', reason: '保留此字段' }],
      waits: [{ on: 'approval.requested', timeoutMs: 3000, timeoutTo: 'review.from_start', note: '保留此字段' }],
      fallback: { kind: 'clarify' }, max_rounds: 2,
      body: { kind: 'graph', routing: { mode: 'deterministic' },
        nodes: [
          { id: 'child', unit_ref: { unit_id: child.unit_id, version: child.version } },
          { id: 'review', unit_ref: { unit_id: review.unit_id, version: review.version } },
        ],
        entry: 'child.from_start',
        edges: [
          { id: 'inner-review', from: 'child.done', to: 'review.from_start', condition: {} },
          { id: 'inner-finish', from: 'review.done', to: 'self.done', condition: {} },
        ],
        on_event: [], fallback: { kind: 'human' } },
    };
    let mounted;
    const workspace = createR1ConfigurationWorkspace({ client: {}, onChange() {
      mounted?.update?.(workspace);
    } });
    Object.assign(workspace.state, { status: 'ready', editorConfig: {
      persona: { entry_unit_ids: [parent.unit_id], fields: {} }, units: [parent, child, review],
      orchestration: { schema_version: 'unit-graph-v1', kind: 'graph', routing: { mode: 'deterministic' },
        nodes: [
          { id: 'entry', unit_ref: { unit_id: parent.unit_id, version: parent.version } },
          { id: 'triage', unit_ref: { unit_id: review.unit_id, version: review.version } },
        ], entry: 'entry.from_start',
        edges: [
          { id: 'finish', from: 'entry.done', to: 'end', condition: {} },
          { id: 'triage-finish', from: 'triage.done', to: 'end', condition: {} },
        ], on_event: [], fallback: { kind: 'human' } },
    } });
    window.keyboardWorkspace = workspace;
    mounted = mountOrchestration(container, workspace);
  });

  const node = page.locator('.react-flow__node').filter({ hasText: 'U-培训流程' });
  await node.waitFor();
  let nodeFocused = false;
  for (let step = 0; step < 32; step++) {
    await page.keyboard.press('Tab');
    if (await node.evaluate(element => element.contains(document.activeElement))) {
      nodeFocused = true;
      break;
    }
  }
  check(nodeFocused, '键盘 Tab 无法聚焦编排节点');
  await page.keyboard.press('Enter');
  const parentCrumb = page.getByRole('button', { name: 'U-培训流程', exact: true });
  await parentCrumb.waitFor({ timeout: 3000 });
  check(await parentCrumb.getAttribute('aria-current') === 'page', 'Enter 未直接下钻到图形单元');
  await page.keyboard.press('Escape');
  const rootCrumb = page.getByRole('button', { name: '版本路由', exact: true });
  check(await rootCrumb.getAttribute('aria-current') === 'page', '嵌套图下钻后 Escape 未返回根层');
  check(await rootCrumb.evaluate(element => element === document.activeElement), 'Escape 返回后焦点未恢复到当前层面包屑');

  const listProjection = page.getByRole('button', { name: '单元清单', exact: true });
  const graphProjection = page.getByRole('button', { name: '编排图', exact: true });
  await listProjection.focus();
  await page.keyboard.press('Enter');
  const parentListButton = page.locator('.orch-list button').filter({ hasText: 'U-培训流程' });
  check(await parentListButton.getAttribute('aria-pressed') === 'true', 'Escape 返回后未选中原嵌套单元');
  const rootInspector = page.getByRole('complementary', { name: '单元检视器' });
  const parentRounds = rootInspector.getByLabel('进入上限', { exact: true });
  await parentListButton.focus();
  await page.keyboard.press('Enter');
  await rootInspector.getByRole('heading', { name: 'U-培训流程', exact: true }).waitFor();
  let inspectorFocused = false;
  for (let step = 0; step < 48; step++) {
    if (await parentRounds.evaluate(element => element === document.activeElement)) {
      inspectorFocused = true;
      break;
    }
    await page.keyboard.press('Tab');
  }
  check(inspectorFocused, '键盘焦点无法从清单到达单元检视器');
  await page.keyboard.press(await page.evaluate(() => navigator.platform.includes('Mac') ? 'Meta+A' : 'Control+A'));
  await page.keyboard.type('4');
  await page.keyboard.press('Enter');
  check(await page.evaluate(() => window.keyboardWorkspace.state.editorConfig.units[0].max_rounds === 4), '键盘提交未写回单元草稿');
  check(await parentRounds.evaluate(element => element === document.activeElement), '应用草稿修改后检视器焦点丢失');

  const parentEvents = rootInspector.getByRole('region', { name: '边界事件与作用域', exact: true });
  check(await parentEvents.count() === 1, 'Unit 边界事件仍只能通过原始 JSON 编辑');
  const parentWaits = rootInspector.getByRole('region', { name: '等待与超时去处', exact: true });
  check(await parentWaits.count() === 1, 'Unit waits 仍只能通过原始 JSON 编辑');
  check(await parentEvents.getByLabel('去处').inputValue() === 'review.from_start', '事件目标未限定为当前 Unit 内容图目标');
  check(await parentWaits.getByLabel('超时后去处').inputValue() === 'review.from_start', '等待目标未限定为当前 Unit 内容图目标');
  const forbiddenTarget = await parentEvents.getByLabel('去处').locator('option').evaluateAll(options => options.some(option => option.value === 'end'));
  check(!forbiddenTarget, '根图 end 被错误暴露为 Unit 边界事件目标');
  await parentEvents.getByLabel('作用域').selectOption('self');
  await parentEvents.getByLabel('作用域').selectOption('subtree');
  await parentWaits.getByLabel('超时毫秒').fill('5000');
  await rootInspector.getByRole('button', { name: '应用单元修改', exact: true }).click();
  const serializedAuxiliary = await page.evaluate(() => window.keyboardWorkspace.state.editorConfig.units[0]);
  check(serializedAuxiliary.on_event[0].scope === 'subtree' && serializedAuxiliary.on_event[0].reason === '保留此字段', '事件编辑未保留未知元数据');
  check(serializedAuxiliary.waits[0].timeoutMs === 5000 && serializedAuxiliary.waits[0].note === '保留此字段', '等待编辑未保留未知元数据');

  await graphProjection.focus();
  await page.keyboard.press('Enter');
  check(await page.locator('.react-flow__node').filter({ hasText: 'U-培训流程' }).locator('.orch-condition-summary').getByText(/无条件/).count() === 1,
    '节点未显示可扫描的路由条件摘要');
  await page.getByRole('button', { name: '适应画布', exact: true }).click();
  await page.locator('.orch-canvas').scrollIntoViewIfNeeded();
  const initialConfig = await page.evaluate(() => JSON.stringify(window.keyboardWorkspace.state.editorConfig));
  const draggedNode = page.locator('.react-flow__node').filter({ hasText: 'U-转人工' });
  const draggedId = await draggedNode.getAttribute('data-id');
  const flowPosition = () => page.locator(`.react-flow__node[data-id="${draggedId}"]`).evaluate(element => element.style.transform);
  const initialPosition = await flowPosition();
  const dragBox = await draggedNode.boundingBox();
  await page.mouse.move(dragBox.x + dragBox.width / 2, dragBox.y + 30);
  await page.mouse.down();
  await page.mouse.move(dragBox.x + dragBox.width / 2 + 180, dragBox.y + 30 + 110, { steps: 8 });
  await page.mouse.up();
  await page.waitForTimeout(100);
  const draggedPosition = await draggedNode.boundingBox();
  check(Math.abs(draggedPosition.x - dragBox.x) > 40 || Math.abs(draggedPosition.y - dragBox.y) > 40, '画布节点不能在会话内临时拖动');
  const movedPosition = await flowPosition();
  check(movedPosition !== initialPosition, `React Flow 节点坐标未随拖动变化：${initialPosition} -> ${movedPosition}; before=${JSON.stringify(dragBox)} after=${JSON.stringify(draggedPosition)}`);
  check(await page.evaluate(() => JSON.stringify(window.keyboardWorkspace.state.editorConfig)) === initialConfig, '拖动节点改变了配置草稿');

  const reflow = page.getByRole('button', { name: '自动布局', exact: true });
  await reflow.click();
  await page.waitForTimeout(100);
  check(await flowPosition() === initialPosition, '自动布局未恢复当前层的拓扑布局');
  await page.getByRole('button', { name: '专注画布', exact: true }).click();
  check(await page.locator('.orch-layout.is-focused').count() === 1, '专注画布模式没有进入聚焦状态');
  check(await rootInspector.isHidden(), '专注画布未隐藏编辑检视器');
  await page.getByRole('button', { name: '退出专注', exact: true }).click();
  check(await rootInspector.isVisible(), '退出专注后未恢复检视器');
  check(await page.evaluate(() => JSON.stringify(window.keyboardWorkspace.state.editorConfig)) === initialConfig, '重排或专注模式改变了配置草稿');
  await graphProjection.focus();
  await page.keyboard.press('Enter');
  check((await node.innerText()).includes('进入上限 4 次'), '图节点摘要未随草稿更新');
  await listProjection.focus();
  await page.keyboard.press('Enter');
  check(await page.getByRole('button', { name: '单元清单', exact: true }).isVisible(), '等价单元清单路径不再可用');

  await graphProjection.focus();
  await page.keyboard.press('Enter');
  const parentNode = page.locator('.react-flow__node').filter({ hasText: 'U-培训流程' });
  await parentNode.focus();
  await page.keyboard.press('Enter');
  await parentCrumb.waitFor({ timeout: 3000 });
  check(await parentCrumb.getAttribute('aria-current') === 'page', '二次 Enter 未下钻到嵌套层');

  const childNode = page.locator('.react-flow__node').filter({ hasText: 'U-接待' });
  await childNode.waitFor();
  let childFocused = false;
  for (let step = 0; step < 32; step++) {
    await page.keyboard.press('Tab');
    if (await childNode.evaluate(element => element.contains(document.activeElement))) {
      childFocused = true;
      break;
    }
  }
  check(childFocused, '键盘 Tab 无法聚焦嵌套单元');
  await page.keyboard.press('Enter');
  const childInspector = page.getByRole('complementary', { name: '单元检视器' });
  await childInspector.getByRole('heading', { name: 'U-接待', exact: true }).waitFor();

  await listProjection.focus();
  await page.keyboard.press('Enter');
  const childListButton = page.locator('.orch-list button').filter({ hasText: 'U-接待' });
  check(await childListButton.getAttribute('aria-pressed') === 'true', '清单投影未保留画布的嵌套单元选中态');
  check(await childInspector.getByRole('heading', { name: 'U-接待', exact: true }).count() === 1, '切换到清单后共享检视器未保留嵌套单元');

  const childRounds = childInspector.getByLabel('进入上限', { exact: true });
  await childRounds.focus();
  await page.keyboard.press(await page.evaluate(() => navigator.platform.includes('Mac') ? 'Meta+A' : 'Control+A'));
  await page.keyboard.type('3');
  await page.keyboard.press('Enter');
  check(await page.evaluate(() => window.keyboardWorkspace.state.editorConfig.units[1].max_rounds === 3), '清单路径中的键盘编辑未写回嵌套单元');
  check(await childRounds.evaluate(element => element === document.activeElement), '应用嵌套草稿修改后检视器焦点丢失');

  await listProjection.focus();
  await page.keyboard.press('Escape');
  const currentCrumb = await page.locator('nav[aria-label="编排层级"] button[aria-current="page"]').innerText();
  const layerPath = await page.evaluate(() => window.keyboardWorkspace.state.orchestration.layerPath);
  check(currentCrumb === '版本路由', `Escape 未返回根层：layerPath=${JSON.stringify(layerPath)}，current=${currentCrumb}`);
  check(await rootCrumb.evaluate(element => element === document.activeElement), 'Escape 返回后焦点未恢复到当前层面包屑');
  const selectedAfterEscape = await page.evaluate(() => window.keyboardWorkspace.state.orchestration.selected);
  check(await parentListButton.getAttribute('aria-pressed') === 'true', `Escape 返回后未选中原嵌套单元：selected=${JSON.stringify(selectedAfterEscape)}`);
  await parentListButton.focus();
  await page.keyboard.press('Enter');
  check(await parentListButton.getAttribute('aria-pressed') === 'true', '根层单元清单无法选择父图');
  await rootInspector.getByRole('heading', { name: 'U-培训流程', exact: true }).waitFor();

  const checkViewport = async width => {
    await page.setViewportSize({ width, height: 960 });
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${width}px 编排工作面发生页面横向溢出`);
    check(!errors.length, `${width}px 视口存在页面错误：${errors.join('；')}`);
  };
  await checkViewport(1440);
  await checkViewport(390);
  await checkViewport(1440);

  await graphProjection.focus();
  await page.keyboard.press('Enter');
  const selectedParentNode = page.locator('.react-flow__node').filter({ hasText: 'U-培训流程' });
  check(await selectedParentNode.getAttribute('aria-selected') === 'true' || await selectedParentNode.evaluate(element => element.classList.contains('selected')), '返回父层后图投影未保留清单选择的父单元');

  await checkViewport(390);
  await checkViewport(1440);

  const edge = page.locator('.react-flow__edge').first();
  await edge.focus();
  await page.keyboard.press('Enter');
  const edgeInspector = page.getByRole('complementary', { name: '边检视器' });
  await edgeInspector.waitFor({ timeout: 3000 });
  check(await edgeInspector.getByRole('heading', { name: '边 · finish', exact: true }).count() === 1, '键盘激活连线未打开对应检视器');
  check(await page.evaluate(() => window.keyboardWorkspace.state.editorConfig.orchestration.edges[0].id === 'finish'), '键盘选边不应修改图合同');
  check(!errors.length, `浏览器错误：${errors.join('；')}`);
  return { passed: true, tabFocus: true, keyboardNodeSelection: true, escapeReturnsAndRestoresFocus: true,
    graphListSelectionSync: true, nestedInspectorEdit: true, unitEventWaitForms: true,
    sessionLayout: true, keyboardEdgeSelection: true,
    inspectorEdit: true, listProjectionAvailable: true, viewports: [1440, 390], errors };
}
