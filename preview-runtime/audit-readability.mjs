import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { launchPreviewBrowser } from './browser-launch.mjs';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const baseUrl = String(process.env.PREVIEW_BASE_URL || 'http://127.0.0.1:18080').trim();
const username = String(process.env.PREVIEW_USERNAME || 'admin').trim();
const password = String(process.env.PREVIEW_PASSWORD || 'admin123').trim();
const outDir = path.join(scriptDir, 'shots', 'readability-audit');
await fs.promises.mkdir(outDir, { recursive: true });

function parseRgb(str) {
  if (!str || typeof str !== 'string') return null;
  const m = str.match(/rgba?\(([^)]+)\)/i);
  if (!m) return null;
  const parts = m[1].split(',').map((v) => Number(v.trim()));
  if (parts.length < 3) return null;
  return { r: parts[0], g: parts[1], b: parts[2], a: parts[3] == null ? 1 : parts[3] };
}

function srgbToLinear(v) {
  const s = v / 255;
  return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
}

function luminance(rgb) {
  const r = srgbToLinear(rgb.r);
  const g = srgbToLinear(rgb.g);
  const b = srgbToLinear(rgb.b);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a, b) {
  const L1 = luminance(a);
  const L2 = luminance(b);
  const light = Math.max(L1, L2);
  const dark = Math.min(L1, L2);
  return (light + 0.05) / (dark + 0.05);
}

async function loginAndSwitchToDay(page) {
  await page.goto(`${baseUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.getByPlaceholder('管理账号').fill(username);
  await page.getByPlaceholder('访问密码').fill(password);
  await page.getByRole('button', { name: '进入管理后台' }).click();
  await page.waitForURL((u) => !u.pathname.endsWith('/login'), { timeout: 15000 });
  await page.waitForTimeout(1000);
  await page.evaluate(() => {
    if (!document.documentElement.classList.contains('theme-day')) {
      const btn = document.getElementById('theme-toggle');
      if (btn) btn.click();
    }
  });
  await page.waitForTimeout(1000);
}

async function openTab(page, name) {
  const map = {
    resource: '#tab-resource',
    subscription: '#tab-subscription',
    monitor: '#tab-monitor',
    task: '#tab-task',
    settings: '#tab-settings',
    about: '#tab-about',
  };
  const sel = map[name];
  await page.click(sel);
  await page.waitForTimeout(900);
}

async function openModals(page) {
  const opened = [];
  const tryClick = async (fn) => {
    try {
      await fn();
      return true;
    } catch {
      return false;
    }
  };

  if (await tryClick(async () => {
    await openTab(page, 'monitor');
    await page.getByRole('button', { name: /新增任务/ }).click();
    await page.waitForTimeout(600);
  })) opened.push({ key: 'modal-monitor', close: () => page.evaluate(() => window.closeMonitorModal && window.closeMonitorModal()) });

  if (await tryClick(async () => {
    await openTab(page, 'subscription');
    await page.getByRole('button', { name: /新增订阅任务/ }).click();
    await page.waitForTimeout(700);
  })) opened.push({ key: 'modal-subscription', close: () => page.evaluate(() => window.closeSubscriptionModal && window.closeSubscriptionModal()) });

  if (await tryClick(async () => {
    await openTab(page, 'settings');
    await page.locator('.info-dot').first().click();
    await page.waitForTimeout(600);
  })) opened.push({ key: 'modal-help', close: () => page.evaluate(() => window.hideLockedModal && window.hideLockedModal('help-modal')) });

  return opened;
}

async function analyzePage(page, key) {
  const shot = path.join(outDir, `${key}.png`);
  await page.screenshot({ path: shot, fullPage: false });

  const issues = await page.evaluate(({ key }) => {
    function parseRgb(str) {
      if (!str || typeof str !== 'string') return null;
      const m = str.match(/rgba?\(([^)]+)\)/i);
      if (!m) return null;
      const parts = m[1].split(',').map((v) => Number(v.trim()));
      if (parts.length < 3) return null;
      return { r: parts[0], g: parts[1], b: parts[2], a: parts[3] == null ? 1 : parts[3] };
    }
    function srgbToLinear(v) {
      const s = v / 255;
      return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
    }
    function luminance(rgb) {
      const r = srgbToLinear(rgb.r);
      const g = srgbToLinear(rgb.g);
      const b = srgbToLinear(rgb.b);
      return 0.2126 * r + 0.7152 * g + 0.0722 * b;
    }
    function contrast(a, b) {
      const L1 = luminance(a);
      const L2 = luminance(b);
      const light = Math.max(L1, L2);
      const dark = Math.min(L1, L2);
      return (light + 0.05) / (dark + 0.05);
    }

    function effectiveBg(el) {
      let node = el;
      let depth = 0;
      while (node && depth < 10) {
        const cs = getComputedStyle(node);
        const bg = parseRgb(cs.backgroundColor);
        if (bg && bg.a > 0.96) return bg;
        node = node.parentElement;
        depth += 1;
      }
      return { r: 255, g: 255, b: 255, a: 1 };
    }

    const all = Array.from(document.querySelectorAll('body *'));
    const found = [];

    for (const el of all) {
      const cs = getComputedStyle(el);
      if (cs.visibility === 'hidden' || cs.display === 'none') continue;
      if (Number(cs.opacity || '1') < 0.4) continue;
      const rect = el.getBoundingClientRect();
      if (rect.width < 10 || rect.height < 10) continue;
      const text = (el.textContent || '').trim().replace(/\s+/g, ' ');
      if (!text) continue;
      if (text.length > 80) continue;

      const fg = parseRgb(cs.color);
      if (!fg || fg.a < 0.7) continue;
      const bg = effectiveBg(el);
      const ratio = contrast(fg, bg);

      if (ratio < 3.5) {
        found.push({
          key,
          ratio: Number(ratio.toFixed(2)),
          text: text.slice(0, 60),
          cls: (el.className || '').toString().slice(0, 120),
          tag: el.tagName,
          color: cs.color,
          bg: `rgb(${bg.r}, ${bg.g}, ${bg.b})`,
        });
      }
    }

    return found.sort((a, b) => a.ratio - b.ratio).slice(0, 20);
  }, { key });

  return { key, screenshot: shot, issues };
}

const { browser, browserMeta } = await launchPreviewBrowser({ headless: true });
const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'zh-CN' })).newPage();

try {
  await loginAndSwitchToDay(page);

  const pages = ['resource', 'subscription', 'monitor', 'task', 'settings', 'about'];
  const report = [];

  for (const p of pages) {
    await openTab(page, p);
    report.push(await analyzePage(page, `page-${p}`));
  }

  const modals = await openModals(page);
  for (const modal of modals) {
    report.push(await analyzePage(page, modal.key));
    await modal.close();
    await page.waitForTimeout(500);
  }

  console.log(JSON.stringify({ outDir, browser: browserMeta, report }, null, 2));
} finally {
  await browser.close();
}
