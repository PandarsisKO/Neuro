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
} finally {
  window.close();
}
