// Focus review — one candidate at a time (Kyle, 2026-09-20: "I really like this new way of reviewing, can we
// build something like this into the app?").
//
// WHY THIS EXISTS, not just how it looks. The review card shows 400 rows sorted by relevance with the best N
// pre-ticked, and one button. Bulk-approving it is the rational thing to do with that interface — but it means
// the app learns almost nothing: the untouched rows get filed as `skipped_low_relevance`, which is the RANKER's
// verdict, and `creator_disposition` then half-counts those as if the person had rejected them. Kyle, on his own
// data: "I have been BULK approving everything so I don't think I have been providing good data back to the app."
// One card at a time produces an actual per-item judgment, and a deliberate Lose here is submitted as
// `user_dismissed` — a real signal at full weight (see ingest.approve_proposed).
//
// Shared by both surfaces: a pending review card (proposed sources) and the pool / Seen-not-added (candidates).
// Callers supply items and a submit function; nothing here knows which surface it is on.

globalThis.FOCUS = {
  open: null, items: [], i: 0, decisions: {}, title: '', subtitle: '', onSubmit: null,
  showScores: true, submitting: false, kind: '',
};

globalThis.focusOpen = function focusOpen(opts) {
  const F = globalThis.FOCUS;
  Object.assign(F, {
    items: opts.items || [], i: 0, decisions: {}, title: opts.title || 'Review',
    subtitle: opts.subtitle || '', onSubmit: opts.onSubmit, kind: opts.kind || '',
    // the two surfaces show DIFFERENT numbers (review relevance vs the pool's potential scan); saying which
    // is not a nicety here -- a score that claims to be something it isn't is the bug this whole line of work
    // has been about
    scoreTitle: opts.scoreTitle || 'score', scoreWord: opts.scoreWord || 'score',
    // A surface whose score is not on the 0-100 relevance scale must say so. Findings carry importance 1-5,
    // and scClass's 60/30 thresholds would paint every one of them red -- the same class of lie as the pool
    // showing `potential` in the slot labelled relevance (fixed 2026-09-20).
    scoreClass: opts.scoreClass || scClass,
    submitting: false,
    // scores are shown by default: this is work, not a blind measurement — but they anchor, so it toggles.
    // Storage can throw outright (private window, blocked site data), so the default must survive that.
    showScores: (() => { try { return JSON.parse(localStorage.getItem('focusShowScores') ?? 'true'); }
                         catch (e) { return true; } })(),
  });
  if (!F.items.length) { toast('Nothing to review here'); return; }
  document.addEventListener('keydown', focusKey, true);
  focusRender();
};

globalThis.focusClose = function focusClose() {
  document.removeEventListener('keydown', focusKey, true);
  const el = $('#focusLayer'); if (el) el.remove();
  globalThis.FOCUS.items = [];
};

globalThis.focusKey = function focusKey(e) {
  if (!$('#focusLayer')) return;
  if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA')) return;
  const k = (e.key || '').toLowerCase();
  if (k === 'k') { e.preventDefault(); focusDecide(true); }
  else if (k === 'l') { e.preventDefault(); focusDecide(false); }
  else if (e.key === 'ArrowLeft') { e.preventDefault(); focusMove(-1); }
  else if (e.key === 'ArrowRight') { e.preventDefault(); focusMove(1); }
  else if (e.key === 'Escape') { e.preventDefault(); focusMaybeClose(); }
};

globalThis.focusDecide = function focusDecide(keep) {
  const F = globalThis.FOCUS, it = F.items[F.i];
  if (!it) return;
  // the Keep button is disabled for a gated item, but the K key would otherwise walk straight past that
  if (keep && it.access_gate) { toast('That one is gated — it cannot be downloaded, so keeping it would do nothing'); return; }
  F.decisions[it.id] = keep;
  if (F.i < F.items.length - 1) { F.i++; focusRender(); }
  else focusRender();                       // last card: stay put, the footer now offers submit
};

globalThis.focusMove = function focusMove(d) {
  const F = globalThis.FOCUS;
  F.i = Math.max(0, Math.min(F.items.length - 1, F.i + d));
  focusRender();
};

globalThis.focusToggleScores = function focusToggleScores() {
  const F = globalThis.FOCUS;
  F.showScores = !F.showScores;
  try { localStorage.setItem('focusShowScores', JSON.stringify(F.showScores)); } catch (e) {}
  focusRender();
};

globalThis.focusMaybeClose = function focusMaybeClose() {
  const F = globalThis.FOCUS, n = Object.keys(F.decisions).length;
  if (n && !confirm(`Close focus review? ${n} decision${n === 1 ? '' : 's'} you made here will be thrown away — nothing has been submitted yet.`)) return;
  focusClose();
};

