async page => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  await page.goto('http://127.0.0.1:18765/#/widget?agent=course-demo');
  const entry = page.locator('[data-widget-entry]');
  await entry.waitFor();
  await page.locator('[data-widget-entry] option[value="widget-entry"]').waitFor({ state: 'attached' });
  if (await page.locator('.install-code code[data-copyable="true"]').count()) {
    throw new Error('Installation code must stay hidden until an entry is selected');
  }
  if (!(await page.getByRole('button', { name: '复制安装代码' }).isDisabled())) {
    throw new Error('Copy command must stay disabled until a published entry is selected');
  }

  await entry.focus();
  await entry.selectOption('widget-entry');
  if (!(await page.evaluate(() => document.activeElement?.matches('[data-widget-entry]')))) {
    throw new Error('Selecting a Widget entry must preserve keyboard focus in the entry control');
  }
  const code = page.locator('.install-code code[data-copyable="true"]');
  await code.waitFor();
  const value = await code.textContent();
  if (!value.includes('http://127.0.0.1:8798/widget.js?agent_id=course-demo&entry_id=widget-entry')) {
    throw new Error(`Installer must use the service origin and entry id: ${value}`);
  }
  if (value.includes('widget-fixture-v1') || value.includes('example.invalid')) {
    throw new Error('Version ids and placeholder domains are not widget entry identifiers');
  }
  if (await page.getByRole('button', { name: '复制安装代码' }).isDisabled()) {
    throw new Error('Copy command should be available for a ready published sandbox entry');
  }
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 960 });
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)) {
      throw new Error(`Widget installer page overflows at ${width}px`);
    }
    await page.screenshot({ path: `output/playwright/r3-widget-installer-ui-${width}.png` });
  }
  if (pageErrors.length) throw new Error(pageErrors.join('\n'));
  return { selectedEntryId: 'widget-entry', versionIdNotUsedAsEntry: true, copyEnabledOnlyAfterSelection: true, viewports: [1440, 390], pageErrors };
}
