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
  await captureInit;   // MV3 worker-respawn race: never act on a capture record from before reconciliation ran
  const cur = await getScan(tabId);
  if (cur && ACTIVE.has(cur.status)) return { error: 'A scan is already running in this tab.', scan: cur };
  const curCapture = await getCapture(tabId);
  if (curCapture && CAPTURE_ACTIVE.has(curCapture.status)) return { error: 'A screenshot capture is already running in this tab — wait for it to finish before scanning.' };
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
// docs/SEND-SCREENSHOT-2026-09-16.md, repair round (Kyle-approved plan, "Approved to execute. Behind now."). One
// record per TAB, keyed `capture:<tabId>`, mirroring the scan record above (same reason: MV3 may evict this
// worker mid-capture, and the popup may close mid-capture — the record on disk, not anything held only in
// memory, is what a reopened popup renders and what survives eviction). Unlike a scan, the capture loop is
// driven entirely from THIS file (no content-script runner reporting back over messages): chrome.tabs.
// captureVisibleTab is a background-only API, so the orchestration has to live here regardless.
// 'captured' (repair round 3, gap #C): a durable intermediate state between the raw capture finishing and
// the upload actually starting -- see startCapture's async IIFE below for why it exists. It is an ACTIVE
// state exactly like 'capturing'/'uploading': a second capture must not start while this tab's record is
// passing through it, however briefly.
const CAPTURE_ACTIVE = new Set(['capturing', 'captured', 'uploading']);
const captureKey = tabId => `capture:${tabId}`;
// Reuses the same per-tab promise-chain lock as scans (withScan): a capture also scrolls the page and would race
// badly against a scan doing DOM work in the same tab, so serializing the two behind one lock is correct, not
// just convenient. It is also how startScan/startCapture's mutual-exclusion checks above stay race-free.
const withCapture = withScan;

async function getCapture(tabId) {
  await captureInit;   // gated call site: capture-get must never read a record from before reconciliation ran
  return (await chrome.storage.local.get(captureKey(tabId)))[captureKey(tabId)] || null;
}
async function putCapture(rec) { await chrome.storage.local.set({ [captureKey(rec.tab_id)]: rec }); }

// Three runtime ceilings, enforced against ACTUAL captured (post-dedup) tiles, never the planned grid size — a
// lazy/infinite-scroll page can keep growing while it is being scrolled (2D: both taller AND wider). When one
// trips, whatever was already stitched is kept and the result is labeled partial_page with a
// capture_partial_reason, rather than thrown away for a single shot.
const CAPTURE_MAX_TOTAL_PIXELS = 40_000_000;   // full-resolution (post-DPR) pixels across every tile, combined
const CAPTURE_MAX_TILES = 60;                  // 2D grid raises the practical tile count over the old 1D fold cap
const CAPTURE_MAX_ELAPSED_MS = 60_000;
const CAPTURE_WATCHDOG_MS = 20_000;            // in-page self-heal window, armed on every sticky/fixed hide (below)
const CAPTURE_SETTLE_MS = 140;                 // scroll landing: setTimeout-based wait, not rAF — Phase 1 spike
const CAPTURE_HIDE_SETTLE_MS = 60;             // measured background-tab rAF throttling to ~1fps, so a bounded
                                                // setTimeout poll (the scan-lib.js settle() pattern) is the only
                                                // reliable way to wait for a repaint from this file.
const CAPTURE_MIN_CALL_INTERVAL_MS = 600;      // BLOCKER fix: captureVisibleTab is capped at ~2 calls/sec across
                                                // the WHOLE browser (every extension, every tab) — not just within
                                                // one capture — so the throttle has to be global, not per-loop.

async function execFn(tabId, func, args) {
  const [{ result }] = await chrome.scripting.executeScript({ target: { tabId }, func, args: args || [] });
  return result;
}

