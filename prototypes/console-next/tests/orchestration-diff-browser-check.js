async (page) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const check = (value, message) => { if (!value) throw new Error(message); };
  // Dedicated disposable SQLite fixture; do not touch the other browser session's drafts.
  await page.addInitScript(() => { window.__LOOMRISE_CONFIG_API__ = 'http://127.0.0.1:8767'; });
  await page.goto('about:blank');
  await page.goto('http://127.0.0.1:18765/#/configuration?agent=course-demo&section=r1-server');
  await page.evaluate(async () => {
    const { createConfigurationClient } = await import('/r1-configuration.js');
    const client = createConfigurationClient();
    const draft = await client.request('draft.get', { agent_id: 'course-demo' });
    const config = draft.config;
    config.persona.fields = { ready: { type: 'boolean' }, tier: { type: 'string' }, 'user.verified': { type: 'boolean' } };
    config.units = [{ unit_id: '接待', version: 1, load_mode: 'routed', reads: ['user.verified'], writes: [],
      entry_ports: [{ port: 'in', requires: [], custom: { keep: true } }], exit_ports: [{ port: 'done', completion: { deterministic: {} }, exits: ['self.done'] }],
      on_event: [], fallback: { kind: 'human' }, max_rounds: 3,
      body: { kind: 'say', text: '虚构测试', verbatim_reason: '服务范围披露' } }];
    config.orchestration = { schema_version: 'unit-graph-v1', kind: 'graph', routing: { mode: 'deterministic' },
      input_fields: ['ready', 'tier', 'user.verified'],
      nodes: [{ id: 'reception', unit_ref: { unit_id: '接待', version: 1 } }], entry: 'reception.in',
      edges: ['first', 'second'].map(id => ({ id, from: 'reception.done', to: 'end', condition: {} })),
      on_event: [], fallback: { kind: 'human' } };
    await client.request('draft.save', { agent_id: 'course-demo', expected_revision: draft.revision, config });
  });
  await page.reload();
  await page.locator('[data-action="r1-tab"][data-tab="flow"]').click();
  await page.locator('.orch-edge-list ol button').first().click();
  await page.getByRole('button', { name: '优先级下移', exact: true }).click();
  await page.getByRole('button', { name: '保存草稿', exact: true }).click();
  await page.locator('.r1-object-diff').getByText('边优先级 $ · 优先级变化', { exact: true }).waitFor();
  check(await page.locator('.r1-object-diff li').count() === 1, '边重排不应产生内容修改');
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 960 });
    check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${width}px 对象差异视图横向溢出`);
  }
  await page.screenshot({ path: 'output/playwright/r3-object-diff-mobile.png', fullPage: true });
  await page.locator('.orch-edge-list ol button').first().click();
  const edgeCondition = page.getByRole('region', { name: '边条件', exact: true });
  await edgeCondition.getByRole('combobox', { name: '判断类型', exact: true }).selectOption('all_of');
  await edgeCondition.getByRole('alert').waitFor();
  await page.getByRole('button', { name: '应用边修改', exact: true }).click();
  check(await page.getByRole('button', { name: '保存草稿', exact: true }).isDisabled(), '未填完整的构造器不应写入草稿');
  check(await edgeCondition.locator('option[value="json"]').getAttribute('disabled') !== null, '未完成表单不应通过模式切换丢失输入');
  await edgeCondition.getByRole('combobox', { name: '比较字段', exact: true }).fill('ready');
  await edgeCondition.getByRole('combobox', { name: '比较方式', exact: true }).selectOption('eq');
  await edgeCondition.getByRole('combobox', { name: '值类型', exact: true }).selectOption('boolean');
  await edgeCondition.getByRole('button', { name: '添加子条件', exact: true }).click();
  await edgeCondition.getByRole('combobox', { name: '判断类型', exact: true }).nth(2).selectOption('any_of');
  await edgeCondition.getByRole('combobox', { name: '比较字段', exact: true }).nth(1).fill('tier');
  await edgeCondition.getByRole('combobox', { name: '比较方式', exact: true }).nth(1).selectOption('in');
  await edgeCondition.getByRole('textbox', { name: '比较列表 JSON', exact: true }).fill('["gold","silver"]');
  await edgeCondition.getByRole('combobox', { name: '判断类型', exact: true }).first().selectOption('any_of');
  check(await edgeCondition.getByRole('combobox', { name: '比较字段', exact: true }).first().inputValue() === 'ready', '切换组合算子丢失子条件');
  await edgeCondition.getByRole('combobox', { name: '判断类型', exact: true }).first().selectOption('all_of');
  await edgeCondition.locator('.orch-condition-tree').first().locator(':scope > .orch-condition-children > button').click();
  await edgeCondition.getByRole('combobox', { name: '判断类型', exact: true }).last().selectOption('event');
  await edgeCondition.getByRole('alert').waitFor();
  await page.getByRole('button', { name: '应用边修改', exact: true }).click();
  check(await page.getByRole('button', { name: '保存草稿', exact: true }).isDisabled(), '未选择事件名不应写入草稿');
  await edgeCondition.getByRole('combobox', { name: '事件名称', exact: true }).selectOption('timeout');
  await edgeCondition.getByText('附加属性（可选）', { exact: true }).click();
  await edgeCondition.getByRole('textbox', { name: '事件属性 JSON', exact: true }).fill('{');
  await edgeCondition.getByRole('alert').waitFor();
  check(await edgeCondition.getByRole('textbox', { name: '事件属性 JSON', exact: true }).inputValue() === '{', '坏事件属性丢失原文');
  await edgeCondition.getByRole('textbox', { name: '事件属性 JSON', exact: true }).fill('{"source":"sandbox","retries":2}');
  await edgeCondition.locator('.orch-condition-tree').first().locator(':scope > .orch-condition-children > button').click();
  await edgeCondition.getByRole('combobox', { name: '判断类型', exact: true }).last().selectOption('state');
  await edgeCondition.getByRole('combobox', { name: '统计指标', exact: true }).selectOption('runs');
  await edgeCondition.getByRole('combobox', { name: '统计窗口', exact: true }).selectOption('forever');
  await edgeCondition.getByRole('spinbutton', { name: '比较值', exact: true }).fill('3');
  await page.getByRole('button', { name: '应用边修改', exact: true }).click();
  await page.getByText('另有未保存修改，不含在本回执中', { exact: false }).waitFor();
  await page.getByRole('button', { name: '保存草稿', exact: true }).click();
  await page.locator('.r1-object-diff').getByText('边 second · 修改', { exact: true }).waitFor();
  check(!(await page.locator('.r1-object-diff').textContent()).includes('优先级变化'), '条件修改误报优先级');
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 960 });
    check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${width}px 条件构造器横向溢出`);
  }
  await page.evaluate(() => document.activeElement?.blur());
  await edgeCondition.screenshot({ path: 'output/playwright/r3-condition-builder-mobile.png' });
  await edgeCondition.getByRole('combobox', { name: '边条件编辑方式', exact: true }).selectOption('json');
  const constructedCondition = JSON.parse(await edgeCondition.getByRole('textbox', { name: '边条件 JSON', exact: true }).inputValue());
  check(constructedCondition.all_of[0].fact.value === true && constructedCondition.all_of[1].any_of[0].fact.value[0] === 'gold', '构造器丢失布尔或列表值类型');
  check(constructedCondition.all_of[2].event.event === 'timeout', '构造器未保留事件名称');
  check(constructedCondition.all_of[2].event.attributes.retries === 2, '事件属性丢失数值类型');
  check(constructedCondition.all_of[3].state.window === 'forever' && constructedCondition.all_of[3].state.value === 3, '状态窗口未正确生成');
  await edgeCondition.getByRole('textbox', { name: '边条件 JSON', exact: true }).fill('{"not":[{"event":{"event":"timeout"}}]}');
  await edgeCondition.getByRole('combobox', { name: '边条件编辑方式', exact: true }).selectOption('form');
  check(await edgeCondition.getByRole('combobox', { name: '事件名称', exact: true }).inputValue() === 'timeout', '旧 not 列表的事件叶丢失');
  check(await edgeCondition.getByRole('button', { name: '添加子条件', exact: true }).count() === 0, '单子条件否定不应允许添加第二个子条件');
  await edgeCondition.getByRole('combobox', { name: '边条件编辑方式', exact: true }).selectOption('json');
  check(JSON.parse(await edgeCondition.getByRole('textbox', { name: '边条件 JSON', exact: true }).inputValue()).not[0].event.event === 'timeout', '旧 not 列表被静默改写');
  await edgeCondition.getByRole('textbox', { name: '边条件 JSON', exact: true }).fill(JSON.stringify(constructedCondition));
  await page.getByRole('button', { name: '单元清单', exact: true }).click();
  await page.locator('.orch-list').getByRole('button', { name: '接待', exact: true }).click();
  const entryPorts = page.getByRole('region', { name: '入口端口配置', exact: true });
  const exitPorts = page.getByRole('region', { name: '出口端口配置', exact: true });
  check(await entryPorts.getByRole('button', { name: '添加入口端口', exact: true }).isDisabled(), '原子单元不应增加端口');
  await entryPorts.getByLabel('进入前须就绪的字段', { exact: true }).fill('user.verified');
  await exitPorts.getByRole('combobox', { name: '完成条件编辑方式', exact: true }).selectOption('json');
  await exitPorts.getByRole('textbox', { name: '完成条件 JSON', exact: true }).fill('[]');
  await page.getByRole('button', { name: '应用单元修改', exact: true }).click();
  await page.getByText('done 的确定性完成条件必须是 JSON 对象', { exact: true }).waitFor();
  check(await page.getByRole('button', { name: '保存草稿', exact: true }).isDisabled(), '坏条件不应写入共享草稿');
  await exitPorts.getByRole('textbox', { name: '完成条件 JSON', exact: true }).fill('{}');
  await exitPorts.getByRole('combobox', { name: '完成条件编辑方式', exact: true }).selectOption('form');
  check(await exitPorts.locator('.orch-condition-editor option[value="llm"]').count() === 0, '确定性完成条件不应提供模型叶');
  await exitPorts.getByRole('combobox', { name: '判断类型', exact: true }).selectOption('fact');
  await exitPorts.getByRole('combobox', { name: '比较字段', exact: true }).fill('system.channel');
  await exitPorts.getByRole('textbox', { name: '比较值', exact: true }).fill('text');
  await exitPorts.getByLabel('模型完成判据', { exact: true }).check();
  await exitPorts.getByLabel('模型判据', { exact: true }).fill('核验已完成');
  await page.getByRole('button', { name: '应用单元修改', exact: true }).click();
  await page.getByRole('button', { name: '保存草稿', exact: true }).click();
  await page.locator('.r1-object-diff').getByText('入口端口 in · 修改', { exact: true }).waitFor();
  await page.locator('.r1-object-diff').getByText('出口端口 done · 修改', { exact: true }).first().waitFor();
  await page.screenshot({ path: 'output/playwright/r3-port-editor-mobile.png', fullPage: true });
  await page.reload();
  check(await page.locator('.r1-object-diff').count() === 0, '刷新后不应伪造最近保存回执');
  const persisted = await page.evaluate(async () => {
    const { createConfigurationClient } = await import('/r1-configuration.js');
    return createConfigurationClient().request('draft.get', { agent_id: 'course-demo' });
  });
  check(persisted.config.orchestration.edges[0].id === 'second', '优先级未持久保存');
  check(persisted.config.orchestration.edges[0].condition.all_of[0].fact.value === true, '构造器条件未持久保存');
  check(persisted.config.orchestration.edges[0].condition.all_of[2].event.event === 'timeout', '事件条件未持久保存');
  check(persisted.config.orchestration.edges[0].condition.all_of[2].event.attributes.source === 'sandbox', '事件属性未持久保存');
  check(persisted.config.orchestration.edges[0].condition.all_of[3].state.metric === 'runs', '状态窗口未持久保存');
  check(persisted.config.units[0].entry_ports[0].requires[0] === 'user.verified', '入口前提未持久保存');
  check(persisted.config.units[0].entry_ports[0].custom.keep === true, '未知端口元数据丢失');
  check(persisted.config.units[0].exit_ports[0].completion.llm === '核验已完成', '出口判据未持久保存');
  check(persisted.config.units[0].exit_ports[0].completion.deterministic.fact.value === 'text', '完成条件构造器未持久保存');
  const validation = await page.evaluate(async () => {
    const { createConfigurationClient } = await import('/r1-configuration.js');
    const client = createConfigurationClient();
    const draft = await client.request('draft.get', { agent_id: 'course-demo' });
    return client.request('draft.validate', { agent_id: 'course-demo', expected_revision: draft.revision });
  });
  check(validation.valid === true, `构造器产物未通过共享结构校验：${JSON.stringify(validation.issues)}`);

  // A model predicate is deferred to the current graph's closed-set selector.
  await page.evaluate(async () => {
    const { createConfigurationClient } = await import('/r1-configuration.js');
    const client = createConfigurationClient();
    const draft = await client.request('draft.get', { agent_id: 'course-demo' });
    draft.config.orchestration.routing.mode = 'hybrid';
    await client.request('draft.save', { agent_id: 'course-demo', expected_revision: draft.revision, config: draft.config });
  });
  await page.reload();
  await page.locator('[data-action="r1-tab"][data-tab="flow"]').click();
  await page.locator('.orch-edge-list ol button').first().click();
  await edgeCondition.getByRole('combobox', { name: '判断类型', exact: true }).first().selectOption('llm');
  await edgeCondition.getByRole('alert').waitFor();
  await page.getByRole('button', { name: '应用边修改', exact: true }).click();
  check(await page.getByRole('button', { name: '保存草稿', exact: true }).isDisabled(), '空模型判据不应写入共享草稿');
  await edgeCondition.getByRole('textbox', { name: '模型判据', exact: true }).fill('访客已确认继续答疑');
  await page.getByRole('button', { name: '应用边修改', exact: true }).click();
  await page.getByRole('button', { name: '保存草稿', exact: true }).click();
  await page.locator('.r1-object-diff').getByText('边 second · 修改', { exact: true }).first().waitFor();
  await page.reload();
  await page.locator('[data-action="r1-tab"][data-tab="flow"]').click();
  await page.locator('.orch-edge-list ol button').first().click();
  check(await edgeCondition.getByRole('textbox', { name: '模型判据', exact: true }).inputValue() === '访客已确认继续答疑', '模型叶保存刷新后未恢复结构化表单');
  const frozen = await page.evaluate(async () => {
    const { createConfigurationClient } = await import('/r1-configuration.js');
    const client = createConfigurationClient();
    const draft = await client.request('draft.get', { agent_id: 'course-demo' });
    const validation = await client.request('draft.validate', { agent_id: 'course-demo', expected_revision: draft.revision });
    const candidate = await client.request('candidate.freeze', { agent_id: 'course-demo', expected_revision: draft.revision,
      idempotency_key: `model-edge-${draft.revision}` });
    return { validation, candidate, condition: draft.config.orchestration.edges[0].condition };
  });
  check(frozen.validation.valid && frozen.candidate.status === 'frozen', '正向模型叶未通过服务端校验与冻结');
  check(JSON.stringify(frozen.condition) === JSON.stringify({ llm: { prompt: '访客已确认继续答疑' } }), '模型条件不是 Loomrise prompt 叶形状');
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 960 });
    check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${width}px 模型条件表单横向溢出`);
  }
  await edgeCondition.screenshot({ path: 'output/playwright/r3-model-condition-mobile.png' });
  await edgeCondition.getByRole('combobox', { name: '判断类型', exact: true }).selectOption('none_of');
  await edgeCondition.getByRole('alert').waitFor();
  const negativeChild = edgeCondition.locator('.orch-condition-children fieldset').first();
  check(await negativeChild.locator('option[value="llm"]').count() === 0, '否定子树不应提供模型叶');
  await page.getByRole('button', { name: '应用边修改', exact: true }).click();
  check(await page.getByRole('button', { name: '保存草稿', exact: true }).isDisabled(), '否定模型叶不应写入共享草稿');
  check(!errors.length, `浏览器错误：${errors.join('；')}`);
  return { passed: true, sqliteSaveReload: true, priorityDiff: true, conditionDiff: true, portEditAndPersistence: true,
    invalidCompletionRejected: true, modelEdgeSaveReloadAndFreeze: true, negativeModelRejected: true,
    staleReceiptWarning: true, widths: [1440, 390], errors };
}
