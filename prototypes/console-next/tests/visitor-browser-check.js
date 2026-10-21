async (page) => {
  const root = 'http://127.0.0.1:8788/console-next/?v=knowledge-ux-20261014';
  const results = [], errors = [];
  const verify = (value, message) => { if (!value) throw new Error(message); };
  const step = async (name, work) => { try { await work(); results.push(name); } catch (error) { throw new Error(name + ': ' + error.message); } };
  const state = () => page.evaluate(() => window.__loomriseDemo.store.state);
  const go = async route => {
    await page.goto(`${root}#/${route}?agent=course-demo`);
    if (['knowledge', 'materials'].includes(route)) { const back = page.locator(`[data-action="${route === 'knowledge' ? 'source-list' : 'material-list'}"]`).first(); if (await back.count()) await back.click(); }
  };
  const submit = name => page.locator(`form[data-form="${name}"] button[type="submit"]`).click();
  const reveal = async locator => {
    for (const detail of await locator.locator('xpath=ancestor::details').all()) {
      if (await detail.getAttribute('open') === null) await detail.locator(':scope > summary').click();
    }
  };
  const image = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jf2kAAAAASUVORK5CYII=', 'base64');
  const upload = async (file, title) => {
    const back = page.locator('[data-action="material-list"]').first(); if (await back.count()) await back.click();
    await page.getByRole('button', { name: '录入物料', exact: true }).click();
    await page.locator('[data-material-file]').setInputFiles(file);
    await page.waitForFunction(() => window.__loomriseDemo.store.state.ui.materials.uploadStatus === 'ready');
    const form = page.locator('form[data-form="material-upsert"]');
    for (const [name, value] of Object.entries({ title, description: `${title}的原创虚构验收素材。`, tags: title, sourceRef: `fictional:${file.name}`, expires: '2099-12-31' })) { const control = form.locator(`[name="${name}"]`); await reveal(control); await control.fill(value); }
    await form.locator('[name="rights"]').check(); await form.locator('[name="autoSendAllowed"]').check();
    await submit('material-upsert');
    const id = (await state()).materials.at(-1).id;
    await page.locator(`[data-action="material-review-summary"][data-id="${id}"]`).click();
    await page.locator(`[data-action="material-publish"][data-id="${id}"]`).click();
    return id;
  };
  const ask = async (surface, question) => {
    const form = page.locator(`form[data-form="${surface === 'trial' ? 'trial' : 'widget-trial'}"]`);
    await form.locator(surface === 'trial' ? '[name="question"]' : '[name="widgetQuestion"]').fill(question);
    await form.locator('button[type="submit"]').click();
    await page.waitForFunction(surface => window.__loomriseDemo.store.state.ui[surface === 'trial' ? 'trialState' : 'widgetTrialState'] === 'complete', surface);
  };
  const messages = async surface => (await state()).ui[surface === 'trial' ? 'trialMessages' : 'widgetTrialMessages'];
  const last = async surface => (await messages(surface)).at(-1);
  const holdRead = () => page.evaluate(() => {
    window.__visitorTransaction = IDBDatabase.prototype.transaction;
    IDBDatabase.prototype.transaction = function(names, mode, ...args) {
      const tx = window.__visitorTransaction.call(this, names, mode, ...args);
      if (this.name === 'loomrise-material-files-v1' && mode === 'readonly') {
        IDBDatabase.prototype.transaction = window.__visitorTransaction;
        const descriptor = Object.getOwnPropertyDescriptor(IDBTransaction.prototype, 'oncomplete');
        Object.defineProperty(tx, 'oncomplete', { set(handler) { descriptor.set.call(tx, event => { window.__visitorResume = () => handler.call(tx, event); }); } });
      }
      return tx;
    };
  });
  const startHeld = async surface => {
    const name = surface === 'trial' ? 'trial' : 'widget-trial';
    await holdRead();
    await page.locator(`form[data-form="${name}"] [name="${surface === 'trial' ? 'question' : 'widgetQuestion'}"]`).fill('请发课程海报给我');
    await submit(name); await page.waitForFunction(() => typeof window.__visitorResume === 'function');
  };
  const resumeRead = async () => { await page.evaluate(() => { window.__visitorResume(); delete window.__visitorResume; }); await page.waitForTimeout(50); };
  await page.route('**/console-next/**', route => route.continue());
  page.setDefaultTimeout(7000); page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width: 1440, height: 900 }); await page.goto(root); await page.reload();
  await Promise.all([page.waitForEvent('load'), page.evaluate(() => window.__loomriseDemo.reset())]);
  await go('materials');
  let imageId, videoId, documentId;
  await step('三类真实原件业务录入与策略准备', async () => {
    imageId = await upload({ name: 'poster.png', mimeType: 'image/png', buffer: image }, '课程海报');
    const bytes = await page.evaluate(async () => {
      const canvas = document.createElement('canvas'); canvas.width = canvas.height = 32; canvas.getContext('2d').fillRect(0, 0, 32, 32);
      const stream = canvas.captureStream(10), recorder = new MediaRecorder(stream, { mimeType: 'video/webm' }), parts = [];
      const stop = new Promise(resolve => { recorder.ondataavailable = event => parts.push(event.data); recorder.onstop = resolve; });
      recorder.start(); for (let frame = 0; frame < 6; frame++) { canvas.getContext('2d').fillStyle = frame % 2 ? '#888' : '#333'; canvas.getContext('2d').fillRect(0, 0, 32, 32); await new Promise(resolve => setTimeout(resolve, 60)); } recorder.stop(); await stop; stream.getTracks().forEach(track => track.stop());
      return [...new Uint8Array(await new Blob(parts).arrayBuffer())];
    });
    videoId = await upload({ name: 'intro.webm', mimeType: 'video/webm', buffer: Buffer.from(bytes) }, '介绍视频');
    documentId = await upload({ name: 'service.txt', mimeType: 'text/plain', buffer: Buffer.from('原创虚构服务手册：只用于前端访客验收。') }, '服务手册');
    await go('trial'); await ask('trial', '请发课程海报给我');
    verify((await last('trial')).status === 'material_blocked' && !(await last('trial')).attachments.length, '默认关闭策略未阻断');
    await go('materials'); await reveal(page.locator('[data-bind="materialPolicy.enabled"]')); await page.locator('[data-bind="materialPolicy.enabled"]').check();
  });
  const inboxBefore = JSON.stringify((await state()).agents[0].conversations);
  await step('试用台自然索取图片，实际收件并查看冻结原件', async () => {
    await go('trial'); await ask('trial', '请发课程海报给我');
    await page.waitForFunction(() => window.__loomriseDemo.store.state.ui.trialMessages.at(-1).localReceipt.status === 'received');
    const message = await last('trial');
    verify(message.attachments[0].id === imageId && message.sources.length === 0 && message.delivery === 'unknown', '图片附件或证据语义错误');
    await page.waitForFunction(() => [...document.querySelectorAll('.visitor-attachment img')].some(image => image.naturalWidth === 1));
    await page.locator(`[data-action="visitor-attachment-preview"][data-message-id="${message.id}"]`).click();
    await page.waitForFunction(() => document.querySelector('.material-preview-image')?.naturalWidth === 1);
    verify(Object.values((await last('trial')).attachmentInteractions).some(value => value.openedAt), '打开动作未留证');
    await page.keyboard.press('Escape');
  });
  await step('试用台接收视频并实际加载播放器，文档查看正文并下载原字节', async () => {
    await ask('trial', '想看看介绍视频');
    verify((await last('trial')).attachments[0].id === videoId, '视频定位错误');
    await page.waitForFunction(() => document.querySelector('.visitor-attachment video')?.readyState >= 1);
    const videoMessage = await last('trial');
    await page.locator(`[data-action="visitor-attachment-preview"][data-message-id="${videoMessage.id}"]`).click();
    await page.waitForFunction(() => document.querySelector('.material-preview-video')?.readyState >= 1);
    await page.locator('.material-preview-video').evaluate(video => video.play());
    await page.keyboard.press('Escape');
    await ask('trial', '把服务手册给我');
    const message = await last('trial'); verify(message.attachments[0].id === documentId, '文档定位错误');
    await page.locator(`[data-action="visitor-attachment-preview"][data-message-id="${message.id}"]`).click();
    await page.waitForFunction(() => document.querySelector('.material-preview-text')?.textContent.includes('原创虚构服务手册'));
    await page.keyboard.press('Escape');
    const downloaded = page.waitForEvent('download');
    await page.locator(`[data-action="visitor-attachment-download"][data-message-id="${message.id}"]`).click();
    verify((await downloaded).suggestedFilename() === 'service.txt', '文档下载错误');
    await page.waitForFunction(() => Object.values(window.__loomriseDemo.store.state.ui.trialMessages.at(-1).attachmentInteractions).some(value => value.downloadStartedAt));
    verify((await state()).runs[0].resultEvidence.localReceived === true && (await state()).runs[0].resultEvidence.resolved === 'unknown', '本地收件误当业务完成');
  });
  await step('PDF原件通过格式预检并由浏览器实际渲染页面', async () => {
    const content = 'BT /F1 12 Tf 20 100 Td (Fictional service guide) Tj ET';
    const objects = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>', '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>', `<< /Length ${content.length} >>\nstream\n${content}\nendstream`, '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'];
    let pdf = '%PDF-1.4\n'; const offsets = [];
    for (let i = 0; i < objects.length; i++) { offsets.push(Buffer.byteLength(pdf)); pdf += `${i + 1} 0 obj\n${objects[i]}\nendobj\n`; }
    const xref = Buffer.byteLength(pdf);
    pdf += `xref\n0 6\n0000000000 65535 f \n${offsets.map(offset => String(offset).padStart(10, '0') + ' 00000 n ').join('\n')}\ntrailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF`;
    await go('materials'); await upload({ name: 'guide.pdf', mimeType: 'application/pdf', buffer: Buffer.from(pdf) }, '阅读说明');
    await go('trial'); await ask('trial', '请发阅读说明给我');
    const message = await last('trial');
    await page.locator(`[data-action="visitor-attachment-preview"][data-message-id="${message.id}"]`).click();
    await page.waitForFunction(() => document.querySelector('.material-preview-pdf')?.src.startsWith('blob:'));
    await page.waitForTimeout(250);
    verify(!page.frames().some(frame => frame.url().startsWith('chrome-error:')), 'PDF原生查看器被阻断');
    verify(page.frames().some(frame => frame.url().startsWith('chrome-extension:')), '未载入浏览器PDF查看器');
    await page.screenshot({ path: '.playwright-mcp/round2/visitor-pdf-desktop.png', animations: 'disabled' });
    await page.keyboard.press('Escape');
  });
  await step('快捷索取、否定请求、FAQ和人工出口保持各自语义', async () => {
    await page.locator('[data-action="trial-example"][data-question]').filter({ hasText: '课程海报' }).click();
    verify(await page.locator('form[data-form="trial"] [name="question"]').inputValue() === '请发课程海报给我', '快捷索取未填入真实title');
    await ask('trial', '不要给我发图片'); verify(!(await last('trial')).attachments.length, '否定索取发文件');
    await page.locator('[data-action="trial-example"][data-kind="known"]').click(); await submit('trial');
    await page.waitForFunction(() => window.__loomriseDemo.store.state.ui.trialState === 'complete');
    verify((await last('trial')).status === 'answered' && !(await last('trial')).attachments.length, 'FAQ被物料分支替换');
    await ask('trial', '转人工'); await ask('trial', '请发课程海报给我');
    verify((await last('trial')).status === 'handoff' && !(await last('trial')).attachments.length, '等待人工仍自动发');
    await page.locator('[data-action="trial-clear"]').click();
  });
  await step('Widget独立访客会话完整接收三类文件，试用台和Inbox不串线', async () => {
    await go('widget');
    for (const [question, id] of [['请发课程海报给我', imageId], ['想看看介绍视频', videoId], ['把服务手册给我', documentId]]) {
      await ask('widget', question); const message = await last('widget'); verify(message.attachments[0].id === id, 'Widget附件类型错误');
      await page.locator(`[data-action="visitor-attachment-preview"][data-message-id="${message.id}"]`).click();
      if (id === imageId) await page.waitForFunction(() => document.querySelector('.material-preview-image')?.naturalWidth === 1);
      else if (id === videoId) await page.waitForFunction(() => document.querySelector('.material-preview-video')?.readyState >= 1);
      else await page.waitForFunction(() => document.querySelector('.material-preview-text')?.textContent.includes('原创虚构服务手册'));
      await page.keyboard.press('Escape');
      if (id === documentId) { const download = page.waitForEvent('download'); await page.locator(`[data-action="visitor-attachment-download"][data-message-id="${message.id}"]`).click(); verify((await download).suggestedFilename() === 'service.txt', 'Widget文档下载错误'); }
    }
    verify((await messages('trial')).length === 0, 'Widget消息串入试用台');
    verify(JSON.stringify((await state()).agents[0].conversations) === inboxBefore, '访客预览占用或改写Inbox');
    await page.screenshot({ path: '.playwright-mcp/round2/visitor-widget-desktop.png', fullPage: true, animations: 'disabled' });
  });
  await step('异步文件读取期间取消、离开和改稿不会追加迟到附件', async () => {
    await go('trial'); await startHeld('trial'); await page.locator('[data-action="trial-cancel"]').click(); await resumeRead();
    verify(!(await messages('trial')).some(item => item.attachments?.length), '取消后收到迟到文件');
    await page.locator('[data-action="trial-clear"]').click(); await startHeld('trial');
    await page.locator('.sidebar [data-page="widget"]').click(); await resumeRead();
    verify((await state()).ui.trialState === 'cancelled', '离开后旧试用继续');
    await startHeld('widget'); await page.locator('[data-bind="widget.title"]').fill('本轮修改的标题'); await resumeRead();
    verify((await state()).ui.widgetTrialState === 'cancelled', '改稿后旧Widget继续');
  });
  await step('只有物料时仍可试用，读取期间撤回拒发且历史附件可查看', async () => {
    await go('knowledge');
    for (const source of (await state()).agents[0].config.sources) {
      const back = page.locator('[data-action="source-list"]'); if (await back.count()) await back.click();
      await page.locator(`[data-action="source-detail"][data-id="${source.id}"]`).first().click();
      const revoke = page.locator(`[data-action="source-revoke"][data-id="${source.id}"]`); await reveal(revoke); await revoke.click();
    }
    await go('trial'); await page.locator('[data-action="trial-clear"]').click(); await ask('trial', '请发课程海报给我');
    verify((await last('trial')).attachments[0].id === imageId, '只物料试用被FAQ前置阻断');
    verify((await state()).agents[0].checks.testedRevision === null, '物料试用授予知识批准证据');
    await startHeld('trial');
    await page.evaluate(id => window.__loomriseDemo.store.dispatch('material-revoke', { id }), imageId); await resumeRead();
    await page.waitForFunction(() => window.__loomriseDemo.store.state.ui.trialState === 'complete');
    verify(!(await last('trial')).attachments.length, '撤回后旧检索仍发送');
    const prior = (await messages('trial')).find(item => item.attachments?.some(item => item.id === imageId));
    await page.locator(`[data-action="visitor-attachment-preview"][data-message-id="${prior.id}"]`).click();
    await page.waitForFunction(() => document.querySelector('.material-preview-image')?.naturalWidth === 1); await page.keyboard.press('Escape');
  });
  await step('缓存缺失不给收件附件，历史Run保留独立检索证据', async () => {
    await page.evaluate(async id => { const cache = await import('./asset-cache.js'); await cache.deleteAssetBlob(window.__loomriseDemo.store.state.materials.find(item => item.id === id).original.blobKey); }, videoId);
    await ask('trial', '想看看介绍视频'); verify(!(await last('trial')).attachments.length, '缺失文件仍给收件附件');
    await go('runs');
    const runs = (await state()).runs;
    const successful = runs.find(run => run.attachments?.some(item => item.id === documentId));
    await page.locator(`[data-action="collection-open"][data-page="runs"][data-id="${successful.id}"]`).click();
    const detail = page.locator(`article[data-run-id="${successful.id}"]`);
    await detail.locator('[data-action="visitor-attachment-preview"]').first().click();
    await page.getByRole('dialog').waitFor(); await page.keyboard.press('Escape');
    verify(runs.some(run => run.materialEvidence?.trace?.some(stage => stage.status === 'blocked')), '拒发Run丢检索依据');
  });
  await step('390px Widget、访客附件和试用输入可操作，无页面横向溢出', async () => {
    await page.setViewportSize({ width: 390, height: 844 }); await go('widget');
    await page.locator('[data-action="widget-trial-clear"]').click(); await ask('widget', '把服务手册给我');
    verify(await page.locator('form[data-form="widget-trial"]').isVisible(), '小屏Widget对话不可见');
    verify(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Widget小屏溢出');
    await page.screenshot({ path: '.playwright-mcp/round2/visitor-widget-mobile.png', fullPage: true, animations: 'disabled' });
    await go('trial'); verify(await page.locator('form[data-form="trial"]').isVisible(), '小屏试用输入不可见');
    verify(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), '试用台小屏溢出');
    await page.screenshot({ path: '.playwright-mcp/round2/visitor-trial-mobile.png', fullPage: true, animations: 'disabled' });
  });
  verify(errors.length === 0, `页面错误：${errors.join('; ')}`);
  return { count: results.length, results, errors, note: '真实本地原件与访客DOM收件/打开/下载；检索与Agent仍为脚本，外部送达与业务完成未验证。' };
}