globalThis.focusRender = function focusRender() {
  const F = globalThis.FOCUS, it = F.items[F.i], n = F.items.length;
  const decided = Object.keys(F.decisions).length;
  const kept = Object.values(F.decisions).filter(Boolean).length;
  const mine = F.decisions[it.id];
  const done = decided === n;

  let layer = $('#focusLayer');
  if (!layer) {
    layer = document.createElement('div');
    layer.id = 'focusLayer';
    document.body.appendChild(layer);
  }
  const score = (it.relevance != null && F.showScores)
    ? `<span class="fsc ${F.scoreClass(it.relevance)}" title="${esc(F.scoreTitle)}">${it.relevance}</span>` : '';
  const why = (it.relevance_why && F.showScores)
    ? `<div class="fwhy">${esc(F.scoreWord)}: ${esc(it.relevance_why)}</div>` : '';
  const facts = it.facts || [
    it.creator ? ['creator', it.creator] : null,
    it.kind_label ? ['kind', it.kind_label] : null,
    it.duration ? ['length', fmt(it.duration)] : null,
    it.published_at ? ['published', it.published_at] : null,
  ].filter(Boolean);

  layer.innerHTML = `
  <div class="fx-back" onclick="focusMaybeClose()"></div>
  <div class="fx-panel" role="dialog" aria-modal="true" aria-label="Focus review">
    <div class="fx-rail"><i style="width:${(decided / n * 100).toFixed(1)}%"></i></div>
    <div class="fx-head">
      <b class="grow">${esc(F.title)}</b>
      <span class="muted fx-count">${F.i + 1} / ${n} · <b>${decided}</b> decided${decided ? ` · ${kept} kept` : ''}</span>
      <button class="small ghost" onclick="focusToggleScores()" title="Scores anchor your judgement. Hiding them makes this a cleaner read of the item itself.">${F.showScores ? 'hide scores' : 'show scores'}</button>
      <button class="small ghost" onclick="focusMaybeClose()">✕</button>
    </div>
    ${F.subtitle ? `<div class="fx-sub muted">${esc(F.subtitle)}</div>` : ''}
    <div class="fx-card">
      <div class="fx-t">${score}${it.url && String(it.url).startsWith('http')
        ? `<a href="${esc(it.url)}" target="_blank" rel="noopener">${esc(it.title || it.url)}</a>`
        : esc(it.title || '(untitled)')}</div>
      <div class="fx-facts">${facts.map(([k, v]) => `<span class="fx-f">${esc(k)} <b>${esc(v)}</b></span>`).join('')}</div>
      ${it.description ? `<div class="fx-desc">${esc(String(it.description).slice(0, 700))}</div>` : ''}
      ${why}
      ${it.quote ? `<div class="fx-quote">“${esc(String(it.quote).slice(0, 600))}”</div>` : ''}
      ${it.note ? `<div class="fwhy">${esc(it.note)}</div>` : ''}
      ${it.access_gate ? `<div class="fx-gate">🔒 ${esc(it.access_gate === 'members_only' ? 'members-only — cannot be downloaded without your own channel membership' : it.access_gate)}</div>` : ''}
    </div>
    <div class="fx-acts">
      <button class="fx-act keep${mine === true ? ' on' : ''}" onclick="focusDecide(true)" ${it.access_gate ? 'disabled title="gated — cannot be ingested"' : ''}>
        <span class="l">Keep</span><span class="k">K</span></button>
      <button class="fx-act lose${mine === false ? ' on' : ''}" onclick="focusDecide(false)">
        <span class="l">Lose</span><span class="k">L</span></button>
    </div>
    <div class="fx-foot">
      <button class="small ghost" onclick="focusMove(-1)" ${F.i === 0 ? 'disabled' : ''}>← back</button>
      <button class="small ghost" onclick="focusMove(1)" ${F.i === n - 1 ? 'disabled' : ''}>forward →</button>
      <span class="grow"></span>
      ${decided ? `<button class="primary" onclick="focusSubmit(this)"${F.submitting ? ' disabled' : ''}>${done ? `Apply all ${n}` : `Apply ${decided} so far`}</button>` : '<span class="muted fx-hint">K to keep · L to lose · ← → to move</span>'}
    </div>
  </div>`;
};

globalThis.focusSubmit = async function focusSubmit(btn) {
  const F = globalThis.FOCUS;
  if (F.submitting) return;
  const keep = [], drop = [];
  for (const [id, v] of Object.entries(F.decisions)) (v ? keep : drop).push(id);
  const undecided = F.items.length - (keep.length + drop.length);
  if (undecided && !confirm(`${undecided} item${undecided === 1 ? '' : 's'} you haven't judged yet will be left exactly as they are. Apply the ${keep.length + drop.length} you did decide?`)) return;
  F.submitting = true;
  if (btn) { btn.disabled = true; btn.textContent = 'Applying…'; }
  try {
    await F.onSubmit({ keep, drop });
    focusClose();
  } catch (e) {
    F.submitting = false;
    if (btn) { btn.disabled = false; btn.textContent = 'Apply'; }
    toast('Could not apply: ' + (e.message || e), 'err');
  }
};