// ---- functions injected into the page (chrome.scripting.executeScript func:) live in capture-lib.js, loaded
// below via importScripts so the exact same, unmodified source can be exercised under jsdom
// (tests/js/run-capture.mjs) — the same technique scan-lib.js uses for the course scanner. They are plain,
// self-contained functions (no closures over background.js state) because executeScript serializes a function
// reference by its source text, wherever that function happens to be defined. capture-lib.js also carries the
// PURE (non-DOM) tiling/ceiling/rate-limit/reconciliation helpers used directly below, and capture-blob-store.js
// carries the durable IndexedDB blob store (service-worker-only — never page-injected, unlike capture-lib.js).
importScripts('capture-lib.js', 'capture-blob-store.js');
const { nsMeasure, nsScrollTo, nsHideAndArm, nsRestore, nsPlanTileGrid, nsIsDuplicateTile, nsCheckCeilings,
        nsStitchScale, nsRateLimitWaitMs, nsIsFallbackEligible, nsReconcileDecision, nsPageIdentity } = self.NSCaptureLib;
const NSBlobStore = self.NSCaptureBlobStore;

// ---- tagged errors gate whether the visible-area fallback is attempted (BLOCKER fix: fallback ONLY for a
// genuine capture-MECHANISM failure — stitching/OffscreenCanvas/transient captureVisibleTab error — NEVER for a
// TAB-IDENTITY failure, since falling back after the target tab stopped being the active tab, changed origin, or
// disappeared would silently attribute someone else's page to this capture's evidence).
class TabIdentityError extends Error { constructor(msg) { super(msg); this.name = 'TabIdentityError'; this.nsErrorKind = 'TabIdentityError'; } }
class CaptureMechanismError extends Error { constructor(msg) { super(msg); this.name = 'CaptureMechanismError'; this.nsErrorKind = 'CaptureMechanismError'; } }

// BLOCKER fix: captureVisibleTab captures the ACTIVE tab of a WINDOW, not an arbitrary tabId — so every single
// call (every tile, plus the fallback) re-verifies that our target tab is still Chrome's active tab, still on an
// http(s) URL, and (once an expectedIdentity is known) still the same document (origin+pathname+search), and
// returns the tab's REAL
// windowId to pass explicitly (never undefined — undefined means "whichever window currently has focus", which
// is not necessarily this tab's window).
// repair round 3 (gap #B): expectedIdentity pins origin+pathname+search (nsPageIdentity), not origin alone --
// a same-origin navigation (example.com/calculator -> example.com/dashboard) used to pass this check unnoticed,
// even though the uploaded provenance (rec.url) still names the URL recorded when the capture started. Evidence
// identity must fail closed on ANY same-document-boundary change, not just a cross-origin one.
async function verifyTabIdentity(tabId, expectedIdentity) {
  let tab;
  try { tab = await chrome.tabs.get(tabId); } catch (e) { throw new TabIdentityError('the tab is gone'); }
  if (!tab.active) throw new TabIdentityError('the tab is no longer the active tab in its window — switch back to it and try again');
  if (!tab.url || !/^https?:/.test(tab.url)) throw new TabIdentityError('the tab navigated away from a capturable page');
  let identity;
  try { identity = nsPageIdentity(tab.url); } catch (e) { throw new TabIdentityError('the tab has no readable URL'); }
  if (expectedIdentity && identity !== expectedIdentity) throw new TabIdentityError('the tab navigated to a different page mid-capture');
  return tab;
}

// Global rate limiter: chrome.storage.session (not .local) survives worker eviction/respawn but correctly resets
// on an actual browser restart (a fresh browser session has made zero captureVisibleTab calls yet). Guarded by
// an in-process async lock — two concurrent captures in different tabs must serialize their read-wait-call-write
// sequence, or both could read the same "last call" timestamp and both proceed immediately, busting the cap.
let _rateLimitLock = Promise.resolve();
function withRateLimit(fn) {
  const run = _rateLimitLock.then(fn, fn);
  _rateLimitLock = run.catch(() => {});
  return run;
}
async function throttledCaptureVisibleTab(windowId) {
  return withRateLimit(async () => {
    const s = await chrome.storage.session.get('nsLastCaptureVisibleTabAt');
    const wait = nsRateLimitWaitMs(s.nsLastCaptureVisibleTabAt ?? null, now(), CAPTURE_MIN_CALL_INTERVAL_MS);
    if (wait > 0) await new Promise(r => setTimeout(r, wait));
    const dataUrl = await chrome.tabs.captureVisibleTab(windowId, { format: 'png' });
    await chrome.storage.session.set({ nsLastCaptureVisibleTabAt: now() });
    return dataUrl;
  });
}

