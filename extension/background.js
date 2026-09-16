// Neuro Search extension — background (MV3 service worker).
// Jobs, all against the user's OWN Neuro Search server and nothing else:
//   1. a heartbeat every few minutes so the app can say "extension ready / last seen N min ago / not detected";
//   2. the list of pages the app is waiting for the browser to capture, so the toolbar badge lights on such a tab
//      ("Neuro Search wants this page"). Nothing is captured without the user pressing the button in the popup.
//   3. (1.7.0, mission CS) the durable STATE and CONTROL PLANE of a course scan. The traversal itself runs in the
//      course tab (scanner.js + scan-lib.js); this worker records every lesson outcome in chrome.storage.local the
//      moment it arrives, answers "should I stop?", and notices when the tab goes away. MV3 may evict this worker
//      at any time: that is fine because each message from the page wakes it and nothing lives only in memory —
//      never because it "stays alive".
const ALARM = 'neurosearch-heartbeat';
const WATCH = 'neurosearch-scan-watch';
const VERSION = chrome.runtime.getManifest().version;

async function cfg() { return chrome.storage.local.get(['appUrl', 'token']); }

async function api(path, opts = {}) {
  const c = await cfg();
  if (!c.appUrl || !c.token) return null;
  const r = await fetch(c.appUrl + path, { ...opts, headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + c.token, ...(opts.headers || {}) } });
  if (!r.ok) throw new Error('app answered ' + r.status);
  return r.json();
}

// Same contract as api(), but for a FormData body (screenshot upload): deliberately does NOT set Content-Type —
// the browser must generate its own `multipart/form-data; boundary=...` header, which a hardcoded JSON header
// would break. Throws (never returns null-silently) on missing config, since a failed screenshot send needs to
// surface to the caller rather than vanish the way a background heartbeat miss safely can.
async function apiForm(path, formData) {
  const c = await cfg();
  if (!c.appUrl || !c.token) throw new Error('Neuro Search is not set up yet (open the popup and add your app URL + token).');
  const r = await fetch(c.appUrl + path, { method: 'POST', headers: { Authorization: 'Bearer ' + c.token }, body: formData });
  if (!r.ok) throw new Error('app answered ' + r.status);
  return r.json();
}

function canon(u) {
  try { const x = new URL(u); x.hash = ''; x.search = ''; return (x.origin + x.pathname).replace(/^https?:\/\/(www\.|old\.|new\.)?/, 'https://').replace(/\/$/, ''); } catch (e) { return u; }
}

async function refreshPending() {
  try {
    await api('/api/extension/heartbeat', { method: 'POST', body: JSON.stringify({ version: VERSION }) });
    const p = await api('/api/capture/pending');
    const items = (p && p.items) || [];
    await chrome.storage.local.set({ pending: items, pendingAt: Date.now() });
    await paintAll(items);
  } catch (e) { /* the app is unreachable: keep the last list, say nothing */ }
}

async function paintAll(items) {
  const tabs = await chrome.tabs.query({});
  for (const t of tabs) await paint(t, items);
}

async function paint(tab, items) {
  if (!tab || !tab.id || !tab.url) return;
  const list = items || (await chrome.storage.local.get('pending')).pending || [];
  const want = canon(tab.url);
  const hit = list.find(i => canon(i.canonical_url || i.url || '') === want);
  try {
    if (hit) {
      await chrome.action.setBadgeText({ tabId: tab.id, text: '●' });
      await chrome.action.setBadgeBackgroundColor({ tabId: tab.id, color: '#2f5bea' });
      await chrome.action.setTitle({ tabId: tab.id, title: `Neuro Search wants this page — ${hit.project_name || 'project'}` });
    } else if (list.length) {
      await chrome.action.setBadgeText({ tabId: tab.id, text: String(list.length) });
      await chrome.action.setBadgeBackgroundColor({ tabId: tab.id, color: '#8a94a6' });
      await chrome.action.setTitle({ tabId: tab.id, title: `Neuro Search — ${list.length} page${list.length === 1 ? '' : 's'} waiting for your browser` });
    } else {
      await chrome.action.setBadgeText({ tabId: tab.id, text: '' });
      await chrome.action.setTitle({ tabId: tab.id, title: 'Neuro Search' });
    }
  } catch (e) { /* tab vanished */ }
}

