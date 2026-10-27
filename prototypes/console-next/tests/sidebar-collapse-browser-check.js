async (page) => {
  const root = `${new URL(page.url()).origin}/`;
  const check = (condition, message) => { if (!condition) throw new Error(message); };
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const preference = () => page.locator('.app-shell').getAttribute('data-sidebar-collapsed');
  const state = () => page.evaluate(() => ({
    page: window.__loomriseDemo.store.state.ui.page,
    agent: window.__loomriseDemo.store.state.selectedAgentId,
    config: JSON.stringify(window.__loomriseDemo.store.currentAgent()?.config),
    versions: JSON.stringify(window.__loomriseDemo.store.currentAgent()?.versions),
    revision: window.__loomriseDemo.store.currentAgent()?.revision,
    hash: location.hash,
    history: history.length,
  }));
  const waitLayout = async collapsed => {
    await page.waitForFunction(collapsed => {
      const workspace = document.querySelector('.workspace');
      const sidebar = document.querySelector('.sidebar');
      return workspace && sidebar && Math.abs(parseFloat(getComputedStyle(workspace).marginLeft) - (collapsed ? 0 : 208)) < 1
        && (getComputedStyle(sidebar).visibility === 'hidden') === collapsed;
    }, collapsed);
  };
  const toggle = async collapsed => {
    const before = await state();
    const button = page.getByRole('button', { name: collapsed ? '收起侧边栏' : '展开侧边栏', exact: true });
    const box = await button.boundingBox();
    const breadcrumb = await page.locator('.breadcrumb').boundingBox();
    check(box && breadcrumb && box.x + box.width <= breadcrumb.x, '侧栏开关没有位于顶栏标题之前');
    await button.click();
    await waitLayout(collapsed);
    const next = page.getByRole('button', { name: collapsed ? '展开侧边栏' : '收起侧边栏', exact: true });
    check(await next.getAttribute('aria-expanded') === String(!collapsed), '侧栏开关的展开状态不正确');
    check(await preference() === String(collapsed), '桌面收起状态未更新');
    check(JSON.stringify(await state()) === JSON.stringify(before), '展开收起改变了页面、专家配置、版本或浏览器历史');
  };
  const screenshot = name => page.screenshot({ path: `output/playwright/sidebar-collapse/${name}.png`, fullPage: true });
  const overflow = async label => check(!await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), `${label} 出现横向溢出`);
  const openMobile = async () => {
    await page.getByRole('button', { name: '打开导航', exact: true }).click();
    await page.waitForFunction(() => {
      const sidebar = document.querySelector('.sidebar');
      return sidebar && getComputedStyle(sidebar).visibility === 'visible' && Math.abs(sidebar.getBoundingClientRect().left) < 1;
    });
  };

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`${root}#/agents`);
  if (await preference() === 'true') await toggle(false);
  await page.getByRole('button', { name: '新建', exact: true }).click();
  await page.getByLabel('专家名称').fill('折叠核验·虚构专家');
  await page.getByRole('button', { name: '创建手动草稿' }).click();
  await page.locator('.app-shell[data-page="overview"]').waitFor();
  if (await page.locator('[data-action="dismiss-toast"]').count()) await page.locator('[data-action="dismiss-toast"]').click();
  const id = new URLSearchParams(page.url().split('?').at(-1)).get('agent');
  check(Boolean(id), '创建后没有进入独立专家');
  const expertUrl = page.url();
  await page.locator('.sidebar-nav [data-page="knowledge"]').click();
  await page.locator('.knowledge-batch-intake > summary').click();
  const batch = page.locator('[data-form="source-batch"]');
  await batch.getByLabel('选择资料').setInputFiles({ name: '虚构侧栏核验.csv', mimeType: 'text/csv', buffer: Buffer.from('问题,答案\n怎样联系,请联系人工\n') });
  await batch.getByLabel('这批资料的出处').fill('保留未提交表单');
  await toggle(true);
  await toggle(false);
  check(await batch.getByLabel('选择资料').evaluate(input => input.files[0]?.name) === '虚构侧栏核验.csv', '展开收起清除了已选文件');
  check(await batch.getByLabel('这批资料的出处').inputValue() === '保留未提交表单', '展开收起清除了未提交表单');
  await page.locator('.sidebar-nav [data-page="overview"]').click();
  await screenshot('expert-expanded-1440');
  await toggle(true);
  await overflow('1440px 专家收起');
  await screenshot('expert-collapsed-1440');
  await page.reload();
  await waitLayout(true);
  check(page.url() === expertUrl && await preference() === 'true', '专家刷新丢失收起偏好或页面');
  await page.locator('.breadcrumb').getByRole('button', { name: '工作区', exact: true }).click();
  await page.locator('.app-shell[data-scope="workspace"]').waitFor();
  await waitLayout(true);
  await screenshot('workspace-collapsed-1440');
  await page.reload();
  await waitLayout(true);
  await toggle(false);
  await screenshot('workspace-expanded-1440');
  await toggle(true);
  await page.locator(`main .agent-name[data-id="${id}"]`).click();
  await page.locator('.app-shell[data-page="overview"]').waitFor();
  await waitLayout(true);

  await page.setViewportSize({ width: 390, height: 844 });
  await openMobile();
  check(await page.locator('.sidebar').isVisible(), '桌面收起偏好阻止了手机导航打开');
  check(await page.locator('.mobile-close button').evaluate(button => button === document.activeElement), '打开手机导航后焦点没有进入抽屉');
  check(await page.getByLabel('切换当前专家', { exact: true }).isVisible(), '手机抽屉中当前专家不可用');
  await overflow('390px 专家抽屉');
  await screenshot('expert-drawer-390');
  await page.locator('.sidebar-nav [data-page="knowledge"]').click();
  await page.locator('.app-shell[data-page="knowledge"]').waitFor();
  await page.locator('.sidebar').waitFor({ state: 'hidden' });
  check(!await page.locator('.sidebar').isVisible(), '手机导航后抽屉未收起');
  check(await preference() === 'true', '手机导航修改了桌面收起偏好');
  await openMobile();
  await page.keyboard.press('Escape');
  await page.locator('.sidebar').waitFor({ state: 'hidden' });
  check(await page.locator('.mobile-menu button').evaluate(button => button === document.activeElement), 'Escape 关闭后焦点没有返回导航按钮');
  await openMobile();
  await page.locator('.workspace-back').click();
  await page.locator('.app-shell[data-scope="workspace"]').waitFor();
  await openMobile();
  check(await page.locator('.sidebar-nav [data-page="materials"]').isVisible(), '工作区手机资源导航不可用');
  await overflow('390px 工作区抽屉');
  await screenshot('workspace-drawer-390');
  await page.locator('.mobile-close [data-action="toggle-nav"]').click();
  check(await preference() === 'true', '关闭手机抽屉修改了桌面收起偏好');
  await page.setViewportSize({ width: 1440, height: 900 });
  await waitLayout(true);
  await toggle(false);
  check(errors.length === 0, `浏览器异常：${errors.join('; ')}`);
  return { desktop: '两平面展开收起、内容宽度、历史不新增与刷新保留通过', mobile: '390px 抽屉与桌面偏好独立，无横向溢出', screenshots: 6, errors };
}
