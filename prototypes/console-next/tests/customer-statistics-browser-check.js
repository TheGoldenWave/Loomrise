async page => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const check = (value, message) => { if (!value) throw new Error(message); };
  const apiOrigin = await page.evaluate(() => window.__LOOMRISE_CONFIG_API__);
  check(Boolean(apiOrigin), 'runner must inject the local configuration fixture origin');
  const windowFrom = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
  const windowTo = new Date(Date.now() + 60 * 1000).toISOString();
  await page.goto('http://127.0.0.1:18765/?r3-statistics-check=1');
  const seeded = await page.evaluate(async ({ apiOrigin, windowFrom, windowTo }) => {
    const call = async (action, payload) => {
      const response = await fetch(`${apiOrigin}/api/customer-service`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, payload }),
      });
      const body = await response.json();
      if (!response.ok || !body.ok) throw new Error(body.error?.message || `${action} failed`);
      return body.result;
    };
    const baseline = await call('customer.statistics', { agent_id: 'course-demo' });
    const baselineText = await call('customer.statistics', { agent_id: 'course-demo', from: windowFrom, to: windowTo, channel: 'text' });
    const conversation = await call('widget.open', { agent_id: 'course-demo', entry_id: 'widget-entry' });
    await call('widget.send', { conversation_id: conversation.conversation_id,
      visitor_token: conversation.visitor_token, text: '体验课多少钱？' });
    const after = await call('customer.statistics', { agent_id: 'course-demo' });
    const afterText = await call('customer.statistics', { agent_id: 'course-demo', from: windowFrom, to: windowTo, channel: 'text' });
    const voice = await call('customer.statistics', { agent_id: 'course-demo', from: windowFrom, to: windowTo, channel: 'voice' });
    return {
      conversation_id: conversation.conversation_id,
      conversation_delta: after.conversation_count - baseline.conversation_count,
      message_delta: after.message_count - baseline.message_count,
      conversation_count: after.conversation_count,
      message_count: after.message_count,
      request_delta: afterText.reception.request_count - baselineText.reception.request_count,
      run_delta: afterText.reception.run_count - baselineText.reception.run_count,
      voice_run_count: voice.reception.run_count,
      voice_supported: voice.reception.coverage.requested_channel_supported,
    };
  }, { apiOrigin, windowFrom, windowTo });
  check(Boolean(seeded.conversation_id), 'fixture 未能创建虚构访客会话');
  check(seeded.conversation_delta === 1, 'fixture 会话增量应为 1');
  check(seeded.message_delta >= 1, 'fixture 至少应保存一条访客消息');
  check(seeded.request_delta === 1, '时间窗文字请求增量应为 1');
  check(seeded.run_delta === 1, '时间窗文字 Run 增量应为 1');
  check(seeded.voice_run_count === 0 && seeded.voice_supported === false, '语音空结果必须标记来源未覆盖');
  let shortWindowDelayed = false;
  await page.route(`${apiOrigin}/api/customer-service`, async route => {
    const body = route.request().postDataJSON();
    if (body.action === 'customer.statistics' && body.payload?.from && body.payload?.to
        && Date.parse(body.payload.to) - Date.parse(body.payload.from) < 2 * 24 * 60 * 60 * 1000) {
      shortWindowDelayed = true;
      await new Promise(resolve => setTimeout(resolve, 700));
    }
    await route.continue();
  });
  await page.goto('http://127.0.0.1:18765/#/inbox?agent=course-demo');
  await page.getByRole('heading', { name: '人工会话' }).waitFor();
  await page.getByRole('button', { name: '客服统计' }).click();
  await page.getByRole('heading', { name: '客服统计' }).waitFor();
  await page.locator('[data-statistics-scope]').waitFor();
  const totals = page.locator('.section').filter({ has: page.getByRole('heading', { name: '当前累计记录', exact: true }) }).locator('.detail-list dd');
  check(await totals.nth(0).innerText() === String(seeded.conversation_count), '会话累计数与服务端记录不符');
  check(await totals.nth(1).innerText() === String(seeded.message_count), '消息累计数与服务端记录不符');
  check((await page.locator('[data-statistics-scope]').innerText()).includes('全部保留接待记录'), '默认范围应显示全部保留记录');
  check(await page.getByText('服务端接待处理区间', { exact: true }).count() === 1, '服务端时延分区未显示');

  const period = page.locator('[data-customer-statistics-filter="period"]');
  await period.selectOption('24h');
  await new Promise(resolve => setTimeout(resolve, 80));
  await period.selectOption('7d');
  await page.waitForFunction(() => {
    const text = document.querySelector('[data-statistics-scope]')?.textContent || '';
    const match = text.match(/窗口 \[([^,]+), ([^)]+)\)/);
    return match && Date.parse(match[2]) - Date.parse(match[1]) > 6 * 24 * 60 * 60 * 1000;
  });
  await new Promise(resolve => setTimeout(resolve, 800));
  const finalScope = await page.locator('[data-statistics-scope]').innerText();
  const finalWindow = finalScope.match(/窗口 \[([^,]+), ([^)]+)\)/);
  check(shortWindowDelayed && finalWindow && Date.parse(finalWindow[2]) - Date.parse(finalWindow[1]) > 6 * 24 * 60 * 60 * 1000,
    '迟到的24小时响应覆盖了后续7天筛选');

  const channel = page.locator('[data-customer-statistics-filter="channel"]');
  await channel.selectOption('text');
  await page.waitForFunction(() => document.querySelector('[data-statistics-scope]')?.textContent.includes('文字'));
  await channel.selectOption('voice');
  await page.getByText('当前客服接待数据源尚未接入语音', { exact: false }).waitFor();
  check((await page.locator('[data-statistics-scope]').innerText()).includes('语音'), '语音筛选未回显服务端范围');
  await period.selectOption('all');
  await channel.selectOption('all');
  await page.waitForFunction(() => document.querySelector('[data-statistics-scope]')?.textContent.includes('全部保留接待记录'));
  await page.locator('.helper').filter({ hasText: '累计范围：当前专家全部保留记录' }).waitFor();
  await page.getByText('本机服务', { exact: true }).waitFor();
  for (const [width, height] of [[1440, 960], [390, 844]]) {
    await page.setViewportSize({ width, height });
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${width}px 页面横向溢出`);
    await page.screenshot({ path: `output/playwright/r3-customer-statistics-${width}.png` });
  }
  await page.unroute(`${apiOrigin}/api/customer-service`);
  await page.getByRole('button', { name: '会话收件箱' }).click();
  await page.getByRole('heading', { name: '人工会话' }).waitFor();
  check(errors.length === 0, errors.join('\n'));
  return { api: 'customer.statistics', fixtureDelta: { conversations: seeded.conversation_delta, messages: seeded.message_delta,
    requests: seeded.request_delta, runs: seeded.run_delta }, caveats: ['historical handoff and visitor delivery remain unknown', 'voice source coverage is unsupported'],
    viewports: [1440, 390], staleFilterResponseRejected: true, pageErrors: errors.length };
}
