async (page) => {
  const root = `${new URL(page.url()).origin}/`;
  const origin = new URL(root).origin;
  const check = (condition, message) => { if (!condition) throw new Error(message); };
  let releaseA;
  const delayedA = new Promise(resolve => { releaseA = resolve; });
  let agentA;
  let agentB;
  let requestedA = false;
  let requestedB = false;
  let markARequested;
  let markBRequested;
  let markAResponseFulfilled;
  const aRequestStarted = new Promise(resolve => { markARequested = resolve; });
  const bRequestStarted = new Promise(resolve => { markBRequested = resolve; });
  const aResponseFulfilled = new Promise(resolve => { markAResponseFulfilled = resolve; });
  const requests = [];
  const saves = [];
  const candidates = new Map();
  const configFor = id => ({
    persona: { name: id, goal: `服务目标 ${id}`, audience: '虚构访客', greeting: '你好', scope: '授权资料', fallback: '转人工', fields: {} },
    units: [], g0_gates: [], hard_rules: [], task_blueprints: [],
  });
  const fulfill = (route, result, status = 200) => route.fulfill({
    status,
    headers: { 'access-control-allow-origin': origin },
    contentType: 'application/json',
    body: JSON.stringify({ schema_version: 'config-api-v1', ok: true, result }),
  });

  await page.addInitScript(() => {
    const responseJson = Response.prototype.json;
    window.__r1ParsedDraftAgents = [];
    Response.prototype.json = async function (...args) {
      const value = await responseJson.apply(this, args);
      if (value?.result?.agent_id && value?.result?.config) {
        window.__r1ParsedDraftAgents.push(value.result.agent_id);
      }
      return value;
    };
  });

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.route('http://127.0.0.1:8766/api/configuration**', async route => {
    const request = route.request();
    if (request.method() === 'OPTIONS') {
      await route.fulfill({
        status: 204,
        headers: {
          'access-control-allow-origin': origin,
          'access-control-allow-methods': 'GET, POST, OPTIONS',
          'access-control-allow-headers': 'content-type',
        },
      });
      return;
    }
    if (request.method() === 'GET') {
      await fulfill(route, { schema_version: 'config-api-v1', ok: true });
      return;
    }
    const { action, payload } = request.postDataJSON();
    requests.push({ action, agentId: payload.agent_id || null });
    if (action === 'draft.get' && payload.agent_id === agentA) {
      requestedA = true;
      markARequested();
      await delayedA;
      await fulfill(route, { agent_id: agentA, revision: 1, base_version_id: 'v1', config: configFor(agentA) });
      markAResponseFulfilled();
      return;
    }
    if (action === 'draft.get' && payload.agent_id === agentB) {
      requestedB = true;
      markBRequested();
      await fulfill(route, { agent_id: agentB, revision: 1, base_version_id: 'v1', config: configFor(agentB) });
      return;
    }
    if (action === 'stable.list') { await fulfill(route, { items: [] }); return; }
    if (action === 'candidate.list') { await fulfill(route, { items: [...candidates.values()] }); return; }
    if (action === 'draft.save') {
      saves.push(payload);
      await fulfill(route, { agent_id: payload.agent_id, revision: payload.expected_revision + 1, base_version_id: 'v1', config: payload.config, diff: [] });
      return;
    }
    if (action === 'candidate.freeze') {
      const candidate = candidates.get(payload.idempotency_key) || {
        candidate_id: `cp_${candidates.size + 1}`, source_revision: payload.expected_revision,
        config: configFor(payload.agent_id), diff: [], status: 'frozen',
      };
      candidates.set(payload.idempotency_key, candidate);
      await fulfill(route, candidate);
      return;
    }
    throw new Error(`unexpected configuration action: ${action}`);
  });

  try {
    await page.goto(`${root}?r1-switch-check=1#/agents`);
    ({ agentA, agentB } = await page.evaluate(() => {
      const { store } = window.__loomriseDemo;
      const first = store.state.agents[0].id;
      store.dispatch('create', { name: '并发切换测试专家' });
      const second = store.currentAgent().id;
      store.dispatch('select-agent', { id: first });
      store.dispatch('navigate', { page: 'configuration', section: 'r1-server' });
      return { agentA: first, agentB: second };
    }));
    await page.waitForFunction(() => location.hash.includes('section=r1-server'));
    await aRequestStarted;
    check(requestedA, '切换前没有启动专家 A 的延迟配置读取');

    await page.locator('#sidebar-agent').selectOption(agentB);
    await page.waitForFunction(expected => window.__loomriseDemo.store.state.selectedAgentId === expected, agentB);
    await bRequestStarted;
    const requestedBWhileAWasPending = requestedB;
    releaseA();
    const switchState = await page.evaluate(() => ({
      selectedAgentId: window.__loomriseDemo.store.state.selectedAgentId,
      page: window.__loomriseDemo.store.state.ui.page,
      section: window.__loomriseDemo.store.state.ui.section,
      hash: location.hash,
    }));
    check(requestedBWhileAWasPending, `专家 A 仍在读取时切换到 B，没有为 B 发起新的配置读取：${JSON.stringify({ switchState, requests })}`);

    await aResponseFulfilled;
    await page.waitForFunction(expected => window.__r1ParsedDraftAgents.includes(expected), agentA);
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const goal = page.locator('[data-r1-bind="persona.goal"]');
    check(await goal.inputValue() === `服务目标 ${agentB}`, '旧专家 A 的延迟响应覆盖了专家 B 的工作面');
    await goal.fill('只修改专家 B');
    await page.locator('[data-action="r1-save"]').click();
    check(saves.length === 1, '编辑后没有提交配置草稿');
    check(saves[0].agent_id === agentB, '编辑专家 B 的页面却向另一专家提交了草稿');
    check(saves[0].config.persona.goal === '只修改专家 B', '提交没有保留专家 B 的编辑内容');
    check(!saves.some(payload => payload.agent_id === agentA), '切换后仍有写入落到专家 A');
    return { checks: ['A 请求延迟时切换 B 会启动 B 的新读取', 'A 迟到响应不会覆盖 B 的配置工作面', '编辑和保存只提交到 B'], requestedA, requestedB, saves };
  } finally {
    releaseA();
  }
}
