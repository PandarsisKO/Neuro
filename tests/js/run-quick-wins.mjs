import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { JSDOM } from 'jsdom';

const dom = new JSDOM('<div id="reviewWrap"></div><div id="paneQueue"></div><dialog id="dlg"><div id="dlgBody"></div></dialog>',
  { url: 'http://localhost', runScripts: 'dangerously' });
const { window } = dom;
const { document } = window;
const source = file => readFileSync(`neurosearch/web/js/${file}.js`, 'utf8');
window.$ = selector => document.querySelector(selector);
window.esc = value => String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;');
window.state = { project: { id: 'project' } };
window.POLL = { enter: () => true, leave: () => {} };
window.loadJobs = () => {};
window.listState = (_, opts) => opts.label || opts.message;
const modal = document.querySelector('#dlg');
modal.showModal = () => { modal.open = true; };
modal.close = () => { modal.open = false; };
const rows = [
  { id: 'gated', title: 'Members', relevance: 100, access_gate: 'members_only' },
  { id: 'first', title: 'First', relevance: 90 },
  { id: 'second', title: 'Second', relevance: 80 },
  { id: 'third', title: 'Third', relevance: 70 },
  { id: 'unscored', title: 'Unscored', relevance: null },
];
const meta = { ranked: true, ranking: false, max_videos: 2 };
const review = { id: 'review', title: 'Listing', meta, proposed: rows };
let evidenceCalls = 0;
let savedReview = null;
window.api = async url => {
  if (url.endsWith('/reviews')) return [review];
  if (url.endsWith('/challenge/review')) return { review: savedReview };
  assert.match(url, /\/projects\/project\/claims\/claim\/evidence$/);
  evidenceCalls++;
  return {
    text: 'The claim',
    supporting: [{ title: 'Video', locator: '12:30', relation: 'SUPPORTS', excerpt: 'First passage',
      link: 'https://example.test/video?t=750s', independent: true }],
    supporting_total: 1,
    counter: [{ title: 'Counter', locator: 'p. 4', relation: 'CONTRADICTS', excerpt: '<counterevidence>',
      link: 'javascript:alert(1)', source_id: 'counter', stale: true, independent: true }],
    counter_total: 1,
  };
};
window.post = async () => { meta.ranking = true; meta.ranked = false; };
const sourceJs = source('sources');
window.eval(sourceJs.slice(sourceJs.indexOf('globalThis.rvSig ='), sourceJs.indexOf('globalThis.rvFocus =')));
const researchJs = source('research');
window.eval(researchJs.slice(researchJs.indexOf('globalThis.renderQueuePane ='), researchJs.indexOf('globalThis.queueRejectOrphans =')));
window.stTag = () => '';
window.RES = { queue: { queue: [{ claim_id: 'claim', text: 'The claim', status: 'proposed',
  reasons: ['corroboration'], members: { note_ids: [] }, independent_sources: 2 }] } };

const checked = () => [...document.querySelectorAll('#rv-review input:checked')].map(x => x.dataset.id).sort();
const box = id => document.querySelector(`#rv-review input[data-id="${id}"]`);
const top = () => document.querySelector('#rv-review input[name=count]');

