async page => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const check = (value, message) => { if (!value) throw new Error(message); };
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto('http://127.0.0.1:8777/widget/course-demo/widget-entry');
  await page.getByLabel('称呼（必填）').fill('派生文件测试访客');
  await page.getByRole('button', { name: '开始咨询', exact: true }).click();
  await page.getByText('已连接', { exact: true }).waitFor();
  await page.getByRole('textbox', { name: '咨询内容' }).fill('请人工发一张示意图');
  await page.locator('#handoff').check();
  await page.getByRole('button', { name: '发送', exact: true }).click();
  await page.getByText('请人工发一张示意图', { exact: true }).waitFor();
  const inbox = await page.context().newPage();
  inbox.on('pageerror', error => errors.push(error.message));
  await inbox.goto('http://127.0.0.1:8777/inbox/course-demo');
  await inbox.locator('#list .conversation').first().click();
  await inbox.getByRole('button', { name: '接管会话', exact: true }).click();
  await inbox.getByText('上传物料', { exact: true }).click();
  const source = await page.evaluate(() => {
    const canvas = document.createElement('canvas'); canvas.width = 1280; canvas.height = 720;
    const context = canvas.getContext('2d'); context.fillStyle = '#347657'; context.fillRect(0, 0, 1280, 720);
    return canvas.toDataURL('image/png').split(',')[1];
  });
  await inbox.locator('#file').setInputFiles({ name: 'fictional-diagram.png', mimeType: 'image/png', buffer: Buffer.from(source, 'base64') });
  await inbox.getByLabel('物料名称', { exact: true }).fill('虚构课程示意图');
  await inbox.getByRole('button', { name: '上传', exact: true }).click();
  await inbox.getByText('物料已上传', { exact: true }).waitFor();
  const original = await inbox.locator('#material option').filter({ hasText: '虚构课程示意图' }).first().getAttribute('value');
  await inbox.getByLabel('选择物料', { exact: true }).selectOption(original);
  await inbox.getByRole('button', { name: '生成预览与压缩文件', exact: true }).click();
  await inbox.locator('#material option').filter({ hasText: '预览图' }).first().waitFor({ state: 'attached' });
  const derived = await inbox.locator('#material option').filter({ hasText: '预览图' }).first().getAttribute('value');
  check(JSON.parse(derived).derivative_id, '派生文件选项未绑定真实产物');
  await inbox.getByLabel('选择物料', { exact: true }).selectOption(derived);
  await inbox.getByRole('button', { name: '发送物料', exact: true }).click();
  await page.getByRole('button', { name: '下载附件', exact: true }).waitFor();
  const downloading = page.waitForEvent('download');
  const receipt = page.waitForResponse(response => response.url().endsWith('/api/customer-service')
    && response.request().postDataJSON()?.action === 'widget.material.download');
  await page.getByRole('button', { name: '下载附件', exact: true }).click();
  const downloaded = await downloading;
  check(await downloaded.failure() === null, '浏览器下载失败');
  check(downloaded.suggestedFilename() === 'preview.png', '下载成了原件');
  const response = await receipt;
  const body = await response.json();
  check(body.ok && body.result.media_type === 'image/png', '下载类型或结果错误');
  check(response.request().postDataJSON().payload.derivative_id === JSON.parse(derived).derivative_id, '下载错派生版本');
  const bytes = Buffer.from(body.result.content_base64, 'base64');
  check(bytes.readUInt32BE(16) === 1024 && bytes.readUInt32BE(20) === 576, '下载文件没有实际缩放');
  for (const width of [1440, 390]) {
    await inbox.setViewportSize({ width, height: 960 });
    check(await inbox.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${width}px Inbox 横向溢出`);
    await inbox.screenshot({ path: `output/playwright/r3-media-inbox-${width}.png` });
  }
  check(!errors.length, errors.join('; '));
  await inbox.close();
  return { passed: true, realImageTransform: true, originalPreserved: true, selectedDerivativeSent: true,
    browserDownloadCompleted: true, dimensions: [1024, 576], widths: [1440, 390], errors };
}