// Stitches PNG data URLs into one page-shaped PNG using OffscreenCanvas (available in MV3 service workers).
// scale comes from the FIRST tile's real bitmap width vs its CSS viewport width (not devicePixelRatio alone —
// zoom/rounding/mid-capture display changes can make dpr wrong) and is applied to every placement, including the
// canvas's own size, for internal consistency. Each shot is drawn at its ACTUAL LANDED (x, y) — not the
// requested scroll target — since nsScrollTo can land short of a request (page too short to scroll further,
// scroll-anchoring, etc), and the caller already deduped on landed coordinates too.
async function stitchShots(shots, pageWidthCss, pageHeightCss) {
  let scale = 1;
  const bitmaps = [];
  try {
    for (const shot of shots) {
      const resp = await fetch(shot.dataUrl);
      const blob = await resp.blob();
      bitmaps.push({ shot, bmp: await createImageBitmap(blob) });
    }
    // hardening item (repair round 2): scale is derived from the FIRST bitmap only, which silently assumed every
    // later tile shares its dimensions. captureVisibleTab should produce uniform output for one tab/window across
    // a single capture run, but a mismatch (a mid-capture DPR/zoom change, a window resize) would otherwise
    // corrupt placement math for every tile after the first with no signal at all. Fail loudly instead.
    const firstW = bitmaps[0].bmp.width, firstH = bitmaps[0].bmp.height;
    const mismatch = bitmaps.find(b => b.bmp.width !== firstW || b.bmp.height !== firstH);
    if (mismatch) {
      throw new CaptureMechanismError(
        `captured tiles have inconsistent bitmap dimensions (expected ${firstW}x${firstH}, got ${mismatch.bmp.width}x${mismatch.bmp.height}) — the browser window or zoom level may have changed mid-capture`);
    }
    scale = nsStitchScale(bitmaps[0].bmp.width, shots[0].viewportWidthCss || pageWidthCss);
    const w = Math.max(1, Math.round(pageWidthCss * scale));
    const h = Math.max(1, Math.round(pageHeightCss * scale));
    // repair round 3 (gap #A): preflight the actual canvas allocation against the SAME 40M ceiling the capture
    // loop enforces on tile count, so the ceiling is a hard limit on what gets allocated/assembled, not just an
    // after-the-fact threshold checked against per-tile counting that the caller could still get wrong. This is
    // a backstop, not the primary fix -- the caller (runCapture) is responsible for passing an already-bounded
    // pageWidthCss/pageHeightCss (the captured tiles' own bounding box on a partial capture), but stitchShots
    // itself must never attempt to allocate an unbounded canvas no matter what it's asked to stitch.
    if (w * h > CAPTURE_MAX_TOTAL_PIXELS) {
      throw new CaptureMechanismError(
        `refusing to assemble a ${w}x${h} image (${w * h} pixels) — exceeds the ${CAPTURE_MAX_TOTAL_PIXELS}-pixel safety ceiling`);
    }
    const canvas = new OffscreenCanvas(w, h);
    const ctx = canvas.getContext('2d');
    for (const { shot, bmp } of bitmaps) ctx.drawImage(bmp, Math.round(shot.x * scale), Math.round(shot.y * scale));
    return { blob: await canvas.convertToBlob({ type: 'image/png' }), scale };
  } catch (e) {
    throw new CaptureMechanismError('could not assemble the captured tiles: ' + String((e && e.message) || e));
  } finally {
    for (const { bmp } of bitmaps) { try { bmp.close(); } catch (e) {} }
  }
}

