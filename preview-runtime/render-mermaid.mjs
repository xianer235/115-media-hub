#!/usr/bin/env node
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { launchPreviewBrowser } from './browser-launch.mjs';

const [inputArg, outputArg] = process.argv.slice(2);
if (!inputArg || !outputArg) {
  console.error('Usage: node render-mermaid.mjs <input.mmd> <output.png>');
  process.exit(1);
}

const inputPath = path.resolve(inputArg);
const outputPath = path.resolve(outputArg);
const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const mermaidBundlePath = path.join(scriptDir, 'node_modules', 'mermaid', 'dist', 'mermaid.min.js');

const diagramText = await fs.readFile(inputPath, 'utf8');
const mermaidBundle = (await fs.readFile(mermaidBundlePath, 'utf8')).replace(/<\/script>/gi, '<\\/script>');

const html = `<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <style>
    html, body {
      margin: 0;
      padding: 0;
      background: #ffffff;
      width: max-content;
      height: max-content;
      font-family: "PingFang SC", "Microsoft YaHei", Arial, sans-serif;
    }
    #canvas {
      display: inline-block;
      padding: 52px;
      background: #ffffff;
      overflow: visible;
    }
    .mermaid {
      display: inline-block;
      overflow: visible;
    }
    .mermaid svg {
      max-width: none !important;
      height: auto !important;
      overflow: visible !important;
    }
  </style>
</head>
<body>
  <div id="canvas">
    <pre class="mermaid" id="diagram"></pre>
  </div>
  <script>
    ${mermaidBundle}
  </script>
  <script>
    const diagram = ${JSON.stringify(diagramText)};
    document.getElementById('diagram').textContent = diagram;
    window.mermaid.initialize({
      startOnLoad: false,
      securityLevel: "loose",
      fontFamily: "PingFang SC, Microsoft YaHei, Arial"
    });
    window.mermaid.run({ querySelector: ".mermaid" })
      .then(() => { window.__MERMAID_DONE__ = true; })
      .catch((err) => {
        window.__MERMAID_ERROR__ = String(err && err.message ? err.message : err || "mermaid run failed");
      });
  </script>
</body>
</html>`;

const { browser } = await launchPreviewBrowser({ headless: true });
try {
  const context = await browser.newContext({
    viewport: { width: 4000, height: 3200 },
    deviceScaleFactor: 3
  });
  const page = await context.newPage();
  await page.setContent(html, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => typeof window.mermaid !== 'undefined', { timeout: 20000 });
  await page.waitForFunction(() => !window.__MERMAID_ERROR__, { timeout: 20000 });
  await page.waitForFunction(() => window.__MERMAID_DONE__ === true, { timeout: 20000 });
  await page.waitForSelector('#canvas svg', { timeout: 20000 });
  await page.locator('#canvas').screenshot({
    path: outputPath,
    type: 'png',
    animations: 'disabled'
  });
  await context.close();
} finally {
  await browser.close();
}

console.log(`Rendered: ${outputPath}`);
