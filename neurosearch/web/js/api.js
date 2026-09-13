
globalThis.$ = s => document.querySelector(s);
globalThis.esc = s => (s ?? '').toString().replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
// ================= 0.63.32: every press is acknowledged within one frame =================
// Kyle: "every single button needs instant feedback that SOMETHING has happened even if it takes many
// seconds to truly do something. right now I click a button and the button doesnt respond for 1-5
// seconds and I think something is broken."
//
// Measured in this file before building anything: 228 controls carry a click handler and TWELVE of them
// acknowledge the click. So this is ONE mechanism, not 216 patched call sites — patching them by hand
// would be a day's work, would miss the next button anyone adds, and could not be gated.
//
// How it works, and why in this order:
//   1. A CAPTURE-phase listener on `document` runs BEFORE any onclick attribute, so the press is marked
//      before the handler gets a chance to block the thread. That is what makes it feel instant: the
//      class lands in the same frame as the click, whatever the handler then does for five seconds.
//   2. Every request in the app goes through `api()` (post/put/del all call it), so `api()` is the one
//      place that knows when the work actually finishes. A request starting within CLAIM_MS of a press
//      belongs to that press; the button stays busy until every request it started has settled.
//   3. A click that starts NO request clears on the next frame — correct, not a bug: a tab switch or a
//      collapse toggle really is done, and it still flashed, which is the acknowledgement.
//   4. A watchdog clears anything still busy after STUCK_MS. A spinner that never stops is the same lie
//      as no spinner at all, and this codebase has paid for that shape six times.
// It never writes a control's textContent. The twelve handlers that already say "⏳ queueing…" or
// "Pinned ✓" own their labels; a class and a pseudo-element compose with those, a label write fights
// them.
globalThis.NSACK = {
  CLAIM_MS: 1500,        // a handler may await something before its first request
  SETTLE_MS: 400,        // bridges the gap between requests in one handler's chain
  STUCK_MS: 45000,       // longer than the slowest measured endpoint, so it never fires on real work
  el: null, at: 0, n: 0, bar: null, depth: 0,
  press(el) {
    this.done();                                       // a new press supersedes an unfinished one
    this.el = el; this.at = performance.now(); this.n = 0;
    el.classList.add('ns-press');
    setTimeout(() => el.classList.remove('ns-press'), 110);
  },
  claim() {
    // A press owns its whole REQUEST CHAIN, not just its first request. `bulkNotes` posts 59 ids in
    // ~200 ms and then calls loadNotes(), which re-fetches the project, the staleness map and a page of
    // findings — several seconds. Releasing on the first settle left that entire tail unacknowledged,
    // which is the exact complaint this feature exists to answer, and it was still true after shipping
    // it. So once a press is busy it keeps claiming regardless of CLAIM_MS; the window only decides
    // whether a press may START a chain.
    const live = this.el && (this.n > 0 || performance.now() - this.at <= this.CLAIM_MS);
    if (!live) return null;
    const el = this.el;
    clearTimeout(this._settle);
    if (this.n === 0) { try { el.setAttribute('aria-busy', 'true'); } catch (e) {} }
    this.n++;
    clearTimeout(this._stuck);
    this._stuck = setTimeout(() => this.done(), this.STUCK_MS);
    return el;
  },
  release(el) {
    if (!el) return;
    if (this.el !== el) { try { el.removeAttribute('aria-busy'); } catch (e) {} return; }
    if (--this.n > 0) return;
    // Do not clear on the instant the last request settles: a handler that immediately issues its next
    // request (post → reload is the commonest shape in this file) would otherwise flicker off and on.
    // A new claim inside SETTLE_MS cancels this, so the state spans the gaps in a chain.
    clearTimeout(this._settle);
    this._settle = setTimeout(() => { if (this.n === 0) this.done(); }, this.SETTLE_MS);
  },
  done() {
    clearTimeout(this._stuck); clearTimeout(this._settle);
    const el = this.el;
    if (el) { try { el.removeAttribute('aria-busy'); el.classList.remove('ns-press'); } catch (e) {} }
    this.el = null; this.n = 0;
  },
  // the window's own bar, for the clicks whose handler re-renders the panel and destroys the button
  rise() { if (++this.depth === 1) this._bar(true); },
  fall() { if (--this.depth <= 0) { this.depth = 0; this._bar(false); } },
  _bar(on) {
    if (!this.bar) { this.bar = document.createElement('div'); this.bar.id = 'nsbar'; this.bar.innerHTML = '<i></i>'; document.body.appendChild(this.bar); }
    this.bar.className = on ? 'on' : '';
  },
};
// capture:true is load-bearing — without it this runs after the onclick has already blocked the thread
document.addEventListener('click', e => {
  const el = e.target && e.target.closest && e.target.closest('button, a[onclick], a[data-action]');
  if (!el || el.disabled || el.dataset.noack === '1' || el.getAttribute('aria-busy') === 'true') return;
  NSACK.press(el);
}, true);

document.addEventListener('change', e => {
  const el = e.target;
  if (el && el.matches('select[onchange], input[onchange]') && !el.disabled) NSACK.press(el);
}, true);

globalThis.api = async function api(path, opts = {}) {
  // opts.ack === false: a background poll must never light the window up. Everything a person started
  // is acknowledged; the 3-second /tick loop is not something a person started.
  const owner = opts.ack === false ? null : NSACK.claim();
  const quiet = opts.ack === false;
  if (!quiet) NSACK.rise();
  try {
    const r = await uiFetch(path, { headers: { 'Content-Type': 'application/json' }, ...opts });
    if (r.status === 401) { location.reload(); return; }
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || j.detail || r.statusText);
    return j;
  } finally {
    if (!quiet) NSACK.fall();
    NSACK.release(owner);
  }
}
globalThis.post = (p, b) => api(p, { method: 'POST', body: JSON.stringify(b) });


export const moduleName = "api";
