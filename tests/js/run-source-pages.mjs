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
  const dlg = byId('dlg');
  window.dlg = dlg;
  dlg.showModal = () => { dlg.open = true; };
  window.HTMLElement.prototype.scrollIntoView = () => {};
  window.esc = value => String(value).replaceAll('<', '&lt;').replaceAll('>', '&gt;');
  window.state.project.name = 'Passage test';
  let resolveOlder;
  const older = new Promise(resolve => { resolveOlder = resolve; });
  window.api = async (url) => {
    const target = new URL(url, 'http://localhost/');
    if (target.pathname === '/api/sources/source-1') {
      return { title: 'Sample document', platform: 'document', segments: [
        { start: 1, text: 'First page' }, { start: 2, text: 'Second page' },
      ] };
    }
    assert.equal(target.pathname, '/api/projects/test-project/passages');
    assert.equal(target.searchParams.get('source_id'), 'source-1');
    assert.equal(target.searchParams.get('phrase'), 'true');
    if (target.searchParams.get('q') === 'earlier') return older;
    return [
      { source_id: 'source-1', title: 'Sample document', platform: 'document', start: 2, timestamp: 'p. 2', text: '<b>Second page</b>' },
      { source_id: 'video', title: 'Sample video', platform: 'youtube', timestamp: '1:05', text: 'Passage from video',
        url: 'https://www.youtube.com/watch?v=sample', link: 'https://www.youtube.com/watch?v=sample&t=65s' },
    ];
  };
  const settle = () => new Promise(resolve => setTimeout(resolve, 0));
  window.openPassageSearch('source-1');
  const form = dlg.querySelector('form');
  assert.equal(window.document.activeElement, form.elements.query);
  form.elements.query.value = 'earlier';
  form.requestSubmit();
  form.elements.query.value = 'second page';
  form.requestSubmit();
  await settle();
  resolveOlder([]);
  await settle();
  assert.equal(dlg.querySelector('.passage-excerpt').textContent, '<b>Second page</b>');
  assert.equal(dlg.querySelector('.passage-excerpt b'), null);
  assert.match(dlg.querySelector('.passage-results a').href, /[&]t=65s$/);
  dlg.querySelector('button[data-passage-source]').click();
  await settle();
  assert.equal(dlg.querySelector('[data-passage-match]').textContent, '[p. 2] Second page');
  console.log('Sources paging, filters, quiet refresh, search and passage navigation passed.');
} finally {
  window.close();
}
