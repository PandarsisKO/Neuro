// ---- sources ----
globalThis.showPane = function showPane(p) {
  document.querySelectorAll('.tabs button').forEach(b => b.classList.toggle('active', b.dataset.pane === p));
  document.querySelectorAll('.pane').forEach(s => s.classList.toggle('active', s.id === 'pane-' + p));
  if (p === 'library') { loadLibrary(); loadCandidates(); }
  if (p === 'discover') loadDiscoveries();
  if (p === 'library') { loadWorks(); loadCommunity(); }
  if (p === 'course') loadCoursePane();
}
globalThis.rvSig = null;
globalThis.RVFOLD = {};      // review card id -> folded? (default: everything after the first)
globalThis.rvUnchecked = {};   // collection id -> Set of source ids the user unticked (survives re-renders)
globalThis.rvFilterText = {};
globalThis.rvAutoApplied = {}; // collection id -> true once the relevance pre-selection has been applied
globalThis.scClass = function scClass(v) { return v >= 60 ? 'hi' : v >= 30 ? 'mid' : ''; }
globalThis.loadReviews = async function loadReviews() {
  const rvs = await api(`/api/projects/${state.project.id}/reviews`).catch(() => []);
  // Only rebuild the card when the list (or its ranking) changed; the poller calls this every few seconds
  const sig = rvs.map(c => c.id + ':' + (c.meta && c.meta.ranked ? 'R' : 'r') + ':' + c.proposed.map(s => s.id + (s.relevance == null ? '' : '=' + s.relevance)).join(',')).join('|');
  if (sig === rvSig) return;
  globalThis.rvSig = sig;
  $('#reviewWrap').innerHTML = rvs.map((c, idx) => {
    const meta = c.meta || {}, want = meta.max_videos || 0, ranked = !!meta.ranked;
    rvData[c.id] = c.proposed;
    const scored = ranked && c.proposed.some(s => s.relevance != null);
    const off = rvUnchecked[c.id] || (rvUnchecked[c.id] = new Set());
    if (scored && !rvAutoApplied[c.id]) {   // first time we see scores: tick the best `want`, untick the rest
      rvAutoApplied[c.id] = true; off.clear();
      c.proposed.forEach((s, i) => { if ((want && i >= want) || !s.relevance) off.add(s.id); });
    }
    const n = c.proposed.length, mins = c.proposed.reduce((a, s) => a + (s.duration || 0), 0) / 60;
    const nSel = c.proposed.filter(s => !off.has(s.id)).length;
    const est = rvEstimate(c.proposed.filter(s => !off.has(s.id)));
    const rankLine = !ranked
      ? `<span class="muted">⏳ Ranking these by relevance to your brief… (titles &amp; descriptions only, nothing downloaded)</span>`
      : scored
        ? `<span class="muted">✨ Sorted by relevance to your brief — the best ${want ? Math.min(want, n) : n} are pre-selected.${meta.rank_note ? ` <span class="status-warn">${esc(meta.rank_note)}</span>` : ''}</span>
           <span style="display:inline-flex;gap:6px;align-items:center;margin-left:auto;white-space:nowrap"><span class="muted">pick top</span><input type="number" min="1" max="${n}" value="${want || n}" style="width:64px;flex:none;padding:4px 6px" onchange="rvTop('${c.id}', +this.value)"><button class="small ghost" title="Scores these by relevance to your brief (titles &amp; descriptions only) — uses your model budget" onclick="rvRerank('${c.id}')">re-rank</button></span>`
        : `<span class="muted">${esc(meta.rank_note || 'Newest first.')} Add a goal or brief in Settings and re-rank to sort by relevance.</span><button class="small ghost push-right" title="Scores these by relevance to your brief (titles &amp; descriptions only) — uses your model budget" onclick="rvRerank('${c.id}')">re-rank</button>`;
    // Only the FIRST review card is open. Three of them (107 + 93 + 398 videos) stacked to a page whose queue
    // controls could not be scrolled to at all — the inner lists swallow the wheel, so "further down" was
    // unreachable. A folded card still shows what it is and how much is selected; opening it is one click.
    const folded = RVFOLD[c.id] !== undefined ? RVFOLD[c.id] : idx > 0;
    return `<div class="card rv${folded ? ' folded' : ''}" style="border-color:var(--warn)" id="rv-${c.id}">
      <div class="row"><b class="grow">Review before starting: ${esc(c.title || c.kind)}<span class="rvfold" onclick="RVFOLD['${c.id}']=!(RVFOLD['${c.id}'] !== undefined ? RVFOLD['${c.id}'] : ${idx > 0});globalThis.rvSig =null;loadReviews()">${folded ? '▸ show' : '▾ hide'}</span></b><span class="muted"><span id="rvsel-${c.id}">${nSel}</span> of ${n} selected${mins ? ` · ${Math.round(mins / 6) / 10} h listed` : ''}</span></div>
      <div style="margin-top:3px;font-size:13px">💵 <span id="rvest-${c.id}">${est}</span></div>
      ${meta.counts ? `<div class="muted" style="margin-top:2px">🗂 ${(meta.counts.already_in_project || 0) + (meta.counts.already_in_library || 0) + (meta.counts.new || 0)} found · <b>${meta.counts.already_in_library || 0}</b> already in your library (reused, not re-downloaded) · <b>${meta.counts.already_in_project || 0}</b> already in this project · <b>${meta.counts.new || 0}</b> new — the estimate below covers only new work</div>` : ''}
      <div class="muted" style="margin-top:2px">Nothing has been downloaded yet. Videos older than your cutoff are skipped automatically once dates are known.${c.kind === 'instagram' ? ' <b>Instagram:</b> these download one at a time with long pauses, using your session — keep it to a handful per day.' : ''}</div>
      <div class="row mt-1">${rankLine}</div>
      <div class="row" style="margin-top:6px"><button class="small ghost" onclick="rvAll('${c.id}', true)">select all</button><button class="small ghost" onclick="rvAll('${c.id}', false)">none</button><input placeholder="filter titles…" style="max-width:240px" value="${esc(rvFilterText[c.id] || '')}" oninput="rvFilter('${c.id}', this.value)"></div>
      <div class="list">${c.proposed.map(s => `<label class="li"${rvFilterText[c.id] && !(s.title || s.url).toLowerCase().includes(rvFilterText[c.id].toLowerCase()) ? ' hidden' : ''}><input type="checkbox" ${off.has(s.id) ? '' : 'checked'} data-id="${s.id}" onchange="rvRemember('${c.id}', this)">${s.relevance != null ? `<span class="sc ${scClass(s.relevance)}" title="relevance">${s.relevance}</span>` : ''}<span class="t" title="${esc(s.title || s.url)}">${esc(s.title || s.url)}</span>${s.relevance_why ? `<span class="why" title="${esc(s.relevance_why)}">${esc(s.relevance_why)}</span>` : ''}<span class="muted">${s.duration ? fmt(s.duration) : ''}</span></label>`).join('')}</div>
      <div class="row rvfoot" style="margin-top:10px"><button class="primary" onclick="rvStart('${c.id}', this)">▶ Start ingesting selected</button><button class="ghost" onclick="rvDiscard('${c.id}')">Discard all</button></div>
    </div>`; }).join('');
}
globalThis.rvData = {};   // collection id -> proposed rows (for live cost estimates)
globalThis.estFallback = function estFallback(s) {   // same formula as usage.estimate_video, for servers that don't send `est`
  const mins = Math.max((s.duration || 0) / 60, 1), chars = mins * 1000, windows = Math.max(1, Math.ceil(chars / 60000));
  return { analyse: (chars / 4 + windows * 1500) / 1e6 * 3 + windows * 800 / 1e6 * 15, whisper: mins * 0.006 };
}
globalThis.rvEstimate = function rvEstimate(rows) {
  rows = rows.map(s => s.est ? s : { ...s, est: estFallback(s) });
  const a = rows.reduce((t, s) => t + (s.est?.analyse || 0), 0), w = rows.reduce((t, s) => t + (s.est?.whisper || 0), 0);
  const hrs = rows.reduce((t, s) => t + (s.duration || 0), 0) / 3600;
  return `<span title="Findings analysis + embeddings, assuming YouTube captions exist (free). Videos without captions are transcribed with Whisper at $0.006/min — worst case +$${w.toFixed(2)} if none of them have captions.">≈ <b>$${a.toFixed(2)}</b> to analyse ${hrs.toFixed(1)} h of selected video <span class="muted">· up to +$${w.toFixed(2)} more if captions are missing (Whisper)</span></span>`;
}
globalThis.rvCount = function rvCount(id) {
  const all = [...document.querySelectorAll(`#rv-${id} input[type=checkbox]`)], on = new Set(all.filter(i => i.checked).map(i => i.dataset.id));
  const a = $(`#rvsel-${id}`), b = $(`#rvest-${id}`); if (a) a.textContent = on.size;
  if (b) b.innerHTML = rvEstimate((rvData[id] || []).filter(s => on.has(s.id)));
}
globalThis.rvRemember = function rvRemember(id, input) { const off = rvUnchecked[id] || (rvUnchecked[id] = new Set()); if (input.checked) off.delete(input.dataset.id); else off.add(input.dataset.id); rvCount(id); }
globalThis.rvAll = function rvAll(id, on) { document.querySelectorAll(`#rv-${id} .li`).forEach(l => { if (!l.hidden) { const i = l.querySelector('input'); i.checked = on; rvRemember(id, i); } }); }
globalThis.rvTop = function rvTop(id, n) { document.querySelectorAll(`#rv-${id} .li`).forEach((l, i) => { const inp = l.querySelector('input'); inp.checked = i < n; rvRemember(id, inp); }); }
globalThis.rvFilter = function rvFilter(id, q) { rvFilterText[id] = q; q = q.toLowerCase(); document.querySelectorAll(`#rv-${id} .li`).forEach(l => l.hidden = !l.textContent.toLowerCase().includes(q)); }
globalThis.rvRerank = async function rvRerank(id) { delete rvAutoApplied[id]; await post(`/api/collections/${id}/rank`, { project_id: state.project.id }); globalThis.rvSig = null; loadReviews(); setTimeout(loadReviews, 4000); }
globalThis.rvStart = async function rvStart(id, btn) {
  const ids = [...document.querySelectorAll(`#rv-${id} input:checked`)].map(i => i.dataset.id);
  if (!ids.length) return alert('Nothing selected.');
  if (btn) { btn.disabled = true; btn.textContent = `Starting ${ids.length}…`; }
  try {
    const r = await post(`/api/collections/${id}/approve`, { source_ids: ids });
    toast(`▶ ${r.started} video${r.started === 1 ? '' : 's'} queued for transcript + findings${r.dropped ? ` · ${r.dropped} unticked ones dropped` : ''}`);
    delete rvUnchecked[id]; delete rvFilterText[id]; delete rvAutoApplied[id]; globalThis.rvSig = null;
    loadReviews(); loadJobs(); loadSources();
  } catch (e) {
    toast('Could not start: ' + (e.message || e), 'err');
    if (btn) { btn.disabled = false; btn.textContent = '▶ Start ingesting selected'; }
  }
}
globalThis.rvDiscard = async function rvDiscard(id) { if (!confirm('Discard this list? Nothing was downloaded; you can paste the link again later.')) return; await post(`/api/collections/${id}/approve`, { source_ids: [] }); delete rvUnchecked[id]; delete rvAutoApplied[id]; globalThis.rvSig = null; loadReviews(); }
// Grouping (PRODUCT-ORGANIZATION.md #1): every source already carries a "channel" — a YouTube channel, a subreddit
// (community.py sets it to the subreddit name), a book's creators, or a web page's domain — so origin grouping needs
// no new scanning or schema, just reading a column that was already there. SRCG remembers which groups the user
// closed by hand so a refresh (a new source landing, a filter change) doesn't re-open them.
// R2 part 3 (SPEED-MISSION.md): `html` is the last content rendered per group and `byKey` the current rows, so a
// refresh can patch only the groups that actually changed instead of rebuilding all 22,470 nodes — which also stops
// every poll from throwing away scroll position and open/closed state.
globalThis.SRCG = { collapsed: new Set(), rows: [], html: new Map(), keys: [], byKey: {}, loaded: false };
globalThis.srcGroupToggled = function srcGroupToggled(key, open) {
  if (open) SRCG.collapsed.delete(key); else SRCG.collapsed.add(key);
  if (!open) return;
  // a collapsed group's rows are never built (on Kyle's project that is most of 1,234 rows of DOM nobody can see),
  // so fill it the first time it is opened.
  const el = document.querySelector(`#srcList details[data-k="${CSS.escape(key)}"] .grows`);
  if (el && !el.innerHTML && (SRCG.byKey[key] || []).length) {
    const html = SRCG.byKey[key].map(srcRowHtml).join('');
    el.innerHTML = html; SRCG.html.set(key, html);
  }
}
globalThis.srcGroupKey = function srcGroupKey(s) {
  if (s.channel) return s.channel;
  return { video: 'YouTube (no channel)', community: 'Community (no subreddit)', book: 'Books', document: 'Documents',
           spreadsheet: 'Spreadsheets', podcast: 'Podcasts', file: 'Files' }[s.platform] || 'Other';
}
globalThis.srcRowHtml = function srcRowHtml(s) {
  const needsBrowser = !!(s.acquisition && s.acquisition.state === 'requires_browser');
  const liveLine = (() => {
    if (needsBrowser) return '';
    if (s.status === 'pending' && s.job) {
      const j = s.job;
      if (j.status === 'running') return `<span class="spin"></span> ${esc(j.message || 'working…')} <span class="muted">· ${ago(j.updated_at || Date.now() / 1000)} ago</span>`;
      if (j.waiting_until && j.waiting_until > Date.now() / 1000) return `⏸ ${esc(j.message || 'waiting')} <span class="muted">· resumes in ${ago(2 * Date.now() / 1000 - j.waiting_until)}</span>`;
      return `⏳ waiting in line · #${j.position}${j.message ? ' · ' + esc(j.message) : ''}`;
    }
    if (s.status === 'pending') return '⏳ pending (no job — use Retry)';
    return '';
  })();
  return `<div class="src ${(s.job && s.job.status === 'running') || s.analysing ? 'live' : ''}">
    ${s.thumbnail_url ? `<img src="${esc(s.thumbnail_url)}" loading="lazy" onerror="this.outerHTML=${esc(JSON.stringify(`<div class="ico">${ICON[s.platform] || '•'}</div>`))}">` : `<div class="ico">${ICON[s.platform] || '•'}</div>`}
    <div class="grow min-w-0">
      <div class="t">${s.priority ? '<span title="Priority source for this project — retrieval favours it">★</span> ' : ''}${s.url.startsWith('http') ? `<a href="${esc(s.url)}" target="_blank">${esc(s.title || s.url)}</a>` : esc(s.title || s.url)}</div>
      <div class="muted">${esc(s.channel || s.platform)} ${s.published_at ? '· ' + s.published_at : ''} ${s.duration ? '· ' + fmt(s.duration) : (s.description || '')}${s.r6_provisional ? ' <span class="tag" title="Fast-wave result: useful early evidence, still provisional while the warm/deep queue continues. Later evidence can revise it.">⚡ provisional</span>' : ''}${s.under_read ? ' <span class="tag status-warn" title="Long source read once at the old 12-finding cap — Read deeper to get what it holds">📚 under-read</span>' : ''} <span class="st ${s.status} ${s.job && s.job.status === 'running' ? 'active' : ''}">${s.job && s.job.status === 'running' ? 'active' : s.status === 'pending' ? 'queued' : s.status}</span> ${s.transcript_kind ? '· ' + s.transcript_kind : ''} ${(s.tags || []).map(t => `<span class="chip">${esc(t)}</span>`).join('')}</div>
      ${needsBrowser ? browserBlock(s) : s.error ? `<div class="muted status-bad">${esc(s.error)}${s.error_class && !s.error_class.startsWith('browser_solvable') ? ` <span class="tag" title="${PERMANENT_FAILURES.has(s.error_class) ? 'A retry cannot help with this one — the material is gone or has no audio. Remove it from the project when you are ready.' : 'This one could work on another try.'}">${PERMANENT_FAILURES.has(s.error_class) ? 'will not work' : 'retryable'} · ${esc(s.error_class.replace(/_/g, ' '))}</span>` : ''}</div>` : ''}
      ${s.status === 'skipped' && s.pool_potential ? `<div class="muted" style="margin-top:3px" title="${esc((s.pool_potential.why || []).join('; ') || 'no signal either way')}"><span class="tag${s.pool_potential.score >= 40 ? ' status-ok' : ''}">🔎 ${s.pool_potential.score >= 40 ? 'worth a look' : 'low potential'} — ${s.pool_potential.score}/100</span>${s.pool_potential.fits ? ` · fits: ${esc(s.pool_potential.fits)}` : ''}</div>` : ''}
      ${completenessLine(s)}
      ${liveLine ? `<div style="margin-top:3px;font-size:13px">${liveLine}</div>` : ''}
      ${s.summary ? `<div class="muted mt-1">${s.legacy_analysis ? `<span class="tag status-warn" title="Preserved from Neuro Search 0.15 — its original project context cannot be verified. Re-analyse to replace it.">⚠ legacy analysis</span> ` : ''}${s.substance != null ? `<span class="tag ${s.substance >= 60 ? 'status-ok' : s.substance >= 30 ? 'status-warn' : 'status-bad'}">substance ${s.substance}/100</span> ` : ''}${esc(s.summary)}</div>` : ''}
      ${s.status === 'ready' ? `<div class="muted mt-1">${s.analysing ? `<span class="spin"></span> ${s.analysis_job && s.analysis_job.status === 'running' ? esc(s.analysis_job.message || 'reading…') + (s.analysis_job.progress ? ` <span class="muted">· ${Math.round(s.analysis_job.progress * 100)}%</span>` : '') : s.analysis_job && s.analysis_job.status === 'queued' ? `queued${s.analysis_job.depth === 'deep' ? ' for a deep read (slow lane — other work keeps running)' : ' for findings'}` : 'reading transcript for findings…'}` : s.suggested ? `<a href="#" onclick="openSourceSuggestions('${s.id}','suggested');return false" class="status-warn">📌 ${s.suggested} suggested finding${s.suggested === 1 ? '' : 's'} waiting for review</a>` : s.approved ? `<a href="#" onclick="sourceDrawer('${s.id}');return false">📌 ${esc(s.value && s.value.label && s.value.label !== 'nothing yet' ? s.value.label : `${s.approved} approved finding${s.approved === 1 ? '' : 's'}`)}</a>${s.value && s.value.stale ? ` <span class="tag status-warn" title="${esc((s.value.stale_reasons || []).join('; '))}">⚠ stale</span>` : ''}` : s.analysed ? '📌 analysed — nothing worth suggesting' : '📌 not analysed yet'}${s.reserve ? ` · <a href="#" onclick="toggleReserve('${s.id}', this);return false" title="Findings the model extracted beyond the length-aware cap — lower importance, kept rather than thrown away. Promote the ones worth keeping.">+${s.reserve} more extracted</a>` : ''}</div><div class="reserve" id="reserve-${s.id}" hidden></div>` : ''}
      ${sourceRowActions(s, needsBrowser)}
    </div></div>`;
}
// 0.63.69 (W4): H-4 found six-plus equal-weight actions on every one of 1,348 rows, "Remove from project" (reversible)
// sitting next to "Delete everywhere" (irreversible) distinguished only by color, and F0 addendum 4's runtime walk
// found a sharper version — row height varies (extra buttons on long-form/video/image sources, extra tag lines),
// so a fast repeated click at a fixed offset can miss its row entirely, not just its button. Fix: one primary action
// by task context — the thing that moves this source forward — stays visible; a rare, high-value, source-type
// action (Calculator, add embedded videos) stays visible alongside it because F0 addendum 4's own bulk-review
// baseline showed exactly this shape of action used on a large share of rows, so it is not buried; everything else,
// destructive actions especially, moves one deliberate step behind a "⋯" overflow menu — same `.menu` component
// already used for chat's Copy/Share menus, so this reuses an existing pattern rather than inventing one. What any
// action does, costs or confirms is unchanged: delSource's confirm() already scales to "Delete everywhere"'s
// irreversibility; this only changes where these buttons sit.
globalThis.sourceRowActions = function sourceRowActions(s, needsBrowser) {
  const canRetry = !needsBrowser && (s.status === 'failed' || (s.status === 'pending' && !s.job));
  // The stated rule, so the choice is never arbitrary: primary = the one action that makes progress on the reason
  // this row is in the list right now. Ingest/Retry when it is not yet in the library; analyse when it has not
  // been read; review what it gave once it has — matching DESIGN.md's outcome-over-implementation labelling.
  let primary = '';
  if (s.status === 'skipped') primary = `<button class="small primary" title="Fetch it even though it is older than the cutoff" onclick="retry('${s.id}')">⏵ Ingest anyway</button>`;
  else if (canRetry) primary = `<button class="small primary" onclick="retry('${s.id}')">Retry</button>`;
  else if (s.status === 'ready') primary = s.analysed
    ? `<button class="small primary" title="Everything this source gave the project: findings, the Claims they became, where it was used, how fresh it is" onclick="sourceDrawer('${s.id}')">What this gave</button>`
    : `<button class="small primary" title="Reads this source with the model to extract findings — uses your model budget" onclick="suggestSource('${s.id}')">Suggest findings</button>`;

  // Rare, source-type-specific and already high-value when present — F0 addendum 4's bulk-review baseline is why
  // these stay a second visible control instead of folding into the overflow with the genuinely rare ones.
  let special = '';
  if (s.status === 'ready' && s.platform === 'spreadsheet') special = `<button class="small primary" onclick="openCalc('${s.id}')">🧮 Calculator</button>`;
  const allVideos = s.video_embeds || [], doneVideos = s.video_embeds_added || [], leftVideos = allVideos.filter(v => !doneVideos.includes(v));
  if (s.status === 'ready' && leftVideos.length) special += `<button class="small primary" title="This page embeds ${leftVideos.length} video (${esc(leftVideos.map(v => v.replace(/^https?:\/\/(www\.)?/, '').slice(0, 40)).join(', '))}). Adding it downloads and transcribes it, which costs money — the page's own notes were free." onclick="addPageVideos('${s.id}', ${leftVideos.length})">🎬 Add the ${leftVideos.length} video${leftVideos.length === 1 ? '' : 's'} on this page</button>`;
  else if (s.status === 'ready' && allVideos.length) special += `<span class="tag" title="${esc(doneVideos.join(', '))}">🎬 ${doneVideos.length} video${doneVideos.length === 1 ? '' : 's'} from this page added</span>`;
  if (s.status === 'ready' && s.long && s.depth === 'deep') special += `<span class="tag" title="This source was read with Read deeper: smaller windows, every specific finding kept">🔬 deep-read</span>`;

  const items = [];
  if (s.status === 'ready') {
    if (s.analysed) items.push(`<button onclick="suggestSource('${s.id}')" title="Reads this source with the model to extract findings again — uses your model budget">Suggest findings</button>`);
    else items.push(`<button onclick="sourceDrawer('${s.id}')" title="Everything this source gave the project: findings, the Claims they became, where it was used, how fresh it is">What this gave</button>`);
    items.push(`<button onclick="viewTranscript('${s.id}')">${s.platform === 'spreadsheet' ? 'Contents' : s.platform === 'book' ? '📖 Read' : 'Transcript'}</button>`);
    if (s.platform === 'image') items.push(`<button title="Read the picture again with the model instead of the free local OCR. Costs a small amount, and is worth it when the free read missed labels or small type. Text already stored is never replaced by a shorter read." onclick="readImageAgain('${s.id}')">👁 Read again with the model</button>`);
    if (s.long && s.depth !== 'deep') items.push(`<button title="A long-form source. Reads it again in smaller parts with a depth instruction and keeps every specific finding (books, courses, podcasts, long interviews). $0 on Claude Code; API cost otherwise." onclick="readDeeper('${s.id}')">🔬 Read deeper</button>`);
  }
  if (!canRetry && !needsBrowser && (s.status === 'failed' || s.status === 'pending')) items.push(`<button onclick="retry('${s.id}')">Retry</button>`);
  items.push(`<button title="${s.priority ? 'Stop favouring this source in answers' : 'Favour this source in answers (a top-tier / authoritative source for this project)'}" onclick="setPriority('${s.id}', ${s.priority ? 'false' : 'true'})">${s.priority ? '★ Priority' : '☆ Make priority'}</button>`);
  items.push(`<button onclick="removeFromProject('${s.id}')">Remove from project</button>`);
  items.push(`<div style="border-top:1px solid var(--line);margin:4px 0"></div>`);
  items.push(`<button class="danger" onclick="delSource('${s.id}')">Delete everywhere</button>`);

  return `<div class="actions">${primary}${special}<button class="small ghost" onclick="toggleMenu(this)" aria-label="More actions for this source" title="More actions">⋯</button><div class="menu" hidden>${items.join('')}</div></div>`;
}
globalThis.toggleMenu = function toggleMenu(btn) {
  const m = btn.nextElementSibling; if (!m || !m.classList.contains('menu')) return;
  const willOpen = m.hidden;
  document.querySelectorAll('.menu').forEach(x => { if (x !== m) x.hidden = true; });
  m.hidden = !m.hidden;
  if (willOpen) setTimeout(() => document.addEventListener('click', function h(e) { if (!m.contains(e.target) && e.target !== btn) { m.hidden = true; document.removeEventListener('click', h); } }), 0);
}
globalThis.renderSourceList = function renderSourceList() {
  const rows = SRCG.rows;
  const empty = '<div class="empty">No sources yet. Add a link, upload a file, paste text, or pull from the library above.</div>';
  const grouping = $('#srcGroupToggle') ? $('#srcGroupToggle').checked : true;
  if (!rows.length) { $('#srcGroupCtl').hidden = true; $('#srcList').innerHTML = empty; SRCG.keys = []; return; }
  if (!grouping) { $('#srcGroupCtl').hidden = true; $('#srcList').innerHTML = rows.map(srcRowHtml).join(''); SRCG.keys = []; return; }
  const groups = {};
  rows.forEach(s => { const k = srcGroupKey(s); (groups[k] = groups[k] || []).push(s); });
  // Kyle, live: "the grouped items don't sort properly if I am sorting by newest — it should also move the groups".
  // Right: a sort the user chose has to order the GROUPS too, or the newest source is buried three groups down.
  // `rows` is already sorted, so first appearance IS the group order under whatever sort is active. Only the
  // default (activity) view keeps the size ordering, where "the biggest channel first" is the useful shape.
  const sortSel = $('#srcSort') ? $('#srcSort').value : 'default';
  const seen = [];
  rows.forEach(s => { const k = srcGroupKey(s); if (!seen.includes(k)) seen.push(k); });
  const keys = sortSel === 'default'
    ? Object.keys(groups).sort((a, b) => groups[b].length - groups[a].length || a.localeCompare(b))
    : seen;
  if (keys.length <= 1) { $('#srcGroupCtl').hidden = true; $('#srcList').innerHTML = rows.map(srcRowHtml).join(''); SRCG.keys = []; return; }
  if (SRCG.collapsed === 'all') SRCG.collapsed = new Set(keys);
  // a search or an active chip/value filter means the user is hunting for something specific — never hide a match
  const searching = !!($('#srcQ') && $('#srcQ').value) || Object.values(state.srcFilters || {}).some(Boolean);
  $('#srcGroupCtl').hidden = false;
  SRCG.byKey = groups;
  const wrap = $('#srcList');
  // build each group's content once; a CLOSED group builds nothing at all (see srcGroupToggled)
  const built = keys.map(k => {
    const open = searching || !SRCG.collapsed.has(k);
    return { k, open, n: groups[k].length, content: open ? groups[k].map(srcRowHtml).join('') : '' };
  });
  const sameShape = SRCG.keys.length === keys.length && SRCG.keys.every((k, i) => k === keys[i])
                    && wrap.children.length === keys.length;
  if (!sameShape) {
    wrap.innerHTML = built.map(b => {
      const keyJs = JSON.stringify(b.k).replace(/"/g, '&quot;');
      return `<details class="fgroup" data-k="${esc(b.k)}" ${b.open ? 'open' : ''} ontoggle="srcGroupToggled(${keyJs}, this.open)">`
           + `<summary class="gh"><b>${esc(b.k)}</b><span>${b.n} source${b.n === 1 ? '' : 's'}</span></summary>`
           + `<div class="grows">${b.content}</div></details>`;
    }).join('');
  } else {
    // patch in place: only the groups whose rendered rows actually differ are touched, so an unchanged group keeps
    // its DOM (and the page keeps its scroll position) while a job ticking away in one group still updates live.
    built.forEach((b, i) => {
      const el = wrap.children[i];
      if (!el) return;
      if (el.open !== b.open) el.open = b.open;
      if (SRCG.html.get(b.k) !== b.content) {
        const box = el.querySelector('.grows');
        if (box) box.innerHTML = b.content;
        const cnt = el.querySelector('summary span');
        if (cnt) cnt.textContent = `${b.n} source${b.n === 1 ? '' : 's'}`;
      }
    });
  }
  SRCG.keys = keys;
  SRCG.html = new Map(built.map(b => [b.k, b.content]));
}
globalThis.loadSources = async function loadSources() {
  loadReviews();
  loadCaptionRecovery();
  const p = new URLSearchParams({ project_id: state.project.id, limit: 2000 }); if ($('#srcQ').value) p.set('q', $('#srcQ').value);
  if (!SRCG.loaded) $('#srcList').innerHTML = listState('loading', { label: 'Loading sources…' });
  let all; try { all = await api('/api/sources?' + p); } catch (e) { $('#srcList').innerHTML = listState('failed', { message: "Couldn't load sources.", retry: 'loadSources()' }); return; }
  SRCG.loaded = true;
  const nReady = all.filter(r => r.status === 'ready').length;
  $('#nSources').textContent = nReady;
  if (FUN.n !== undefined && FUN.n !== nReady) loadFun(state.view === 'sources' ? 'srcFun' : null);   // a new source landed: fresh numbers, fresh comparison
  // group: what is being worked on right now floats to the top, then failures, then the rest (newest first)
  const needsBrowser = s => !!(s.acquisition && s.acquisition.state === 'requires_browser');
  const bucket = s => needsBrowser(s) ? 1 : (s.status === 'pending' || s.analysing) ? 0 : s.status === 'failed' ? 1 : s.status === 'ready' ? 2 : 3;
  const counts = { working: all.filter(s => bucket(s) === 0).length, failed: all.filter(s => s.status === 'failed').length, browser: all.filter(needsBrowser).length,
                   ready: all.filter(s => s.status === 'ready').length, skipped: all.filter(s => s.status === 'skipped').length, deep: all.filter(s => s.status === 'ready' && s.long).length };
  const chips = [['all', 'All', all.length], ['working', '⟳ Working on', counts.working], ['browser', '🌐 Browser needed', counts.browser], ['failed', '✕ Failed', counts.failed], ['ready', '✓ Ready', counts.ready], ['deep', '📚 Deep content', counts.deep], ['skipped', 'Skipped', counts.skipped], ['pool', '🔎 Known, not captured', POOL.total ?? '…']];
  if (state.srcFilter === 'pool') { $('#srcChips').innerHTML = chips.filter(([k, , n]) => k === 'all' || n).map(([k, l, n]) => `<span class="chipf ${state.srcFilter === k ? 'on' : ''}" onclick="state.srcFilter='${k}';loadSources()">${l} <b>${n}</b></span>`).join(''); return loadPool(); }
  if (POOL.total == null) api(`/api/projects/${state.project.id}/pool?limit=1`).then(r => { POOL.total = r.total; }).catch(() => {});
  loadCaptureQueue(all.filter(needsBrowser));
  $('#srcChips').innerHTML = chips.filter(([k, , n]) => k === 'all' || n).map(([k, l, n]) => `<span class="chipf ${state.srcFilter === k ? 'on' : ''}" onclick="state.srcFilter='${k}';loadSources()">${l} <b>${n}</b></span>`).join('');
  const f = state.srcFilter || 'all';
  // S2: composable value filters (AND), a length band and a sort — every one a column on the row, no model calls
  const F = state.srcFilters || {};
  const lenBand = $('#srcLen') ? $('#srcLen').value : '', sortBy = $('#srcSort') ? $('#srcSort').value : 'default';
  const inBand = s => !lenBand || (lenBand === 'books' ? ['book', 'document', 'spreadsheet', 'file'].includes(s.platform) : lenBand === 'short' ? (s.duration || 0) > 0 && s.duration < 900 : lenBand === 'mid' ? s.duration >= 900 && s.duration < 2700 : lenBand === 'long' ? (s.duration || 0) >= 2700 : true);
  const v = s => s.value || {};
  const passes = s => (!F.matters || v(s).matters) && (!F.stale || v(s).stale) && (!F.priority || s.priority) && (!F.under_read || s.under_read) && (!F.deep || s.depth === 'deep')
    && (!F.nothing || (s.status === 'ready' && s.analysed && !s.approved)) && (!F.unused || (s.status === 'ready' && v(s).never_used)) && inBand(s);
  document.querySelectorAll('#srcFilters .chipf').forEach(c => c.classList.toggle('on', !!F[c.dataset.f]));
  const activeF = Object.keys(F).filter(k => F[k]);
  $('#srcFilterNote').textContent = activeF.length || lenBand ? `${all.filter(passes).length} match` : '';
  const sorter = (a, b) => sortBy === 'value' ? (v(b).score || 0) - (v(a).score || 0) || (b.approved || 0) - (a.approved || 0)
    : sortBy === 'unused' ? ((v(a).used && (v(a).used.plan_evidence + v(a).used.chat_citations)) || 0) - ((v(b).used && (v(b).used.plan_evidence + v(b).used.chat_citations)) || 0) || (v(a).score || 0) - (v(b).score || 0)
    : sortBy === 'longest' ? (b.duration || 0) - (a.duration || 0) : sortBy === 'newest' ? (b.published_at || '').localeCompare(a.published_at || '') : sortBy === 'title' ? (a.title || '').localeCompare(b.title || '')
    : f === 'deep' ? ((b.under_read ? 1 : 0) - (a.under_read ? 1 : 0)) || ((b.duration || 0) - (a.duration || 0)) : bucket(a) - bucket(b) || (b.updated_at || 0) - (a.updated_at || 0);
  const rows = all.filter(s => f === 'all' || (f === 'working' ? bucket(s) === 0 : f === 'browser' ? needsBrowser(s) : f === 'deep' ? (s.status === 'ready' && s.long) : s.status === f && !needsBrowser(s))).filter(passes).sort(sorter);
  const underRead = f === 'deep' ? rows.filter(s => s.under_read) : [];
  $('#srcCount').innerHTML = `${rows.length}${f !== 'all' ? ' of ' + all.length : ''} source${all.length === 1 ? '' : 's'}` +
    (f === 'deep' ? ` <span class="muted">· books, courses, podcasts and interviews over 45 min · ${underRead.length} under-read (read once, ≤ ${12} findings)</span>` + (underRead.length ? ` <button class="small primary" title="Reads each under-read long source again in smaller parts and keeps every specific finding. $0 on Claude Code (slow); API cost otherwise." onclick="readDeeperAll(${JSON.stringify(underRead.map(s => s.id))})">🔬 Read deeper on all ${underRead.length}</button>` : '') : '') +
    (f === 'skipped' && rows.length ? ` <button class="small" onclick="ingestSkipped()">⏵ Ingest all ${rows.length} anyway</button>` : '') +
    (f === 'skipped' && rows.some(s => !s.thumbnail_url) ? ` <button class="small ghost" title="Re-fetches metadata only (no download, stays skipped) for skipped sources with no thumbnail yet — catches up rows skipped before this was fixed." onclick="refreshSkippedMeta()">🔄 Refresh info</button>` : '') +
    (f === 'failed' && rows.length > 1 ? ` <button class="small" onclick="retryAllSources()">↻ Retry all ${rows.length}</button>` : '') +
    (f === 'failed' && rows.length ? ` <button class="small danger" onclick="clearFailedSources()">✕ Clear all failed</button>` : '') +
    // music-only shorts/reels: the audio said nothing, but the caption often holds the substance
    (capRecover.n ? ` <button class="small ghost" title="${capRecover.n} source${capRecover.n === 1 ? '' : 's'} said nothing out loud but carry real text in the caption — read that text so they can produce findings. No download, no re-transcription." onclick="recoverCaptions()">💬 Read ${capRecover.n} caption-only source${capRecover.n === 1 ? '' : 's'}</button>` : '');
  SRCG.rows = rows;
  renderSourceList();
}
globalThis.setPriority = async function setPriority(id, flag) {
  await put(`/api/projects/${state.project.id}/priority`, { source_ids: [id], priority: flag });
  loadSources();
}
globalThis.viewTranscript = async function viewTranscript(id, ordinal) {
  const s = await api('/api/sources/' + id);
  const isDoc = s.platform === 'document', isWeb = s.platform === 'web', isSheet = s.platform === 'spreadsheet';
  const link = t => s.platform === 'youtube' ? `${s.url}${s.url.includes('?') ? '&' : '?'}t=${Math.floor(t)}s` : (isWeb ? s.url : null);
  const secLabel = s.platform === 'book' ? Object.fromEntries((s.sections || []).map(x => [x.ordinal, x.label])) : null;
  const lab = t => secLabel ? (secLabel[Math.round(t)] || `section ${Math.round(t)}`) : isDoc ? `p. ${Math.round(t)}` : isWeb ? `§ ${Math.round(t)}` : isSheet ? `sheet ${Math.round(t)}` : fmt(t);
  if (s.platform === 'book') { renderBook(s, ordinal); return; }
  $('#dlgBody').innerHTML = `<b>${esc(s.title)}</b> <a class="muted" href="/api/sources/${id}/transcript.txt" target="_blank">download .txt</a>
    <div class="transcript">${s.segments.map(g => (link(g.start) ? `<a href="${esc(link(g.start))}" target="_blank"><b>[${lab(g.start)}]</b></a>` : `<b>[${lab(g.start)}]</b>`) + ' ' + esc(g.text)).join('\n')}</div>`;
  dlg.showModal();
}
// ---- G6P2: the book reader — Contents tree (chapters → sections, roles) beside the text; a citation opens the book at its section
globalThis.ROLE_LABEL = { title_page: 'title page', copyright: 'copyright', foreword: 'foreword', preface: 'preface', introduction: 'introduction', part: 'part', chapter: 'chapter', appendix: 'appendix', notes: 'notes', bibliography: 'bibliography', glossary: 'glossary', index: 'index', acknowledgements: 'acknowledgements', epilogue: 'epilogue', prologue: 'prologue', back_matter: 'back matter', front_matter: 'front matter' };
globalThis.renderBook = function renderBook(s, ordinal) {
  const secs = s.sections || [], text = Object.fromEntries((s.segments || []).map(g => [Math.round(g.start), g.text]));
  const chapters = []; for (const x of secs) { const last = chapters[chapters.length - 1]; if (!last || last.spine !== x.spine_index) chapters.push({ spine: x.spine_index, title: x.chapter, no: x.chapter_no, role: x.role, secs: [] }); chapters[chapters.length - 1].secs.push(x); }
  const meta = [s.channel, s.published_at, s.description].filter(Boolean).map(esc).join(' · ');
  $('#dlgBody').innerHTML = `<b>📖 ${esc(s.title)}</b> <span class="muted">${meta}</span> <a class="muted" href="/api/sources/${s.id}/transcript.txt" target="_blank">download .txt</a>
    <div style="display:flex;gap:14px;margin-top:8px;min-height:50vh">
      <div style="width:260px;flex:none;overflow:auto;max-height:65vh;border-right:1px solid var(--line);padding-right:8px;font-size:12.5px"><div class="muted mb-1">Contents</div>
        ${chapters.map(c => `<div style="margin:4px 0"><a href="#" onclick="bookGo(${c.secs[0].ordinal});return false"><b>${c.no ? 'Ch. ' + c.no + ' · ' : ''}${esc(c.title || '')}</b></a>${c.role && c.role !== 'body' && c.role !== 'chapter' ? ` <span class="muted">(${esc(ROLE_LABEL[c.role] || c.role)})</span>` : ''}${c.secs.length > 1 ? c.secs.slice(1).filter(x => x.section).map(x => `<div style="padding-left:12px"><a href="#" onclick="bookGo(${x.ordinal});return false">${esc(x.section)}</a></div>`).join('') : ''}</div>`).join('')}</div>
      <div id="bookText" class="transcript" style="flex:1;max-height:65vh;overflow:auto">${secs.map(x => `<div id="sec-${x.ordinal}" style="margin-bottom:14px"><b>[${esc(x.label)}]</b>${x.role && !['body', 'chapter', 'part', 'introduction'].includes(x.role) ? ` <span class="muted">${esc(ROLE_LABEL[x.role] || x.role)}</span>` : ''}<div>${esc(text[x.ordinal] || '')}</div></div>`).join('')}</div>
    </div>`;
  dlg.showModal();
  if (ordinal) setTimeout(() => bookGo(ordinal), 50);
}
globalThis.bookGo = function bookGo(ordinal) { const el = document.getElementById('sec-' + ordinal); if (!el) return; el.scrollIntoView({ block: 'start' }); el.style.background = 'var(--user)'; setTimeout(() => el.style.background = '', 1500); }
// a citation link of the form #book/<source_id>/<ordinal> (search hits, findings, chat) opens the book at that section
document.addEventListener('click', e => { const a = e.target.closest && e.target.closest('a[href^="#book/"]'); if (!a) return; e.preventDefault(); const [, sid, ord] = a.getAttribute('href').split('/'); viewTranscript(sid, +ord); });
globalThis.openCalc = async function openCalc(id) {
  const m = await api(`/api/sources/${id}/calculator`);
  const fmtv = v => typeof v === 'number' ? (Math.abs(v) >= 1000 ? v.toLocaleString(undefined, { maximumFractionDigits: 2 }) : +v.toFixed(4)) : esc(String(v ?? ''));
  $('#dlgBody').innerHTML = `<b>🧮 ${esc(m.file)}</b> <span class="muted">— change any input, then Recalculate. The workbook's own formulas do the maths. In chat you can just ask: "run the calculator with price 800k".</span>
    <div class="calcgrid" style="margin-top:10px"><div><div class="starth">Inputs</div>${m.inputs.map((i, n) => `<label class="ci"><span title="${esc(i.cell)}">${esc(i.label)}</span><input data-cell="${esc(i.cell)}" value="${esc(String(i.value))}"></label>`).join('') || '<div class="muted">No labelled inputs found.</div>'}
      <button class="primary mt-2" onclick="runCalc('${id}')">Recalculate</button> <span class="muted" id="calcMsg"></span></div>
    <div><div class="starth">Outputs</div><div id="calcOut">${m.outputs.map(o => `<div class="co"><span title="${esc(o.cell)} ${esc(o.formula || '')}">${esc(o.label)}</span><b>${fmtv(o.value)}</b></div>`).join('') || '<div class="muted">No formula outputs found.</div>'}</div></div></div>`;
  dlg.showModal();
}
globalThis.runCalc = async function runCalc(id) {
  const inputs = {}; document.querySelectorAll('#dlgBody .ci input').forEach(i => { if (i.value !== '') inputs[i.dataset.cell] = i.value; });
  $('#calcMsg').innerHTML = '<span class="spin"></span>';
  try {
    const r = await post(`/api/sources/${id}/calculate`, { inputs });
    const fmtv = v => typeof v === 'number' ? (Math.abs(v) >= 1000 ? v.toLocaleString(undefined, { maximumFractionDigits: 2 }) : +v.toFixed(4)) : esc(String(v ?? ''));
    $('#calcOut').innerHTML = Object.entries(r.outputs).map(([k, v]) => `<div class="co"><span>${esc(k)}</span><b>${fmtv(v)}</b></div>`).join('');
    $('#calcMsg').textContent = r.unknown_inputs?.length ? 'ignored: ' + r.unknown_inputs.join(', ') : '✓';
  } catch (e) { $('#calcMsg').textContent = 'error: ' + e.message; }
}
// S5: the known-but-uncaptured pool — skipped (pre-cutoff) sources + Candidate Index rows, ranked by a $0 potential scan
globalThis.POOL = { total: null, rank: 'fit', kind: 'all' };
globalThis.loadPool = async function loadPool() {
  const p = new URLSearchParams({ rank_by: POOL.rank, kind: POOL.kind, limit: 150 }); if ($('#srcQ').value) p.set('q', $('#srcQ').value);
  let r; try { r = await api(`/api/projects/${state.project.id}/pool?` + p); } catch (e) { $('#srcList').innerHTML = '<div class="muted">could not load the pool</div>'; return; }
  POOL.total = r.total;
  const c = r.counts;
  $('#srcCount').innerHTML = `${r.total} known, not captured <span class="muted">· ${c.skipped} skipped at the date cutoff · ${c.candidates} seen while exploring · <b>${c.worth_a_look}</b> worth a look · ${c.fits_a_question} fit an open question</span>` +
    (c.worth_a_look ? ` <button class="small primary" onclick="captureManyPool()" title="Captures every item at or above 'worth a look' (potential ≥ 40) in your current rank/show filter — same as clicking Capture on each one">Capture the ${c.worth_a_look} that fit</button>` : '');
  $('#srcFilterNote').textContent = '';
  const pot = v => `<span class="fi" title="potential ${v}/100 — a $0 scan of the title and description against your open questions, weak areas and the project's own words">${'●'.repeat(Math.round(v / 20))}<span class="dim">${'●'.repeat(5 - Math.round(v / 20))}</span></span>`;
  $('#srcList').innerHTML = `<div class="row" style="gap:6px;margin:4px 0 10px;font-size:12.5px"><span class="muted">${esc(r.explain)}</span></div>
    <div class="row" style="gap:6px;margin-bottom:8px;font-size:12.5px"><span class="muted">Rank by:</span>
      ${[['fit', 'fits my open questions'], ['relevance', 'review score'], ['creator', 'same creator as a priority source'], ['newest', 'newest']].map(([k, l]) => `<span class="chipf ${POOL.rank === k ? 'on' : ''}" onclick="POOL.rank='${k}';loadPool()">${l}</span>`).join('')}
      <span class="muted" style="margin-left:10px">Show:</span>${[['all', 'all'], ['skipped', 'skipped at cutoff'], ['candidates', 'seen while exploring']].map(([k, l]) => `<span class="chipf ${POOL.kind === k ? 'on' : ''}" onclick="POOL.kind='${k}';loadPool()">${l}</span>`).join('')}</div>` +
    (r.items.map(i => `<div class="src"><div class="ico">${i.kind === 'skipped' ? '⏭' : '👁'}</div><div class="grow min-w-0">
      <div class="t">${pot(i.potential)} ${i.url && i.url.startsWith('http') ? `<a href="${esc(i.url)}" target="_blank">${esc(i.title)}</a>` : esc(i.title)}${i.same_creator_as_priority ? ' <span class="tag" title="same creator as one of your ★ priority sources">★ creator</span>' : ''}</div>
      <div class="muted">${esc(i.creator || i.platform)} ${i.published_at ? '· ' + esc(i.published_at) : ''} ${i.duration ? '· ' + fmt(i.duration) : ''} · <span title="how Neuro Search knows about it">${esc(i.why_known)}</span></div>
      ${i.fits ? `<div class="muted" style="margin-top:2px">fits: <b>${esc(String(i.fits))}</b></div>` : ''}
      ${i.why.length ? `<div class="muted" style="font-size:12px;margin-top:2px">${esc(i.why.join(' · '))}</div>` : ''}
      <div class="actions"><button class="small primary" onclick="poolAct(${JSON.stringify(i.actions.capture).replace(/"/g, '&quot;')}, '${esc(i.title).replace(/'/g, '')}')">${esc(i.actions.capture.label)}</button><button class="small ghost" onclick="poolAct(${JSON.stringify(i.actions.dismiss).replace(/"/g, '&quot;')})">${esc(i.actions.dismiss.label)}</button></div>
    </div></div>`).join('') || '<div class="muted">Nothing known but uncaptured — every seen source is either in the project or dismissed.</div>');
}
globalThis.poolAct = async function poolAct(a, title) {
  if (a.method === 'DELETE') await del(a.endpoint, a.body || {}); else await post(a.endpoint, a.body || {});
  toast(a.label === 'Not for this project' ? 'dismissed' : `⏵ capturing${title ? ' — ' + title.slice(0, 40) : ''}`); POOL.total = null; loadPool(); loadJobs();
}
globalThis.captureManyPool = async function captureManyPool() {
  if (!confirm(`Capture every item at or above 'worth a look' in the current filter (rank: ${POOL.rank}, show: ${POOL.kind})? Each one goes through the same path as clicking Capture by hand — attached instantly if you already own it, otherwise queued as a normal ingest.`)) return;
  const r = await post(`/api/projects/${state.project.id}/pool/capture-many`, { rank_by: POOL.rank, kind: POOL.kind, q: $('#srcQ').value || null, min_potential: 40, limit: 20 });
  toast(r.captured ? `⏵ ${r.line}${r.available_above_threshold > r.considered ? ` · ${r.available_above_threshold - r.considered} more met the threshold — run it again for the rest` : ''}` : r.line);
  POOL.total = null; loadPool(); loadJobs();
}
globalThis.toggleSrcFilter = function toggleSrcFilter(k) { state.srcFilters = state.srcFilters || {}; state.srcFilters[k] = !state.srcFilters[k]; loadSources(); }
// L3: the local provider is slow on purpose — buying speed is an explicit choice, never implied by slowness
// Kyle, live 2026-09-09: "I am not sure what the buttons on this progress bar do or what the risks/costs are."
// Fair — they were labelled "next 10" beside a banner that says $0, with the price hidden in a hover title and a
// confirm dialog. A button that spends money says so on its face. Each one now carries its own estimated cost and
// the time it buys, computed from the same per-job numbers the purchase itself uses.
globalThis.accelEstimate = function accelEstimate(b, n, order) {
  const js = order === 'value' ? [...b.jobs].sort((x, y) => (y.value || 0) - (x.value || 0)) : b.jobs;
  const pick = js.slice(0, n);
  const cost = pick.reduce((t, j) => t + (j.api_cost || 0), 0);
  const w = pick.reduce((t, j) => t + (j.windows || 0), 0);
  const mins = b.windows && b.local_minutes ? Math.round(b.local_minutes * (w / b.windows)) : null;
  return { cost, mins, n: pick.length };
}
globalThis.accelMins = function accelMins(m) { return m == null ? '' : m >= 60 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${m} min`; }
globalThis.loadBacklog = async function loadBacklog() {
  const el = $('#backlog'); if (!el || !state.project) return;
  let b; try { b = await api(`/api/projects/${state.project.id}/ai-backlog`); } catch (e) { el.innerHTML = ''; return; }
  if (!b.local_queued || !b.local_ready) { el.innerHTML = ''; return; }
  state.backlog = b;
  const btn = (n, order, label) => {
    const e = accelEstimate(b, n, order);
    return `<button class="small ${order === 'value' ? 'ghost' : (n === b.choices[0] ? '' : 'ghost')}" onclick="accelerate(${n},'${order}')" title="Moves ${e.n} queued job${e.n === 1 ? '' : 's'} onto the paid Anthropic API. Same work, same quality — you are buying time, not a different answer. The rest stay on Claude Code at $0.">${label} · ~$${e.cost.toFixed(2)}${e.mins ? ` · saves ~${accelMins(e.mins)}` : ''}</button>`;
  };
  // 0.59.2: one button per genuinely DIFFERENT set, each with its own criterion and its own price. The old dialog
  // offered "next N" alongside "all N, most valuable first" — and when N was everything, sorting bought the same
  // thing twice under two names. The server now computes the sets and collapses duplicates, so the UI just renders
  // whatever distinct purchases actually exist.
  const opts = b.options || [];
  const picks = opts.map((o, i) => `<button class="small ${i === 0 ? '' : 'ghost'}" onclick="accelerateOption('${o.key}')" title="${esc(o.why)} Same work, same quality — you are buying time, not a different answer. Whatever you don't move keeps running on Claude Code at $0.">⏩ ${esc(o.label)} · ~$${o.api_cost.toFixed(2)}</button>`).join('');
  const pools = b.pools || {};
  el.innerHTML = `<div class="banner" style="display:block">
    <div>🖥 ${esc(b.line)}. Nothing is stuck — this is Claude Code working through the queue at $0.</div>
    ${pools.api_idle_by_construction ? `<div class="muted" style="font-size:12px;margin:6px 0 0">${pools.local_workers} local worker${pools.local_workers === 1 ? '' : 's'} on ${pools.local_queued} job${pools.local_queued === 1 ? '' : 's'}; the API worker is idle and <b>cannot help with this backlog</b> until you move some of it across. ${esc(pools.why)}</div>` : ''}
    <div class="muted" style="font-size:12px;margin:6px 0 4px">Optional: pay to skip the wait. Each button below moves a different set of jobs onto the paid API — same work and same quality. Nothing is cancelled or redone.</div>
    <div style="display:flex;gap:8px;flex-wrap:wrap">${picks || '<span class="muted">nothing worth moving</span>'}</div></div>`;
}
// 0.59.2: buy exactly the set the button named — the server priced it, so the confirmation cannot drift from it.
globalThis.accelerateOption = async function accelerateOption(key) {
  const b = await api(`/api/projects/${state.project.id}/ai-backlog`);
  const o = (b.options || []).find(x => x.key === key);
  if (!o) return toast('that option is no longer available — the queue changed');
  const u = state.usage || {};
  const budget = u.daily_budget ? `\n• Counts toward today's budget: $${(u.today || 0).toFixed(2)} of $${u.daily_budget.toFixed(2)} used so far.` : '';
  if (!confirm(`${o.label} — run ${o.n} job${o.n === 1 ? '' : 's'} on the paid Anthropic API instead of waiting for Claude Code?`
    + `\n\n• ${o.why}`
    + `\n• Estimated cost: about $${o.api_cost.toFixed(2)}.`
    + `\n• Same work and the same quality — you are buying time, not a different answer.`
    + `\n• The other ${b.local_queued - o.n} job${b.local_queued - o.n === 1 ? '' : 's'} keep running on Claude Code at $0.`
    + budget)) return;
  const r = await post(`/api/projects/${state.project.id}/accelerate`, { option: key });
  toast(`⏩ ${r.moved} job${r.moved === 1 ? '' : 's'} moved to the API · ~$${(r.api_cost || 0).toFixed(2)}`);
  loadJobs(); loadBacklog();
}
globalThis.accelerate = async function accelerate(n, order) {
  const b = await api(`/api/projects/${state.project.id}/ai-backlog`);
  const e = accelEstimate(b, n, order);
  const u = state.usage || {};
  const budget = u.daily_budget ? `\n• Counts toward today's budget: $${(u.today || 0).toFixed(2)} of $${u.daily_budget.toFixed(2)} used so far.` : '';
  const left = b.local_queued - e.n;
  if (!confirm(`Run ${e.n} queued job${e.n === 1 ? '' : 's'} on the paid Anthropic API instead of waiting for Claude Code?`
    + `\n\n• Estimated cost: about $${e.cost.toFixed(2)}.`
    + (e.mins ? `\n• Saves about ${accelMins(e.mins)} of waiting.` : '')
    + `\n• Same work and the same quality — you are buying time, not a different answer.`
    + (order === 'value' ? `\n• The sources that matter most go first (in the plan, priority, strong Claims, findings you rated 4–5).` : '')
    + budget
    + `\n• This cannot be undone once they start.`
    + (left > 0 ? `\n• The other ${left} keep running on Claude Code at $0.` : ''))) return;
  const r = await post(`/api/projects/${state.project.id}/accelerate`, { n, order });
  toast(`⏩ ${r.moved} moved to the API · est. $${r.api_cost.toFixed(2)}`); loadJobs();
}
globalThis.readDeeperAll = async function readDeeperAll(ids) { if (!confirm(`Read deeper on ${ids.length} long source${ids.length === 1 ? '' : 's'}? Each is re-read in smaller parts (about 3× the model calls of a normal read). Approved findings are kept; suggestions are replaced.`)) return; const r = await post(`/api/projects/${state.project.id}/suggest`, { source_ids: ids, depth: 'deep' }); toast(`🔬 ${r.sources} queued for a deep read`); state.srcFilter = 'working'; loadSources(); loadJobs(); }
// 0.63.4 — the note on an unread image told him to "use 'Read with the model'", and there was no such button
// anywhere in the app. There is now. It asks for the model rung explicitly (engine=model) rather than re-walking
// the ladder, because the reason to press it is that the free rung already read the image and read it badly.
// 0.63.16 — "Send this page" captured a lesson's notes and dropped its Loom video without trace. The embeds are
// recorded at capture time now; adding them is a separate click because a video is a download and a transcription.
globalThis.addPageVideos = async function addPageVideos(id, n) {
  if (!confirm(`Add ${n} embedded video${n === 1 ? '' : 's'} from this page?\n\nThe page's notes were free. A video is downloaded and transcribed, which costs money.`)) return;
  try {
    const r = await post(`/api/projects/${state.project.id}/page-videos`, { source_id: id });
    toast(r.queued ? `🎬 ${r.queued} queued — watch it in Sources` : (r.why || 'nothing to add'));
    loadSources(); loadJobs();
  } catch (e) { toast('could not add the video: ' + e.message); }
}

globalThis.readImageAgain = async function readImageAgain(id) {
  if (!confirm('Read this image again with the model?\n\nThe free local OCR is tried first on upload. This is a paid call — small, but not free — and is worth it when the free read missed labels or small type.')) return;
  try {
    const r = await api(`/api/sources/${id}/read-image?engine=model&project_id=${state.projectId || ''}`, { method: 'POST' });
    if (r.kept) {
      toast(`Kept the ${r.chars} characters already stored — this read found only ${r.read_chars}.`);
    } else if (!r.chars) {
      toast(r.note || 'nothing readable in this image');
    } else {
      toast(`Read ${r.chars} characters with the ${r.engine}.`);
      loadSources();
    }
  } catch (e) { toast('could not read the image: ' + e.message); }
}

globalThis.readDeeper = async function readDeeper(id) { const r = await post(`/api/projects/${state.project.id}/suggest`, { source_ids: [id], depth: 'deep' }); toast('🔬 Reading deeper — findings land in Suggested as each part completes; the card shows deep-read when done'); loadJobs(); }
// 0.63.5 — a source you clicked goes to the front of the queue, so the message can say what will happen rather
// than "in a minute" (the measured median wait for this job was 2.6 hours). alert() blocked the page for it.
globalThis.suggestSource = async function suggestSource(id) {
  const r = await post(`/api/projects/${state.project.id}/suggest`, { source_ids: [id] });
  toast(r.lane === 'priority' ? '📌 Next in the queue — suggestions land in Findings when it finishes'
        : '📌 Queued — suggestions appear in Findings when it runs');
  loadJobs();
}
globalThis.ingestSkipped = async function ingestSkipped() { if (!confirm('Queue every skipped video regardless of the date cutoff?')) return; const r = await post('/api/sources/retry-skipped', { project_id: state.project.id }); toast(`⏵ ${r.queued} queued`); state.srcFilter = 'working'; loadSources(); loadJobs(); }
globalThis.capRecover = { n: 0 };
globalThis.loadCaptionRecovery = async function loadCaptionRecovery() {
  try { capRecover.n = (await api(`/api/projects/${state.project.id}/sources/caption-recovery`)).count || 0; }
  catch (e) { capRecover.n = 0; }
}
globalThis.recoverCaptions = async function recoverCaptions() {
  const r = await post(`/api/projects/${state.project.id}/sources/caption-recovery`, {});
  toast(r.queued ? `💬 ${r.queued} queued — reading their captions` : 'nothing to recover');
  capRecover.n = 0; loadJobs();
}
globalThis.refreshSkippedMeta = async function refreshSkippedMeta() { const r = await post(`/api/projects/${state.project.id}/sources/refresh-skipped-metadata`, {}); toast(r.queued ? `🔄 ${r.queued} queued — thumbnails and the value scan catch up as each finishes` : 'nothing missing a thumbnail'); loadJobs(); }
globalThis.clearFailedSources = async function clearFailedSources() {
  if (!confirm('Remove every failed source from this project? Jobs that could bring them back are cancelled; sources nothing else uses are deleted. Sources cited in findings or held by other projects are only removed from this project.')) return;
  const r = await post('/api/sources/clear-failed-in-project', { project_id: state.project.id });
  toast(`✕ ${r.cleared} cleared (${r.deleted} deleted, ${r.excluded} removed from this project, ${r.jobs_cancelled} job${r.jobs_cancelled === 1 ? '' : 's'} cancelled)`);
  state.srcFilter = 'all'; loadSources(); loadJobs();
}
globalThis.retryAllSources = async function retryAllSources() { const r = await post('/api/sources/retry-failed-in-project', { project_id: state.project.id }); toast(`↻ ${r.queued} queued`); state.srcFilter = 'working'; loadSources(); loadJobs(); }
globalThis.retry = async function retry(id) { await post(`/api/sources/${id}/retry`); loadSources(); loadJobs(); }
// ---- B1/B2: browser-assisted acquisition + completeness ----
globalThis.EXT = { state: 'unknown' };
globalThis.CAPTURE_SEEN = null;      // job ids waiting at the last poll — a vanished id = a capture landed (B2 walk)
globalThis.CAPTURE_TIMER = null;
globalThis.completenessLine = function completenessLine(s) {
  const c = s.completeness; if (!c || c.status === 'complete' || s.status !== 'ready') return '';
  const what = c.status === 'partial' ? `⚠ Partial capture: ${c.captured} comment${c.captured === 1 ? '' : 's'} captured${c.expected != null ? `, the thread reports ~${c.expected}` : ''}${c.missing ? ` · ${c.missing} may not be loaded` : ''}${c.partial_reason && !c.missing ? ` · ${esc(c.partial_reason)}` : ''}` : `Completeness unknown: ${c.captured} comment${c.captured === 1 ? '' : 's'} captured, no count reported by the platform`;
  return `<div class="muted" style="margin-top:3px;color:var(--warn)">${what}${c.accepted ? ' <span class="muted">· accepted as is</span>' : ''} <button class="small ghost" onclick="recapture('${s.id}')">Reopen and capture more</button>${c.accepted ? '' : ` <button class="small ghost" onclick="acceptPartial('${s.id}')">Accept partial</button>`}</div>`;
}
globalThis.recapture = async function recapture(id) { const r = await post(`/api/sources/${id}/recapture`, { project_id: state.project.id }); $('#captureCard').hidden = false; setTimeout(() => { loadSources(); loadJobs(); }, 1500); }
globalThis.acceptPartial = async function acceptPartial(id) { await post(`/api/sources/${id}/accept-partial`); loadSources(); }
globalThis.browserBlock = function browserBlock(s) {
  const a = s.acquisition || {};
  return `<div style="margin:6px 0;padding:8px 10px;border:1px solid var(--accent);border-radius:8px;background:var(--user)">
    <b>🌐 Browser needed</b>${a.status === 'expired' ? ' <span class="muted">· this request expired — open and capture again</span>' : ''}<div class="muted" style="margin-top:2px">${esc(a.reason || 'Neuro Search could not retrieve this directly. Use your browser to finish capturing it.')}</div>
    <div class="row" style="margin-top:6px;gap:6px;flex-wrap:wrap">
      ${a.job_id ? `<button class="small primary" onclick="openAndCapture('${esc(a.url)}')">Open & Capture</button>` : `<button class="small primary" onclick="retry('${s.id}')">Ask again</button>`}
      <button class="small ghost" onclick="toggleCaptureHelp(this)">How this works</button>
      ${a.job_id ? `<button class="small ghost" onclick="cancelCapture('${a.job_id}')">Cancel</button>` : ''}
      <span class="muted text-xs">${extLine()}</span>
    </div>
    <div class="muted" style="margin-top:6px;font-size:12px" hidden>Open & Capture opens the page in a new tab. The Neuro Search extension recognizes it (its icon shows a blue dot): press the extension button, then <b>Capture for Neuro Search</b>. The page arrives here as the same source — nothing to paste or re-select. No extension yet? Download it from Settings → Extension, load it in chrome://extensions, and pair it with this app's address and password.</div>
  </div>`;
}
// D1: findings extracted beyond the cap ("reserve") — shown inline under the source card, promotable one by one or all at once
globalThis.toggleReserve = async function toggleReserve(sid, a) {
  const box = $(`#reserve-${sid}`); if (!box) return;
  if (!box.hidden) { box.hidden = true; return; }
  box.hidden = false; box.innerHTML = '<span class="muted">loading…</span>';
  const r = await api(`/api/projects/${state.project.id}/notes?status=reserve&source_id=${sid}`);
  const notes = r.notes || [];
  box.innerHTML = `<div class="row" style="margin:6px 0 2px"><span class="muted" style="flex:1;font-size:12px">${notes.length} more extracted (lower importance for this brief). They are not exported or planned on until you promote them.</span>
    <button class="small" onclick="bulkReserve(${JSON.stringify(notes.map(n => n.id))}, 'suggested', '${sid}')">Send all to Suggested</button><button class="small ghost" onclick="bulkReserve(${JSON.stringify(notes.map(n => n.id))}, 'dismissed', '${sid}')">Dismiss all</button></div>` +
    notes.map(n => findingCard(n, `<button class="small primary" title="Keep it — approved findings feed exports, the plan and Claims" onclick="reserveVerdict(${n.id}, 'approved', '${sid}')">✓ Approve</button><button class="small" title="Move it into the review queue to decide later" onclick="reserveVerdict(${n.id}, 'suggested', '${sid}')">📌 To review</button><button class="small ghost" title="Not worth keeping (nothing is deleted — it stays as dismissed)" onclick="reserveVerdict(${n.id}, 'dismissed', '${sid}')">✕ Dismiss</button>`)).join('');
}
globalThis.reserveVerdict = async function reserveVerdict(id, status, sid) { await post(`/api/notes/${id}/status`, { status }); const box = $(`#reserve-${sid}`); if (box) { box.hidden = true; } loadSources(); if (status !== 'dismissed') toast(status === 'approved' ? '✓ approved' : '📌 sent to Suggested'); }
globalThis.bulkReserve = async function bulkReserve(ids, status, sid) { await post('/api/notes/bulk-status', { note_ids: ids, status }); loadSources(); toast(`${ids.length} finding${ids.length === 1 ? '' : 's'} ${status === 'dismissed' ? 'dismissed' : 'sent to Suggested'}`); }
globalThis.extLine = function extLine() { return EXT.state === 'ready' ? '✓ extension ready' : EXT.state === 'stale' ? `extension last seen ${ago(EXT.last_seen)} ago` : EXT.state === 'not_detected' ? '⚠ extension not detected — see How this works' : ''; }
globalThis.toggleCaptureHelp = function toggleCaptureHelp(btn) { const d = btn.parentElement.nextElementSibling; d.hidden = !d.hidden; }
globalThis.openAndCapture = function openAndCapture(url) { window.open(url, '_blank'); }
globalThis.cancelCapture = async function cancelCapture(jobId) { await del(`/api/capture/${jobId}`); loadSources(); loadJobs(); }
globalThis.loadCaptureQueue = async function loadCaptureQueue(rows) {
  try {
    const q = await api(`/api/capture/pending?project_id=${state.project.id}`); globalThis.EXT = q.extension || EXT;
    const items = q.items || [];
    const card = $('#captureCard');
    // B2: a request that vanished since the last poll = a capture landed → show its outcome (complete / partial) and move on
    const now = new Set(items.map(i => i.job_id));
    const landed = CAPTURE_SEEN ? [...CAPTURE_SEEN].filter(([jid]) => !now.has(jid)) : [];
    globalThis.CAPTURE_SEEN = new Map(items.map(i => [i.job_id, i]));
    let outcome = '';
    for (const [, it] of landed) {
      if (!it.source_id) continue;
      try {
        const src = await api(`/api/sources/${it.source_id}`);
        const c = src.completeness ? JSON.parse(src.completeness) : null;
        if (src.status === 'ready') outcome += `<div class="banner" style="margin:4px 0">✓ Captured “${esc(src.title || it.title)}”${c ? ` — ${c.captured} comment${c.captured === 1 ? '' : 's'}` : ''}.${c && c.status === 'partial' ? ` <b>Partial:</b> the thread reports ~${c.expected}; ${c.missing || 0} may not be loaded. <button class="small" onclick="acceptPartial('${src.id}')">Accept partial</button> <button class="small" onclick="recapture('${src.id}')">Reopen and capture more</button>` : c && c.status === 'unknown' ? ' Completeness unknown (no comment count reported).' : ''}</div>`;
        else if (src.status === 'pending') outcome += `<div class="banner" style="margin:4px 0">⟳ Capture received for “${esc(src.title || it.title)}” — finishing…</div>`;
        else outcome += `<div class="banner" style="margin:4px 0">✗ “${esc(src.title || it.title)}”: ${esc(src.error || 'the capture could not be used')}</div>`;
      } catch (e) {}
    }
    if (!items.length) { if (outcome) { card.hidden = false; card.innerHTML = `<b>🌐 Browser capture</b> <span class="muted">· nothing waiting</span>${outcome}`; } else card.hidden = true; clearTimeout(CAPTURE_TIMER); return; }
    card.hidden = false;
    const first = items.find(i => i.status !== 'expired') || items[0];
    card.innerHTML = `<b>🌐 Browser capture</b> <span class="muted">· ${items.length} source${items.length === 1 ? '' : 's'} need${items.length === 1 ? 's' : ''} your browser · ${extLine() || 'extension state unknown'}</span>${outcome}
      <div style="margin:6px 0;padding:8px 10px;border:1px solid var(--accent);border-radius:8px;background:var(--user)"><b>Next — ${items.indexOf(first) + 1} of ${items.length}:</b> ${esc(first.title || first.canonical_url)}<div class="muted" style="font-size:12px;margin-top:2px">Open it in Chrome, press the Neuro Search extension button, then <b>Capture for Neuro Search</b>. This list advances by itself when the capture lands.</div>
        <div class="row" style="margin-top:6px;gap:6px"><button class="small primary" onclick="openAndCapture('${esc(first.canonical_url || first.url)}')">Open & Capture</button><button class="small ghost" onclick="cancelCapture('${first.job_id}')">Skip (cancel)</button>${EXT.state !== 'ready' ? `<span class="muted text-xs">${extLine() || ''}</span>` : ''}</div></div>
      ${items.length > 1 ? `<details><summary class="muted">All ${items.length} waiting</summary>${items.map((it, i) => `<div class="row" style="padding:4px 0;border-top:1px solid var(--line);align-items:center"><span class="muted fixed" style="width:44px">${i + 1}</span><span class="grow min-w-0">${esc(it.title || it.canonical_url)} <span class="muted">· ${esc(it.adapter === 'reddit_thread' ? 'Reddit thread' : 'web page')}${it.status === 'expired' ? ' · expired — open and capture again' : ''}</span></span><button class="small" onclick="openAndCapture('${esc(it.canonical_url || it.url)}')">Open</button><button class="small ghost" onclick="cancelCapture('${it.job_id}')">Cancel</button></div>`).join('')}</details>` : ''}`;
    clearTimeout(CAPTURE_TIMER);
    globalThis.CAPTURE_TIMER = setTimeout(() => { if (state.view === 'sources') loadSources(); }, 5000);
  } catch (e) { /* the sources list still renders */ }
}
globalThis.removeFromProject = async function removeFromProject(id) { await del(`/api/projects/${state.project.id}/members`, { source_ids: [id] }); loadSources(); }
globalThis.delSource = async function delSource(id) { if (!confirm('Delete this source and its transcript from every project?')) return; await del('/api/sources/' + id); loadSources(); }
globalThis.exportCsv = function exportCsv(seg) { location.href = `/api/export/${seg ? 'segments' : 'sources'}.csv?project_id=${state.project.id}`; }
// ---- G2: understand what was pasted before deciding what to run
globalThis.classifyTimer = null;
globalThis.lastClassified = null;
globalThis.classifyInput = async function classifyInput() {
  const text = $('#inUrls').value.trim(); const box = $('#inDetect');
  if (!text) { box.innerHTML = ''; globalThis.lastClassified = null; return; }
  try {
    const r = await post('/api/classify', { input: text }); globalThis.lastClassified = r.items;
    box.innerHTML = r.items.map((c, i) => {
      const acts = c.actions.map(a => `<label style="margin-right:10px;cursor:pointer" title="${esc(a.note || '')}"><input type="radio" name="act${i}" value="${a.action}" ${a.available ? '' : 'disabled'} ${a.action === c.default_action ? 'checked' : ''}> ${esc(a.label)}${a.available ? '' : ' <span class="muted">(coming)</span>'}</label>`).join('');
      return `<div class="mt-1"><b>${esc(c.label)}</b>${c.host ? ` <span class="muted">${esc(c.host)}</span>` : ''} — ${esc(c.detail)}<div style="margin-top:2px">${acts || '<span class="muted">nothing to do yet</span>'}</div></div>`;
    }).join('');
  } catch (e) { box.textContent = ''; }
}
$('#inUrls').addEventListener('input', () => { clearTimeout(globalThis.classifyTimer); globalThis.classifyTimer = setTimeout(classifyInput, 350); });
globalThis.ingestUrls = async function ingestUrls() {
  const text = $('#inUrls').value.trim(); if (!text) return;
  const tags = $('#inTags').value.split(',').map(t => t.trim()).filter(Boolean);
  if (!globalThis.lastClassified) await classifyInput();
  const items = globalThis.lastClassified || [];
  let queued = 0, skipped = [];
  for (let i = 0; i < items.length; i++) {
    const c = items[i]; const chosen = document.querySelector(`input[name="act${i}"]:checked`);
    const action = chosen ? chosen.value : c.default_action;
    if (!action) { skipped.push(c.label); continue; }
    if (action === 'upload') { skipped.push(`${c.label} — use Upload`); continue; }
    const r = await post(`/api/projects/${state.project.id}/add`, { input: c.input, action, tags, force: $('#inForce').checked, since_years: +$('#inSince').value, max_videos: +$('#inMax').value });
    const res = r.items[0]?.result || {};
    if (res.queued) queued++; else skipped.push(`${c.label}: ${res.note || 'not queued'}`);
  }
  if (queued) toast(`▶ ${queued} queued`);
  if (skipped.length) toast(skipped.join(' · '));
  $('#inUrls').value = ''; $('#inDetect').innerHTML = ''; globalThis.lastClassified = null; loadJobs();
}
globalThis.ingestFiles = async function ingestFiles() {
  const files = [...$('#inFile').files]; if (!files.length) return;
  for (const f of files) {
    const fd = new FormData(); fd.append('file', f); if (files.length === 1) fd.append('title', $('#inFileTitle').value); fd.append('project_id', state.project.id); fd.append('tags', $('#inTags').value);
    const r = await uiFetch('/api/ingest/file', { method: 'POST', body: fd }); const j = await r.json(); if (!r.ok) alert(j.error || j.detail);
  }
  $('#inFile').value = ''; $('#inFileTitle').value = ''; loadJobs();
}
globalThis.ingestText = async function ingestText() {
  const title = $('#inTextTitle').value.trim(), text = $('#inText').value.trim(); if (!title || !text) return;
  await post('/api/ingest/text', { title, text, url: $('#inTextUrl').value || null, project_id: state.project.id, tags: [] });
  $('#inText').value = ''; $('#inTextTitle').value = ''; loadSources();
}
// ---- G7 communities ----
globalThis.COMM_MISSIONS = [];
globalThis.loadCommunity = async function loadCommunity() {
  try {
    const m = await api(`/api/projects/${state.project.id}/community/missions`); globalThis.COMM_MISSIONS = m.missions || [];
    $('#commMission').innerHTML = '<option value="">— pick a mission from the research state —</option>' + COMM_MISSIONS.map((x, i) => `<option value="${i}">${esc(x.kind.replace('_', ' '))}: ${esc(x.query.slice(0, 90))}</option>`).join('');
    const s = await api(`/api/projects/${state.project.id}/community/synthesis`); const st = s.stats || {};
    $('#commCounts').textContent = st.threads ? `· ${st.threads} thread${st.threads === 1 ? '' : 's'} · ${st.substantive} substantive posts · ${st.corrections} correction${st.corrections === 1 ? '' : 's'}` : '';
    $('#commAccess').innerHTML = st.reddit_api ? '' : `<div class="muted" style="font-size:12px;margin:4px 0">Reddit refuses every non-browser reader (since June 2026): to add a thread, open it in Chrome and use the extension's <b>Send this page</b>; to search a subreddit from here, add <code>REDDIT_CLIENT_ID</code> / <code>REDDIT_CLIENT_SECRET</code> (a Reddit “script” app) to <code>.env</code>.</div>`;
    const syn = s.syntheses || [];
    $('#commSynth').innerHTML = syn.length ? `<div class="muted" style="margin-top:6px"><b>Cross-thread experience</b> (derived — cite the posts, not this)</div>` + syn.slice(0, 12).map(x => `<div class="kn">${stTag(x.kind === 'FREQUENTLY_REPORTED' ? 'strong' : x.kind === 'RARE_BUT_SERIOUS' || x.kind === 'STRONG_DISAGREEMENT' ? 'weak' : 'developing')}<div><b>${esc(x.kind.replace(/_/g, ' '))}</b> · ${x.independent_lines} independent firsthand line${x.independent_lines === 1 ? '' : 's'}${x.contradicting ? ` · ${x.contradicting} disputing` : ''}<div class="why">${esc(x.statement)}</div>${x.coverage && x.coverage.note ? `<div class="muted" style="color:var(--warn);font-size:12px">⚠ ${esc(x.coverage.note)}</div>` : ''}<div>${(x.evidence || []).slice(0, 6).map(e => `<a class="chip" href="${esc(e.link || '#')}" target="_blank">${esc(e.relation === 'CONTRADICTS' ? '✗ ' : '')}${esc(e.locator || '')}${e.independent ? '' : ' ↩'}</a>`).join('')}</div></div></div>`).join('') : '';
  } catch (e) { $('#commMsg').textContent = e.message; }
}
globalThis.exploreCommunity = async function exploreCommunity() {
  const community = $('#commName').value.trim(); if (!community) { $('#commMsg').textContent = 'name a community, e.g. r/smallbusiness'; return; }
  const mi = $('#commMission').value; const mission = mi === '' ? null : COMM_MISSIONS[+mi]; const q = $('#commQ').value.trim() || null;
  if (!mission && !q) { $('#commMsg').textContent = 'pick a mission or type a query'; return; }
  $('#commMsg').textContent = 'searching (metadata only)…';
  try {
    const r = await post(`/api/projects/${state.project.id}/community/explore`, { community, query: q, mission });
    $('#commMsg').textContent = `${r.found} candidate thread${r.found === 1 ? '' : 's'} for “${r.query}” — ${r.note}`;
    $('#commResults').innerHTML = (r.candidates || []).map(x => `<div class="row" style="padding:5px 0;border-bottom:1px solid var(--line);align-items:flex-start"><span class="grow"><a href="${esc(x.url)}" target="_blank">${esc(x.title || x.url)}</a> <span class="muted">· ${x.community || ''} · ${x.num_comments ?? '?'} comments · ${x.engagement ?? '?'} points (reaction, not truth) · fit ${x.mission_score}${x.experience_language ? ' · experience language' : ''}</span>${x.description ? `<div class="muted text-xs">${esc(x.description.slice(0, 200))}</div>` : ''}</span><button class="small primary" onclick="candAct('${x.candidate_id}','acquire')">Acquire thread</button></div>`).join('') || '<div class="muted">nothing found</div>';
    loadCandidates();
  } catch (e) { $('#commMsg').textContent = e.message; }
}
// ---- G6 works ----
globalThis.loadWorks = async function loadWorks() {
  const q = $('#workQ').value.trim();
  const r = await api(`/api/works?project_id=&limit=100` + (q ? '&q=' + encodeURIComponent(q) : ''));
  const s = r.stats || {}; $('#workCounts').textContent = s.works ? `· ${s.works} work${s.works === 1 ? '' : 's'} · ${s.versions} version${s.versions === 1 ? '' : 's'} · ${s.owned} cop${s.owned === 1 ? 'y' : 'ies'} owned · ${s.discussing} source${s.discussing === 1 ? '' : 's'} discussing them` : '';
  $('#works').innerHTML = (r.works || []).map(w => `<div class="row" style="padding:5px 0;border-bottom:1px solid var(--line);align-items:flex-start"><span class="grow">📜 <b>${esc(w.title)}</b> <span class="muted">${esc(w.kind)} · ${w.resolution}${w.versions.length ? ' · ' + w.versions.map(v => esc(v.label) + (v.status === 'superseded' ? ' (superseded)' : '')).join(', ') : ''} · ${w.owned} cop${w.owned === 1 ? 'y' : 'ies'} owned${w.discussing ? ', ' + w.discussing + ' source' + (w.discussing === 1 ? '' : 's') + ' discussing it' : ''}${w.candidates ? ', ' + w.candidates + ' seen' : ''}${w.relevance ? ' · ' + esc(w.relevance) + ' here' : ''}</span></span><button class="small ghost" onclick="$('#workQ').value='${esc(w.title)}';resolveWork()">Resolve</button></div>`).join('') || '<div class="muted">No Works yet — they appear as sources and findings name SOPs, publications, statutes, books or papers.</div>';
}
globalThis.resolveWork = async function resolveWork() {
  const text = $('#workQ').value.trim(); if (!text) return;
  $('#workMsg').textContent = 'resolving…';
  try {
    const r = await post('/api/works/resolve', { text, project_id: state.project.id });
    if (r.identity !== 'resolved') { $('#workMsg').textContent = r.note || 'identity unresolved'; return; }
    const head = `${r.work.title}${r.version ? ' — ' + r.version : ''}`;
    if (r.access === 'owned' && r.where === 'project') $('#workMsg').textContent = `${head}: already in this project.`;
    else if (r.access === 'owned') $('#workMsg').innerHTML = `${esc(head)}: you own a copy in another project — <button class="small" onclick="attachFromLibrary('${r.source_ids[0]}', this)">Add it here</button> (no re-acquisition)`;
    else if (r.access === 'candidate') $('#workMsg').textContent = `${head}: resolved identity; a copy was seen but not acquired — see Seen, not added.`;
    else $('#workMsg').innerHTML = `${esc(head)}: resolved identity, unresolved access — no copy owned or seen.` + (r.url ? ` <button class="small" onclick="acquireWork('${esc(text)}')">Acquire the official document</button>` : ' Upload a copy you own.');
  } catch (e) { $('#workMsg').textContent = e.message; }
  loadWorks();
}
globalThis.acquireWork = async function acquireWork(text) {
  const r = await post(`/api/projects/${state.project.id}/add`, { input: text, action: 'acquire', tags: [] });
  const res = r.items[0]?.result || {}; $('#workMsg').textContent = res.queued ? '▶ acquiring the official document…' : (res.note || 'not queued'); loadJobs();
}
globalThis.loadLibrary = async function loadLibrary() {
  const p = new URLSearchParams({ not_in_project: state.project.id, status: 'ready', limit: 500 }); if ($('#libQ').value) p.set('q', $('#libQ').value);
  const rows = await api('/api/sources?' + p);
  $('#library').innerHTML = rows.map(s => `<div class="row" style="padding:5px 0;border-bottom:1px solid var(--line)"><span class="grow">${ICON[s.platform] || '•'} ${esc(s.title)} <span class="muted">${esc(s.channel || '')} ${s.duration ? fmt(s.duration) : ''}</span></span><button class="small" onclick="addFromLibrary('${s.id}', this)">Add</button></div>`).join('') || '<div class="muted">Nothing else in the library.</div>';
}
globalThis.loadCandidates = async function loadCandidates() {
  const p = new URLSearchParams({ limit: 60 }); if ($('#candQ').value) p.set('q', $('#candQ').value); if ($('#candState').value) p.set('state', $('#candState').value);
  const r = await api(`/api/projects/${state.project.id}/candidates?` + p);
  const c = r.counts || {};
  $('#candCounts').textContent = c.total ? `· ${c.total} for this project (${c.available || 0} available, ${(c.skipped_limit || 0) + (c.skipped_low_relevance || 0)} skipped, ${c.user_dismissed || 0} dismissed, ${c.acquired || 0} acquired) · ${c.global} seen overall` : '· nothing yet';
  const st = x => ({ available: 'available', skipped_limit: 'skipped: outside the number picked', skipped_low_relevance: 'skipped: low relevance', skipped_cost: 'skipped: cost', user_dismissed: 'dismissed', duplicate: 'duplicate', acquired: 'acquired', unseen_by_project: 'seen in another project' })[x] || x;
  $('#candidates').innerHTML = (r.items || []).map(x => {
    const o = x.origin || (x.project || {}).origin || {}; const stt = x.state || 'available'; const rel = x.relevance ?? (x.project || {}).relevance;
    return `<div class="row" style="padding:5px 0;border-bottom:1px solid var(--line);align-items:flex-start"><span class="grow">${ICON[x.platform] || '•'} ${x.url && x.url.startsWith('http') ? `<a href="${esc(x.url)}" target="_blank">${esc(x.title || x.url)}</a>` : esc(x.title || x.url)} <span class="muted">${esc(x.creator || '')}${x.published_at ? ' · ' + x.published_at : ''}${x.duration ? ' · ' + fmt(x.duration) : ''}${rel != null ? ` · relevance ${rel}` : ''}</span><div class="muted text-xs">${esc(st(stt))}${o.title ? ` · seen in ${esc(o.title)}` : ''}${x.in_library ? ' · <b>already in your library</b>' : ''}${x.description ? `<br>${esc(x.description.slice(0, 160))}` : ''}</div></span>
      ${stt === 'acquired' || x.in_project ? '' : `<button class="small primary" onclick="candAct('${x.id}','acquire')">${x.in_library ? 'Add from library' : 'Add'}</button>`}
      ${stt === 'user_dismissed' ? `<button class="small ghost" onclick="candAct('${x.id}','restore')">Restore</button>` : stt === 'acquired' ? '' : `<button class="small ghost" onclick="candAct('${x.id}','dismiss')">Dismiss</button>`}</div>`;
  }).join('') || '<div class="muted">Nothing matches.</div>';
}
globalThis.candAct = async function candAct(id, act) {
  let reason = null; if (act === 'dismiss') { reason = prompt('Why? (optional — e.g. "not this creator", "wrong jurisdiction", "too old")') || null; }
  const r = await post(`/api/candidates/${id}/${act}`, { project_id: state.project.id, reason });
  if (act === 'acquire') toast(r.job_id ? '▶ queued — it goes through the normal ingest' : '✓ attached from your library');
  loadCandidates(); if (act === 'acquire') loadJobs();
}
globalThis.loadCoursePane = async function loadCoursePane() {
  try { const w = await api('/api/whoami'); const addr = w.lan_url && location.hostname === 'localhost' ? `${w.lan_url} (from another computer on your network) or ${location.origin} (this computer)` : location.origin; $('#appAddr').textContent = addr; } catch (e) { $('#appAddr').textContent = location.origin; }
  const cs = (await api('/api/collections')).filter(c => c.kind === 'course');
  $('#courseList').innerHTML = cs.length ? '<b>Imported courses</b>' + cs.map(c => `<div class="muted" style="padding:4px 0">🎓 ${esc(c.title)} — ${c.n_sources} videos</div>`).join('') : '';
}
globalThis.loadBudget = async function loadBudget() {
  const u = await api('/api/usage'); $('#bDaily').value = u.daily_budget; $('#bMonthly').value = u.monthly_budget;
  const kinds = Object.entries(u.month_by_kind || {}).map(([k, v]) => `${k} $${v.toFixed(2)}`).join(' · ');
  $('#bBreak').textContent = `This month: $${u.month.toFixed(2)}` + (kinds ? ` (${kinds})` : '') + ` · today $${u.today.toFixed(2)}` + (u.month_saved >= 0.01 ? ` · prompt caching saved $${u.month_saved.toFixed(2)}` : '') + (u.blocked ? ` · ⏸ ${u.blocked}` : '');
}
globalThis.loadHealth = async function loadHealth() {
  try {
    const h = await api('/api/health');
    const ago = ts => { if (!ts) return 'never'; const m = Math.round((Date.now() / 1000 - ts) / 60); return m < 1 ? 'just now' : m < 90 ? `${m} min ago` : `${(m / 60).toFixed(1)} h ago`; };
    const ok = b => b ? '✅' : '⚠️';
    // 2026-09-14 - DESIGN.md's adopt list has called for soft-tinted status pills since the INSPIRATION review
    // (Vyra's "↗ Normal" / "↘ Low" arrow-badges), but --ok-soft/--warn-soft/--bad-soft were defined in styles.css
    // and used almost nowhere. These three percentage rows are exactly the "vital sign" shape Vyra's pattern is
    // for, so they get the badge first rather than a blanket restyle of every .status-* span (most of those are
    // plain-color inline text, not pills, and forcing backgrounds onto all of them would be a much bigger, riskier
    // change nobody asked for).
    const pillHtml = (isOk, pct) => `<span class="pill-stat ${isOk ? 'ok' : 'warn'}">${isOk ? '↗' : '↘'} ${pct.toFixed(1)}%</span>`;
    const it = h.db.integrity, bk = h.backup.last_verified, ev = h.evidence;
    const rows = [
      [`${ok(it && it.ok)} Database integrity`, it ? `${it.result} · checked ${ago(it.ts)}` + (it.duplicate_claim_evidence ? ` · ${it.duplicate_claim_evidence} duplicate citation row(s) - needs a look` : '') + (it.dangling_origin_note_id ? ` · ${it.dangling_origin_note_id} claim(s) with an unrecoverable origin-note link (pre-0.63.75, informational only)` : '') : 'not checked yet'],
      [`${ok(bk)} Verified backup`, bk ? `${ago(bk.ts)} · ${(bk.bytes / 1e6).toFixed(1)} MB · ${bk.counts.sources} sources, ${bk.counts.messages} messages` : (h.backup.last_error ? 'FAILED: ' + h.backup.last_error.error : 'none yet')],
      [`${ok(!h.jobs.stale_running)} Queue`, `${h.jobs.queued || 0} queued · ${h.jobs.running || 0} running · ${h.jobs.failed || 0} failed` + (h.jobs.stale_running ? ` · ${h.jobs.stale_running} stale` : '')],
      [`${ok(ev.finding_quote_validity == null || ev.finding_quote_validity >= 0.98)} Finding quotes verified`, ev.findings_checked ? raw(`${pillHtml(ev.finding_quote_validity >= 0.98, ev.finding_quote_validity * 100)} of ${ev.findings_checked} (${ev.findings_rejected} rejected)`) : 'none yet'],
      [`${ok(ev.finding_citation_rate == null || ev.finding_citation_rate >= 0.99)} Verified findings that can be cited`, ev.citation_rate_since ? raw(`${pillHtml(ev.finding_citation_rate >= 0.99, ev.finding_citation_rate * 100)} of the ${ev.citation_rate_since} counted since v0.63.24${ev.findings_uncitable ? ` (${ev.findings_uncitable} with no locator)` : ''}${ev.locator_from_quote ? ` · ${ev.locator_from_quote} located from the quote` : ''}`) : 'nothing counted yet'],
      [`${ok(ev.citation_validity == null || ev.citation_validity >= 0.99)} Answer citations valid`, ev.citations_checked ? raw(`${pillHtml(ev.citation_validity >= 0.99, ev.citation_validity * 100)} of ${ev.citations_checked}`) : 'none yet'],
      // 0.63.28 — `model_routing` has been computed since 0.56.3 and rendered NOWHERE. On Kyle's machine it held
      // 363 findings calls where the contract asked for claude-sonnet-5 and the local Claude Code CLI returned
      // claude-haiku-4-5, which is both a quality substitution the app never chose AND the reason paid API
      // fallbacks happen (Haiku fails the findings structured-output schema, the CLI exits 1, health goes to
      // `error`, and the work bounces to the API that charges). A counter nobody reads is how that stayed invisible.
      // 0.63.29 — judged on `since_fix`, not the raw count. The 363 rows on Kyle's machine were mis-readings of
      // the CLI's modelUsage (cached tokens ignored, so the scaffolding model outscored the model that did the
      // work), kept rather than deleted and shown as such.
      (() => { const ms = h.model_routing?.mismatches || [], real = ms.filter(m => (m.since_fix ?? m.count) > 0),
                     stale = ms.reduce((a, m) => a + (m.before_fix || 0), 0);
        return [`${ok(!real.length)} Model the provider actually ran`, real.length
          ? raw(real.map(m => `<b>${esc(m.task || '')}</b>: asked ${esc(m.requested || '?')}, got ${esc(m.actual || '?')} on ${esc(m.executed_by || '?')} — ${m.since_fix ?? m.count}×`).join('<br>')
             + `<div class="muted" style="margin-top:3px">The app has no model-substitution path, so every row here is a provider overriding a contract — usually the local CLI. Local work is free on a subscription but is not the model the task was measured on.</div>`)
          : `every call ran the model its contract asked for${stale ? ` · ${stale} earlier row${stale === 1 ? '' : 's'} were mis-readings corrected in v0.63.29, kept rather than deleted` : ''}`]; })(),
      [`${ok(!h.disk.free_gb || h.disk.free_gb > 5)} Disk`, h.disk.free_gb != null ? `${h.disk.free_gb} GB free · database ${h.disk.db_mb} MB` : '—'],
      [`${ok(!(h.structured_outputs || {}).fallbacks && !(h.structured_outputs || {}).unrecovered && !(h.structured_outputs || {}).mismatches)} Structured-output fallbacks`, h.structured_outputs ? `${h.structured_outputs.fallbacks} fallback${h.structured_outputs.fallbacks === 1 ? '' : 's'} · ${h.structured_outputs.mismatches} schema mismatch${h.structured_outputs.mismatches === 1 ? '' : 'es'} (${h.structured_outputs.unrecovered} unrecovered) · truncated ${h.structured_outputs.truncated} · refused ${h.structured_outputs.refused} · steady state 0` : '—'],
      [`${h.fake_ai ? '🧪' : '✅'} Models`, h.fake_ai ? 'FAKE AI MODE — no real model calls' : 'live'],
      ...((h.providers || []).map(p => [`${p.status === 'Healthy' ? '✅' : p.status === 'Checking' ? '🔎' : '⏸'} ${p.label}`, p.status === 'Healthy' ? 'Healthy' : `${p.status}${p.detail ? ' · ' + p.detail : ''}${p.waiting_jobs ? ` · ${p.waiting_jobs} job${p.waiting_jobs === 1 ? '' : 's'} waiting` : ''}`])),
      [`${ok(Object.values(h.flags || {}).every(f => f.ok))} Experimental flags`, Object.entries(h.flags || {}).filter(([k]) => k !== 'NEUROSEARCH_FAKE_AI').map(([k, f]) => `${k.replace('NEUROSEARCH_', '').toLowerCase()} ${f.ok ? 'off' : 'ON'} (${f.status})`).join(' · ') || '—'],
      [`${h.release ? (h.release.verdict === 'PASS' ? '✅' : '⚠️') : '⚠️'} Last release check`, h.release ? `${h.release.verdict} · ${h.release.app_version} @ ${h.release.git_sha} · ${h.release.timestamp} · ${h.release.checks} gates` : 'none yet — run: neurosearch release-check'],
      [`${ok(!(h.library || {}).duplicate_fingerprints)} Global Library`, h.library ? `${h.library.sources} sources (${h.library.ready} ready) · ${h.library.shared_by_projects} shared by several projects · ${h.library.acquisitions_avoided} acquisition${h.library.acquisitions_avoided === 1 ? '' : 's'} avoided by reuse · profiles: ${h.library.profiles ? `${h.library.profiles.enriched} enriched, ${h.library.profiles.wanted + h.library.profiles.queued} wanted/queued, ${h.library.profiles.recalls} recalls` : '—'} · ${h.library.candidates_seen || 0} seen, ${h.library.candidates_not_acquired || 0} not acquired (Candidate Index)${h.library.duplicate_fingerprints ? ` · ⚠ ${h.library.duplicate_fingerprints} duplicate content fingerprints` : ''}` : '—'],
      [`${ok(!((h.perf || {}).slowest || []).some(s => s.p50 > 1))} Slowest endpoints (since restart)`, ((h.perf || {}).slowest || []).length ? (h.perf.slowest.map(s => `${s.key} ${s.p50.toFixed(2)}s p50 / ${s.p90.toFixed(2)}s p90 (${s.n})`).join(' · ') + ' — full picture: Measure speed') : 'nothing measured yet'],
      ...(Object.keys((h.perf || {}).caches || {}).length ? [[`📈 Cache hit rate`, Object.entries(h.perf.caches).map(([k, c]) => `${k} ${c.rate == null ? '—' : (c.rate * 100).toFixed(0) + '%'} (${c.hit}/${c.hit + c.miss})`).join(' · ')]] : []),
      [`${ok(!(h.network || {}).fetch_blocked)} Network boundary`, `${(h.network || {}).fetch_blocked || 0} fetch${(h.network || {}).fetch_blocked === 1 ? '' : 'es'} refused (private/internal address, size or time limit)`],
      // 0.59.0: the recorded-vs-actual spend gap belongs on the page you open when you wonder where the money went.
      ...(h.spend ? [[
        `${h.spend.local_is_free ? '✅' : '⚠️'} Spend (recorded vs likely charged)`,
        `today $${(h.spend.today || {}).likely_total ?? 0} · 7 days $${(h.spend.week || {}).likely_total ?? 0} · month $${(h.spend.month || {}).likely_total ?? 0}`
        + (h.spend.local_is_free
            ? ` · local path free (${(h.spend.month || {}).local_calls || 0} calls, $${(h.spend.month || {}).local_if_billed ?? 0} avoided)`
            : ` — of the month, $${(h.spend.month || {}).recorded ?? 0} was recorded and $${(h.spend.month || {}).local_if_billed ?? 0} came from the local Claude Code path, which is NOT free here`)
        + ` · budgets: $${(h.spend.budgets || {}).daily ?? '—'}/day, $${(h.spend.budgets || {}).monthly ?? '—'}/month`
        + ((h.spend.budgets || {}).weekly ? `, $${h.spend.budgets.weekly}/week` : ', no weekly budget set')
        + ` · ceiling $${(h.spend.budgets || {}).rate_per_hour ?? '—'}/hour`
      ], [`${h.spend.local_is_free ? '✅' : '⚠️'} Who pays for local calls`, `${h.spend.billing_mode} — ${h.spend.note}`]] : []),
      // 0.60.3: a cancelled batch's completed requests were paid for. Collecting them is free.
      ...(h.batches && !h.batches.error && h.batches.unsettled ? [[
        `⚠️ Provider batches: work paid for and not written`,
        `${h.batches.unsettled} batch${h.batches.unsettled === 1 ? '' : 'es'} · ${h.batches.awaiting_collection || 0} request${(h.batches.awaiting_collection || 0) === 1 ? '' : 's'} not collected · ${h.batches.collected_not_written || 0} collected but never written. ${h.batches.note}`
      ]] : []),
      // 0.59.3: how much, per useful thing. "Is it improving?" is a different question from "how much have we spent".
      ...(h.cost_value && !h.cost_value.error ? [[
        `${h.cost_value.week_vs_month === 'dearer' ? '⚠️' : '✅'} Cost per kept finding`,
        (h.cost_value.month.per_kept_finding == null
          ? 'no findings kept this month yet'
          : `$${(+h.cost_value.month.per_kept_finding).toFixed(4)} this month (${h.cost_value.month.kept} kept for $${(+h.cost_value.month.cost).toFixed(2)})`
            + (h.cost_value.week.per_kept_finding == null ? ''
               : ` · $${(+h.cost_value.week.per_kept_finding).toFixed(4)} over 7 days — ${h.cost_value.week_vs_month}`))
        + ` · $${(+h.cost_value.total_charged_month).toFixed(2)} charged this month, $${(+h.cost_value.unattributed_month).toFixed(2)} of it on work no unit claims`
        + ' — full picture: Cost per unit of value'
      ]] : []),
    ];
    const sb = $('#settleBtn'); if (sb) sb.hidden = !(h.batches && h.batches.unsettled);
    // 2026-09-14 - v used to always go through esc(), which silently mangled the model-routing row's own
    // <b>/<br>/<div> markup into literal escaped text. Rows that build safe HTML themselves now wrap it in raw()
    // (see api.js) to say so explicitly; everything else keeps going through esc() exactly as before.
    $('#healthLine').innerHTML = rows.map(([k, v]) => `<div><b>${k}</b><br><span class="muted">${v && v.__raw ? v.html : esc(v)}</span></div>`).join('');
  } catch (e) { $('#healthLine').textContent = 'health unavailable: ' + e.message; }
}
globalThis.settleBatches = async function settleBatches() {
  const b = $('#settleBtn'); const m = $('#healthMsg');
  b.disabled = true; const was = b.textContent; b.textContent = '⏳ collecting…';
  try {
    // 0.62.7: this used to run the whole settlement inside the request. Recovering 410 stranded cohorts took
    // minutes and blocked everything else in a single-process server, so it queues and the Jobs panel shows it.
    const r = await post('/api/batches/settle-all', {});
    if (r.queued) { m.textContent = r.note; loadJobs(); }
    else if (r.attempted === 0) { m.textContent = r.note || 'nothing is waiting to be collected'; }
    else {
      const still = (r.results || []).filter(x => x.still_processing).length;
      m.textContent = `${r.materialized || 0} source(s) gained findings from ${r.attempted} batch(es)`
        + (still ? ` · ${still} still processing at the provider — try again later` : '');
    }
    loadHealth();
  } catch (e) { m.textContent = 'could not collect: ' + (e.message || e); }
  b.disabled = false; b.textContent = was;
}
globalThis.valueReport = async function valueReport() {
  // 0.59.3: the question Kyle asked after the overnight run — "the volume of data is always valuable, just HOW is
  // something we want to keep checking that we are improving against". Every other spend surface says how much.
  const box = $('#valueOut'); box.textContent = 'adding it up…';
  try {
    const pid = state.project ? state.project.id : null;
    const r = await api('/api/usage/value/report' + (pid ? `?project_id=${encodeURIComponent(pid)}` : ''));
    const money = v => v == null ? '—' : '$' + (+v).toFixed(v < 0.1 ? 4 : 2);
    const tbl = (title, cols, rows, foot) => rows.length ? `<div style="margin-top:10px"><b>${title}</b><table style="width:100%;border-collapse:collapse;margin-top:4px"><tr>${cols.map(c => `<th style="text-align:left;padding:2px 8px 2px 0;font-weight:600">${esc(c)}</th>`).join('')}</tr>${rows.map(rw => `<tr>${rw.map(v => `<td style="padding:2px 8px 2px 0">${esc(String(v))}</td>`).join('')}</tr>`).join('')}</table>${foot ? `<div class="muted" style="margin-top:3px">${esc(foot)}</div>` : ''}</div>` : '';
    let html = '';
    for (const w of ['today', 'week', 'month']) {
      const rep = r.windows[w]; if (!rep) continue;
      html += tbl(`Per unit of value — ${w === 'week' ? 'last 7 days' : w}`,
        ['unit', 'spend', 'produced', 'each', 'why not'],
        rep.rows.map(x => [x.label, money(x.cost), x.count, x.per_unit == null ? '—' : money(x.per_unit),
                           x.per_unit_unavailable || '']),
        `${money(rep.total_charged)} charged in total · ${money(rep.attributed)} attributed · `
        + `${money(rep.unattributed.total)} on work no unit claims (${Object.keys(rep.unattributed.by_kind || {}).join(', ') || 'none'})`
        + (rep.estimated && rep.estimated.share ? ` · ${Math.round(rep.estimated.share * 100)}% of it estimated from the local path rather than metered` : ''));
    }
    for (const [unit, bm] of Object.entries(r.by_model || {})) {
      if (!bm.supported || !(bm.rows || []).length) continue;
      html += tbl(`Per ${bm.label}, by model (month)`, ['model', 'spend', 'calls', 'produced', 'each', 'why not'],
        bm.rows.map(x => [x.model, money(x.cost), x.calls, x.count, x.per_unit == null ? '—' : money(x.per_unit),
                          x.per_unit_unavailable || '']),
        bm.verdict || 'not enough models on their own rates to compare');
    }
    const tr = r.trend || {};
    if ((tr.rows || []).length) {
      html += tbl(`Per ${tr.label}, by day`, ['day', 'spend', 'kept', 'each'],
        tr.rows.map(x => [x.day, money(x.cost), x.count, x.per_unit == null ? '—' : money(x.per_unit)]));
    }
    html += `<div class="muted" style="margin-top:10px">Compare a row against the same row in an earlier window, never against another row.<br>${(r.caveats || []).map(c => '• ' + esc(c)).join('<br>')}</div>`;
    box.innerHTML = html || '<span class="muted">nothing spent and nothing produced yet</span>';
  } catch (e) { box.textContent = 'could not add it up: ' + (e.message || e); }
}
globalThis.perfReport = async function perfReport() {
  // R0: the same three tables SPEED-MISSION.md §A was written from, regenerated from live data.
  const box = $('#perfOut'); box.textContent = 'measuring…';
  try {
    const p = await api('/api/perf');
    const tbl = (title, cols, rows) => rows.length ? `<div style="margin-top:10px"><b>${title}</b><table style="width:100%;border-collapse:collapse;margin-top:4px"><tr>${cols.map(c => `<th style="text-align:left;padding:2px 8px 2px 0;font-weight:600">${c}</th>`).join('')}</tr>${rows.map(r => `<tr>${r.map(v => `<td style="padding:2px 8px 2px 0;white-space:nowrap">${esc(String(v))}</td>`).join('')}</tr>`).join('')}</table></div>` : '';
    const s = n => `${(+n).toFixed(2)}s`;
    box.innerHTML =
      tbl(`Endpoints — this process, slowest first`, ['endpoint', 'p50', 'p90', 'max', 'n'],
        Object.entries(p.timings || {}).slice(0, 12).map(([k, v]) => [k, s(v.p50), s(v.p90), s(v.max), v.n])) +
      tbl(`Jobs — work vs waiting (last ${p.window_days} days)`, ['kind', 'work p50', 'wait p50', 'waiting', 'n'],
        (p.queue || []).map(q => [q.kind, s(q.work_p50), s(q.wait_p50), `${Math.round(q.waiting_share * 100)}%`, q.n])) +
      tbl(`Model calls — task × provider (last ${p.window_days} days)`, ['task', 'provider', 'p50', 'p90', 'n'],
        (p.models || []).map(m => [m.task, m.provider, s(m.p50), s(m.p90), m.n])) ||
      '<span class="muted">nothing measured yet — use the app for a minute and press again</span>';
  } catch (e) { box.textContent = 'could not measure: ' + (e.message || e); }
}
globalThis.backupNow = async function backupNow() { $('#healthMsg').textContent = 'snapshotting…'; try { await post('/api/backup', {}); $('#healthMsg').textContent = 'verified ✓'; } catch (e) { $('#healthMsg').textContent = 'failed: ' + e.message; } loadHealth(); setTimeout(() => $('#healthMsg').textContent = '', 3000); }
globalThis.saveBudget = async function saveBudget() { await post('/api/usage/budget', { daily: +$('#bDaily').value, monthly: +$('#bMonthly').value }); $('#bMsg').textContent = 'Saved ✓'; setTimeout(() => $('#bMsg').textContent = '', 2000); loadBudget(); loadSpend(); }
globalThis.cancelQueued = async function cancelQueued() {
  if (!confirm('Cancel everything that has not started yet? Finished videos are kept; the rest go back to the Review card so you can approve a smaller set later.')) return;
  const r = await post('/api/jobs/cancel-queued', { project_id: state.project.id }); alert(`Cancelled ${r.cancelled} queued job(s).`); loadJobs(); loadSources();
}
globalThis.togglePause = async function togglePause(p) { await post('/api/usage/budget', { paused: p }); loadJobs(); }
globalThis.toggleBackground = async function toggleBackground(p) {
  // Only the speculative lanes stop; anything the user started keeps running. Background jobs are idempotent, so
  // stopping one mid-pass re-does no paid work when it resumes.
  const r = await post('/api/jobs/background-pause', { paused: p, project_id: state.project && state.project.id })
    .catch(e => { toast(e.message || e, 'err'); return null; });
  if (r) toast(p ? `⏸ background held${r.stopped ? ` · stopped ${r.stopped} running` : ''}${r.waiting ? ` · ${r.waiting} waiting` : ''}`
                 : '▶ background resumed — it picks up where it left off');
  loadSpend(); loadJobs();
}
globalThis.recheckAccount = async function recheckAccount() {
  // The banner is a CACHED BELIEF about the account: only a working call, or the user saying the situation
  // changed, may retire it. Clearing is free — if the block is real the next attempt re-sets it immediately.
  try {
    const r = await post('/api/usage/recheck', {});
    const local = r.local_ai && r.local_ai.rechecking ? ' · re-probing Claude Code' : '';
    toast(r.blocked ? `still blocked — ${r.blocked}` : `✅ unblocked${r.jobs_released ? ` · ${r.jobs_released} job${r.jobs_released === 1 ? '' : 's'} released` : ''}${local}`, r.blocked ? 'err' : '');
    if (r.local_ai && r.local_ai.rechecking) setTimeout(() => { loadSpend(); loadHealth && loadHealth(); }, 4000);   // the probe finishes in the background
  } catch (e) { toast(e.message || e, 'err'); }
  loadSpend(); loadJobs();
}
// ---- G4: "Evidence already in your library" — suggestions with provenance; nothing is attached until you click Add
// 0.62.5 — the rung between "what you own" and "the web": sources the app has SEEN and never read (ranked-but-
// skipped videos, the ingest cutoff, everything exploration enumerated). Kyle's own ordering.
globalThis.renderSeen = function renderSeen(seen) {
  const box = $('#discSeen'); if (!box) return;
  if (!seen || !(seen.items || []).length) { box.innerHTML = seen && seen.note ? `<div class="muted">👁 ${esc(seen.note)}</div>` : ''; return; }
  const c = seen.counts || {};
  box.innerHTML = `<div class="card status-ok-border"><b>👁 Already seen, never read</b>
    <span class="muted">(${seen.total} match “${esc(seen.searched || seen.query || '')}” · ${c.candidates || 0} from exploration, ${c.skipped || 0} skipped at the cutoff · $0 to find, and you can read any of them)</span>
    ${seen.items.map(i => `<div style="padding:6px 0;border-top:1px solid var(--line)"><div class="row"><span class="grow"><b>${esc(i.title)}</b>
      <span class="muted">${esc(i.creator || i.platform || '')}${i.published_at ? ' · ' + esc(i.published_at) : ''} · ${esc(i.why_known)}</span></span>
      <span class="muted" style="font-size:12px;margin-right:6px">potential ${i.potential}</span>
      <button class="small primary" onclick="captureSeen('${i.kind}','${i.id}', this)">Read this</button></div>
      ${(i.why || []).length ? `<div class="muted" style="font-size:12.5px">${esc((i.why || []).slice(0, 3).join(' · '))}${i.fits ? ' · fits: ' + esc(i.fits) : ''}</div>` : ''}</div>`).join('')}
    </div>`;
}
globalThis.captureSeen = async function captureSeen(kind, id, btn) {
  // Same acknowledgement discipline as discAdd (0.60.1): the work is queued, so the click itself has to say so.
  const was = btn.textContent; btn.disabled = true; btn.textContent = '⏳ queueing…';
  try {
    if (kind === 'skipped') await post(`/api/sources/${id}/retry`, {});
    else await post(`/api/candidates/${id}/acquire`, { project_id: state.project.id });
    btn.textContent = 'queued ✓';
    toast('⏵ queued for reading — it appears in Sources as it is read');
    loadJobs(); loadSources();
  } catch (e) { btn.disabled = false; btn.textContent = was; toast(e.message || e, 'err'); }
}
globalThis.renderLibrarySuggestions = function renderLibrarySuggestions(lib) {
  const box = $('#discLibrary'); if (!lib) { box.innerHTML = ''; return; }
  const items = lib.suggestions || [];
  // 0.62.0: a search the library cannot answer says so, above the hits, instead of presenting them as answers.
  const sat = lib.saturated;
  const satBox = sat ? `<div class="banner" style="margin-bottom:6px"><b>📚 You already own this subject</b> — ${esc(sat.note)}</div>` : '';
  const vg = lib.vague_query;
  const vgBox = vg ? `<div class="banner" style="margin-bottom:6px"><b>⚠ This search is too vague to match on</b> — ${esc(vg.why)}. ${esc(vg.advice)}. The ${vg.shown_anyway} closest things you own are listed below and tagged as generic matches; nothing was skipped.</div>` : '';
  if (!items.length) { box.innerHTML = satBox + vgBox + `<div class="muted">🗄 Nothing relevant found in your library outside this project (${lib.scope || 0} sources checked at no cost).</div>`; return; }
  box.innerHTML = satBox + vgBox + `<div class="card" style="border-color:${vg || sat ? 'var(--warn)' : 'var(--ok)'}"><b>🗄 ${vg ? 'Closest things in your library' : sat ? 'What is left in your library' : 'In your library — no new acquisition needed'}</b> <span class="muted">(${items.length} of ${lib.scope} sources outside this project matched${lib.anchor && lib.anchor.term ? ` on “${esc(lib.anchor.term)}”` : ''}; ranked by matching passages, then profile)</span>
    ${items.map(s => `<div style="padding:6px 0;border-top:1px solid var(--line)"><div class="row"><span class="grow"><b>${esc(s.title || s.url)}</b> <span class="muted">${esc(s.channel || s.platform || '')}${s.published_at ? ' · ' + s.published_at : ''}</span></span>${s.generic_match ? '<span class="muted" style="font-size:12px;margin-right:6px" title="Matched only words that do not name a subject">generic match</span>' : ''}<button class="small ${s.generic_match ? '' : 'primary'}" onclick="attachFromLibrary('${s.source_id}', this)">Add to project</button></div>
      <div class="muted" style="font-size:12.5px">${esc(s.why.join(' · '))}${s.authority_signals && s.authority_signals.length ? ' · ' + s.authority_signals.map(a => esc(a.value)).slice(0, 3).join(', ') : ''}${s.evidence_class ? ' · ' + esc(s.evidence_class) : ''}${s.enriched ? '' : ' · <span title="Profile not yet enriched — recall still works from passages and metadata">baseline profile</span>'}</div>
      ${s.profile_summary ? `<div class="muted" style="font-size:12.5px">${esc(s.profile_summary)}</div>` : ''}
      ${s.chunks && s.chunks[0] ? `<div style="font-size:12.5px;margin-top:2px">“${esc(s.chunks[0].text.slice(0, 220))}” <a class="muted" href="${esc(s.chunks[0].link)}" target="_blank">@ ${esc(s.chunks[0].timestamp)}</a></div>` : ''}</div>`).join('')}
    ${lib.enrichment && lib.enrichment.wanted ? `<div class="muted" style="margin-top:6px">${lib.enrichment.wanted} of these will get a richer profile when enough have accumulated for a batch (never required for recall).</div>` : ''}</div>`;
}
globalThis.attachFromLibrary = async function attachFromLibrary(sid, btn) {
  const r = await post(`/api/projects/${state.project.id}/members`, { source_ids: [sid], collection_ids: [] });
  if (btn) { btn.textContent = 'Added ✓'; btn.disabled = true; }
  state.project = r; $('#nSources').textContent = r.n_sources; toast('✓ attached — nothing re-downloaded; findings for this project are being prepared');
}
globalThis.loadDiscoveries = async function loadDiscoveries(keepMsg = false) {
  const ds = await api(`/api/projects/${state.project.id}/discoveries`);
  const show = ds.filter(d => d.status !== 'dismissed');
  const KIND = { youtube_channel: '▶ YouTube channel', podcast: '🎙 Podcast', newsletter: '✉ Newsletter', website: '🌐 Website', person: '👤 Person' };
  const q = v => JSON.stringify(v).replace(/"/g, '&quot;');
  $('#discList').innerHTML = show.map(d => {
    const isSearch = u => /youtube\.com\/results\?/.test(u || '');
    const vids = (d.start_with || []).filter(v => v.url && !isSearch(v.url) && /youtu|\.mp3|podcast|loom|vimeo/i.test(v.url));
    const searches = [...(d.start_with || []).map(v => v.url), d.url].filter(isSearch);
    const isChan = d.url && /youtube\.com\/(@|channel\/|c\/|user\/)/.test(d.url);
    // 0.60.2: a suggested address that does not resolve is a fact on the row, checked for free before the user
    // clicks. A 403 is NOT hidden — the page is usually there and the server just dislikes us.
    const lc = d.link_check || null;
    const dead = lc && (lc.status === 'not_found' || lc.status === 'unreachable');
    return `<div class="d ${d.status}">
    <div class="dh">
      <div class="dmain">
        <div class="dt"><b>${esc(d.name)}</b>${d.known_for ? ` <span class="gist">— ${esc(d.known_for)}</span>` : ''}</div>
        <div class="dwhy">${esc(d.why || '')}</div>
        <div class="dmeta">${KIND[d.kind] || esc(d.kind || '')}${d.fit ? ` · fit <span class="status-warn">${'●'.repeat(d.fit)}</span>` : ''}${d.depth ? ` · ${esc(d.depth)}` : ''}${d.angle ? ` · <span title="angle / bias">${esc(d.angle)}</span>` : ''}${d.status === 'added' ? ' · <span class="status-ok">added ✓</span>' : ''}${lc && lc.status !== 'ok' && lc.status !== 'skipped' ? ` · <span style="color:var(--${dead ? 'bad' : 'warn'})" title="${esc(lc.detail || lc.reason || '')}">${lc.status === 'not_found' ? `that address is gone (${lc.http || 404})` : lc.status === 'blocked' ? `the site would not let us read it (${lc.http || 'blocked'}) — the page is probably there` : lc.status === 'refused' ? 'refused by the fetch boundary' : 'could not reach it'}</span>` : ''}</div>
      </div>
      <div class="dacts">
        <!-- 0.60.1 (Kyle: "some buttons are blue and some are white - why is that?"): the colour used to depend on
             d.kind — website and newsletter were primary, a paper or a person was not — which encoded nothing the
             reader could see and made half the list look disabled. Every row's affirmative action now looks the
             same, and only the dismiss stays ghost. -->
        ${vids.length ? `<button class="small primary" title="${esc(vids[0].title)}" onclick="discAdd(${d.id}, ${JSON.stringify(vids[0].url).replace(/"/g, '&quot;')}, false, this)">＋ Start video</button>` : ''}
        ${isChan ? `<button class="small primary" onclick="discAdd(${d.id}, ${JSON.stringify(d.url).replace(/"/g, '&quot;')}, true, this)">＋ Channel</button>` : ''}
        ${searches.length ? `<button class="small primary" title="Lists the top YouTube results for review — nothing downloaded until you approve" onclick="discAdd(${d.id}, ${JSON.stringify(searches[0]).replace(/"/g, '&quot;')}, true, this)">🔍 Search YouTube</button>` : ''}
        ${!isChan && !searches.length && d.url && /^https?:/.test(d.url) && !vids.length && !dead ? `<button class="small primary" title="Read this page into the project (text only; use a specific article URL for best results)" onclick="discAdd(${d.id}, ${JSON.stringify(d.url).replace(/"/g, '&quot;')}, false, this)">＋ Add page</button>` : ''}
        ${dead && lc.suggested_url ? `<button class="small primary" title="${esc(lc.suggested_why || '')}" onclick="discAdd(${d.id}, ${JSON.stringify(lc.suggested_url).replace(/"/g, '&quot;')}, false, this)">＋ Add the site instead</button>` : ''}
        ${d.status !== 'added' ? `<button class="small ghost" title="Dismiss" aria-label="Dismiss" onclick="discStatus(${d.id},'dismissed')"><svg class="ic"><use href="#ic-dismiss"></use></svg></button>` : ''}
      </div>
    </div>
    ${(d.start_with || []).length || d.url ? `<div class="dlinks">${(d.start_with || []).map(v => v.url ? `<a href="${esc(v.url)}" target="_blank">▶ ${esc(v.title)}</a>` : `<span>▶ ${esc(v.title)}</span>`).join(' · ')}${d.url ? `${(d.start_with || []).length ? ' · ' : ''}<a href="${esc(d.url)}" target="_blank">open ${KIND[d.kind] ? KIND[d.kind].replace(/^\S+ /, '') : 'page'} ↗</a>` : ''}</div>` : ''}
    </div>`; }).join('') || '<div class="muted">No suggestions yet — click <b>Find sources</b>.</div>';
  if (!keepMsg && show.length && show[0].note) $('#discMsg').textContent = show[0].note;
}


export const moduleName = "sources";
