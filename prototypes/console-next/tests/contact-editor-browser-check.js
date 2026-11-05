async page => {
  const diagnostics = { pageErrors: [], consoleErrors: [], apiFailures: [] };
  const pendingApiFailures = [];
  const observe = (target, name) => {
    target.on('pageerror', error => diagnostics.pageErrors.push({ page: name, message: error.message }));
    target.on('console', message => {
      if (message.type() === 'error') diagnostics.consoleErrors.push({ page: name, text: message.text(), location: message.location() });
    });
    target.on('response', response => {
      if (!response.url().includes('/api/customer-service') || response.status() < 400) return;
      pendingApiFailures.push((async () => {
        const request = response.request();
        let envelope = null;
        try { envelope = await response.json(); } catch {}
        let requestBody = null;
        try { requestBody = request.postDataJSON(); } catch {}
        diagnostics.apiFailures.push({ page: name, status: response.status(), url: response.url(),
          action: requestBody?.action || null, code: envelope?.error?.code || null });
      })());
    });
  };
  observe(page, 'editor');
  const check = (value, message) => { if (!value) throw new Error(message); };
  await page.setViewportSize({ width: 1440, height: 960 });
  const previewUrl = await page.evaluate(() => window.__LOOMRISE_CONSOLE_PREVIEW_URL__ || 'http://127.0.0.1:18765/');
  await page.goto(previewUrl);
  const { schema, apiOrigin } = await page.evaluate(async () => {
    const { createConfigurationClient } = await import('/r1-configuration.js');
    const client = createConfigurationClient();
    return { schema: (await client.customerRequest('contact.templates', { agent_id: 'course-demo' })).schema,
      apiOrigin: client.origin };
  });
  const expectedTypes = ['text', 'chat', 'social', 'link', 'portfolio', 'media', 'services', 'testimonials', 'booking',
    'faq', 'metrics', 'menu', 'hours', 'location', 'skills', 'experience', 'schedule', 'jobs', 'community', 'qr', 'contact'];
  check(JSON.stringify(schema.block_types.map(kind => kind.type)) === JSON.stringify(expectedTypes), '服务端联系页块目录与 21 类验收矩阵不一致');
  const kindByType = Object.fromEntries(schema.block_types.map(kind => [kind.type, kind]));
  await page.evaluate(async () => {
    const { createConfigurationClient } = await import('/r1-configuration.js');
    const client = createConfigurationClient();
    const draft = await client.request('draft.get', { agent_id: 'course-demo' });
    await client.customerRequest('contact.save', { agent_id: 'course-demo', expected_revision: draft.revision,
      contact: { title: '联系页 21 类矩阵', description: '全部使用本机虚构 fixture。', blocks: [] } });
  });
  await page.goto(new URL('#/contact?agent=course-demo', previewUrl).href);
  await page.getByLabel('页面标题', { exact: true }).waitFor();
  await page.getByLabel('页面标题', { exact: true }).fill('联系页 21 类矩阵');
  await page.getByLabel('页面说明', { exact: true }).fill('全部使用本机虚构 fixture。');
  check(!(await page.locator('.contextbar').textContent()).includes('已自动保存'), '联系页使用了本地自动保存状态');
  for (const type of expectedTypes) {
    await page.getByLabel('新增内容块', { exact: true }).selectOption(type);
    await page.getByRole('button', { name: '添加内容块', exact: true }).click();
  }
  check(await page.locator('[data-contact-block]').count() === expectedTypes.length, '不能新增完整的 21 类联系页块');
  await page.getByRole('button', { name: '保存修改', exact: true }).click();
  await page.locator('#workspace-content').getByText('已保存到服务端', { exact: false }).waitFor();
  await page.reload();
  check(await page.getByLabel('页面标题', { exact: true }).inputValue() === '联系页 21 类矩阵', '刷新丢失已保存联系页标题');
  check(await page.getByLabel('页面说明', { exact: true }).inputValue() === '全部使用本机虚构 fixture。', '刷新丢失已保存联系页说明');
  const savedBlocks = page.locator('[data-contact-block]');
  check(await savedBlocks.count() === expectedTypes.length, '刷新丢失联系页块');
  for (const [index, type] of expectedTypes.entries()) {
    check(await savedBlocks.nth(index).getAttribute('data-contact-block') === `block-${index + 1}`, `${type} 空块保存/刷新后顺序或身份不一致`);
  }
  const url = await page.getByRole('link', { name: '预览已保存草稿' }).getAttribute('href');
  const emptyPreview = await page.context().newPage();
  observe(emptyPreview, 'empty-preview');
  await emptyPreview.setViewportSize({ width: 1440, height: 960 });
  await emptyPreview.goto(url);
  check(await emptyPreview.locator('section[data-block-type]').count() === expectedTypes.length, '空状态预览没有显示全部 21 类块');
  for (const type of expectedTypes) {
    const block = emptyPreview.locator(`section[data-block-type="${type}"]`);
    check(await block.locator('h2').textContent() === kindByType[type].label, `${type} 空状态标题不一致`);
    if (type === 'chat') check((await block.textContent()).includes('不会创建访客会话'), '客服入口草稿预览暗示已建立会话');
    else check(await block.locator('.hint').textContent() === '暂无内容', `${type} 空状态提示缺失`);
    if (['social', 'link', 'booking'].includes(type)) {
      check(await block.locator('a').count() === 0, `${type} 空配置仍显示外链`);
    }
  }
  await emptyPreview.close();
  const expectations = [];
  const fieldValue = (type, field) => {
    if (type === 'faq' && field === 'question') return '如何报名？';
    if (type === 'faq' && field === 'answer') return '请联系人工客服。';
    if (type === 'media' && field === 'src') return 'https://example.test/course-preview.png';
    if (type === 'media' && field === 'alt') return '虚构课程示意图片';
    if (type === 'media' && field === 'media_type') return 'image';
    if (field === 'href' && type === 'contact') return 'mailto:help@example.test';
    if (field === 'href') return `https://example.test/${type}`;
    if (field === 'src') return `https://example.test/${type}-fixture.png`;
    if (field === 'alt') return `虚构${kindByType[type].label}图片`;
    if (field === 'media_type') return 'image';
    return `${type}-${field}-fixture`;
  };
  for (const [blockIndex, type] of expectedTypes.entries()) {
    const title = `${kindByType[type].label}矩阵标题`;
    const body = `${type}-block-body-fixture`;
    await page.locator(`#contact-field-blocks-${blockIndex}-title`).fill(title);
    await page.locator(`#contact-field-blocks-${blockIndex}-body`).fill(body);
    const kind = kindByType[type];
    const itemCount = type === 'media' ? 3 : kind.item_fields.length ? 1 : 0;
    const items = [];
    for (let itemIndex = 0; itemIndex < itemCount; itemIndex += 1) {
      await savedBlocks.nth(blockIndex).getByRole('button', { name: '添加内容', exact: true }).click();
      const values = Object.fromEntries(kind.item_fields.map(field => [field, fieldValue(type, field)]));
      if (type === 'media' && itemIndex > 0) {
        values.src = itemIndex === 1 ? 'https://example.test/course-preview.webm' : 'https://example.test/course-preview.wav';
        values.alt = itemIndex === 1 ? '虚构课程预览视频' : '虚构课程预览音频';
        values.media_type = itemIndex === 1 ? 'video' : 'audio';
      }
      for (const [field, value] of Object.entries(values)) {
        const control = page.locator(`#contact-field-blocks-${blockIndex}-items-${itemIndex}-${field}`);
        if (field === 'media_type') await control.selectOption(value);
        else await control.fill(value);
      }
      items.push(values);
    }
    expectations.push({ type, title, body, items });
  }
  await page.getByRole('button', { name: '保存修改', exact: true }).click();
  await page.locator('#workspace-content').getByText('已保存到服务端', { exact: false }).waitFor();
  await page.reload();
  await page.locator('[data-contact-block]').first().waitFor();
  check(await page.getByLabel('页面标题', { exact: true }).inputValue() === '联系页 21 类矩阵', '编辑后刷新丢失页面标题');
  check(await page.getByLabel('页面说明', { exact: true }).inputValue() === '全部使用本机虚构 fixture。', '编辑后刷新丢失页面说明');
  check(await page.locator('[data-contact-block]').count() === expectedTypes.length, '编辑后刷新丢失内容块');
  for (const [blockIndex, expected] of expectations.entries()) {
    check(await page.locator(`#contact-field-blocks-${blockIndex}-title`).inputValue() === expected.title, `${expected.type} 刷新丢失块标题`);
    check(await page.locator(`#contact-field-blocks-${blockIndex}-body`).inputValue() === expected.body, `${expected.type} 刷新丢失块说明`);
    for (const [itemIndex, values] of expected.items.entries()) {
      for (const [field, value] of Object.entries(values)) {
        check(await page.locator(`#contact-field-blocks-${blockIndex}-items-${itemIndex}-${field}`).inputValue() === value,
          `${expected.type} 刷新丢失条目字段 ${field}`);
      }
    }
  }
  const faqBlock = page.locator('[data-contact-block="block-10"]');
  const faqRows = faqBlock.locator('fieldset.contact-item');
  check(await faqRows.count() === 1, 'FAQ 浏览器 fixture 未建立一个起始条目');
  await faqBlock.getByRole('button', { name: '添加内容', exact: true }).click();
  check(await faqRows.count() === 2, 'FAQ 不能添加第二个条目');
  await page.locator('#contact-field-blocks-9-items-1-question').fill('待删除的问题？');
  await page.locator('#contact-field-blocks-9-items-1-answer').fill('待删除的回答。');
  await faqBlock.locator('[data-action="cs-contact-remove-item"][data-item-index="1"]').click();
  check(await faqRows.count() === 1, 'FAQ 条目删除没有从编辑器移除目标条目');
  check(await page.locator('#contact-field-blocks-9-items-0-question').inputValue() === '如何报名？', '删除新增条目时改动了已有 FAQ');
  const preview = await page.context().newPage();
  observe(preview, 'filled-preview');
  await preview.setViewportSize({ width: 1440, height: 960 });
  const localMediaFixtureRequests = { image: 0, video: 0, audio: 0 };
  const webm = Buffer.from('GkXfo59ChoEBQveBAULygQRC84EIQoKEd2VibUKHgQJChYECGFOAZwH/////////EU2bdKtNu4tTq4QVSalmU6yBoU27i1OrhBZUrmtTrIHNTbuMU6uEElTDZ1OsggEa7AEAAAAAAABoAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAVSalmpyrXsYMPQkBNgI1MYXZmNjIuMTIuMTAwV0GNTGF2ZjYyLjEyLjEwMBZUrmvIrgEAAAAAAAA/14EBc8WIi49brEtBhr6cgQAitZyDdW5kiIEAhoVWX1ZQOIOBASPjg4Q7msoA4JCwgRC6gRCagQJVsIRVuYEBElTDZ9hzc6BjwIBnyJpFo4dFTkNPREVSRIeNTGF2ZjYyLjEyLjEwMHNzsmPAi2PFiIuPW6xLQYa+Z8ihRaOHRU5DT0RFUkSHlExhdmM2Mi4yOC4xMDAgbGlidnB4H0O2dajngQCjo4EAAIAQAgCdASoQABAAAEcIhYWImYSIAgIADA1gAP7/q1CA', 'base64');
  const sampleRate = 8000;
  const sampleCount = sampleRate / 10;
  const wav = Buffer.alloc(44 + sampleCount * 2);
  wav.write('RIFF', 0); wav.writeUInt32LE(wav.length - 8, 4); wav.write('WAVEfmt ', 8);
  wav.writeUInt32LE(16, 16); wav.writeUInt16LE(1, 20); wav.writeUInt16LE(1, 22);
  wav.writeUInt32LE(sampleRate, 24); wav.writeUInt32LE(sampleRate * 2, 28);
  wav.writeUInt16LE(2, 32); wav.writeUInt16LE(16, 34); wav.write('data', 36);
  wav.writeUInt32LE(sampleCount * 2, 40);
  for (let i = 0; i < sampleCount; i += 1) wav.writeInt16LE(Math.round(Math.sin(2 * Math.PI * 440 * i / sampleRate) * 1000), 44 + i * 2);
  const installMediaFixture = target => target.route('https://example.test/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('.png')) {
      localMediaFixtureRequests.image += 1;
      return route.fulfill({ status: 200, contentType: 'image/svg+xml',
        body: '<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"></svg>' });
    }
    if (path.endsWith('.webm')) {
      localMediaFixtureRequests.video += 1;
      return route.fulfill({ status: 200, contentType: 'video/webm', body: webm });
    }
    if (path.endsWith('.wav')) {
      localMediaFixtureRequests.audio += 1;
      return route.fulfill({ status: 200, contentType: 'audio/wav', body: wav });
    }
    return route.abort();
  });
  const assertRenderedBlocks = async (target, expectedBlocks, chatPath = null) => {
    const actualTypes = await target.locator('section[data-block-type]').evaluateAll(blocks => blocks.map(block => block.dataset.blockType));
    check(JSON.stringify(actualTypes) === JSON.stringify(expectedBlocks.map(block => block.type)), '联系页渲染的块类型或顺序不一致');
    for (const expected of expectedBlocks) {
      const block = target.locator(`section[data-block-type="${expected.type}"]`);
      check(await block.locator('h2').textContent() === expected.title, `${expected.type} 渲染标题与已保存值不一致`);
      if (expected.body) check((await block.locator('p').allTextContents()).includes(expected.body), `${expected.type} 未显示块说明`);
      if (expected.type === 'faq') {
        check(await block.locator('details').count() === expected.items.length, 'FAQ 渲染数量不一致');
        for (const [index, item] of expected.items.entries()) {
          const faq = block.locator('details').nth(index);
          check(await faq.locator('summary').textContent() === item.question, 'FAQ 问题不一致');
          await faq.locator('summary').click();
          check(await faq.locator('p').textContent() === item.answer, 'FAQ 展开答案不一致');
        }
      } else if (expected.type === 'testimonials') {
        check(await block.locator('blockquote').count() === expected.items.length, '评价渲染数量不一致');
        for (const [index, item] of expected.items.entries()) {
          const quote = block.locator('blockquote').nth(index);
          check(await quote.locator('p').textContent() === item.quote && await quote.locator('cite').textContent() === item.author,
            '评价渲染内容不一致');
        }
      } else if (expected.type === 'chat') {
        if (chatPath) check(await block.locator('a.chat').getAttribute('href') === chatPath, '公开客服入口未固定到批准版本');
        else check((await block.textContent()).includes('不会创建访客会话') && await block.locator('a.chat').count() === 0,
          '客服入口草稿预览不应创建可用会话');
      } else if (expected.items.length) {
        check(await block.locator('.item').count() === expected.items.length, `${expected.type} 渲染条目数量不一致`);
        for (const [index, item] of expected.items.entries()) {
          const renderedItem = block.locator('.item').nth(index);
          for (const [field, value] of Object.entries(item)) {
            if (field === 'href') {
              const link = renderedItem.locator('a');
              check(await link.getAttribute('href') === value, `${expected.type} 渲染链接字段不一致`);
              check(await link.getAttribute('target') === '_blank', `${expected.type} 外链未使用独立浏览上下文`);
              check(await link.getAttribute('rel') === 'noopener noreferrer', `${expected.type} 外链缺少 opener 隔离`);
            }
            else if (field === 'src') check(await renderedItem.locator('img, video, audio').getAttribute('src') === value, `${expected.type} 渲染资源地址不一致`);
            else if (field === 'alt') {
              const resource = expected.type === 'media' && item.media_type !== 'image' ? renderedItem.locator(item.media_type) : renderedItem.locator('img');
              const accessibleText = expected.type === 'media' && item.media_type !== 'image'
                ? await resource.getAttribute('aria-label') : await resource.getAttribute('alt');
              check(accessibleText === value, `${expected.type} 渲染资源说明不一致`);
            } else if (field === 'media_type') {
              check(await renderedItem.locator(value === 'image' ? 'img' : value).count() === 1, '媒体类型与渲染元素不一致');
            } else check((await renderedItem.textContent()).includes(value), `${expected.type} 渲染字段 ${field} 缺失`);
          }
        }
      }
    }
  };
  await installMediaFixture(preview);
  await preview.goto(url);
  await assertRenderedBlocks(preview, expectations);
  const mediaExpected = expectations.find(item => item.type === 'media');
  const assertDecodedMedia = async target => {
    const image = target.locator('section[data-block-type="media"] img[alt="虚构课程示意图片"]');
    await image.scrollIntoViewIfNeeded();
    await image.evaluate(element => element.decode());
    check(await image.getAttribute('src') === 'https://example.test/course-preview.png', '图片与保存内容不一致');
    check(await image.evaluate(element => element.complete && element.naturalWidth === 1), '本机媒体图片 fixture 未正常载入');
    const video = target.locator('section[data-block-type="media"] video[aria-label="虚构课程预览视频"]');
    const audio = target.locator('section[data-block-type="media"] audio[aria-label="虚构课程预览音频"]');
    check(await video.getAttribute('src') === 'https://example.test/course-preview.webm', '视频与保存内容不一致');
    check(await audio.getAttribute('src') === 'https://example.test/course-preview.wav', '音频与保存内容不一致');
    check(await video.getAttribute('preload') === 'none' && await video.getAttribute('controls') !== null, '视频缺少安全的原生控件');
    check(await audio.getAttribute('preload') === 'none' && await audio.getAttribute('controls') !== null, '音频缺少安全的原生控件');
    await video.evaluate(element => element.load());
    await audio.evaluate(element => element.load());
    await target.waitForFunction(() => document.querySelector('video[aria-label="虚构课程预览视频"]')?.readyState >= 1
      && document.querySelector('audio[aria-label="虚构课程预览音频"]')?.readyState >= 1);
    check(await video.evaluate(element => element.videoWidth === 16 && element.videoHeight === 16), '本机视频 fixture 未解码');
    check(await audio.evaluate(element => element.duration > 0), '本机音频 fixture 未解码');
    for (const type of ['portfolio', 'menu', 'qr']) {
      const image = target.locator(`section[data-block-type="${type}"] img`);
      check(await image.count() === 1 && await image.getAttribute('alt') === `虚构${kindByType[type].label}图片`, `${type} 图片不一致`);
      await image.scrollIntoViewIfNeeded();
      await image.evaluate(element => element.decode());
      check(await image.evaluate(element => element.complete && element.naturalWidth === 1), `${type} 图片 fixture 未正常载入`);
    }
    check((await target.locator('section[data-block-type="booking"]').textContent()).includes('不代表预约成功'), '预约链接未说明跳转不代表已预约');
  };
  await assertDecodedMedia(preview);
  check(mediaExpected.items.length === 3, '媒体编辑没有覆盖图片、视频、音频');
  check(localMediaFixtureRequests.image >= 1 && localMediaFixtureRequests.video >= 1
    && localMediaFixtureRequests.audio >= 1, '媒体请求没有全部由本机 fixture 接管');
  await preview.setViewportSize({ width: 390, height: 844 });
  check(await preview.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), '390px 联系页草稿预览横向溢出');
  await preview.screenshot({ path: 'output/playwright/r3-contact-preview-21-blocks-390.png' });
  await preview.close();
  await page.locator('[data-contact-block="block-2"] [data-action="cs-contact-up"]').click();
  const reorderedBlocks = page.locator('[data-contact-block]');
  check(await reorderedBlocks.nth(0).getAttribute('data-contact-block') === 'block-2'
    && await reorderedBlocks.nth(1).getAttribute('data-contact-block') === 'block-1', '块上移未改变当前顺序');
  await page.locator('[data-contact-block="block-1"] [data-action="cs-contact-remove"]').click();
  check(await page.locator('[data-contact-block]').count() === expectedTypes.length - 1, '删除块没有从编辑器移除目标块');
  await page.getByRole('button', { name: '保存修改', exact: true }).click();
  await page.locator('#workspace-content').getByText('已保存到服务端', { exact: false }).waitFor();
  await page.reload();
  const persistedOrder = await page.locator('[data-contact-block]').evaluateAll(blocks => blocks.map(block => block.dataset.contactBlock));
  check(persistedOrder.length === expectedTypes.length - 1, '刷新后块删除未持久化');
  check(persistedOrder[0] === 'block-2' && persistedOrder[1] === 'block-3' && !persistedOrder.includes('block-1'),
    '刷新后块顺序或删除未持久化');
  await page.getByLabel('已批准的沙盒入口标识', { exact: true }).fill('contact-entry');
  await page.getByRole('button', { name: '查看入口版本', exact: true }).click();
  await page.getByRole('button', { name: '启用批准版 contact-fixture-v1', exact: true }).click();
  const share = page.getByRole('link', { name: '打开联系页 / 获取分享地址', exact: true });
  await share.waitFor();
  const sharedUrl = await share.getAttribute('href');
  const publicPage = await page.context().newPage();
  observe(publicPage, 'public-page');
  await publicPage.setViewportSize({ width: 1440, height: 960 });
  await publicPage.goto(sharedUrl);
  check(await publicPage.getByRole('heading', { name: '已批准测试页面', exact: true }).count() === 1, '启用错误地使用了当前草稿');
  check(await publicPage.locator('section[data-block-type]').count() === 1, '公开页面未保持原批准版快照');
  await publicPage.setViewportSize({ width: 390, height: 844 });
  check(await publicPage.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), '390px 已批准公开联系页横向溢出');
  await publicPage.screenshot({ path: 'output/playwright/r3-contact-public-390.png' });
  await publicPage.close();
  await page.getByRole('button', { name: '停用此联系页', exact: true }).click();
  await page.getByText('此入口的联系页尚未启用。', { exact: true }).waitFor();
  const disabledResponse = await page.request.get(sharedUrl);
  check(disabledResponse.status() === 404, '停用后公开页面仍可访问');
  const matrixSnapshot = await page.evaluate(async () => {
    const { createConfigurationClient } = await import('/r1-configuration.js');
    return createConfigurationClient().request('stable.get', { agent_id: 'course-demo', version_id: 'contact-matrix-fixture-v1' });
  });
  const matrixContact = matrixSnapshot.config.contact;
  check(JSON.stringify(matrixContact.blocks.map(({ type, title, body, items }) => ({ type, title, body, items }))) === JSON.stringify(expectations),
    '21 类批准 fixture 与草稿编辑矩阵的内容不同');
  await page.getByLabel('已批准的沙盒入口标识', { exact: true }).fill('contact-matrix-entry');
  await page.getByRole('button', { name: '查看入口版本', exact: true }).click();
  await page.getByRole('button', { name: '启用批准版 contact-matrix-fixture-v1', exact: true }).click();
  await share.waitFor();
  const matrixUrl = await share.getAttribute('href');
  const matrixPage = await page.context().newPage();
  observe(matrixPage, 'public-21-blocks');
  await installMediaFixture(matrixPage);
  const beforePublicMedia = { ...localMediaFixtureRequests };
  await matrixPage.setViewportSize({ width: 1440, height: 960 });
  const matrixResponse = await matrixPage.goto(matrixUrl);
  check(matrixResponse.status() === 200, '21 类批准公开页面不可访问');
  const matrixHtml = await matrixResponse.text();
  check(!matrixHtml.includes(matrixSnapshot.config.persona.goal), '公开联系页泄露内部 Prompt');
  check(await matrixPage.locator('script, input, textarea, form, iframe').count() === 0, '公开联系页包含编辑器或可执行配置');
  check(await matrixPage.getByRole('heading', { name: matrixContact.title, exact: true }).count() === 1, '公开联系页标题与批准快照不一致');
  check(await matrixPage.getByText(matrixContact.description, { exact: true }).count() === 1, '公开联系页说明与批准快照不一致');
  check((await matrixPage.locator('body').textContent()).includes('已批准沙盒版本 · contact-matrix-fixture-v1'), '公开联系页未标识实际批准版本');
  await assertRenderedBlocks(matrixPage, matrixContact.blocks, '/contact/course-demo/contact-matrix-entry/chat/contact-matrix-fixture-v1');
  await assertDecodedMedia(matrixPage);
  for (const mediaType of ['image', 'video', 'audio']) {
    check(localMediaFixtureRequests[mediaType] > beforePublicMedia[mediaType], `批准公开页面 ${mediaType} 没有由本机 fixture 载入`);
  }
  for (const width of [1440, 390]) {
    await matrixPage.setViewportSize({ width, height: 844 });
    check(await matrixPage.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${width}px 21 类批准公开联系页横向溢出`);
    await matrixPage.evaluate(() => window.scrollTo(0, 0));
    await matrixPage.screenshot({ path: `output/playwright/r3-contact-public-21-blocks-${width}.png` });
  }
  await matrixPage.locator('section[data-block-type="media"]').screenshot({ path: 'output/playwright/r3-contact-public-media-390.png' });
  await matrixPage.locator('section[data-block-type="faq"]').screenshot({ path: 'output/playwright/r3-contact-public-faq-390.png' });
  await matrixPage.close();
  await page.getByRole('button', { name: '停用此联系页', exact: true }).click();
  await page.getByText('此入口的联系页尚未启用。', { exact: true }).waitFor();
  check((await page.request.get(matrixUrl)).status() === 404, '停用后 21 类批准公开页面仍可访问');
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 960 });
    check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${width}px 联系页工作台溢出`);
    await page.screenshot({ path: `output/playwright/r3-contact-editor-${width}.png` });
  }
  await page.evaluate(async () => {
    const { createConfigurationClient } = await import('/r1-configuration.js');
    const client = createConfigurationClient();
    const draft = await client.request('draft.get', { agent_id: 'course-demo' });
    await client.request('draft.save', { agent_id: 'course-demo', expected_revision: draft.revision, config: draft.config });
  });
  await page.getByLabel('页面标题', { exact: true }).fill('冲突中的本地标题');
  await page.getByRole('button', { name: '保存修改', exact: true }).click();
  await page.getByText('冲突中的本地内容（可复制保留）', { exact: true }).waitFor();
  check(await page.getByLabel('页面标题', { exact: true }).inputValue() === '冲突中的本地标题', '冲突覆盖了未保存输入');
  await Promise.all(pendingApiFailures);
  const expectedApiFailures = [
    { status: 404, action: 'contact.get', code: 'not_found', count: 2 },
    { status: 409, action: 'contact.save', code: 'revision_conflict', count: 1 },
  ];
  for (const expected of expectedApiFailures) {
    check(diagnostics.apiFailures.filter(item => item.status === expected.status && item.action === expected.action && item.code === expected.code).length === expected.count,
      `联系页预期 API 响应数量不符 ${expected.action}/${expected.code}/${expected.status}`);
  }
  const expectedFailureCount = expectedApiFailures.reduce((count, expected) => count + expected.count, 0);
  check(diagnostics.pageErrors.length === 0, JSON.stringify(diagnostics.pageErrors));
  check(diagnostics.consoleErrors.length === expectedFailureCount, `未预期 console errors: ${JSON.stringify(diagnostics.consoleErrors)}`);
  check(diagnostics.apiFailures.length === expectedFailureCount, `存在未解释的失败客服 API 响应: ${JSON.stringify(diagnostics.apiFailures)}`);
  for (const error of diagnostics.consoleErrors) {
    const status = Number(error.text.match(/\b(404|409)\b/)?.[1]);
    const expected = expectedApiFailures.find(item => item.status === status);
    check(expected && error.location.url === `${apiOrigin}/api/customer-service`
      && diagnostics.apiFailures.some(item => item.status === expected.status && item.action === expected.action && item.code === expected.code
        && item.url === error.location.url), `console error 无法与实际 action/code/status 响应一一对应: ${JSON.stringify(error)}`);
  }
  return { blockTypes: expectedTypes.length, emptyBlocks: expectedTypes.length, editedBlocks: expectations.length,
    listTypes: expectedTypes.filter(type => kindByType[type].item_fields.length > 0).length,
    persistedReload: true, listItemDelete: true, blockDelete: true, blockReorder: true,
    approvedPublicMobile: { fixtureBlocks: 1, widths: [1440, 390] }, blockPreview: true, faqPreview: true,
    approvedPublicMatrix: { fixtureBlocks: matrixContact.blocks.length, widths: [1440, 390],
      allVisibleFields: true, mediaDecoded: true, faqExpanded: true, fixedChatVersion: true, privatePromptHidden: true, disabled: true,
      approval: 'preseeded-fixture-not-release-gate' },
    mediaBlockPreview: { image: true, video: true, audio: true }, externalLinkPolicy: true, emptyExternalLinksHidden: true,
    localMediaFixtureRequests, revisionConflict: true, approvedBinding: true, pageErrors: diagnostics.pageErrors,
    consoleErrors: diagnostics.consoleErrors, apiFailures: diagnostics.apiFailures,
    disable: true, viewports: [1440, 390], previewViewports: [1440, 390] };
}
