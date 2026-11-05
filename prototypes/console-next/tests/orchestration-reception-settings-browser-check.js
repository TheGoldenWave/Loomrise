async page => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const check = (value, message) => { if (!value) throw new Error(message); };
  await page.addInitScript(() => { window.__LOOMRISE_CONFIG_API__ ||= 'http://127.0.0.1:8789'; });
  await page.goto('about:blank');
  const app = await page.evaluate(() => window.__LOOMRISE_CONSOLE_PREVIEW_URL__ || 'http://127.0.0.1:18765/');
  await page.goto(`${app}#/configuration?agent=course-demo&section=r1-server`);
  await page.locator('[data-action="r1-tab"][data-tab="reception"]').click();
  await page.getByLabel('固定模型 ID', { exact: true }).waitFor();
  await page.locator('[data-r1-source]').first().waitFor();
  check(await page.getByLabel('启用 AI 接待', { exact: true }).isChecked(), '批准配置开关未正确显示');
  check(await page.getByLabel('固定模型 ID', { exact: true }).inputValue() === 'deterministic-browser-fixture', '冻结模型身份丢失');
  check(await page.locator('[data-r1-source]').first().isChecked(), '来源哈希未与当前引用对齐');
  const phrases = page.getByLabel('显式转人工短语', { exact: true });
  await phrases.fill('转人工\n');
  check(await phrases.inputValue() === '转人工\n', '短语编辑丢失末尾换行');
  await phrases.fill('Straße\nSTRASSE');
  check(await page.locator('[data-r1-handoff-error]').isVisible(), '重复短语未提示错误');
  check(await page.getByRole('button', { name: '保存草稿', exact: true }).isDisabled(), '错误短语仍能保存');
  await phrases.fill('转人工\nTalk to a human');
  const faqSource = page.locator('[data-r1-faq-source]');
  await faqSource.selectOption({ label: '虚构课程说明' });
  await page.locator('[data-r1-faq-question]').fill('Straße');
  await page.getByRole('button', { name: '添加', exact: true }).click();
  check(await page.locator('.r1-faq-row').count() === 2, 'FAQ 建议没有添加到版本草稿');
  await page.locator('[data-r1-faq-question]').fill('STRASSE');
  await page.getByRole('button', { name: '添加', exact: true }).click();
  check(await page.locator('[data-r1-faq-error]').isVisible(), 'Unicode case-fold 重复建议未被拒绝');
  const longQuestion = '😀'.repeat(81);
  await page.locator('[data-r1-faq-question]').fill(longQuestion);
  await faqSource.selectOption({ label: '虚构课程说明' });
  await page.getByRole('button', { name: '添加', exact: true }).click();
  check(await page.locator('.r1-faq-row input').nth(2).inputValue() === longQuestion,
    'FAQ 字符限制按 UTF-16 code unit 截断了合法 Unicode 文本');
  await page.locator('.r1-faq-row').nth(2).getByRole('button', { name: '移除' }).click();
  check(await page.locator('.r1-faq-row').count() === 2, 'FAQ 建议移除失败');
  await page.getByLabel('启用 AI 接待', { exact: true }).uncheck();
  await page.getByLabel('接待时机', { exact: true }).selectOption('offline');
  await page.locator('[data-r1-source]').first().uncheck();
  check(await page.locator('[data-r1-source]').first().evaluate(node => document.activeElement === node), '选择来源后焦点丢失');
  await page.locator('[data-r1-source]').first().check();
  await page.getByRole('button', { name: '保存草稿', exact: true }).click();
  await page.getByRole('button', { name: '服务端校验', exact: true }).click();
  await page.getByText('服务端校验通过', { exact: true }).waitFor();
  await page.reload();
  await page.locator('[data-action="r1-tab"][data-tab="reception"]').click();
  await page.locator('[data-r1-source]').first().waitFor();
  check(!(await page.getByLabel('启用 AI 接待', { exact: true }).isChecked()), '布尔开关未持久保存');
  check(await page.getByLabel('接待时机', { exact: true }).inputValue() === 'offline', '接待时机未持久保存');
  check(await page.locator('[data-r1-source]').first().isChecked(), '来源引用未持久保存');
  check(await phrases.inputValue() === '转人工\nTalk to a human', '转人工短语未随草稿保存');
  check(await page.locator('.r1-faq-row').count() === 2
    && await page.locator('.r1-faq-row input').nth(1).inputValue() === 'Straße', 'FAQ 建议未随版本草稿持久保存');
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${width}px 接待配置横向溢出`);
    await page.getByLabel('AI 客服接待配置', { exact: true }).screenshot({ path: `output/playwright/r3-reception-settings-${width}.png` });
  }
  await page.locator('[data-action="r1-tab"][data-tab="history"]').click();
  await page.getByRole('button', { name: '只读查看', exact: true }).first().click();
  await page.locator('[data-action="r1-tab"][data-tab="reception"]').click();
  check(await page.getByLabel('固定模型 ID', { exact: true }).isDisabled(), '只读版本可改接待模型');
  check(await phrases.isDisabled() && await phrases.inputValue() === '', '稳定版本被草稿短语修改或可写');
  check(await page.getByLabel('启用 AI 接待', { exact: true }).isChecked(), '保存草稿改变了稳定版本');
  check(!errors.length, errors.join('; '));
  return { passed: true, sharedSaveReload: true, modelPinned: true, sourceHashPinned: true, keyboardFocus: true,
    stableReadOnly: true, widths: [1440, 390], pageErrors: errors.length };
}