try {
  await window.loadReviews();
  assert.deepEqual(checked(), ['first', 'second']);
  assert.equal(top().max, '3');
  box('second').click();
  box('third').click();
  await window.rvRerank('review', document.querySelector('button[onclick^=rvRerank]'));
  await window.loadReviews();
  assert.deepEqual(checked(), ['first', 'third']);
  meta.ranking = false;
  meta.ranked = true;
  review.proposed = [rows[0], rows[2], rows[3], rows[1], rows[4]];
  await window.loadReviews();
  assert.deepEqual(checked(), ['first', 'third']);
  const form = top().form;
  form.dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true }));
  assert.deepEqual(checked(), ['second', 'third']);
  top().value = '100';
  window.rvTop('review', top());
  assert.equal(top().value, '3');
  assert.deepEqual(checked(), ['first', 'second', 'third']);

  await window.renderQueuePane();
  assert.equal(evidenceCalls, 0);
  assert.match(document.querySelector('#paneQueue').textContent, /Show evidence/);
  assert.match(document.querySelector('#paneQueue').textContent, /needs corroboration/);
  assert.doesNotMatch(document.querySelector('#paneQueue').textContent, /sources disagree/);
  document.querySelector('button[onclick^=showClaimEvidence]').click();
  await new Promise(setImmediate);
  const panel = document.querySelector('#dlgBody');
  assert.equal(evidenceCalls, 1);
  assert.match(panel.textContent, /First passage/);
  assert.match(panel.textContent, /<counterevidence>/);
  assert.match(panel.textContent, /Source revised/);
  assert.equal(panel.querySelector('a').getAttribute('href'), '/api/sources/counter/transcript.txt');
  assert.match(panel.querySelector('a[href^=https]').getAttribute('href'), /t=750s$/);
  window.post = async (url, body) => {
    assert.match(url, /claims\/claim\/challenge$/);
    assert.equal(body.alternate, 'opposite result');
    assert.equal(body.semantic, false);
    return { text: 'The claim', queries: [body.q, body.alternate], method: 'keyword', searched_at: '2026-11-12T20:00:00Z',
      passage_limit_per_scope: 8, scopes: { project: { sources_in_scope: 10, passages: [
        { chunk_id: 12, source_id: 'other', text: 'An independent result', title: 'Test source' }
      ] } } };
  };
  const challenge = panel.querySelector('[data-claim-challenge]');
  challenge.elements.alternate.value = 'opposite result';
  challenge.requestSubmit();
  await new Promise(setImmediate);
  const outcome = panel.querySelector('[data-challenge-outcome]');
  assert.match(outcome.textContent, /insufficient/);
  const assessment = panel.querySelector('[data-challenge-passage]');
  for (const [choice, expected] of [
    ['irrelevant', /insufficient/], ['qualification', /Novelty remains unassessed/], ['contradiction', /Novelty remains unassessed/], ['equivalent', /Equivalent assertion reviewed in the project/],
  ]) {
    assessment.value = choice;
    assessment.dispatchEvent(new window.Event('change'));
    assert.match(outcome.textContent, expected);
  }

  assert.match(window.claimChallengeSummary({ project: { passages: [] } }), /insufficient/);
  assert.match(window.claimChallengeSummary({ library: { passages: [{ assessment: 'equivalent' }] } }), /reviewed in the library/);
  assert.match(window.claimChallengeSummary({ project: { passages: [
    { assessment: 'equivalent', same_origin_as_support: true }
  ] } }), /already cited origin/);

  window.put = async (url, body) => {
    assert.match(url, /challenge\/review$/);
    assert.equal(body.scopes.project.passages[0].assessment, 'equivalent');
    savedReview = { ...body, saved_at: 1794528000, claim_changed: false };
    return { review: savedReview };
  };
  panel.querySelector('[data-challenge-save]').click();
  await new Promise(setImmediate);
  assert.match(panel.querySelector('[data-challenge-save-status]').textContent, /Assessment saved/);
  savedReview.scopes.project.passages[0].changed = true;
  await window.showClaimEvidence('claim');
  await new Promise(setImmediate);
  const saved = panel.querySelector('[data-saved-challenge]');
  assert.match(saved.textContent, /Last saved assessment/);
  assert.match(saved.textContent, /Passage changed/);

  const planJs = source('plan');
  window.eval(planJs.slice(planJs.indexOf('globalThis.planUpdateEvidence ='), planJs.indexOf('globalThis.renderPlan =')));
  const card = document.createElement('div');
  card.innerHTML = window.planUpdateEvidence({ claim_evidence: {
    text: 'A scoped Claim', counter: [], supporting: [{
      source_id: 'source', locator: '12:30', excerpt: '<passage>', relation: 'SUPPORTS', stale: true,
      title: 'Source title', link: 'https://example.test/video?t=750s'
    }] } });
  assert.match(card.textContent, /A scoped Claim/);
  assert.match(card.textContent, /<passage>/);
  assert.match(card.textContent, /Source revised/);
  assert.equal(card.querySelector('a').getAttribute('href'), 'https://example.test/video?t=750s');

  window.eval(planJs.replace(/^route\(\);$/m, '').replace(/^export const moduleName.*$/m, ''));
  const planWrap = document.createElement('div');
  planWrap.id = 'planWrap';
  document.body.append(planWrap);
  window.STATUSES = ['not_started', 'complete'];
  window.stLabel = s => s.replaceAll('_', ' ');
  window.planState = {
    plan: { id: 'saved', project_id: 'project', status: 'started', version: 2,
      items: { 'phases.0.tasks.0': { status: 'complete' } }, updates: [], plan: {
        approach: { recommended: 'Use the hall', why: 'The library closed', alternatives: [{ option: 'Library', why_not: 'Closed' }] },
        phases: [{ name: 'Preparation' }, { name: 'Registration' }, { name: 'Follow-up' }],
        analysis: { assumptions: [{ assumption: 'Eight people will attend' }] },
        _evidence: { F1: { label: 'Venue agreement' } },
      } },
    execution: { phase: { name: 'Registration' }, phase_index: 1, next_actions: [], completed: 1, tasks: {
      'phases.0.tasks.0': { phase: 0, label: 'Compare venues' }, 'phases.2.tasks.0': { phase: 2, label: 'Survey attendees' },
    } },
    versions: [{ version: 2, label: 'current', created_at: 1800000000 }, { version: 1, created_at: 1790000000 }],
    recorded_decisions: [{ content: 'Chose the hall because the library closed', status: 'active', created_at: 1795000000 }],
  };
  window.planState.activity = { cursor: 73, more: false, changes: [
    { title: 'Task finished', section: 'work', anchor: 'plan-item-phases.0.tasks.0', at: 1795000000 }
  ] };
  window.renderPlan(window.planState);
  assert.match(planWrap.querySelector('#plan-section-reasoning').parentElement.textContent, /The library closed/);
  for (const row of planWrap.querySelectorAll('.plan-phase')) assert.equal(row.closest('details'), null);
  assert.match(planWrap.querySelector('#plan-section-work').parentElement.textContent, /Compare venues.*Survey attendees/s);
  assert.match(planWrap.querySelector('#plan-section-decisions').parentElement.textContent, /Chose the hall/);
  const versionLink = planWrap.querySelector('#plan-section-history + ul a');
  assert.match(versionLink.getAttribute('href'), /plan.html\?version=1$/);
  window.jumpToPlanSection('history');
  assert.equal(document.activeElement.id, 'plan-section-history');
  assert.ok(planWrap.contains(versionLink));
  assert.match(planWrap.querySelector('#planActivity').textContent, /Task finished/);
  planWrap.querySelector('#planActivity li button').click();
  assert.equal(document.activeElement.id, 'plan-item-phases.0.tasks.0');
  window.markPlanActivityReviewed();
  assert.equal(window.localStorage.getItem('ns_plan_reviewed:project'), '73');
  assert.match(planWrap.querySelector('#planActivity').textContent, /No recorded plan changes/);
  assert.ok(planWrap.contains(versionLink));

} finally {
  window.close();
}
