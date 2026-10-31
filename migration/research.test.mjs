import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { createCounterexample } from './counterexample.mjs';
import { mountStudy } from './article.mjs';

const require = createRequire(import.meta.url);
const initSqlJs = require('./vendor/sql-wasm.js');
const SQL = await initSqlJs({ locateFile: file => fileURLToPath(new URL(`./vendor/${file}`, import.meta.url)) });
const fixture = await readFile(new URL('../data/reward-migrations/browser-fixture.sqlite', import.meta.url));
const manifest = JSON.parse(await readFile(new URL('../data/reward-migrations/browser-fixture.manifest.json', import.meta.url), 'utf8'));
const html = await readFile(new URL('../blog.html', import.meta.url), 'utf8');
const { JSDOM } = require(process.env.LATENT_JSDOM_PATH || '/tmp/latent-dom-check/node_modules/jsdom');
const turn = () => new Promise(resolve => setImmediate(resolve));

test('published fixture is exactly the native-verified asset', () => {
  assert.equal(fixture.byteLength, manifest.fixture.bytes);
  assert.equal(createHash('sha256').update(fixture).digest('hex'), manifest.fixture.sha256);
});

test('WASM SQLite independently reproduces the full-database scalar witness', () => {
  const experiment = createCounterexample(SQL, fixture, manifest);
  assert.equal(experiment.baseline.reward, 1);
  assert.equal(experiment.baseline.transactions, 425);
  assert.equal(experiment.baseline.customers, 259);
  for (let i = 0; i < 3; i++) {
    const after = experiment.addTransaction();
    assert.equal(after.candidate, 3.088803088803089);
    assert.equal(after.reference, 2.7027027027027026);
    assert.equal(after.reward, 0);
    assert.equal(after.transactions, 426);
    assert.equal(after.eurTransactions, 8);
    assert.equal(after.eurCustomers, 7);
    assert.equal(after.customers, 259);
    assert.throws(() => experiment.addTransaction(), /Reset/);
    assert.deepEqual(experiment.reset(), experiment.baseline);
  }
  experiment.close();
});

test('recorded figure switches real cases and references with correct accessible state', () => {
  const dom = new JSDOM(html);
  const doc = dom.window.document;
  mountStudy(doc);
  assert.equal(doc.getElementById('case-reward').textContent, '0');
  doc.querySelector('[data-version="new"]').click();
  assert.equal(doc.getElementById('case-reward').textContent, '1');
  assert.equal(doc.querySelector('[data-version="new"]').getAttribute('aria-pressed'), 'true');
  assert.equal(doc.querySelector('[data-version="old"]').getAttribute('aria-pressed'), 'false');
  doc.querySelector('[data-case="115"]').click();
  assert.equal(doc.getElementById('case-reward').textContent, '0');
  assert.match(doc.getElementById('case-explanation').textContent, /177,686/);
  assert.match(doc.getElementById('case-record').getAttribute('href'), /115\.json$/);
  doc.querySelector('[data-version="old"]').click();
  assert.equal(doc.getElementById('case-reward').textContent, '1');
  assert.equal(doc.querySelectorAll('[data-case][aria-pressed="true"]').length, 1);
  dom.window.close();
});

test('article executes the real SQL mutation, then resets the actual database', async () => {
  const dom = new JSDOM(html);
  const doc = dom.window.document;
  let loads = 0;
  const controller = mountStudy(doc, { databaseFactory: async () => {
    loads++;
    return createCounterexample(SQL, fixture, manifest);
  } });
  const button = doc.getElementById('add-transaction');
  button.click();
  button.click();
  await turn();
  assert.equal(loads, 1);
  assert.equal(doc.getElementById('live-candidate').textContent, '3.088803%');
  assert.equal(doc.getElementById('live-reference').textContent, '2.702703%');
  assert.equal(doc.getElementById('live-reward').textContent, '0');
  assert.equal(doc.getElementById('live-customers').textContent, '259');
  assert.equal(doc.getElementById('live-eur-customers').textContent, '7');
  assert.equal(button.disabled, true);
  assert.equal(button.hasAttribute('aria-busy'), false);
  doc.getElementById('reset-transaction').click();
  assert.equal(doc.getElementById('live-reward').textContent, '1');
  assert.equal(doc.getElementById('live-transactions').textContent, '425');
  assert.equal(button.disabled, false);
  button.click();
  await turn();
  assert.equal(loads, 1);
  assert.equal(doc.getElementById('live-reward').textContent, '0');
  controller.dispose();
  dom.window.close();
});

test('loading failure is visible, does not invent a result, and can be retried', async () => {
  const dom = new JSDOM(html);
  const doc = dom.window.document;
  let attempts = 0;
  const controller = mountStudy(doc, { databaseFactory: async () => {
    if (++attempts === 1) throw new Error('Test: fixture unavailable.');
    return createCounterexample(SQL, fixture, manifest);
  } });
  doc.getElementById('add-transaction').click();
  await turn();
  assert.match(doc.getElementById('live-status').textContent, /fixture unavailable/);
  assert.equal(doc.getElementById('live-reward').textContent, '1');
  assert.equal(doc.getElementById('add-transaction').disabled, false);
  doc.getElementById('add-transaction').click();
  await turn();
  assert.equal(doc.getElementById('live-reward').textContent, '0');
  controller.dispose();
  dom.window.close();
});

test('page is a single research article with complete fallback content and unique IDs', () => {
  const dom = new JSDOM(html);
  const doc = dom.window.document;
  assert.equal(doc.querySelectorAll('h1').length, 1);
  assert.equal(doc.querySelectorAll('article').length, 1);
  assert.equal(doc.querySelectorAll('select').length, 0);
  const ids = [...doc.querySelectorAll('[id]')].map(element => element.id);
  assert.equal(new Set(ids).size, ids.length);
  for (const link of doc.querySelectorAll('a[href^="#"]')) {
    assert.ok(doc.getElementById(link.getAttribute('href').slice(1)));
  }
  assert.match(doc.getElementById('recorded-witness').textContent, /Recorded transition: 0 → 1/);
  assert.match(doc.querySelector('.counterexample figcaption').textContent, /3\.088803/);
  assert.equal(doc.getElementById('add-transaction').disabled, true); // honest no-JS fallback
  dom.window.close();
});
