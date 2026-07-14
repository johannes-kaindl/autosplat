// E2E for pose-authoring: the ?authoring=1 copy-pose button's visibility
// gate. Real clipboard/pose-value verification is out of scope for headless
// E2E (see embed-smoke.test.mjs's rationale) — covered by the manual smoke
// in the pose-authoring design spec instead.
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { setTimeout as wait } from 'node:timers/promises';
import puppeteer from 'puppeteer-core';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, '..', '..');          // embed/
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const PORT = 8132;
const URL_BASE = `http://localhost:${PORT}`;

let server = null;
let browser = null;

before(async () => {
  server = spawn('python3', ['-m', 'http.server', String(PORT)], {
    cwd: ROOT, stdio: ['ignore', 'pipe', 'pipe'],
  });
  for (let i = 0; i < 30; i++) {
    try { const r = await fetch(URL_BASE + '/'); if (r.ok) break; }
    catch { /* still booting */ }
    await wait(100);
  }
  browser = await puppeteer.launch({
    executablePath: CHROME, headless: 'new',
    args: ['--no-sandbox', '--disable-features=Translate', '--hide-scrollbars'],
  });
});

after(async () => {
  if (browser) await browser.close();
  if (server) { server.kill(); await wait(200); }
});

test('authoring=1 with broken src: copy-pose button stays hidden through the error state', async () => {
  const page = await browser.newPage();
  await page.goto(URL_BASE + '/?src=does-not-exist.sog&authoring=1',
                  { waitUntil: 'domcontentloaded' });
  await page.click('#gate');
  await page.waitForFunction(
    () => !document.getElementById('error-card').hidden, { timeout: 30000 });
  const hidden = await page.evaluate(
    () => document.getElementById('btn-copy-pose').hidden);
  assert.equal(hidden, true, 'copy-pose button hidden while load failed');
  await page.close();
});

test('without authoring param: copy-pose button stays hidden regardless of state', async () => {
  const page = await browser.newPage();
  await page.goto(URL_BASE + '/?src=does-not-exist.sog',
                  { waitUntil: 'domcontentloaded' });
  const beforeClick = await page.evaluate(
    () => document.getElementById('btn-copy-pose').hidden);
  assert.equal(beforeClick, true, 'hidden before any interaction');
  await page.click('#gate');
  await page.waitForFunction(
    () => !document.getElementById('error-card').hidden, { timeout: 30000 });
  const afterError = await page.evaluate(
    () => document.getElementById('btn-copy-pose').hidden);
  assert.equal(afterError, true, 'still hidden after error state');
  await page.close();
});
