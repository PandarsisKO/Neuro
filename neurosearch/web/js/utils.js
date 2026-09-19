// ---- shared status component (Rung W5, H-1/RC-F) ----
// One place that turns the raw /api/usage payload into independently legible parts, ordered by what
// needs noticing first: a blocked/paused warning (if any), local-AI health, today's spend, this
// month's spend -- then, de-emphasized, the local/paid split richness the old single sentence also
// carried (kept so nothing is lost, just no longer competing for the first glance). Used by both
// Home's header line and the Chat sidebar footer (`H-1`'s propagation note).
globalThis.healthInfo = function healthInfo(u) {
  const la = (u && u.local_ai) || {};
  if (la.profile !== 'local') return null;
  const map = { ready: ['status-ok', 'Local AI ready'], checking: ['status-warn', 'Checking…'], unchecked: ['status-warn', 'Not checked'],
    usage_limit: ['status-bad', 'Usage limit'], disabled: ['', 'Local AI off'] };
  const [cls, label] = map[la.state] || ['status-bad', la.state ? String(la.state).replace(/_/g, ' ') : 'Unknown'];
  return { cls, label, title: la.line || '' };
}
globalThis.statusBar = function statusBar(u, compact) {
  if (!u) return '';
  // RD-3: the project sidebar footer used to render the exact same bar as Home's header -- health,
  // today AND this month's spend, at the foot of every project, every time. The two figures that
  // change while you're actually working a project (is local AI OK right now, what has today cost)
  // are what the sidebar needs; the month total belongs to the page you came to Home or Settings for.
  if (compact) {
    if (u.blocked) return `<span class="statusbar"><span class="stbit status-warn" title="${esc(u.blocked)}">⏸ paused</span></span>`;
    const h = healthInfo(u);
    const bits = [];
    if (h) bits.push(`<span class="stbit" title="${esc(h.title)}"><span class="${h.cls}">●</span> ${esc(h.label)}</span>`);
    bits.push(`<span class="stbit" title="spent today">$${u.today.toFixed(2)} today</span>`);
    return `<span class="statusbar">${bits.join('')}</span>`;
  }
  const bits = [];
  if (u.blocked) bits.push(`<span class="stbit status-warn" title="${esc(u.blocked)}">⏸ paused</span>`);
  const h = healthInfo(u);
  if (h) bits.push(`<span class="stbit" title="${esc(h.title)}"><span class="${h.cls}">●</span> ${esc(h.label)}</span>`);
  bits.push(`<span class="stbit" title="spent today">$${u.today.toFixed(2)} today</span>`);
  bits.push(`<span class="stbit" title="spent this month">$${u.month.toFixed(2)} this month</span>`);
  // RD-2: this used to also append the local/paid split line (call count, % local, "actual"/"avoided"
  // dollar figures) -- a third and fourth reading of the same money Settings' Health panel already
  // shows authoritatively (recorded vs likely-charged, local calls avoided). One canonical place for
  // that breakdown beats a fifth figure competing with it on every Home/sidebar render.
  return `<span class="statusbar">${bits.join('')}</span>`;
}
// A last-activity signal legible at a glance (M-1) -- relative for anything recent, an actual date once
// it stops being useful as a "how recently" answer.
globalThis.relTime = function relTime(ts) {
  if (!ts) return '';
  const s = Date.now() / 1000 - ts;
  if (s < 90) return 'just now';
  if (s < 3600) { const m = Math.round(s / 60); return `${m} min ago`; }
  if (s < 86400) { const h = Math.round(s / 3600); return `${h} h ago`; }
  if (s < 86400 * 13) { const d = Math.round(s / 86400); return `${d} day${d === 1 ? '' : 's'} ago`; }
  return new Date(ts * 1000).toLocaleDateString();
}

// ---- shared list-state primitive (loading / empty / failed) — DESIGN.md SS7/SS11, Rung F2 ----
// One shared three-state block for any list that renders from a fetch. `loading` shows on first
// paint only (callers gate that themselves); `failed` always renders an explicit retry rather
// than leaving stale or blank content that reads as "still loading" forever.
globalThis.listState = function listState(kind, opts = {}) {
  if (kind === 'loading') return `<div class="empty"><span class="spin"></span> ${esc(opts.label || 'Loading…')}</div>`;
  if (kind === 'failed') return `<div class="empty listfail">⚠ ${esc(opts.message || "Couldn't load — try again.")} <button class="small ghost" onclick="${opts.retry || ''}">Retry</button></div>`;
  return `<div class="empty">${esc(opts.message || 'Nothing here yet.')}</div>`;
}

// ---- fun stats: how much material has this project's sources saved you from watching/reading yourself ----
// RD-1: this card used to render on four surfaces (Home, sidebar, Sources, Settings) with a
// decorative "another comparison" reroll and a pile of yardstick/book comparisons. Home is now
// the only surface it renders on -- one honest reading in one place, not a "fun facts" moment
// competing with the page's actual job.
globalThis.FUN = { seed: 0, data: {} };
globalThis.funCard = function funCard(f, title) {
  if (!f || !f.sources) return '';
  return `<div class="fun fun-sub"><div class="funh row" style="gap:8px">📊 ${title}</div>
    <div class="funrow">
      <div class="funstat"><b>${f.hours.toLocaleString()}</b><span>hours of audio &amp; video, read for you</span></div>
      ${f.findings ? `<div class="funstat"><b>${f.findings}</b><span>approved findings pulled out of it</span></div>` : ''}
    </div>
    <div class="muted" style="margin-top:6px">${f.sources} sources</div></div>`;
}
globalThis.toast = function toast(msg, kind = '') {
  let t = $('#toast'); if (!t) { t = document.createElement('div'); t.id = 'toast'; document.body.appendChild(t); }
  t.textContent = msg; t.className = 'show ' + kind; clearTimeout(t._h); t._h = setTimeout(() => t.className = '', 4500);
}
globalThis.put = (p, b) => api(p, { method: 'PUT', body: JSON.stringify(b) });
globalThis.del = (p, b) => api(p, { method: 'DELETE', body: b ? JSON.stringify(b) : undefined });
globalThis._t = undefined; const debounce = (f, ms = 300) => { clearTimeout(_t); globalThis._t = setTimeout(f, ms); };
// "added 3h ago" / "added 4d ago": coarse, for a row's meta line (`ago` is the fine one for a running job)
globalThis.agoShort = t => { const s = Math.max(0, Math.round(Date.now() / 1000 - t)); return s < 60 ? 'just now' : s < 3600 ? `${Math.floor(s / 60)}m ago` : s < 86400 ? `${Math.floor(s / 3600)}h ago` : s < 86400 * 30 ? `${Math.floor(s / 86400)}d ago` : new Date(t * 1000).toLocaleDateString(); };
globalThis.ago = t => { const s = Math.max(0, Math.round(Date.now() / 1000 - t)); return s < 60 ? `${s}s` : s < 3600 ? `${Math.floor(s / 60)}m ${s % 60}s` : `${Math.floor(s / 3600)}h ${Math.floor(s % 3600 / 60)}m`; };
globalThis.fmt = s => { s = Math.round(s || 0); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = s % 60; return h ? `${h}:${String(m).padStart(2, '0')}:${String(x).padStart(2, '0')}` : `${m}:${String(x).padStart(2, '0')}`; };
globalThis.ICON = { youtube: '▶', instagram: '◎', document: '📄', file: '🎙', manual: '✎', media: '♪', web: '🌐', spreadsheet: '🧮', book: '📖', community: '💬' };



export const moduleName = "utils";
