import { readFileSync, existsSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { homedir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const testDirectory = dirname(fileURLToPath(import.meta.url));
const check = process.argv[2];
if (!['config-ui-browser-check.js', 'terminology-browser-check.js', 'navigation-browser-check.js', 'sidebar-collapse-browser-check.js'].includes(check)) throw new Error('请选择已登记的浏览器检查脚本');
const cli = process.env.PLAYWRIGHT_CLI || join(process.env.CODEX_HOME || join(homedir(), '.codex'), 'skills/playwright/scripts/playwright_cli.sh');
if (!existsSync(cli)) throw new Error('未找到 Playwright CLI 包装脚本；请通过 PLAYWRIGHT_CLI 指定已安装脚本');
const options = { cwd: resolve(testDirectory, '../../..'), stdio: 'inherit', timeout: 120000 };
const argumentsForSession = ['proxy', cli, '--session', check === 'sidebar-collapse-browser-check.js' ? 'sidebar-collapse' : 'config-ui-round1'];
try {
  execFileSync('rtk', [...argumentsForSession, 'open', 'http://127.0.0.1:8765/'], options);
  execFileSync('rtk', [...argumentsForSession, 'run-code', readFileSync(join(testDirectory, check), 'utf8')], options);
} catch {
  process.exitCode = 1;
}
