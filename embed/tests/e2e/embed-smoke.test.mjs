// End-to-end smoke for the embed page: DOM lifecycle of gate/hint/error.
// Uses puppeteer-core + system Chrome. Real splat rendering is verified
// manually with ../serve.sh — headless GL is not a fidelity reference,
// which is also why the error-message assertion tolerates the WebGL2 path.
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
const PORT = 8131;
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

test('no src: dropzone shown, gate + controls stay hidden', async () => {
  const page = await browser.newPage();
  await page.goto(URL_BASE + '/', { waitUntil: 'domcontentloaded' });
  const s = await page.evaluate(() => ({
    dropzone: !document.getElementById('dropzone').hidden,
    hint: document.getElementById('hint-card').hidden,
    gate: document.getElementById('gate').hidden,
    controls: document.getElementById('controls').hidden,
  }));
  assert.equal(s.dropzone, true, 'dropzone visible');
  assert.equal(s.hint, true, 'hint card hidden');
  assert.equal(s.gate, true, 'gate hidden');
  assert.equal(s.controls, true, 'controls hidden');
  await page.close();
});

test('with src: gate shown with scene label, hint hidden', async () => {
  const page = await browser.newPage();
  await page.goto(URL_BASE + '/?src=c/max_strasse.sog',
                  { waitUntil: 'domcontentloaded' });
  const s = await page.evaluate(() => ({
    gateHidden: document.getElementById('gate').hidden,
    label: document.getElementById('gate-label').textContent,
    hintHidden: document.getElementById('hint-card').hidden,
  }));
  assert.equal(s.gateHidden, false, 'gate visible');
  assert.equal(s.label, 'max strasse');
  assert.equal(s.hintHidden, true, 'hint hidden');
  await page.close();
});

test('poster param: gate gets background image + has-poster class', async () => {
  const page = await browser.newPage();
  await page.goto(URL_BASE + '/?src=x.sog&poster=poster.jpg',
                  { waitUntil: 'domcontentloaded' });
  const s = await page.evaluate(() => ({
    cls: document.getElementById('gate').classList.contains('has-poster'),
    bg: document.getElementById('gate').style.backgroundImage,
  }));
  assert.equal(s.cls, true);
  assert.match(s.bg, /poster\.jpg/);
  await page.close();
});

test('gate click with broken src: error card with retry appears', async () => {
  const page = await browser.newPage();
  await page.goto(URL_BASE + '/?src=does-not-exist.sog',
                  { waitUntil: 'domcontentloaded' });
  await page.click('#gate');
  await page.waitForFunction(
    () => !document.getElementById('error-card').hidden, { timeout: 30000 });
  const s = await page.evaluate(() => ({
    msg: document.getElementById('error-msg').textContent,
    retry: !!document.getElementById('btn-retry'),
    spinnerHidden: document.getElementById('spinner').hidden,
  }));
  assert.match(s.msg, /Could not load|WebGL2/);
  assert.equal(s.retry, true, 'retry button present');
  assert.equal(s.spinnerHidden, true, 'spinner gone');
  await page.close();
});

test('autoplay=1: gate never shows, load starts immediately', async () => {
  const page = await browser.newPage();
  await page.goto(URL_BASE + '/?src=does-not-exist.sog&autoplay=1',
                  { waitUntil: 'domcontentloaded' });
  const gateHidden = await page.evaluate(
    () => document.getElementById('gate').hidden);
  assert.equal(gateHidden, true, 'gate stays hidden with autoplay');
  await page.waitForFunction(
    () => !document.getElementById('error-card').hidden, { timeout: 30000 });
  await page.close();
});