// ================================================================== course scan: durable state + control plane
// One record per TAB, keyed `scan:<tabId>`, carrying its own `scan_id` nonce. Every message from the page and the
// popup names a scan_id; a message whose scan_id is not the tab's current one is a superseded runner (double
// injection, a restart) and is told to stop rather than merged. A record outlives the popup, the worker and the
// scan itself, so reopening the popup shows the finished inventory until the next scan on that tab replaces it.
const ACTIVE = new Set(['finding', 'scanning']);
const key = tabId => `scan:${tabId}`;
const now = () => Date.now();

async function getScan(tabId) { return (await chrome.storage.local.get(key(tabId)))[key(tabId)] || null; }

async function putScan(rec) { await chrome.storage.local.set({ [key(rec.tab_id)]: rec }); }

// Every mutation of a tab's record runs under this per-tab queue: a lesson event from the page and a cancel from
// the popup can arrive in the same instant, and a read-modify-write race would drop one of them. The runner waits
// for the reply before its next step, so a lesson boundary is on disk before the page continues — that, not the
// worker staying alive, is what makes a scan survive popup close, worker eviction and browser focus changes.
const locks = new Map();
function withScan(tabId, fn) {
  const prev = locks.get(tabId) || Promise.resolve();
  const next = prev.then(fn, fn);
  locks.set(tabId, next.catch(() => {}));
  return next;
}

function summarize(rec) {
  const c = { video_found: 0, multiple_videos: 0, no_video: 0, needs_user_play: 0, blocked: 0, scan_failed: 0, not_scanned: 0 };
  for (const l of rec.lessons || []) c[l.outcome] = (c[l.outcome] || 0) + 1;
  const ready = c.video_found + c.multiple_videos;
  const attention = c.no_video + c.needs_user_play + c.blocked;
  const unread = c.scan_failed + c.not_scanned;
  return { ...c, ready, attention, unread, completed: (rec.lessons || []).length, expected: rec.expected || 0 };
}

async function startScan(tabId) {
  const cur = await getScan(tabId);
  if (cur && ACTIVE.has(cur.status)) return { error: 'A scan is already running in this tab.', scan: cur };
  let tab; try { tab = await chrome.tabs.get(tabId); } catch (e) { return { error: 'That tab is gone.' }; }
  if (!tab.url || !/^https?:/.test(tab.url)) return { error: 'This page cannot be scanned (not a web page).' };
  // the page may still have a runner from an earlier popup even if our record says otherwise: ask before injecting
  try {
    const [{ result: active }] = await chrome.scripting.executeScript({ target: { tabId }, func: () => globalThis.__nsScanActive || null });
    if (active) return { error: 'A scan is already running in this tab.', scan: cur };
  } catch (e) { return { error: 'Cannot scan this page: ' + (e.message || e) }; }
  const scan_id = (crypto.randomUUID ? crypto.randomUUID() : String(now()) + Math.random());
  const rec = { scan_id, tab_id: tabId, origin: new URL(tab.url).origin, url: tab.url, title: tab.title || '', strategy: null,
                started_at: now(), updated_at: now(), finished_at: null, status: 'finding', reason: null,
                expected: 0, current: null, lessons: [], errors: [], diagnosis: null, duplicates: {}, course: null };
  await putScan(rec);
  try {
    await chrome.scripting.executeScript({ target: { tabId }, func: (r) => { globalThis.__nsScanReq = r; }, args: [{ scan_id, tab_id: tabId }] });
    await chrome.scripting.executeScript({ target: { tabId }, files: ['scan-lib.js', 'scanner.js'] });
  } catch (e) {
    rec.status = 'failed'; rec.reason = 'inject_failed'; rec.errors.push(String(e.message || e).slice(0, 200)); rec.finished_at = now();
    await putScan(rec); return { error: 'Cannot scan this page: ' + (e.message || e), scan: rec };
  }
  chrome.alarms.create(WATCH, { periodInMinutes: 0.5 });
  return { ok: true, scan: rec };
}

async function cancelScan(tabId) {
  const rec = await getScan(tabId);
  if (!rec || !ACTIVE.has(rec.status)) return { ok: false };
  rec.cancel_requested = true; rec.updated_at = now(); await putScan(rec);
  try { await chrome.tabs.sendMessage(tabId, { type: 'scan-cancel', scan_id: rec.scan_id }); } catch (e) { /* the poll at the next boundary will see it */ }
  return { ok: true, scan: rec };
}

