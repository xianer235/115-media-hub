import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { launchPreviewBrowser } from './browser-launch.mjs';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const baseUrl = String(process.env.PREVIEW_BASE_URL || 'http://127.0.0.1:18080').trim();
const username = String(process.env.PREVIEW_USERNAME || 'admin').trim();
const password = String(process.env.PREVIEW_PASSWORD || 'admin123').trim();
const outDir = path.join(scriptDir, 'shots', 'modal-audit');
await fs.promises.mkdir(outDir, { recursive: true });

async function login(page) {
  await page.goto(`${baseUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.getByPlaceholder('管理账号').fill(username);
  await page.getByPlaceholder('访问密码').fill(password);
  await page.getByRole('button', { name: '进入管理后台' }).click();
  await page.waitForURL((u) => !u.pathname.endsWith('/login'), { timeout: 15000 });
  await page.waitForTimeout(1000);
}

async function toDay(page) {
  await page.evaluate(() => {
    if (!document.documentElement.classList.contains('theme-day')) {
      const btn = document.getElementById('theme-toggle');
      if (btn) btn.click();
    }
  });
  await page.waitForTimeout(800);
}

async function switchTab(page, key) {
  const map = {
    resource: '#tab-resource',
    subscription: '#tab-subscription',
    monitor: '#tab-monitor',
    task: '#tab-task',
    settings: '#tab-settings',
    about: '#tab-about',
  };
  await page.click(map[key]);
  await page.waitForTimeout(900);
}

async function shot(page, name) {
  const file = path.join(outDir, `${name}.png`);
  await page.screenshot({ path: file, fullPage: false });
  return file;
}

async function safeOpen(page, name, openFn, closeFn = null) {
  try {
    await openFn();
    await page.waitForTimeout(700);
    const file = await shot(page, name);
    if (closeFn) {
      await closeFn();
      await page.waitForTimeout(400);
    }
    return { name, file, ok: true };
  } catch (e) {
    return { name, ok: false, error: String(e?.message || e) };
  }
}

const { browser, browserMeta } = await launchPreviewBrowser({ headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'zh-CN' });
const page = await context.newPage();

try {
  await login(page);
  await toDay(page);

  const output = [];

  await switchTab(page, 'resource');
  output.push({ name: 'page-resource', file: await shot(page, 'page-resource'), ok: true });

  await switchTab(page, 'settings');
  output.push({ name: 'page-settings', file: await shot(page, 'page-settings'), ok: true });

  output.push(await safeOpen(
    page,
    'modal-help',
    () => page.evaluate(() => window.showHelp && window.showHelp('配色检查帮助示例文本')),
    () => page.evaluate(() => window.closeHelpModal && window.closeHelpModal()),
  ));

  output.push(await safeOpen(
    page,
    'modal-resource-source',
    () => page.evaluate(() => window.openResourceSourceModal && window.openResourceSourceModal()),
    () => page.evaluate(() => window.closeResourceSourceModal && window.closeResourceSourceModal()),
  ));

  output.push(await safeOpen(
    page,
    'modal-resource-source-import',
    () => page.evaluate(() => window.openResourceSourceImportModal && window.openResourceSourceImportModal()),
    () => page.evaluate(() => window.closeResourceSourceImportModal && window.closeResourceSourceImportModal()),
  ));

  output.push(await safeOpen(
    page,
    'modal-resource-source-manager',
    () => page.evaluate(() => window.openResourceSourceManagerModal && window.openResourceSourceManagerModal()),
    () => page.evaluate(() => window.closeResourceSourceManagerModal && window.closeResourceSourceManagerModal()),
  ));

  await switchTab(page, 'monitor');
  output.push({ name: 'page-monitor', file: await shot(page, 'page-monitor'), ok: true });
  output.push(await safeOpen(
    page,
    'modal-monitor',
    () => page.evaluate(() => window.openNewMonitorTask && window.openNewMonitorTask()),
    () => page.evaluate(() => window.closeMonitorModal && window.closeMonitorModal()),
  ));

  await switchTab(page, 'subscription');
  output.push({ name: 'page-subscription', file: await shot(page, 'page-subscription'), ok: true });
  output.push(await safeOpen(
    page,
    'modal-subscription',
    () => page.evaluate(() => window.openNewSubscriptionTask && window.openNewSubscriptionTask()),
    () => page.evaluate(() => window.closeSubscriptionModal && window.closeSubscriptionModal()),
  ));

  output.push(await safeOpen(
    page,
    'modal-subscription-tmdb',
    async () => {
      await page.evaluate(() => {
        if (window.openNewSubscriptionTask) window.openNewSubscriptionTask();
      });
      await page.waitForTimeout(400);
      await page.evaluate(() => window.openSubscriptionTmdbSearchModal && window.openSubscriptionTmdbSearchModal());
    },
    async () => {
      await page.evaluate(() => window.closeSubscriptionTmdbSearchModal && window.closeSubscriptionTmdbSearchModal());
      await page.evaluate(() => window.closeSubscriptionModal && window.closeSubscriptionModal());
    },
  ));

  output.push(await safeOpen(
    page,
    'modal-subscription-folder',
    async () => {
      await page.evaluate(() => {
        if (window.openNewSubscriptionTask) window.openNewSubscriptionTask();
      });
      await page.waitForTimeout(400);
      await page.evaluate(() => window.openSubscriptionFolderModal && window.openSubscriptionFolderModal());
    },
    async () => {
      await page.evaluate(() => window.closeSubscriptionFolderModal && window.closeSubscriptionFolderModal());
      await page.evaluate(() => window.closeSubscriptionModal && window.closeSubscriptionModal());
    },
  ));

  await switchTab(page, 'resource');
  output.push(await safeOpen(
    page,
    'modal-resource-job-list',
    () => page.evaluate(() => window.toggleResourceJobModal && window.toggleResourceJobModal(true)),
    () => page.evaluate(() => window.toggleResourceJobModal && window.toggleResourceJobModal(false)),
  ));

  output.push(await safeOpen(
    page,
    'modal-resource-import',
    async () => {
      const btn = page.locator('[data-resource-action="import"]').first();
      await btn.click({ timeout: 5000 });
    },
    () => page.evaluate(() => window.closeResourceJobModal && window.closeResourceJobModal()),
  ));

  output.push(await safeOpen(
    page,
    'modal-resource-folder',
    async () => {
      const btn = page.locator('[data-resource-action="import"]').first();
      await btn.click({ timeout: 5000 });
      await page.waitForTimeout(400);
      await page.evaluate(() => window.openResourceFolderModal && window.openResourceFolderModal());
    },
    async () => {
      await page.evaluate(() => window.closeResourceFolderModal && window.closeResourceFolderModal());
      await page.evaluate(() => window.closeResourceJobModal && window.closeResourceJobModal());
    },
  ));

  await switchTab(page, 'task');
  output.push({ name: 'page-task', file: await shot(page, 'page-task'), ok: true });

  await switchTab(page, 'about');
  output.push({ name: 'page-about', file: await shot(page, 'page-about'), ok: true });

  console.log(JSON.stringify({ outDir, browser: browserMeta, output }, null, 2));
} finally {
  await context.close();
  await browser.close();
}
