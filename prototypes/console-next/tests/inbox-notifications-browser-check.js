async page => {
  const check = (value, message) => { if (!value) throw new Error(message); };
  const origin = await page.evaluate(() => window.__LOOMRISE_CONFIG_API__ || 'http://127.0.0.1:8791');
  const diagnostics = { pageErrors: [], consoleErrors: [] };
  const reads = [];
  const acknowledgements = [];
  const eventProcessingOrder = [];
  let activeConsumerId = null;
  page.on('pageerror', error => diagnostics.pageErrors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') diagnostics.consoleErrors.push(message.text()); });
  page.on('request', request => {
    if (!request.url().endsWith('/api/customer-service') || request.method() !== 'POST') return;
    const value = request.postDataJSON();
    if (value.action === 'inbox.read') reads.push(value.payload);
    if (value.action === 'inbox.consumer.cursor') {
      activeConsumerId = value.payload.consumer_id;
    }
    if (['inbox.list', 'inbox.messages', 'inbox.read', 'inbox.consumer.cursor', 'inbox.consumer.ack'].includes(value.action)) {
      eventProcessingOrder.push(value.action);
    }
    if (value.action === 'inbox.consumer.ack') {
      acknowledgements.push(value.payload);
      eventProcessingOrder.push(`ack:${value.payload.through_sequence}`);
    }
  });
  await page.addInitScript(() => {
    window.__notificationStub = { permission: 'default', next: 'denied', requests: 0, notices: [], fail: false };
    window.Notification = class {
      static get permission() { return window.__notificationStub.permission; }
      static async requestPermission() {
        const stub = window.__notificationStub; stub.requests += 1; stub.permission = stub.next; return stub.permission;
      }
      constructor(title, options) {
        if (window.__notificationStub.fail) throw new Error('fixture display unavailable');
        this.title = title; this.options = options; this.close = () => {};
        window.__notificationStub.notices.push(this);
      }
    };
    const nativeSetInterval = window.setInterval.bind(window);
    window.setInterval = (callback, delay, ...args) => delay === 3000
      ? 0 : nativeSetInterval(callback, delay, ...args);
  });
  const api = (action, payload = {}) => page.evaluate(async ({ action, payload, origin }) => {
    const response = await fetch(`${origin}/api/customer-service`, { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action, payload }) });
    const value = await response.json();
    if (!response.ok || !value.ok) throw new Error(value.error?.message || action);
    return value.result;
  }, { action, payload: { agent_id: 'course-demo', ...payload }, origin });
  const widget = (action, payload) => page.evaluate(async ({ action, payload, origin }) => {
    const response = await fetch(`${origin}/api/customer-service`, { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action, payload }) });
    const value = await response.json(); if (!value.ok) throw new Error(value.error?.message || action); return value.result;
  }, { action, payload, origin });
  const list = () => api('inbox.list');
  const consumerCursor = consumerId => api('inbox.consumer.cursor', { consumer_id: consumerId });
  const waitForConsumerRequest = target => target.waitForRequest(request => {
    try { return request.postDataJSON()?.action === 'inbox.consumer.cursor'; }
    catch { return false; }
  });
  const thread = id => page.locator('#list .conversation').filter({ hasText: id });
  const refresh = () => page.getByRole('button', { name: '刷新', exact: true }).click();
  const notices = () => page.evaluate(() => window.__notificationStub.notices.length);
  const waitRead = async (id, sequence) => {
    await page.waitForFunction(async ({ origin, id, sequence }) => {
      const response = await fetch(`${origin}/api/customer-service`, { method: 'POST',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: 'inbox.list', payload: { agent_id: 'course-demo' } }) });
      const value = await response.json();
      return value.result.items.find(item => item.conversation_id === id)?.read_sequence >= sequence;
    }, { origin, id, sequence });
  };
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto(`${origin}/inbox/course-demo`);
  await page.getByLabel('新访客消息提醒', { exact: true }).waitFor({ state: 'attached', timeout: 5000 });
  await page.waitForFunction(() => Object.keys(sessionStorage).some(key => key.endsWith(':consumer')));
  const originalConsumerId = await page.evaluate(() => {
    const key = Object.keys(sessionStorage).find(value => value.endsWith(':consumer'));
    return key ? sessionStorage.getItem(key) : null;
  });
  const copiedSession = await page.evaluate(() => Object.fromEntries(
    Object.keys(sessionStorage).map(key => [key, sessionStorage.getItem(key)])));
  const reloadCursorRequest = waitForConsumerRequest(page);
  await page.reload();
  const reloadedConsumerId = (await reloadCursorRequest).postDataJSON().payload.consumer_id;
  check(reloadedConsumerId === originalConsumerId, '同标签页刷新更换了持久化消费者 ID');
  const duplicate = await page.context().newPage();
  const duplicateCursorRequest = waitForConsumerRequest(duplicate);
  await duplicate.addInitScript(entries => {
    for (const [key, value] of Object.entries(entries)) sessionStorage.setItem(key, value);
  }, copiedSession);
  await duplicate.goto(`${origin}/inbox/course-demo`);
  const duplicateConsumerId = (await duplicateCursorRequest).postDataJSON().payload.consumer_id;
  check(duplicateConsumerId !== originalConsumerId, '复制的 sessionStorage 复用了另一个标签页的消费者 ID');
  await duplicate.close();
  await page.locator('#notificationSettings summary').click();
  check(await page.evaluate(() => window.__notificationStub.requests) === 0, '页面加载自动请求通知权限');
  await page.getByLabel('新访客消息提醒', { exact: true }).check();
  await page.getByLabel('当前待人工提醒', { exact: true }).check();
  await page.getByRole('button', { name: '保存个人提醒偏好', exact: true }).click();
  await page.getByText('个人提醒偏好已保存。', { exact: true }).waitFor();
  await page.evaluate(() => {
    for (const key of Object.keys(sessionStorage)) {
      if (key.endsWith(':cursor') || key.endsWith(':consumer')) sessionStorage.removeItem(key);
    }
  });
  const backlog = await api('widget.open', { entry_id: 'contact-entry' });
  await widget('widget.send', { conversation_id: backlog.conversation_id, visitor_token: backlog.visitor_token,
    text: 'PRIVATE-HISTORICAL-访客信息', request_human: false, message_id: crypto.randomUUID() });
  await page.reload();
  await page.waitForFunction(() => Object.keys(sessionStorage).some(key => key.endsWith(':consumer')));
  await page.locator('#notificationSettings summary').click();
  check(await page.getByLabel('新访客消息提醒', { exact: true }).isChecked()
    && await page.getByLabel('当前待人工提醒', { exact: true }).isChecked(), '个人偏好刷新后丢失');
  check(await page.evaluate(() => window.__notificationStub.requests) === 0, '偏好恢复自动申请系统权限');
  await page.getByRole('button', { name: '开启本页浏览器提醒', exact: true }).click();
  await page.getByText('浏览器未允许提醒，站内未读仍可用。', { exact: true }).waitFor();
  await page.evaluate(() => { window.__notificationStub.permission = 'default'; window.__notificationStub.next = 'granted'; });
  await page.getByRole('button', { name: '开启本页浏览器提醒', exact: true }).click();
  await page.getByText('本页浏览器提醒已开启；仅页面开启时检查。', { exact: true }).waitFor();
  check(await notices() === 0, '开启提醒重发了历史积压');

  const cold = await api('widget.open', { entry_id: 'contact-entry' });
  await widget('widget.send', { conversation_id: cold.conversation_id, visitor_token: cold.visitor_token,
    text: 'PRIVATE-COLD-访客信息', request_human: false, message_id: crypto.randomUUID() });
  await page.waitForFunction(() => window.__notificationStub.notices.length === 1);
  check(await page.evaluate(id => {
    const notice = window.__notificationStub.notices[0];
    return notice.title === '有新的访客消息' && notice.options.tag.includes(id);
  }, cold.conversation_id), '无游标冷启动后的第一条新消息未提醒');

  const first = await api('widget.open', { entry_id: 'contact-entry' });
  const second = await api('widget.open', { entry_id: 'contact-entry' });
  const transient = await api('widget.open', { entry_id: 'contact-entry' });
  await widget('widget.send', { conversation_id: first.conversation_id, visitor_token: first.visitor_token,
    text: 'PRIVATE-FIRST-访客信息', request_human: true, message_id: crypto.randomUUID() });
  await widget('widget.send', { conversation_id: second.conversation_id, visitor_token: second.visitor_token,
    text: 'PRIVATE-SECOND-访客信息', request_human: false, message_id: crypto.randomUUID() });
  await widget('widget.send', { conversation_id: transient.conversation_id, visitor_token: transient.visitor_token,
    text: 'PRIVATE-TRANSIENT-访客信息', request_human: true, message_id: crypto.randomUUID() });
  const transientClaim = await api('inbox.claim', { conversation_id: transient.conversation_id });
  await api('inbox.release', { conversation_id: transient.conversation_id,
    generation: transientClaim.occupancy_generation });
  await refresh();
  await thread(first.conversation_id).getByText('未读 1', { exact: true }).waitFor();
  await thread(first.conversation_id).getByText('当前待人工接管', { exact: false }).waitFor();
  await thread(transient.conversation_id).getByText('自动接待', { exact: false }).waitFor();
  check(reads.length === 0, '列表或提醒自动标记已读');
  await page.waitForFunction(() => window.__notificationStub.notices.length === 4);
  check(await notices() === 4, '事件游标未提醒新消息或轮询间发生后已结束的接管请求');
  check(await page.evaluate(ids => ids.every(({ id, title }) => {
    const notice = window.__notificationStub.notices.find(item => item.options.tag.includes(id));
    return notice?.title === title;
  }), [
    { id: first.conversation_id, title: '当前有会话等待人工接管' },
    { id: second.conversation_id, title: '有新的访客消息' },
    { id: transient.conversation_id, title: '当前有会话等待人工接管' },
  ]), '同事务的接管提醒未优先于普通访客消息');
  check(await page.evaluate(() => window.__notificationStub.notices.every(item =>
    !JSON.stringify({ title: item.title, body: item.options.body }).includes('PRIVATE-'))), '提醒泄露了访客正文');
  const beforeRepeated = await notices();
  await refresh(); await refresh();
  check(await notices() === beforeRepeated, '重复轮询重复提醒');
  await page.evaluate(id => window.__notificationStub.notices.find(item => item.options.tag.includes(id)).onclick(), first.conversation_id);
  await waitRead(first.conversation_id, 1);
  check((await list()).items.find(item => item.conversation_id === first.conversation_id).state !== 'human', '通知点击自动接管');

  let releaseDelayed;
  const released = new Promise(resolve => { releaseDelayed = resolve; });
  let signalDelay;
  const delayed = new Promise(resolve => { signalDelay = resolve; });
  let delayOnce = true;
  await page.route(`${origin}/api/customer-service`, async route => {
    const body = route.request().postDataJSON();
    if (delayOnce && body.action === 'inbox.messages' && body.payload.conversation_id === first.conversation_id) {
      delayOnce = false; const response = await route.fetch(); signalDelay(); await released; return route.fulfill({ response });
    }
    return route.continue();
  });
  await widget('widget.send', { conversation_id: first.conversation_id, visitor_token: first.visitor_token,
    text: 'PRIVATE-FIRST-LATE', request_human: false, message_id: crypto.randomUUID() });
  await thread(first.conversation_id).click(); await delayed;
  await thread(second.conversation_id).click();
  await page.locator('#messages .message').filter({ hasText: 'PRIVATE-SECOND-访客信息' }).waitFor();
  releaseDelayed();
  await waitRead(second.conversation_id, 1);
  check(!(await page.locator('#messages').textContent()).includes('PRIVATE-FIRST-LATE'), '旧线程迟到响应覆盖新线程');
  check((await list()).items.find(item => item.conversation_id === first.conversation_id).read_sequence === 1, '旧线程迟到响应标记未渲染消息已读');
  await page.unroute(`${origin}/api/customer-service`);

  await page.getByRole('textbox', { name: '回复内容', exact: true }).fill('保留的人工回复草稿');
  await widget('widget.send', { conversation_id: second.conversation_id, visitor_token: second.visitor_token,
    text: 'PRIVATE-SECOND-NEW', request_human: false, message_id: crypto.randomUUID() });
  await refresh();
  await page.locator('#messages .message').filter({ hasText: 'PRIVATE-SECOND-NEW' }).waitFor();
  await waitRead(second.conversation_id, 2);
  check(await page.getByRole('textbox', { name: '回复内容', exact: true }).inputValue() === '保留的人工回复草稿', '轮询覆盖回复输入');

  await widget('widget.send', { conversation_id: second.conversation_id, visitor_token: second.visitor_token,
    text: '用于验证历史滚动的虚构记录。\n'.repeat(80), request_human: false, message_id: crypto.randomUUID() });
  await refresh();
  await waitRead(second.conversation_id, 3);
  check(await page.locator('#messages').evaluate(element => element.scrollHeight > element.clientHeight), '历史滚动样本未超过可视区域');
  await page.locator('#messages').evaluate(element => { element.scrollTop = 0; });
  await widget('widget.send', { conversation_id: second.conversation_id, visitor_token: second.visitor_token,
    text: '历史阅读期间到达的新消息', request_human: false, message_id: crypto.randomUUID() });
  await refresh();
  await page.locator('#messages .message').filter({ hasText: '历史阅读期间到达的新消息' }).waitFor({ state: 'attached' });
  check(await page.locator('#messages').evaluate(element => element.scrollTop <= 1), '轮询把正在阅读的历史强制滚到底部');

  const pendingAction = async (action, selector, label) => {
    let release, signal;
    const held = new Promise(resolve => { release = resolve; });
    const reached = new Promise(resolve => { signal = resolve; });
    const handler = async route => {
      if (route.request().postDataJSON().action !== action) return route.continue();
      signal(); await held; return route.continue();
    };
    await page.route(`${origin}/api/customer-service`, handler);
    const completed = page.waitForResponse(response => response.request().postDataJSON()?.action === action);
    await page.locator(selector).click(); await reached;
    try {
      const refreshed = page.waitForResponse(response => response.request().postDataJSON()?.action === 'inbox.messages');
      await refresh(); await refreshed;
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      check(await page.locator(selector).isDisabled(), `轮询重新启用正在提交的${label}`);
    } finally {
      release();
      const response = await completed;
      check((await response.json()).ok, `${label}未通过真实后端`);
      await page.unroute(`${origin}/api/customer-service`, handler);
    }
  };
  await page.locator('.upload summary').click();
  const uploadName = `r3-inbox-busy-${crypto.randomUUID().slice(0, 8)}.txt`;
  await page.locator('#file').setInputFiles({ name: uploadName, mimeType: 'text/plain',
    buffer: Buffer.from('原创虚构的 Inbox 请求状态验证资料。') });
  await pendingAction('material.create', '#upload', '上传');
  await page.locator('#material option').filter({ hasText: uploadName }).waitFor({ state: 'attached' });
  await page.locator('#material').selectOption({ label: `${uploadName} · v1 · 原件` });
  await pendingAction('material.process', '#processMaterial', '文件处理');
  await pendingAction('inbox.claim', '#claim', '接管');
  await page.waitForFunction(() => !document.querySelector('#send').disabled);
  await page.getByRole('textbox', { name: '回复内容', exact: true }).fill('请求状态验证的人工回复');
  await pendingAction('inbox.reply', '#send', '回复');
  await page.getByRole('textbox', { name: '回复内容', exact: true }).fill('保留的人工回复草稿');
  await pendingAction('inbox.send_material', '#sendMaterial', '发送物料');
  await page.locator('.upload summary').click();

  let failPreference = true;
  await page.route(`${origin}/api/customer-service`, async route => {
    if (failPreference && route.request().postDataJSON().action === 'inbox.preferences.save') {
      failPreference = false; return route.abort('failed');
    }
    return route.continue();
  });
  await page.getByLabel('当前待人工提醒', { exact: true }).uncheck();
  await page.getByRole('button', { name: '保存个人提醒偏好', exact: true }).click();
  await page.getByText('偏好保存失败，原偏好与当前回复内容已保留。', { exact: true }).waitFor();
  check(await page.getByLabel('当前待人工提醒', { exact: true }).isChecked()
    && (await api('inbox.preferences')).handoff, '保存失败覆盖了原个人偏好');
  check(await page.getByRole('textbox', { name: '回复内容', exact: true }).inputValue() === '保留的人工回复草稿', '偏好失败清空回复草稿');
  await page.unroute(`${origin}/api/customer-service`);

  const durableConsumerId = activeConsumerId;
  const latestEvents = await api('inbox.events', { after_sequence: 0, limit: 100 });
  await page.waitForFunction(async ({ origin, consumerId, cursor }) => {
    const response = await fetch(`${origin}/api/customer-service`, { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
        action: 'inbox.consumer.cursor', payload: { agent_id: 'course-demo', consumer_id: consumerId },
      }) });
    const value = await response.json(); return value.result?.cursor >= cursor;
  }, { origin, consumerId: durableConsumerId, cursor: latestEvents.next_cursor });

  await thread(second.conversation_id).click();
  await page.locator('#messages .message').filter({ hasText: 'PRIVATE-SECOND-NEW' }).waitFor();
  const readFailureTargetId = await page.locator('#list .conversation[aria-current="true"]')
    .getAttribute('data-conversation-id');
  check(readFailureTargetId === second.conversation_id, '刷新失败回归未选中拦截目标会话');
  let failRead = true;
  let signalFailedRead;
  const failedReadStarted = new Promise(resolve => { signalFailedRead = resolve; });
  await page.route(`${origin}/api/customer-service`, async route => {
    const body = route.request().postDataJSON();
    if (failRead && body.action === 'inbox.messages' && body.payload.conversation_id === readFailureTargetId) {
      failRead = false; signalFailedRead(); return route.abort('failed');
    }
    return route.continue();
  });
  await refresh();
  await failedReadStarted;
  check((await page.locator('#messages').textContent()).includes('PRIVATE-SECOND-NEW')
    && await page.getByRole('textbox', { name: '回复内容', exact: true }).inputValue() === '保留的人工回复草稿', '读取失败清空对话或输入');
  await page.unroute(`${origin}/api/customer-service`);

  check(typeof durableConsumerId === 'string' && durableConsumerId.length <= 128,
    '浏览器没有持久化有界 Inbox 消费者 ID');
  await thread(second.conversation_id).click();
  await page.locator('#messages .message').filter({ hasText: 'PRIVATE-SECOND-NEW' }).waitFor();
  const projectionTargetId = await page.locator('#list .conversation[aria-current="true"]')
    .getAttribute('data-conversation-id');
  check(projectionTargetId === second.conversation_id, '投影失败回放未选中拦截目标会话');
  const beforeProjectionEvents = await api('inbox.events', { after_sequence: 0, limit: 100 });
  await page.waitForFunction(async ({ origin, consumerId, cursor }) => {
    const response = await fetch(`${origin}/api/customer-service`, { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
        action: 'inbox.consumer.cursor', payload: { agent_id: 'course-demo', consumer_id: consumerId },
      }) });
    const value = await response.json(); return value.result?.cursor >= cursor;
  }, { origin, consumerId: durableConsumerId, cursor: beforeProjectionEvents.next_cursor });
  const beforeFailedProjection = await consumerCursor(durableConsumerId);
  eventProcessingOrder.length = 0;
  let failProjection = true;
  let releaseProjection;
  const projectionHeld = new Promise(resolve => { releaseProjection = resolve; });
  let signalProjectionRetry;
  const projectionRetryStarted = new Promise(resolve => { signalProjectionRetry = resolve; });
  await page.route(`${origin}/api/customer-service`, async route => {
    const body = route.request().postDataJSON();
    if (body.action !== 'inbox.messages' || body.payload.conversation_id !== projectionTargetId) {
      return route.continue();
    }
    if (failProjection) {
      failProjection = false;
      eventProcessingOrder.push('projection-failed');
      return route.abort('failed');
    }
    eventProcessingOrder.push('projection-retry-started');
    signalProjectionRetry();
    await projectionHeld;
    const response = await route.fetch();
    eventProcessingOrder.push('projection-refreshed');
    return route.fulfill({ response });
  });
  await widget('widget.send', { conversation_id: second.conversation_id, visitor_token: second.visitor_token,
    text: 'PRIVATE-ACK-RETRY', request_human: false, message_id: crypto.randomUUID() });
  await projectionRetryStarted;
  const whileProjectionBlocked = await consumerCursor(durableConsumerId);
  check(whileProjectionBlocked.cursor === beforeFailedProjection.cursor,
    `Inbox 详情刷新完成前已推进消费回执: ${JSON.stringify({ before: beforeFailedProjection.cursor,
      whileBlocked: whileProjectionBlocked.cursor,
      acknowledgements: acknowledgements.filter(item => item.consumer_id === durableConsumerId),
      eventProcessingOrder })}`);
  check(!acknowledgements.some(value => value.consumer_id === durableConsumerId
    && value.through_sequence === beforeFailedProjection.cursor + 1), '处理失败后仍已确认事件');
  releaseProjection();
  await page.waitForFunction(async ({ origin, consumerId, cursor }) => {
    const response = await fetch(`${origin}/api/customer-service`, { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
        action: 'inbox.consumer.cursor', payload: { agent_id: 'course-demo', consumer_id: consumerId },
      }) });
    const value = await response.json(); return value.result?.cursor >= cursor;
  }, { origin, consumerId: durableConsumerId, cursor: beforeFailedProjection.cursor + 1 });
  await page.unroute(`${origin}/api/customer-service`);
  const afterProjectionAck = await consumerCursor(durableConsumerId);
  const failedProjectionIndex = eventProcessingOrder.lastIndexOf('projection-failed');
  const refreshedProjectionIndex = eventProcessingOrder.lastIndexOf('projection-refreshed');
  const acknowledgedIndex = eventProcessingOrder.lastIndexOf(`ack:${beforeFailedProjection.cursor + 1}`);
  check(failedProjectionIndex >= 0 && refreshedProjectionIndex > failedProjectionIndex
    && acknowledgedIndex > refreshedProjectionIndex,
  `事件回执时序不符: ${JSON.stringify({ before: beforeFailedProjection.cursor, after: afterProjectionAck.cursor,
    acknowledgements: acknowledgements.filter(item => item.consumer_id === durableConsumerId),
    failedProjectionIndex, refreshedProjectionIndex, acknowledgedIndex, eventProcessingOrder })}`);

  await page.evaluate(() => { window.__notificationStub.fail = true; });
  await widget('widget.send', { conversation_id: first.conversation_id, visitor_token: first.visitor_token,
    text: 'PRIVATE-DISPLAY-FAILURE', request_human: false, message_id: crypto.randomUUID() });
  await refresh();
  await page.getByText('浏览器提醒未能显示，站内未读仍可用。', { exact: true }).waitFor();
  await thread(first.conversation_id).getByText('未读 2', { exact: true }).waitFor();
  await page.locator('#messages').evaluate(element => { element.scrollTop = element.scrollHeight; });
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 960 });
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${width}px Inbox 横向溢出`);
    await page.screenshot({ path: `output/playwright/r3-inbox-notifications-${width}.png`, fullPage: true });
  }
  const unsupported = await page.context().newPage();
  unsupported.on('pageerror', error => diagnostics.pageErrors.push(error.message));
  await unsupported.addInitScript(() => { Object.defineProperty(window, 'Notification', { value: undefined }); });
  await unsupported.goto(`${origin}/inbox/course-demo`);
  await unsupported.locator('#notificationSettings summary').click();
  await unsupported.getByText('此浏览器不支持本页提醒，站内未读仍可用。', { exact: true }).waitFor();
  await unsupported.locator('#list .conversation').first().click();
  await unsupported.locator('#messages .message').first().waitFor();
  await unsupported.close();
  check(diagnostics.pageErrors.length === 0, JSON.stringify(diagnostics.pageErrors));
  return { result: 'pass', widths: [1440, 390], persistedPreferences: true, explicitPermission: true,
    visitorUnread: true, renderBeforeRead: true, staleThreadIgnored: true, activeThreadRefresh: true,
    consumerReloadStable: true, clonedTabConsumerUnique: true, projectionAckAfterRefresh: true,
    notificationClickDoesNotClaim: true, privateContentExcluded: true, unchangedPollDeduped: true,
    failurePreservesInput: true, historyScrollPreserved: true, failedPreferencePreserved: true,
    pendingActionsStayDisabled: true, lostCursorBaseline: true, handoffPriority: true,
    permissionAndDisplayStubOnly: true, diagnostics };
}
