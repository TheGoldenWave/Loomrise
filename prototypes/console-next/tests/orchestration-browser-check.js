async (page) => {
  // 本脚本验收 R3 的真实图合同 unit-graph-v1（服务端 SCHEMA_VERSION，见 loomrise/graph_validation.py）。
  // 旧的 R1 扁平清单夹具（只有 units，用 exit_ports[].exits 表达去处）已删除：旧清单投影
  // 生成的边不带 edgeConfig，画布与边检视器读取 edge.edgeConfig.condition 会抛 TypeError，
  // 「编排图 / 单元清单」工具栏随之消失，页面只提示「画布无法解析当前草稿」。
  // 因此「候选出口」这一类只对旧清单成立的断言不再保留，改用图合同的节点/边语义。
  // 具体删除项：旧夹具 makeUnit(id, targets) 把去处写进 exit_ports[].exits，并按
  // 「候选出口未投影」断言边数；图合同下去处由 orchestration.edges 决定，exits 不再
  // 参与投影，该断言在新合同下无意义，已替换为图合同的节点/边计数断言。
  const check = (value, message) => { if (!value) throw new Error(message); };
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto('http://127.0.0.1:18765/#/configuration?agent=course-demo&section=r1-server');
  await page.reload();

  // 图合同写入说明：页面没有常驻的 orchestration 编辑器。canvas.jsx 只在
  // repairPath === 'orchestration' 时渲染「原始 orchestration 配置修复」原文框，
  // 而该分支只能由服务端校验返回 $.orchestration.* issue 的「转到原始配置修复」按钮触发；
  // 服务端又只在草稿已包含 orchestration 时才校验图分支（config_validation.py），
  // 因此无法从 UI 首次写入图合同。这里沿用同目录 orchestration-validation /
  // orchestration-advisory 检查的既有做法：用页面自身的配置客户端把图写入共享草稿，
  // 其余（units 清单、人设入口、保存、撤销/重做、检视器、冻结只读）全部走页面 UI。
  const orchestration = {
    schema_version: 'unit-graph-v1',
    kind: 'graph',
    routing: { mode: 'deterministic' },
    entry: 'start.in',
    input_fields: [],
    nodes: [
      { id: 'start', unit_ref: { unit_id: 'U-咨询', version: 1 } },
      { id: 'hand', unit_ref: { unit_id: 'U-人工', version: 1 } },
    ],
    // 每条边都必须显式写 condition（{} 表示无条件）；hand.done 也必须有出边，
    // 否则 graph_validation.py:422-425 会报 unconnected_exit_port。
    // 出边只能指向本层入口端口或 end（graph_validation.py:578-589），
    // 因此 hand.done 收束到结束路由，画布会多渲染一个「结束路由」终止节点。
    edges: [
      { id: 'e1', from: 'start.done', to: 'hand.in', condition: {} },
      { id: 'e2', from: 'hand.done', to: 'end', condition: {} },
    ],
    on_event: [],
    fallback: { kind: 'clarify' },
  };
  await page.evaluate(async graph => {
    const { createConfigurationClient } = await import('/r1-configuration.js');
    const client = createConfigurationClient();
    const draft = await client.request('draft.get', { agent_id: 'course-demo' });
    await client.request('draft.save', {
      agent_id: 'course-demo', expected_revision: draft.revision,
      config: { ...draft.config, orchestration: graph },
    });
  }, orchestration);
  await page.reload();

  await page.locator('[data-action="r1-tab"][data-tab="persona"]').click();
  await page.locator('[data-r1-json="persona.entry_unit_ids"]').fill('["U-咨询"]');
  await page.locator('[data-action="r1-tab"][data-tab="flow"]').click();
  await page.getByRole('button', { name: '编排图', exact: true }).waitFor();
  // 页面每次重渲染都会重建 <details>，原始清单可能重新收起；每次写入前按需展开。
  const unitsEditor = async () => {
    const editor = page.locator('[data-r1-json="units"]');
    if (!await editor.isVisible()) await page.getByText('原始 Unit 清单与修复', { exact: true }).click();
    return editor;
  };
  // body.kind 只能是 graph / tool / judge / speak / say；其中 tool 与 speak 在冻结时
  // 会追加 unsupported_graph_atom（graph_validation.py:477-480），能通过校验的原子只有
  // say 与 judge。say 必须同时给 text 与 verbatim_reason（graph_validation.py:446-450）。
  const makeUnit = (id, exits) => ({ unit_id: id, version: 1, load_mode: 'routed',
    entry_ports: [{ port: 'in', requires: [] }], reads: [], writes: [],
    exit_ports: [{ port: 'done', completion: { deterministic: { event: { event: 'timeout' } } }, exits }],
    on_event: [], fallback: { kind: 'clarify' }, max_rounds: 2,
    body: { kind: 'say', text: '本机虚构固定内容', verbatim_reason: '浏览器验收 fixture' },
  });
  // exits 仍需写成「已知路由单元」或「self.<出口端口>」（config_validation.py:387-399），
  // 空数组会报 empty_exits，写成 hand.in 这类节点端口会报 unknown_unit_reference。
  const units = [makeUnit('U-咨询', ['U-人工']), makeUnit('U-人工', ['self.done'])];
  await (await unitsEditor()).fill(JSON.stringify(units, null, 2));
  await page.locator('.react-flow__node').first().waitFor();
  // 图合同要求 hand.done 有出边，边只能收束到 end，因此画布为 2 个路由单元 + 1 个终止节点。
  check(await page.locator('.react-flow__node').count() === 3, '图合同未投影出 2 个路由单元与 1 个结束节点');
  await page.locator('.orch-toolbar-meta').getByText('2 个路由单元', { exact: false }).waitFor();
  await page.locator('.react-flow__edge').first().waitFor();
  check(await page.locator('.react-flow__edge').count() === 2, '图合同未投影出两条边（主边 + 收束到结束）');
  const nodeTexts = await page.locator('.react-flow__node').allInnerTexts();
  check(nodeTexts.some(text => text.includes('U-咨询')) && nodeTexts.some(text => text.includes('U-人工')),
    `节点文案缺少单元标识：${nodeTexts.join(' | ')}`);
  // 首屏可见性：切到 flow 后用户不滚动就应看到至少一个节点（布局修复的验收点）。
  const firstNodeBox = await page.locator('.react-flow__node').first().evaluate(node => {
    const rect = node.getBoundingClientRect();
    return { top: rect.top, viewport: innerHeight };
  });
  check(firstNodeBox.top < firstNodeBox.viewport,
    `首屏看不到画布节点：首节点 top=${Math.round(firstNodeBox.top)}，视口高=${firstNodeBox.viewport}`);
  await page.getByRole('button', { name: '保存草稿', exact: true }).click();
  await page.getByText('与服务端草稿一致', { exact: false }).waitFor();
  check(await page.getByRole('button', { name: '保存草稿', exact: true }).isDisabled(), '基准草稿尚未保存');
  check(await page.getByRole('button', { name: '撤销修改', exact: true }).isDisabled(), '保存后未建立新历史边界');
  await page.getByRole('button', { name: '单元清单', exact: true }).click();
  await page.locator('.orch-list').getByRole('button', { name: 'U-咨询', exact: true }).click();
  check(await page.getByRole('complementary', { name: '单元检视器' }).count() === 1, '清单未打开检视器');
  await page.getByRole('button', { name: '编排图', exact: true }).click();
  check(await page.locator('.orch-node.is-selected').count() === 1, '切回图丢失选中态');
  await page.getByLabel('进入上限', { exact: true }).fill('4');
  await page.getByRole('button', { name: '应用单元修改', exact: true }).click();
  check(await page.getByRole('button', { name: '保存草稿', exact: true }).isEnabled(), '检视器修改后保存按钮未更新');
  check(await page.getByRole('button', { name: '撤销修改', exact: true }).isEnabled(), '检视器修改后撤销按钮未更新');
  check(await page.getByRole('button', { name: '服务端校验', exact: true }).isDisabled(), '未保存修改仍可校验旧版');
  check(await page.getByRole('button', { name: '冻结候选', exact: true }).isDisabled(), '未保存修改仍可冻结旧版');
  await page.locator('.r1-service-header').getByText('有未保存修改', { exact: false }).waitFor();
  check(await page.getByRole('button', { name: '应用单元修改', exact: true }).evaluate(element => element === document.activeElement), '检视器应用修改后丢失焦点');
  const rawUnits = () => page.locator('[data-r1-json="units"]').inputValue().then(JSON.parse);
  check((await rawUnits())[0].max_rounds === 4, '检视器修改未同步原始 JSON');
  await page.getByRole('button', { name: '撤销修改', exact: true }).click();
  check((await rawUnits())[0].max_rounds === 2, '撤销未还原原始 JSON');
  await page.getByRole('button', { name: '重做修改', exact: true }).click();
  const editedUnits = await rawUnits();
  check(editedUnits[0].max_rounds === 4, '重做未同步原始 JSON');
  editedUnits[1].max_rounds = 3;
  await (await unitsEditor()).fill(JSON.stringify(editedUnits, null, 2));
  check((await rawUnits())[0].max_rounds === 4, '原始 JSON 编辑覆盖了检视器修改');
  await page.getByRole('button', { name: '保存草稿', exact: true }).click();
  await page.getByText('与服务端草稿一致', { exact: false }).waitFor();
  await page.reload();
  await page.locator('[data-action="r1-tab"][data-tab="flow"]').click();
  await page.getByRole('button', { name: '单元清单', exact: true }).click();
  await page.locator('.orch-list').getByRole('button', { name: 'U-咨询', exact: true }).click();
  check(await page.getByLabel('进入上限', { exact: true }).inputValue() === '4', '服务端重读未保留检视器修改');
  await page.getByRole('button', { name: '判定规则', exact: true }).click();
  await page.getByRole('heading', { name: '边界事件', exact: true }).waitFor();
  await page.getByRole('button', { name: '编排图', exact: true }).click();
  await page.screenshot({ path: 'output/playwright/r3-canvas-desktop.png', fullPage: true });
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 960 });
    check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${width}px 页面横向溢出`);
  }
  await page.screenshot({ path: 'output/playwright/r3-canvas-mobile.png', fullPage: true });
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.getByRole('button', { name: '冻结候选', exact: true }).click();
  await page.getByRole('heading', { name: '发布前检查', exact: true }).waitFor();
  await page.locator('[data-action="r1-tab"][data-tab="flow"]').click();
  await page.getByRole('button', { name: '单元清单', exact: true }).click();
  await page.locator('.orch-list').getByRole('button', { name: 'U-咨询', exact: true }).click();
  check(await page.getByLabel('进入上限', { exact: true }).isDisabled(), '冻结候选检视器可写');
  check(await page.getByRole('region', { name: '入口端口配置', exact: true }).getByRole('textbox', { name: '端口标识', exact: true }).isDisabled(), '冻结候选端口标识可写');
  check(await page.getByRole('region', { name: '出口端口配置', exact: true }).getByRole('checkbox', { name: '模型完成判据', exact: true }).isDisabled(), '冻结候选完成判据可写');
  check(await page.getByRole('region', { name: '完成条件', exact: true }).getByRole('combobox', { name: '判断类型', exact: true }).isDisabled(), '冻结候选条件构造器可写');
  check(await page.getByRole('region', { name: '完成条件', exact: true }).getByRole('combobox', { name: '事件名称', exact: true }).isDisabled(), '冻结候选事件名称可写');
  check(await page.getByRole('button', { name: '应用单元修改', exact: true }).count() === 0, '候选出现写入动作');
  check(!errors.length, `浏览器错误：${errors.join('；')}`);
  return { passed: true, schema: 'unit-graph-v1', routedUnits: 2, nodes: 3, edges: 2, firstScreenNodeVisible: true, persistedMaxRounds: 4, sharedDraftControls: true, undoRedo: true, inspectorFocus: true, candidateReadOnly: true, widths: [1440, 390], errors };
}
