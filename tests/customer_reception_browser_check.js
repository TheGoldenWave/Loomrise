async page => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const check = (value, message) => { if (!value) throw new Error(message); };
  const appOrigin = new URL(page.url()).origin;
  const configPromise = page.waitForResponse(response => response.url().endsWith('/api/customer-service')
    && response.request().postDataJSON()?.action === 'widget.configuration', { timeout: 10000 });
  await page.goto(`${appOrigin}/widget/course-demo/widget-entry`);
  const configEnvelope = await (await configPromise).json();
  check(configEnvelope.ok && configEnvelope.result.faq_suggestions?.[0] === '体验课多少钱？', '公共配置未投影 FAQ 问题建议');
  const publicConfig = JSON.stringify(configEnvelope.result);
  check(!publicConfig.includes('source_id') && !publicConfig.includes('content_hash')
    && !publicConfig.includes('体验课价格为 19 元。'), 'Widget 公共配置泄露了来源标识、哈希或正文');
  await page.evaluate(() => sessionStorage.clear());
  await page.reload();
  await page.getByText('已连接', { exact: true }).waitFor();
  check(await page.locator('#intro #greeting').innerText() === '此页面使用确定性测试答复。', 'Widget 引导语未作为首屏欢迎显示');
  check(await page.locator('#intro #greeting').count() === 1, 'Widget 欢迎语出现多次');
  check(await page.locator('#messages .assistant').count() === 0, 'Widget 引导语不应重复写成自动 assistant 首句');
  const suggestionRequestPromise = page.waitForRequest(request => request.url().endsWith('/api/customer-service')
    && request.postDataJSON()?.action === 'widget.send', { timeout: 10000 });
  await page.getByRole('button', { name: '体验课多少钱？', exact: true }).click();
  const suggestionRequest = await suggestionRequestPromise;
  const suggestionPayload = suggestionRequest.postDataJSON().payload;
  check(suggestionPayload.text === '体验课多少钱？' && !('source_id' in suggestionPayload)
    && !('content_hash' in suggestionPayload), 'FAQ 点击未走普通访客问题发送合同');
  await page.locator('#reception').filter({ hasText: 'AI 答复已保存' }).waitFor();
  check(await page.locator('#messages .assistant').count() === 1, '应恰有一条 AI 答复');
  check(!(await page.locator('#messages').innerText()).includes('此页面使用确定性测试答复。'), 'Widget 引导语不得重复出现在首条答复中');
  check((await page.locator('#messages .citation').innerText()).includes('体验课价格为 19 元。'), '未显示可核验引文');
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 960 });
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'Widget 页面横向溢出');
    await page.screenshot({ path: `output/playwright/r3-reception-${width}.png` });
  }
  await page.reload();
  await page.locator('#messages .citation').waitFor();
  await page.getByRole('textbox', { name: '咨询内容' }).fill('模拟故障');
  await page.getByRole('button', { name: '发送', exact: true }).click();
  await page.locator('#reception').filter({ hasText: 'AI 服务暂时不可用' }).waitFor();
  check(await page.getByRole('textbox', { name: '咨询内容' }).inputValue() === '', '已保存的访客消息不能保留成待重发文本');
  check(await page.locator('#messages .assistant').count() === 1, '模型异常不得产生假答复');
  await page.reload();
  await page.locator('#reception').filter({ hasText: 'AI 服务暂时不可用' }).waitFor();
  check(await page.locator('#messages .visitor').count() === 2, '刷新不应重复访客消息');
  const inbox = await page.context().newPage();
  inbox.on('pageerror', error => errors.push(error.message));
  await inbox.goto(`${appOrigin}/inbox/course-demo`);
  const inboxActions = [];
  inbox.on('request', request => {
    if (!request.url().endsWith('/api/customer-service')) return;
    try {
      const action = request.postDataJSON()?.action;
      if (action) inboxActions.push(action);
    } catch { /* Ignore non-JSON browser requests. */ }
  });
  await inbox.locator('#list .conversation').first().click();
  await inbox.locator('#messages').filter({ hasText: 'AI 服务暂时不可用' }).waitFor();
  check((await inbox.locator('#messages').innerText()).includes('运行 run_'), 'Inbox 缺少运行关联');
  check((await inbox.locator('#conversationSummary').innerText()).includes('最近访客：模拟故障'), 'Inbox 接管摘要未反映最近访客消息');
  for (const width of [1440, 390]) {
    await inbox.setViewportSize({ width, height: 960 });
    await inbox.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    check(await inbox.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'Inbox 接管辅助区横向溢出');
  }
  const draftReply = inbox.getByRole('button', { name: '插入通用回复草稿' });
  check(await draftReply.isDisabled(), '未接管会话不能插入人工回复草稿');
  await inbox.getByRole('button', { name: '接管会话' }).click();
  await inbox.waitForFunction(() => !document.querySelector('#draftReply').disabled);
  await draftReply.click();
  check(await inbox.getByRole('textbox', { name: '回复内容' }).inputValue() === '您好，已收到您的消息。', '回复草稿没有填入可编辑文本框');
  check(!inboxActions.includes('inbox.reply'), '插入草稿不得自动发送消息');
  await inbox.getByRole('textbox', { name: '回复内容' }).fill('您好，人工已接管。');
  await inbox.getByRole('button', { name: '发送', exact: true }).click();
  check(inboxActions.includes('inbox.reply'), '明确提交后应通过现有人工回复接口发送');
  await page.getByText('您好，人工已接管。', { exact: true }).waitFor();
  await page.locator('#reception').filter({ hasText: '人工客服已回复' }).waitFor();
  const beforeRelease = (await inbox.evaluate(async () => {
    const response = await fetch('/api/customer-service', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'inbox.list', payload: { agent_id: 'course-demo' } }) });
    return (await response.json()).result.items[0];
  }));
  const releaseButton = inbox.getByRole('button', { name: '释放并恢复 AI', exact: true });
  await releaseButton.waitFor({ state: 'attached' });
  check(await releaseButton.isEnabled(), '当前认领坐席不能释放会话');
  await releaseButton.click();
  await inbox.waitForFunction(async previous => {
    const response = await fetch('/api/customer-service', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'inbox.list', payload: { agent_id: 'course-demo' } }) });
    const value = await response.json();
    const item = value.result.items.find(conversation => conversation.conversation_id === previous.conversation_id);
    return item?.state === 'bot' && item.assigned_to === null
      && item.occupancy_generation === previous.occupancy_generation + 1;
  }, beforeRelease);
  check(await releaseButton.isDisabled(), '释放后的会话仍可再次释放');
  await page.getByRole('textbox', { name: '咨询内容' }).fill('恢复 AI 后继续咨询价格');
  await page.getByRole('button', { name: '发送', exact: true }).click();
  await page.waitForFunction(() => document.querySelectorAll('#messages .assistant').length === 2);
  check((await page.locator('#messages .assistant').last().innerText()).includes('体验课价格为 19 元。'), '释放后自动接待没有恢复');
  await inbox.close();
  check(errors.length === 0, errors.join('\n'));
  return { citations: true, persistedHistory: true, errorWithoutDuplicate: true, welcomePriority: true, humanRoundTrip: true,
           releaseRestoresReception: true, handoffSummary: true, replyDraftRequiresManualSend: true,
           viewports: [1440, 390], pageErrors: errors.length, provider: 'deterministic fixture' };
}
