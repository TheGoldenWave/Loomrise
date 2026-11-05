async page => {
  const check = (value, message) => { if (!value) throw new Error(message); };
  const origin = await page.evaluate(() => window.__LOOMRISE_CONFIG_API__ || 'http://127.0.0.1:18879');
  const errors = [];
  let replies = 0;
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => {
    if (request.url().endsWith('/api/customer-service') && request.method() === 'POST'
      && request.postDataJSON().action === 'inbox.reply') replies += 1;
  });
  const api = (action, payload = {}) => page.evaluate(async ({ action, payload, origin }) => {
    const response = await fetch(`${origin}/api/customer-service`, { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action, payload }) });
    const result = await response.json();
    if (!result.ok) throw new Error(result.error?.message || action);
    return result.result;
  }, { action, payload: action.startsWith('widget.') && action !== 'widget.open' ? payload : { agent_id: 'course-demo', ...payload }, origin });
  const send = (session, text) => api('widget.send', { conversation_id: session.conversation_id,
    visitor_token: session.visitor_token, text, request_human: true, message_id: crypto.randomUUID() });
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto(`${origin}/inbox/course-demo`);
  const session = await api('widget.open', { entry_id: 'widget-entry' });
  await send(session, '体验课多少钱？请人工协助。');
  await page.getByRole('button', { name: '刷新', exact: true }).click();
  await page.locator('#list [data-conversation-id]').filter({ hasText: session.conversation_id }).click();
  await page.getByText('AI 摘要与回复候选', { exact: true }).click();
  const generate = page.locator('#generateAssistance');
  const adopt = page.locator('#adoptAssistance');
  const proposal = page.locator('#assistanceProposal');
  const composer = page.getByLabel('回复内容', { exact: true });
  check(await generate.isDisabled(), '未接管仍可生成辅助候选');
  await page.getByRole('button', { name: '接管会话', exact: true }).click();
  await page.waitForFunction(() => !document.querySelector('#generateAssistance').disabled);
  await composer.fill('人工原草稿');
  await generate.click();
  await proposal.waitFor({ state: 'visible' });
  check(await composer.inputValue() === '人工原草稿' && replies === 0, '生成覆盖或发送了人工草稿');
  check((await page.locator('#assistanceCitations').textContent()).includes('体验课价格为 19 元。'), '候选缺少资料引用');
  check((await page.locator('#assistanceSummary').textContent()).includes('<script>')
    && await page.evaluate(() => window.__assistanceInjected) === undefined, '模型内容被当作 HTML 执行');
  check(await adopt.textContent() === '采用并替换回复草稿', '替换现有草稿未明确提示');
  await adopt.click();
  await page.waitForFunction(() => document.querySelector('#text').value === '体验课价格为 19 元。');
  check(replies === 0, '采用候选自动发送了回复');
  await page.getByRole('button', { name: '发送', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('#text').value === '');
  check(replies === 1, '人工发送没有使用唯一原回复接口');
  const delivered = await api('widget.messages', { conversation_id: session.conversation_id, visitor_token: session.visitor_token });
  check(delivered.items.some(message => message.sender === 'operator' && message.text === '体验课价格为 19 元。'), '人工回复未回到访客线程');

  // Hold an already generated response while a newer visitor message invalidates its snapshot.
  let releaseGenerated, generationReady;
  const released = new Promise(resolve => { releaseGenerated = resolve; });
  const ready = new Promise(resolve => { generationReady = resolve; });
  let hold = true;
  await page.route('**/api/customer-service', async route => {
    if (hold && route.request().method() === 'POST' && route.request().postDataJSON().action === 'inbox.assistance.generate') {
      hold = false;
      const response = await route.fetch(); generationReady(); await released;
      await route.fulfill({ response });
    } else await route.continue();
  });
  await page.waitForFunction(() => !document.querySelector('#generateAssistance').disabled);
  await composer.fill('新草稿保留');
  await generate.click();
  await ready;
  await send(session, '新增问题，请保留会话上下文');
  await page.getByRole('button', { name: '刷新', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('#conversationSummary').textContent.includes('新增问题'));
  releaseGenerated();
  await page.waitForFunction(() => !document.querySelector('#generateAssistance').disabled);
  check(await proposal.isHidden() && await adopt.isDisabled(), '迟到候选覆盖了更新后的会话');
  check(await composer.inputValue() === '新草稿保留' && replies === 1, '丢弃迟到候选改变了人工草稿或发送');
  await page.unroute('**/api/customer-service');

  await generate.click();
  await proposal.waitFor({ state: 'visible' });
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 960 });
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${width}px 横向溢出`);
    await page.screenshot({ path: `output/playwright/r3-inbox-assistance-${width}.png` });
  }
  const second = await api('widget.open', { entry_id: 'widget-entry' });
  await send(second, '另一个访客请求人工');
  await page.getByRole('button', { name: '刷新', exact: true }).click();
  await page.locator('#list [data-conversation-id]').filter({ hasText: second.conversation_id }).click();
  check(await proposal.isHidden() && await adopt.isDisabled(), '候选泄漏到另一个线程');
  await page.locator('#list [data-conversation-id]').filter({ hasText: session.conversation_id }).click();
  await page.waitForFunction(() => !document.querySelector('#generateAssistance').disabled);
  await send(session, '辅助故障');
  await page.getByRole('button', { name: '刷新', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('#conversationSummary').textContent.includes('辅助故障'));
  await generate.click();
  await page.waitForFunction(() => !document.querySelector('#generateAssistance').disabled);
  check(await proposal.isHidden() && !((await page.locator('#assistanceStatus').textContent()).includes('PRIVATE-')),
    'Provider 故障返回了候选或泄漏连接细节');
  check(errors.length === 0, errors.join('; '));
  return { passed: true, manualAdoptionAndSend: true, lateCandidateDiscarded: true,
    crossThreadIsolation: true, providerFailureRedacted: true, pageErrors: 0, widths: [1440, 390] };
}