async function finishScan(rec, status, reason) {
  if (!ACTIVE.has(rec.status)) return;
  rec.status = status; rec.reason = reason || null; rec.finished_at = now(); rec.updated_at = now(); rec.current = null;
  await putScan(rec);
}

// A message from the page about a scan. Returns what the runner needs to know: whether to stop.
async function onScanEvent(m, sender) {
  const tabId = sender.tab && sender.tab.id;
  if (!tabId) return { ignored: true, cancel: true };
  const rec = await getScan(tabId);
  if (!rec || rec.scan_id !== m.scan_id) return { ignored: true, cancel: true };   // superseded runner: stop
  if (!ACTIVE.has(rec.status)) return { cancel: true };
  rec.updated_at = now();
  switch (m.event) {
    case 'lessons-found':
      rec.status = 'scanning'; rec.strategy = m.strategy; rec.expected = m.expected || 0; break;
    case 'lesson':
      if (m.record) { rec.lessons.push(m.record); rec.current = null; }
      break;
    case 'done': {
      const s = m.summary || m;
      rec.course = s.course || rec.course; rec.diagnosis = s.diagnosis || rec.diagnosis; rec.duplicates = s.duplicates || {};
      rec.expected = s.expected || rec.expected; rec.strategy = s.strategy || rec.strategy;
      if (s.lessons && s.lessons.length >= rec.lessons.length) rec.lessons = s.lessons;
      const sum = summarize(rec);
      const status = s.status === 'cancelled' ? 'cancelled' : (sum.unread > 0 || (rec.expected && sum.completed < rec.expected)) ? 'partial' : 'done';
      await finishScan(rec, status, s.status === 'cancelled' ? 'cancelled' : null); return { cancel: false };
    }
    case 'failed':
      rec.errors.push(String(m.detail || 'failed').slice(0, 300)); await finishScan(rec, rec.lessons.length ? 'partial' : 'failed', 'runner_error'); return { cancel: true };
    case 'refused':
      return { cancel: true };
    case 'poll':
    default:
      break;
  }
  await putScan(rec);
  return { cancel: !!rec.cancel_requested };
}

// Liveness: only the runner going away ends a scan early — never a URL change by itself (an app course moves its
// address while switching lessons). Tab closed → interrupted. Origin changed → interrupted. Navigation that killed
// the isolated world → the ping gets no listener → interrupted, partial kept.
function checkAlive(tabId, why) { return withScan(tabId, () => _checkAlive(tabId, why)); }
async function _checkAlive(tabId, why) {
  const rec = await getScan(tabId); if (!rec || !ACTIVE.has(rec.status)) return;
  let tab; try { tab = await chrome.tabs.get(tabId); } catch (e) { return finishScan(rec, rec.lessons.length ? 'partial' : 'interrupted', 'tab_closed'); }
  try { if (new URL(tab.url).origin !== rec.origin) return finishScan(rec, rec.lessons.length ? 'partial' : 'interrupted', 'origin_changed'); } catch (e) { /* no url yet */ }
  try {
    const r = await chrome.tabs.sendMessage(tabId, { type: 'scan-ping', scan_id: rec.scan_id });
    if (!r || !r.alive) throw new Error('no runner');
  } catch (e) {
    // a runner that finished normally has already sent 'done'; one that is silent AND absent is gone
    const fresh = await getScan(tabId);
    if (fresh && ACTIVE.has(fresh.status)) await finishScan(fresh, fresh.lessons.length ? 'partial' : 'interrupted', why || 'navigated');
  }
}

async function anyActive() {
  const all = await chrome.storage.local.get(null);
  return Object.entries(all).filter(([k, v]) => k.startsWith('scan:') && v && ACTIVE.has(v.status)).map(([, v]) => v);
}

async function pruneScans() {
  const all = await chrome.storage.local.get(null); const dead = [];
  for (const [k, v] of Object.entries(all)) if (k.startsWith('scan:') && v && (now() - (v.updated_at || 0) > 7 * 86400e3)) dead.push(k);
  if (dead.length) await chrome.storage.local.remove(dead);
}


