// Send-screenshot capture-lib test harness: runs the SHIPPED extension/capture-lib.js primitives against an HTML
// fixture in jsdom, exercising the sticky/fixed hide+restore, the in-page watchdog and the measurement function —
// the same technique tests/js/run.mjs uses for scan-lib.js. It does NOT prove chrome.tabs.captureVisibleTab pixel
// output, DPR crop math against a real screen, or MV3 service-worker importScripts — those stay live-browser
// gates (docs/SEND-SCREENSHOT-2026-09-16.md).
//
//   node tests/js/run-capture.mjs <fixture.html> <command> [args-json]
//
// commands:
//   measure                              -> nsMeasure()
//   hide <watchdogMs>                    -> nsHideAndArm(watchdogMs); returns { hidden, stillHiddenCount }
//   hide-then-restore <watchdogMs>       -> nsHideAndArm then nsRestore(); returns { hidden, afterRestoreCount }
//   watchdog-selfheal <watchdogMs> <waitMs>  -> nsHideAndArm, wait waitMs WITHOUT calling nsRestore, report count
//   plan-tile-grid <measure> <vw> <vh>       -> nsPlanTileGrid(measure, vw, vh)
//   dedupe-tiles <points>                    -> points: [[x,y],...]; returns which are duplicates, in order
//   check-ceilings <progress> <ceilings>     -> nsCheckCeilings(progress, ceilings)
//   stitch-scale <bitmapWidthPx> <cssViewportWidth>  -> nsStitchScale(...)
//   rate-limit-wait <lastCallAtMs> <nowMs> <minIntervalMs>  -> nsRateLimitWaitMs(...)
//   fallback-eligible <errorKind>            -> nsIsFallbackEligible(errorKind)
//   reconcile-decision <rec> <nowMs> <blobExists>  -> nsReconcileDecision(rec, nowMs, blobExists)
//   page-identity <urlStr>                    -> nsPageIdentity(urlStr) (repair round 3, gap #B;
//                                                 round 4 also folds in route-like hashes)
//   simulate-growth-traversal <dims> <vw> <vh> <growthSchedule>
//       -> mirrors background.js's runCapture tile-walk + regrow-on-growth algorithm (including the idx=0 reset
//          on any grid reshape, second review round's fix) using ONLY the real nsPlanTileGrid/nsIsDuplicateTile
//          helpers, driven by a scripted growth schedule. Proves the traversal visits every tile of the FINAL
//          grid shape even when growth inserts new tiles earlier in row-major order (e.g. width growth adding a
//          column) than the walk has already reached.
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { createRequire } from 'node:module';

const here = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
let JSDOM;
try { ({ JSDOM } = require('jsdom')); }
catch (e) { console.error('jsdom is not installed: run `npm ci --prefix tests/js`. The send-screenshot gate cannot pass without it.'); process.exit(3); }

const [fixture, command, argsJson] = process.argv.slice(2);
const args = argsJson ? JSON.parse(argsJson) : [];

const html = readFileSync(fixture, 'utf8');
const dom = new JSDOM(html, { url: 'https://capture.test/page', runScripts: 'dangerously', pretendToBeVisual: true });
const { window } = dom;

const lib = readFileSync(path.join(here, '..', '..', 'extension', 'capture-lib.js'), 'utf8');
window.eval(lib);
const { nsMeasure, nsHideAndArm, nsRestore, nsHideScrollbars, nsRestoreScrollbars, nsPlanTileGrid, nsIsDuplicateTile, nsCheckCeilings,
        nsStitchScale, nsRateLimitWaitMs, nsIsFallbackEligible, nsReconcileDecision, nsPageIdentity, nsIsRouteLikeHash } = window.NSCaptureLib;

function stillHidden() {
  let n = 0;
  for (const el of window.document.querySelectorAll('body *')) {
    const cs = window.getComputedStyle(el);
    if (cs.visibility === 'hidden' && (cs.position === 'sticky' || cs.position === 'fixed')) n++;
  }
  return n;
}

function scrollbarStyleEl() { return window.document.getElementById('ns-capture-hide-scrollbars'); }