// The 5-step ordered visible-area fallback (repair round 2's design), reached ONLY on a CaptureMechanismError
// from the tiled attempt — never on a TabIdentityError, which is rethrown as-is instead (see runCapture). Each
// step matters in this order: undo whatever mid-flight state the failed tiled attempt left BEFORE trying
// anything else, then re-establish that the tab is still genuinely the one we mean to capture (a mechanism
// failure earlier does not excuse skipping this — identity could have ALSO changed in the meantime), then obey
// the same global throttle as every other call, then capture, then label the result honestly.
async function fallbackVisibleCapture(tabId, expectedIdentity, origScrollX, origScrollY) {
  // 1. restore styles + original scroll position
  try { await execFn(tabId, nsRestore); } catch (e) {}
  try { await execFn(tabId, (x, y) => { window.scrollTo({ left: x, top: y, behavior: 'instant' }); }, [origScrollX, origScrollY]); } catch (e) {}
  await new Promise(r => setTimeout(r, CAPTURE_HIDE_SETTLE_MS));
  // 2. freshly re-verify tab/window/document-identity/active-state
  const tab = await verifyTabIdentity(tabId, expectedIdentity);
  // 3. obey the same global throttle (inside throttledCaptureVisibleTab)
  // 4. capture
  const dataUrl = await throttledCaptureVisibleTab(tab.windowId);
  const m = await execFn(tabId, nsMeasure);
  const resp = await fetch(dataUrl);
  const blob = await resp.blob();
  // 5. label
  return {
    blob, mode: 'visible_only', partial_reason: 'fallback_after_error',
    dimensions: { page_width: m.scrollWidth, page_height: m.viewportHeight, viewport_width: m.viewportWidth, viewport_height: m.viewportHeight, dpr: m.dpr },
    title: m.title,
  };
}

