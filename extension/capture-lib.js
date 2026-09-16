// Neuro Search — send-screenshot capture-engine primitives (extension 1.8.0, docs/SEND-SCREENSHOT-2026-09-16.md).
//
// Plain functions, no imports: loaded two ways —
//   1. background.js: `importScripts('capture-lib.js')` (classic, non-module MV3 service worker), then each
//      function is passed BY REFERENCE to chrome.scripting.executeScript({ func: ... }), which serializes it by
//      source text and runs it in the target page's isolated world. That is why none of these close over anything
//      outside themselves — a closure would serialize as broken source referencing variables that do not exist
//      on the other side.
//   2. tests/js/run-capture.mjs: `window.eval(lib)` against a jsdom window, exactly as tests/js/run.mjs does for
//      scan-lib.js — proves DOM traversal (sticky/fixed detection), the watchdog timer, and hide/restore
//      idempotency without a real Chrome extension host.
//
// Exposed as `self.NSCaptureLib` (works as `self` in both a service worker and a jsdom window — jsdom's `window`
// IS its own `self`).
(function (root) {
  function nsMeasure() {
    const de = document.documentElement;
    return {
      scrollWidth: de.scrollWidth, scrollHeight: de.scrollHeight,
      viewportWidth: window.innerWidth, viewportHeight: window.innerHeight,
      dpr: window.devicePixelRatio || 1, scrollX: window.scrollX, scrollY: window.scrollY,
      title: document.title,
    };
  }

  async function nsScrollTo(x, y, settleMs) {
    window.scrollTo({ left: x, top: y, behavior: 'instant' });
    await new Promise(r => setTimeout(r, settleMs));
    return { scrollX: window.scrollX, scrollY: window.scrollY };
  }

  // Hides sticky/fixed elements (they'd otherwise "stamp" themselves into every fold after the first) and arms an
  // in-page watchdog timer that self-restores if nothing calls nsRestore in time. This IS the content-script
  // watchdog the plan requires: it does not depend on the background service worker still being alive, a message
  // channel still being open, or a try/finally on the OTHER side ever running — it is a plain page-context
  // setTimeout that heals the page on its own if the whole background operation is interrupted (worker killed,
  // tab navigated away and the isolated world recreated, losing that side's closure, etc). visibility:hidden (not
  // display:none) is used so layout — and therefore scrollHeight — does not shift from hiding these elements.
  function nsHideAndArm(watchdogMs) {
    if (window.__nsCaptureWatchdog) { clearTimeout(window.__nsCaptureWatchdog); window.__nsCaptureWatchdog = null; }
    let hidden = window.__nsCaptureHidden;
    if (hidden && hidden.length) { for (const h of hidden) { try { h.el.setAttribute('style', h.prevStyle); } catch (e) {} } }
    hidden = window.__nsCaptureHidden = [];
    let all;
    try { all = document.querySelectorAll('body *'); } catch (e) { all = []; }
    for (const el of all) {
      let cs;
      try { cs = getComputedStyle(el); } catch (e) { continue; }
      if (cs.position !== 'sticky' && cs.position !== 'fixed') continue;
      let rect;
      try { rect = el.getBoundingClientRect(); } catch (e) { continue; }
      if (rect.width === 0 && rect.height === 0) continue;
      hidden.push({ el, prevStyle: el.getAttribute('style') || '' });
      try { el.style.setProperty('visibility', 'hidden', 'important'); } catch (e) {}
    }
    window.__nsCaptureWatchdog = setTimeout(() => {
      const list = window.__nsCaptureHidden || [];
      for (const h of list) { try { h.el.setAttribute('style', h.prevStyle); } catch (e) {} }
      window.__nsCaptureHidden = [];
      window.__nsCaptureWatchdog = null;
    }, watchdogMs);
    return { hiddenCount: hidden.length };
  }

  function nsRestore() {
    if (window.__nsCaptureWatchdog) { clearTimeout(window.__nsCaptureWatchdog); window.__nsCaptureWatchdog = null; }
    const list = window.__nsCaptureHidden || [];
    for (const h of list) { try { h.el.setAttribute('style', h.prevStyle); } catch (e) {} }
    window.__nsCaptureHidden = [];
  }

  root.NSCaptureLib = { nsMeasure, nsScrollTo, nsHideAndArm, nsRestore };
})(typeof self !== 'undefined' ? self : this);