const timeout = setTimeout(() => { console.error('harness timeout'); process.exit(2); }, 15000);
(async () => {
  try {
    let out;
    if (command === 'measure') {
      out = nsMeasure();
    } else if (command === 'hide') {
      const r = nsHideAndArm(args[0] ?? 20000);
      out = { hidden: r.hiddenCount, stillHiddenCount: stillHidden() };
    } else if (command === 'hide-then-restore') {
      const r = nsHideAndArm(args[0] ?? 20000);
      nsRestore();
      out = { hidden: r.hiddenCount, afterRestoreCount: stillHidden() };
    } else if (command === 'watchdog-selfheal') {
      const watchdogMs = args[0] ?? 200, waitMs = args[1] ?? 500;
      const r = nsHideAndArm(watchdogMs);
      await new Promise(res => setTimeout(res, waitMs));
      out = { hidden: r.hiddenCount, afterWaitCount: stillHidden() };
    } else if (command === 'hide-twice-then-restore') {
      // Case 3 regression: throttledCaptureVisibleTab's preCapture hook calls nsHideAndArm a SECOND time,
      // after the rate-limit wait, right before the snapshot -- re-verifying/re-hiding anything a reactive
      // third-party widget (a Google reCAPTCHA badge, confirmed live on Reddit's home feed) re-showed itself
      // in the gap since the first hide. Must stay idempotent and still fully restorable.
      const r1 = nsHideAndArm(args[0] ?? 20000);
      const r2 = nsHideAndArm(args[0] ?? 20000);
      const stillHiddenAfterBoth = stillHidden();
      nsRestore();
      out = { firstHidden: r1.hiddenCount, secondHidden: r2.hiddenCount, stillHiddenAfterBoth, afterRestoreCount: stillHidden() };
    } else if (command === 'hide-descendant-visibility-override') {
      // Case 3 regression (second finding, 2026-09-17): a fixed/sticky element that CONTAINS a descendant with
      // its own explicit `visibility: visible` (a real pattern found live on Reddit -- a small avatar image
      // inside the hidden header kept rendering on its own, stamping into every fold after the first) must have
      // that descendant forced hidden too, and restored correctly afterward.
      const el = window.document.getElementById('descendant-override-target');
      const before = el ? window.getComputedStyle(el).visibility : 'missing';
      const r = nsHideAndArm(args[0] ?? 20000);
      const afterHide = el ? window.getComputedStyle(el).visibility : 'missing';
      nsRestore();
      const afterRestore = el ? window.getComputedStyle(el).visibility : 'missing';
      out = { before, afterHide, afterRestore, hiddenCount: r.hiddenCount };
    } else if (command === 'hide-scrollbars') {
      nsHideScrollbars(args[0] ?? 20000);
      out = { styleElPresent: !!scrollbarStyleEl() };
    } else if (command === 'hide-scrollbars-then-restore') {
      nsHideScrollbars(args[0] ?? 20000);
      const before = !!scrollbarStyleEl();
      nsRestoreScrollbars();
      out = { before, after: !!scrollbarStyleEl() };
    } else if (command === 'scrollbars-watchdog-selfheal') {
      const watchdogMs = args[0] ?? 200, waitMs = args[1] ?? 500;
      nsHideScrollbars(watchdogMs);
      const before = !!scrollbarStyleEl();
      await new Promise(res => setTimeout(res, waitMs));
      out = { before, afterWait: !!scrollbarStyleEl() };
    } else if (command === 'plan-tile-grid') {
      out = nsPlanTileGrid(args[0], args[1], args[2]);
    } else if (command === 'dedupe-tiles') {
      const seen = new Set();
      out = args[0].map(([x, y]) => nsIsDuplicateTile(seen, x, y));
    } else if (command === 'check-ceilings') {
      out = { reason: nsCheckCeilings(args[0], args[1]) };
    } else if (command === 'stitch-scale') {
      out = { scale: nsStitchScale(args[0], args[1]) };
    } else if (command === 'rate-limit-wait') {
      out = { waitMs: nsRateLimitWaitMs(args[0], args[1], args[2]) };
    } else if (command === 'fallback-eligible') {
      out = { eligible: nsIsFallbackEligible(args[0]) };
    } else if (command === 'reconcile-decision') {
      out = nsReconcileDecision(args[0], args[1], args[2]);
    } else if (command === 'page-identity') {
      out = { identity: nsPageIdentity(args[0]) };
    } else if (command === 'is-route-like-hash') {
      out = { routeLike: nsIsRouteLikeHash(args[0]) };
    } else if (command === 'simulate-growth-traversal') {
      const [initialDims, vw, vh, growthSchedule] = args;
      let dims = initialDims;
      let grid = nsPlanTileGrid(dims, vw, vh).tiles;
      let idx = 0;
      const seen = new Set();
      const captured = [];
      let growthPtr = 0;
      let guard = 0;
      while (idx < grid.length && guard < 2000) {
        guard++;
        const target = grid[idx]; idx += 1;
        if (nsIsDuplicateTile(seen, target.x, target.y)) continue;
        captured.push({ x: target.x, y: target.y });
        if (growthPtr < growthSchedule.length && captured.length === growthSchedule[growthPtr].afterTiles) {
          const g = growthSchedule[growthPtr].dims; growthPtr++;
          if (g.scrollWidth > dims.scrollWidth || g.scrollHeight > dims.scrollHeight) {
            dims = { scrollWidth: Math.max(dims.scrollWidth, g.scrollWidth), scrollHeight: Math.max(dims.scrollHeight, g.scrollHeight) };
            grid = nsPlanTileGrid(dims, vw, vh).tiles;
            idx = 0;
          }
        }
      }
      const coveredAll = grid.every(t => captured.some(c => c.x === t.x && c.y === t.y));
      out = { captured, finalGridSize: grid.length, capturedCount: captured.length, coveredAll, guardTripped: guard >= 2000 };
    } else {
      throw new Error('unknown command: ' + command);
    }
    clearTimeout(timeout);
    console.log(JSON.stringify(out));
  } catch (e) { clearTimeout(timeout); console.error('run failed:', e && e.stack || e); process.exit(1); }
})();
