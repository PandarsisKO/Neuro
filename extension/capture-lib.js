// Neuro Search — send-screenshot capture-engine primitives (extension 1.9.3, docs/SEND-SCREENSHOT-2026-09-16.md).
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
    const hiddenEls = [];
    for (const el of all) {
      let cs;
      try { cs = getComputedStyle(el); } catch (e) { continue; }
      if (cs.position !== 'sticky' && cs.position !== 'fixed') continue;
      let rect;
      try { rect = el.getBoundingClientRect(); } catch (e) { continue; }
      if (rect.width === 0 && rect.height === 0) continue;
      hidden.push({ el, prevStyle: el.getAttribute('style') || '' });
      try { el.style.setProperty('visibility', 'hidden', 'important'); } catch (e) {}
      hiddenEls.push(el);
    }
    // Case 3 repair (second finding, 2026-09-17): visibility is INHERITED, not enforced top-down -- a descendant
    // that sets its own explicit visibility (a common defensive pattern for icon/avatar components, so ambient
    // CSS can't accidentally hide them) can override an already-hidden ancestor and keep rendering on its own,
    // stamping just that one piece into every fold after the first even though the ancestor itself is correctly
    // hidden. A live Reddit capture found exactly this: the sticky header was hidden correctly, but a small
    // avatar image inside it had its own `visibility: visible` and kept showing in the same corner of every
    // tile. Walk each hidden element's subtree once more and force any descendant whose OWN computed visibility
    // still reads 'visible' back to hidden too, tracked the same way so nsRestore/the watchdog put it back.
    for (const el of hiddenEls) {
      let descendants;
      try { descendants = el.querySelectorAll('*'); } catch (e) { continue; }
      for (const d of descendants) {
        let dcs;
        try { dcs = getComputedStyle(d); } catch (e) { continue; }
        if (dcs.visibility !== 'visible') continue;
        hidden.push({ el: d, prevStyle: d.getAttribute('style') || '' });
        try { d.style.setProperty('visibility', 'hidden', 'important'); } catch (e) {}
      }
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

  // Case 2 repair (2026-09-16 live-Chrome acceptance): a page that overflows BOTH axes shows Chrome's own
  // page-level scrollbar (rendered as a viewport overlay, not page content) INSIDE every captureVisibleTab
  // screenshot. When tile rows land back-to-back with no vertical overlap between them (the common case --
  // overlap only happens where nsPlanTileGrid clamps the last row), nothing is ever drawn over that baked-in
  // scrollbar band, and a real strip of content (a whole table row, in the case that found this) is
  // permanently replaced by a scrollbar graphic in the stitched image. Unlike sticky/fixed elements, this
  // needs to be hidden for the FIRST tile too -- there is no "natural" tile where a baked-in scrollbar is
  // correct -- so it is armed once before the capture loop starts, not per-tile like nsHideAndArm/nsRestore.
  // CSS-only (scrollbar-width / ::-webkit-scrollbar), so scrolling itself is unaffected -- only the visible
  // scrollbar chrome is suppressed. Same self-healing watchdog pattern as nsHideAndArm for the same reason:
  // this must never depend on the background service worker still being alive to undo it.
  function nsHideScrollbars(watchdogMs) {
    if (window.__nsScrollbarWatchdog) { clearTimeout(window.__nsScrollbarWatchdog); window.__nsScrollbarWatchdog = null; }
    if (!window.__nsScrollbarStyleEl) {
      const style = document.createElement('style');
      style.id = 'ns-capture-hide-scrollbars';
      style.textContent = 'html, body { scrollbar-width: none !important; } '
        + 'html::-webkit-scrollbar, body::-webkit-scrollbar { display: none !important; width: 0 !important; height: 0 !important; }';
      (document.head || document.documentElement).appendChild(style);
      window.__nsScrollbarStyleEl = style;
    }
    window.__nsScrollbarWatchdog = setTimeout(() => {
      if (window.__nsScrollbarStyleEl) { try { window.__nsScrollbarStyleEl.remove(); } catch (e) {} window.__nsScrollbarStyleEl = null; }
      window.__nsScrollbarWatchdog = null;
    }, watchdogMs);
  }

  function nsRestoreScrollbars() {
    if (window.__nsScrollbarWatchdog) { clearTimeout(window.__nsScrollbarWatchdog); window.__nsScrollbarWatchdog = null; }
    if (window.__nsScrollbarStyleEl) { try { window.__nsScrollbarStyleEl.remove(); } catch (e) {} window.__nsScrollbarStyleEl = null; }
  }

  // ================================================================================== pure helpers (no DOM)
  // Repair round (docs/SEND-SCREENSHOT-2026-09-16.md, repair plan). Plain math/decision functions with no
  // closures, no chrome.* calls and no DOM access -- callable two ways, same as the functions above:
  //   1. background.js, directly (NOT via chrome.scripting.executeScript -- these never touch a page): after
  //      importScripts('capture-lib.js') they exist on `self` (the service worker's own global object) exactly
  //      like the DOM helpers do, and background.js calls them as plain function calls.
  //   2. tests/js/run-capture.mjs, via window.eval, exactly like the DOM helpers -- proving the math without any
  //      real browser, real tab or real captureVisibleTab call.

  // 2D tile grid covering the whole page. A page that fits in one viewport on both axes still gets exactly one
  // tile at (0,0) -- the "1x1 grid" case IS the visible-area-only capture, not a special case of it.
  function nsPlanTileGrid(measure, viewportWidth, viewportHeight) {
    const cols = Math.max(1, Math.ceil(measure.scrollWidth / viewportWidth));
    const rows = Math.max(1, Math.ceil(measure.scrollHeight / viewportHeight));
    const maxX = Math.max(0, measure.scrollWidth - viewportWidth);
    const maxY = Math.max(0, measure.scrollHeight - viewportHeight);
    const tiles = [];
    for (let row = 0; row < rows; row++) {
      const y = rows === 1 ? 0 : Math.min(row * viewportHeight, maxY);
      for (let col = 0; col < cols; col++) {
        const x = cols === 1 ? 0 : Math.min(col * viewportWidth, maxX);
        tiles.push({ row, col, x, y });
      }
    }
    return { tiles, rows, cols };
  }

  // Whole-capture tile identity: a Set of every LANDED (scrollX, scrollY) pair seen so far across the entire
  // capture, not just the immediately-previous tile -- catches an A->B->A repeat (e.g. a page that snapped back
  // to an earlier scroll position because of its own scroll-anchoring) even though it is not adjacent to the
  // duplicate. Mutates `seenKeys` (a Set the caller owns) and returns whether (x,y) was already present.
  // repair round 2 (hardening item): key on the ACTUAL landed coordinates, not a rounded approximation --
  // the design settled on deduping by real landed position, and rounding here could theoretically collapse
  // two genuinely distinct fractional scroll positions (subpixel scroll offsets are real under some
  // zoom/DPR combinations) into the same key, silently treating them as the same tile.
  function nsTileKey(x, y) { return x + ',' + y; }
  function nsIsDuplicateTile(seenKeys, x, y) {
    const k = nsTileKey(x, y);
    if (seenKeys.has(k)) return true;
    seenKeys.add(k);
    return false;
  }

  // Three runtime ceilings, checked against ACTUAL captured (post-dedup) progress, never the planned grid size --
  // a lazy/infinite-scroll page can make the planned grid balloon mid-capture. Returns the partial reason or null.
  function nsCheckCeilings(progress, ceilings) {
    if (progress.elapsedMs > ceilings.maxElapsedMs) return 'ceiling_time';
    if (progress.tilesCaptured > ceilings.maxTiles) return 'ceiling_folds';
    if (progress.totalPixels > ceilings.maxTotalPixels) return 'ceiling_pixels';
    // repair round (case 7, 2026-09-18): a narrow-but-very-tall page can stay under maxTotalPixels while one
    // axis alone exceeds what Chrome's canvas/GPU texture limits can render cleanly -- checked in addition to,
    // not instead of, the total-pixel ceiling above. ceilings.maxAxisPixels is optional so existing callers
    // that don't pass it (older tests, other call sites) are unaffected.
    if (ceilings.maxAxisPixels != null && (progress.width > ceilings.maxAxisPixels || progress.height > ceilings.maxAxisPixels)) return 'ceiling_axis';
    return null;
  }

  // Stitch placement scale from the ACTUAL createImageBitmap result, not devicePixelRatio alone (zoom/rounding/
  // mid-capture display changes can make dpr wrong). dpr is still recorded separately as pure provenance.
  function nsStitchScale(bitmapWidthPx, cssViewportWidth) {
    if (!cssViewportWidth) return 1;
    return bitmapWidthPx / cssViewportWidth;
  }

  // captureVisibleTab is rate-limited (~2/sec). Returns how many ms to wait before the next call is safe, given
  // the timestamp of the last call (null = never called yet) and the minimum interval required between calls.
  function nsRateLimitWaitMs(lastCallAtMs, nowMs, minIntervalMs) {
    if (lastCallAtMs == null) return 0;
    const elapsed = nowMs - lastCallAtMs;
    return elapsed >= minIntervalMs ? 0 : minIntervalMs - elapsed;
  }

  // The visible-area fallback is safe ONLY for a genuine capture-MECHANISM failure (stitching/OffscreenCanvas/
  // transient captureVisibleTab error) -- never when the target tab's IDENTITY became uncertain (not active,
  // origin/navigation change, permission loss), since the evidence's attribution would then be unreliable.
  // Callers tag their caught errors with a `.nsErrorKind` of one of these two strings; anything else is treated
  // as identity-uncertain (fail closed -- no fallback) rather than assumed safe.
  function nsIsFallbackEligible(errorKind) {
    return errorKind === 'CaptureMechanismError';
  }

  // Worker-respawn reconciliation: given a capture:<tabId> record found at worker-init time, "now", and whether
  // that record's blob is STILL present in NSCaptureBlobStore (the caller checks IndexedDB — this function stays
  // pure/sync, no IndexedDB access of its own), decide what the record must become. A record left 'capturing'
  // means the runCapture loop that owned it is simply gone (the worker that ran it was evicted/restarted) --
  // nothing will ever call back into it, so it is failed outright (it never reached the durable-blob step, so
  // there is nothing to retry with regardless). A record left 'captured' or 'uploading' is different ONLY when
  // its blob actually survived: THIS worker's request may have already reached the server (only the response
  // was lost when the worker died), so the server-side capture_id idempotency makes it safe to treat as a
  // recoverable 'upload_failed' -- capture-retry resubmits the SAME capture_id and either finds the server's
  // already-materialized job or lands it for the first time, never double-charging a duplicate job. But if the
  // blob is gone (repair round 2: the earlier version of this function always assumed it survived, which let
  // the popup offer a "Retry send" that could never actually work), there is nothing capture-retry could
  // resubmit, so this is a hard, honest 'failed' instead -- never a retry button with nothing behind it.
  // 'captured' itself (repair round 3, gap #C) is a durable intermediate state startCapture persists BEFORE
  // saving the blob, precisely so a crash between persisting that status and the blob write never gets
  // misread as the earlier, unconditionally-failed 'capturing' state -- it must be treated exactly like
  // 'uploading' here: blob-existence is the only thing that decides recoverability, not which of the two
  // status strings happens to be on disk. Terminal states (done/failed/upload_failed) are left alone (returns
  // null: nothing to do).
  function nsReconcileDecision(rec, nowMs, blobExists) {
    if (!rec) return null;
    if (rec.status === 'capturing') return { status: 'failed', error: 'the browser or extension restarted mid-capture' };
    if (rec.status === 'captured' || rec.status === 'uploading') {
      if (blobExists) return { status: 'upload_failed', error: 'the browser or extension restarted while sending — press Retry send' };
      return { status: 'failed', error: 'the browser or extension restarted while sending, and the captured image was not saved — please capture again' };
    }
    return null;
  }

  // repair round 3 (gap #B): same-document identity for provenance pinning. Comparing tab ORIGIN alone (the
  // pre-existing check) lets a same-origin navigation -- example.com/calculator -> example.com/dashboard --
  // pass unnoticed mid-capture, even though the uploaded provenance (rec.url) still names the URL recorded when
  // the capture started. For screenshot evidence, same-origin is not a strong enough identity: this pins
  // origin + pathname + search (a same-document hash-only change, e.g. an in-page anchor jump, is still the
  // same document and stays allowed; a path or query change is not).
  //
  // repair round 4 (Kyle's third re-review): a bare hash change is not always "the same document" in practice.
  // Hash-ROUTED single-page apps switch between entirely different rendered screens through the hash alone
  // (#/dashboard, #!/settings, #/users/42) while origin+pathname+search never changes -- so the round 3 version
  // of this function let a hash-routed SPA navigate to a completely different screen mid-capture without ever
  // tripping the identity check, the exact failure mode gap #B was meant to close. An ordinary in-page anchor
  // jump (#results, #section-2) is still a single token with no path separator or query-like character and must
  // stay allowed, or every page with a table of contents would fail closed on a routine same-page jump. The
  // heuristic: a hash counts as ROUTE-LIKE (and joins the pinned identity) when it contains '/' or '?' --
  // both are how every mainstream hash-router (react-router hash mode, Vue hash mode, Backbone/Angular's
  // hashbang convention) spells a route, and neither ever appears in a plain anchor name.
  function nsIsRouteLikeHash(hash) {
    return !!hash && (hash.includes('/') || hash.includes('?'));
  }
  function nsPageIdentity(urlStr) {
    const u = new URL(urlStr);
    const base = u.origin + u.pathname + u.search;
    return nsIsRouteLikeHash(u.hash) ? base + u.hash : base;
  }

  root.NSCaptureLib = {
    nsMeasure, nsScrollTo, nsHideAndArm, nsRestore, nsHideScrollbars, nsRestoreScrollbars,
    nsPlanTileGrid, nsTileKey, nsIsDuplicateTile, nsCheckCeilings, nsStitchScale, nsRateLimitWaitMs,
    nsIsFallbackEligible, nsReconcileDecision, nsPageIdentity, nsIsRouteLikeHash,
  };
})(typeof self !== 'undefined' ? self : this);