// ================================================================== send screenshot: durable state + capture engine
// docs/SEND-SCREENSHOT-2026-09-16.md. One record per TAB, keyed `capture:<tabId>`, mirroring the scan record above
// (same reason: MV3 may evict this worker mid-capture, and the popup may close mid-capture — the record on disk,
// not anything held only in memory, is what a reopened popup renders and what survives eviction). Unlike a scan,
// the capture loop is driven entirely from THIS file (no content-script runner reporting back over messages):
// chrome.tabs.captureVisibleTab is a background-only API, so the orchestration has to live here regardless.
const CAPTURE_ACTIVE = new Set(['capturing', 'uploading']);
const captureKey = tabId => `capture:${tabId}`;
// Reuses the same per-tab promise-chain lock as scans (withScan): a capture also scrolls the page and would race
// badly against a scan doing DOM work in the same tab, so serializing the two behind one lock is correct, not
// just convenient.
const withCapture = withScan;

async function getCapture(tabId) { return (await chrome.storage.local.get(captureKey(tabId)))[captureKey(tabId)] || null; }
async function putCapture(rec) { await chrome.storage.local.set({ [captureKey(rec.tab_id)]: rec }); }

// Three runtime ceilings, enforced PER FOLD (not once up front): a lazy/infinite-scroll page can keep growing
// while it is being scrolled, so the loop re-measures scrollHeight after every fold and can only ever find out a
// ceiling was crossed just after crossing it — never before. When one trips, whatever was already stitched is kept
// and the result is labeled full_page with a capture_partial_reason, rather than thrown away for a single shot.
const CAPTURE_MAX_TOTAL_PIXELS = 40_000_000;   // full-resolution (post-DPR) pixels across every fold, combined
const CAPTURE_MAX_FOLDS = 30;
const CAPTURE_MAX_ELAPSED_MS = 60_000;
const CAPTURE_WATCHDOG_MS = 20_000;            // in-page self-heal window, armed on every sticky/fixed hide (below)
const CAPTURE_SETTLE_MS = 140;                 // scroll landing: setTimeout-based wait, not rAF — Phase 1 spike
const CAPTURE_HIDE_SETTLE_MS = 60;             // measured background-tab rAF throttling to ~1fps, so a bounded
                                                // setTimeout poll (the scan-lib.js settle() pattern) is the only
                                                // reliable way to wait for a repaint from this file.

async function execFn(tabId, func, args) {
  const [{ result }] = await chrome.scripting.executeScript({ target: { tabId }, func, args: args || [] });
  return result;
}

// ---- functions injected into the page (chrome.scripting.executeScript func:) live in capture-lib.js, loaded
// below via importScripts so the exact same, unmodified source can be exercised under jsdom
// (tests/js/run-capture.mjs) — the same technique scan-lib.js uses for the course scanner. They are plain,
// self-contained functions (no closures over background.js state) because executeScript serializes a function
// reference by its source text, wherever that function happens to be defined.
importScripts('capture-lib.js');
const { nsMeasure, nsScrollTo, nsHideAndArm, nsRestore } = self.NSCaptureLib;

// ---- background-side orchestration

// Stitches PNG data URLs (one per fold, already cropped to the viewport by the browser) into one tall PNG using
// OffscreenCanvas, which is available in MV3 service workers. Later folds may overlap the previous fold's bottom
// edge by less than a full viewport height on the final fold (the last scroll position is clamped to
// pageHeight - viewportHeight); the caller passes the exact draw Y for each shot so there is no double-drawing.
async function stitchShots(shots, pageWidthCss, pageHeightCss, dpr) {
  const w = Math.round(pageWidthCss * dpr), h = Math.round(pageHeightCss * dpr);
  const canvas = new OffscreenCanvas(w, h);
  const ctx = canvas.getContext('2d');
  for (const shot of shots) {
    const resp = await fetch(shot.dataUrl);
    const blob = await resp.blob();
    const bmp = await createImageBitmap(blob);
    ctx.drawImage(bmp, 0, Math.round(shot.y * dpr));
    bmp.close();
  }
  const outBlob = await canvas.convertToBlob({ type: 'image/png' });
  return outBlob;
}

