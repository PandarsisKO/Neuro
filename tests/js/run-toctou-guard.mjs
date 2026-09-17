// Proves the TOCTOU (check-then-use) fix in extension/background.js's throttledCaptureVisibleTab: a fast tab
// switch happening AFTER verifyTabIdentity's own `tab.active` check (during the rate-limit wait or the
// preCapture re-hide round trip) but BEFORE the actual chrome.tabs.captureVisibleTab call must fail closed
// (TabIdentityError, captureVisibleTab never called) instead of silently capturing the wrong tab's pixels.
//
// This extracts the SHIPPED source of throttledCaptureVisibleTab (plus its direct dependencies: TabIdentityError,
// withRateLimit/_rateLimitLock, now) straight out of extension/background.js by string boundary -- not a
// reimplementation -- and runs it in a vm context against a mock chrome.tabs/chrome.storage.session. It does NOT
// prove real captureVisibleTab pixel output or real browser tab-switch timing -- that stays a live-browser gate,
// same boundary test_s54_send_screenshot.py documents for capture-lib.js.
//
//   node tests/js/run-toctou-guard.mjs stays-active
//   node tests/js/run-toctou-guard.mjs switches-during-precapture
//   node tests/js/run-toctou-guard.mjs switches-window-during-precapture
//   node tests/js/run-toctou-guard.mjs tab-closed-during-precapture

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import vm from 'node:vm';

const here = path.dirname(fileURLToPath(import.meta.url));
const bgPath = path.join(here, '..', '..', 'extension', 'background.js');
const bg = readFileSync(bgPath, 'utf8');

function slice(startMarker, endMarker, label) {
  const start = bg.indexOf(startMarker);
  if (start === -1) { console.error(`extraction failed: could not find start marker for ${label} (${JSON.stringify(startMarker)}) -- has background.js changed shape?`); process.exit(3); }
  const end = bg.indexOf(endMarker, start);
  if (end === -1) { console.error(`extraction failed: could not find end marker for ${label} (${JSON.stringify(endMarker)}) -- has background.js changed shape?`); process.exit(3); }
  return bg.slice(start, end).trim();
}

const tabIdentityErrorSrc = slice('class TabIdentityError extends Error', 'class CaptureMechanismError', 'TabIdentityError');
const rateLimitSrc = slice('let _rateLimitLock', 'async function throttledCaptureVisibleTab', 'withRateLimit');
const fnSrc = slice('async function throttledCaptureVisibleTab', '// Stitches PNG data URLs', 'throttledCaptureVisibleTab');

if (!fnSrc.includes('await chrome.tabs.get(tabId)') || !fnSrc.includes('.active') ) {
  console.error('SOURCE CHANGED: throttledCaptureVisibleTab no longer re-checks the active tab immediately before captureVisibleTab -- the TOCTOU fix appears to have been removed or moved. This harness needs updating alongside it, not silently passing.');
  process.exit(3);
}

const command = process.argv[2];
const TAB_ID = 100, WINDOW_ID = 10;
const state = { activeTabId: TAB_ID, activeWindowId: WINDOW_ID, exists: true };
const captureLog = [];

const chromeMock = {
  tabs: {
    get: async (tabId) => {
      if (!state.exists) { const e = new Error('No tab with id: ' + tabId); throw e; }
      return { id: tabId, active: tabId === state.activeTabId, windowId: state.activeWindowId };
    },
    captureVisibleTab: async (windowId, opts) => {
      captureLog.push({ windowId, opts });
      return 'data:image/png;base64,AAAA';
    },
  },
  storage: { session: {
    get: async () => ({}),   // nsRateLimitWaitMs stubbed below always returns 0 -- no real wait needed to exercise this gap
    set: async () => {},
  } },
};

function preCaptureFor(command) {
  switch (command) {
    case 'stays-active':
      return async () => {};   // nothing changes between the earlier verifyTabIdentity and this capture
    case 'switches-during-precapture':
      // the real-world case the correction described: user Cmd+Tabs to a DIFFERENT tab in the SAME window
      // during the hide-and-settle wait that runs as preCapture
      return async () => { state.activeTabId = 999; };
    case 'switches-window-during-precapture':
      // a same-tab-id-but-different-window edge case (e.g. the tab got dragged into another window)
      return async () => { state.activeWindowId = 20; };
    case 'tab-closed-during-precapture':
      return async () => { state.exists = false; };
    default:
      console.error(`unknown command ${JSON.stringify(command)}`);
      process.exit(2);
  }
}

const sandbox = {
  chrome: chromeMock,
  console,
  setTimeout,
  Promise,
  now: () => Date.now(),
  CAPTURE_MIN_CALL_INTERVAL_MS: 0,
  nsRateLimitWaitMs: () => 0,   // real rate-limit math is covered elsewhere (capture-lib.js's own gate); stubbed to 0 here so this harness's only variable is the active-tab recheck
};
vm.createContext(sandbox);
vm.runInContext([tabIdentityErrorSrc, rateLimitSrc, fnSrc, 'globalThis.__throttled = throttledCaptureVisibleTab;'].join('\n\n'), sandbox);

const preCapture = preCaptureFor(command);

(async () => {
  let result;
  try {
    const dataUrl = await sandbox.__throttled(TAB_ID, WINDOW_ID, preCapture);
    result = { threw: false, dataUrl, captureCount: captureLog.length };
  } catch (e) {
    result = { threw: true, name: e.name, nsErrorKind: e.nsErrorKind, message: e.message, captureCount: captureLog.length };
  }
  console.log(JSON.stringify(result));
})();
