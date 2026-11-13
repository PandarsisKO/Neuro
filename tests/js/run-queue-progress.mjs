import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { JSDOM } from 'jsdom';

const dom = new JSDOM('<details id="jobsDetails" open></details><div id="bar"></div>', { runScripts: 'outside-only' });
const { window } = dom;
window.esc = value => String(value);
window.$ = selector => window.document.querySelector(selector);
const js = readFileSync('neurosearch/web/js/research.js', 'utf8');
window.eval(js.slice(js.indexOf('globalThis.jobProgress ='), js.indexOf('globalThis.pollFails =')));
const slot = window.$('#bar');
const render = (job) => {
  slot.innerHTML = window.jobProgress(job) + window.liveTag(job);
  window.refreshJobActivity();
  return slot.querySelector('[role=progressbar]');
};
try {
  const batch = { status: 'external_pending', batch: { phase: 'processing', sources: 40, done: 0, provider_total: 20, provider_done: 6 } };
  assert.equal(render(batch).getAttribute('aria-valuenow'), '6');
  batch.batch.provider_done = 14;
  assert.equal(render(batch).firstElementChild.style.width, '70%');
  batch.batch.phase = 'materializing';
  batch.batch.done = 10;
  assert.equal(render(batch).firstElementChild.style.width, '25%');
  assert.match(render(batch).getAttribute('aria-label'), /sources written/);

  const working = render({ status: 'running', progress: 0.25, heartbeat_at: Date.now() / 1000, updated_at: Date.now() / 1000 - 65 });
  assert.equal(working.firstElementChild.style.width, '25%');
  assert.equal(working.hasAttribute('aria-valuenow'), false);
  assert.match(slot.textContent, /Worker check-in just now.*Stage updated 1m ago/);
  assert.equal(render({ status: 'queued', progress: 0 }), null);
  assert.equal(render({ status: 'queued', state: 'resuming', progress: 0.5 }).classList.contains('job-progress-active'), false);
  assert.equal(render({ status: 'external_pending', external_provider: 'browser', progress: 0 }), null);
  assert.equal(window.jobPollDelay(true), 2000);
  window.$('#jobsDetails').open = false;
  assert.equal(window.jobPollDelay(true), 3000);
  assert.equal(window.jobPollDelay(false), 15000);

  // Import outcomes and ready evidence are different milestones.
  const importSlot = window.document.createElement('div');
  importSlot.id = 'collectionImport';
  window.document.body.append(importSlot);
  window.eval(readFileSync('neurosearch/web/js/api.js', 'utf8').split('\n').find(line => line.startsWith('globalThis.esc = ')));
  window.eval(js.slice(js.indexOf('globalThis.collectionImportVisible ='), js.indexOf('globalThis.loadJobs =')));
  const importBatch = {
    title: 'Collection <small>title</small>', total: 4, searchable: 0, source: null, finding: null,
    counts: { done: 1, queued: 1, external_pending: 1, skipped: 1 },
  };
  window.renderCollectionImport(importBatch);
  assert.equal(importSlot.querySelector('small'), null);
  assert.match(importSlot.textContent, /1 of 4 import jobs completed.*1 queued.*1 waiting on external work.*1 skipped/);
  assert.match(importSlot.textContent, /No searchable sources yet/);
  assert.match(importSlot.textContent, /No cited findings yet/);
  let opened;
  window.sourceDrawer = id => { opened = id; };
  window.openSourceSuggestions = (id, status) => { opened = [id, status]; };
  importBatch.searchable = 1;
  importBatch.source = { id: 'abc', title: 'Title' };
  importBatch.finding = { source_id: 'abc', status: 'suggested' };
  window.renderCollectionImport(importBatch);
  const sourceButton = importSlot.querySelector('[data-import-source]');
  window.renderCollectionImport(importBatch);
  assert.equal(importSlot.querySelector('[data-import-source]'), sourceButton);
  sourceButton.click();
  assert.equal(opened, 'abc');
  importSlot.querySelector('[data-import-finding]').click();
  assert.deepEqual(opened, ['abc', 'suggested']);
  window.renderCollectionImport(null);
  assert.equal(importSlot.hidden, true);
  assert.equal(importSlot.textContent, '');
} finally {
  window.close();
}
