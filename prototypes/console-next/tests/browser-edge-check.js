async (page) => {
  const root = 'http://127.0.0.1:8788/console-next/?v=knowledge-ux-20261014';
  const results = [];
  const check = (value, label) => { if (!value) throw new Error(label); results.push(label); };
  const sourceList = async () => { const back = page.locator('[data-action="source-list"]').first(); if (await back.count() && await back.isVisible()) await back.click(); };
  const openCollection = async name => { const opener = page.locator(`[data-action="collection-open"][data-page="${name}"]`).first(); if (await opener.count()) await opener.click(); };
  await page.route('**/console-next/**', route => route.continue());
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.reload();
  const id = await page.evaluate(() => window.__loomriseDemo.store.state.selectedAgentId);
  await page.goto(`${root}#/knowledge?agent=${id}`);
  await sourceList();
  await page.locator('[data-action="source-tab"][data-tab="File"]').click();
  await page.getByRole('button', { name: '添加资料', exact: true }).click();
  await page.evaluate(() => {
    window.__fileTextOriginal = File.prototype.text;
    File.prototype.text = function () {
      if (this.name === 'held.txt') return new Promise(resolve => { window.__resolveHeldFile = resolve; });
      return window.__fileTextOriginal.call(this);
    };
  });
  await page.locator('[data-source-file]').setInputFiles({ name: 'held.txt', mimeType: 'text/plain', buffer: Buffer.from('旧对象授权资料（虚构）') });
  await page.waitForFunction(() => typeof window.__resolveHeldFile === 'function');
  await page.locator('[data-action="select-agent"]').selectOption('course-demo');
  await page.evaluate(async () => { window.__resolveHeldFile('旧对象授权资料（虚构）'); await new Promise(resolve => setTimeout(resolve, 30)); File.prototype.text = window.__fileTextOriginal; });
  check(await page.evaluate(() => window.__loomriseDemo.store.state.ui.sourceFileMeta === null && window.__loomriseDemo.store.state.ui.sourceFileBody === ''), '晚到文件读取未串入另一个专家');

  await page.locator('[data-action="select-agent"]').selectOption(id);
  await page.goto(`${root}#/knowledge?agent=${id}`);
  await sourceList();
  await page.locator('[data-action="source-tab"][data-tab="File"]').click();
  await page.getByRole('button', { name: '添加资料', exact: true }).click();
  const contents = '虚构服务说明：周末上午可以咨询。';
  await page.locator('[data-source-file]').setInputFiles({ name: 'service.txt', mimeType: 'text/plain', buffer: Buffer.from(contents) });
  await page.waitForFunction(() => window.__loomriseDemo.store.state.ui.sourceFileBody.includes('虚构服务说明'));
  const source = page.locator('form[data-form="source"]');
  check(await source.locator('[name="body"]').inputValue() === contents, '本地文件正文实际读取并填入人工审阅表单');
  await source.locator('[name="sourceRef"]').fill('fictional:local-service-text');
  await source.locator('[name="expires"]').fill('2099-12-31');
  await source.locator('[name="rights"]').check();
  await source.locator('button[type="submit"]').click();
  check(await page.evaluate(() => window.__loomriseDemo.store.currentAgent().config.sources.at(-1).filename === 'service.txt'), '文件登记保持本对象与文件来源');

  await page.goto(`${root}#/iterations?agent=${id}`);
  await page.locator('[data-action="proposal-create"]').first().click();
  const proposal = page.locator('form[data-form="proposal"]');
  await proposal.locator('[name="title"]').fill('人工口径校验');
  await proposal.locator('[name="reason"]').fill('只采用有效真值比较结果');
  await proposal.locator('[name="after"]').fill('需要人工进一步核实。');
  await proposal.locator('button[type="submit"]').click();
  await page.locator('[data-action="proposal-evaluate"]').first().click();
  check(await page.evaluate(() => window.__loomriseDemo.store.state.proposals[0].evaluation === 'pass'), '候选按当前人工案例完成模拟比较');
  await page.goto(`${root}#/cases?agent=${id}`);
  await openCollection('cases');
  await page.locator('[data-action="case-edit"]').first().click();
  const truth = page.locator('form[data-form="case"]');
  await truth.locator('[name="expected"]').selectOption('answered');
  await truth.locator('button[type="submit"]').click();
  await page.goto(`${root}#/iterations?agent=${id}`);
  await openCollection('iterations');
  check(await page.locator('[data-action="proposal-apply"]').first().isDisabled(), '修改真值后旧候选不能沿用已通过状态');
  return { count: results.length, results, note: '仅本地前端反例验证；未接真实文件解析、AI或发布。' };
}
