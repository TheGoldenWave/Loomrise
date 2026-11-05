import { readFileSync, existsSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { homedir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const testDirectory = dirname(fileURLToPath(import.meta.url));
const check = process.argv[2];
const isInboxAssistance = check === 'inbox-assistance-browser-check.js';
const isInboxFilters = check === 'inbox-filters-browser-check.js' || isInboxAssistance;
if (!isInboxFilters && !['config-ui-browser-check.js', 'terminology-browser-check.js', 'navigation-browser-check.js', 'sidebar-collapse-browser-check.js', 'orchestration-browser-check.js', 'orchestration-nested-browser-check.js', 'orchestration-diff-browser-check.js', 'orchestration-advisory-browser-check.js', 'orchestration-overlay-browser-check.js', 'orchestration-history-browser-check.js', 'orchestration-reception-settings-browser-check.js', 'orchestration-keyboard-browser-check.js', 'orchestration-validation-browser-check.js', 'customer-statistics-browser-check.js', 'contact-editor-browser-check.js', 'contact-generation-browser-check.js', 'inbox-notifications-browser-check.js', 'widget-configuration-browser-check.js', 'widget-material-browser-check.js', 'widget-live-reception-browser-check.js', 'widget-offline-reception-browser-check.js', 'widget-install-browser-check.js', 'widget-installer-ui-browser-check.js', 'customer_reception_browser_check.js'].includes(check)) throw new Error('请选择已登记的浏览器检查脚本');
const cli = process.env.PLAYWRIGHT_CLI || join(process.env.CODEX_HOME || join(homedir(), '.codex'), 'skills/playwright/scripts/playwright_cli.sh');
if (!existsSync(cli)) throw new Error('未找到 Playwright CLI 包装脚本；请通过 PLAYWRIGHT_CLI 指定已安装脚本');
const options = { cwd: resolve(testDirectory, '../../..'), stdio: 'inherit', timeout: 120000 };
const isOrchestration = check.startsWith('orchestration-') || check.startsWith('contact-');
const isWidget = check.startsWith('widget-');
const isWidgetInstall = check === 'widget-install-browser-check.js';
const isWidgetInstallerUi = check === 'widget-installer-ui-browser-check.js';
const session = process.env.PLAYWRIGHT_SESSION || (isWidgetInstall ? 'r3-widget-install'
  : isWidgetInstallerUi ? 'r3-widget-installer-ui'
  : check === 'customer_reception_browser_check.js' ? 'r3-reception'
  : check === 'widget-offline-reception-browser-check.js' ? 'r3-offline-reception'
  : isWidget ? 'r3-widget' : check === 'sidebar-collapse-browser-check.js' ? 'sidebar-collapse'
  : isInboxAssistance ? 'r3-inbox-assistance' : isInboxFilters ? 'r3-inbox-filters' : check === 'inbox-notifications-browser-check.js' ? 'r3-inbox-notifications'
  : check === 'customer-statistics-browser-check.js' ? 'r3-statistics'
    : check === 'contact-editor-browser-check.js' ? 'r3-contact-editor'
      : check === 'contact-generation-browser-check.js' ? 'r3-contact-generation'
      : isOrchestration ? (check.includes('validation') ? 'r3-validation' : check.includes('nested') ? 'r3-nested' : check.includes('diff') ? 'r3-diff'
      : check.includes('overlay') ? 'r3-overlay-telemetry' : check.includes('keyboard') ? 'r3-keyboard-focus' : 'r3-canvas')
      : 'config-ui-round1');
const argumentsForSession = ['proxy', cli, '--session', session];
let browserScript = readFileSync(isWidgetInstall
  ? resolve(testDirectory, '../../../tests/widget_install_browser_check.js')
  : check === 'customer_reception_browser_check.js'
    ? resolve(testDirectory, '../../../tests', check) : join(testDirectory, check), 'utf8');
const configuredPreviewUrl = process.env.CONSOLE_TEST_APP_URL || null;
if (configuredPreviewUrl) {
  const preview = new URL(configuredPreviewUrl);
  if (preview.protocol !== 'http:' || !['127.0.0.1', 'localhost'].includes(preview.hostname)
    || preview.username || preview.password || preview.pathname !== '/' || preview.search || preview.hash) {
    throw new Error('CONSOLE_TEST_APP_URL 仅允许本机 HTTP 根路径');
  }
}
if (process.env.CONFIGURATION_TEST_API) {
  const fixture = new URL(process.env.CONFIGURATION_TEST_API);
  if (fixture.protocol !== 'http:' || !['127.0.0.1', 'localhost'].includes(fixture.hostname)
    || fixture.username || fixture.password || fixture.pathname !== '/' || fixture.search || fixture.hash) throw new Error('浏览器测试只允许本机 HTTP fixture origin');
  browserScript = `async (page) => { await page.addInitScript(config => {
    window.__LOOMRISE_CONFIG_API__ = config.api;
    if (config.app) window.__LOOMRISE_CONSOLE_PREVIEW_URL__ = config.app;
  }, ${JSON.stringify({ api: fixture.origin, app: configuredPreviewUrl })}); await page.goto('about:blank'); return (${browserScript})(page); }`;
}
try {
  const initialUrl = isWidgetInstall
    ? 'http://127.0.0.1:8799/widget_install_site.html'
    : isWidgetInstallerUi ? 'http://127.0.0.1:18765/'
    : check === 'widget-offline-reception-browser-check.js'
    ? 'http://127.0.0.1:18878/widget/course-demo/widget-entry'
    : check === 'widget-live-reception-browser-check.js' || check === 'customer_reception_browser_check.js'
      || check === 'widget-offline-reception-browser-check.js'
    ? 'http://127.0.0.1:8788/widget/course-demo/widget-entry'
    : isWidget ? 'http://127.0.0.1:8777/widget/course-demo/widget-entry'
      : isOrchestration || isInboxFilters || check === 'customer-statistics-browser-check.js' || check === 'inbox-notifications-browser-check.js' ? 'http://127.0.0.1:18765/'
        : 'http://127.0.0.1:8765/';
  const previewUrl = process.env.CONSOLE_TEST_APP_URL || initialUrl;
  execFileSync('rtk', [...argumentsForSession, 'open', previewUrl], options);
  execFileSync('rtk', [...argumentsForSession, 'run-code', browserScript], options);
} catch {
  process.exitCode = 1;
}