async function runCapture(tabId, rec) {
  const startedAt = now();
  let origScrollX = 0, origScrollY = 0;
  let restored = false;
  const restore = async () => {
    if (restored) return; restored = true;
    try { await execFn(tabId, nsRestore); } catch (e) { /* watchdog will self-heal if this fails */ }
    try { await execFn(tabId, (x, y) => { window.scrollTo({ left: x, top: y, behavior: 'instant' }); }, [origScrollX, origScrollY]); } catch (e) {}
  };
  try {
    const m0 = await execFn(tabId, nsMeasure);
    origScrollX = m0.scrollX; origScrollY = m0.scrollY;
    const dpr = m0.dpr || 1;
    rec.title = m0.title || rec.title;
    rec.updated_at = now();
    await putCapture(rec);

    const viewportH = m0.viewportHeight;
    let pageH = m0.scrollHeight;
    let fold = 0, y = 0;
    const shots = [];
    let partialReason = null;

    while (true) {
      if (now() - startedAt > CAPTURE_MAX_ELAPSED_MS) { partialReason = 'ceiling_time'; break; }
      if (fold >= CAPTURE_MAX_FOLDS) { partialReason = 'ceiling_folds'; break; }

      await execFn(tabId, nsScrollTo, [0, y, CAPTURE_SETTLE_MS]);
      if (fold > 0) {
        await execFn(tabId, nsHideAndArm, [CAPTURE_WATCHDOG_MS]);
        await new Promise(r => setTimeout(r, CAPTURE_HIDE_SETTLE_MS));
      }
      let dataUrl;
      try {
        dataUrl = await chrome.tabs.captureVisibleTab(undefined, { format: 'png' });
      } finally {
        if (fold > 0) { try { await execFn(tabId, nsRestore); } catch (e) {} }
      }
      shots.push({ y, dataUrl });
      fold += 1;
      rec.fold = fold; rec.updated_at = now();
      await putCapture(rec);

      // Re-measure AFTER this fold: the page may have grown while it was being scrolled (lazy/infinite content).
      const m = await execFn(tabId, nsMeasure);
      pageH = Math.max(pageH, m.scrollHeight);

      const totalPixels = m0.viewportWidth * dpr * Math.min(pageH, fold * viewportH) * dpr;
      if (totalPixels > CAPTURE_MAX_TOTAL_PIXELS) { partialReason = 'ceiling_pixels'; break; }

      const nextY = fold * viewportH;
      if (nextY >= pageH - 2) break;   // reached the true bottom
      y = Math.min(nextY, pageH - viewportH > 0 ? pageH - viewportH : nextY);
    }

    await restore();

    if (!shots.length) throw new Error('capture produced no image');

    // Single fold and nothing forced a stop: this is the honest "visible area only" tier, not a stitched page.
    if (shots.length === 1 && !partialReason) {
      const resp = await fetch(shots[0].dataUrl);
      const blob = await resp.blob();
      return {
        blob, mode: 'visible_only', partial_reason: null,
        dimensions: { page_width: m0.scrollWidth, page_height: viewportH, viewport_width: m0.viewportWidth, viewport_height: viewportH, dpr },
        title: rec.title,
      };
    }

    const finalPageH = Math.min(pageH, shots[shots.length - 1].y + viewportH);
    const blob = await stitchShots(shots, m0.scrollWidth, finalPageH, dpr);
    return {
      blob, mode: 'full_page', partial_reason: partialReason,
      dimensions: { page_width: m0.scrollWidth, page_height: finalPageH, viewport_width: m0.viewportWidth, viewport_height: viewportH, dpr },
      title: rec.title,
    };
  } catch (e) {
    await restore();
    throw e;
  }
}

async function startCapture(tabId, projectId, note) {
  const cur = await getCapture(tabId);
  if (cur && CAPTURE_ACTIVE.has(cur.status)) return { error: 'A screenshot capture is already running in this tab.', capture: cur };
  let tab; try { tab = await chrome.tabs.get(tabId); } catch (e) { return { error: 'That tab is gone.' }; }
  if (!tab.url || !/^https?:/.test(tab.url)) return { error: 'This page cannot be captured (not a web page).' };
  const capture_id = (crypto.randomUUID ? crypto.randomUUID() : String(now()) + Math.random());
  const rec = {
    capture_id, tab_id: tabId, url: tab.url, title: tab.title || '', project_id: projectId || null, note: note || null,
    status: 'capturing', fold: 0, started_at: now(), updated_at: now(), finished_at: null, error: null, result: null,
  };
  await putCapture(rec);

  (async () => {
    try {
      const out = await runCapture(tabId, rec);
      rec.status = 'uploading'; rec.updated_at = now(); await putCapture(rec);

      const fd = new FormData();
      const filename = 'screenshot-' + capture_id.slice(0, 8) + '.png';
      fd.append('file', out.blob, filename);
      if (out.title) fd.append('title', out.title);
      if (rec.project_id) fd.append('project_id', rec.project_id);
      fd.append('immediate', 'false');
      fd.append('capture_url', rec.url);
      if (out.title) fd.append('capture_page_title', out.title);
      fd.append('captured_at', String(rec.started_at / 1000));
      fd.append('capture_mode', out.mode);
      if (out.partial_reason) fd.append('capture_partial_reason', out.partial_reason);
      if (out.dimensions) {
        fd.append('capture_page_width', String(Math.round(out.dimensions.page_width)));
        fd.append('capture_page_height', String(Math.round(out.dimensions.page_height)));
        fd.append('capture_viewport_width', String(Math.round(out.dimensions.viewport_width)));
        fd.append('capture_viewport_height', String(Math.round(out.dimensions.viewport_height)));
        fd.append('capture_dpr', String(out.dimensions.dpr));
      }
      if (rec.note) fd.append('capture_note', rec.note);

      const uploadRes = await apiForm('/api/ingest/file', fd);
      rec.status = 'done'; rec.finished_at = now(); rec.updated_at = now();
      rec.result = { mode: out.mode, partial_reason: out.partial_reason, job_id: uploadRes && uploadRes.job };
      await putCapture(rec);
    } catch (e) {
      rec.status = 'failed'; rec.error = String((e && e.message) || e).slice(0, 300); rec.finished_at = now(); rec.updated_at = now();
      await putCapture(rec);
    }
  })();

  return { ok: true, capture: rec };
}

