async (page) => {
  const root = 'http://127.0.0.1:8788/console-next/?v=knowledge-ux-20261014';
  const results = [];
  const errors = [];
  const verify = (condition, message) => { if (!condition) throw new Error(message); };
  const step = async (name, work) => { try { await work(); } catch (error) { throw new Error(name + ': ' + error.message); } results.push(name); };
  const state = () => page.evaluate(() => window.__loomriseDemo.store.state);
  const current = () => page.evaluate(() => window.__loomriseDemo.store.currentAgent());
  const go = async route => { await page.goto(`${root}#/${route}?agent=course-demo`); if (route === 'materials') await library(); };
  const reveal = async form => {
    for (const detail of await form.locator('xpath=ancestor::details').all()) {
      if (await detail.getAttribute('open') === null) await detail.locator(':scope > summary').click();
    }
  };
  const submit = async name => {
    const form = page.locator(`form[data-form="${name}"]`);
    await reveal(form); await form.locator('button[type="submit"]').click();
  };
  const click = async locator => { await reveal(locator); await locator.click(); };
  const library = async () => { const back = page.locator('[data-action="material-list"]').first(); if (await back.count()) await back.click(); };
  const upload = async (file, title, auto = true) => {
    await library();
    await page.getByRole('button', { name: '录入物料', exact: true }).click();
    await page.locator('[data-material-file]').setInputFiles(file);
    await page.waitForFunction(() => window.__loomriseDemo.store.state.ui.materials.uploadStatus === 'ready');
    const form = page.locator('form[data-form="material-upsert"]');
    await form.locator('[name="title"]').fill(title);
    await form.locator('[name="description"]').fill(`${title}的虚构测试说明；只用于定位文件。`);
    await reveal(form.locator('[name="tags"]')); await form.locator('[name="tags"]').fill(title);
    await form.locator('[name="sourceRef"]').fill(`fictional:${file.name}`);
    await form.locator('[name="expires"]').fill('2099-12-31');
    await form.locator('[name="rights"]').check();
    if (auto) await form.locator('[name="autoSendAllowed"]').check();
    await submit('material-upsert');
    const id = (await state()).materials.at(-1).id;
    await page.locator(`[data-action="material-review-summary"][data-id="${id}"]`).click();
    await page.locator(`[data-action="material-publish"][data-id="${id}"]`).click();
    return id;
  };
  const detail = async id => { if ((await state()).ui.materials.detailId !== id) { await library(); await page.locator(`[data-action="material-detail"][data-id="${id}"]`).first().click(); } };
  const pick = async id => {
    await page.locator('[data-action="material-picker-open"]').click();
    await page.locator(`[data-action="material-pick"][data-id="${id}"][data-variant="original"]`).click();
    await page.locator('[data-action="material-picker-done"]').click();
  };
  const holdTransaction = mode => page.evaluate(mode => {
    window.__materialOriginalTransaction = IDBDatabase.prototype.transaction;
    IDBDatabase.prototype.transaction = function (names, requestedMode, ...args) {
      const tx = window.__materialOriginalTransaction.call(this, names, requestedMode, ...args);
      if (this.name === 'loomrise-material-files-v1' && requestedMode === mode) {
        IDBDatabase.prototype.transaction = window.__materialOriginalTransaction;
        const descriptor = Object.getOwnPropertyDescriptor(IDBTransaction.prototype, 'oncomplete');
        Object.defineProperty(tx, 'oncomplete', { configurable: true, set(handler) {
          descriptor.set.call(tx, event => { window.__materialResume = () => handler.call(tx, event); });
        } });
      }
      return tx;
    };
  }, mode);
  page.setDefaultTimeout(6000);
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/console-next/**', route => route.continue());
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(root); await page.reload();
  await Promise.all([page.waitForEvent('load'), page.evaluate(() => window.__loomriseDemo.reset())]);
  await page.waitForFunction(() => window.__loomriseDemo?.store.state.ui.page === 'agents');
  await go('create');
  await page.locator('form[data-form="create"] [name="name"]').fill('第二测试客服');
  await page.locator('form[data-form="create"] [name="goal"]').fill('按原创虚构资料提供咨询。');
  await submit('create');
  const secondAgentId = (await state()).selectedAgentId;
  await go('materials');
  const beforeSources = (await current()).config.sources.length;
  let imageId, videoId, documentId;
  // Original fixture bytes, no third-party or user material.
  const image = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jf2kAAAAASUVORK5CYII=', 'base64');
  await step('图片、视频、文档实际缓存，业务审阅发布且独立于知识资料', async () => {
    imageId = await upload({ name: 'fixture.png', mimeType: 'image/png', buffer: image }, '课程海报');
    const bytes = await page.evaluate(async () => {
      const canvas = document.createElement('canvas'); canvas.width = canvas.height = 32;
      canvas.getContext('2d').fillRect(0, 0, 32, 32);
      const stream = canvas.captureStream(5); const recorder = new MediaRecorder(stream, { mimeType: 'video/webm' });
      const parts = [];
      const stopped = new Promise(resolve => { recorder.ondataavailable = event => parts.push(event.data); recorder.onstop = resolve; });
      recorder.start(); await new Promise(resolve => setTimeout(resolve, 150)); recorder.stop(); await stopped;
      stream.getTracks().forEach(track => track.stop());
      return [...new Uint8Array(await new Blob(parts, { type: 'video/webm' }).arrayBuffer())];
    });
    videoId = await upload({ name: 'fixture.webm', mimeType: 'video/webm', buffer: Buffer.from(bytes) }, '介绍视频');
    documentId = await upload({ name: 'fixture.txt', mimeType: 'text/plain', buffer: Buffer.from('原创虚构服务手册：供本地前端验收使用。') }, '服务手册');
    const s = await state();
    verify(s.materials.length === 3 && s.materials.every(item => item.status === 'published'), '物料未独立登记并发布');
    verify((await current()).config.sources.length === beforeSources, '物料污染知识资料数量');
    verify(!JSON.stringify(s).includes('data:image'), '二进制进入localStorage状态');
  });
  await step('跨刷新图片与视频读取真实原件，文档可下载原字节', async () => {
    await page.reload();
    await detail(imageId);
    await page.locator(`[data-action="material-preview"][data-id="${imageId}"][data-mode="download"]`).waitFor();
    await page.locator(`[data-action="material-preview"][data-id="${imageId}"]`).filter({ hasText: '预览原件' }).click();
    await page.waitForFunction(() => document.querySelector('.material-preview-image')?.naturalWidth === 1);
    await page.locator('[data-action="material-preview-close"]').first().click();
    await detail(videoId);
    await page.locator(`[data-action="material-preview"][data-id="${videoId}"]`).filter({ hasText: '预览原件' }).click();
    await page.waitForFunction(() => document.querySelector('.material-preview-video')?.readyState >= 1);
    await page.locator('[data-action="material-preview-close"]').first().click();
    await detail(documentId);
    const download = page.waitForEvent('download');
    await page.locator(`[data-action="material-preview"][data-id="${documentId}"][data-mode="download"]`).click();
    verify((await download).suggestedFilename() === 'fixture.txt', '文档下载文件名错误');
    const body = await page.evaluate(async id => {
      const cache = await import('./asset-cache.js');
      const item = window.__loomriseDemo.store.state.materials.find(item => item.id === id);
      return (await cache.readAssetBlob(item.original.blobKey)).blob.text();
    }, documentId);
    verify(body === '原创虚构服务手册：供本地前端验收使用。', '实际原件内容未持久化');
  });
  await step('压缩和简介候选明确模拟、未审简介不供Agent、失败不丢原件', async () => {
    await detail(imageId);
    const original = (await state()).materials.find(item => item.id === imageId).original;
    await click(page.locator('[data-action="material-compress-demo"]'));
    await click(page.locator('[data-action="material-compress-fail"]'));
    await click(page.locator('[data-action="material-summary-demo"]'));
    await library(); await click(page.locator('[data-action="material-auto-retrieve"]'));
    verify(!(await state()).ui.materials.autoResults.some(item => item.id === imageId), '未经审阅简介可被自动召回');
    await detail(imageId); await page.locator('[data-action="material-apply-summary"]').click();
    await page.locator('[data-action="material-review-summary"]').click();
    const asset = (await state()).materials.find(item => item.id === imageId);
    verify(JSON.stringify(asset.original) === JSON.stringify(original), '处理失败丢失原件');
    verify(asset.variants.find(item => item.id === 'compressed-demo').blobKey === null, '假造压缩文件');
    verify(asset.summary.text.includes('尚未读取或理解'), '元数据候选冒充内容理解');
  });
  await step('Agent策略默认关闭，明确索取后自动记录附件和冻结策略', async () => {
    verify((await current()).config.materialPolicy.enabled === false, '自动发默认启用');
    await library(); await reveal(page.locator('[data-bind="materialPolicy.enabled"]')); await page.locator('[data-bind="materialPolicy.enabled"]').check();
    await go('inbox');
    const form = page.locator('form[data-form="material-auto-send"]');
    await reveal(form); await form.locator('[name="query"]').fill('课程海报');
    await form.locator('[name="explicitRequest"]').uncheck();
    const count = (await current()).conversations[0].messages.length;
    await submit('material-auto-send');
    verify((await current()).conversations[0].messages.length === count, '无明确请求仍自动发送');
    await form.locator('[name="explicitRequest"]').check();
    await submit('material-auto-send');
    await page.waitForFunction(() => window.__loomriseDemo.store.currentAgent().conversations[0].messages.at(-1).actor === 'agent');
    const last = (await current()).conversations[0].messages.at(-1);
    verify(last.attachments[0].id === imageId && last.delivery === 'unknown', '未记录正确附件和未知送达');
    verify(last.requestEvidence.origin === 'operator-simulated-request', '模拟请求冒充访客事实');
    verify(last.materialPolicy.enabled === true && (await current()).conversations[0].requestStatus === 'waiting', '发送错误改变业务终态');
  });
  await step('人工接管阻断Agent，人工纯附件发送保留发送时快照', async () => {
    await page.locator('[data-action="inbox-handoff"]').click();
    const auto = page.locator('form[data-form="material-auto-send"]'); await reveal(auto);
    verify(await auto.locator('button[type="submit"]').isDisabled(), '人工接管后自动发送未阻断');
    await pick(documentId); await submit('inbox');
    await page.waitForFunction(() => window.__loomriseDemo.store.currentAgent().conversations[0].messages.at(-1).actor === 'human');
    const last = (await current()).conversations[0].messages.at(-1);
    verify(last.text === '' && last.attachments[0].id === documentId, '纯附件回复失败');
    await go('materials');
    await page.locator(`[data-action="material-edit"][data-id="${documentId}"]`).first().click();
    await page.locator('form[data-form="material-upsert"] [name="title"]').fill('服务手册新版');
    await submit('material-upsert');
    await go('inbox');
    verify((await current()).conversations[0].messages.at(-1).attachments[0].title === '服务手册', '历史附件被新名称改写');
  });
  await step('发送异步校验期间占用变化阻断迟到发送，文本和选择仍保留', async () => {
    await pick(imageId);
    await page.locator('form[data-form="inbox"] [name="message"]').fill('保留这段待发说明');
    const count = (await current()).conversations[0].messages.length;
    await holdTransaction('readonly'); await submit('inbox');
    await page.waitForFunction(() => typeof window.__materialResume === 'function');
    await page.locator('[data-action="inbox-release"]').click();
    await page.evaluate(() => { window.__materialResume(); delete window.__materialResume; });
    await page.waitForFunction(() => window.__loomriseDemo.store.state.ui.toast?.text.includes('代次'));
    verify((await current()).conversations[0].messages.length === count + 1, '迟到发送追加了附件消息');
    verify(!(await current()).conversations[0].messages.at(-1).attachments?.length, '迟到附件错发');
    verify((await state()).ui.materials.selected.length === 1, '失败清空附件选择');
    verify(await page.locator('form[data-form="inbox"] [name="message"]').inputValue() === '保留这段待发说明', '失败清空文本');
  });
  await step('选择后撤回或本地文件缺失拒发，既有历史不改写', async () => {
    await page.locator('[data-action="inbox-handoff"]').click();
    await pick(imageId);
    await go('materials'); await detail(imageId);
    await click(page.locator('[data-action="material-revoke"]')); await go('inbox');
    const count = (await current()).conversations[0].messages.length;
    await submit('inbox'); verify((await current()).conversations[0].messages.length === count, '撤回后旧选择仍发送');
    await pick(videoId);
    await page.evaluate(async id => {
      const cache = await import('./asset-cache.js');
      await cache.deleteAssetBlob(window.__loomriseDemo.store.state.materials.find(item => item.id === id).original.blobKey);
    }, videoId);
    await submit('inbox');
    await page.waitForFunction(() => window.__loomriseDemo.store.state.ui.toast?.text.includes('缓存不可用'));
    verify((await current()).conversations[0].messages.length === count, '无实际文件仍记录发送');
    verify((await state()).ui.materials.selected[0].id === videoId, '文件缺失清空选择');
    verify((await current()).conversations[0].messages.some(message => message.attachments?.some(item => item.id === imageId)), '撤回删除历史证据');
  });
  await step('晚到上传不会进入另一个专家的录入表单', async () => {
    await go('materials'); await page.getByRole('button', { name: '录入物料', exact: true }).click();
    await holdTransaction('readwrite');
    await page.locator('[data-material-file]').setInputFiles({ name: 'late.png', mimeType: 'image/png', buffer: image });
    await page.waitForFunction(() => typeof window.__materialResume === 'function');
    verify(await page.locator('form[data-form="material-upsert"] button[type="submit"]').isDisabled(), '缓存未完成仍可提交');
    await page.locator('[data-action="select-agent"]').selectOption(secondAgentId);
    await page.evaluate(() => { window.__materialResume(); delete window.__materialResume; });
    await page.waitForTimeout(50);
    verify((await state()).ui.materials.upload === null, '晚到文件串入新专家');
    verify((await state()).materials.length === 3, '晚到文件自动登记物料');
  });
  await step('390px物料列表、选择器和原件预览可操作且无横向溢出', async () => {
    await page.setViewportSize({ width: 390, height: 844 }); await go('materials');
    await detail(imageId);
    await page.screenshot({ path: '.playwright-mcp/round2/materials-mobile.png', fullPage: true, animations: 'disabled' });
    verify(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), '物料库窄屏溢出');
    await page.locator(`[data-action="material-preview"][data-id="${imageId}"]`).filter({ hasText: '预览原件' }).click();
    await page.waitForFunction(() => document.querySelector('.material-preview-image')?.naturalWidth === 1);
    await page.screenshot({ path: '.playwright-mcp/round2/material-preview-mobile.png', animations: 'disabled' });
    verify(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), '预览窄屏溢出');
    await page.keyboard.press('Escape');
    await go('inbox'); await page.locator('[data-action="material-picker-open"]').click();
    await page.screenshot({ path: '.playwright-mcp/round2/material-picker-mobile.png', fullPage: true, animations: 'disabled' });
    verify(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), '选择器窄屏溢出');
  });
  verify(errors.length === 0, `浏览器错误：${errors.join('; ')}`);
  await page.setViewportSize({ width: 1440, height: 900 }); await go('materials');
  await page.screenshot({ path: '.playwright-mcp/round2/materials-desktop.png', fullPage: true, animations: 'disabled' });
  return { count: results.length, results, errors, note: '实际文件缓存/预览/下载与UI反例；内容理解、压缩、外部发送仍为模拟。' };
}
