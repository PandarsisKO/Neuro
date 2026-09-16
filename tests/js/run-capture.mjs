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
const { nsMeasure, nsHideAndArm, nsRestore } = window.NSCaptureLib;

function stillHidden() {
  let n = 0;
  for (const el of window.document.querySelectorAll('body *')) {
    const cs = window.getComputedStyle(el);
    if (cs.visibility === 'hidden' && (cs.position === 'sticky' || cs.position === 'fixed')) n++;
  }
  return n;
}

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
    } else {
      throw new Error('unknown command: ' + command);
    }
    clearTimeout(timeout);
    console.log(JSON.stringify(out));
  } catch (e) { clearTimeout(timeout); console.error('run failed:', e && e.stack || e); process.exit(1); }
})();
