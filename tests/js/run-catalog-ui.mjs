import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const require = createRequire(path.join(root, 'tests/js/package.json'));
const { JSDOM } = require('jsdom');
const src = readFileSync(path.join(root, 'neurosearch/web/js/sources.js'), 'utf8').replace(/^export const moduleName.*$/m, '');
const dom = new JSDOM('<!doctype html><textarea id="inUrls"></textarea><input id="libQ"><input id="candQ"><select id="candState"></select><div id="library"></div><div id="candCounts"></div><div id="candidates"></div><div id="subredditCatalogs"></div>', { url: 'https://fixture.invalid/', runScripts: 'outside-only' });
const w = dom.window;
w.$ = selector => w.document.querySelector(selector);
w.esc = value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#39;');
w.state = { project: { id: 'one' } };
w.toast = w.loadJobs = () => {};
w.ICON = {}; w.fmt = value => String(value);
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
  } else if (scenario === 'selected-capture') {
    const item = title => ({ id: title, title, url: 'https://www.reddit.com/r/fixture/comments/' + title + '/', capture_status: 'not_captured', state: 'available', metadata: {}, why: [] });
    w.api = async url => {
      if (url.endsWith('/yield')) return {};
      return url.includes('page=1') ? { ...response('second'), total: 2, page: 1, items: [item('second')], next_page: null } : { ...response('first'), total: 2, page: 0, items: [item('first')], next_page: 1 };
    };
    await w.openSubredditCatalog('catalog');
    assert.equal(w.document.querySelectorAll('input[type="checkbox"]').length, 1);
    await w.toggleCatalogCandidate('first', 'catalog', true);
    w.CATALOG.page = 1;
    await w.openSubredditCatalog('catalog', false);
    await w.toggleCatalogCandidate('second', 'catalog', true);
    assert.equal(w.$('#subredditCatalogDetail').textContent.includes('Capture selected (2)'), true);
    const posts = [];
    w.post = async (url, body) => { posts.push({ url, body }); return { attached: 0, jobs_queued: 2, failed: [] }; };
    await w.catalogCaptureSelected('catalog');
    assert.deepEqual(Array.from(posts[0].body.candidate_ids), ['first', 'second']);
    assert.equal(w.CATALOG.selectedIds.size, 0);
  } else if (scenario === 'draft-focus') {
    w.api = async url => url.endsWith('/yield') ? {} : response('one');
    await w.openSubredditCatalog('catalog');
    const input = w.$('#subredditCatalogSearch');
    input.focus(); input.value = 'unsent title'; input.setSelectionRange(3, 8);
    await w.openSubredditCatalog('catalog', false);
    const restored = w.$('#subredditCatalogSearch');
    assert.equal(restored.value, 'unsent title');
    assert.equal(w.document.activeElement, restored);
    assert.deepEqual([restored.selectionStart, restored.selectionEnd], [3, 8]);
  } else if (scenario === 'reset-source-project') {
    w.$('#library').textContent = 'old library'; w.$('#candidates').textContent = 'old candidates'; w.$('#subredditCatalogs').textContent = 'old catalog';
    w.CATALOG = { ...w.CATALOG, id: 'catalog', selectedIds: new Set(['one']) };
    w.resetSourceProjectState();
    assert.equal(w.$('#library').textContent, ''); assert.equal(w.$('#candidates').textContent, ''); assert.equal(w.$('#subredditCatalogs').textContent, '');
    assert.equal(w.CATALOG.id, null); assert.equal(w.CATALOG.selectedIds.size, 0);
  } else if (scenario === 'filtered-count') {
    w.api = async url => url.endsWith('/yield') ? {} : response('one');
    await w.openSubredditCatalog('catalog');
    w.CATALOG.q = 'one';
    await w.openSubredditCatalog('catalog', false);
    assert.ok(w.$('#subredditCatalogDetail').textContent.includes('1 matching'));
  } else if (scenario === 'late-library') {
    const waiting = defer();
    w.api = async () => waiting.promise;
    const old = w.loadLibrary();
    w.state.project = { id: 'two' }; w.resetSourceProjectState();
    waiting.resolve([{ id: 'old', title: 'old source' }]); await old;
    assert.equal(w.$('#library').textContent, '');
  } else throw Error('unknown scenario');
  console.log('PASS ' + scenario);
} finally { w.close(); }
