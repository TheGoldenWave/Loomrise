async page => {
  const check = (value, message) => { if (!value) throw new Error(message); };
  const diagnostics = { pageErrors: [], consoleErrors: [], failedResponses: [] };
  const generationRequests = [];
  const pendingResponses = [];
  page.on('pageerror', error => diagnostics.pageErrors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') diagnostics.consoleErrors.push({ text: message.text(), location: message.location() }); });
  page.on('request', request => {
    if (!request.url().endsWith('/api/customer-service') || request.method() !== 'POST') return;
    const body = request.postDataJSON();
    if (body.action === 'contact.generate') generationRequests.push(body.payload);
  });
  page.on('response', response => {
    if (!response.url().endsWith('/api/customer-service') || response.status() < 400) return;
    pendingResponses.push((async () => diagnostics.failedResponses.push({
      status: response.status(), code: (await response.json()).error?.code,
    }))());
  });
  const api = (action, payload = {}, customer = false) => page.evaluate(async ({ action, payload, customer }) => {
    const { createConfigurationClient } = await import('/r1-configuration.js');
    const client = createConfigurationClient();
    return customer ? client.customerRequest(action, payload) : client.request(action, payload);
  }, { action, payload: { agent_id: 'course-demo', ...payload }, customer });
  const draft = () => api('draft.get');
  const title = () => page.getByLabel('页面标题', { exact: true });
  const brief = () => page.getByLabel('页面素材与要求', { exact: true });
  const save = () => page.getByRole('button', { name: '保存修改', exact: true });
  const generate = () => page.getByRole('button', { name: '生成待审候选', exact: true });
  const candidate = () => page.locator('[data-contact-proposal]');
  const openDrafting = async () => {
    const detail = page.locator('details.contact-generation');
    if (!(await detail.evaluate(element => element.open))) await detail.locator('summary').click();
  };
  const waitSaved = () => page.locator('#workspace-content').getByText('已保存到服务端', { exact: false }).waitFor();
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto('http://127.0.0.1:18765/#/contact?agent=course-demo');
  await title().waitFor();
  await api('contact.enable', { entry_id: 'contact-entry', expected_version_id: 'contact-fixture-v1' }, true);
  const published = await api('contact.get', { entry_id: 'contact-entry' }, true);
  await title().fill('手动已保存页面');
  await save().click(); await waitSaved();
  const before = await draft();
  await title().fill('手动未保存内容');
  await openDrafting();
  await brief().focus();
  await brief().pressSequentially('fixture ');
  await brief().evaluate(element => {
    element.dispatchEvent(new CompositionEvent('compositionstart', { bubbles: true, data: '' }));
    element.value += '虚构课程素材';
    element.dispatchEvent(new InputEvent('input', { bubbles: true, isComposing: true, data: '虚构课程素材' }));
    element.dispatchEvent(new CompositionEvent('compositionend', { bubbles: true, data: '虚构课程素材' }));
  });
  check(await brief().inputValue() === 'fixture 虚构课程素材', '中文 composition 结束后素材丢失');
  check(await brief().evaluate(element => document.activeElement === element), '素材输入重绘后焦点丢失');
  await page.getByLabel('起草参考模板', { exact: true }).selectOption('support');
  await generate().click();
  check(await page.getByRole('button', { name: '正在起草…', exact: true }).isDisabled(), '生成中可重复请求');
  check(await title().isDisabled() && await save().isDisabled(), '生成中仍可修改或保存');
  await candidate().waitFor();
  check(await title().inputValue() === '手动未保存内容', '生成候选覆盖了当前编辑内容');
  check(JSON.stringify(await draft()) === JSON.stringify(before), '生成候选改变了服务端草稿或 revision');
  check(JSON.stringify(await api('contact.get', { entry_id: 'contact-entry' }, true)) === JSON.stringify(published), '生成候选改变了已启用页');
  check((await candidate().textContent()).includes('<script>window.__contactInjected = true</script>'), '候选没有保留转义原文');
  check(await candidate().locator('script, iframe, img').count() === 0, '候选解释了可执行标记');
  check(await page.evaluate(() => window.__contactInjected) === undefined, '候选脚本被执行');
  check(!(await candidate().textContent()).includes('deterministic-browser-fixture'), '页面暴露了原始 Provider 证据');
  check((await candidate().locator('dl dt').allTextContents()).slice(0, 2).join(',') === '问题,回答', '候选 FAQ 没有先显示问题再显示回答');
  const candidateGap = await candidate().evaluate(element => element.querySelector('.contact-block h4').getBoundingClientRect().top
    - element.querySelector('p.helper').getBoundingClientRect().bottom);
  check(candidateGap <= 40, '候选说明与第一个内容块之间存在多余空行');
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 960 });
    await page.evaluate(() => window.scrollTo(0, 0));
    check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${width}px 生成候选横向溢出`);
    await page.screenshot({ path: `output/playwright/r3-contact-generation-${width}.png`, fullPage: true });
  }
  await page.getByRole('button', { name: '采用并替换编辑内容', exact: true }).click();
  check(await title().inputValue() === '虚构课程联系候选', '显式采用没有更新编辑器');
  check(JSON.stringify(await draft()) === JSON.stringify(before), '采用候选自动保存了草稿');
  check(await save().isEnabled(), '采用候选后没有待保存状态');
  await save().click(); await waitSaved();
  const after = await draft();
  check(after.revision === before.revision + 1 && after.config.contact.title === '虚构课程联系候选', '单独保存没有持久化采用内容');
  check(JSON.stringify(await api('contact.get', { entry_id: 'contact-entry' }, true)) === JSON.stringify(published), '保存草稿改变了批准页');
  await page.reload(); await title().waitFor();
  check(await title().inputValue() === '虚构课程联系候选', '采用并保存后刷新丢失内容');
  await openDrafting();
  await title().fill('失败后必须保留的手动内容');
  await brief().fill('FIXTURE-FAIL 虚构素材'); await generate().click();
  await page.locator('.contact-generation [role="alert"]').waitFor();
  check(await title().inputValue() === '失败后必须保留的手动内容' && await save().isEnabled(), '生成失败阻断或覆盖手动内容');
  check(!(await page.locator('#workspace-content').textContent()).includes('PRIVATE-PROVIDER-DETAIL'), '模型错误泄露了 Provider 内部细节');
  check(JSON.stringify(await draft()) === JSON.stringify(after), '生成失败改变了草稿');
  await brief().fill('虚构课程新候选'); await generate().click(); await candidate().waitFor();
  await title().fill('候选之后的新手动输入');
  check(await candidate().count() === 0, '本地编辑没有使旧候选失效');
  await brief().fill('FIXTURE-CONFLICT 虚构素材');
  await generate().click();
  await api('contact.save', { expected_revision: after.revision,
    contact: { ...after.config.contact, title: '其他会话更新' } }, true);
  await page.locator('details').filter({ has: page.getByText('冲突中的本地内容（可复制保留）', { exact: true }) }).waitFor();
  check(await title().inputValue() === '候选之后的新手动输入', '生成期间服务端版本漂移覆盖了本地内容');
  check(await save().isDisabled() && await candidate().count() === 0, '版本冲突后仍可采用或保存');
  check(generationRequests.length === 4, '生成请求数量异常或出现重复请求');
  check(generationRequests.every(payload => ['agent_id,brief,expected_revision', 'agent_id,brief,expected_revision,template_id'].includes(Object.keys(payload).sort().join(','))), '生成请求发送了配置或其他未授权上下文');
  await Promise.all(pendingResponses);
  check(diagnostics.pageErrors.length === 0, JSON.stringify(diagnostics.pageErrors));
  check(diagnostics.failedResponses.length === 2
    && diagnostics.failedResponses.some(item => item.status === 502 && item.code === 'generation_failed')
    && diagnostics.failedResponses.some(item => item.status === 409 && item.code === 'revision_conflict'), '失败响应超出预期');
  check(diagnostics.consoleErrors.length === 2 && diagnostics.consoleErrors.every(error =>
    error.location.url.endsWith('/api/customer-service')
      && /\b(502|409)\b/.test(error.text)), JSON.stringify(diagnostics.consoleErrors));
  return { result: 'pass', generationRequests: generationRequests.length, widths: [1440, 390],
    chineseCompositionAndFocus: true, proposalOnly: true, explicitAdoptionAndSave: true,
    approvedPageUnchanged: true, escapedContent: true, localEditInvalidation: true,
    providerFailurePreservesInput: true, revisionConflictPreservesInput: true, diagnostics };
}