async function runCapture(tabId, rec) {
  const startedAt = now();
  let origScrollX = 0, origScrollY = 0;
  let restored = false;
  let firstTileCaptured = false;

  const tab0 = await verifyTabIdentity(tabId, null);          // TabIdentityError here propagates as-is — no fallback
  const expectedIdentity = nsPageIdentity(tab0.url);   // gap #B: pins origin+pathname+search, not origin alone

  const restoreStylesAndScroll = async () => {
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

    const viewportWidth = m0.viewportWidth, viewportHeight = m0.viewportHeight;
    let dims = { scrollWidth: m0.scrollWidth, scrollHeight: m0.scrollHeight };
    let grid = nsPlanTileGrid(dims, viewportWidth, viewportHeight).tiles;
    const plannedTileCountInitial = grid.length;
    const seenTileKeys = new Set();
    const shots = [];   // { x, y, dataUrl, viewportWidthCss }
    let partialReason = null;
    let idx = 0;
    let pageW = dims.scrollWidth, pageH = dims.scrollHeight;
    // repair round 2 (gap #4): the 40M-pixel safety ceiling must agree with what stitchShots will actually
    // produce. stitchShots derives its placement scale from the FIRST captured tile's real bitmap width vs
    // the CSS viewport width (nsStitchScale) rather than trusting devicePixelRatio, because Chrome's actual
    // captureVisibleTab output can differ from cssPixels * dpr under zoom/rounding. The ceiling accounting
    // below now uses that same real, captured scale once it is known -- dpr itself is left untouched
    // everywhere else in this file as pure provenance metadata.
    let capturedScale = null;

    while (idx < grid.length) {
      if (now() - startedAt > CAPTURE_MAX_ELAPSED_MS) { partialReason = 'ceiling_time'; break; }
      if (shots.length >= CAPTURE_MAX_TILES) { partialReason = 'ceiling_folds'; break; }

      const target = grid[idx];
      idx += 1;
      const landed = await execFn(tabId, nsScrollTo, [target.x, target.y, CAPTURE_SETTLE_MS]);

      // whole-capture tile identity (not just adjacent): skip a landed position already captured this run
      if (nsIsDuplicateTile(seenTileKeys, landed.scrollX, landed.scrollY)) continue;

      if (firstTileCaptured) {
        await execFn(tabId, nsHideAndArm, [CAPTURE_WATCHDOG_MS]);
        await new Promise(r => setTimeout(r, CAPTURE_HIDE_SETTLE_MS));
      }

      let dataUrl;
      try {
        const tab = await verifyTabIdentity(tabId, expectedIdentity);   // per-tile re-verification
        dataUrl = await throttledCaptureVisibleTab(tab.windowId);
      } catch (e) {
        if (firstTileCaptured) { try { await execFn(tabId, nsRestore); } catch (e2) {} }
        if (e instanceof TabIdentityError) throw e;
        throw new CaptureMechanismError(String((e && e.message) || e));
      }
      if (firstTileCaptured) { try { await execFn(tabId, nsRestore); } catch (e) {} }
      firstTileCaptured = true;

      shots.push({ x: landed.scrollX, y: landed.scrollY, dataUrl, viewportWidthCss: viewportWidth });
      rec.fold = shots.length; rec.updated_at = now();
      await putCapture(rec);

      if (capturedScale == null) {
        // Derive the real captured scale once, from this (first) tile's actual bitmap -- same technique
        // stitchShots uses -- so the running pixel total below reflects what will actually be stitched,
        // not an dpr-based estimate that can disagree with it under zoom/scaling edge cases. Never let a
        // decode failure here block or fail the capture itself: fall back to dpr for accounting only.
        try {
          const resp = await fetch(dataUrl);
          const blob = await resp.blob();
          const bmp = await createImageBitmap(blob);
          capturedScale = nsStitchScale(bmp.width, viewportWidth);
          bmp.close();
        } catch (e) {
          capturedScale = dpr;
        }
      }

      // re-measure AFTER this tile: the page may have grown while it was being scrolled (lazy/infinite content),
      // in either dimension. Extend the grid when it has, and RESTART the walk from idx=0 over the reshaped
      // grid rather than continuing from the current idx (fix, second review round): nsPlanTileGrid is
      // row-major, so growing the COLUMN count (width growth) shifts every later row's tile indices — continuing
      // from the old idx can walk straight past a newly-inserted tile that now sits EARLIER in the new grid than
      // idx already is, and that tile would never be visited at all. seenTileKeys makes re-visiting an
      // already-captured landed position a cheap skip (nsScrollTo + immediate continue, no recapture), so the
      // restart costs a little time, never correctness — and CAPTURE_MAX_ELAPSED_MS still bounds the total.
      const m = await execFn(tabId, nsMeasure);
      pageW = Math.max(pageW, m.scrollWidth); pageH = Math.max(pageH, m.scrollHeight);
      if (m.scrollWidth > dims.scrollWidth || m.scrollHeight > dims.scrollHeight) {
        dims = { scrollWidth: Math.max(dims.scrollWidth, m.scrollWidth), scrollHeight: Math.max(dims.scrollHeight, m.scrollHeight) };
        grid = nsPlanTileGrid(dims, viewportWidth, viewportHeight).tiles;
        idx = 0;
      }

      // gap #4 fix: use the real captured-bitmap scale for the running pixel total, not dpr, so the safety
      // ceiling agrees with the image stitchShots will actually produce. dpr remains provenance-only.
      const effScale = capturedScale != null ? capturedScale : dpr;
      const totalPixels = viewportWidth * effScale * viewportHeight * effScale * shots.length;
      const ceilingHit = nsCheckCeilings(
        { elapsedMs: now() - startedAt, tilesCaptured: shots.length, totalPixels },
        { maxElapsedMs: CAPTURE_MAX_ELAPSED_MS, maxTiles: CAPTURE_MAX_TILES, maxTotalPixels: CAPTURE_MAX_TOTAL_PIXELS });
      if (ceilingHit) { partialReason = ceilingHit; break; }
    }

    await restoreStylesAndScroll();
    if (!shots.length) throw new CaptureMechanismError('capture produced no image');

    // A single tile, the whole (never-regrown) grid, and nothing forced a stop: this is the honest "visible area
    // only" tier — a page that never needed tiling, not a stitched page.
    if (shots.length === 1 && plannedTileCountInitial === 1 && grid.length === 1 && !partialReason) {
      const resp = await fetch(shots[0].dataUrl);
      const blob = await resp.blob();
      return {
        blob, mode: 'visible_only', partial_reason: null,
        dimensions: { page_width: pageW, page_height: viewportHeight, viewport_width: viewportWidth, viewport_height: viewportHeight, dpr },
        title: rec.title,
      };
    }

    // repair round 3 (gap #A): finalPageW/H used to fall back to pageW/pageH (the full MEASURED page, not what
    // was actually captured) whenever that was larger than the shots' own bounding box. On a partial capture of
    // an enormous or infinite-scroll page, that meant stitchShots could be asked to allocate an OffscreenCanvas
    // hundreds of millions of pixels large -- the tile-capture loop's own 40M ceiling never protected the FINAL
    // stitched image at all, only the per-tile capture count. A partial capture must stitch only the bounding
    // rectangle actually covered by captured tiles; only a COMPLETE capture may trust the full measured page
    // size (and even then shots should already cover it -- Math.max is just defensive rounding slop).
    const complete = idx >= grid.length && !partialReason;
    // Two DIFFERENT things, deliberately kept separate: (1) the STITCH canvas must only ever span what was
    // actually captured (shotsMaxX/Y) -- that's the fix for gap #A; (2) the reported page_width/page_height
    // provenance should stay the TRUE measured page size when known, because "the page was 50000px wide and we
    // only captured the first 3000px" is honest information the partial_page label + partial_reason already
    // frame correctly -- collapsing page_width down to the captured area would make an already-partial capture
    // look like a smaller, complete one.
    const shotsMaxX = Math.max(...shots.map(s => s.x + viewportWidth));
    const shotsMaxY = Math.max(...shots.map(s => s.y + viewportHeight));
    const stitchW = complete ? Math.max(pageW, shotsMaxX) : shotsMaxX;
    const stitchH = complete ? Math.max(pageH, shotsMaxY) : shotsMaxY;
    const finalPageW = Math.max(pageW, shotsMaxX);
    const finalPageH = Math.max(pageH, shotsMaxY);
    const { blob } = await stitchShots(shots, stitchW, stitchH);
    return {
      blob, mode: complete ? 'full_page' : 'partial_page', partial_reason: complete ? null : (partialReason || 'ceiling_folds'),
      dimensions: { page_width: finalPageW, page_height: finalPageH, viewport_width: viewportWidth, viewport_height: viewportHeight, dpr },
      title: rec.title,
    };
  } catch (e) {
    await restoreStylesAndScroll();
    if (e instanceof TabIdentityError) throw e;                 // never falls back — evidence identity uncertain
    // any other failure (including a CaptureMechanismError we threw ourselves, or stitching's own) gets exactly
    // one fallback attempt to a single honest visible-area shot
    return fallbackVisibleCapture(tabId, expectedIdentity, origScrollX, origScrollY);
  }
}

