import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { launchPreviewBrowser } from './browser-launch.mjs';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const outDir = path.join(scriptDir, 'shots', 'quick-link-preview');
const reportFile = path.join(outDir, 'report.json');

const baseUrl = String(process.env.PREVIEW_BASE_URL || 'http://127.0.0.1:18080').trim();
const username = String(process.env.PREVIEW_USERNAME || 'admin').trim();
const password = String(process.env.PREVIEW_PASSWORD || 'admin123').trim();
const locale = String(process.env.PREVIEW_LOCALE || 'zh-CN').trim() || 'zh-CN';
const viewportWidth = Number.parseInt(String(process.env.PREVIEW_WIDTH || '1512'), 10) || 1512;
const viewportHeight = Number.parseInt(String(process.env.PREVIEW_HEIGHT || '920'), 10) || 920;
const headless = String(process.env.PREVIEW_HEADLESS || 'true').trim().toLowerCase() !== 'false';

await fs.mkdir(outDir, { recursive: true });

function runLabel() {
  const now = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
}

function screenshotPath(name) {
  return path.join(outDir, `${name}.png`);
}

async function login(page) {
  await page.goto(`${baseUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.getByPlaceholder('管理账号').fill(username);
  await page.getByPlaceholder('访问密码').fill(password);
  await page.getByRole('button', { name: '进入管理后台' }).click();
  await page.waitForURL((u) => !u.pathname.endsWith('/login'), { timeout: 15000 });
  await page.waitForTimeout(900);
}

async function switchToResourceTab(page) {
  const tab = page.locator('#tab-resource');
  await tab.waitFor({ state: 'visible', timeout: 10000 });
  await tab.click();
  await page.waitForTimeout(500);
}

async function setTheme(page, mode) {
  await page.evaluate((target) => {
    const isDay = document.documentElement.classList.contains('theme-day');
    if ((target === 'day' && !isDay) || (target === 'night' && isDay)) {
      document.getElementById('theme-toggle')?.click();
    }
  }, mode);
  await page.waitForTimeout(700);
}

async function openQuickLinkModal(page) {
  const manageBtn = page.locator('[data-resource-quick-link-action="manage"]').first();
  await manageBtn.waitFor({ state: 'visible', timeout: 12000 });
  await manageBtn.click();
  const modal = page.locator('#resource-quick-link-modal');
  await modal.waitFor({ state: 'visible', timeout: 6000 });
  await page.waitForTimeout(260);
}

async function closeQuickLinkModal(page) {
  await page.evaluate(() => {
    if (typeof window.closeResourceQuickLinkModal === 'function') {
      window.closeResourceQuickLinkModal();
      return;
    }
    const modal = document.getElementById('resource-quick-link-modal');
    if (modal) modal.classList.add('hidden');
  });
  await page.waitForTimeout(220);
}

async function ensureSampleQuickLink(page) {
  const rows = page.locator('#resource-quick-link-list .resource-quick-link-item');
  const count = await rows.count();
  if (count > 0) {
    return { seeded: false };
  }
  const suffix = Date.now().toString(36).slice(-5);
  const sampleName = `预览测试-${suffix}`;
  const sampleUrl = `https://example.com/s/preview-${suffix}`;
  await page.fill('#resource-quick-link-name', sampleName);
  await page.fill('#resource-quick-link-url', sampleUrl);
  await page.click('#resource-quick-link-save-btn');
  await rows.first().waitFor({ state: 'visible', timeout: 6000 });
  await page.waitForTimeout(240);
  return { seeded: true, sampleName, sampleUrl };
}

async function capture(page, name) {
  const file = screenshotPath(name);
  await page.screenshot({ path: file, fullPage: false });
  return file;
}

async function readRowMetrics(page) {
  return page.evaluate(() => {
    const getRect = (el) => {
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return {
        top: Math.round(r.top),
        bottom: Math.round(r.bottom),
        left: Math.round(r.left),
        right: Math.round(r.right),
        height: Math.round(r.height),
      };
    };
    const input = document.getElementById('resource-search-input');
    const search = document.getElementById('resource-search-btn');
    const sync = document.getElementById('resource-sync-btn');
    const strip = document.getElementById('resource-quick-link-strip');
    return {
      input: getRect(input),
      search: getRect(search),
      sync: getRect(sync),
      sameRow: !!(input && sync && Math.abs(input.getBoundingClientRect().top - sync.getBoundingClientRect().top) < 4),
      quickStripText: String(strip?.textContent || '').replace(/\s+/g, ' ').trim(),
    };
  });
}

async function readQuickLinkStyles(page) {
  return page.evaluate(() => {
    const pick = (selector) => {
      const el = document.querySelector(selector);
      if (!el) return null;
      const cs = getComputedStyle(el);
      return {
        color: cs.color,
        background: cs.backgroundColor,
        border: cs.borderColor,
        boxShadow: cs.boxShadow,
      };
    };
    return {
      htmlClass: document.documentElement.className,
      modal: pick('#resource-quick-link-modal .resource-quick-link-modal-shell'),
      manageBtn: pick('#resource-quick-link-strip .resource-quick-link-manage-btn'),
      fieldLabel: pick('.resource-quick-link-field-label'),
      input: pick('.resource-quick-link-input'),
      note: pick('.resource-quick-link-note'),
      card: pick('#resource-quick-link-list .resource-quick-link-item'),
      actionPrimary: pick('#resource-quick-link-list .resource-quick-link-item-action-primary'),
      actionNormal: pick('#resource-quick-link-list .resource-quick-link-item-action:not(.resource-quick-link-item-action-primary):not(.resource-quick-link-item-action-danger)'),
      actionDanger: pick('#resource-quick-link-list .resource-quick-link-item-action-danger'),
    };
  });
}

const { browser, browserMeta } = await launchPreviewBrowser({ headless });
const context = await browser.newContext({
  viewport: { width: viewportWidth, height: viewportHeight },
  locale,
});
const page = await context.newPage();
const runId = runLabel();

try {
  await login(page);
  await switchToResourceTab(page);

  const report = {
    runId,
    generatedAt: new Date().toISOString(),
    config: {
      baseUrl,
      browser: browserMeta,
      locale,
      viewport: { width: viewportWidth, height: viewportHeight },
      headless,
    },
    output: {},
  };

  await setTheme(page, 'night');
  await switchToResourceTab(page);
  report.output.resourcePanelNight = await capture(page, 'resource-panel-night');
  report.output.rowNight = await readRowMetrics(page);

  await openQuickLinkModal(page);
  report.output.seed = await ensureSampleQuickLink(page);
  report.output.quickLinkModalNight = await capture(page, 'resource-quick-link-modal-night');
  report.output.stylesNight = await readQuickLinkStyles(page);
  await closeQuickLinkModal(page);

  await setTheme(page, 'day');
  await switchToResourceTab(page);
  report.output.resourcePanelDay = await capture(page, 'resource-panel-day');
  report.output.rowDay = await readRowMetrics(page);

  await openQuickLinkModal(page);
  await ensureSampleQuickLink(page);
  report.output.quickLinkModalDay = await capture(page, 'resource-quick-link-modal-day');
  report.output.stylesDay = await readQuickLinkStyles(page);
  await closeQuickLinkModal(page);

  await fs.writeFile(reportFile, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
  console.log(JSON.stringify({ outDir, reportFile, runId, sameRowDay: report.output.rowDay?.sameRow, sameRowNight: report.output.rowNight?.sameRow }, null, 2));
} finally {
  await context.close();
  await browser.close();
}
