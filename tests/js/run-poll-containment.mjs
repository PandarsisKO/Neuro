// P0.1 poll containment (docs/SPEED-AUDIT-2026-09-17.md): runs the SHIPPED neurosearch/web/js/api.js in a vm
// context against a scripted uiFetch and proves the three rules that stop a slow server from filling the
// browser's connection pool: (1) at most POLL.MAX_INFLIGHT quiet requests are on the wire at once while a
// user action is never queued behind them; (2) a quiet request is abandoned (AbortError) after POLL.TIMEOUT_MS
// and releases its slot; (3) POLL.enter/leave coalesce a refresh: a second call while one runs is remembered
// exactly once, and the rerun is quiet only when every coalesced caller was.
//
//   node tests/js/run-poll-containment.mjs limit
//   node tests/js/run-poll-containment.mjs timeout
//   node tests/js/run-poll-containment.mjs coalesce
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import vm from 'node:vm';

const here = path.dirname(fileURLToPath(import.meta.url));
let src = readFileSync(path.join(here, '..', '..', 'neurosearch', 'web', 'js', 'api.js'), 'utf8');
src = src.replace(/^export const moduleName.*$/m, '');
if (!src.includes('globalThis.POLL = {') || !src.includes('await POLL.acquire()')) {
  console.error('SOURCE CHANGED: api.js no longer routes quiet requests through POLL.acquire() -- update this harness with the change, do not let it pass silently.');
  process.exit(3);
}

const calls = [];            // every uiFetch the shipped api() made: {path, signal}
let mode = 'hang';           // 'hang' = never resolves (honours abort); 'ok' = resolves at once
const ctx = {
  console, setTimeout, clearTimeout, performance, Promise, Error, AbortController, Headers: globalThis.Headers,
  document: { addEventListener() {}, createElement() { return { appendChild() {}, classList: { add() {}, remove() {} } }; }, body: { appendChild() {} }, hidden: false },
  location: { reload() { throw new Error('unexpected reload'); } },
  uiFetch(p, opts = {}) {
    calls.push({ path: p, signal: opts.signal });
    if (mode === 'ok') return Promise.resolve({ ok: true, status: 200, json: async () => ({ ok: true }) });
    return new Promise((_, rej) => { if (opts.signal) opts.signal.addEventListener('abort', () => { const e = new Error('aborted'); e.name = 'AbortError'; rej(e); }); });
  },
};
ctx.globalThis = ctx; ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(src, ctx, { filename: 'api.js' });
const { api, POLL } = ctx;
const tick = () => new Promise(r => setTimeout(r, 5));
const fail = msg => { console.error('FAIL: ' + msg); process.exit(1); };

const scenario = process.argv[2];
if (scenario === 'limit') {
  const quiet = Array.from({ length: 6 }, (_, i) => api('/api/poll' + i, { ack: false }).catch(() => {}));
  await tick();
  if (calls.length !== POLL.MAX_INFLIGHT) fail(`expected ${POLL.MAX_INFLIGHT} quiet requests on the wire, saw ${calls.length}`);
  const action = api('/api/conversations', { method: 'POST', body: '{}' }).catch(() => {});
  await tick();
  if (calls.length !== POLL.MAX_INFLIGHT + 1) fail(`a user action must not wait behind queued polls (saw ${calls.length} requests, expected ${POLL.MAX_INFLIGHT + 1})`);
  if (calls[calls.length - 1].path !== '/api/conversations') fail('the user action was not the request that went out');
  if (calls[calls.length - 1].signal) fail('a user action must carry no abort budget by default');
  if (!calls[0].signal) fail('a quiet request must carry an abort signal');
  console.log(`PASS limit: ${POLL.MAX_INFLIGHT} of 6 polls on the wire, action went out immediately`);
  process.exit(0);
}
if (scenario === 'timeout') {
  POLL.TIMEOUT_MS = 30;
  const t0 = Date.now();
  let err = null;
  await api('/api/sources?project_id=x', { ack: false }).catch(e => { err = e; });
  const dt = Date.now() - t0;
  if (!err || err.name !== 'AbortError') fail(`a stalled quiet request must reject with AbortError (got ${err && err.name})`);
  if (dt > 1000) fail(`abort took ${dt} ms against a 30 ms budget`);
  if (POLL.inflight !== 0) fail(`the abandoned request did not release its slot (inflight=${POLL.inflight})`);
  // and the next poll goes straight out: the slot really was freed
  calls.length = 0; mode = 'ok';
  const r = await api('/api/tick', { ack: false });
  if (!r || !r.ok || calls.length !== 1) fail('the slot freed by the abort was not reusable');
  console.log(`PASS timeout: aborted after ${dt} ms, slot released`);
  process.exit(0);
}
if (scenario === 'coalesce') {
  const runs = [];
  const refresh = q => { if (!POLL.enter('k', q)) return; runs.push('run:' + q); setTimeout(() => POLL.leave('k', refresh), 10); };
  refresh(true); refresh(true); refresh(true);                 // one running, two coalesced
  if (runs.length !== 1) fail('a refresh already in flight must not start again');
  await new Promise(r => setTimeout(r, 40));
  if (runs.length !== 2) fail(`expected exactly one rerun after the in-flight refresh finished, saw ${runs.length - 1}`);
  if (runs[1] !== 'run:true') fail(`all callers were quiet, so the rerun must be quiet (got ${runs[1]})`);
  await new Promise(r => setTimeout(r, 40));
  if (runs.length !== 2) fail('the rerun must not re-trigger itself');
  runs.length = 0;
  refresh(true); refresh(undefined);                            // a click (loud) lands during a quiet poll
  await new Promise(r => setTimeout(r, 40));
  if (runs.length !== 2 || runs[1] !== 'run:undefined') fail(`a loud caller during a quiet refresh must make the rerun loud (got ${JSON.stringify(runs)})`);
  // watchdog: a key whose body threw past its own catch (never called leave) frees itself after 2x the timeout
  POLL.TIMEOUT_MS = 10;
  if (!POLL.enter('stuck', true)) fail('fresh key must enter');
  await new Promise(r => setTimeout(r, 30));
  if (!POLL.enter('stuck', true)) fail('a wedged key must free itself after the watchdog window');
  console.log('PASS coalesce: single flight, one rerun, loud wins, watchdog frees a wedged key');
  process.exit(0);
}
console.error('unknown scenario'); process.exit(2);
