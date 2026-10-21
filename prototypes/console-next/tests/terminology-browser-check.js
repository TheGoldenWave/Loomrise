async (page) => {
  const root = 'http://127.0.0.1:8788/console-next/';
  await page.goto(root);
  await page.setViewportSize({ width: 1440, height: 900 });
  const reports = [];
  const routes = ['agents', 'create', 'overview', 'configuration', 'knowledge', 'materials', 'trial', 'inbox', 'widget', 'contact', 'runs', 'cases', 'iterations', 'versions', 'connections', 'deployment'];
  for (const route of routes) {
    await page.evaluate(route => {
      const store = window.__loomriseDemo.store;
      store.dispatch('navigate', { page: route });
      if (store.state.ui.readonly) store.dispatch('readonly-toggle');
      if (route === 'knowledge') store.dispatch('source-list');
      if (route === 'materials') store.dispatch('material-list');
      if (['runs', 'cases', 'iterations', 'connections'].includes(route)) store.dispatch('collection-back', { page: route });
    }, route);
    const report = await page.evaluate(() => {
      const visible = node => Boolean(node.getClientRects().length) && getComputedStyle(node).visibility !== 'hidden';
      const copy = [...document.querySelectorAll('main h1, main h2, main h3, main button, main label, main summary, main .badge, main .helper, main [aria-label]')].filter(visible).map(node => ({ text: node.textContent.trim(), accessibleName: node.getAttribute('aria-label') || '' }));
      return { title: document.querySelector('main h1')?.textContent, checked: copy.length, findings: copy.filter(item => /\b(?:Agent|Inbox|Widget|Mock|FAQ|URL|Trace|revision)\b/.test(item.text + ' ' + item.accessibleName)) };
    });
    reports.push({ route, ...report });
  }
  return { routes: reports.length, reports, note: '实际可见控件/标签/状态/帮助与无障碍名称定向抽取；技术协议、格式、用户原文按语境保留，不是完整语言或辅助技术认证。' };
}