// Builds and sends the multipart upload for a capture whose blob is already durable in NSBlobStore. Shared by
// the first attempt (inside startCapture's async body) and capture-retry, so both paths are byte-for-byte
// identical in what they send — including capture_id, the end-to-end idempotency key.
async function uploadCapture(rec) {
  const blob = await NSBlobStore.get(rec.capture_id);
  if (!blob) throw new Error('the captured image is no longer available on this device — please capture again');
  const out = rec.pending_upload;   // { title, mode, partial_reason, dimensions } — set once, reused on every retry
  const fd = new FormData();
  const filename = 'screenshot-' + rec.capture_id.slice(0, 8) + '.png';
  fd.append('file', blob, filename);
  fd.append('capture_id', rec.capture_id);
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
  return apiForm('/api/ingest/file', fd);
}

async function startCapture(tabId, projectId, note) {
  await captureInit;   // MV3 worker-respawn race: never act on a capture record from before reconciliation ran
  const cur = await getCapture(tabId);
  if (cur && CAPTURE_ACTIVE.has(cur.status)) return { error: 'A screenshot capture is already running in this tab.', capture: cur };
  const curScan = await getScan(tabId);
  if (curScan && ACTIVE.has(curScan.status)) return { error: 'A course scan is already running in this tab — wait for it to finish before capturing.' };
  let tab; try { tab = await chrome.tabs.get(tabId); } catch (e) { return { error: 'That tab is gone.' }; }
  if (!tab.url || !/^https?:/.test(tab.url)) return { error: 'This page cannot be captured (not a web page).' };
  const capture_id = (crypto.randomUUID ? crypto.randomUUID() : String(now()) + Math.random());
  const rec = {
    capture_id, tab_id: tabId, url: tab.url, title: tab.title || '', project_id: projectId || null, note: note || null,
    status: 'capturing', fold: 0, started_at: now(), updated_at: now(), finished_at: null, error: null, result: null,
    pending_upload: null,
  };
  await putCapture(rec);

  (async () => {
    try {
      const out = await runCapture(tabId, rec);

      // repair round 3 (gap #C): a durability hole existed here. The OLD ordering saved the blob to IndexedDB
      // FIRST, then flipped status to 'uploading' and persisted that. If the worker died in between those two
      // steps, the persisted record still said 'capturing' -- and nsReconcileDecision treats every 'capturing'
      // record as an unconditional hard failure, discarding a blob that was actually sitting safely in
      // IndexedDB. Fix: persist metadata FIRST (status -> 'captured', pending_upload set) -- a crash right after
      // this write, before the blob is saved, correctly has no blob and IS a hard failure -- THEN save the
      // blob, THEN transition to 'uploading'. 'captured' is handled identically to 'uploading' everywhere blob
      // existence matters (nsReconcileDecision, reconcileCapturesOnWorkerInit, and the catch block below): the
      // record's own status alone is never enough to say retry is safe, only status + a confirmed blob is.
      rec.status = 'captured'; rec.updated_at = now();
      rec.pending_upload = { title: out.title, mode: out.mode, partial_reason: out.partial_reason, dimensions: out.dimensions };
      await putCapture(rec);

      await NSBlobStore.put(capture_id, out.blob);
      rec.status = 'uploading'; rec.updated_at = now();
      await putCapture(rec);

      const uploadRes = await uploadCapture(rec);
      rec.status = 'done'; rec.finished_at = now(); rec.updated_at = now();
      rec.result = { mode: out.mode, partial_reason: out.partial_reason, job_id: uploadRes && uploadRes.job, job_status: uploadRes && uploadRes.status };
      await putCapture(rec);
      try { await NSBlobStore.delete(capture_id); } catch (e) {}   // upload confirmed: the durable copy's job is done
      try { await NSBlobStore.pruneExpired(); } catch (e) {}
    } catch (e) {
      // an upload failure (network, server error) is RECOVERABLE: capture_id is stable and 'upload_failed' lets
      // capture-retry resubmit the same bytes under the same idempotency key without recapturing -- but ONLY if
      // the blob actually made it into IndexedDB. Status alone can't tell us that: 'uploading' guarantees it (the
      // blob write already succeeded by the time status flips), but 'captured' does NOT -- NSBlobStore.put()
      // itself could be what threw. Check IndexedDB directly rather than trusting the status string, exactly
      // like reconcileCapturesOnWorkerInit does for a worker-restart failure of the same shape.
      let recoverable = false;
      if (rec.status === 'uploading') {
        recoverable = true;
      } else if (rec.status === 'captured') {
        try { recoverable = !!(await NSBlobStore.get(capture_id)); } catch (e2) { recoverable = false; }
      }
      rec.status = recoverable ? 'upload_failed' : 'failed';
      rec.error = String((e && e.message) || e).slice(0, 300); rec.finished_at = now(); rec.updated_at = now();
      await putCapture(rec);
    }
  })();

  return { ok: true, capture: rec };
}

