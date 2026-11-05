async page => {
  const check = (value, message) => { if (!value) throw new Error(message); };
  const origin = await page.evaluate(() => window.__LOOMRISE_CONFIG_API__ || 'http://127.0.0.1:8791');
  const errors = [];
  const mutations = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => {
    if (!request.url().endsWith('/api/customer-service') || request.method() !== 'POST') return;
    const value = request.postDataJSON();
    if (['inbox.read', 'inbox.claim', 'inbox.reply', 'inbox.release'].includes(value.action)) mutations.push(value.action);
  });
  const api = (action, payload = {}) => page.evaluate(async ({ action, payload, origin }) => {
    const response = await fetch(`${origin}/api/customer-service`, { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action, payload }) });
    const value = await response.json();
    if (!response.ok || !value.ok) throw new Error(value.error?.message || action);
    return value.result;
  }, { action, payload: action === 'widget.send' ? payload : { agent_id: 'course-demo', ...payload }, origin });
  const send = (session, text, human = false) => api('widget.send', {
    conversation_id: session.conversation_id, visitor_token: session.visitor_token,
    message_id: crypto.randomUUID(), text, request_human: human,
  });
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto(`${origin}/inbox/course-demo`);
  const filter = page.getByLabel('筛选会话', { exact: true });
  await filter.waitFor({ timeout: 5000 });
  const bot = await api('widget.open', { entry_id: 'contact-entry' });
  const waiting = await api('widget.open', { entry_id: 'contact-entry' });
  const mine = await api('widget.open', { entry_id: 'contact-entry' });
  await send(bot, '自动接待线程');
  await send(waiting, '请人工接待', true);
  await send(mine, '准备由我接管');
  await page.getByRole('button', { name: '刷新', exact: true }).click();
  const item = id => page.locator('#list [data-conversation-id]').filter({ hasText: id });
  await item(mine.conversation_id).waitFor();
  await filter.selectOption('mine');
  await page.getByText('当前筛选下没有会话。', { exact: true }).waitFor();
  await filter.selectOption('all');
  await item(mine.conversation_id).click();
  await page.getByRole('button', { name: '接管会话', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('#status').textContent.startsWith('由我接管'));
  await page.getByLabel('回复内容').fill('保留在当前会话的草稿');
  const before = mutations.length;
  await filter.selectOption('waiting');
  await item(waiting.conversation_id).waitFor();
  check(await item(bot.conversation_id).count() === 0 && await item(mine.conversation_id).count() === 0, '待接管筛选包含其他状态');
  check(await page.getByLabel('回复内容').inputValue() === '保留在当前会话的草稿', '筛选丢失回复草稿');
  check((await page.locator('#status').textContent()).startsWith('由我接管'), '筛选切换了当前会话');
  check(mutations.length === before, '筛选触发了已读、接管或发送');
  await send(bot, 'SSE 后进入待接管', true);
  await item(bot.conversation_id).waitFor();
  check(await filter.inputValue() === 'waiting', 'SSE 更新重置了筛选');
  check(await page.getByLabel('回复内容').inputValue() === '保留在当前会话的草稿', 'SSE 更新丢失当前草稿');
  await filter.selectOption('mine');
  check(await item(mine.conversation_id).count() === 1 && await item(waiting.conversation_id).count() === 0, '由我接管筛选错误');
  await filter.selectOption('unread');
  check(await item(waiting.conversation_id).count() === 1 && await item(mine.conversation_id).count() === 0, '未读筛选错误');
  await filter.selectOption('all');
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 960 });
    check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${width}px 横向溢出`);
    await page.screenshot({ path: `output/playwright/r3-inbox-filters-${width}.png` });
  }
  check(errors.length === 0, errors.join('; '));
  return { passed: true, filters: ['all', 'waiting', 'mine', 'unread'], sseRetainsFilter: true,
    noFilterSideEffects: true, preservesSelectedDraft: true, pageErrors: errors.length, widths: [1440, 390] };
}
