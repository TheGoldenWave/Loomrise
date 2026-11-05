async page => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('http://127.0.0.1:8799/widget_install_site.html');
  const frame = page.locator('iframe[data-loomrise-widget="course-demo/widget-entry"]');
  await frame.waitFor({ state: 'attached' });
  const widget = page.frameLocator('iframe[data-loomrise-widget="course-demo/widget-entry"]');
  await widget.getByText('已连接', { exact: true }).waitFor();

  const visitorContext = await page.context().browser().newContext();
  const visitorPage = await visitorContext.newPage();
  visitorPage.on('pageerror', error => errors.push(error.message));
  await visitorPage.goto('http://127.0.0.1:8799/widget_install_site.html');
  const otherWidget = visitorPage.frameLocator('iframe[data-loomrise-widget="course-demo/widget-entry"]');
  await otherWidget.getByText('已连接', { exact: true }).waitFor();
  const sessionFrom = locator => locator.locator('body').evaluate(() =>
    JSON.parse(sessionStorage.getItem('loomrise:course-demo:widget-entry')));
  const firstSession = await sessionFrom(widget);
  const secondSession = await sessionFrom(otherWidget);
  if (firstSession.conversation_id === secondSession.conversation_id) {
    throw new Error('Independent browser contexts must receive separate visitor conversations');
  }
  const firstOnly = 'VISITOR-CONTEXT-FIRST-ONLY';
  const secondOnly = 'VISITOR-CONTEXT-SECOND-ONLY';
  await widget.locator('#text').fill(firstOnly);
  await widget.locator('#send').click();
  await widget.locator('#messages').getByText(firstOnly, { exact: true }).waitFor();
  await otherWidget.locator('#text').fill(secondOnly);
  await otherWidget.locator('#send').click();
  await otherWidget.locator('#messages').getByText(secondOnly, { exact: true }).waitFor();
  if (await widget.locator('#messages').getByText(secondOnly, { exact: true }).count()
      || await otherWidget.locator('#messages').getByText(firstOnly, { exact: true }).count()) {
    throw new Error('Independent visitor conversations must not expose each other messages');
  }
  const crossCredentials = await otherWidget.locator('body').evaluate(async (_, sessions) => {
    async function call(action, payload) {
      const response = await fetch('/api/customer-service', { method: 'POST',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action, payload }) });
      return { status: response.status, body: await response.json() };
    }
    return {
      readFirst: await call('widget.messages', {
        conversation_id: sessions.first.conversation_id, visitor_token: sessions.second.visitor_token,
      }),
      readSecond: await call('widget.messages', {
        conversation_id: sessions.second.conversation_id, visitor_token: sessions.first.visitor_token,
      }),
      writeFirst: await call('widget.send', {
        conversation_id: sessions.first.conversation_id, visitor_token: sessions.second.visitor_token,
        text: 'CROSS-CONTEXT-UNAUTHORIZED-WRITE', request_human: false,
        message_id: 'cross-context-write-first',
      }),
      writeSecond: await call('widget.send', {
        conversation_id: sessions.second.conversation_id, visitor_token: sessions.first.visitor_token,
        text: 'CROSS-CONTEXT-UNAUTHORIZED-WRITE', request_human: false,
        message_id: 'cross-context-write-second',
      }),
    };
  }, { first: firstSession, second: secondSession });
  for (const result of Object.values(crossCredentials)) {
    if (![403, 404].includes(result.status) || result.body.ok) {
      throw new Error(`Cross-context visitor credentials must be rejected: ${JSON.stringify(crossCredentials)}`);
    }
  }

  await widget.locator('#text').fill('请人工客服联系我');
  await widget.locator('#handoff').check();
  await widget.locator('#send').click();
  await widget.locator('#reception').filter({ hasText: '已请求人工客服' }).waitFor();

  const inbox = await page.context().newPage();
  inbox.on('pageerror', error => errors.push(error.message));
  await inbox.goto('http://127.0.0.1:8798/inbox/course-demo');
  await inbox.locator('#list .conversation').first().click();
  await inbox.locator('#messages').filter({ hasText: '请人工客服联系我' }).waitFor();
  await inbox.getByRole('button', { name: '接管会话' }).click();
  await inbox.getByRole('textbox', { name: '回复内容' }).fill('您好，人工已接管。');
  await inbox.getByRole('button', { name: '发送', exact: true }).click();
  await widget.getByText('您好，人工已接管。', { exact: true }).waitFor();

  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 960 });
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)) {
      throw new Error(`Independent host page overflows at ${width}px`);
    }
    await page.screenshot({ path: `output/playwright/r3-widget-install-${width}.png` });
  }
  const denied = await page.context().newPage();
  const policyErrors = [];
  denied.on('console', message => {
    if (message.type() === 'error') policyErrors.push(message.text());
  });
  await denied.goto('http://127.0.0.1:8800/widget_install_site.html');
  if (await denied.locator('iframe[data-loomrise-widget]').count()) {
    throw new Error('An origin outside the allowlist must not receive an injected Widget');
  }
  await denied.evaluate(() => {
    const frame = document.createElement('iframe');
    frame.src = 'http://127.0.0.1:8798/widget/course-demo/widget-entry';
    document.body.append(frame);
  });
  await denied.waitForTimeout(250);
  if (!policyErrors.some(message => message.includes('frame-ancestors'))) {
    throw new Error('A disallowed parent origin must be blocked by the Widget frame policy');
  }
  await denied.close();
  await visitorContext.close();
  const result = {
    separateVisitorSessions: true,
    crossContextReadsAndWritesDenied: true,
    loaderOrigin: await frame.getAttribute('src'),
    visitorMessageVisibleInInbox: true,
    humanReplyReturnedToWidget: true,
    disallowedOriginBlocked: true,
    viewports: [1440, 390],
    pageErrors: errors,
  };
  await inbox.close();
  if (errors.length) throw new Error(errors.join('\n'));
  return result;
}
