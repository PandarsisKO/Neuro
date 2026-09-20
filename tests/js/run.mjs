// Course-scanner test harness: runs the SHIPPED extension/scan-lib.js pipeline against an HTML fixture in jsdom.
//
//   node tests/js/run.mjs <fixture.html> [--url https://course.test/path/] [--cancel-after N] [--fetch-dir DIR]
//
// Prints one JSON object: { summary, events, clicks, fetched }. jsdom proves classification, DOM traversal,
// MutationObserver settling, outcomes, dedupe, partial failure and the safety rules. It does NOT prove real React
// event semantics, Chrome resource timing, MV3 lifecycle or any live site — those stay live-browser gates
// (docs/COURSE-SCANNER-2026-09-15.md). Missing jsdom is a FAILURE of the gate, never a skip: this file throws.
import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';
import { createRequire } from 'node:module';

const here = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
let JSDOM;
try { ({ JSDOM } = require('jsdom')); }
catch (e) { console.error('jsdom is not installed: run `npm ci --prefix tests/js` (pinned in tests/js/package.json). The scanner gate cannot pass without it.'); process.exit(3); }

const args = process.argv.slice(2);
const fixture = args[0];
const opt = (name, dflt) => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : dflt; };
const url = opt('--url', 'https://course.test/courses/demo/');
const cancelAfter = +opt('--cancel-after', '0');
const fetchDir = opt('--fetch-dir', path.dirname(fixture));

const html = readFileSync(fixture, 'utf8');
const dom = new JSDOM(html, { url, runScripts: 'dangerously', pretendToBeVisual: true });
const { window } = dom;
window.__clicks = [];                                             // fixtures record what was activated
if (!window.performance.getEntriesByType) window.performance.getEntriesByType = () => [];
// the shipped library, byte for byte
const lib = readFileSync(path.join(here, '..', '..', 'extension', 'scan-lib.js'), 'utf8');
window.eval(lib);

const events = []; const fetched = []; let lessonsSeen = 0;
const bridge = {
  emit: async (event, payload) => { events.push({ event, ...(event === 'lesson' ? { index: payload.index, outcome: payload.record.outcome, title: payload.record.title } : {}) }); if (event === 'lesson') lessonsSeen++; },
  cancelled: async () => cancelAfter > 0 && lessonsSeen >= cancelAfter,
  fetch: async u => {
    fetched.push(u);
    const p = path.join(fetchDir, new URL(u).pathname.replace(/^\/+/, '').replace(/\/$/, '') || 'index.html');
    const file = existsSync(p) ? p : (existsSync(p + '.html') ? p + '.html' : path.join(p, 'index.html'));
    if (!existsSync(file)) return { status: 404, text: async () => '' };
    if (/blocked/.test(file)) return { status: 403, text: async () => '' };
    return { status: 200, text: async () => readFileSync(file, 'utf8') };
  },
};
const settle = { min_ms: 30, quiet_ms: 60, cap_ms: 700, sample_ms: 15, grace_ms: 400, content_grace_ms: 1500 };
const timeout = setTimeout(() => { console.error('harness timeout'); process.exit(2); }, 30000);
try {
  const summary = await window.NSScan.run(window, bridge, { settle });
  clearTimeout(timeout);
  console.log(JSON.stringify({ summary, events, clicks: window.__clicks, fetched }, null, 0));
} catch (e) { clearTimeout(timeout); console.error('run failed:', e && e.stack || e); process.exit(1); }
