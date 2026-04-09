import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { launchPreviewBrowser } from './browser-launch.mjs';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const baseUrl = String(process.env.PREVIEW_BASE_URL || 'http://127.0.0.1:18080').trim();
const username = String(process.env.PREVIEW_USERNAME || 'admin').trim();
const password = String(process.env.PREVIEW_PASSWORD || 'admin123').trim();
const outDir = path.join(scriptDir, 'shots', 'contrast-audit');
await fs.promises.mkdir(outDir, { recursive: true });

function parseRgb(str) {
  if (!str || typeof str !== 'string') return null;
  const m = str.match(/rgba?\(([^)]+)\)/i);
  if (!m) return null;
  const p = m[1].split(',').map((v) => Number(v.trim()));
  if (p.length < 3 || p.some((n) => Number.isNaN(n))) return null;
  return { r: p[0], g: p[1], b: p[2], a: p[3] == null ? 1 : p[3] };
}

function composite(fg, bg) {
  const a = fg?.a == null ? 1 : fg.a;
  if (!fg || !bg) return null;
  const clamp = (n) => Math.max(0, Math.min(255, n));
  if (a >= 0.999) return { r: clamp(fg.r), g: clamp(fg.g), b: clamp(fg.b), a: 1 };
  return {
    r: clamp(fg.r * a + bg.r * (1 - a)),
    g: clamp(fg.g * a + bg.g * (1 - a)),
    b: clamp(fg.b * a + bg.b * (1 - a)),
    a: 1,
  };
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

async function login(page) {
  await page.goto(`${baseUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.getByPlaceholder('管理账号').fill(username);
  await page.getByPlaceholder('访问密码').fill(password);
  await page.getByRole('button', { name: '进入管理后台' }).click();
  await page.waitForURL((u) => !u.pathname.endsWith('/login'), { timeout: 15000 });
  await page.waitForTimeout(900);
}

async function setTheme(page, mode) {
  await page.evaluate((target) => {
    const isDay = document.documentElement.classList.contains('theme-day');
    if ((target === 'day' && !isDay) || (target === 'night' && isDay)) {
      const btn = document.getElementById('theme-toggle');
      if (btn) btn.click();
    }
  }, mode);
  await page.waitForTimeout(700);
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
  await page.waitForTimeout(700);
}

async function analyze(page, key, mode) {
  const screenshot = path.join(outDir, `${mode}-${key}.png`);
  await page.screenshot({ path: screenshot, fullPage: false });

  const issues = await page.evaluate(({ key, mode }) => {
    function parseRgb(str) {
      if (!str || typeof str !== 'string') return null;
      const m = str.match(/rgba?\(([^)]+)\)/i);
      if (!m) return null;
      const p = m[1].split(',').map((v) => Number(v.trim()));
      if (p.length < 3 || p.some((n) => Number.isNaN(n))) return null;
      return { r: p[0], g: p[1], b: p[2], a: p[3] == null ? 1 : p[3] };
    }
    function composite(fg, bg) {
      if (!fg || !bg) return null;
      const a = fg.a == null ? 1 : fg.a;
      const clamp = (n) => Math.max(0, Math.min(255, n));
      if (a >= 0.999) return { r: clamp(fg.r), g: clamp(fg.g), b: clamp(fg.b), a: 1 };
      return {
        r: clamp(fg.r * a + bg.r * (1 - a)),
        g: clamp(fg.g * a + bg.g * (1 - a)),
        b: clamp(fg.b * a + bg.b * (1 - a)),
        a: 1,
      };
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

    function pickBg(el) {
      const bodyBg = parseRgb(getComputedStyle(document.body).backgroundColor) || { r: 255, g: 255, b: 255, a: 1 };
      let node = el;
      let current = bodyBg;
      let depth = 0;
      while (node && depth < 12) {
        const cs = getComputedStyle(node);
        const bg = parseRgb(cs.backgroundColor);
        if (bg && bg.a > 0) {
          current = composite(bg, current) || current;
          if (bg.a > 0.98) break;
        }
        node = node.parentElement;
        depth += 1;
      }
      return current;
    }

    function ownText(el) {
      const arr = [];
      for (const n of el.childNodes) {
        if (n.nodeType === Node.TEXT_NODE) {
          const t = (n.textContent || '').replace(/\s+/g, ' ').trim();
          if (t) arr.push(t);
        }
      }
      return arr.join(' ').trim();
    }

    const all = Array.from(document.querySelectorAll('body *'));
    const out = [];

    for (const el of all) {
      const cs = getComputedStyle(el);
      if (cs.display === 'none' || cs.visibility === 'hidden') continue;
      if (Number(cs.opacity || '1') < 0.4) continue;
      const rect = el.getBoundingClientRect();
      if (rect.width < 8 || rect.height < 8) continue;

      const text = ownText(el) || (el.tagName === 'INPUT' ? (el.getAttribute('placeholder') || '') : '');
      if (!text) continue;
      if (text.length > 100) continue;

      const fgRaw = parseRgb(cs.color);
      if (!fgRaw) continue;
      const bg = pickBg(el);
      const fg = composite(fgRaw, bg) || fgRaw;
      const ratio = contrast(fg, bg);

      const size = Number.parseFloat(cs.fontSize || '16');
      const weight = Number.parseInt(cs.fontWeight || '400', 10);
      const isLarge = size >= 18 || (size >= 14 && weight >= 700);
      const threshold = isLarge ? 3 : 4.5;

      if (ratio < threshold) {
        out.push({
          view: key,
          mode,
          ratio: Number(ratio.toFixed(2)),
          threshold,
          text: text.slice(0, 80),
          tag: el.tagName,
          cls: (el.className || '').toString().slice(0, 180),
          color: cs.color,
          background: `rgb(${Math.round(bg.r)}, ${Math.round(bg.g)}, ${Math.round(bg.b)})`,
          size,
          weight,
        });
      }
    }

    out.sort((a, b) => a.ratio - b.ratio);
    return out.slice(0, 30);
  }, { key, mode });

  return { key, mode, screenshot, issues };
}

async function safeOpen(page, openFn, closeFn = null) {
  try {
    await openFn();
    await page.waitForTimeout(600);
    return {
      ok: true,
      close: async () => {
        if (closeFn) {
          await closeFn();
          await page.waitForTimeout(300);
        }
      },
    };
  } catch (e) {
    return { ok: false, error: String(e?.message || e), close: async () => {} };
  }
}

const { browser, browserMeta } = await launchPreviewBrowser({ headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'zh-CN' });
const page = await context.newPage();

try {
  await login(page);

  const report = [];

  for (const mode of ['day', 'night']) {
    await setTheme(page, mode);

    for (const tab of ['resource', 'subscription', 'monitor', 'task', 'settings', 'about']) {
      await switchTab(page, tab);
      report.push(await analyze(page, `page-${tab}`, mode));
    }

    await switchTab(page, 'settings');
    {
      const s = await safeOpen(
        page,
        () => page.evaluate(() => window.showHelp && window.showHelp('对比度检查示例文本')),
        () => page.evaluate(() => window.closeHelpModal && window.closeHelpModal()),
      );
      if (s.ok) {
        report.push(await analyze(page, 'modal-help', mode));
      }
      await s.close();
    }

    {
      const s = await safeOpen(
        page,
        () => page.evaluate(() => window.openResourceSourceModal && window.openResourceSourceModal()),
        () => page.evaluate(() => window.closeResourceSourceModal && window.closeResourceSourceModal()),
      );
      if (s.ok) {
        report.push(await analyze(page, 'modal-resource-source', mode));
      }
      await s.close();
    }

    {
      const s = await safeOpen(
        page,
        () => page.evaluate(() => window.openResourceSourceImportModal && window.openResourceSourceImportModal()),
        () => page.evaluate(() => window.closeResourceSourceImportModal && window.closeResourceSourceImportModal()),
      );
      if (s.ok) {
        report.push(await analyze(page, 'modal-resource-source-import', mode));
      }
      await s.close();
    }

    {
      const s = await safeOpen(
        page,
        () => page.evaluate(() => window.openResourceSourceManagerModal && window.openResourceSourceManagerModal()),
        () => page.evaluate(() => window.closeResourceSourceManagerModal && window.closeResourceSourceManagerModal()),
      );
      if (s.ok) {
        report.push(await analyze(page, 'modal-resource-source-manager', mode));
      }
      await s.close();
    }

    await switchTab(page, 'monitor');
    {
      const s = await safeOpen(
        page,
        () => page.evaluate(() => window.openNewMonitorTask && window.openNewMonitorTask()),
        () => page.evaluate(() => window.closeMonitorModal && window.closeMonitorModal()),
      );
      if (s.ok) {
        report.push(await analyze(page, 'modal-monitor', mode));
      }
      await s.close();
    }

    await switchTab(page, 'subscription');
    {
      const s = await safeOpen(
        page,
        () => page.evaluate(() => window.openNewSubscriptionTask && window.openNewSubscriptionTask()),
        () => page.evaluate(() => window.closeSubscriptionModal && window.closeSubscriptionModal()),
      );
      if (s.ok) {
        report.push(await analyze(page, 'modal-subscription', mode));
      }
      await s.close();
    }

    {
      const s = await safeOpen(
        page,
        async () => {
          await page.evaluate(() => window.openNewSubscriptionTask && window.openNewSubscriptionTask());
          await page.waitForTimeout(350);
          await page.evaluate(() => window.openSubscriptionTmdbSearchModal && window.openSubscriptionTmdbSearchModal());
        },
        async () => {
          await page.evaluate(() => window.closeSubscriptionTmdbSearchModal && window.closeSubscriptionTmdbSearchModal());
          await page.evaluate(() => window.closeSubscriptionModal && window.closeSubscriptionModal());
        },
      );
      if (s.ok) {
        report.push(await analyze(page, 'modal-subscription-tmdb', mode));
      }
      await s.close();
    }

    {
      const s = await safeOpen(
        page,
        async () => {
          await page.evaluate(() => window.openNewSubscriptionTask && window.openNewSubscriptionTask());
          await page.waitForTimeout(350);
          await page.evaluate(() => window.openSubscriptionFolderModal && window.openSubscriptionFolderModal());
        },
        async () => {
          await page.evaluate(() => window.closeSubscriptionFolderModal && window.closeSubscriptionFolderModal());
          await page.evaluate(() => window.closeSubscriptionModal && window.closeSubscriptionModal());
        },
      );
      if (s.ok) {
        report.push(await analyze(page, 'modal-subscription-folder', mode));
      }
      await s.close();
    }

    await switchTab(page, 'resource');
    {
      const s = await safeOpen(
        page,
        () => page.evaluate(() => window.toggleResourceJobModal && window.toggleResourceJobModal(true)),
        () => page.evaluate(() => window.toggleResourceJobModal && window.toggleResourceJobModal(false)),
      );
      if (s.ok) {
        report.push(await analyze(page, 'modal-resource-job-list', mode));
      }
      await s.close();
    }

    {
      const s = await safeOpen(
        page,
        async () => {
          await page.locator('[data-resource-action="import"]').first().click({ timeout: 5000 });
        },
        () => page.evaluate(() => window.closeResourceJobModal && window.closeResourceJobModal()),
      );
      if (s.ok) {
        report.push(await analyze(page, 'modal-resource-import', mode));
      }
      await s.close();
    }

    {
      const s = await safeOpen(
        page,
        async () => {
          await page.locator('[data-resource-action="import"]').first().click({ timeout: 5000 });
          await page.waitForTimeout(350);
          await page.evaluate(() => window.openResourceFolderModal && window.openResourceFolderModal());
        },
        async () => {
          await page.evaluate(() => window.closeResourceFolderModal && window.closeResourceFolderModal());
          await page.evaluate(() => window.closeResourceJobModal && window.closeResourceJobModal());
        },
      );
      if (s.ok) {
        report.push(await analyze(page, 'modal-resource-folder', mode));
      }
      await s.close();
    }
  }

  const summary = report
    .map((item) => ({ view: `${item.mode}:${item.key}`, issueCount: item.issues.length, worst: item.issues[0] || null }))
    .sort((a, b) => (a.worst?.ratio ?? 99) - (b.worst?.ratio ?? 99));

  const result = { outDir, browser: browserMeta, summary: summary.slice(0, 40), report };
  const jsonFile = path.resolve('/tmp', 'contrast-audit.json');
  await fs.promises.writeFile(jsonFile, JSON.stringify(result, null, 2));
  console.log(JSON.stringify({ outDir, browser: browserMeta, jsonFile, worst: summary.slice(0, 25) }, null, 2));
} finally {
  await context.close();
  await browser.close();
}
