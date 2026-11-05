async page => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const check = (value, message) => { if (!value) throw new Error(message); };
  await page.goto('http://127.0.0.1:18878/widget/course-demo/widget-entry');
  await page.evaluate(() => sessionStorage.clear());
  await page.reload();
  await page.getByText('此页面使用确定性测试答复。', { exact: true }).waitFor();
  await page.getByText('已连接', { exact: true }).waitFor();

  const responsePromise = page.waitForResponse(response => response.url().endsWith('/api/customer-service')
    && response.request().postDataJSON()?.action === 'widget.send', { timeout: 10000 });
  const visitorText = '我会在服务时间内回复。';
  await page.getByRole('textbox', { name: '咨询内容', exact: true }).fill(visitorText);
  await page.getByRole('button', { name: '发送', exact: true }).click();
  const envelope = await (await responsePromise).json();
  check(envelope.ok, '离线模式接待请求失败');
  check(envelope.result.reception.status === 'outside_schedule', '开放时段的离线模式应交由人工接待');
  check(envelope.result.assistant === null, '开放时段的离线模式不得生成 AI 答复');
  await page.getByText('当前由人工接待，消息已保留在客服收件箱。', { exact: true }).waitFor();
  check(await page.locator('#messages .visitor').count() === 1, '访客消息应保留且只出现一次');
  check(await page.locator('#messages .assistant').count() === 0, '离线模式不应产生 assistant 消息');

  const conversationId = await page.evaluate(() =>
    JSON.parse(sessionStorage.getItem('loomrise:course-demo:widget-entry')).conversation_id);
  await page.reload();
  await page.getByText('当前由人工接待，消息已保留在客服收件箱。', { exact: true }).waitFor();
  check(JSON.parse(await page.evaluate(() => sessionStorage.getItem('loomrise:course-demo:widget-entry'))).conversation_id
    === conversationId, '刷新后 Widget 会话 ID 应保持不变');
  check(await page.locator('#messages .visitor').count() === 1, '刷新不应重复访客消息');

  const inbox = await page.context().newPage();
  inbox.on('pageerror', error => errors.push(error.message));
  await inbox.goto('http://127.0.0.1:18878/inbox/course-demo');
  await inbox.locator('#list .conversation').filter({ hasText: conversationId }).click();
  await inbox.locator('#messages').filter({ hasText: visitorText }).waitFor();
  check(await inbox.locator('#messages .assistant').count() === 0, 'Inbox 不应出现离线模式自动答复');

  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 960 });
    check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'Widget 页面横向溢出');
    await page.screenshot({ path: `output/playwright/r3-offline-reception-${width}.png` });
  }
  await inbox.close();
  check(errors.length === 0, errors.join('\n'));
  return { passed: true, mode: 'offline', openHours: 'always', outsideSchedule: true,
    persistedVisitorMessage: true, inboxVisible: true, widths: [1440, 390], pageErrors: errors.length };
}
