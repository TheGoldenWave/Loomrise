async (page) => {
  const root = 'http://127.0.0.1:8788/console-next/';
  const reports = [];
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.reload();
  await page.waitForFunction(() => window.__loomriseDemo);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const id = await page.evaluate(() => window.__loomriseDemo.store.state.selectedAgentId);
  const routes = ['agents', 'create', 'overview', 'configuration', 'knowledge', 'materials', 'trial', 'inbox', 'widget', 'contact', 'runs', 'cases', 'iterations', 'versions', 'connections', 'deployment'];
  for (const [name, width, height] of [['desktop', 1440, 900], ['mobile', 390, 844]]) {
    await page.setViewportSize({ width, height });
    for (const route of routes) {
      await page.goto(`${root}#/${route}?agent=${id}`);
      await page.evaluate(() => {
        const store = window.__loomriseDemo.store;
        if (store.state.ui.navOpen) store.dispatch('toggle-nav');
        if (store.state.ui.readonly) store.dispatch('readonly-toggle');
        store.dispatch('set-side-panel', { panel: 'preview' });
        store.dispatch('set-side-panel', { panel: 'editor' });
        if (store.state.ui.page === 'configuration') {
          store.dispatch('set-depth', { depth: 'business' });
          store.dispatch('set-section', { section: 'service' });
        }
        scrollTo(0, 0);
      });
      await page.locator('main h1').waitFor();
      const metrics = await page.evaluate(() => ({ width: innerWidth, documentWidth: document.documentElement.scrollWidth, title: document.querySelector('main h1')?.textContent, bodyText: document.querySelector('main')?.innerText.length, failedImages: [...document.images].filter(image => image.getClientRects().length && image.currentSrc && image.complete && !image.naturalWidth).length, pendingImages: [...document.images].filter(image => image.getClientRects().length && image.currentSrc && !image.complete).length }));
      await page.screenshot({ path: `.playwright-mcp/round2/${route}-${name}.png`, fullPage: true, scale: 'css', animations: 'disabled' });
      reports.push({ route, viewport: name, ...metrics });
    }
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`${root}#/configuration?agent=${id}`);
  await page.evaluate(() => {
    const store = window.__loomriseDemo.store;
    store.dispatch('set-depth', { depth: 'detailed' });
    store.dispatch('set-section', { section: 'fields' });
    store.dispatch('set-side-panel', { panel: 'editor' });
  });
  await page.screenshot({ path: '.playwright-mcp/round2/detailed-desktop.png', fullPage: true, scale: 'css', animations: 'disabled' });
  await page.evaluate(() => window.__loomriseDemo.store.dispatch('set-side-panel', { panel: 'assistant' }));
  await page.screenshot({ path: '.playwright-mcp/round2/agent-assist-desktop.png', fullPage: true, scale: 'css', animations: 'disabled' });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: '.playwright-mcp/round2/agent-assist-mobile.png', fullPage: true, scale: 'css', animations: 'disabled' });
  return { checked: reports.length, reports, errors, overflow: reports.filter(item => item.documentWidth > item.width), screenshots: 35, note: '第二轮及物料扩展截图；加载最新模块并停止截图时的过渡，未验证真实后台。' };
}
