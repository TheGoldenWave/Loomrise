async (page) => {
  // 仅向当前本地原型注入原创虚构夹具；不访问模型、渠道或外部业务。
  const root = 'http://127.0.0.1:8788/console-next/?v=console-optimization-20261015';
  const results = [], errors = [], layouts = [];
  const check = (value, message) => { if (!value) throw new Error(message); };
  const step = async (name, work) => { try { await work(); results.push(name); } catch (error) { throw new Error(`${name}: ${error.message}`); } };
  const dispatch = (action, data = {}) => page.evaluate(({ action, data }) => window.__loomriseDemo.store.dispatch(action, data), { action, data });
  const state = () => page.evaluate(() => window.__loomriseDemo.store.state);
  const go = async name => { await dispatch('navigate', { page: name }); await page.locator('main h1').waitFor(); };
  const mode = name => page.locator(`[data-collection-page="${name}"]`);
  const expectMode = async (name, expected) => check(await mode(name).getAttribute('data-collection-mode') === expected, `${name} 未进入 ${expected} 工作面`);
  const noOverflow = async label => {
    const metric = await page.evaluate(() => ({ width: innerWidth, height: innerHeight, documentWidth: document.documentElement.scrollWidth }));
    layouts.push({ label, ...metric });
    check(metric.documentWidth <= metric.width, `${label} 页面横向溢出：${metric.documentWidth}/${metric.width}`);
  };
  page.setDefaultTimeout(7000);
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(root);
  await page.waitForFunction(() => window.__loomriseDemo?.store);
  await Promise.all([page.waitForEvent('load'), page.evaluate(() => window.__loomriseDemo.reset())]);
  await page.waitForFunction(() => window.__loomriseDemo?.store);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.evaluate(() => {
    const store = window.__loomriseDemo.store, state = store.state;
    const agent = state.agents.find(item => item.id === 'course-demo');
    state.selectedAgentId = agent.id;
    agent.config.sources = [];
    store.dispatch('navigate', { page: 'overview' });
  });

  await step('四组导航完整、概览缺口唯一主动作且摘要默认折叠', async () => {
    check(JSON.stringify(await page.locator('.sidebar .nav-group-title').allTextContents()) === JSON.stringify(['配置与资料', '客服应用', '运行与验收', '版本与设置']), '不是已确认四组导航');
    const pages = ['agents', 'overview', 'configuration', 'knowledge', 'materials', 'inbox', 'widget', 'contact', 'trial', 'runs', 'cases', 'iterations', 'versions', 'connections', 'deployment'];
    for (const name of pages) check(await page.locator(`.sidebar [data-page="${name}"]`).count() === 1, `导航缺少或重复 ${name}`);
    check(await page.locator('.sidebar .nav-group > [data-page="overview"], .sidebar .nav-group > [data-page="configuration"]').count() === 0, '概览和配置仍是一级入口');
    check(await page.locator('.nav-subgroup[data-parent-page="agents"] [data-page]').count() === 2, '专家列表下未提供两个二级入口');
    check(await page.locator('.sidebar [data-page="agents"]').evaluate(node => node.classList.contains('has-active-child')), '专家列表未标示当前子页面');
    check(await page.locator('.breadcrumb [data-page="agents"]').count() === 1, '缺少返回专家列表的上下文入口');
    await page.locator('.nav-subgroup [data-page="configuration"]').click();
    check((await state()).ui.page === 'configuration', '二级专家配置入口不可达');
    await page.locator('.nav-subgroup [data-page="overview"]').click();
    check((await state()).ui.page === 'overview', '二级业务概览入口不可达');
    check(await page.locator('.next-step .btn-primary').count() === 1, '概览没有唯一缺口主动作');
    check(await page.locator('.next-step .btn-primary').getAttribute('data-page') === 'knowledge', '无资料时主动作未指向资料');
    check(await page.locator('.overview-summary[open]').count() === 0, '摘要未默认折叠');
    await page.locator('.next-step .btn-primary').click();
    check((await state()).ui.page === 'knowledge', '缺口主动作不能到达处理入口');
    await noOverflow('概览与资料入口 1440×900');
  });

  await step('配置首次定位固化，补齐缺口不跳模块且目录保持横排', async () => {
    await page.evaluate(() => {
      const store = window.__loomriseDemo.store;
      store.currentAgent().config.goal = '';
      store.state.ui.section = '';
      store.dispatch('navigate', { page: 'configuration' });
    });
    check((await state()).ui.section === 'service', '未首次定位服务缺口');
    check(await page.locator('.config-nav [data-module-status]').count() === 10, '十模块目录不完整');
    await page.locator('[data-bind="goal"]').fill('依据授权虚构资料回答问题，复杂问题转人工。');
    check((await state()).ui.section === 'service', '补齐目标后自动跳模块');
    check(await page.locator('[data-bind="goal"]').evaluate(node => node === document.activeElement), '编辑丢失输入焦点');
    const cells = await page.locator('.config-nav [data-module-status]').evaluateAll(nodes => nodes.map(node => ({ top: node.getBoundingClientRect().top, left: node.getBoundingClientRect().left })));
    check(cells[0].top === cells[1].top && cells[0].left < cells[1].left, '桌面目录退回纵向第三栏');
  });

  await page.evaluate(() => {
    const store = window.__loomriseDemo.store, state = store.state, agent = store.currentAgent();
    const time = '2026-10-15T01:00:00.000Z';
    agent.config.sources = ['FAQ', 'URL', 'File'].flatMap(type => Array.from({ length: 10 }, (_, index) => {
      const phase = index % 5;
      return { id: `optimization-${type}-${index}`, type, title: `专项${type}资料${index}`, question: `虚构专项问题${index}？`, answer: index === 0 ? '这是用于窄屏三行摘要与键盘展开的原创虚构解答。'.repeat(7) : index === 1 ? '短解答。' : '原创虚构内容，不能作真实业务承诺。'.repeat(index + 2), body: type === 'File' ? '原创虚构本地文件正文。' : '', filename: type === 'File' ? `fictional-${index}.txt` : '', url: type === 'URL' ? `https://example.invalid/fictional-${index}` : '', status: phase === 4 ? 'revoked' : phase === 1 ? 'received' : phase === 2 ? 'failed' : 'indexed', rights: phase !== 3, sourceRef: `fictional:optimization-${type}-${index}`, expires: '2099-12-31', version: 1, fictional: true, metadataOnly: type === 'URL' };
    }));
    state.runs = Array.from({ length: 3 }, (_, index) => ({ id: `optimization-run-${index}`, agentId: agent.id, input: `专项${index}访客输入`, answer: `详情答复证据${index}`, status: ['unknown', 'answered', 'failed'][index], revision: agent.revision, createdAt: time, sources: [{ id: 'optimization-FAQ-0', title: '历史来源证据', version: 1 }], resultEvidence: { generated: true, delivered: false, resolved: 'unknown' } }));
    state.cases = Array.from({ length: 3 }, (_, index) => ({ id: `optimization-case-${index}`, agentId: agent.id, title: `专项${index}案例`, input: `专项${index}固定输入`, expected: 'unknown', must: `必须显式说明未知${index}`, forbid: `禁止承诺金额${index}`, status: index === 0 ? 'pending' : 'reviewed', runId: `optimization-run-${index}`, createdAt: time }));
    state.proposals = Array.from({ length: 3 }, (_, index) => ({ id: `optimization-proposal-${index}`, agentId: agent.id, title: `专项${index}候选`, reason: `专项${index}资料不足依据`, status: 'pending', baseRevision: index === 0 ? agent.revision - 1 : agent.revision, createdAt: time, diff: [{ path: 'fallback', label: '资料外回复', before: `详情旧值${index}`, after: `详情新值${index}` }], evaluation: index === 2 ? 'fail' : null, comparison: [{ caseId: `optimization-case-${index}`, before: 'unknown', after: 'unknown', expected: 'unknown' }] }));
    state.connections = [{ id: 'simulation', name: '专项0脚本连接', provider: 'simulation', model: 'local-script', status: 'simulation', streaming: 'simulation', tools: 'simulation', cancel: 'simulation', createdAt: time }, { id: 'optimization-connection-1', name: '专项1失败连接', provider: 'compatible', model: 'fictional-model', status: 'failed', error: '虚构认证检查失败，请重新演示检查。', createdAt: time }, { id: 'optimization-connection-2', name: '专项2待检查连接', provider: 'compatible', model: 'fictional-model', status: 'pending', createdAt: time }];
    for (const ui of Object.values(state.ui.collections)) Object.assign(ui, { query: '', status: 'all', detailId: null, form: false });
    state.ui.search = ''; state.ui.sourceFilter = 'all'; state.ui.sourceTab = 'FAQ'; state.ui.sourceDetail = null; state.ui.sourceForm = false;
    store.dispatch('navigate', { page: 'runs' });
  });

  for (const name of ['runs', 'cases', 'iterations', 'connections']) {
    await step(`${name} 列表、详情、表单互斥，筛选与焦点恢复，空态及只读`, async () => {
      await go(name); await expectMode(name, 'list');
      check(await mode(name).locator('tbody tr').count() === 3, '摘要列表缺少记录');
      check(await mode(name).locator('form[data-form]').count() === 0, '表单挤在列表中');
      check(await mode(name).getByText(/详情旧值|必须显式说明未知|详情答复证据/).count() === 0, '完整证据混入首层列表');
      await mode(name).locator(`[data-ui-bind="collections.${name}.query"]`).fill('无匹配的专项检索词');
      check(await mode(name).getByText('没有匹配的记录', { exact: true }).isVisible(), '筛选空态不明确');
      await mode(name).locator('[data-action="collection-clear"]').first().click();
      check(await mode(name).locator('tbody tr').count() === 3, '清筛选没有恢复记录');
      await mode(name).locator(`[data-ui-bind="collections.${name}.query"]`).fill('专项');
      const statusControl = mode(name).locator(`[data-ui-bind="collections.${name}.status"]`);
      const value = name === 'iterations' ? 'stale' : await statusControl.locator('option').nth(1).getAttribute('value');
      await statusControl.selectOption(value);
      const opener = mode(name).locator('[data-action="collection-open"]').first();
      const id = await opener.getAttribute('data-id');
      await opener.click(); await expectMode(name, 'detail');
      check(await mode(name).locator('[data-action="collection-open"]').count() === 0, '详情与列表并列');
      check(await mode(name).locator('h1[data-collection-heading]').evaluate(node => node === document.activeElement), '详情标题未获得焦点');
      if (name === 'cases') {
        check(await mode(name).getByText('必须显式说明未知0', { exact: true }).isVisible(), '案例必须行为未显式展示');
        check(await mode(name).getByText('禁止承诺金额0', { exact: true }).isVisible(), '案例禁止行为未显式展示');
        await mode(name).locator('[data-action="case-edit"]').click(); await expectMode(name, 'form');
        check(await mode(name).locator('[data-action="case-review"]').count() === 0, '编辑与详情操作并列');
        await mode(name).locator('[data-action="collection-cancel"]').click(); await expectMode(name, 'detail');
      }
      if (name === 'iterations') {
        check(await mode(name).getByText('详情旧值0', { exact: true }).isVisible() && await mode(name).getByText('详情新值0', { exact: true }).isVisible(), '候选新旧值丢失');
        check(await mode(name).getByRole('heading', { name: '固定输入逐案例对比（脚本模拟）' }).isVisible(), '逐案例比较丢失');
        check(await mode(name).locator('[data-action="proposal-apply"]').isDisabled(), '过期候选仍可采用');
      }
      if (name === 'runs') check(await mode(name).getByText('历史来源证据 · v1', { exact: true }).isVisible(), '运行来源证据丢失');
      await mode(name).locator('[data-action="collection-back"]').click(); await expectMode(name, 'list');
      check((await state()).ui.collections[name].query === '专项' && (await state()).ui.collections[name].status === value, '返回丢失筛选');
      check(await mode(name).locator(`[data-action="collection-open"][data-id="${id}"]`).evaluate(node => node === document.activeElement), '返回未聚焦发起行');
      await mode(name).locator('[data-action="collection-clear"]').first().click();
      if (name !== 'runs') {
        const create = name === 'connections' ? '[data-action="collection-new"]' : name === 'cases' ? '[data-action="case-create"]' : '[data-action="proposal-create"]';
        await mode(name).locator(create).first().click(); await expectMode(name, 'form');
        check(await mode(name).locator('tbody tr').count() === 0, '新建与列表并列');
        check(await mode(name).locator('input[type="password"], input[name="apiKey"]').count() === 0, '原型收集密钥');
        await mode(name).locator('[data-action="collection-cancel"]').click(); await expectMode(name, 'list');
      }
      await page.locator('.topbar [data-action="readonly-toggle"]').click();
      check(await mode(name).locator(`[data-ui-bind="collections.${name}.query"]`).isEnabled(), '只读禁用了筛选');
      await mode(name).locator('[data-action="collection-open"]').first().click(); await expectMode(name, 'detail');
      for (const action of ['case-edit', 'case-review', 'proposal-apply', 'proposal-reject', 'connection-test', 'case-from-run']) {
        for (const button of await mode(name).locator(`[data-action="${action}"]`).all()) check(await button.isDisabled(), `只读没有禁止 ${action}`);
      }
      await mode(name).locator('[data-action="collection-back"]').click();
      await page.locator('.topbar [data-action="readonly-toggle"]').click();
      await page.evaluate(name => {
        const store = window.__loomriseDemo.store, key = { runs: 'runs', cases: 'cases', iterations: 'proposals', connections: 'connections' }[name];
        window.__optimizationRecords = store.state[key]; store.state[key] = []; store.dispatch('collection-clear', { page: name });
      }, name);
      check(await mode(name).getByRole('heading', { name: /^还没有/ }).isVisible(), '零记录与筛选无结果未区分');
      check(await mode(name).getByText('没有匹配的记录', { exact: true }).count() === 0, '零记录被当成无匹配');
      await page.locator('.topbar [data-action="readonly-toggle"]').click();
      check(await mode(name).getByText('当前为只读视图。返回草稿后可以编辑配置、资料和版本绑定。', { exact: true }).isVisible(), '只读空态未解释恢复路径');
      await page.locator('.topbar [data-action="readonly-toggle"]').click();
      await page.evaluate(name => {
        const store = window.__loomriseDemo.store, key = { runs: 'runs', cases: 'cases', iterations: 'proposals', connections: 'connections' }[name];
        store.state[key] = window.__optimizationRecords; delete window.__optimizationRecords; store.dispatch('collection-clear', { page: name });
      }, name);
      await noOverflow(`${name} 列表 1440×900`);
    });
  }

  await step('三类型各10条、合计30条混合长短/状态资料，类型数与筛选数分开', async () => {
    await go('knowledge');
    check(await page.locator('.library-summary').innerText().then(text => /30 条资料/.test(text) && /4 条可试用/.test(text) && /14 条待处理/.test(text) && /12 条不可用/.test(text)), '全部资料状态计数错误');
    for (const type of ['FAQ', 'URL', 'File']) {
      await page.locator(`[data-action="source-tab"][data-tab="${type}"]`).click();
      check(await page.locator(`[data-action="source-tab"][data-tab="${type}"]`).innerText().then(text => /10/.test(text)), `${type} 类型总数错误`);
      check(await page.locator('tr[data-source-id]').count() === 10, `${type} 混合列表缺项`);
      await page.locator('[data-ui-bind="sourceFilter"]').selectOption('unavailable');
      check(await page.locator('tr[data-source-id]').count() === 4, `${type} 不可用筛选错误`);
      check(await page.locator('.knowledge-list-count').innerText().then(text => /共 10 条/.test(text) && /筛选结果：4 条/.test(text)), '类型数量被错误改成筛选数量');
      await page.locator('[data-ui-bind="search"]').fill('无匹配资料');
      await page.locator('[data-action="source-clear"]').click();
      check(await page.locator('tr[data-source-id]').count() === 10, '清筛选没有恢复当前类型');
    }
    await noOverflow('30条知识混合列表 1440×900');
  });

  for (const [label, width, height] of [['桌面', 1440, 900], ['手机', 390, 844]]) {
    await page.setViewportSize({ width, height });
    for (const name of ['overview', 'runs', 'cases', 'iterations', 'connections', 'knowledge']) {
      await go(name); await noOverflow(`${label} ${name} ${width}×${height}`);
      if (['runs', 'cases', 'iterations', 'connections'].includes(name)) {
        await mode(name).locator('[data-action="collection-open"]').first().click(); await noOverflow(`${label} ${name} 详情`);
        await mode(name).locator('[data-action="collection-back"]').click();
        if (name !== 'runs') {
          await dispatch('collection-new', { page: name }); await noOverflow(`${label} ${name} 表单`);
          await mode(name).locator('[data-action="collection-cancel"]').click();
        }
      }
    }
  }
  await step('390px不足190字但超过三行的解答默认摘要，原生键盘展开完整正文', async () => {
    await go('knowledge');
    await page.locator('[data-action="source-tab"][data-tab="FAQ"]').click();
    const row = page.locator('tr[data-source-id="optimization-FAQ-0"]');
    const disclosure = row.locator('details.knowledge-answer-disclosure');
    const excerpt = row.locator('.knowledge-answer-excerpt');
    const metrics = await excerpt.evaluate(node => ({ height: node.getBoundingClientRect().height, scrollHeight: node.scrollHeight, lineHeight: parseFloat(getComputedStyle(node).lineHeight), clamp: getComputedStyle(node).webkitLineClamp }));
    check(metrics.clamp === '3' && metrics.height <= metrics.lineHeight * 3 + 2, '默认解答不是最多三行摘要');
    check(metrics.scrollHeight > metrics.height, '夹具未覆盖不足190字但视觉超过三行的解答');
    check(await disclosure.getAttribute('open') === null, '解答默认展开');
    await disclosure.locator('summary').focus(); await page.keyboard.press('Enter');
    check(await disclosure.getAttribute('open') !== null, 'Enter无法展开解答');
    const answer = await page.evaluate(() => window.__loomriseDemo.store.currentAgent().config.sources.find(item => item.id === 'optimization-FAQ-0').answer);
    check(answer.length <= 190, '夹具不再覆盖190字以内边界');
    check(await disclosure.locator('.knowledge-answer-full').isVisible() && await disclosure.locator('.knowledge-answer-full').textContent() === answer, '完整解答不可读或丢失正文');
    await page.keyboard.press('Space');
    check(await disclosure.getAttribute('open') === null, 'Space无法收起解答');
    await noOverflow('390px长解答键盘收放');
  });
  check(errors.length === 0, `页面错误：${errors.join('; ')}`);
  return { count: results.length, results, layouts, errors, note: '仅本地原创虚构夹具与浏览器交互；不验证真实模型、外部业务写入、渠道送达或正式发布门禁。' };
}
