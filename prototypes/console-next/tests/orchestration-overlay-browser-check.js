async page => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const check = (value, message) => { if (!value) throw new Error(message); };
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto('http://127.0.0.1:18765/orchestration/');
  await page.evaluate(async () => {
    await Promise.all(['/styles.css', '/dist/orchestration.css'].map(href => new Promise((resolve, reject) => {
      const link = document.createElement('link'); link.rel = 'stylesheet'; link.href = href;
      link.onload = resolve; link.onerror = reject; document.head.append(link);
    })));
    const { createConfigurationClient, createR1ConfigurationWorkspace } = await import('/r1-configuration.js');
    const { mountOrchestration } = await import('/dist/orchestration.js');
    document.body.replaceChildren();
    const container = document.createElement('main'); container.style.padding = '16px'; document.body.append(container);
    const workspace = createR1ConfigurationWorkspace({ client: createConfigurationClient({ baseUrl: 'http://127.0.0.1:8779' }) });
    await workspace.load('course-demo');
    await workspace.openStable('r3-overlay-fixture-v1');
    // Keep the component fixture on the actual HTTP workspace and remount on service state change.
    const hooked = createR1ConfigurationWorkspace({ client: workspace.client, onChange() {
      unmount?.(); unmount = mountOrchestration(container, hooked);
    } });
    Object.assign(hooked.state, workspace.state);
    window.overlayWorkspace = hooked;
    let unmount = mountOrchestration(container, hooked);
  });
  await page.getByRole('button', { name: '查询实际走向' }).click();
  await page.getByText('2 次运行', { exact: false }).waitFor();
  check((await page.locator('.orch-run-overlay').allTextContents()).some(text => text.startsWith('进入 2')), '真实事件未映射到根节点');
  check(!(await page.locator('.orch-run-overlay').allTextContents()).some(text => text.includes('%')), '小样本比例被展示');
  check(!(await page.locator('.orch-run-overlay').allTextContents()).some(text => /执行|终止/.test(text)), '进入数模式混入执行时长或终止数');
  await page.getByRole('combobox', { name: '显示内容' }).selectOption('detail');
  await page.getByText('节点角标展示解释器执行时长均值与样本数', { exact: false }).waitFor();
  check((await page.locator('.orch-run-overlay').allTextContents()).some(text => /终止 \d+/.test(text) && /执行 .*\(n=\d+\)/.test(text)), '节点的耗时样本数或终止目标未映射');
  await page.getByRole('combobox', { name: '显示内容' }).selectOption('count');
  check(!(await page.locator('.orch-run-overlay').allTextContents()).some(text => /执行|终止/.test(text)), '返回进入数后仍显示详细指标');
  await page.getByRole('button', { name: '单元清单', exact: true }).click();
  await page.getByRole('button', { name: 'disclosure', exact: true }).click();
  await page.getByRole('button', { name: '展开内容层' }).click();
  await page.getByRole('button', { name: '编排图', exact: true }).click();
  await page.locator('.orch-run-overlay').waitFor();
  check((await page.locator('.orch-run-overlay').allTextContents()).some(text => text.startsWith('进入 2')), '子图路径没有精确匹配');
  await page.getByRole('combobox', { name: '渠道' }).selectOption('voice');
  await page.getByRole('button', { name: '查询实际走向' }).click();
  await page.getByText('1 次运行', { exact: false }).waitFor();
  await page.getByRole('combobox', { name: '显示内容' }).selectOption('detail');
  await page.getByText('节点角标展示解释器执行时长均值与样本数', { exact: false }).waitFor();
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 960 });
    check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${width}px 页面溢出`);
    await page.locator('.orch-canvas').scrollIntoViewIfNeeded();
    await page.waitForFunction(() => {
      const bounds = document.querySelector('.orch-canvas').getBoundingClientRect();
      return [...document.querySelectorAll('.react-flow__node')].every(node => {
        const box = node.getBoundingClientRect();
        return box.x >= bounds.x - 1 && box.right <= bounds.right + 1;
      });
    });
    const bounds = await page.locator('.orch-canvas').boundingBox();
    for (const node of await page.locator('.react-flow__node').all()) {
      const box = await node.boundingBox();
      check(box.x >= bounds.x - 1 && box.x + box.width <= bounds.x + bounds.width + 1, '窄屏画布未适应节点宽度');
    }
    await page.locator('.orch-canvas').screenshot({ path: `output/playwright/r3-overlay-canvas-${width}.png` });
  }
  await page.getByRole('combobox', { name: '显示内容' }).selectOption('off');
  check(await page.locator('.orch-run-overlay').count() === 0, '关闭后仍显示统计');
  check(await page.locator('.orch-inspector fieldset:enabled').count() === 0, '查看统计时稳定版本可编辑');
  check(errors.length === 0, errors.join('\n'));
  return { pageErrors: errors.length, source: 'SQLite + actual scripted ExecutionService RunEvents', counts: [2, 1], displayModes: ['count', 'detail', 'off'], viewports: [1440, 390] };
}
