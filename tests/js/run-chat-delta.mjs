// CHR2 gate harness (docs/CHAT-REFRESH-PLAN.md §14/§15): runs the SHIPPED neurosearch/web/js/{api,chats}.js in
// jsdom against a scripted uiFetch, proving the 18 CHR2 gates without a live server or browser. Behavioral gates
// exercise the real code; a few (6, 7, 18) are static source scans, same technique run-poll-containment.mjs uses
// for api.js -- if the shipped source stops containing the pattern being scanned for, that is itself a signal
// worth failing loudly on rather than silently passing.
//
//   node tests/js/run-chat-delta.mjs
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { createRequire } from 'node:module';

const here = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
let JSDOM;
try { ({ JSDOM } = require('jsdom')); }
catch (e) { console.error('jsdom is not installed: run `npm ci --prefix tests/js`.'); process.exit(3); }

const root = path.join(here, '..', '..');
const apiSrc = readFileSync(path.join(root, 'neurosearch', 'web', 'js', 'api.js'), 'utf8').replace(/^export const moduleName.*$/m, '');
const chatsSrc = readFileSync(path.join(root, 'neurosearch', 'web', 'js', 'chats.js'), 'utf8').replace(/^export const moduleName.*$/m, '');

let failures = 0, passes = 0;
const fail = msg => { console.error('FAIL: ' + msg); failures++; };
const pass = msg => { console.log('PASS: ' + msg); passes++; };
const tick = (ms = 5) => new Promise(r => setTimeout(r, ms));

