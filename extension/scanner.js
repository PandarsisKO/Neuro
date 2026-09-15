// Neuro Search — course scanner runner (content script, injected on demand after scan-lib.js).
//
// 1.7.0 (mission CS, docs/COURSE-SCANNER-2026-09-15.md): this file is only the bridge between the page and the
// extension. The pipeline itself is NSScan.run in scan-lib.js — linked-page strategy, interactive-SPA strategy,
// rendered-content inspection — and every lesson it touches ends in an explicit outcome. What this file owns:
//
//   * identity: the scan_id the background handed us (set in this isolated world just before injection); every
//     message carries it, so a superseded runner's late messages are ignored by the background, never merged;
//   * idempotency: one traversal per tab — a second injection while one is running refuses, it does not race;
//   * cancellation: the background may push `scan-cancel`; the runner also asks at every lesson boundary;
//   * liveness: `scan-ping` answers while the runner is alive; a navigation that kills this world stops answering,
//     which is how the background tells "the page went away" from "the URL changed inside the app".
//
// 1.6.0's lesson is kept in scan-lib.js: navigation is never a lesson, the page you are looking at always counts,
// and an empty result names what it saw instead of blaming the login.
(() => {
  'use strict';
  const req = globalThis.__nsScanReq;                       // { scan_id, tab_id } from the background
  if (!req || !req.scan_id) { chrome.runtime.sendMessage({ type: 'scan-event', event: 'failed', detail: 'no scan id' }).catch(() => {}); return; }
  if (globalThis.__nsScanActive) {
    chrome.runtime.sendMessage({ type: 'scan-event', scan_id: req.scan_id, event: 'refused', detail: 'a scan is already running in this tab', active: globalThis.__nsScanActive }).catch(() => {});
    return;
  }
  const scan_id = req.scan_id;
  globalThis.__nsScanActive = scan_id;
  let cancel = false;
  const onMsg = (m, sender, reply) => {
    if (!m || m.scan_id !== scan_id) return;
    if (m.type === 'scan-cancel') { cancel = true; reply({ ok: true }); }
    if (m.type === 'scan-ping') reply({ alive: true, scan_id });
  };
  chrome.runtime.onMessage.addListener(onMsg);
  const send = payload => chrome.runtime.sendMessage({ type: 'scan-event', scan_id, ...payload });
  const bridge = {
    emit: async (event, payload) => { try { const r = await send({ event, ...payload }); if (r && r.cancel) cancel = true; } catch (e) { cancel = true; /* the extension went away: stop at this boundary */ } },
    cancelled: async () => { if (cancel) return true; try { const r = await send({ event: 'poll' }); if (r && r.cancel) cancel = true; } catch (e) { cancel = true; } return cancel; },
    fetch: url => fetch(url, { credentials: 'include' }),
  };
  NSScan.run(window, bridge, {}).catch(e => send({ event: 'failed', detail: String(e).slice(0, 300) }).catch(() => {}))
    .finally(() => { chrome.runtime.onMessage.removeListener(onMsg); if (globalThis.__nsScanActive === scan_id) globalThis.__nsScanActive = null; });
})();
