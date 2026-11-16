import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { JSDOM } from 'jsdom';

const html = readFileSync('neurosearch/web/index.html', 'utf8');
const markup = new JSDOM(html).window.document.querySelector('#jobsCard').outerHTML;
const dom = new JSDOM(markup + '<div id="bar"></div>', { runScripts: 'outside-only', url: 'http://localhost' });
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
  window.$('#jobsDetails').open = true;
  assert.equal(window.jobPollDelay(true), 2000);
  window.$('#jobsDetails').open = false;
  assert.equal(window.jobPollDelay(true), 3000);
  assert.equal(window.jobPollDelay(false), 15000);

  // Import outcomes and ready evidence are different milestones.
  const importSlot = window.$('#collectionImport');
  window.state = { project: { id: 'project' } };
  window.POLL = { enter: () => true, leave: () => {} };
  window.SRCG = { rows: [] };
  window.pollTick = () => {};
  window.loadSpend = () => null;
  window.loadBacklog = window.restoreJobHistories = () => {};
  window.subredditRecovery = () => '';
  window.subredditJobNeedsHelp = () => false;
  window.eval(readFileSync('neurosearch/web/js/api.js', 'utf8').split('\n').find(line => line.startsWith('globalThis.esc = ')));
  window.eval(js.slice(js.indexOf('globalThis.jobsTimer ='), js.indexOf('globalThis.jobProgress =')));
  window.eval(js.slice(js.indexOf('globalThis.pollFails ='), js.indexOf('globalThis.lastRev =')));
  const importBatch = {
    id: 'batch-id', title: 'Collection <small>title</small>', total: 4, searchable: 0, source: null, finding: null,
    counts: { done: 1, queued: 1, external_pending: 1, skipped: 1 },
  };
  const queued = { id: 'job', status: 'queued', progress: 0, kind: 'ingest_source', payload: { name: 'Video' } };
  const response = { jobs: [queued], collection_import: importBatch };
  window.api = async path => path.startsWith('/api/projects/') ? response : {};
  await window.loadJobs(true);
  assert.match(window.$('#jobsSummary').textContent, /Progress queue · 1 job waiting/);
  assert.equal(importSlot.querySelector('small'), null);
  assert.match(importSlot.textContent, /1 of 4 import jobs completed.*1 queued.*1 waiting on external work.*1 skipped/);
  assert.match(importSlot.textContent, /No searchable sources yet/);
  assert.match(importSlot.textContent, /No cited findings yet/);
  assert.equal(importSlot.querySelector('[data-import-dismiss]'), null);
  importSlot.querySelector('summary').click();
  let opened;
  window.sourceDrawer = id => { opened = id; };
  window.openSourceSuggestions = (id, status) => { opened = [id, status]; };
  importBatch.searchable = 1;
  importBatch.source = { id: 'abc', title: 'Title' };
  importBatch.finding = { source_id: 'abc', status: 'suggested' };
  await window.loadJobs(true);
  assert.equal(importSlot.querySelector('details').open, true);
  const sourceButton = importSlot.querySelector('[data-import-source]');
  window.renderCollectionImport(importBatch);
  assert.equal(importSlot.querySelector('[data-import-source]'), sourceButton);
  sourceButton.click();
  assert.equal(opened, 'abc');
  importSlot.querySelector('[data-import-finding]').click();
  assert.deepEqual(opened, ['abc', 'suggested']);
  // When the last job finishes, the queue still opens and the old import can
  // be dismissed. Polls do not bring it back, but retries and new batches do.
  response.jobs = [];
  importBatch.counts = { done: 3, skipped: 1 };
  await window.loadJobs(true);
  assert.match(importSlot.querySelector('summary').textContent, /Import finished · 3 of 4 import jobs completed · 1 skipped/);
  assert.equal(window.$('#jobsCard').hidden, false);
  assert.equal(window.$('#jobsDetails').hidden, false);
  window.$('#jobsSummary').click();
  assert.equal(window.$('#jobsDetails').open, true);
  assert.match(window.$('#jobs').textContent, /No active jobs for this project/);
  assert.equal(importSlot.querySelector('details').open, true);
  importSlot.querySelector('[data-import-dismiss]').click();
  assert.equal(importSlot.hidden, true);
  assert.equal(window.document.activeElement, window.$('#jobsSummary'));
  assert.equal(window.localStorage.getItem('ns_dismissed_import:project'), 'batch-id');
  await window.loadJobs(true);
  assert.equal(importSlot.hidden, true);
  response.collection_import = { ...importBatch, id: 'another-batch' };
  await window.loadJobs(true);
  assert.equal(importSlot.hidden, false);
  response.collection_import = importBatch;
  importBatch.counts = { done: 2, queued: 1, skipped: 1 };
  await window.loadJobs(true);
  assert.equal(importSlot.hidden, false);
  assert.equal(importSlot.querySelector('[data-import-dismiss]'), null);
  importBatch.counts = { done: 3, skipped: 1 };
  await window.loadJobs(true);
  assert.equal(importSlot.hidden, false);
} finally {
  window.close();
}
