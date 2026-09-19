import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const require = createRequire(path.join(root, 'tests/js/package.json'));
const { JSDOM } = require('jsdom');
const src = readFileSync(path.join(root, 'neurosearch/web/js/sources.js'), 'utf8').replace(/^export const moduleName.*$/m, '');
const dom = new JSDOM('<!doctype html><textarea id="inUrls"></textarea><div id="subredditCatalogs"></div>', { url: 'https://fixture.invalid/', runScripts: 'outside-only' });
const w = dom.window;
w.$ = selector => w.document.querySelector(selector);
w.esc = value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#39;');
w.state = { project: { id: 'one' } };
w.toast = w.loadJobs = () => {};
w.eval(src);
const defer = () => { let resolve, reject; const promise = new Promise((r, j) => { resolve = r; reject = j; }); return { promise, resolve, reject }; };
const response = title => ({ revision: title, collection: { url: 'https://www.reddit.com/r/fixture/' }, total: 1,
  mode: 'recommended', state: 'available', items: [{ id: title, title, url: 'https://www.reddit.com/r/fixture/comments/a/',
    capture_status: 'not_captured', state: 'available', metadata: {}, why: [] }], next_page: null });
const scenario = process.argv[2];
try {
  if (scenario === 'escape') {
    w.api = async () => ({ items: [{ id: 'catalog', external_id: 'fixture', scan: {
      status: 'blocked', error: '<img id="injected" src=x onerror="alert(1)">', observed_oldest: '<b id="date-injected">bad</b>'
    } }] });
    await w.loadSubredditCatalogs();
    assert.equal(w.document.querySelector('#injected'), null, 'scan error must render as text, not markup');
    assert.equal(w.document.querySelector('#date-injected'), null);
    assert.ok(w.$('#subredditCatalogs').textContent.includes('<img'));
  } else if (scenario === 'project-switch') {
    const waiting = defer(), entered = defer();
    w.api = async url => url.endsWith('/yield') ? (entered.resolve(), waiting.promise) : response('old-project');
    const old = w.openSubredditCatalog('catalog');
    await entered.promise;
    w.state.project = { id: 'two' };
    w.$('#subredditCatalogs').textContent = 'new project';
    waiting.resolve({ captured_threads: 0, findings: 0, distinct_claims_supported: 0 });
    await old;
    assert.equal(w.$('#subredditCatalogs').textContent, 'new project', 'late yield response must not paint old project');
  } else if (scenario === 'query-race') {
    const waiting = defer(), entered = defer();
    w.api = async url => url.endsWith('/yield') ? {} : (entered.resolve(), waiting.promise);
    const old = w.openSubredditCatalog('catalog');
    await entered.promise;
    w.CATALOG.q = 'new-query';
    w.api = async url => url.endsWith('/yield') ? {} : response('new-result');
    await w.openSubredditCatalog('catalog', false);
    waiting.resolve(response('old-result'));
    await old;
    assert.ok(w.$('#subredditCatalogs').textContent.includes('new-result'));
    assert.ok(!w.$('#subredditCatalogs').textContent.includes('old-result'), 'late prior query must not replace current rows');
    assert.deepEqual(Array.from(w.CATALOG.visibleIds), ['new-result']);
  } else if (scenario === 'stale-action') {
    const posts = [];
    w.api = async url => url.endsWith('/yield') ? {} : response('old-result');
    await w.openSubredditCatalog('catalog');
    w.state.project = { id: 'two' };
    w.post = async (...args) => { posts.push(args); return {}; };
    await w.catalogCaptureDisplayed('catalog', null);
    assert.equal(posts.length, 0, 'stale displayed selection must not mutate the new project');
  } else if (scenario === 'stale-row-actions' || scenario === 'stale-card-actions') {
    const posts = [];
    w.api = async url => url.endsWith('/yield') ? {} : response('old-result');
    await w.openSubredditCatalog('catalog');
    w.state.project = { id: 'two' };
    w.post = async (...args) => { posts.push(args); return {}; };
    w.prompt = () => { throw Error('stale view must not prompt'); };
    if (scenario === 'stale-row-actions') {
      await w.catalogCapture('old-result', 'catalog');
      await w.catalogAct('old-result', 'catalog', 'dismiss');
      await w.catalogAct('old-result', 'catalog', 'restore');
    } else {
      await w.refreshSubredditCatalog('catalog', null, 'one');
      await w.cancelSubredditCatalog('catalog', null, 'one');
      await w.openSubredditCatalog('catalog', true, 'one');
    }
    assert.equal(posts.length, 0);
    assert.equal(w.CATALOG.projectId, 'one');
  } else if (scenario === 'stale-error') {
    const waiting = defer(), entered = defer();
    const errors = [];
    w.toast = msg => errors.push(msg);
    w.api = async () => (entered.resolve(), waiting.promise);
    const old = w.openSubredditCatalog('catalog');
    await entered.promise;
    w.api = async url => url.endsWith('/yield') ? {} : response('new-result');
    await w.openSubredditCatalog('catalog', false);
    waiting.reject(Error('revision changed'));
    await old;
    assert.equal(w.CATALOG.revision, 'new-result');
    assert.deepEqual(errors, []);
  } else if (scenario === 'late-action') {
    const waiting = defer(), entered = defer();
    w.api = async url => url.endsWith('/yield') ? {} : response('old-result');
    await w.openSubredditCatalog('catalog');
    w.post = async url => { assert.ok(url.startsWith('/api/projects/one/')); entered.resolve(); return waiting.promise; };
    const old = w.catalogCapture('old-result', 'catalog');
    await entered.promise;
    w.state.project = { id: 'two' };
    w.api = async url => url.endsWith('/yield') ? {} : response('new-result');
    await w.openSubredditCatalog('catalog');
    waiting.resolve({ job_id: 'job' });
    await old;
    assert.equal(w.CATALOG.revision, 'new-result');
    assert.ok(!w.$('#subredditCatalogs').textContent.includes('old-result'));
  } else if (scenario === 'pending-action') {
    w.api = async url => url.endsWith('/yield') ? {} : response('old-result');
    await w.openSubredditCatalog('catalog');
    const waiting = defer(), entered = defer(), posts = [];
    w.api = async url => url.endsWith('/yield') ? {} : (entered.resolve(), waiting.promise);
    const next = w.openSubredditCatalog('catalog', false);
    await entered.promise;
    w.post = async (...args) => posts.push(args);
    await w.catalogCaptureDisplayed('catalog');
    assert.equal(posts.length, 0, 'loading results must not use the previously displayed selection');
    waiting.resolve(response('new-result')); await next;
  } else if (scenario === 'project-reset') {
    w.api = async url => url.endsWith('/yield') ? {} : response('old-result');
    await w.openSubredditCatalog('catalog');
    w.CATALOG.q = 'old query'; w.CATALOG.page = 9;
    w.state.project = { id: 'two' };
    await w.openSubredditCatalog('catalog', false);
    assert.equal(w.CATALOG.q, ''); assert.equal(w.CATALOG.page, 0);
    assert.equal(w.CATALOG.projectId, 'two');
  } else throw Error('unknown scenario');
  console.log('PASS ' + scenario);
} finally { w.close(); }
