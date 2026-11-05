async page => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const check = (value, message) => { if (!value) throw new Error(message); };
  await page.goto('http://127.0.0.1:8788/widget/course-demo/widget-entry');
  await page.evaluate(() => sessionStorage.clear());
  await page.reload();
  await page.getByText('此页面使用真实模型和虚构资料。', { exact: true }).waitFor();
  await page.getByText('已连接', { exact: true }).waitFor();
  const responsePromise = page.waitForResponse(response => response.url().endsWith('/api/customer-service')
    && response.request().postDataJSON()?.action === 'widget.send', { timeout: 75000 });
  await page.getByRole('textbox', { name: '咨询内容', exact: true }).fill('请依据资料告诉我体验课价格。');
  await page.getByRole('button', { name: '发送', exact: true }).click();
  const response = await responsePromise;
  const envelope = await response.json();
  check(envelope.ok, '真实接待请求失败');
  check(envelope.result.reception.status === 'answered', `接待未答复：${envelope.result.reception.status}`);
  await page.locator('#messages .assistant').waitFor();
  check((await page.locator('#messages .assistant').innerText()).includes('19'), '答复不包含资料中的价格');
  check((await page.locator('#messages .citation').innerText()).includes('体验课价格为 19 元。'), '真实答复没有可核验原文');
  const conversationId = await page.evaluate(() =>
    JSON.parse(sessionStorage.getItem('loomrise:course-demo:widget-entry')).conversation_id);
  await page.reload();
  await page.locator('#messages .citation').waitFor();
  check(await page.locator('#messages .assistant').count() === 1, '刷新导致重复答复');
  const inbox = await page.context().newPage();
  await inbox.goto('http://127.0.0.1:8788/inbox/course-demo');
  await inbox.locator('#list .conversation').filter({ hasText: conversationId }).click();
  await inbox.waitForFunction(runId => document.querySelector('#messages')?.innerText.includes(runId),
    envelope.result.reception.run_id);
  check((await inbox.locator('#messages').innerText()).includes(envelope.result.reception.run_id), 'Inbox 缺少本次真实接待的 Run 关联');
  await inbox.getByRole('button', { name: '接管会话', exact: true }).click();
  await inbox.getByRole('textbox', { name: '回复内容', exact: true }).fill('测试人工已接管。');
  await inbox.getByRole('button', { name: '发送', exact: true }).click();
  await page.getByText('测试人工已接管。', { exact: true }).waitFor();
  await page.getByRole('textbox', { name: '咨询内容', exact: true }).fill('后续由人工继续回答。');
  await page.getByRole('button', { name: '发送', exact: true }).click();
  await page.locator('#reception').filter({ hasText: '人工' }).waitFor();
  check(await page.locator('#messages .assistant').count() === 1, '人工接管后仍自动答复');
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 960 });
    check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), '接待页面横向溢出');
    await page.screenshot({ path: `output/playwright/r3-live-reception-${width}.png` });
  }
  await inbox.close();
  check(!errors.length, errors.join('; '));
  return { passed: true, evidence: 'real model with fictional data', reception: envelope.result.reception,
    groundedPrice: true, citations: envelope.result.assistant.citations, persistedHistory: true,
    humanTakeover: true, widths: [1440, 390], pageErrors: errors.length };
}
