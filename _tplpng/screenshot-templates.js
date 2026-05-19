// Capture preview screenshots for the AIUI App Builder template gallery.
const { chromium } = require('playwright');

const BASE = 'https://ai-ui.coolestdomain.win/api/template-preview';
const TEMPLATES = ['landing', 'portfolio', 'crud', 'dashboard', 'invoice'];
const OUT_DIR = 'C:/Users/alama/Desktop/Lukas Work/IO/_tplpng';

(async () => {
  const browser = await chromium.launch({ headless: false });
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await ctx.newPage();

  for (const key of TEMPLATES) {
    const url = `${BASE}/${key}/index.html`;
    console.log(`\n=== ${key} ===`);
    console.log(`Loading: ${url}`);
    try {
      await page.goto(url, { waitUntil: 'networkidle', timeout: 15000 });
    } catch (e) {
      console.log(`  WARN: ${e.message}`);
    }
    await page.waitForTimeout(2000);

    const out = `${OUT_DIR}/new-${key}.png`;
    await page.screenshot({ path: out, fullPage: false });
    const size = require('fs').statSync(out).size;
    console.log(`  saved -> ${out} (${size} bytes)`);
  }

  await browser.close();
  console.log('\nDone.');
})();
