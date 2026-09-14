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
globalThis.statusBar = function statusBar(u) {
  if (!u) return '';
  const bits = [];
  if (u.blocked) bits.push(`<span class="stbit status-warn" title="${esc(u.blocked)}">⏸ paused</span>`);
  const h = healthInfo(u);
  if (h) bits.push(`<span class="stbit" title="${esc(h.title)}"><span class="${h.cls}">●</span> ${esc(h.label)}</span>`);
  bits.push(`<span class="stbit" title="spent today">$${u.today.toFixed(2)} today</span>`);
  bits.push(`<span class="stbit" title="spent this month">$${u.month.toFixed(2)} this month</span>`);
  const la = u.local_ai || {};
  if (la.profile === 'local' && la.split && la.split.line) bits.push(`<span class="stbit">${esc(la.split.line)}</span>`);
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

// ---- fun stats: how much did we not have to watch? ----
globalThis.YARDSTICKS = [   // [label, hours] — things people know the length of
  // binge-watching
  ['all eight seasons of Game of Thrones', 70.5], ['every episode of The Office (US)', 74], ['all of Breaking Bad', 62], ['all of The Sopranos', 86],
  ['every episode of Friends', 85], ['all five seasons of The Wire', 60], ['all of Seinfeld', 66], ['every episode of Succession', 39],
  ['every Simpsons episode ever made', 290], ['all of Stranger Things', 42], ['every Marvel movie back to back', 60], ['every James Bond film', 52],
  ['the entire Harry Potter film series', 19.7], ['the extended Lord of the Rings trilogy', 11.4], ['the Star Wars saga (all nine)', 21.5],
  ['every Fast & Furious movie', 21], ['all the Pixar films', 42], ['the whole Rocky and Creed series', 18], ['every Best Picture winner since 2000', 52],
  // audiobooks & talks
  ['the Lord of the Rings audiobook', 52], ['all seven Harry Potter audiobooks', 117], ['the War and Peace audiobook', 61], ['the Bible as an audiobook', 75],
  ['every TED talk ever posted on YouTube', 1300], ['Joe Rogan\'s longest 100 episodes', 300], ['a semester of a college course', 45],
  // travel
  ['a New York → Los Angeles drive, non-stop', 41], ['a transatlantic flight', 7.5], ['the longest flight in the world (New York → Singapore)', 18.5],
  ['driving Route 66 end to end', 38], ['the Trans-Siberian Railway, Moscow → Vladivostok', 144], ['a full lap of the Indy 500 (all 200)', 3],
  ['driving around the equator at highway speed', 415], ['the Apollo 11 mission, launch to splashdown', 195], ['one orbit of the ISS', 1.5],
  // life
  ['a full night\'s sleep', 8], ['a standard work week', 40], ['a working month', 160], ['a whole year of weekends (Saturdays only)', 832],
  ['the Beatles\' entire studio catalogue', 10.5], ['the Eras Tour, start to finish', 3.5], ['a full NFL season for one team', 51], ['every match of a World Cup', 128],
  ['a marathon at a brisk walking pace', 6], ['climbing Everest from base camp (round trip)', 60]];
globalThis.BOOKS = [['the whole Lord of the Rings trilogy plus The Hobbit', 576000], ['War and Peace', 587000], ['the Bible, cover to cover', 783000],
  ['all seven Harry Potter books', 1084000], ['Moby-Dick', 209000], ['the complete works of Shakespeare', 884000], ['Infinite Jest', 543000],
  ['Les Misérables', 655000], ['Don Quixote', 345000], ['Ulysses', 265000], ['A Song of Ice and Fire (all five books)', 1770000],
  ['Atlas Shrugged', 561000], ['the Wheel of Time series', 4400000], ['Dune', 188000], ['every Sherlock Holmes story', 660000],
  ['The Great Gatsby', 47000], ['1984', 89000], ['The Hobbit', 95000], ['the Encyclopaedia Britannica (one volume)', 1500000]];
globalThis.FUN = { seed: 0, data: {} };
globalThis.funReroll = function funReroll(el) { FUN.seed++; const id = el.dataset.el; const d = FUN.data[id]; if (d) $('#' + id).innerHTML = funCard(d.f, d.title, id); }
globalThis.funCard = function funCard(f, title, elId) {
  if (elId) FUN.data[elId] = { f, title };
  if (!f || !f.sources) return '';
  const h = f.hours, secs = f.seconds;
  const d = Math.floor(secs / 86400), hh = Math.floor(secs % 86400 / 3600), mm = Math.floor(secs % 3600 / 60);
  const straight = d ? `${d} day${d === 1 ? '' : 's'}, ${hh} h ${mm} min` : `${hh} h ${mm} min`;
  const weeks = h / 40;
  // pick a yardstick that gives a satisfying multiple (between 1.2× and 12×; else the closest); which one rotates with
  // the size of the library and every press of the dice, so the comparison changes as the project grows
  const pick = (list, val) => { let ok = list.filter(([, n]) => val / n >= 1.2 && val / n <= 12); if (!ok.length) ok = [list.reduce((a, b) => Math.abs(Math.log(val / b[1])) < Math.abs(Math.log(val / a[1])) ? b : a)]; const [l, n] = ok[(f.sources + FUN.seed) % ok.length]; return { label: l, times: val / n }; };
  const x = v => v >= 10 ? Math.round(v) + '×' : v >= 2 ? v.toFixed(1).replace(/\.0$/, '') + '×' : v >= 1.2 ? v.toFixed(1) + '×' : (v * 100).toFixed(0) + '% of';
  const y = h >= 0.5 ? pick(YARDSTICKS, h) : null, b = f.words >= 20000 ? pick(BOOKS, f.words) : null;
  const plat = Object.entries(f.by_platform || {}).sort((a, b2) => b2[1] - a[1]).map(([k, n]) => `${n} ${({ youtube: 'YouTube video', media: 'podcast/audio', web: 'web page', document: 'document', instagram: 'reel', spreadsheet: 'spreadsheet', file: 'file', manual: 'pasted text' })[k] || k}${n === 1 ? '' : 's'}`).join(' · ');
  const per = f.hours && f.spend ? `$${(f.spend / f.hours).toFixed(2)} per hour of material` : '';
  // Rung W5/M-2: on Home specifically this block competes with the page's actual job (picking a
  // project) by using larger type than any project title -- subordinate it there only; the same
  // card at full strength inside a project (elId !== 'homeFun') isn't competing with anything.
  const subCls = elId === 'homeFun' ? ' fun-sub' : '';
  return `<div class="fun${subCls}"><div class="funh row" style="gap:8px">📊 ${title}<span class="grow"></span>${elId ? `<button class="small" data-el="${elId}" onclick="funReroll(this)" title="another comparison">🎲 another comparison</button>` : ''}</div>
    <div class="funrow">
      <div class="funstat"><b>${h.toLocaleString()}</b><span>hours of audio &amp; video, read for you</span></div>
      <div class="funstat"><b>${straight}</b><span>if you watched it all back to back${weeks >= 1 ? ` — ${weeks.toFixed(1)} working weeks` : ''}${h >= 2 ? `; still ${(h / 2).toFixed(0)} h at 2× speed` : ''}</span></div>
      <div class="funstat"><b>${(f.words / 1000).toFixed(0)}k</b><span>words of transcript${b ? ` — ${x(b.times)} ${esc(b.label)}` : ''}</span></div>
      ${y ? `<div class="funstat"><b>${x(y.times)}</b><span>${esc(y.label)}</span></div>` : ''}
      ${f.findings ? `<div class="funstat"><b>${f.findings}</b><span>approved findings pulled out of it</span></div>` : ''}
      ${f.spend ? `<div class="funstat"><b>$${f.spend.toFixed(2)}</b><span>spent${per ? ` — ${per}` : ''}</span></div>` : ''}
      ${f.saved >= 0.01 ? `<div class="funstat"><b>$${f.saved.toFixed(2)}</b><span>saved by prompt caching</span></div>` : ''}
    </div>
    <div class="muted" style="margin-top:6px">${f.sources} sources: ${plat}${f.longest ? ` · longest: “${esc(f.longest.title)}” (${f.longest.hours} h)` : ''}</div></div>`;
}
globalThis.toast = function toast(msg, kind = '') {
  let t = $('#toast'); if (!t) { t = document.createElement('div'); t.id = 'toast'; document.body.appendChild(t); }
  t.textContent = msg; t.className = 'show ' + kind; clearTimeout(t._h); t._h = setTimeout(() => t.className = '', 4500);
}
globalThis.put = (p, b) => api(p, { method: 'PUT', body: JSON.stringify(b) });
globalThis.del = (p, b) => api(p, { method: 'DELETE', body: b ? JSON.stringify(b) : undefined });
globalThis._t = undefined; const debounce = (f, ms = 300) => { clearTimeout(_t); globalThis._t = setTimeout(f, ms); };
globalThis.ago = t => { const s = Math.max(0, Math.round(Date.now() / 1000 - t)); return s < 60 ? `${s}s` : s < 3600 ? `${Math.floor(s / 60)}m ${s % 60}s` : `${Math.floor(s / 3600)}h ${Math.floor(s % 3600 / 60)}m`; };
globalThis.fmt = s => { s = Math.round(s || 0); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = s % 60; return h ? `${h}:${String(m).padStart(2, '0')}:${String(x).padStart(2, '0')}` : `${m}:${String(x).padStart(2, '0')}`; };
globalThis.ICON = { youtube: '▶', instagram: '◎', document: '📄', file: '🎙', manual: '✎', media: '♪', web: '🌐', spreadsheet: '🧮', book: '📖', community: '💬' };



export const moduleName = "utils";