async function pruneCaptures() {
  const all = await chrome.storage.local.get(null); const dead = [];
  for (const [k, v] of Object.entries(all)) if (k.startsWith('capture:') && v && (now() - (v.updated_at || 0) > 7 * 86400e3)) dead.push(k);
  if (dead.length) await chrome.storage.local.remove(dead);
}

chrome.runtime.onInstalled.addListener(() => { chrome.alarms.create(ALARM, { periodInMinutes: 5 }); refreshPending(); pruneScans(); pruneCaptures(); });
chrome.runtime.onStartup.addListener(async () => {
  chrome.alarms.create(ALARM, { periodInMinutes: 5 }); refreshPending(); pruneScans(); pruneCaptures();
  // the browser restarted: every runner is gone, whatever the records say
  for (const rec of await anyActive()) await withScan(rec.tab_id, () => finishScan(rec, rec.lessons.length ? 'partial' : 'interrupted', 'browser_restarted'));
});
chrome.alarms.onAlarm.addListener(async a => {
  if (a.name === ALARM) refreshPending();
  if (a.name === WATCH) {
    const active = await anyActive();
    if (!active.length) { chrome.alarms.clear(WATCH); return; }
    for (const rec of active) await checkAlive(rec.tab_id, 'runner_silent');
  }
});
chrome.tabs.onUpdated.addListener((tabId, info, tab) => {
  if (info.status === 'complete' || info.url) paint(tab);
  // a document load may or may not have killed the runner: ask it, after it has had a moment to (re)appear
  if (info.status === 'loading') setTimeout(() => checkAlive(tabId, 'navigated'), 1500);
});
chrome.tabs.onRemoved.addListener(tabId => { checkAlive(tabId, 'tab_closed'); });
chrome.tabs.onActivated.addListener(async ({ tabId }) => { try { paint(await chrome.tabs.get(tabId)); } catch (e) {} });
chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (!msg) return;
  if (msg.type === 'refresh-pending') { refreshPending().then(() => reply({ ok: true })); return true; }
  if (msg.type === 'scan-event') { const t = sender.tab && sender.tab.id; withScan(t, () => onScanEvent(msg, sender)).then(reply, e => reply({ error: String(e), cancel: true })); return true; }
  if (msg.type === 'scan-start') { withScan(msg.tabId, () => startScan(msg.tabId)).then(reply, e => reply({ error: String(e) })); return true; }
  if (msg.type === 'scan-cancel') { withScan(msg.tabId, () => cancelScan(msg.tabId)).then(reply, e => reply({ error: String(e) })); return true; }
  if (msg.type === 'scan-get') { getScan(msg.tabId).then(s => reply({ scan: s, summary: s ? summarize(s) : null }), e => reply({ error: String(e) })); return true; }
  if (msg.type === 'capture-start') { withCapture(msg.tabId, () => startCapture(msg.tabId, msg.projectId, msg.note)).then(reply, e => reply({ error: String(e) })); return true; }
  if (msg.type === 'capture-get') { getCapture(msg.tabId).then(c => reply({ capture: c }), e => reply({ error: String(e) })); return true; }
});
