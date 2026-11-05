async page => {
  const errors = [];
  let faqSend = null;
  page.on('pageerror', error => errors.push(error.message));
  const check = (value, message) => { if (!value) throw new Error(message); };
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.route('**/api/customer-service', async route => {
    const body = route.request().postDataJSON();
    if (body?.action === 'widget.configuration') {
      const response = await route.fetch();
      const result = await response.json();
      result.result.faq_suggestions = ['体验课多少钱？'];
      await route.fulfill({ response, json: result });
      return;
    }
    if (body?.action === 'widget.send' && body.payload?.text === '体验课多少钱？') faqSend = body;
    await route.continue();
  });
  await page.goto('http://127.0.0.1:8777/widget/course-demo/widget-entry');
  await page.evaluate(() => sessionStorage.clear());
  await page.reload();
  await page.getByRole('heading', { name: '虚构课程客服' }).waitFor();
  await page.getByText('当前不在接待时段，可在此留言。').waitFor();
  await page.getByRole('button', { name: '开始咨询' }).click();
  check(await page.locator('#visitorProfile').isVisible(), '必填字段未阻止开始');
  const nameInput = page.locator('#profileFields input[name="visitor_name"]');
  const emailInput = page.locator('#profileFields input[name="visitor_email"]');
  const telInput = page.locator('#profileFields input[name="visitor_phone"]');
  check(await nameInput.count() === 1 && await nameInput.getAttribute('type') === 'text'
    && await nameInput.getAttribute('required') !== null, '必填文本字段类型或约束未按配置渲染');
  check(await emailInput.count() === 1 && await emailInput.getAttribute('type') === 'email'
    && await emailInput.getAttribute('required') === null, '选填邮箱字段类型或约束未按配置渲染');
  check(await telInput.count() === 1 && await telInput.getAttribute('type') === 'tel'
    && await telInput.getAttribute('required') === null, '选填电话字段类型或约束未按配置渲染');
  await page.getByRole('button', { name: '开始咨询' }).click();
  check(await page.evaluate(() => !sessionStorage.getItem('loomrise:course-demo:widget-entry')),
    '缺少必填称呼时仍建立了 Widget 会话');
  await page.getByLabel('称呼（必填）').fill('测试访客');
  await page.getByRole('button', { name: '开始咨询' }).click();
  await page.getByText('已连接', { exact: true }).waitFor();
  const offlineSession = await page.evaluate(() => JSON.parse(sessionStorage.getItem('loomrise:course-demo:widget-entry')));
  check(offlineSession?.conversation_id && offlineSession?.visitor_token, '离线留言前未建立 Widget 会话');
  await page.getByRole('button', { name: '体验课多少钱？', exact: true }).click();
  await page.locator('#messages .visitor').filter({ hasText: '体验课多少钱？' }).waitFor();
  await page.locator('#reception').filter({ hasText: '消息已保留在客服收件箱' }).waitFor();
  check(faqSend?.action === 'widget.send' && faqSend.payload?.text === '体验课多少钱？',
    'FAQ 建议没有沿普通 widget.send 路径提交');
  check(!('source_id' in faqSend.payload) && !('content_hash' in faqSend.payload),
    'FAQ 建议请求不应传入知识来源引用');
  check(await page.locator('#messages .assistant').count() === 0,
    'FAQ 建议点击不应显示静态答案');
  await page.reload();
  const restoredOfflineSession = await page.evaluate(() => JSON.parse(sessionStorage.getItem('loomrise:course-demo:widget-entry')));
  check(restoredOfflineSession?.conversation_id === offlineSession.conversation_id,
    '刷新后离线留言切换到了新会话');
  await page.locator('#messages .visitor').filter({ hasText: '体验课多少钱？' }).waitFor();
  check(await page.locator('#messages .visitor').filter({ hasText: '体验课多少钱？' }).count() === 1,
    '刷新后离线留言丢失或重复');
  await page.getByRole('textbox', { name: '咨询内容' }).fill('请人工协助');
  await page.locator('#handoff').check();
  await page.getByRole('button', { name: '发送', exact: true }).click();
  await page.getByText('请人工协助', { exact: true }).waitFor();
  await page.reload();
  await page.getByText('请人工协助', { exact: true }).waitFor();
  check(await page.locator('#visitorProfile').isHidden(), '旧会话刷新后重复要求访客信息');
  const inbox = await page.context().newPage();
  await inbox.goto('http://127.0.0.1:8777/inbox/course-demo');
  await inbox.locator('#list .conversation').first().click();
  const inboxSession = await inbox.evaluate(async () => {
    const response = await fetch('/api/customer-service', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'inbox.list', payload: { agent_id: 'course-demo' } }) });
    return (await response.json()).result.items[0];
  });
  check(inboxSession?.conversation_id === offlineSession.conversation_id,
    'Inbox 中的离线留言不属于原 Widget 会话');
  check(inboxSession.visitor_fields?.visitor_name === '测试访客'
    && Object.keys(inboxSession.visitor_fields).length === 1,
  '选填字段为空时应保留称呼且不生成空字段投影');
  await inbox.locator('#messages .visitor').filter({ hasText: '体验课多少钱？' }).waitFor();
  await inbox.getByText('测试访客', { exact: true }).waitFor();
  await inbox.getByRole('button', { name: '接管会话' }).click();
  await inbox.getByRole('textbox', { name: '回复内容' }).fill('您好，我来协助。');
  await inbox.getByRole('button', { name: '发送', exact: true }).click();
  await page.getByText('您好，我来协助。', { exact: true }).waitFor();
  const repliedSession = await page.evaluate(() => JSON.parse(sessionStorage.getItem('loomrise:course-demo:widget-entry')));
  check(repliedSession?.conversation_id === offlineSession.conversation_id,
    '坐席回复续接到了不同的 Widget 会话');
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 960 });
    check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'Widget 页面横向溢出');
    await page.screenshot({ path: `output/playwright/r3-widget-config-${width}.png` });
  }
  check(errors.length === 0, errors.join('\n'));
  await inbox.close();

  const english = await page.context().newPage();
  english.on('pageerror', error => errors.push(error.message));
  await english.route('**/api/customer-service', async route => {
    if (route.request().method() !== 'POST' || route.request().postDataJSON()?.action !== 'widget.configuration') {
      await route.continue();
      return;
    }
    const response = await route.fetch();
    const body = await response.json();
    body.result.widget.language = 'en';
    body.result.widget.title = 'T'.repeat(100);
    body.result.widget.greeting = 'G'.repeat(2000);
    body.result.widget.availability = 'open';
    await route.fulfill({ response, json: body });
  });
  await english.setViewportSize({ width: 390, height: 844 });
  await english.goto('http://127.0.0.1:8777/widget/course-demo/widget-entry');
  await english.getByText('Enter visitor details', { exact: true }).waitFor();
  check(await english.locator('html').getAttribute('lang') === 'en', 'Widget 未应用英文语言配置');
  check(await english.locator('h1').innerText() === 'T'.repeat(100), 'Widget 未显示完整上限标题');
  check(await english.locator('#greeting').innerText() === 'G'.repeat(2000), 'Widget 未显示完整上限欢迎语');
  check(await english.locator('#availability').innerText() === 'Within service hours', 'Widget 可用状态未翻译');
  check(await english.getByRole('button', { name: 'Start chat' }).isVisible(), '英文开始咨询按钮缺失');
  await english.getByRole('button', { name: 'Start chat' }).click();
  check(await english.getByRole('textbox', { name: '咨询内容' }).isVisible() === false, '填写必填资料前不应进入对话');
  await english.getByLabel('称呼 (required)').fill('English fixture');
  await english.locator('#profileFields input[name="visitor_email"]').fill('visitor@example.test');
  await english.locator('#profileFields input[name="visitor_phone"]').fill('+1 555 0100');
  await english.getByRole('button', { name: 'Start chat' }).click();
  await english.getByPlaceholder('Enter your question').waitFor();
  check(await english.getByRole('button', { name: 'Send', exact: true }).isVisible(), '英文发送按钮缺失');
  const englishSession = await english.evaluate(() => JSON.parse(sessionStorage.getItem('loomrise:course-demo:widget-entry')));
  await english.getByLabel('咨询内容').fill('验证访客字段投影');
  await english.getByRole('button', { name: 'Send', exact: true }).click();
  await english.locator('#messages .visitor').filter({ hasText: '验证访客字段投影' }).waitFor();
  const englishInbox = await english.context().newPage();
  await englishInbox.goto('http://127.0.0.1:8777/inbox/course-demo');
  await englishInbox.locator('#list .conversation').filter({ hasText: englishSession.conversation_id }).click();
  await englishInbox.locator('#visitorInfo').getByText('English fixture').waitFor();
  const visitorInfo = await englishInbox.locator('#visitorInfo').innerText();
  for (const value of ['English fixture', 'visitor@example.test', '+1 555 0100']) {
    check(visitorInfo.includes(value), `Inbox 未显示访客字段 ${value}`);
  }
  await englishInbox.close();
  check(await english.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), '英文最大长度内容造成手机横向溢出');
  await english.close();
  check(errors.length === 0, errors.join('\n'));
  return { pageErrors: errors.length, requiredFields: true, optionalFields: true, persistedVisitorFields: true,
    persistedHistory: true, offlineSameThread: true, humanRoundTrip: true,
    language: 'en', maxText: true, viewports: [1440, 390] };
}
