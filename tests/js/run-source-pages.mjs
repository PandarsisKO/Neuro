import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { JSDOM } from 'jsdom';

const web = new URL('../../neurosearch/web/', import.meta.url);
const read = (file) => readFileSync(new URL(file, web), 'utf8');
const dom = new JSDOM(read('index.html'), { url: 'http://localhost/', runScripts: 'outside-only' });
const { window } = dom;
const byId = (id) => window.document.getElementById(id);

try {
  window.$ = (selector) => window.document.querySelector(selector);
  window.state = { project: { id: 'test-project' }, srcFilter: 'all' };
  window.listState = (_, { label }) => label;
  window.POLL = { enter: () => true, leave: () => {} };
  window.eval(read('js/sources.js').replace(/^export const moduleName.*$/m, ''));
  window.loadReviews = () => {};
  window.loadCaptionRecovery = () => {};
  window.loadCaptureQueue = () => {};
  window.srcRowHtml = (source) => `<div class="src">${source.id}</div>`;
  window.POOL.total = 0;
  byId('srcGroupToggle').checked = false;

  const sources = Array.from({ length: 2002 }, (_, i) => ({
    id: `source-${i}`, platform: 'manual', created_at: i, status: i === 0 ? 'failed' : 'ready',
  }));
  let requests = 0;
  window.api = async (url) => {
    requests++;
    const params = new URL(url, 'http://localhost/').searchParams;
    assert.equal(params.get('all_project_rows'), 'true');
    return params.has('q') ? [sources[1]] : [...sources];
  };

  await window.loadSources();
  assert.equal(byId('srcRange').textContent, '1–150 of 2002');
  assert.equal(byId('srcList').children.length, 150);
  assert.equal(byId('srcPrevious').disabled, true);

  for (let page = 0; page < 13; page++) window.turnSourcesPage(1);
  assert.equal(byId('srcRange').textContent, '1951–2002 of 2002');
  assert.equal(byId('srcList').lastElementChild.textContent, 'source-0');
  assert.equal(byId('srcNext').disabled, true);
  assert.equal(requests, 1, 'paging should stay local');

  await window.loadSources(true);
  assert.equal(byId('srcRange').textContent, '1951–2002 of 2002', 'polling should keep the current page');
  window.state.srcFilter = 'failed';
  window.filterSources();
  assert.equal(byId('srcList').textContent, 'source-0');
  assert.equal(byId('srcPager').hidden, true);
  assert.equal(requests, 2, 'filtering should stay local');

  window.state.srcFilter = 'all';
  byId('srcQ').value = 'source-1';
  await window.loadSources();
  assert.equal(byId('srcList').textContent, 'source-1');
  assert.equal(byId('nSources').textContent, '2001', 'search should preserve the full project count');
  console.log('Sources paging, filters, quiet refresh and search passed.');
} finally {
  window.close();
}
