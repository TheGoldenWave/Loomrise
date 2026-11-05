async (page) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const check = (value, message) => { if (!value) throw new Error(message); };
  await page.goto('about:blank');
  await page.goto('http://127.0.0.1:18765/#/configuration?agent=course-demo&section=r1-server');
  await page.evaluate(async () => {
    const { createConfigurationClient } = await import('/r1-configuration.js');
    const client = createConfigurationClient();
    const draft = await client.request('draft.get', { agent_id: 'course-demo' });
    const atom = (unitId, requires = []) => ({ unit_id: unitId, version: 1, load_mode: 'routed', reads: [], writes: [],
      entry_ports: [{ port: 'from_start', requires }], exit_ports: [{ port: 'done', completion: { deterministic: {} }, exits: ['self.done'] }],
      on_event: [], fallback: { kind: 'human' }, max_rounds: 3, body: { kind: 'say', text: '虚构校验定位', verbatim_reason: '测试' } });
    const packageUnit = atom('U-package');
    packageUnit.entry_ports[0].goto = 'child.from_start';
    packageUnit.body = { kind: 'graph', routing: { mode: 'deterministic' },
      nodes: [{ id: 'child', unit_ref: { unit_id: 'U-child', version: 1 } }],
      edges: [{ id: 'nested-edge', from: 'child.done', to: 'self.done', condition: 'bad' }] };
    draft.config.persona.fields = { verified: { type: 'boolean' } };
    draft.config.units = [packageUnit, atom('U-child', ['verified'])];
    draft.config.orchestration = { schema_version: 'unit-graph-v1', kind: 'graph', routing: { mode: 'deterministic' },
      nodes: [{ id: 'package', unit_ref: { unit_id: 'U-package', version: 1 } }], entry: 'package.from_start',
      edges: [{ id: 'root-edge', from: 'package.done', to: 'end', condition: { fact: { field: 'not_declared', op: 'eq', value: true } } }], on_event: [], unknown_field: true };
    await client.request('draft.save', { agent_id: 'course-demo', expected_revision: draft.revision, config: draft.config });
  });
  await page.reload();
  await page.locator('[data-action="r1-tab"][data-tab="flow"]').click();
  await page.getByRole('button', { name: '服务端校验', exact: true }).click();
  const result = page.getByRole('region', { name: '服务端校验结果', exact: true });
  await result.waitFor();
  const paths = await result.locator('[data-validation-path]').evaluateAll(items => items.map(item => item.dataset.validationPath));
  const rootEdgePath = paths.find(path => path.startsWith('$.orchestration.edges[0].condition'));
  const nestedEdgePath = paths.find(path => path.startsWith('$.units[0].body.edges[0].condition'));
  const portPath = paths.find(path => path.startsWith('$.units[1].entry_ports[0].requires'));
  check(rootEdgePath?.endsWith('.condition.fact.field') && nestedEdgePath && portPath, `服务端未返回预期 issue 路径：${paths.join(', ')}`);

  await result.locator(`[data-validation-path="${rootEdgePath}"]`).getByRole('button', { name: '定位到对象' }).click();
  await page.locator('[aria-label="边检视器"]').waitFor();
  await page.waitForFunction(() => document.activeElement?.closest('label')?.textContent?.startsWith('比较字段'));
  check(await page.locator('.orch-edge-list').getByRole('button', { name: /root-edge.*服务端校验问题/ }).count() === 1,
    'root edge 未在边清单显示服务端校验状态');
  check(await page.getByLabel('比较字段', { exact: true }).evaluate(element => element === document.activeElement),
    'root edge condition 未聚焦到实际比较字段');

  await result.locator(`[data-validation-path="${portPath}"]`).getByRole('button', { name: '定位到对象' }).click();
  const portField = page.getByRole('region', { name: '入口端口配置', exact: true }).locator('.orch-port-row').locator('[data-validation-field="requires"]');
  await portField.waitFor();
  await page.waitForFunction(() => document.activeElement?.dataset.validationField === 'requires');
  check(await portField.evaluate(element => element === document.activeElement), 'Unit port 定位未聚焦 requires 字段');
  check(await page.locator('.orch-node.has-validation-error').getByText('服务端校验问题', { exact: false }).count() >= 1,
    '端口错误没有文本化显示在相关节点');

  await result.locator(`[data-validation-path="${nestedEdgePath}"]`).getByRole('button', { name: '定位到对象' }).click();
  check(await page.getByRole('navigation', { name: '编排层级' }).getByRole('button', { name: 'U-package' }).count() === 1,
    'nested edge 定位未下钻至所属图层');
  await page.locator('[aria-label="边检视器"]').waitFor();
  await page.waitForFunction(() => document.activeElement?.name === 'condition' && document.activeElement?.tagName === 'TEXTAREA');
  check(await page.locator('.orch-inspector .orch-condition-editor textarea[name="condition"]').evaluate(element => element === document.activeElement),
    '无法表单化的整段条件错误没有聚焦原始 JSON 修复栏');
  check(await page.locator('.orch-edge-list').getByRole('button', { name: /nested-edge.*服务端校验问题/ }).count() === 1,
    'nested edge 未在当前层边清单显示服务端校验状态');

  const unknownPath = paths.find(path => path === '$.orchestration.unknown_field');
  check(unknownPath, `未知字段 validation path 缺失：${paths.join(', ')}`);
  await result.locator(`[data-validation-path="${unknownPath}"]`).getByRole('button', { name: '转到原始配置修复' }).click();
  check(await page.getByText('原始 orchestration 配置修复 · 服务器校验路径保留', { exact: true }).count() === 1,
    '未知 orchestration path 未提供原始 JSON 修复入口');
  check(!errors.length, `浏览器错误：${errors.join('；')}`);
  return { passed: true, rootEdge: rootEdgePath, nestedEdge: nestedEdgePath, unitPort: portPath, unknownPathRepair: true, errors };
}