// Resend the SAME capture_id's already-captured bytes — never recaptures pixels, never regenerates capture_id.
// The server's create_or_get_capture_ingest_request is itself idempotent on capture_id, so this is safe to press
// more than once, including while an earlier press is still in flight (withCapture serializes per-tab anyway).
async function retryCapture(tabId) {
  await captureInit;
  const rec = await getCapture(tabId);
  if (!rec) return { error: 'No screenshot capture found for this tab to retry.' };
  if (CAPTURE_ACTIVE.has(rec.status)) return { error: 'This capture is already in progress.', capture: rec };
  if (rec.status !== 'upload_failed') return { error: 'Only a failed send can be retried.', capture: rec };
  if (!rec.pending_upload) return { error: 'Nothing to retry — the captured image was never durably saved.', capture: rec };

  rec.status = 'uploading'; rec.updated_at = now(); rec.error = null;
  await putCapture(rec);

  (async () => {
    try {
      const uploadRes = await uploadCapture(rec);
      rec.status = 'done'; rec.finished_at = now(); rec.updated_at = now();
      rec.result = { mode: rec.pending_upload.mode, partial_reason: rec.pending_upload.partial_reason, job_id: uploadRes && uploadRes.job, job_status: uploadRes && uploadRes.status };
      await putCapture(rec);
      try { await NSBlobStore.delete(rec.capture_id); } catch (e) {}
    } catch (e) {
      rec.status = 'upload_failed'; rec.error = String((e && e.message) || e).slice(0, 300); rec.finished_at = now(); rec.updated_at = now();
      await putCapture(rec);
    }
  })();

  return { ok: true, capture: rec };
}

