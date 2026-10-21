async (page) => {
  const root = 'http://127.0.0.1:8788/console-next/?v=knowledge-ux-20261014';
  const results = [], errors = [], layouts = [];
  const verify = (value, message) => { if (!value) throw new Error(message); };
  const step = async (name, work) => { try { await work(); results.push(name); } catch (error) { throw new Error(name + ': ' + error.message); } };
  const state = () => page.evaluate(() => window.__loomriseDemo.store.state);
  const current = () => page.evaluate(() => window.__loomriseDemo.store.currentAgent());
  const go = async route => { await page.goto(`${root}#/${route}?agent=course-demo`); if (route === 'knowledge') await backSources(); else if (route === 'materials') await backMaterials(); };
  const reveal = async locator => {
    for (const detail of await locator.locator('xpath=ancestor::details').all()) {
      if (await detail.getAttribute('open') === null) await detail.locator(':scope > summary').click();
    }
  };
  const click = async locator => { await reveal(locator); await locator.click(); };
  const submit = async name => click(page.locator(`form[data-form="${name}"] button[type="submit"]`));
  const fill = async (form, name, value) => { const control = form.locator(`[name="${name}"]`); await reveal(control); await control.fill(value); };
  const check = async (form, name) => { const control = form.locator(`[name="${name}"]`); await reveal(control); await control.check(); };
  const sourceList = () => page.locator('.knowledge-table');
  const sourceRow = id => page.locator(`.knowledge-table tr[data-source-id="${id}"]`);
  const sourceDetail = id => sourceRow(id).locator('[data-action="source-detail"]').first();
  const materialRow = id => page.locator(`.material-table tr[data-material-row="${id}"]`);
  const backSources = async () => { const back = page.locator('[data-action="source-list"]'); if (await back.count()) await back.click(); };
  const backMaterials = async () => { const back = page.locator('[data-action="material-list"]').first(); if (await back.count()) await back.click(); };
  const assertSourceSurface = async mode => {
    const form = await page.locator('form[data-form="source"]').count();
    const detail = await page.locator('.knowledge-source-detail').count();
    const list = await page.locator('.knowledge-workspace .library-toolbar').count();
    verify(form === Number(mode === 'form') && detail === Number(mode === 'detail') && list === Number(mode === 'list'), `知识 ${mode} 工作面不互斥`);
  };
  const assertMaterialSurface = async mode => {
    verify(await page.locator(`[data-library-surface="material-${mode}"]`).count() === 1, `未进入物料 ${mode} 工作面`);
    verify(await page.locator('form[data-form="material-upsert"]').count() === Number(mode === 'form'), '物料表单和其他工作面同时呈现');
    verify(await page.locator('.material-table').count() === Number(mode === 'list'), '物料列表和其他工作面同时呈现');
  };
  const authorize = async (form, sourceRef) => {
    await fill(form, 'sourceRef', sourceRef); await fill(form, 'expires', '2099-12-31'); await check(form, 'rights');
  };
  const layout = async name => {
    const metric = await page.evaluate(() => ({ width: innerWidth, scrollWidth: document.documentElement.scrollWidth, focus: document.activeElement?.getAttribute('data-action') }));
    verify(metric.scrollWidth <= metric.width, `${name} 横向溢出：${metric.scrollWidth}/${metric.width}`);
    layouts.push({ name, ...metric });
  };
  const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jf2kAAAAASUVORK5CYII=', 'base64');
  const answer = '这是原创虚构的客服标准解答：访客可以先查看资料，再决定是否联系人工。\n保留换行与 <示例标签>，不执行 HTML。';
  const revised = '这是修订后的原创虚构解答。\n' + '管理员可以在列表查看问题与标准解答，核对来源授权后进入试用；这段文字仅作为本地前端验收资料。'.repeat(5) + '\n唯一搜索词：问答优化留存验证。';
  let faqId, urlId, fileId, assetId;
  page.setDefaultTimeout(7000); page.on('pageerror', error => errors.push(error.message));
  await page.route('**/console-next/**', route => route.continue());
  await page.setViewportSize({ width: 1440, height: 960 }); await page.goto(root); await page.reload();
  await Promise.all([page.waitForEvent('load'), page.evaluate(() => window.__loomriseDemo.reset())]);
  await page.waitForFunction(() => window.__loomriseDemo?.store.state.ui.page === 'agents');
  await go('knowledge');

  await step('FAQ 首屏同时显示问题与标准解答，答案参与搜索和状态筛选', async () => {
    await assertSourceSurface('list');
    const faqs = (await current()).config.sources.filter(source => source.type === 'FAQ');
    verify(faqs.length > 0, '缺少虚构 FAQ 初始资料');
    for (const source of faqs) {
      verify((await sourceRow(source.id).locator('.knowledge-question-cell').innerText()).includes(source.question), '列表未显示问题');
      verify((await sourceRow(source.id).locator('.knowledge-answer-cell').innerText()).includes(source.answer), '列表未显示标准解答');
    }
    await page.locator('[data-ui-bind="search"]').fill(faqs[0].answer);
    verify(await sourceList().locator('tbody tr').count() === 1, '标准解答不能定位资料');
    await page.locator('[data-ui-bind="sourceFilter"]').selectOption('ready');
    verify(await sourceRow(faqs[0].id).count() === 1, '有效资料被可试用筛选隐藏');
    await page.locator('[data-ui-bind="sourceFilter"]').selectOption('pending');
    verify(await sourceList().count() === 0, '待处理筛选仍包含就绪资料');
    await page.locator('[data-ui-bind="sourceFilter"]').selectOption('all'); await page.locator('[data-ui-bind="search"]').fill('');
  });
  await step('键盘进入详情、编辑与取消互斥，返回列表保留筛选并回到发起行', async () => {
    const source = (await current()).config.sources.find(source => source.type === 'FAQ');
    await page.locator('[data-ui-bind="search"]').fill(source.title); await page.locator('[data-ui-bind="sourceFilter"]').selectOption('ready');
    await sourceDetail(source.id).focus(); await page.keyboard.press('Enter'); await assertSourceSurface('detail');
    verify(await page.locator('[data-library-heading]').evaluate(element => element === document.activeElement), '详情标题未获得键盘焦点');
    await page.locator('[data-action="source-edit"]').click(); await assertSourceSurface('form');
    await page.locator('form[data-form="source"] [name="answer"]').fill('这次取消的输入不会覆盖标准解答。');
    await page.locator('form[data-form="source"] [data-action="source-form-toggle"]').click(); await assertSourceSurface('detail');
    verify((await current()).config.sources.find(item => item.id === source.id).answer === source.answer, '取消修订仍覆盖资料');
    await backSources(); await assertSourceSurface('list');
    verify(await page.locator('[data-ui-bind="search"]').inputValue() === source.title && await page.locator('[data-ui-bind="sourceFilter"]').inputValue() === 'ready', '返回丢失列表筛选');
    verify(await page.evaluate(id => document.activeElement?.dataset.action === 'source-detail' && document.activeElement?.dataset.id === id, source.id), '返回未聚焦原发起行');
    await page.locator('[data-action="source-tab"][data-tab="URL"]').click();
    verify((await state()).ui.search === '' && (await state()).ui.sourceFilter === 'all' && !(await state()).ui.sourceDetail, '切换资料类型残留旧详情或搜索');
    await page.locator('[data-action="source-tab"][data-tab="FAQ"]').click();
    await page.locator('[data-action="source-tab"][data-tab="FAQ"]').focus();
    for (const [key, tab] of [['ArrowRight', 'URL'], ['End', 'File'], ['Home', 'FAQ']]) {
      await page.keyboard.press(key);
      verify((await state()).ui.sourceTab === tab, `${key} 未切换到 ${tab} 资料类型`);
      verify(await page.evaluate(tab => document.activeElement?.dataset.tab === tab && document.activeElement?.getAttribute('aria-selected') === 'true', tab), `${key} 未聚焦当前选中资料类型`);
    }
  });
  await step('完整手动创建 FAQ，取消新增返回列表，修订版本递增且刷新保存', async () => {
    await page.getByRole('button', { name: '添加资料', exact: true }).click(); await assertSourceSurface('form');
    await page.locator('form[data-form="source"] [name="title"]').fill('取消的新问答');
    await page.locator('form[data-form="source"] [data-action="source-form-toggle"]').click(); await assertSourceSurface('list');
    await page.getByRole('button', { name: '添加资料', exact: true }).click();
    const form = page.locator('form[data-form="source"]');
    await fill(form, 'title', '原创虚构问答验收'); await fill(form, 'question', '能快速查看并修订标准解答吗？'); await fill(form, 'answer', answer);
    await authorize(form, 'fictional:knowledge-workspace-faq'); await submit('source');
    faqId = (await current()).config.sources.at(-1).id; await assertSourceSurface('detail');
    verify((await page.locator('.knowledge-answer .source-text').innerText()) === answer, '解答换行或标签显示错误');
    await backSources(); await page.locator('[data-ui-bind="search"]').fill('原创虚构问答验收'); await page.locator('[data-ui-bind="sourceFilter"]').selectOption('pending');
    await sourceRow(faqId).locator('[data-action="source-edit"]').click(); await assertSourceSurface('form');
    await page.locator('form[data-form="source"] [name="answer"]').fill(revised); await submit('source');
    verify((await current()).config.sources.find(item => item.id === faqId).version === 2, '修订没有生成资料版本');
    await page.reload(); await assertSourceSurface('detail');
    verify((await current()).config.sources.find(item => item.id === faqId).answer === revised, '刷新丢失修订解答');
    await backSources(); await page.locator('[data-ui-bind="search"]').fill('问答优化留存验证');
    verify(await sourceRow(faqId).count() === 1, '解答结尾未参与搜索');
    const disclosure = sourceRow(faqId).locator('details.knowledge-answer-disclosure');
    verify(await disclosure.getAttribute('open') === null, '长解答默认全部展开造成过密列表');
    await disclosure.locator('summary').click(); verify((await disclosure.locator('.knowledge-answer-full').innerText()) === revised, '长解答不能完整阅读');
  });
  await step('只读保留查看与搜索，资料写入入口不可操作', async () => {
    await page.locator('[data-action="readonly-toggle"]').first().click();
    verify(await page.getByRole('button', { name: '添加资料', exact: true }).isDisabled(), '只读仍可添加资料');
    verify(await sourceRow(faqId).locator('[data-action="source-edit"]').isDisabled(), '只读仍可修订问答');
    await sourceDetail(faqId).click(); await assertSourceSurface('detail');
    verify(await page.locator('[data-action="source-edit"]').isDisabled(), '只读详情可编辑');
    verify(await page.locator('[data-action="source-revoke"]').isDisabled(), '只读仍可撤回资料');
    await backSources(); await page.locator('[data-action="readonly-toggle"]').first().click();
  });
  await step('网页只登记 URL，文本文件实际读取并以内容详情呈现', async () => {
    await page.locator('[data-action="source-tab"][data-tab="URL"]').click(); await page.getByRole('button', { name: '添加资料', exact: true }).click();
    let form = page.locator('form[data-form="source"]');
    await fill(form, 'title', '虚构授权页面'); await fill(form, 'url', 'https://example.invalid/fictional-guide'); await authorize(form, 'fictional:authorized-url'); await submit('source');
    urlId = (await current()).config.sources.at(-1).id;
    const url = (await current()).config.sources.find(item => item.id === urlId);
    verify(url.metadataOnly === true && !url.body && url.status !== 'indexed', '仅登记 URL 冒充网页内容解析完成');
    verify((await page.locator('.knowledge-source-detail').innerText()).includes('仅登记'), '网页详情未说明登记边界');
    await backSources(); await page.locator('[data-action="source-tab"][data-tab="File"]').click(); await page.getByRole('button', { name: '添加资料', exact: true }).click();
    const body = '原创虚构 TXT 内容：这里是可供人工核对的服务说明。\n标准文本有换行与 <标签>。';
    await page.locator('[data-source-file]').setInputFiles({ name: 'knowledge-guide.txt', mimeType: 'text/plain', buffer: Buffer.from(body) });
    await page.waitForFunction(() => window.__loomriseDemo.store.state.ui.sourceFileBody.includes('原创虚构 TXT 内容'));
    form = page.locator('form[data-form="source"]'); verify(await form.locator('[name="body"]').inputValue() === body, 'TXT 未读取实际字节');
    await fill(form, 'title', '原创虚构 TXT 说明'); await authorize(form, 'fictional:knowledge-guide-txt'); await submit('source');
    fileId = (await current()).config.sources.at(-1).id;
    verify((await page.locator('.knowledge-body .source-text').innerText()) === body, '文件详情未显示实际文本');
    for (const stage of ['parsed', 'review', 'indexed']) await page.locator(`[data-action="source-stage"][data-stage="${stage}"]`).click();
    verify((await current()).config.sources.find(item => item.id === fileId).status === 'indexed', '人工处理路径不可达');
  });
  await step('物料完整手动录入，范围选择联动，手写简介审阅发布', async () => {
    await go('materials'); await page.getByRole('button', { name: '录入物料', exact: true }).click(); await assertMaterialSurface('form');
    const form = page.locator('form[data-form="material-upsert"]');
    await page.locator('[data-material-file]').setInputFiles({ name: 'workspace-poster.png', mimeType: 'image/png', buffer: png });
    await page.waitForFunction(() => window.__loomriseDemo.store.state.ui.materials.uploadStatus === 'ready');
    await fill(form, 'title', '原创虚构工作区海报'); await fill(form, 'description', '人工填写的原创虚构海报简介，用于本地文件定位，不作为课程事实。'); await authorize(form, 'fictional:workspace-poster');
    const targets = form.locator('[data-material-scope-target]');
    await form.locator('[name="scope"]').selectOption('workspace');
    verify(await targets.isHidden() && await targets.evaluate(element => element.disabled), '工作区范围仍暴露指定专家复选框');
    await form.locator('[name="scope"]').selectOption('selected');
    verify(await targets.isVisible() && !(await targets.evaluate(element => element.disabled)), '指定专家范围无法恢复');
    await form.locator('[name="scope"]').selectOption('workspace');
    verify(!(await form.locator('[name="tags"]').isVisible()), '标签及发送细项默认未收起');
    await fill(form, 'tags', '虚构海报, 工作区'); await check(form, 'autoSendAllowed'); await submit('material-upsert');
    assetId = (await state()).materials.at(-1).id; await assertMaterialSurface('detail');
    verify((await state()).materials.find(item => item.id === assetId).scope === 'workspace', '范围保存错误');
    verify(!(await page.locator('[data-action="material-compress-demo"]').isVisible()), '后处理演示默认占据主工作面');
    await page.locator(`[data-action="material-review-summary"][data-id="${assetId}"]`).click(); await page.locator(`[data-action="material-publish"][data-id="${assetId}"]`).click();
    const asset = (await state()).materials.find(item => item.id === assetId);
    verify(asset.status === 'published' && asset.summary.reviewed && asset.summary.origin !== 'simulation', '人工简介未经审阅发布或依赖 AI 演示');
  });
  await step('物料实际原件预览、详情修订取消、返回列表保留筛选和焦点', async () => {
    const preview = page.locator(`[data-action="material-preview"][data-id="${assetId}"]`).filter({ hasText: '预览原件' });
    await preview.click(); await page.waitForFunction(() => document.querySelector('.material-preview-image')?.naturalWidth === 1);
    verify(await page.locator('.app-shell').evaluate(element => element.inert), '原件弹窗未阻断背景交互');
    for (const key of ['Tab', 'Shift+Tab']) {
      for (let press = 0; press < 5; press++) {
        await page.keyboard.press(key);
        verify(await page.locator('.material-preview-dialog').evaluate(element => element.contains(document.activeElement)), `${key} 焦点逃出原件预览弹窗`);
      }
    }
    await page.keyboard.press('Escape');
    verify(await preview.evaluate(element => element === document.activeElement), '关闭原件预览未返回发起按钮');
    verify(!(await page.locator('.app-shell').evaluate(element => element.inert)), '关闭原件预览后背景仍无法交互');
    await backMaterials(); await assertMaterialSurface('list');
    await page.locator('[data-ui-bind="materials.query"]').fill('原创虚构工作区海报'); await page.locator('[data-ui-bind="materials.kind"]').selectOption('image'); await page.locator('[data-ui-bind="materials.status"]').selectOption('published');
    await materialRow(assetId).locator('[data-action="material-detail"]').first().focus(); await page.keyboard.press('Enter'); await assertMaterialSurface('detail');
    await page.locator(`[data-action="material-edit"][data-id="${assetId}"]`).first().click(); await assertMaterialSurface('form');
    await page.locator('form[data-form="material-upsert"] [name="description"]').fill('这个取消的简介不应保存。');
    await page.locator('form[data-form="material-upsert"] [data-action="material-form-toggle"]').click(); await assertMaterialSurface('detail');
    verify(!(await state()).materials.find(item => item.id === assetId).summary.text.includes('取消的简介'), '取消修订保存了新简介');
    await backMaterials(); await assertMaterialSurface('list');
    verify((await state()).ui.materials.query === '原创虚构工作区海报' && (await state()).ui.materials.kind === 'image' && (await state()).ui.materials.status === 'published', '物料返回丢失筛选');
    verify(await page.evaluate(id => document.activeElement?.dataset.action === 'material-detail' && document.activeElement?.dataset.id === id, assetId), '物料返回未聚焦发起行');
  });
  await step('自动发送策略默认收起，版本与检索可下探，处理演示和管理分区可操作', async () => {
    const policy = page.locator('details.material-policy');
    verify(await policy.getAttribute('open') === null && !(await page.locator('[data-bind="materialPolicy.enabled"]').isVisible()), '自动发送策略默认未收起');
    await policy.locator(':scope > summary').click();
    await page.locator('[data-bind="materialPolicy.enabled"]').check();
    const preferred = page.locator('[data-bind="materialPolicy.preferredVariant"]'); verify(!(await preferred.isVisible()), '发送版本细项默认未收起');
    await reveal(preferred); await preferred.selectOption('original');
    await page.locator('[data-ui-bind="materials.autoQuery"]').fill('原创虚构工作区海报'); await page.locator('[data-action="material-auto-retrieve"]').click();
    verify((await state()).ui.materials.autoResults.some(item => item.id === assetId), '已审发布物料不能检索');
    verify(await policy.locator('[data-action="navigate"][data-page="trial"]').isVisible() && await policy.locator('[data-action="navigate"][data-page="widget"]').isVisible(), '试用及 Widget 入口不可达');
    await materialRow(assetId).locator('[data-action="material-detail"]').first().click();
    verify(await page.locator('.material-policy').count() === 0, '专家策略与单条详情同时堆叠');
    const compress = page.locator('[data-action="material-compress-demo"]'); await click(compress);
    verify((await state()).materials.find(item => item.id === assetId).variants.some(item => item.id === 'compressed-demo' && !item.blobKey), '模拟处理制造真实派生文件声明');
    const revoke = page.locator('[data-action="material-revoke"]'); verify(!(await revoke.isVisible()), '撤回操作默认暴露在主工作面'); await reveal(revoke); verify(await revoke.isEnabled(), '管理折叠区不可操作');
    await backMaterials();
    await page.locator('[data-action="readonly-toggle"]').first().click(); await reveal(page.locator('[data-bind="materialPolicy.enabled"]'));
    verify(await page.locator('[data-bind="materialPolicy.enabled"]').isDisabled() && await page.getByRole('button', { name: '录入物料', exact: true }).isDisabled(), '只读物料写入仍可用');
    await page.locator('[data-action="readonly-toggle"]').first().click();
  });
  await step('390、951、1440px 的列表、详情与编辑均无横向溢出', async () => {
    for (const width of [390, 951, 1440]) {
      await page.setViewportSize({ width, height: 927 }); await go('knowledge'); await page.locator('[data-action="source-tab"][data-tab="FAQ"]').click();
      await page.locator('[data-ui-bind="search"]').fill('问答优化留存验证'); await layout(`知识列表 ${width}`);
      await page.screenshot({ path: `.playwright-mcp/round2/knowledge-workspace-${width}.png`, fullPage: true, animations: 'disabled' });
      await sourceDetail(faqId).click(); await layout(`知识详情 ${width}`); await page.locator('[data-action="source-edit"]').click(); await layout(`知识编辑 ${width}`);
      await page.locator('form[data-form="source"] [data-action="source-form-toggle"]').click(); await backSources();
      for (const [type, id] of [['URL', urlId], ['File', fileId]]) { await page.locator(`[data-action="source-tab"][data-tab="${type}"]`).click(); await layout(`${type} 列表 ${width}`); await sourceDetail(id).click(); await layout(`${type} 详情 ${width}`); await backSources(); }
      await go('materials'); await layout(`物料列表 ${width}`); await page.screenshot({ path: `.playwright-mcp/round2/material-workspace-${width}.png`, fullPage: true, animations: 'disabled' });
      await materialRow(assetId).locator('[data-action="material-detail"]').first().click(); await layout(`物料详情 ${width}`); await page.locator(`[data-action="material-edit"][data-id="${assetId}"]`).first().click(); await layout(`物料编辑 ${width}`);
      await page.locator('form[data-form="material-upsert"] [data-action="material-form-toggle"]').click(); await backMaterials();
    }
  });
  verify(errors.length === 0, `页面错误：${errors.join('; ')}`);
  await page.setViewportSize({ width: 1440, height: 960 });
  return { count: results.length, results, layouts, errors, note: '真实人工知识/物料配置与本地缓存验收；后台解析、检索、AI 和外部发送未接入。' };
}
