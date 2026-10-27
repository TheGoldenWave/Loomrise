async (page) => {
  const root = 'http://127.0.0.1:8765/';
  await page.goto(root);
  await page.setViewportSize({ width: 1440, height: 900 });
  const reports = [];
  const routes = ['overview', 'knowledge', 'redlines', 'business', 'flow', 'test', 'versions', 'settings', 'configuration'];
  for (const width of [1440, 390]) {
  await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
  for (const route of routes) {
    await page.evaluate(route => {
      const store = window.__loomriseDemo.store;
      store.dispatch('navigate', { page: route });
      if (store.state.ui.readonly) store.dispatch('readonly-toggle');
      if (route === 'knowledge') store.dispatch('source-list');
      if (route === 'configuration') store.dispatch('set-section', { section: 'service' });
      if (route === 'materials') store.dispatch('material-list');
      if (['runs', 'cases', 'iterations', 'connections'].includes(route)) store.dispatch('collection-back', { page: route });
    }, route);
    const report = await page.evaluate(() => {
      const visible = node => Boolean(node.getClientRects().length) && getComputedStyle(node).visibility !== 'hidden';
      const copy = [...document.querySelectorAll('main h1, main h2, main h3, main button, main label, main summary, main .badge, main .helper, main [aria-label]')].filter(visible).filter(node => !node.closest('details:not([open]), .release-technical')).map(node => ({ text: node.textContent.trim(), accessibleName: node.getAttribute('aria-label') || '' }));
      const internal = /(?:装载|编排|验收|守卫|沙盒|口径|事实|结果承诺|运行叠加|证据抽屉|草稿\s*r\d+|业务概览|业务配置|详细配置|保存草稿|发布到沙盒)/;
      return { title: document.querySelector('main h1')?.textContent, checked: copy.length, findings: copy.filter(item => internal.test(item.text + ' ' + item.accessibleName)) };
    });
    reports.push({ width, route, ...report });
  }
  }
  const failures = reports.filter(report => report.findings.length);
  if (failures.length) throw new Error(JSON.stringify(failures));
  return { views: reports.length, reports, note: '七个一级工作面、设置和更多设置的可见标题/控件文案扫描；折叠技术详情与用户原文不计入，不是完整语言或辅助技术认证。' };
}