async function pruneCaptures() {
  const all = await chrome.storage.local.get(null); const dead = [];
  for (const [k, v] of Object.entries(all)) if (k.startsWith('capture:') && v && (now() - (v.updated_at || 0) > 7 * 86400e3)) dead.push(k);
  if (dead.length) await chrome.storage.local.remove(dead);
  try { await NSBlobStore.pruneExpired(); } catch (e) {}
}

// Worker-respawn reconciliation (MV3 may evict/respawn this worker at any point, not just at onInstalled/
// onStartup — a message from the popup can wake a brand-new worker mid-capture). Runs UNCONDITIONALLY on every
// worker initialization — the top-level call below is unawaited, since MV3 re-executes this whole script
// top-to-bottom on every spin-up and this line runs every time, not just on install/browser-start. Every message
// handler that touches capture:<tabId> state (capture-start, capture-retry, capture-get, and startScan's
// capture-active check) `await captureInit` as its FIRST step so no message can act on a stale pre-reconciliation
// record — while chrome.runtime.onMessage's own listener registration (bottom of this file) stays synchronous,
// so no message is ever missed while reconciliation is still running.
async function reconcileCapturesOnWorkerInit() {
  const all = await chrome.storage.local.get(null);
  const nowMs = now();
  for (const [k, v] of Object.entries(all)) {
    if (!k.startsWith('capture:') || !v) continue;
    // repair round 2: nsReconcileDecision needs to know whether the blob actually survived before offering a
    // recoverable 'upload_failed' (and therefore a "Retry send" button) -- checking IndexedDB is why this stays
    // here in background.js rather than inside the pure decision function itself. 'captured' (repair round 3,
    // gap #C) needs exactly the same check: it is the durable-metadata-persisted-before-the-blob-write state,
    // so its own status string alone never tells us whether the blob actually made it into IndexedDB.
    let blobExists = false;
    if (v.status === 'uploading' || v.status === 'captured') {
      try { blobExists = !!(await NSBlobStore.get(v.capture_id)); } catch (e) { blobExists = false; }
    }
    const decision = nsReconcileDecision(v, nowMs, blobExists);
    if (!decision) continue;
    const rec = { ...v, ...decision, updated_at: nowMs, finished_at: v.finished_at || nowMs };
    await putCapture(rec);
  }
}

chrome.runtime.onInstalled.addListener(() => { chrome.alarms.create(ALARM, { periodInMinutes: 5 }); refreshPending(); pruneScans(); pruneCaptures(); });
chrome.runtime.onStartup.addListener(async () => {
  chrome.alarms.create(ALARM, { periodInMinutes: 5 }); refreshPending(); pruneScans(); pruneCaptures();
  // the browser restarted: every runner is gone, whatever the records say
  for (const rec of await anyActive()) await withScan(rec.tab_id, () => finishScan(rec, rec.lessons.length ? 'partial' : 'interrupted', 'browser_restarted'));
});
chrome.alarms.onAlarm.addListener(async a => {
  if (a.name === ALARM) {
    refreshPending();
    // repair round 2 (gap #3): pruneExpired's 2h/5-blob/200MB retention bounds were only ever enforced at
    // onInstalled/onStartup and after a successful upload's own cleanup — a failed screenshot sitting in
    // IndexedDB during a long-running Chrome session could outlive its promised TTL by hours. The heartbeat
    // alarm already fires every 5 minutes for refreshPending; piggybacking a lightweight prune on it is the
    // recurring hook the design always needed.
    pruneCaptures();
  }
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
  if (msg.type === 'capture-retry') { withCapture(msg.tabId, () => retryCapture(msg.tabId)).then(reply, e => reply({ error: String(e) })); return true; }
});

// Unawaited, and deliberately placed AFTER every chrome.*.addListener registration above: MV3 re-executes this
// whole script top-to-bottom on every worker spin-up (not just onInstalled/onStartup), so this line runs on
// EVERY initialization. Listener registration itself is synchronous regardless of where this call sits, so no
// message can ever be missed while reconciliation is still running — but it is placed last anyway so the
// script's own read order matches that guarantee: every listener is already registered before any async
// capture-state work begins.
const captureInit = reconcileCapturesOnWorkerInit();
