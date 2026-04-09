import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { devices } from 'playwright';
import { launchPreviewBrowser } from './browser-launch.mjs';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const baseUrl = String(process.env.PREVIEW_BASE_URL || 'http://127.0.0.1:18080').trim();
const username = String(process.env.PREVIEW_USERNAME || 'admin').trim();
const password = String(process.env.PREVIEW_PASSWORD || 'admin123').trim();
const outDir = path.join(scriptDir, 'shots', 'theme-audit');
await fs.promises.mkdir(outDir, { recursive: true });

async function login(page) {
  await page.goto(`${baseUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.getByPlaceholder('管理账号').fill(username);
  await page.getByPlaceholder('访问密码').fill(password);
  await page.getByRole('button', { name: '进入管理后台' }).click();
  await page.waitForURL((u) => !u.pathname.endsWith('/login'), { timeout: 15000 });
  await page.waitForTimeout(1200);
}

async function grabPalette(page) {
  return await page.evaluate(() => {
    const read = (selector) => {
      const el = document.querySelector(selector);
      if (!el) return null;
      const cs = getComputedStyle(el);
      return {
        selector,
        color: cs.color,
        bg: cs.backgroundColor,
        border: cs.borderColor,
      };
    };

    return {
      htmlClass: document.documentElement.className,
      body: read('body'),
      nav: read('nav'),
      title: read('.nav-title'),
      themeToggle: read('#theme-toggle'),
      logout: read('a[href="/logout"]'),
      tabActive: read('#tab-row .tab-active'),
      tabInactive: read('#tab-row .tab-inactive'),
      groupCard: read('.group-card'),
      searchInput: read('#resource-search-input'),
      searchBtn: read('#resource-search-btn'),
      syncBtn: read('#resource-sync-btn'),
      resourceCard: read('.resource-card'),
      chip: read('.resource-card .text-slate-100'),
    };
  });
}

async function runCase(browser, name, contextOptions) {
  const ctx = await browser.newContext({ locale: 'zh-CN', ...contextOptions });
  const page = await ctx.newPage();
  await login(page);

  await page.waitForTimeout(600);
  const nightFile = path.join(outDir, `${name}-night.png`);
  await page.screenshot({ path: nightFile, fullPage: false });
  const nightPalette = await grabPalette(page);

  await page.evaluate(() => {
    const btn = document.getElementById('theme-toggle');
    if (btn) btn.click();
  });
  await page.waitForTimeout(900);
  const dayFile = path.join(outDir, `${name}-day.png`);
  await page.screenshot({ path: dayFile, fullPage: false });
  const dayPalette = await grabPalette(page);

  await ctx.close();
  return {
    night: { screenshot: nightFile, palette: nightPalette },
    day: { screenshot: dayFile, palette: dayPalette },
  };
}

const { browser, browserMeta } = await launchPreviewBrowser({ headless: true });
try {
  const desktop = await runCase(browser, 'desktop', { viewport: { width: 1440, height: 900 } });
  const mobile = await runCase(browser, 'mobile', devices['iPhone 13']);
  console.log(JSON.stringify({ outDir, browser: browserMeta, desktop, mobile }, null, 2));
} finally {
  await browser.close();
}