// ---- static gates: source scans (mirror run-poll-containment.mjs's guard style) ----
if (!/globalThis\.chatDeltaMode = function/.test(chatsSrc)) fail('static: chatDeltaMode not found in chats.js -- gate scans below are stale');
if (/pollTick[\s\S]{0,400}loadChatDelta|loadChatDelta[\s\S]{0,400}pollTick/.test(chatsSrc)) fail('gate 6: loadChatDelta appears wired near pollTick');
else pass('gate 6: loadChatDelta is not referenced from pollTick');
if (/loadChats[\s\S]*?\n\}/m.test(chatsSrc) && /globalThis\.loadChats = async function[\s\S]*?\n\}/.exec(chatsSrc)[0].includes('Delta')) fail('gate 7: loadChats() references chat delta (a chat-list badge/fetch)');
else pass('gate 7: loadChats() (the chat-list renderer) has no delta reference');
if (!/globalThis\.refreshChat = async function/.test(chatsSrc) || !/\/api\/conversations\/.*\/refresh/.test(chatsSrc)) fail('gate 18: CHR3 explicit refresh control is not wired to its bounded endpoint');
else pass('gate 18: CHR3 has an explicit refresh control; it is not part of polling or chat-list loading');
const askBody = /globalThis\.ask = async function ask\(\)[\s\S]*?\n\}\n/.exec(chatsSrc)?.[0] || '';
if (!/addMsg\('assistant', r\.answer[\s\S]*?clearChatDelta\(\)/.test(askBody)) fail('gate 9 (static): ask() does not call clearChatDelta() after rendering the new answer');
else pass('gate 9 (static): ask() clears chat delta UI right after a new answer is added');

// ---- behavioral harness: real api.js + chats.js in jsdom, scripted /delta responses ----
function makeDom() {
  const dom = new JSDOM(`<!doctype html><body>
    <div id="chatHead"></div><div id="chatDelta"></div><div id="chat"></div>
    <div id="chatList"></div><div id="chatTitle"></div>
    <textarea id="q"></textarea><button id="askBtn"></button><span id="qAttach"></span>
    <input type="checkbox" id="useWeb"><span id="nFindings">0</span><span id="nSources">0</span>
    <span id="shareChatMsg"></span><span id="wsFoot"></span>
  </body>`, { url: 'https://ns.test/', runScripts: 'dangerously', pretendToBeVisual: true });
  const { window } = dom;
  window.fetchLog = [];
  window.deltaResponses = {};   // conversation_id -> response object (or {__error:true})
  window.uiFetch = async (p, opts = {}) => {
    window.fetchLog.push({ path: p, ack: opts.headers ? undefined : undefined, opts });
    const m = /\/api\/conversations\/([^/]+)\/delta/.exec(p);
    if (m) {
      const r = window.deltaResponses[m[1]];
      if (r && r.__error) return { ok: false, status: 500, json: async () => ({ error: 'boom' }) };
      return { ok: true, status: 200, json: async () => (r || {}) };
    }
    return { ok: true, status: 200, json: async () => ([]) };
  };
  window.eval(apiSrc);
  // minimal stand-ins for globals chats.js touches outside the CHR2 surface (never exercised by these gates)
  window.eval(`
    globalThis.state = { project: { id: 'p1', name: 'Proj' }, conv: null, chats: [], attached: [] };
    globalThis.listState = (k, o) => '<div class="' + k + '">' + ((o && o.label) || (o && o.message) || '') + '</div>';
    globalThis.showView = () => {};
    globalThis.watchIngest = () => {};
    globalThis.toast = () => {};
    globalThis.loadChats = async () => {};
    globalThis.put = (p, b) => api(p, { method: 'PUT', body: JSON.stringify(b) });
  `);
  window.eval(chatsSrc);
  return { dom, window };
}

// gate 1 + 5: Exact chat -> automatic single-flight /delta on open
{
  const { window } = makeDom();
  window.deltaResponses['c1'] = { mode: 'exact', nothing_new: false, material_changes: [{ category: 'contradicts', why_relevant: 'X changed' }], supporting_changes: [], irrelevant_new_source_count: 0, plan_impacts: [], rollups: null, new_claims: null, approximate_limitations: [], latest_activity_at: 1758000000 };
  const ms = [{ role: 'user', content: 'q1', meta: {} }, { role: 'assistant', content: 'a1', meta: { evidence: { complete: true } } }];
  window.state.conv = 'c1';
  // POLL's documented contract (api.js, shared with loadJobs/loadSources): one refresh in flight, and any calls
  // that arrive while it runs are coalesced into exactly ONE rerun afterwards -- not "call it 3 times, fetch
  // once ever," which is not what this app's single-flight primitive does anywhere. Three back-to-back opens of
  // the same Exact chat must therefore settle at exactly 2 requests (the one running + the one coalesced rerun),
  // never 3 (proving no pile-up).
  window.scheduleChatDelta('c1', ms);
  window.scheduleChatDelta('c1', ms);
  window.scheduleChatDelta('c1', ms);
  await tick(20);
  const hits = window.fetchLog.filter(f => f.path.includes('/delta'));
  if (hits.length !== 2) fail(`gate 1/5: expected 2 /delta calls (1 run + 1 coalesced rerun) for an Exact chat opened 3x back-to-back, saw ${hits.length}`);
  else pass('gate 1/5: Exact chat auto-check is single-flight (coalesces repeated opens into one rerun, no pile-up)');
  const html = window.document.getElementById('chatDelta').innerHTML;
  if (!html.includes("What's new") || !html.includes('meaningful change')) fail('gate 1: compact "What\'s new" card did not render for an Exact chat with material changes');
  else pass('gate 1: compact card rendered for Exact chat with a real change');
  const refresh = window.document.querySelector('button[onclick^="refreshChat"]');
  if (!refresh) fail('gate 18: meaningful delta card did not expose the explicit Refresh this chat control');
  else {
    await window.refreshChat('c1', refresh);
    const calls = window.fetchLog.filter(f => f.path.includes('/refresh'));
    if (calls.length !== 1) fail(`gate 18: clicking Refresh this chat did not make exactly one bounded refresh request (saw ${calls.length})`);
    else pass('gate 18: refresh is one explicit request, never an automatic delta poll side effect');
  }
}

// gate 2 + 3: Approximate/legacy chat does NOT call /delta on open; clicking the affordance DOES
{
  const { window } = makeDom();
  const ms = [{ role: 'user', content: 'q1', meta: {} }, { role: 'assistant', content: 'a1', meta: {} }];   // no evidence -> legacy
  window.state.conv = 'c2';
  window.scheduleChatDelta('c2', ms);
  await tick(10);
  if (window.fetchLog.some(f => f.path.includes('/delta'))) fail('gate 2: /delta was called automatically for a legacy/Approximate chat');
  else pass('gate 2: legacy/Approximate chat does not auto-call /delta');
  if (!window.document.getElementById('chatDelta').innerHTML.includes('Check what')) fail('gate 4 render: affordance button did not render for a legacy chat');
  window.deltaResponses['c2'] = { mode: 'approximate', nothing_new: false, material_changes: [], supporting_changes: [], irrelevant_new_source_count: 0, plan_impacts: [], rollups: { sources_changed: 830, findings_added: 16992, claims_added_or_updated: 14265, claim_evidence_added: 500 }, new_claims: null, approximate_limitations: ['This chat predates evidence snapshots.'] };
  window.loadChatDelta('c2', false);
  await tick(10);
  const hits = window.fetchLog.filter(f => f.path.includes('/delta'));
  if (hits.length !== 1) fail(`gate 3: clicking "Check what's new" did not call /delta exactly once (saw ${hits.length})`);
  else pass('gate 3: clicking the Approximate affordance calls /delta');
}

// gate 4/12: hidden document defers the automatic Exact check; becoming visible fires the one pending check
{
  const { window } = makeDom();
  Object.defineProperty(window.document, 'hidden', { value: true, configurable: true });
  window.deltaResponses['c3'] = { mode: 'exact', nothing_new: true, material_changes: [], supporting_changes: [], irrelevant_new_source_count: 0, plan_impacts: [], rollups: null, new_claims: null, approximate_limitations: [] };
  const ms = [{ role: 'assistant', content: 'a1', meta: { evidence: { complete: true } } }];
  window.state.conv = 'c3';
  window.scheduleChatDelta('c3', ms);
  await tick(10);
  if (window.fetchLog.some(f => f.path.includes('/delta'))) fail('gate 4: an automatic Exact check launched while document.hidden was true');
  else pass('gate 4: hidden document defers the automatic Exact check');
  Object.defineProperty(window.document, 'hidden', { value: false, configurable: true });
  window.document.dispatchEvent(new window.Event('visibilitychange'));
  await tick(10);
  const hits = window.fetchLog.filter(f => f.path.includes('/delta'));
  if (hits.length !== 1) fail(`gate 4: becoming visible did not fire exactly one pending check (saw ${hits.length})`);
  else pass('gate 4: becoming visible fires the single pending Exact check');
}

// gate 8: switching chats mid-request never paints the stale response into the newly selected chat
{
  const { window } = makeDom();
  let resolveSlow;
  window.uiFetch = (p) => {
    window.fetchLog.push({ path: p });
    if (p.includes('/delta')) return new Promise(res => { resolveSlow = () => res({ ok: true, status: 200, json: async () => ({ mode: 'exact', nothing_new: false, material_changes: [{ category: 'contradicts', why_relevant: 'stale answer' }], supporting_changes: [], irrelevant_new_source_count: 0, plan_impacts: [], rollups: null, new_claims: null, approximate_limitations: [] }) }); });
    return Promise.resolve({ ok: true, status: 200, json: async () => ([]) });
  };
  const ms = [{ role: 'assistant', content: 'a1', meta: { evidence: { complete: true } } }];
  window.state.conv = 'c4';
  window.scheduleChatDelta('c4', ms);   // request in flight for c4...
  window.clearChatDelta();
  window.state.conv = 'c5';             // ...user switches to c5 before it resolves
  window.document.getElementById('chatDelta').innerHTML = '<div class="untouched">c5 has nothing to show</div>';
  await tick(10);   // let the request actually reach uiFetch (it's behind POLL.acquire()'s own await) before resolving it
  resolveSlow();
  await tick(10);
  const html = window.document.getElementById('chatDelta').innerHTML;
  if (!html.includes('c5 has nothing to show')) fail('gate 8: a late /delta response for a previous chat painted over the newly selected chat');
  else pass('gate 8: a late response for a previous chat never paints into the newly selected chat');
}

// gate 19: a refresh completing after a chat switch must not reopen the old chat over the user's selection
{
  const { window } = makeDom();
  let release; let loads = 0, selects = 0;
  window.state.conv = 'c8';
  window.post = () => new Promise(resolve => { release = resolve; });
  window.loadChats = async () => { loads++; };
  window.selectChat = async () => { selects++; };
  const btn = window.document.createElement('button');
  const refreshing = window.refreshChat('c8', btn);
  window.state.conv = 'c9';
  release({});
  await refreshing;
  if (window.state.conv !== 'c9' || loads || selects) fail('gate 19: a completed refresh reopened or reloaded the old chat after the user switched');
  else pass('gate 19: a completed refresh leaves a newer chat selection untouched');
}

// gate 10/11: empty states
{
  const { window } = makeDom();
  window.state.conv = 'c6';
  window.document.getElementById('chatDelta').innerHTML = '<div class="checking">checking…</div>';
  window.renderChatDelta('c6', { nothing_new: true, irrelevant_new_source_count: 0, material_changes: [], supporting_changes: [], plan_impacts: [], rollups: null, new_claims: null, approximate_limitations: [] }, true);
  if (window.document.getElementById('chatDelta').innerHTML.trim() !== '') fail('gate 10: a truly-empty automatic Exact result left a persistent card');
  else pass('gate 10: truly-nothing-changed automatic result leaves no persistent card');

  window.renderChatDelta('c6', { nothing_new: true, irrelevant_new_source_count: 15, material_changes: [], supporting_changes: [], plan_impacts: [], rollups: null, new_claims: null, approximate_limitations: [] }, true);
  const html = window.document.getElementById('chatDelta').innerHTML;
  if (!html.includes("What's new") || !html.includes('Nothing important changed')) fail('gate 11: busy-but-irrelevant result did not render the compact "Nothing important changed" state');
  else pass('gate 11: busy-but-irrelevant renders the compact explanatory state');
}

// gate 12/13/14/15/16/17: rendering details of the expanded card
{
  const { window } = makeDom();
  const manyContradicts = Array.from({ length: 12 }, (_, i) => ({ category: 'contradicts', why_relevant: `contradiction ${i}` }));
  const r = {
    mode: 'approximate', nothing_new: false,
    material_changes: manyContradicts,
    supporting_changes: [{ category: 'new_claim', why_relevant: 'claim A' }],
    irrelevant_new_source_count: 0,
    plan_impacts: [],   // no known plan impact -> group 12 must not render
    rollups: { sources_changed: 830, findings_added: 16992, claims_added_or_updated: 14265, claim_evidence_added: 0 },
    new_claims: { total: 2997, shown: 2 },
    approximate_limitations: ['Approximate limitation text.'],
    latest_activity_at: 1758000000,
  };
  const expanded = window.renderDeltaExpanded('c7', r);
  if (expanded.includes('Master Plan')) fail('gate 12: "Could affect your Master Plan" rendered with an empty plan_impacts list');
  else pass('gate 12: Plan Impact group is absent when there are no known items');
  if (/16992\s*(<\/div>)?\s*<div|findings_added/.test(expanded) === false && expanded.includes('16,992')) pass('gate 13: rollups render as one aggregate sentence (16,992 findings)');
  else if (expanded.match(/findings/gi)?.length > 2) fail('gate 13: rollups appear to have been expanded into multiple rows instead of one sentence');
  else pass('gate 13: rollups render compactly');
  if (expanded.includes('2,995 more newly relevant Claims')) pass('gate 14: new_claims.total is represented as a remaining-count sentence alongside the shown examples');
  else fail('gate 14: new_claims total-minus-shown count is missing from the rendered output');
  const supportingMatch = /<details class="deltaGroup deltaSupporting">([\s\S]*?)<\/details>/.exec(expanded);
  if (!supportingMatch) fail('gate 15: "More supporting evidence" is not a collapsible <details> element');
  else if (/<details class="deltaGroup deltaSupporting"[^>]*\bopen\b/.test(expanded)) fail('gate 15: supporting evidence <details> is open by default (should be collapsed)');
  else pass('gate 15: supporting evidence is a collapsed-by-default <details> disclosure');
  const restSplit = expanded.split(/<div id="deltaRest_/);
  const visibleCount = (restSplit[0].match(/contradiction \d+/g) || []).length;
  const totalCount = (expanded.match(/contradiction \d+/g) || []).length;
  if (restSplit.length < 2) fail('gate 16: no hidden overflow container found for a 12-item group');
  else if (visibleCount !== 8) fail(`gate 16: expected the initial (visible, pre-overflow) slice to show 8 of 12 contradictions, saw ${visibleCount}`);
  else if (totalCount !== 12) fail(`gate 16: expected all 12 contradictions present somewhere in the DOM (visible + hidden overflow), saw ${totalCount} -- items were dropped, not just paginated`);
  else pass('gate 16: a large group shows an initial slice (8) with the rest held in a hidden overflow container, none dropped');
  if (!expanded.includes('Show 4 more')) fail('gate 16: no "Show N more" control for the remaining items');
  else pass('gate 16: "Show N more" control offers the rest of a large group in one action');
  if (!expanded.includes('Approximate limitation text.')) fail('gate 17: approximate_limitations text is missing from the expanded/supporting content');
  else pass('gate 17: approximate_limitations text appears inside the (lazy, post-check) expanded content');
  const compact = window.deltaCompactLine(r);
  if (compact.includes('Approximate limitation')) fail('gate 17: approximate_limitations leaked into the compact pre-click line');
  else pass('gate 17: the compact line carries no limitation text (it only appears after disclosure)');
}

console.log(`\n${passes} passed, ${failures} failed`);
process.exit(failures ? 1 : 0);
