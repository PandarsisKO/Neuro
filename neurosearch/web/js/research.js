// ---- research (G5) ----
globalThis.stTag = function stTag(x) { return `<span class="st ${esc(x)}">${esc((x || '').replace('_', ' '))}</span>`; }
globalThis.trunc = function trunc(s, n) { s = String(s || ''); return s.length > n ? s.slice(0, Math.max(0, n - 1)) + '…' : s; }
globalThis.renderResearch = function renderResearch(st) {
  const m = st.map || { nodes: [], counts: {} };
  if (typeof st.attention === 'number') $('#nResearch').textContent = st.attention ? (st.attention + (st.attention_capped ? '+' : '')) : '';   // R3: what needs you, not how many Claims exist
  $('#resMap').innerHTML = m.nodes.length ? m.nodes.map(n => `<div class="kn">${stTag(n.state)}<div><b>${esc(n.topic)}</b> <span class="muted">· ${n.claims_total} claim${n.claims_total === 1 ? '' : 's'}${n.targets_open ? ` · ${n.targets_open} open target${n.targets_open === 1 ? '' : 's'}` : ''}${n.tensions_open ? ` · ${n.tensions_open} tension${n.tensions_open === 1 ? '' : 's'}` : ''}</span><div class="why">${esc(n.why || '')}</div></div></div>`).join('')
    : `<div class="muted">No Claims yet — approve some findings (or press Refresh) and the map builds itself at no cost.</div>`;
  const ts = st.tensions || [];
  $('#resTensions').innerHTML = ts.length ? ts.map(t => `<div class="kn tension">${stTag(t.impact)}<div><b>${esc(t.kind.replace('_', ' '))}</b> <div class="why">${esc(t.description)}</div></div><span style="margin-left:auto;display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end"><button class="small ghost" onclick="tensionStatus('${t.id}','resolved')">Resolved</button> <button class="small ghost" onclick="tensionStatus('${t.id}','dismissed')">Dismiss</button></span></div>`).join('')
    : `<div class="muted">None open — no contradictions, single-source outliers, weak consensus, stale Claims or missing perspectives detected.</div>`;
  const tg = (st.targets || []).filter(t => t.status !== 'closed_by_user' && t.status !== 'dropped');
  $('#resTargets').innerHTML = tg.length ? tg.map(t => {
    const esc_ = t.last_escalation && t.last_escalation.steps ? t.last_escalation.steps : null;
    const trail = esc_ ? `<div class="why">Looked: ${esc_.map(s => s.step === 'external' ? (s.run ? 'web search queued' : 'web not run') : `${s.step.replace('_', ' ')} ${s.found}${s.resurfaced ? ` (${s.resurfaced} resurfaced)` : ''}`).join(' → ')}</div>` : '';
    const known = t.known_uncaptured ? `<div class="why">${t.known_uncaptured} promising source${t.known_uncaptured === 1 ? '' : 's'} known, not captured — <button class="small" onclick="captureBest('${t.id}', ${Math.min(3, t.known_uncaptured)})" title="Attach if already owned; otherwise capture through the normal path (your browser when the server cannot read it). Never a web search.">Capture best ${Math.min(3, t.known_uncaptured)}</button> <a href="#" onclick="showKnown('${t.id}');return false">see them</a></div>` : '';
    return `<div class="kn">${stTag(t.status === 'satisfied' ? 'strong' : 'missing')}<div><b>${esc(t.question)}</b> <span class="muted">· ${t.sufficiency}${t.origin === 'model' || t.origin === 'tension' ? ' · proposed' : ''}</span><div class="why">Enough = ${esc(t.closure || '')}${t.gap ? ` — <b>gap:</b> ${esc(t.gap)}` : ' — satisfied'}</div>${trail}${known}</div><span style="margin-left:auto;display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end"><button class="small" onclick="pursueTarget('${t.id}',false)" title="Project evidence → global library → seen-not-added (reranked against this target) — no web, no model call">Look ($0)</button> <button class="small ghost" onclick="pursueTarget('${t.id}',true)" title="…then a web Discover run for this exact question">+ web</button> <button class="small ghost" onclick="targetStatus('${t.id}','closed_by_user')">Close</button></span></div>`; }).join('')
    : `<div class="muted">No evidence targets yet.</div>`;
  // Claims itself is rendered by the R7 workbench (loadClaimsWorkbench) — a separate, filtered, paged query over the
  // FULL claim set, not this bootstrap state's 300-cap. This function still fills the map/tensions/targets above.
}
// ---- R7: the Claims workbench — filters, facets, sort, paging, batch accept/reject, one plain-language line per Claim.
// RESEARCH-TAB.md §5 asked for this when R2 was designed; R2 moved the old flat list under a tab without rebuilding it.
globalThis.CW = { q: '', status: 'all', strength: '', freshness: '', needs_decision: false, sort: 'priority', offset: 0, limit: 30, sel: new Set() };
globalThis.CWG = { collapsed: new Set() };   // remembers which area-groups the user closed by hand (area -> closed)
globalThis.claimCard = function claimCard(c) {
  const ev = (c.evidence || []).map(e => `<a class="chip" href="${esc(e.link || '#')}" target="_blank" title="${esc(e.relation)} · ${esc(e.evidence_class || '')}${e.independent ? '' : ' · repeats another source'}${e.stale ? ' · STALE (source revised)' : ''}">${e.relation === 'CONTRADICTS' ? '✗ ' : e.relation === 'QUALIFIES' ? '≈ ' : ''}${esc(trunc(e.title || 'source', 34))}${e.locator ? ' @ ' + esc(e.locator) : ''}${e.independent ? '' : ' ↩'}</a>`).join('');
  return `<div class="kn" style="${c.status === 'rejected' ? 'opacity:.5' : ''}"><input type="checkbox" style="margin-top:3px" ${CW.sel.has(c.id) ? 'checked' : ''} onchange="claimSel('${c.id}',this.checked)">${stTag(c.strength)}<div class="grow min-w-0"><div>${esc(c.text)}</div><div class="why"><b>${esc(c.plain)}</b> · ${esc(c.type_label)}${c.area ? ` · ${esc(c.area)}` : ''}<span title="${esc(c.strength_why || '')}"> — ${esc((c.strength_why || '').slice(0, 140))}</span></div><div style="margin-top:2px">${ev}${c.evidence_total > (c.evidence || []).length ? `<span class="muted"> +${c.evidence_total - c.evidence.length} more</span>` : ''}</div></div><span style="margin-left:auto;display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end">${c.status !== 'accepted' ? `<button class="small" title="You stand behind this: it counts as settled for its research area, and the plan and chat may lean on it. Reversible — nothing is deleted." onclick="claimStatus('${c.id}','accepted')">Accept</button> ` : ''}${c.application !== 'established' ? `<button class="small ghost" onclick="claimStatus('${c.id}','${c.status}','established')" title="You judge that this applies to your situation">Applies to us</button> ` : ''}${c.status !== 'rejected' ? `<button class="small ghost" title="You do not accept this: it stops counting as evidence for its area. Nothing is deleted and it is reversible." onclick="claimStatus('${c.id}','rejected')">Reject</button>` : ''}</span></div>`;
}
globalThis.claimSel = function claimSel(id, on) { if (on) CW.sel.add(id); else CW.sel.delete(id); renderClaimsBulkBar(); }
globalThis.renderClaimsBulkBar = function renderClaimsBulkBar() {
  $('#cwBulk').hidden = !CW.sel.size;
  $('#cwBulk').innerHTML = CW.sel.size ? `<div class="banner" style="display:flex;gap:8px;align-items:center"><span class="grow"><b>${CW.sel.size}</b> selected</span><button class="small" onclick="claimsBulk('accepted')">Accept all</button><button class="small ghost" onclick="claimsBulk('rejected')">Reject all</button><button class="small ghost" onclick="CW.sel.clear();renderClaimsBulkBar();loadClaimsWorkbench()">Clear</button></div>` : '';
}
globalThis.claimsBulk = async function claimsBulk(status) {
  const ids = [...CW.sel];
  if (!confirm(`${status === 'accepted' ? 'Accept' : 'Reject'} ${ids.length} Claim${ids.length === 1 ? '' : 's'}? You can change any of them back individually afterward.`)) return;
  const r = await post(`/api/projects/${state.project.id}/claims/bulk-status`, { claim_ids: ids, status });
  toast(`${r.changed} ${status}${r.skipped ? ` · ${r.skipped} skipped` : ''}`); CW.sel.clear(); renderClaimsBulkBar(); loadClaimsWorkbench();
}
globalThis.loadClaimsWorkbench = async function loadClaimsWorkbench() {
  const p = new URLSearchParams({ status: CW.status, strength: CW.strength, freshness: CW.freshness, needs_decision: CW.needs_decision, sort: CW.sort, limit: CW.limit, offset: CW.offset });
  if (CW.q) p.set('q', CW.q); if (RES.area) p.set('area', RES.area);
  let r; try { r = await api(`/api/projects/${state.project.id}/claims?` + p); } catch (e) { $('#resClaims').innerHTML = '<div class="muted">could not load Claims</div>'; return; }
  const f = r.facets;
  $('#cwCount').textContent = `${r.total} match${r.total === 1 ? 'es' : ''} this filter · ${f.needs_decision} need${f.needs_decision === 1 ? 's' : ''} a decision`;
  // PRODUCT-ORGANIZATION.md #9/#12: group this page by the same Area the Overview/Areas panes already name — pointless
  // once a single area is already the filter (RES.area), since every row would share the one group.
  const grouping = $('#cwGroupToggle') && $('#cwGroupToggle').checked && !RES.area;
  const byArea = []; const aidx = {};
  if (grouping) for (const c of r.claims) { const k = c.area || 'Everything else'; if (!(k in aidx)) { aidx[k] = byArea.length; byArea.push([k, []]); } byArea[aidx[k]][1].push(c); }
  $('#cwGroupCtl').hidden = !(grouping && byArea.length > 1);
  if (!r.claims.length) {
    $('#resClaims').innerHTML = `<div class="empty">Nothing matches this filter${RES.area ? ' in this area' : ''}.</div>`;
  } else if (!grouping || byArea.length <= 1) {
    $('#resClaims').innerHTML = r.claims.map(claimCard).join('');
  } else {
    if (CWG.collapsed === 'all') CWG.collapsed = new Set(byArea.map(([k]) => k));
    const searching = !!CW.q || CW.needs_decision || !!CW.strength || !!CW.freshness;
    $('#resClaims').innerHTML = byArea.map(([area, list]) => {
      const open = searching || byArea.length <= 4 || !CWG.collapsed.has(area);
      const keyJs = JSON.stringify(area).replace(/"/g, '&quot;');
      return `<details class="fgroup" ${open ? 'open' : ''} ontoggle="this.open?CWG.collapsed.delete(${keyJs}):CWG.collapsed.add(${keyJs})"><summary class="gh"><b>${esc(area)}</b><span>${list.length}</span></summary>${list.map(claimCard).join('')}</details>`;
    }).join('');
  }
  const pages = Math.max(1, Math.ceil(r.total / CW.limit));
  const cur = Math.floor(CW.offset / CW.limit) + 1;
  $('#cwPager').innerHTML = r.total > CW.limit ? `<button class="small ghost" ${cur <= 1 ? 'disabled' : ''} onclick="CW.offset=Math.max(0,CW.offset-CW.limit);loadClaimsWorkbench()">‹ prev</button><span class="muted">page ${cur} of ${pages}</span><button class="small ghost" ${cur >= pages ? 'disabled' : ''} onclick="CW.offset+=CW.limit;loadClaimsWorkbench()">next ›</button>` : '';
  renderClaimsBulkBar();
}
// "Why this answer" (RESEARCH-TAB.md §5): a chat citation opens the Claims resting on that source, closest locator first.
globalThis.whyThisAnswer = async function whyThisAnswer(sourceId, locator) {
  if (!sourceId) return;
  $('#dlgBody').innerHTML = '<span class="spin"></span> checking what this source became…'; dlg.showModal();
  let r; try { r = await api(`/api/projects/${state.project.id}/claims/for-source?source_id=${encodeURIComponent(sourceId)}&locator=${encodeURIComponent(locator || '')}`); } catch (e) { $('#dlgBody').innerHTML = esc(e.message); return; }
  $('#dlgBody').innerHTML = `<b>Why this answer</b> <span class="muted">· ${r.total} Claim${r.total === 1 ? '' : 's'} rest${r.total === 1 ? 's' : ''} on this source</span>` +
    (r.claims.length ? r.claims.map(c => `<div class="kn" style="${c.matched_here ? '' : 'opacity:.75'}">${stTag(c.strength)}<div class="grow"><div>${esc(c.text)}</div><div class="why"><b>${esc(c.plain)}</b> · ${esc(c.type_label)}${c.matched_here ? ' · this exact passage' : ''}</div></div><span style="margin-left:auto;display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end">${c.status !== 'accepted' ? `<button class="small" title="You stand behind this: it counts as settled for its research area, and the plan and chat may lean on it. Reversible — nothing is deleted." onclick="claimStatus('${c.id}','accepted');dlg.close()">Accept</button>` : ''}</span></div>`).join('')
      : '<div class="muted">This source has not become a Claim yet — it may be too new, or its findings did not carry a proposition worth harvesting.</div>') +
    `<div class="row" style="margin-top:10px"><button class="small ghost" onclick="dlg.close();showView('research');resPane('claims')">See all Claims</button></div>`;
}
// "Settle this" (RESEARCH-TAB.md §5): a chat gap becomes an Evidence Target in one click, through the normal path.
globalThis.settleGap = async function settleGap(gap) {
  const r = await post(`/api/projects/${state.project.id}/targets`, { question: gap, sufficiency: 'corroborative' });
  toast(r ? '⏵ added to Open questions' : 'could not add — too short');
}
// ---- S3: the source drawer — one place per source (value · findings · Claims · where used · staleness) ----
globalThis.sourceDrawer = async function sourceDrawer(sid) {
  $('#dlgBody').innerHTML = '<span class="spin"></span> reading everything this source gave…'; dlg.showModal();
  let d; try { d = await api(`/api/projects/${state.project.id}/sources/${sid}/digest`); }
  catch (e) { $('#dlgBody').innerHTML = `<div class="muted">could not load: ${esc(e.message)}</div>`; return; }
  const s = d.source, v = d.value, st = d.staleness, u = d.used_in;
  // SM-3: same fix as useBadges() above -- 🧠 reserved for the Research nav item, text names its subject.
  const badge = f => { const b = []; if (f.used.plan) b.push('<span class="tag" title="cited by the Master Plan">in plan</span>');
    if (f.used.chat) b.push(`<span class="tag" title="cited in ${f.used.chat} chat answer(s)">cited ${f.used.chat}×</span>`);
    if (f.used.claim) b.push(`<span class="tag" title="became or evidences a Claim">Claim: ${esc(f.used.claim)}</span>`);
    return b.join(' '); };
  const group = (key, label, actions) => {
    const list = d.findings[key] || []; if (!list.length) return '';
    return `<div style="margin-top:10px"><b>${label} (${list.length})</b>${actions || ''}</div>` + list.slice(0, 60).map(f => `
      <div class="f"><span class="fi" title="importance ${f.importance || 0}/5">${'●'.repeat(f.importance || 0)}<span class="dim">${'●'.repeat(5 - (f.importance || 0))}</span></span>
        <div class="main"><div class="ttl">${esc(f.title || (f.content || '').slice(0, 90))}</div>
          <div class="meta">${badge(f)} ${f.locator ? `<a class="chip" href="${esc(f.link || '#')}" target="_blank">▶ ${esc(f.locator)}</a>` : ''}${f.area ? `<span class="tag muted">${esc(f.area)}</span>` : ''}</div></div>
        <div class="act">${key === 'reserve' ? `<button class="small primary" title="Approve" aria-label="Approve" onclick="drawerNote(${f.id},'approved','${sid}')"><svg class="ic"><use href="#ic-approve"></use></svg></button><button class="small" title="Send to Suggested" aria-label="Send to Suggested" onclick="drawerNote(${f.id},'suggested','${sid}')"><svg class="ic"><use href="#ic-flag"></use></svg></button>`
          : key === 'suggested' ? `<button class="small primary" title="Approve" aria-label="Approve" onclick="drawerNote(${f.id},'approved','${sid}')"><svg class="ic"><use href="#ic-approve"></use></svg></button><button class="small ghost" title="Dismiss" aria-label="Dismiss" onclick="drawerNote(${f.id},'dismissed','${sid}')"><svg class="ic"><use href="#ic-dismiss"></use></svg></button>`
          : key === 'approved' ? `<button class="small ghost" title="Dismiss" aria-label="Dismiss" onclick="drawerNote(${f.id},'dismissed','${sid}')"><svg class="ic"><use href="#ic-dismiss"></use></svg></button>`
          : key === 'dismissed' ? `<button class="small ghost" title="Put it back in the review queue" onclick="drawerNote(${f.id},'suggested','${sid}')">↩ Restore</button>` : ''}</div></div>`).join('');
  };
  const staleLine = st.status === 'current' ? '<span class="st strong">current</span>'
    : st.status === 'current_accepted' ? '<span class="st developing">accepted as still usable</span>'
    : st.status === 'rebuilding' ? '<span class="st developing">re-analysing…</span>'
    : st.status ? `<span class="st weak">${esc((st.status || '').replace('_', ' '))}</span> <span class="muted">${esc((st.reasons || []).join('; '))}</span>` : '';
  const oneSource = st.status === 'stale' || st.status === 'legacy_unverified'
    ? `<button class="small primary" onclick="drawerRebuild('${sid}')">Re-read it${st.tier === 'rebuild_transcript' ? ' — its transcript changed' : ''}</button>` +
      (st.tier !== 'rebuild_transcript' ? `<button class="small ghost" title="Keep these findings and stop flagging it until the inputs change again" onclick="drawerAccept('${sid}')">Accept as still usable</button>` : '')
    : '';
  $('#dlgBody').innerHTML = `
    <div class="row" style="align-items:baseline;gap:8px;flex-wrap:wrap"><b class="text-base">${esc(s.title)}</b>
      ${s.url && s.url.startsWith('http') ? `<a class="muted" href="${esc(s.url)}" target="_blank">open ↗</a>` : ''}
      ${v.priority ? '<span class="tag">★ priority</span>' : ''}${s.depth === 'deep' ? '<span class="tag">🔬 deep-read</span>' : ''}${s.long ? '<span class="tag">📚 long-form</span>' : ''}</div>
    <div class="muted">${esc(s.channel || s.platform)}${s.published_at ? ' · ' + esc(s.published_at) : ''}${s.duration ? ' · ' + fmt(s.duration) : ''} · ${staleLine}</div>
    <div class="card mt-2"><b>What it gave you</b><div>${esc(v.label)}</div>
      ${v.why.length ? `<div class="why">Why it matters: ${v.why.map(esc).join(' · ')}</div>` : v.never_used ? `<div class="why">Nothing has used it yet — no plan step, chat answer or Claim rests on it.</div>` : ''}
      <div class="row" style="gap:6px;margin-top:8px;flex-wrap:wrap">
        <button class="small" onclick="dlg.close();askAboutSource('${sid}',${JSON.stringify(s.title).replace(/"/g, '&quot;')})">Ask about this source</button>
        <button class="small ghost" onclick="dlg.close();viewTranscript('${sid}')">${s.platform === 'book' ? '📖 Read' : s.platform === 'spreadsheet' ? 'Contents' : 'Transcript'}</button>
        ${s.long && s.depth !== 'deep' ? `<button class="small ghost" title="Read it again in smaller parts and keep every specific finding" onclick="dlg.close();readDeeper('${sid}')">Read deeper</button>` : ''}
        ${oneSource}
      </div></div>
    ${(u.plan.uses || []).length || (u.chat || []).length ? `<div style="margin-top:10px"><b>Where it shows up</b></div>` +
      (u.plan.uses || []).map(p => `<div class="kn"><span class="st strong">📋 plan</span><div><b>${esc(p.where)}</b>${p.text ? `<div class="why">${esc(p.text)}</div>` : ''}</div></div>`).join('') +
      (u.chat || []).map(c => `<div class="kn"><span class="st developing">💬 chat</span><div><b>${esc(c.conversation)}</b> <span class="muted">· ${esc((c.locators || []).join(', '))}</span><div class="why">${esc(c.snippet)}</div></div></div>`).join('')
      : ''}
    ${d.claims.length ? `<div style="margin-top:10px"><b>Claims resting on it (${d.claims.length})</b></div>` + d.claims.slice(0, 12).map(c => `<div class="kn">${stTag(c.strength)}<div><div>${esc((c.text || '').slice(0, 200))}</div><div class="why">${esc(c.claim_type)}${c.independent ? '' : ' · repeats another source'}${c.stale ? ' · evidence stale' : ''}${c.locator ? ' · ' + esc(c.locator) : ''}</div></div></div>`).join('') : ''}
    ${group('approved', 'Approved findings')}
    ${group('suggested', 'Waiting for review')}
    ${group('reserve', 'Extracted beyond the cap', ' <span class="muted" style="font-weight:normal;font-size:12px">— lower importance, kept rather than thrown away</span>')}
    ${group('dismissed', 'Dismissed')}
    ${d.findings_total ? '' : '<div class="muted" style="margin-top:10px">No findings from this source yet.</div>'}`;
}
globalThis.drawerNote = async function drawerNote(id, status, sid) { await post(`/api/notes/${id}/status`, { status }); sourceDrawer(sid); if (state.view === 'findings') loadNotes(); if (state.view === 'sources') loadSources(); }
globalThis.drawerRebuild = async function drawerRebuild(sid) { await post(`/api/projects/${state.project.id}/rebuild-stale`, { what: ['findings'], source_ids: [sid], transport: 'interactive' }); toast('↻ queued'); dlg.close(); loadJobs(); if (state.view === 'sources') loadSources(); }
globalThis.drawerAccept = async function drawerAccept(sid) { await post(`/api/projects/${state.project.id}/staleness/accept`, { source_ids: [sid] }); toast('kept as still usable'); sourceDrawer(sid); loadStaleness(); }
globalThis.askAboutSource = function askAboutSource(sid, title) {
  state.attached.push({ id: sid, name: title });
  $('#qAttach').innerHTML = `<span class="chip" title="pinned to your next question">📎 ${esc(title.slice(0, 60))}</span>`;
  showView('chat'); setTimeout(() => { const q = $('#q'); if (q) { q.placeholder = `Ask about "${title.slice(0, 40)}"…`; q.focus(); } }, 100);
}
// ---- R2: the Research shell — one $0 request renders every pane (research_view.overview?full=1) ----
globalThis.RES = { pane: 'overview', area: null, v: null, state: null, next: [], qs: [], wos: [], open: {} };
globalThis.resSay = function resSay(m) { const el = $('#resMsg'); if (el) el.textContent = m || ''; }
globalThis.loadResearch = async function loadResearch() {
  try { RES.v = await api(`/api/projects/${state.project.id}/research/overview?full=1&limit=6`); }
  catch (e) { resSay('could not load: ' + e.message); return; }
  $('#nResearch').textContent = RES.v.attention ? (RES.v.attention + (RES.v.attention_capped ? '+' : '')) : '';   // 0.63.23: the card says 99+, so the badge must too
  RES.qs = RES.v.questions || []; RES.wos = RES.v.watchouts || []; RES.next = RES.v.next || [];
  if (RES.state) { try { RES.state = await api(`/api/projects/${state.project.id}/research`); renderResearch(RES.state); } catch (e) { } }
  renderShell();
}
globalThis.resLoadState = async function resLoadState() {
  if (RES.state) return RES.state;
  resSay('loading Claims…');
  RES.state = await api(`/api/projects/${state.project.id}/research`);
  renderResearch(RES.state); loadEvaluation(); resSay('');
  return RES.state;
}
globalThis.resPane = function resPane(name) { RES.pane = name; if (name === 'tools') resLoadState().catch(e => resSay(e.message)); if (name === 'claims') { CW.offset = 0; CW.sel.clear(); loadClaimsWorkbench().catch(e => resSay(e.message)); } renderShell(); }
globalThis.resSetArea = async function resSetArea(a) {
  RES.area = (RES.area === a) ? null : a;
  if (RES.pane === 'overview' || RES.pane === 'areas') RES.pane = 'questions';
  renderShell();                                   // draw immediately from what is already loaded
  if (RES.area && RES.v && RES.v.questions_truncated) { await resAreaQuestions(RES.area); renderShell(); }
  if (RES.state) renderResearch(RES.state);
  if (RES.pane === 'claims') loadClaimsWorkbench();
}
globalThis.resClearArea = function resClearArea() { RES.area = null; renderShell(); if (RES.state) renderResearch(RES.state); if (RES.pane === 'claims') loadClaimsWorkbench(); }
globalThis.areaChip = function areaChip(a) { return a ? `<span class="chipf ${RES.area === a ? 'on' : ''}" title="Show only this area" onclick="resSetArea(${JSON.stringify(a).replace(/"/g, '&quot;')})">${esc(a)}</span>` : ''; }
globalThis.inArea = x => !RES.area || x.area === RES.area;

globalThis.renderShell = function renderShell() {
  const v = RES.v; if (!v) return;
  const s = v.summary || {};
  const openQ = RES.qs.filter(q => q.status === 'open'), issues = RES.wos.filter(w => w.impact === 'high' || w.impact === 'medium');
  // SM-5: this tab used to count the paged client list (openQ.length) while the Overview stat tile beside it
  // counts the server total (s.important_questions) -- same screen, same concept, an order of magnitude
  // apart. The tile already has the number; the tab drops its own.
  const tabs = [['overview', 'Overview', null], ['questions', 'Open questions', null], ['watchouts', 'Watch-outs', RES.wos.length],
                ['areas', 'Areas', (v.areas || []).length], ['claims', 'Claims', s.claims_total], ['tools', 'Research tools', null]];
  $('#resNav').innerHTML = tabs.map(([k, l, n]) => `<span class="chipf ${RES.pane === k ? 'on' : ''}" onclick="resPane('${k}')">${l}${n != null ? ` <b>${n}</b>` : ''}</span>`).join('');
  $('#resHead').innerHTML = v.empty ? 'nothing to research yet — approve some findings first'
    : `<b>${v.attention}</b> need${v.attention === 1 ? 's' : ''} you${v.attention_capped ? '+' : ''} · ${s.claims_total} Claim${s.claims_total === 1 ? '' : 's'} from your findings, all built at no cost`;
  $('#resAreaBar').innerHTML = RES.area ? `<div class="banner" style="display:flex;gap:8px;align-items:center"><span class="grow">Showing only <b>${esc(RES.area)}</b></span><button class="small ghost" onclick="resClearArea()">show everything</button></div>` : '';
  for (const [k] of tabs) { const el = $('#pane' + k[0].toUpperCase() + k.slice(1)); if (el) el.hidden = RES.pane !== k; }
  if (RES.pane === 'overview') renderOverview();
  if (RES.pane === 'questions') renderQuestionsPane();
  if (RES.pane === 'watchouts') renderWatchoutsPane();
  if (RES.pane === 'areas') renderAreasPane();
}

globalThis.renderOverview = function renderOverview() {
  const v = RES.v, s = v.summary || {};
  if (v.empty) { $('#paneOverview').innerHTML = `<div class="empty">No Claims yet. Approve findings in 📌 Findings — the research state builds itself from them at no cost.</div>`; return; }
  const stat = (n, l, t) => `<div style="flex:1;min-width:120px"><div style="font-size:20px;font-weight:600">${n}</div><div class="muted text-xs" title="${esc(t || '')}">${l}</div></div>`;
  const nxt = RES.next.filter(inArea);
  $('#paneOverview').innerHTML =
    `<div class="card row" style="gap:14px;flex-wrap:wrap">
      ${stat(s.important_questions, 'important open questions', 'Open questions on findings you rated 4–5, or that the Master Plan depends on')}
      ${stat(s.issues, 'watch-outs worth acting on', 'High or medium impact issues — stale evidence, contradictions, one-sided topics, lone viewpoints')}
      ${stat(s.claims_awaiting_decision, 'Claims awaiting your decision', 'Strong, important, still proposed — accept or reject them')}
      ${stat(`${(v.areas || []).filter(a => a.strong > 0).length}/${s.areas_total}`, 'areas with a well-evidenced conclusion', 'Areas where at least one Claim is Strong. The rest rest on single or repeated sources — the open questions above are how they move.')}
    </div>
    <h3 class="mt-4">Do these next</h3>
    <div class="muted" style="margin-bottom:6px">Ranked by what it costs you to leave it alone: importance, whether the Master Plan rests on it, impact, and how many Claims it touches. Everything here is $0 unless a button says otherwise.</div>
    ${nxt.length ? nxt.map((x, i) => x.type === 'watchout' ? woCard(x, RES.wos.indexOf(RES.wos.find(w => w.id === x.id))) : qCard(x, RES.qs.indexOf(RES.qs.find(q => q.id === x.id)))).join('')
      : `<div class="empty">Nothing pressing${RES.area ? ' in this area' : ''} — the open questions and watch-outs that remain are lower priority.</div>`}
    ${(v.recently_improved || []).length ? `<h3 class="mt-4">Recently improved</h3>` + v.recently_improved.map(r => `<div class="kn"><span class="st strong">${r.kind === 'claim_strong' ? 'accepted' : 'settled'}</span><div><div>${esc(r.text)}</div>${r.detail ? `<div class="why">${esc(r.detail)}</div>` : ''}</div></div>`).join('') : ''}
    <h3 class="mt-4">Areas <span class="muted" style="font-weight:normal;font-size:12px">— what this project is actually about, grouped from your findings</span></h3>
    ${(v.areas || []).slice(0, 8).map(areaCard).join('')}
    ${(v.areas || []).length > 8 ? `<div class="muted"><a href="#" onclick="resPane('areas');return false">see all ${v.areas.length} areas →</a></div>` : ''}`;
}

globalThis.woCard = function woCard(w, i) {
  const cover = RES.qs.filter(q => q.status === 'open' && (w.underlying || []).some(u => u.claim_id && u.claim_id === q.claim_id));
  const oid = 'wo' + i;
  return `<div class="kn tension"><div class="grow min-w-0">
    <div>${stTag(w.impact)} <b>${esc(w.title)}</b> ${areaChip(w.area)}</div>
    <div class="why">${esc(w.detail)}</div>
    <div class="why">If you leave it: ${esc(w.if_ignored)}</div>
    <div class="row" style="gap:6px;margin-top:6px;flex-wrap:wrap">
      ${cover.length ? `<button class="small primary" title="${esc(w.action.help)}" onclick="resPursueMany(${i})">${esc(w.action.label)} · $0</button>` : ''}
      <button class="small ghost" onclick="resToggle('${oid}')">Show the ${w.claims} Claim${w.claims === 1 ? '' : 's'}</button>
      <button class="small ghost" title="This is handled — clear it" onclick="resWo(${i},'resolved')">Resolved</button>
      <button class="small ghost" title="Never bring this up again for this project. A later refresh will not reopen it." onclick="resWo(${i},'dismissed')">Not important to my project</button>
    </div>
    <div id="${oid}" style="margin-top:6px" hidden>${(w.underlying || []).map(u => `<div class="why" style="padding:5px 0;border-top:1px solid var(--line)">${esc(u.claim || u.description)}</div>`).join('')}</div>
  </div></div>`;
}

globalThis.qCard = function qCard(q, i) {
  const acts = (q.actions || []).map((a, ai) => `<button class="small ${ai === 0 ? 'primary' : 'ghost'}" title="${esc(a.help)} — ${esc(a.cost)}" onclick="resQAct(${i},${ai})">${esc(a.label)}${a.cost === '$0' ? ' · $0' : ' · ' + esc(a.cost)}</button>`).join('');
  return `<div class="kn"><div class="grow min-w-0">
    <div>${stTag(q.status === 'satisfied' ? 'strong' : q.important ? 'developing' : 'missing')} <b>${esc(q.headline || q.question)}</b> ${areaChip(q.area)}</div>
    <div class="why">${esc(q.current)}</div>
    <div class="why">Still needed: ${esc(q.gap)} · ${esc(q.what_settles_it)} · asked because ${esc(q.why_asking)}</div>
    ${(q.already_checked || []).length ? `<div class="why">Already looked in: ${q.already_checked.map(esc).join(' · ')}</div>` : ''}
    ${q.known_uncaptured ? `<div class="why">${q.known_uncaptured} promising source${q.known_uncaptured === 1 ? '' : 's'} known but not captured — <a href="#" onclick="showKnown('${q.id}');return false">see them</a></div>` : ''}
    <div class="row" style="gap:6px;margin-top:6px;flex-wrap:wrap">${acts}
      <button class="small ghost" title="Which sources you already partly own are worth reading more of, ranked by what each has already given this project" onclick="whereToLook('${q.id}')">Where to look · $0</button>
      <button class="small ghost" title="Close it — you do not need this question answered" onclick="resQClose(${i})">Settle · not needed</button></div>
  </div></div>`;
}

// C2/C3 (0.58.3): gap analysis used to start every search from nothing. This shows which master sources are worth
// reading more of, ranked by what each has ALREADY given this project, with the numbers behind every line.
globalThis.whereToLook = async function whereToLook(targetId) {
  let r; try { r = await api(`/api/projects/${state.project.id}/where-to-look?limit=8` + (targetId ? `&target_id=${encodeURIComponent(targetId)}` : '')); }
  catch (e) { return toast('could not work out where to look'); }
  const rows = r.rows || [];
  $('#dlgBody').innerHTML = `<h3 style="margin:0 0 4px">Where to look</h3>
    ${r.question ? `<div class="why" style="margin-bottom:6px">For: ${esc(r.question)}${(r.wanted_classes || []).length ? ` · needs ${r.wanted_classes.map(esc).join(', ')} evidence` : ''}</div>` : ''}
    <p class="muted" style="margin:0 0 10px">${esc(r.note)}</p>
    ${rows.length ? rows.map(x => `<div class="kn"><div class="grow min-w-0">
        <div><b>${esc(x.creator)}</b> <span class="muted">· ${x.untapped} unread · ${x.read} read · ${x.findings} findings (${x.per_source} per source)</span>${x.proven ? ' <span class="st strong">proven here</span>' : ''}</div>
        ${(x.why || []).map(w => `<div class="why">${esc(w)}</div>`).join('')}
        <div class="why">${x.expected_findings != null ? `Reading the next 10 would be worth roughly ${x.expected_findings} findings — an extrapolation from your own history with this source, not a promise.` : `Too few of this source's items read to project a rate from yet.`}</div>
      </div><button class="small primary" onclick="dlg.close();poolFilter(${JSON.stringify(x.creator).replace(/"/g, '&quot;')})">See what is left</button></div>`).join('')
      : `<div class="empty">Nothing to recommend yet. A source is only suggested once it has both given this project findings AND has material you have not read — ${r.considered || 0} source${r.considered === 1 ? '' : 's'} considered.</div>`}`;
  dlg.showModal();
}
// The pool already filters on creator (`q` matches title + creator + reasons), so this reuses the existing view
// rather than adding a second one: Sources → 🔎 Known, not captured, filtered to that creator, ranked by fit.
globalThis.poolFilter = function poolFilter(creator) {
  try {
    state.srcFilter = 'pool'; POOL.rank = 'fit'; POOL.kind = 'all';
    showView('sources');
    $('#srcQ').value = creator;
    loadSources();
  } catch (e) { toast(`open Sources → 🔎 Known, not captured and search for ${creator}`); }
}

globalThis.areaCard = function areaCard(a) {
  return `<div class="kn"><div class="grow min-w-0">
    <div>${stTag(a.state)} <b>${esc(a.name)}</b> <span class="muted">· ${a.claims} Claim${a.claims === 1 ? '' : 's'}</span></div>
    <div class="why">You understand: ${esc(a.understand)}${(a.attention || []).length ? ' · Needs work: ' + a.attention.map(esc).join(', ') : ''}</div>
    </div><button class="small ghost" onclick="resSetArea(${JSON.stringify(a.name).replace(/"/g, '&quot;')})">${RES.area === a.name ? '✕ clear' : 'Focus'}</button></div>`;
}

// 0.62.7: this pane rendered EVERY open question as a full card. On Kyle's project that is 2,667 of them, from a
// 4.8 MB slice of a 5.9 MB payload — the same defect the Sources list had before 0.46.3 and the Findings list
// before 0.60.1. The shell now carries the most important 200 and the rest are fetched a page at a time, in the
// same order, so a page boundary is never a change of subject.
globalThis.renderQuestionsPane = function renderQuestionsPane() {
  const open = RES.qs.filter(q => q.status === 'open' && inArea(q)), rest = RES.qs.filter(q => q.status !== 'open' && inArea(q));
  const total = RES.v.questions_open != null ? RES.v.questions_open : open.length;
  const more = RES.qs.length < (RES.v.questions_total || 0) && !RES.area;
  $('#paneQuestions').innerHTML =
    `<div class="muted">What is not settled yet, in plain language: what would settle it, what the evidence says now, what is missing, and where to look — cheapest first. Nothing here spends money unless the button says so.</div>
     <h3 class="mt-3">Open (${open.length}${total > open.length ? ` of ${total}` : ''})</h3>
     ${total > open.length ? `<div class="muted" style="font-size:12.5px;margin-bottom:6px">Showing the ${open.length} most important. ${RES.area ? '' : 'Nothing is hidden — load more below.'}</div>` : ''}
     ${open.length ? open.map(q => qCard(q, RES.qs.indexOf(q))).join('') : `<div class="empty">No open questions${RES.area ? ' in this area' : ''}.</div>`}
     ${more ? `<div style="margin-top:10px"><button class="small" onclick="resMoreQuestions(this)">Load the next 200 of ${RES.v.questions_total}</button></div>` : ''}
     ${rest.length ? `<h3 style="margin-top:14px">Settled (${rest.length})</h3>` + rest.slice(0, 30).map(q => `<div class="kn"><span class="st strong">settled</span><div><div>${esc(q.headline || q.question)}</div><div class="why">${esc(q.current)}</div></div></div>`).join('') : ''}`;
}
globalThis.resMoreQuestions = async function resMoreQuestions(btn) {
  const was = btn.textContent; btn.disabled = true; btn.textContent = 'loading…';
  try {
    const r = await api(`/api/projects/${state.project.id}/research/questions?offset=${RES.qs.length}&limit=200`);
    const have = new Set(RES.qs.map(q => q.id));
    RES.qs = RES.qs.concat((r.questions || []).filter(q => !have.has(q.id)));   // ids, not indexes: qCard uses index into RES.qs
    renderShell();
  } catch (e) { btn.disabled = false; btn.textContent = was; toast(e.message || e, 'err'); }
}
globalThis.resAreaQuestions = async function resAreaQuestions(area) {
  // Focusing an area must not be answered from a truncated list, or an area with nothing in the first page reads
  // as empty when it is not.
  try {
    const r = await api(`/api/projects/${state.project.id}/research/questions?limit=200&area=${encodeURIComponent(area)}`);
    const have = new Set(RES.qs.map(q => q.id));
    RES.qs = RES.qs.concat((r.questions || []).filter(q => !have.has(q.id)));
  } catch (e) { /* the inline page still renders; this only adds to it */ }
}

globalThis.renderWatchoutsPane = function renderWatchoutsPane() {
  const ws = RES.wos.filter(inArea);
  $('#paneWatchouts').innerHTML =
    `<div class="muted">Problems with the evidence itself, grouped into issues — not one row per Claim. Acting on one covers every Claim behind it.</div>
     <div class="mt-3">${ws.length ? ws.map(w => woCard(w, RES.wos.indexOf(w))).join('') : `<div class="empty">None open${RES.area ? ' in this area' : ''} — no stale evidence, contradictions, one-sided topics or lone viewpoints detected.</div>`}</div>`;
}

globalThis.renderAreasPane = function renderAreasPane() {
  const v = RES.v;
  $('#paneAreas').innerHTML =
    `<div class="muted">What this project is about, grouped from your findings at no cost. Focus an area to filter the questions, watch-outs and Claims below it. "Everything else" holds Claims whose harvested topic was a single generic word — a normalisation pass (Research tools) is what labels those.</div>
     <div class="mt-3">${(v.areas || []).map(areaCard).join('') || '<div class="empty">No areas yet.</div>'}</div>`;
}

globalThis.resToggle = function resToggle(id) { const el = $('#' + id); if (el) el.hidden = !el.hidden; }
globalThis.resWo = async function resWo(i, status) {
  const w = RES.wos[i]; if (!w) return;
  if (status === 'dismissed' && !confirm(`Dismiss "${w.title}" for good? It covers ${w.claims} Claim${w.claims === 1 ? '' : 's'} and a later refresh will not bring it back.`)) return;
  resSay('…');
  try { const r = await post(`/api/projects/${state.project.id}/tensions/bulk-status`, { tension_ids: (w.underlying || []).map(u => u.tension_id), status });
    resSay(`${r.changed} ${status === 'dismissed' ? 'dismissed' : 'resolved'}`); } catch (e) { resSay(e.message); }
  loadResearch();
}
globalThis.resPursueMany = async function resPursueMany(i) {
  const w = RES.wos[i]; if (!w) return;
  const cover = RES.qs.filter(q => q.status === 'open' && (w.underlying || []).some(u => u.claim_id && u.claim_id === q.claim_id));
  resSay(`looking in your own research for ${cover.length} question${cover.length === 1 ? '' : 's'}…`);
  let found = 0;
  for (const q of cover.slice(0, 8)) {
    try { const r = await post(`/api/targets/${q.id}/pursue`, { external: false }); found += (r.escalation.steps || []).reduce((n, s) => n + (s.found || 0), 0); } catch (e) { }
  }
  resSay(`checked this project, your library and previously seen sources — ${found} possible source${found === 1 ? '' : 's'} found. Nothing was attached; see each question.`);
  loadResearch();
}
globalThis.resQAct = async function resQAct(i, ai) {
  const q = RES.qs[i], a = (q.actions || [])[ai]; if (!q || !a) return;
  resSay(a.label + '…');
  try {
    const r = await post(a.endpoint, a.body || {});
    if (a.endpoint.endsWith('/pursue')) {
      const st = (r.escalation || {}).steps || [];
      resSay(st.map(s => s.step === 'external' ? (s.run ? 'web search queued' : '') : `${s.step.replace('_', ' ')}: ${s.found}`).filter(Boolean).join(' · '));
    } else if (a.endpoint.endsWith('/capture-best')) {
      const jobs_ = (r.started || []).filter(x => x.how === 'job').length, att = (r.started || []).length - jobs_;
      resSay(`${att ? att + ' attached from your library' : ''}${att && jobs_ ? ' · ' : ''}${jobs_ ? jobs_ + ' capture' + (jobs_ === 1 ? '' : 's') + ' queued' : ''}`); loadJobs();
    } else resSay('done');
  } catch (e) { resSay(e.message); }
  loadResearch();
}
globalThis.resQClose = async function resQClose(i) {
  const q = RES.qs[i]; if (!q || !confirm(`Settle "${q.label || q.question}"? It leaves the research state and the chat's context.`)) return;
  await post(`/api/targets/${q.id}/status`, { status: 'closed_by_user' }); loadResearch();
}
globalThis.refreshResearch = async function refreshResearch(extract) {
  $('#resMsg').textContent = extract ? 'normalising…' : 'refreshing…';
  try { const r = await post(`/api/projects/${state.project.id}/research/refresh`, { extract }); renderResearch(r.state);
    const x = r.extracted || {}; $('#resMsg').textContent = `harvested ${r.harvested}` + (extract ? (x.calls != null ? ` · ${x.normalized} normalised, ${x.targets} targets proposed (${x.calls} call${x.calls === 1 ? '' : 's'})` : x.job ? ' · queued as a job' : x.error ? ' · ' + x.error : '') : '');
  } catch (e) { $('#resMsg').textContent = e.message; }
}
globalThis.evaluateNormalisation = async function evaluateNormalisation() {
  if (!confirm('Run one bounded normalisation evaluation (about 150 Claims, ~8 model calls)?')) return;
  $('#resMsg').textContent = 'queued…';
  try { const r = await post(`/api/projects/${state.project.id}/research/evaluate`, { budget: 150 }); $('#resMsg').textContent = 'evaluation running as a job (' + Object.entries(r.cohort_preview || {}).map(([k, v]) => `${v} ${k}`).join(', ') + ')'; loadJobs(); setTimeout(loadEvaluation, 15000); }
  catch (e) { $('#resMsg').textContent = e.message; }
}
globalThis.loadEvaluation = async function loadEvaluation() {
  const r = await api(`/api/projects/${state.project.id}/research/evaluation`); const el = $('#resEval'); if (!el) return;
  if (r.none) { el.textContent = ''; return; }
  const t = r.tensions || {};
  el.innerHTML = `<b>Last normalisation evaluation</b> · ${r.cohort.size} Claims (${Object.entries(r.cohort.by_reason || {}).map(([k, v]) => `${v} ${k}`).join(', ')}) · ${r.calls} call${r.calls === 1 ? '' : 's'} · $${(r.cost_usd || 0).toFixed(3)} · merged ${r.merged} · qualifiers present ${r.qualifiers_present}/${r.cohort.size} · hedges kept ${r.hedges_kept}/${r.hedged_before} · over-generalised ${(r.over_generalized || []).length} · topics ${r.topics.before} → ${r.topics.after} · weak-consensus ${t.before?.WEAK_CONSENSUS ?? '?'} → ${t.after?.WEAK_CONSENSUS ?? '?'} · targets proposed ${r.targets_proposed}`;
}
globalThis.claimStatus = async function claimStatus(id, status, application) { await post(`/api/claims/${id}/status`, { status, application: application || null }); loadResearch(); }
globalThis.tensionStatus = async function tensionStatus(id, status) { await post(`/api/tensions/${id}/status`, { status }); loadResearch(); }
globalThis.targetStatus = async function targetStatus(id, status) { await post(`/api/targets/${id}/status`, { status }); loadResearch(); }
globalThis.captureBest = async function captureBest(tid, n) { $('#resMsg').textContent = 'capturing…'; try { const r = await post(`/api/targets/${tid}/capture-best`, { n }); const jobs_ = r.started.filter(x => x.how === 'job').length, att = r.started.length - jobs_; $('#resMsg').textContent = `${att ? att + ' attached from the library' : ''}${att && jobs_ ? ' · ' : ''}${jobs_ ? jobs_ + ' capture' + (jobs_ === 1 ? '' : 's') + ' queued' + (r.started.some(x => x.acquisition_hint === 'browser_likely') ? ' (some will need your browser — see Sources → Browser capture)' : '') : ''}`; } catch (e) { $('#resMsg').textContent = e.message; } loadResearch(); loadJobs(); }
globalThis.showKnown = async function showKnown(tid) { const k = await api(`/api/targets/${tid}/known`); $('#dlgBody').innerHTML = `<b>Known, not captured</b> <span class="muted">· ${k.known_uncaptured} source${k.known_uncaptured === 1 ? '' : 's'}${k.browser_likely ? ` · ${k.browser_likely} likely need your browser` : ''}</span>` + (k.best.map(b => `<div class="row" style="padding:6px 0;border-top:1px solid var(--line)"><span class="grow"><a href="${esc(b.url)}" target="_blank">${esc(b.title || b.url)}</a> <span class="muted">· fit ${b.relevance ?? '?'}${b.num_comments ? ' · ' + b.num_comments + ' comments' : ''}${b.acquisition_hint === 'browser_likely' ? ' · browser capture likely' : ''}</span></span><button class="small ghost" onclick="post('/api/candidates/${b.candidate_id}/dismiss-link',{project_id:state.project.id,kind:'evidence_target',ref_id:'${tid}'}).then(()=>{dlg.close();loadResearch()})" title="Not useful for this question — the source stays known">Not for this</button></div>`).join('') || '<div class="muted">nothing linked yet — press Look on the question first</div>'); dlg.showModal(); }
globalThis.addTarget = async function addTarget() { const q = $('#resTargetQ').value.trim(); if (!q) return; await post(`/api/projects/${state.project.id}/targets`, { question: q, sufficiency: $('#resTargetS').value }); $('#resTargetQ').value = ''; loadResearch(); }
globalThis.pursueTarget = async function pursueTarget(id, external) { $('#resMsg').textContent = 'looking…'; try { const r = await post(`/api/targets/${id}/pursue`, { external }); const st = r.escalation.steps; $('#resMsg').textContent = st.map(s => s.step === 'external' ? (s.run ? 'web search queued' : '') : `${s.step.replace('_', ' ')}: ${s.found}`).filter(Boolean).join(' · '); } catch (e) { $('#resMsg').textContent = e.message; } loadResearch(); if (external) loadJobs(); }
globalThis.renderResearchHeader = function renderResearchHeader(r) {
  const el = $('#discResearch'); if (!el) return;
  if (!r || !r.counts) { el.innerHTML = ''; return; }
  const c = r.counts; const tg = r.targets || [], ts = r.tensions || [];
  el.innerHTML = `<div class="kn"><div><b>Research state</b> <span class="muted">· strong ${c.strong || 0} · developing ${c.developing || 0} · weak ${c.weak || 0} · missing ${c.missing || 0} — <a href="#" onclick="showView('research');return false">open the map</a></span>` +
    (tg.length ? `<div class="why">Open evidence targets steering this search: ${tg.slice(0, 4).map(t => esc(t.question.slice(0, 90))).join(' · ')}</div>` : '') +
    (ts.length ? `<div class="why">⚠ ${ts.slice(0, 2).map(t => esc(t.description.slice(0, 120))).join(' · ')}</div>` : '') + `</div></div>`;
}
globalThis.runDiscover = async function runDiscover() {
  const btn = $('#discBtn'); btn.disabled = true;
  const t0 = Date.now(), tick = m => { $('#discMsg').innerHTML = `<span class="spin"></span> ${esc(m || 'searching the web for the people worth learning from')} · ${Math.round((Date.now() - t0) / 1000)}s (first results in ~10 s, links verified after)`; };
  tick();
  try {
    const r = await post(`/api/projects/${state.project.id}/discover`, { refine: $('#discRefine').value || null, background: true, mode: $('#discMode').value });
    if (r.job_id) {
      for (;;) {
        await new Promise(res => setTimeout(res, 2500));
        const j = await api(`/api/jobs/${r.job_id}`);
        if (j.status === 'done') { const res = j.result || {}; $('#discMsg').textContent = (res.note || '') + (res.added === 0 && !res.web_skipped ? ' (nothing new beyond what was already suggested)' : ''); renderSeen(res.seen); renderLibrarySuggestions(res.library); renderResearchHeader(res.research); break; }
        if (j.status === 'failed') { $('#discMsg').textContent = 'error: ' + (j.message || 'discover failed'); break; }
        tick(j.message);
        if ((j.progress || 0) >= 0.45) loadDiscoveries(true);   // first take is in — show it while links are verified
      }
    } else { $('#discMsg').textContent = (r.note || '') + (r.added === 0 ? ' (nothing new beyond what was already suggested)' : ''); }
    await loadDiscoveries();
  } catch (e) { $('#discMsg').textContent = 'error: ' + e.message; }
  btn.disabled = false;
}
globalThis.discStatus = async function discStatus(id, status) { await post(`/api/discoveries/${id}/status`, { status }); loadDiscoveries(); }
globalThis.discAdd = async function discAdd(id, url, whole, btn) {
  // 0.60.1 (Kyle): "clicking on a button does not give immediate user feedback that something happened". The work
  // is queued, so there is nothing to show when it completes — what was missing was an acknowledgement that the
  // click landed. The button says so itself, and is disabled so the same source cannot be queued twice by an
  // impatient second click.
  if (whole && !confirm('List these videos for review? Nothing is downloaded until you approve the list in Sources.')) return;
  const label = btn ? btn.textContent : '';
  if (btn) { btn.disabled = true; btn.textContent = '⏳ adding…'; }
  try {
    await post('/api/ingest', { url, tags: [], project_id: state.project.id, force: false });
    await post(`/api/discoveries/${id}/status`, { status: 'added' });
    if (btn) btn.textContent = whole ? 'listed ✓' : 'added ✓';
    toast(whole ? '🔍 listing them for review — approve the list in Sources' : '⏵ queued — it appears in Sources as it is read');
  } catch (e) {
    if (btn) { btn.disabled = false; btn.textContent = label; }
    toast(e.message || e, 'err');
    return;
  }
  loadDiscoveries(); loadJobs(); loadSources();
}

globalThis.addFromLibrary = async function addFromLibrary(id, btn) {
  const label = btn ? btn.textContent : '';
  if (btn) { btn.disabled = true; btn.textContent = '⏳ adding…'; }
  try { await post(`/api/projects/${state.project.id}/members`, { source_ids: [id] }); if (btn) btn.textContent = 'added ✓'; toast('✓ added to this project — nothing was re-downloaded'); }
  catch (e) { if (btn) { btn.disabled = false; btn.textContent = label; } return toast(e.message || e, 'err'); }
  loadLibrary(); loadSources();
}
// ================= BOOTSTRAP R3: Starting Research =================
// What Neuro Search already owns that this project could use. Every row's reason is a PASSAGE the user can click
// and check — never "highly relevant to your goal", which is what you get when you ask a model to explain a
// retrieval it did not perform. Nothing here is attached until the user says so; attaching adds a membership row
// and never copies, re-downloads or re-transcribes anything.
globalThis.BOOT = { open: new Set(), showAll: false, busy: false };
globalThis.bootWhy = function bootWhy(h) {
  const p = (h.passages || [])[0];
  return `<div class="muted" style="font-size:12px;margin-top:3px">${esc((h.why || []).join(' · '))}</div>` +
    (p ? `<div style="font-size:12px;margin-top:4px;padding:6px 8px;border-left:2px solid var(--line)">${p.link ? `<a href="${esc(p.link)}" target="_blank" rel="noopener">${esc(p.timestamp || 'open')}</a> ` : ''}${esc(p.text || '')}</div>` : '');
}
globalThis.bootRow = function bootRow(h) {
  const open = BOOT.open.has(h.source_id);
  return `<div class="job" style="flex-wrap:wrap;align-items:flex-start">
    <input type="checkbox" class="bootPick" value="${h.source_id}" ${h.band === 'strong' && !h.from_old_matcher ? 'checked' : ''} style="margin-top:5px">
    <div class="grow min-w-0">
      <div style="overflow:hidden;text-overflow:ellipsis">${esc(h.title || h.source_id)}${h.channel ? ` <span class="muted text-xs">· ${esc(h.channel)}</span>` : ''}</div>
      ${open ? bootWhy(h) : `<div class="muted" style="font-size:12px;margin-top:3px">${esc((h.why || [])[0] || '')}</div>`}
    </div>
    <span class="tag" title="${h.band === 'strong' ? 'matched more than one part of your goal, and one passage covers most of it' : 'matched, but less of your goal'}">${h.band === 'strong' ? 'strong' : 'possible'}</span>${h.from_old_matcher ? `<span class="tag status-warn" title="Judged by the library matcher as it was before 0.60.2. Scan again to re-judge it — free.">older matcher</span>` : ''}${h.weak_query_only ? `<span class="tag status-warn" title="It matched only the generic words in your goal, not anything specific to the subject.">generic match</span>` : ''}
    <button class="small ghost" onclick="BOOT.open.has('${h.source_id}') ? BOOT.open.delete('${h.source_id}') : BOOT.open.add('${h.source_id}'); renderBoot();">${open ? 'Hide why' : 'Why'}</button>
  </div>`;
}
globalThis.BOOTSTATE = null;
globalThis.loadBoot = async function loadBoot() {
  if (!state.project) return;
  try { globalThis.BOOTSTATE = await api(`/api/projects/${state.project.id}/bootstrap`); } catch (e) { globalThis.BOOTSTATE = null; }
  renderBoot();
}
globalThis.renderBoot = function renderBoot() {
  const el = $('#bootCard'); if (!el) return;
  const b = BOOTSTATE;
  const pending = (b?.sources || []).filter(h => h.state === 'suggested');
  const live = pending.filter(h => !h.weak_query_only);
  if (!b || (!pending.length && !b.run)) { el.hidden = true; return; }
  const c = b.counts, run = b.run || {};
  const shown = BOOT.showAll ? live : live.filter(h => h.band === 'strong').concat(live.filter(h => h.band !== 'strong').slice(0, 5));
  const projs = (b.projects || []).slice(0, 4);
  el.hidden = false;
  el.innerHTML = `<b>${live.length ? 'Research in your library that may help this project' : 'No specific matches in the last library scan'}</b>
    <div class="muted mt-1">${c.strong} strong matches${c.possible ? ` · ${c.possible} possible matches` : ''}${run.scope ? ` · searched ${run.scope} sources outside this project` : ''}. These are sources you already own.</div>
    ${c.attached ? `<div class="muted">Already added ${c.attached} sources from your library.</div>` : ''}
    ${b.stale ? `<div class="banner" style="margin:8px 0">The project brief or open research gaps changed. Scan again for current suggestions.</div>` : ''}
    ${b.matcher_stale ? `<div class="banner" style="margin:8px 0">${esc(b.matcher_note || '')} <button class="small primary" onclick="rescanBoot()">Scan again — free</button></div>` : ''}
    ${c.weak_query_only ? `<div class="muted" style="margin-top:6px">Excluded ${c.weak_query_only} sources that matched only generic wording, without a specific connection to this project.</div>` : ''}
    ${projs.length ? `<div class="muted mt-2">Where it lives: ${projs.map(p => `<span class="tag" title="${esc(p.line)}">${esc(p.name)} — ${p.relevant} of ${p.total}</span>`).join(' ')}</div>` : ''}
    <div class="mt-2">${shown.map(bootRow).join('')}</div>
    <div class="row" style="margin-top:8px;flex-wrap:wrap">
      ${shown.length ? `<button class="small primary" onclick="bootDecide('attach')">Add selected</button><button class="small ghost" onclick="bootDecide('dismiss')">Not useful</button>` : ''}
      ${live.length > shown.length ? `<button class="small ghost" onclick="BOOT.showAll=true;renderBoot()">Show all ${live.length}</button>` : ''}
      <span class="grow"></span><button class="small ghost" onclick="rescanBoot()">Scan again</button>
    </div>`;
}

globalThis.bootDecide = async function bootDecide(decision) {
  if (BOOT.busy) return;
  const ids = [...document.querySelectorAll('#bootCard .bootPick:checked')].map(i => i.value);
  if (!ids.length) { toast('Nothing selected'); return; }
  BOOT.busy = true;
  try {
    const r = await post(`/api/projects/${state.project.id}/bootstrap/decide`, { source_ids: ids, decision });
    toast(decision === 'attach' ? `✓ Added ${r.count} source${r.count === 1 ? '' : 's'} you already owned` : `Hid ${r.count}`);
    if (decision === 'attach') { loadSources().catch(() => {}); }
  } catch (e) { toast(e.message || e, 'err'); }
  BOOT.busy = false; loadBoot();
}
globalThis.rescanBoot = async function rescanBoot() {
  try { await post(`/api/projects/${state.project.id}/bootstrap`, {}); toast('🔎 searching what you already own'); }
  catch (e) { toast(e.message || e, 'err'); }
  loadJobs(); setTimeout(loadBoot, 1500);
}
globalThis.jobsTimer = undefined;
globalThis.jobLabel = function jobLabel(j) {
  const what = j.label || j.payload.url || j.payload.name || j.payload.source_id || '';
  if (j.kind === 'suggest_findings') return 'finding suggestions · ' + what;
  if (j.kind === 'suggest_findings_batch') { const n = (j.payload.source_ids || []).length || j.batch?.sources || 0; return `background analysis · ${n} source${n === 1 ? '' : 's'}${j.payload.reason === 'stale' ? ' (stale rebuild)' : ''}`; }
  if (j.kind === 'rank_proposed') return 'ranking videos by relevance';
  if (j.kind === 'ingest_source') return 'transcript · ' + what;
  if (j.kind === 'refresh_skipped_metadata') return 'refreshing skipped info · ' + what;
  if (j.kind === 'bootstrap_scan') return 'searching research you already have';
  if (j.kind === 'extract_claims') return j.payload?.evaluation ? 'checking claim quality' : 'finding claims to track';
  if (j.kind === 'refresh_research') return 'bringing the research state up to date';
  if (j.kind === 'settle_batches') return 'collecting finished batches (already paid for)';
  return what || j.kind;
}
globalThis.rateResume = async function rateResume() {
  try { await post('/api/usage/rate-resume', {}); toast('▶ paid background work released'); } catch (e) { toast(e.message || e, 'err'); }
  loadJobs();
}
globalThis.retryJob = async function retryJob(id) { await post(`/api/jobs/${id}/retry`, {}).catch(e => toast(e.message || e, 'err')); toast('Queued again'); loadJobs(); }
globalThis.retryFailed = async function retryFailed() { const r = await post('/api/jobs/retry-failed', { project_id: state.project.id }); toast(`↻ ${r.retried} job${r.retried === 1 ? '' : 's'} queued again`); loadJobs(); }
globalThis.dismissJob = async function dismissJob(id) { await post(`/api/jobs/${id}/dismiss`, {}).catch(e => toast(e.message || e, 'err')); loadJobs(); }
globalThis.cancelJob = async function cancelJob(id) { await post(`/api/jobs/${id}/cancel`, {}).catch(e => alert(e.message || e)); globalThis.rvSig = null; loadJobs(); loadReviews(); }
globalThis.bumpJob = async function bumpJob(id) { await post(`/api/jobs/${id}/bump`, {}).catch(e => toast(e.message || e, 'err')); toast('⏫ moved to the front of the queue'); loadJobs(); }
globalThis.CHECK_NOW_STATES = new Set(['budget_wait', 'rate_limit_wait', 'provider_wait', 'retry_wait']);
globalThis.checkNowJob = async function checkNowJob(id) { await post(`/api/jobs/${id}/check-now`, {}).catch(e => toast(e.message || e, 'err')); toast('🔄 checking now — this will run next'); loadJobs(); }
// "How do I know it's actually doing anything?" (Kyle, live). A running job writes a heartbeat every time it
// finishes a unit of work, so the age of that heartbeat is the honest liveness signal — a number that changes on
// every poll. It is never invented: if the job has gone quiet, the tag says so instead of pretending.
globalThis.liveTag = function liveTag(j) {
  if (j.status !== 'running' || !j.updated_at) return '';
  const q = Math.round(Date.now() / 1000 - j.updated_at);
  if (q > 180) return ` <span class="status-warn" title="no progress update for a while — it will time out and retry on its own">· quiet for ${ago(j.updated_at)}</span>`;
  return ` <span class="muted" title="the worker reported progress this recently — this is what tells you it is alive" style="font-size:11px">· alive ${q < 5 ? 'just now' : q + 's ago'}</span>`;
}
globalThis.pollFails = 0;
globalThis.JOBSBOX = { expanded: (() => { try { return localStorage.getItem('ns_jobsbox') === 'all'; } catch (e) { return false; } })() };
globalThis.toggleJobsBox = function toggleJobsBox() {
  JOBSBOX.expanded = !JOBSBOX.expanded;
  try { localStorage.setItem('ns_jobsbox', JOBSBOX.expanded ? 'all' : 'hot'); } catch (e) {}
  loadJobs();
}
globalThis.loadJobs = async function loadJobs() {
  clearTimeout(jobsTimer);
  let js;
  try { js = await api(`/api/projects/${state.project.id}/jobs?limit=30`); globalThis.pollFails = 0; $('#offline')?.remove(); }
  catch (e) {
    // server restarting (auto-reload after an update) or briefly unreachable: keep polling instead of going quiet
    globalThis.pollFails++;
    if (!$('#offline')) { const d = document.createElement('div'); d.id = 'offline'; d.className = 'banner'; d.style.cssText = 'position:fixed;top:8px;right:12px;z-index:99'; d.textContent = '⟳ reconnecting to the server…'; document.body.appendChild(d); }
    globalThis.jobsTimer = setTimeout(pollTick, Math.min(3000 * pollFails, 15000));
    return;
  }
  const active = js.filter(j => j.status === 'queued' || j.status === 'running' || j.status === 'external_pending');
  const STATE_LABEL = { queued: 'queued', running: 'running', blocked: 'blocked', retry_wait: 'retry wait', budget_wait: 'budget wait', rate_limit_wait: 'rate-limit wait', provider_wait: 'waiting for provider', external_pending: 'in background', external_tentative: 'verifying', external_handle_ambiguous: 'verifying', cancelling: 'cancelling', failed: 'failed', done: 'done', cancelled: 'cancelled' };
  const stateClass = st => ({ blocked: 'queued', retry_wait: 'queued', budget_wait: 'queued', rate_limit_wait: 'queued', provider_wait: 'queued', external_pending: 'queued', external_tentative: 'queued', external_handle_ambiguous: 'queued', cancelling: 'running' })[st] || st;
  const jobMsg = j => j.provider_wait ? j.provider_wait.message : j.batch ? j.batch.label : (j.message || '');
  const depLine = j => { const d = j.dependencies; if (!d) return ''; const bad = [...(d.failed || []), ...(d.cancelled || [])]; return `<div class="muted" style="font-size:12px;width:100%;padding-left:8px">${d.done}/${d.total} upstream done${d.pending ? ` · ${d.pending} pending` : ''}${bad.length ? ` · <span class="status-bad">${bad.length} failed: ${esc(bad.map(x => x.label || x.id.slice(0, 8)).join(', '))}</span> <button class="small" onclick="retryJob('${bad[0].id}')">↻ Retry failed analysis</button>` : ''}</div>`; };
  const recentFailed = js.filter(j => j.status === 'failed' && (Date.now() / 1000 - (j.finished_at || j.created_at || 0)) < 6 * 3600).slice(0, 5);
  const show = [...active, ...recentFailed];
  // 0.60.0 (Kyle): with 300+ queued the box was a wall. Collapsed it shows what is ACTUALLY moving — anything
  // running, anything that failed, and the banners — with one line counting the rest; expanded it is unchanged.
  // The queue itself is not touched: this is what the box draws, not what the workers do.
  const isHot = j => j._budget || j.status === 'running' || j.status === 'failed' || j.status === 'cancelling'
    || (j.state || j.status) === 'external_pending' || j.bumped;
  const st = await api('/api/stats'); const u = await loadSpend();
  $('#jobsCard').hidden = !(show.length || st.youtube?.paused || u?.blocked);
  if (u?.blocked) show.unshift({ status: 'queued', payload: { url: `⏸ Queue paused — ${u.blocked}. Nothing is lost; it continues from where it stopped.` }, progress: 0, message: '', _budget: true, _recheck: !u.paused });
  if (st.youtube?.paused) show.unshift({ status: 'queued', payload: { url: `YouTube asked us to slow down — downloads resume automatically in ~${Math.ceil(st.youtube.seconds_left / 60)} min` }, progress: 0, message: '' });
  loadBacklog();
  // 0.51.0: the RATE is the number a human notices. A daily total says nothing about $5 in ten minutes.
  const rt = u && u.rate ? u.rate : null;
  const rateBit = rt ? ` · <span title="spend in the last hour · the ceiling that holds paid background work is $${rt.ceiling.toFixed(2)}/h" style="${rt.blocked ? 'color:var(--warn);font-weight:600' : rt.rate > rt.ceiling * 0.6 ? 'color:var(--warn)' : ''}">$${rt.rate.toFixed(2)}/h</span>` : '';
  if (rt && rt.blocked) show.unshift({ status: 'queued', payload: { url: `⏸ Spending hit $${(rt.at_block || rt.rate).toFixed(2)} in an hour (ceiling $${rt.ceiling.toFixed(2)}/h) — paid background work is held until ${new Date(rt.until * 1000).toLocaleTimeString()}. Your chats, ingests and local work keep running. Nothing is lost.` }, progress: 0, message: '', _budget: true, _rate: true });
  const hot = show.filter(isHot), cold = show.filter(j => !isHot(j));
  const drawn = JOBSBOX.expanded ? show : hot;
  const coldCounts = {};
  cold.forEach(j => { const k = STATE_LABEL[j.state || j.status] || j.status; coldCounts[k] = (coldCounts[k] || 0) + 1; });
  const coldLine = cold.length ? `<div class="row muted" style="font-size:12.5px;padding:2px 0 6px"><span class="grow">${Object.entries(coldCounts).map(([k, n]) => `${n} ${esc(k)}`).join(' · ')}${JOBSBOX.expanded ? '' : ' — not shown'}</span><button class="small ghost" onclick="toggleJobsBox()">${JOBSBOX.expanded ? '▴ Show only what is running' : `▾ Show all ${show.length}`}</button></div>` : '';
  // SM-6: one line, always visible, for what the collapsed jobsPanel is hiding -- "N jobs running · doing X" if
  // anything is actually moving, else a queued count. The full console (spend, Pause/Cancel/Budget, every row)
  // is unchanged; it is just one click away instead of open by default.
  const runningNow = show.filter(j => !j._budget && (j.status === 'running' || (j.state || j.status) === 'external_pending'));
  const queuedCount = show.filter(j => !j._budget).length;
  const jobsSummaryEl = $('#jobsSummary');
  if (jobsSummaryEl) jobsSummaryEl.textContent = !queuedCount ? 'In progress'
    : runningNow.length ? `${runningNow.length} job${runningNow.length === 1 ? '' : 's'} running · ${jobLabel(runningNow[0])}`
    : `${queuedCount} job${queuedCount === 1 ? '' : 's'} queued`;

  $('#jobs').innerHTML = (u ? `<div class="row" style="padding:4px 0 8px;font-size:12.5px"><span class="muted grow">Spend: $${u.today.toFixed(2)} of $${u.daily_budget.toFixed(2)} today · $${u.month.toFixed(2)} of $${u.monthly_budget.toFixed(2)} this month${rateBit}</span><button class="small ${u.paused ? 'primary' : ''}" onclick="togglePause(${!u.paused})">${u.paused ? '▶ Resume queue' : '⏸ Pause queue'}</button><button class="small ${u.background_paused ? 'primary' : 'ghost'}" title="${u.background_paused ? 'Let the speculative work run again — it resumes where it left off' : 'Hold the bulk background work — claim passes (whatever lane they run on), caption recovery, metadata backfill — so it stays out of the way. Your own ingests, findings, ranking and chats keep running.'}" onclick="toggleBackground(${!u.background_paused})">${u.background_paused ? '▶ Resume background' : '⏸ Pause background'}</button><button class="small danger" onclick="cancelQueued()">Cancel queued</button>${recentFailed.length > 1 ? `<button class="small" onclick="retryFailed()">↻ Retry all failed</button>` : ''}<button class="small ghost" onclick="showView('settings')">Budget…</button></div>` : '') + coldLine + drawn.map(j => j._budget ? `<div class="banner" style="margin:4px 0 8px">${esc(j.payload.url)}${j._rate ? ` <button class="small ghost" title="Let paid background work run again now. It will be held again if the rate goes back over the ceiling." onclick="rateResume()">▶ Carry on anyway</button>` : ''}${j._recheck ? ` <button class="small ghost" title="Re-check the account now — if you raised the limit or added credits this clears the block and lets the queue try again. Costs nothing: a refusal fails before any work is done." onclick="recheckAccount()">Re-check account</button>` : ''}</div>` : `<div class="job" style="flex-wrap:wrap"><span class="st ${stateClass(j.state || j.status)}" title="${esc(j.state || j.status)}${j.run_id ? ' · run ' + j.run_id.slice(0, 8) : ''}${j.attempts ? ' · attempts ' + j.attempts : ''}">${j.external_provider === 'browser' && (j.state || j.status) === 'external_pending' ? '🌐 browser needed' : STATE_LABEL[j.state || j.status] || j.status}</span>
    <span style="flex:2;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${j.bumped ? '<span title="moved to the front of the queue">⏫ </span>' : ''}${esc(jobLabel(j))}${j.executed_by ? ` <span class="muted" title="${esc(j.fallback_reason ? 'meant local, ran on the API: ' + j.fallback_reason : 'which AI provider ran this job')}" style="font-size:11px">${j.executed_by === 'local' ? '🖥 local' : j.executed_by === 'mixed' ? '🖥/☁ mixed' : '☁ API' + (j.fallback_reason ? ' (fallback)' : '')}</span>` : (j.execution_policy && j.execution_policy !== 'local_preferred' && (j.status === 'queued' || j.status === 'running') ? ` <span class="muted" style="font-size:11px">${esc(j.execution_policy.replace('_', ' '))}</span>` : '')}</span>
    <div class="bar"><i style="width:${Math.round((j.batch && j.batch.sources ? j.batch.done / j.batch.sources : j.progress) * 100)}%"></i></div><span class="muted grow">${esc(jobMsg(j))}${j.status === 'running' && j.started_at ? ` <span title="running for">· ${ago(j.started_at)}</span>` : ''}${liveTag(j)}</span>${j.status === 'queued' && j.id && CHECK_NOW_STATES.has(j.state) ? `<button class="small ghost" title="Its stored message is a snapshot from when it was first parked — make a fresh attempt right now instead of waiting" onclick="checkNowJob('${j.id}')">Check now</button>` : ''}${j.status === 'queued' && j.id && !j.bumped ? `<button class="small ghost" title="Run this next, ahead of everything else queued" onclick="bumpJob('${j.id}')">⏫ Start next</button>` : ''}${(j.status === 'queued' || j.status === 'running' || j.status === 'external_pending') && j.id && !j.cancel_requested_at ? `<button class="small ghost" title="${j.status === 'queued' ? 'Remove from the queue' : 'Stop at the next safe point'}" aria-label="Cancel job" onclick="cancelJob('${j.id}')"><svg class="ic"><use href="#ic-dismiss"></use></svg></button>` : ''}${j.status === 'failed' && j.id ? `<button class="small" title="Try again" onclick="retryJob('${j.id}')">↻ Retry</button><button class="small ghost" title="Hide this error" aria-label="Hide this error" onclick="dismissJob('${j.id}')"><svg class="ic"><use href="#ic-dismiss"></use></svg></button>` : ''}${j.id ? `<button class="small ghost" title="History" onclick="jobHistory('${j.id}', this)">⋯</button>` : ''}${depLine(j)}</div>`).join('');
  clearTimeout(jobsTimer);
  const analysing = (SRCG.rows || []).some(s => s.analysing || (s.job && s.job.status === 'running'));
  // keep a slow heartbeat even when idle so work started elsewhere (extension, CLI, retries) shows up
  const every = (active.length || analysing) ? 3000 : 15000;
  globalThis.jobsTimer = setTimeout(pollTick, every);
  if (active.some(j => j.kind === 'ingest_url' || j.kind === 'rank_proposed')) setTimeout(() => loadReviews().catch(() => {}), 3500);
}

// R2: the poll asks "did anything change?" (~6 ms) before rebuilding the Sources view (~440 ms). Panes refresh
// only when the revision they depend on has actually moved. A full reconcile every RECONCILE_EVERY ticks means a
// fingerprint that ever missed a change self-corrects within about a minute instead of leaving a stale screen.
globalThis.lastRev = null;
globalThis.ticksSinceFull = 0;
globalThis.RECONCILE_EVERY = 20;
globalThis.pollTick = async function pollTick() {
  if (state.view !== 'sources' || !state.project) return;
  let t;
  try { t = await api(`/api/projects/${state.project.id}/tick`, { ack: false }); }
  catch (e) { loadJobs(); loadSources().catch(() => {}); return; }   // tick unavailable → behave exactly as before
  const rev = t.rev, prev = globalThis.lastRev;
  const changed = k => !prev || prev[k] !== rev[k];
  const full = ++globalThis.ticksSinceFull >= RECONCILE_EVERY;
  if (full) globalThis.ticksSinceFull = 0;
  globalThis.lastRev = rev;
  const srcChanged = full || changed('sources') || changed('jobs') || changed('notes') || changed('research');
  if (full || changed('jobs')) loadJobs(); else globalThis.jobsTimer = setTimeout(pollTick, t.active ? 3000 : 15000);
  if (srcChanged) loadSources().catch(() => {});
  if (full || changed('jobs') || changed('sources')) loadBoot();
}

globalThis.jobHistory = async function jobHistory(id, btn) {
  const ev = await api(`/api/jobs/${id}/events`);
  const row = btn.closest('.job'); let box = row.querySelector('.jobhist');
  if (box) { box.remove(); return; }
  box = document.createElement('div'); box.className = 'jobhist muted'; box.style.cssText = 'width:100%;font-size:11.5px;font-family:ui-monospace,monospace;white-space:pre;overflow:auto;max-height:180px;padding:4px 8px';
  box.textContent = ev.map(e => { const t = new Date(e.ts * 1000).toLocaleTimeString(); const p = e.payload || {}; const extra = e.stage ? e.stage : (p.worker_id ? 'worker ' + p.worker_id.split(':').pop() : p.message || p.handle || p.delay ? (p.message || p.handle || `wait ${Math.round(p.delay / 60)} min`) : ''); return `${t}  ${e.event_type.padEnd(20)} ${e.run_id ? 'run ' + e.run_id.slice(0, 6) + '  ' : ''}${extra}`; }).join('\n') || 'no events';
  row.appendChild(box);
}
// ---- findings ----
globalThis.STALE = { data: null };
globalThis.reviewItem = function reviewItem(title, why, body, open = false) {
  return `<details class="review-item" ${open ? 'open' : ''}><summary><span class="grow"><b>${title}</b><span class="muted text-xs"> — ${why}</span></span></summary><div class="review-item-body">${body}</div></details>`;
}
globalThis.syncFindingsReview = function syncFindingsReview() {
  const hub = $('#findingsReview'); if (!hub) return;
  const n = hub.querySelectorAll('.review-item').length;
  hub.hidden = !n;
  const count = $('#findingsReviewCount'); if (count) count.textContent = n ? `${n} item${n === 1 ? '' : 's'}` : '';
}
globalThis.loadStaleness = async function loadStaleness() {
  try { STALE.data = await api(`/api/projects/${state.project.id}/staleness`); } catch (e) { STALE.data = null; return; }
  const s = STALE.data;
  const nf = $('#nFindings'), np = $('#nPlan');
  if (nf) nf.classList.toggle('stale', s.stale_sources > 0);
  if (np) np.classList.toggle('stale', s.plan.status === 'stale');
  renderTriageCard('staleFindings');
  renderStaleCard('stalePlan', 'plan');
}
// S1: the stale set as three answers — rebuild (matters / transcript changed) · accept as still usable · retry failed
globalThis.renderTriageCard = async function renderTriageCard(elId) {
  const el = $('#' + elId); if (!el) return;
  const s = STALE.data; if (!s) { el.innerHTML = ''; return; }
  const reb = s.sources.filter(x => x.status === 'rebuilding');
  if (!s.stale_sources && !s.legacy_sources && !reb.length) { el.innerHTML = ''; syncFindingsReview(); return; }
  if (STALE.left) { el.innerHTML = ''; syncFindingsReview(); return; }
  let t; try { t = await api(`/api/projects/${state.project.id}/staleness/triage`); } catch (e) { el.innerHTML = ''; syncFindingsReview(); return; }
  STALE.triage = t;
  const T = t.tiers;
  const row = (key, label, btn, danger) => { const x = T[key]; if (!x || !x.count) return '';
    const names = x.sources.slice(0, 3).map(r => esc((r.title || '').slice(0, 48))).join(' · ') + (x.count > 3 ? ` · +${x.count - 3}` : '');
    const why = key === 'rebuild_matters' ? ` <span class="muted">(${esc([...new Set(x.sources.flatMap(r => r.why))].slice(0, 3).join('; '))})</span>` : key === 'retry_failed' ? ` <span class="muted">(${esc([...new Set(x.sources.map(r => (r.reasons.find(z => z.startsWith('last rebuild failed')) || '').replace('last rebuild failed: ', '')))].slice(0, 2).join(' / ').slice(0, 140))})</span>` : '';
    return `<div class="row" style="margin-top:6px;gap:8px;align-items:flex-start;flex-wrap:wrap"><div class="grow min-w-0"><b>${x.count}</b> ${label}${why}<div class="muted text-xs">${names}</div><div class="muted text-xs">${esc(t.explain[key])}</div></div>
      <div style="display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end">${btn(x)}</div></div>`; };
  // 0.45.2: both currencies on every button. The local price is time, the API price is dollars; the card shows each tier's
  // two options side by side so "faster" is a thing you can SEE and press, not something you have to know exists.
  // 0.45.3: three prices, because there are three. Free-but-hours, half-price-in-the-background, full-price-now.
  const fastBtn = (x, key, label) => !x.api_cost ? '' :
    ` <button class="small ${x.local_line ? '' : 'primary'}" title="One background batch through the Message Batches API — half the price of running it now, and it does not tie up Claude Code. Results land source by source." onclick="rebuildTier('${key}', 'batch')">${label} in the background · ${esc(x.batch_line.replace(' on the API in the background', ''))}</button>` +
    (x.local_line ? ` <button class="small" title="Queues them and moves them straight onto the API pool — minutes instead of hours" onclick="rebuildTier('${key}', 'api')">${label} now · ${esc(x.api_line)}</button>` : '');
  const rebuildBtns = (x, key) => `<button class="small ${x.local_line ? 'primary' : ''}" title="${t.local ? 'Runs on Claude Code in the background — $0, but slow' : 'Runs on the API'}" onclick="rebuildTier('${key}')">Rebuild · ${esc(x.cost_line)}</button>${fastBtn(x, key, 'Rebuild')}`;
  const acceptBtns = x => `<button class="small" onclick="acceptTier('accept')">Accept ${x.count} as still usable</button> <button class="small ghost" onclick="rebuildTier('accept')" title="Re-read them anyway">Rebuild · ${esc(x.cost_line)}</button>${fastBtn(x, 'accept', 'Rebuild')}`;
  const retryBtns = x => `<button class="small" onclick="rebuildTier('retry_failed')">Retry ${x.count} · ${esc(x.cost_line)}</button>${fastBtn(x, 'retry_failed', 'Retry')}`;
  // 0.61.0: a warning that says ZERO is worse than no warning. This card appears whenever anything is
  // re-analysing, so the headline has to be built from what is actually non-zero — Kyle's screen read
  // "⚠ 0 sources analysed against older inputs · 15 re-analysing", which is a scary way to say "working".
  const head = t.stale_total
    ? `⚠ ${t.stale_total} source${t.stale_total === 1 ? '' : 's'} analysed against older inputs`
    : (reb.length ? `⟳ Re-analysing ${reb.length} source${reb.length === 1 ? '' : 's'}` : 'Source analysis');
  const body = `${t.accepted ? `<span class="muted">${t.accepted} accepted as still usable.</span>` : ''}${t.stale_total && reb.length ? ` <span class="muted">${reb.length} re-analysing.</span>` : ''}
    <div class="muted">Every option below shows both prices — hours on Claude Code, or dollars on the API — and nothing runs unless you ask.${t.local ? '' : ' Claude Code is not active: costs are API dollars.'}</div>
    ${row('rebuild_matters', 'stale AND carrying weight', x => rebuildBtns(x, 'rebuild_matters'))}
    ${row('rebuild_transcript', 'whose transcript changed', x => rebuildBtns(x, 'rebuild_transcript'))}
    ${row('retry_failed', 'whose last rebuild failed', retryBtns)}
    ${row('accept', 'stale only because the brief changed, carrying no weight', acceptBtns)}
    <div class="row mt-2"><span class="muted grow text-xs">${s.plan.status === 'stale' ? 'The Master Plan is rebuilt after the sources it rests on (see the Plan tab).' : ''}</span><button class="small ghost" onclick="STALE.left=1;renderTriageCard('${elId}')">Hide for now</button></div>`;
  el.innerHTML = reviewItem(head, t.stale_total ? 'source inputs changed; existing findings remain usable until you decide' : 'source analysis is currently running', body, true);
  syncFindingsReview();
}
globalThis.rebuildTier = async function rebuildTier(tier, mode) {
  const T = (STALE.triage && STALE.triage.tiers && STALE.triage.tiers[tier]) || {};
  const slow = T.local_line ? T.local_line.replace('$0 · about ', '').replace(' on Claude Code', '').replace(/ \(\d+ at a time\)/, '') : 'hours';
  if (mode === 'batch' && !confirm(`Re-read ${T.count} source${T.count === 1 ? '' : 's'} as one background batch for about $${(T.batch_cost || 0).toFixed(2)}?\n\nThat is half what running them now costs ($${(T.api_cost || 0).toFixed(2)}) because the Message Batches API discounts the model tokens. It runs in the background and results land source by source, so it does not tie up Claude Code or make you wait ${slow}.`)) return;
  if (mode === 'api' && !confirm(`Re-read ${T.count} source${T.count === 1 ? '' : 's'} on the API right now for about ${T.api_line}?\n\nThey finish in minutes instead of ${slow} on Claude Code. The same work as a background batch is about half this ($${(T.batch_cost || 0).toFixed(2)}) if you can wait. Each job still passes the daily budget on its own.`)) return;
  const r = await post(`/api/projects/${state.project.id}/rebuild-stale`, { what: ['findings'], tier, transport: mode === 'batch' ? 'batch' : 'interactive' });
  let msg = `${r.queued} job${r.queued === 1 ? '' : 's'} queued`;
  if (mode === 'batch') msg = `${T.count} queued as one background batch · est. $${(T.batch_cost || 0).toFixed(2)}`;
  if (mode === 'api' && r.queued) {
    const a = await post(`/api/projects/${state.project.id}/accelerate`, { n: r.queued, order: 'value' });
    msg += ` · ${a.moved} moved to the API, est. $${(a.api_cost || 0).toFixed(2)}`;
  }
  toast(msg); loadStaleness(); loadJobs();
}
globalThis.acceptTier = async function acceptTier(tier) {
  const r = await post(`/api/projects/${state.project.id}/staleness/accept`, { tier });
  toast(`${r.accepted} accepted as still usable${r.refused ? ` · ${r.refused} refused (transcript changed)` : ''}`); loadStaleness();
}
globalThis.renderStaleCard = function renderStaleCard(elId, what) {
  const el = $('#' + elId); if (!el) return;
  const s = STALE.data; if (!s) { el.innerHTML = ''; return; }
  const money = v => '$' + (+v).toFixed(2);
  let h = '';
  if (what === 'findings') {
    const stale = s.sources.filter(x => x.status === 'stale'), legacy = s.sources.filter(x => x.status === 'legacy_unverified'), reb = s.sources.filter(x => x.status === 'rebuilding');
    if (!stale.length && !legacy.length && !reb.length) { el.innerHTML = ''; return; }
    const why = [...new Set(stale.flatMap(x => x.reasons))].join(', ');
    const rebNote = [...new Set(reb.map(x => x.note).filter(Boolean))].join(', ');
    const parts = [];
    if (stale.length) parts.push(`${stale.length} source${stale.length === 1 ? '' : 's'} analysed against older inputs`);
    if (legacy.length) parts.push(`${legacy.length} legacy analys${legacy.length === 1 ? 'is' : 'es'} (preserved from 0.15 — original project context cannot be verified)`);
    if (reb.length) parts.push(`${reb.length} re-analysing${rebNote ? ' · ' + esc(rebNote) : '…'}`);
    stale.push(...legacy);
    h = `<div class="card status-warn-border"><b>⚠ ${parts.join(' · ')}</b>
      <div class="muted">${why ? `Why: ${esc(why)}. ` : ''}Their findings are still readable and usable — they just may not reflect what the project is about now. Nothing is re-run unless you ask.</div>
      ${stale.length ? `<div class="row" style="margin-top:8px;flex-wrap:wrap"><span class="muted" style="width:100%">Re-analyse ${stale.length} stale (${esc(s.estimate.basis)})${s.budget.daily_remaining != null ? ` · daily budget left ${money(s.budget.daily_remaining)}` : ''}${s.budget.fits ? '' : ' · <span class="status-warn">exceeds today\'s budget — it will run as far as the budget allows and continue tomorrow</span>'}</span>
        <button class="small primary" onclick="rebuildStale(['findings'],'interactive')" title="Faster · standard model cost">Rebuild now · ${money(s.estimate.findings)}</button><button class="small" onclick="rebuildStale(['findings'],'batch')" title="Up to 24 hours · ~50% lower model cost (model cost only)">Rebuild in background · ${money(s.estimate.findings_background ?? s.estimate.findings / 2)} model cost</button><button class="small ghost" onclick="STALE.left=1;renderStaleCard('${elId}','${what}')">Leave stale</button></div>` : ''}</div>`;
  } else {
    const p = s.plan;
    if (p.status !== 'stale' && p.status !== 'rebuilding') { el.innerHTML = ''; return; }
    if (p.status === 'rebuilding') h = `<div class="card status-warn-border"><b>🔄 Master Plan is being rebuilt${p.note ? ' · ' + esc(p.note) : '…'}</b><div class="muted">The previous version stays readable until the new one is saved.</div></div>`;
    else {
      // 0.63.68 (W3): was four co-equal buttons (Rebuild plan / Re-analyse now / Re-analyse in background / Raise
      // budget) in one row before the plan itself was visible. "Rebuild plan" is the cheapest option that always
      // fully resolves the PLAN's own staleness (it costs p.estimate alone, no re-analysis required), so it is
      // the one recommended default, kept primary and immediately visible per DESIGN.md's stated-rule requirement
      // — never an arbitrary pick. The two costlier "re-analyse stale sources first" variants are one step away in
      // a details/summary disclosure (styled like W2's review-item — same visual language, not the Findings hub
      // itself). "Raise budget" only appears when the estimates actually exceed today's remaining budget instead
      // of unconditionally, matching how the Findings branch above already only warns about budget when it applies.
      const altBody = `<div class="row" style="flex-wrap:wrap"><span class="muted" style="width:100%">Re-analysing first means the plan reflects current source content, not just its own staleness reason${s.budget.daily_remaining != null ? ` · daily budget left ${money(s.budget.daily_remaining)}` : ''}</span>
        <button class="small" onclick="rebuildStale(['findings','plan'],'interactive')" title="Faster · standard model cost">Re-analyse now + rebuild · ${money(s.estimate.total)}</button><button class="small" onclick="rebuildStale(['findings','plan'],'batch')" title="Up to 24 hours · ~50% lower model cost on the re-analysis (model cost only)">Re-analyse in background + rebuild · ${money(s.estimate.total_background ?? s.estimate.total)}</button></div>`;
      h = `<div class="card status-warn-border"><b>⚠ Plan may be stale</b> <span class="muted">v${p.version}${p.reasons.length ? ' — ' + esc(p.reasons.join('; ')) : ''}</span>
      <div class="muted">It is still readable and every task status is kept. Rebuilding writes a new version on top of it.</div>
      <div class="row" style="margin-top:8px;flex-wrap:wrap;align-items:center"><button class="small primary" onclick="rebuildStale(['plan'],'interactive')">Rebuild plan · ${money(p.estimate)}</button><span class="muted">${s.budget.daily_remaining != null ? `daily budget left ${money(s.budget.daily_remaining)}` : ''}</span></div>
      ${s.stale_sources ? reviewItem('Other ways to rebuild', `re-analyse ${s.stale_sources} stale source${s.stale_sources === 1 ? '' : 's'} first, then rebuild`, altBody) : ''}
      ${!s.budget.fits ? `<div class="row" style="margin-top:8px;flex-wrap:wrap;align-items:center"><span class="muted">Today's estimates exceed the remaining budget.</span><button class="small ghost" onclick="showView('settings')">Raise budget</button></div>` : ''}</div>`;
    }
  }
  el.innerHTML = STALE.left && what === 'findings' ? '' : h;
}
globalThis.rebuildStale = async function rebuildStale(what, transport = 'interactive') {
  const r = await post(`/api/projects/${state.project.id}/rebuild-stale`, { what, transport });
  const est = transport === 'batch' ? (r.estimate.total_background ?? r.estimate.total) : r.estimate.total;
  toast(`${r.queued} job${r.queued === 1 ? '' : 's'} queued${transport === 'batch' ? ' in the background (up to 24 hours; each source becomes current as it completes)' : ''} · est. $${(+est).toFixed(2)}${transport === 'batch' ? ' model cost' : ''}${r.budget.fits ? '' : ' · will pause when the daily budget is reached and resume tomorrow'}`);
  loadStaleness(); loadJobs();
}
// 0.61.0 — the Findings tab was re-running five whole-project passes every four seconds.
//
// Seen in Kyle's own browser: while sources are being read, `loadNotes` re-ran on a 4 s timer and each pass
// fetched /findings, /findings/quality, /staleness, /staleness/triage and the project row — several of which walk
// every note in the project. The Sources view solved this in 0.46.2 with a 13 ms "did anything change?" request
// (`/tick`); Findings never got it. The revision covers notes, sources, jobs and research, which is everything
// this tab draws, so an unchanged revision means there is nothing to redraw. A full reconcile still runs every
// RECONCILE_EVERY ticks, so a fingerprint that ever missed a change self-corrects within a minute.
globalThis.notesRev = null;
globalThis.notesTicks = 0;
globalThis.notesTick = async function notesTick() {
  if (state.view !== 'findings' || !state.project) return;
  let t;
  try { t = await api(`/api/projects/${state.project.id}/tick`, { ack: false }); } catch (e) { scheduleNotesTick(); return; }
  const rev = JSON.stringify(t.rev);
  globalThis.notesTicks++;
  if (rev !== globalThis.notesRev || globalThis.notesTicks >= RECONCILE_EVERY) { globalThis.notesTicks = 0; await loadNotes(); }
  else scheduleNotesTick();
}
globalThis.scheduleNotesTick = function scheduleNotesTick() {
  clearTimeout(window._notesTimer);
  window._notesTimer = setTimeout(notesTick, 4000);
}
globalThis.loadNotes = async function loadNotes() {
  // 0.60.1 (Kyle: "click it and nothing loads"): this used to fetch /api/projects/{id} — every approved and
  // suggested finding in full, about 8 MB on his business project — and /api/sources?limit=2000 on top, before
  // drawing anything. The counts now come from the endpoint's own `counts`, and the Suggested list is the same
  // server-paged query the workbench below uses. Nothing about what the user can DO here changed.
  loadStaleness();
  const p = await api('/api/projects/' + state.project.id);
  const c = p.counts || {};
  const nApproved = c.approved || 0, nSug = c.suggested || 0;
  $('#nFindings').textContent = nApproved;
  const analysing = (p.analysing || {}).sources || 0;
  FWAVE.queued = (p.analysing || {}).queued || 0;
  globalThis.notesRev = JSON.stringify((await api(`/api/projects/${state.project.id}/tick`, { ack: false }).catch(() => ({}))).rev || null);
  clearTimeout(window._notesTimer);
  if (analysing) scheduleNotesTick();
  let sug = [], sugTotal = nSug;
  if (nSug) {
    try {
      const r = await api(`/api/projects/${state.project.id}/findings?` + new URLSearchParams({ status: 'suggested', limit: 100, offset: 0, sort: 'importance' }));
      sug = r.findings || []; sugTotal = r.total != null ? r.total : nSug;
    } catch (e) { sug = []; }
  }
  const legacy = sug.filter(n => !n.title).length;
  // CL-2: this used to render every suggested finding as its own card, right above a workbench that already has
  // a 'suggested' filter for the exact same list — one pile of cards duplicating another. It's now a single
  // REVIEW entry that sends the user to that filter; bulk approve/dismiss live on the workbench itself (see
  // loadWorkbench's #fbBulk), scoped to whichever page is actually on screen rather than a separate top-100 pull.
  $('#suggestedReview').innerHTML = (legacy ? reviewItem(`${legacy} legacy suggestion${legacy === 1 ? '' : 's'}`, 'older analysis produced run-on text', `<button class="small" onclick="analyzeChooser(true)">Re-analyse all…</button> <span class="muted text-xs">Cost is shown before anything runs.</span>`) : '')
    + (sugTotal ? reviewItem(`${sugTotal} suggested finding${sugTotal === 1 ? '' : 's'} waiting`, 'new findings extracted from your sources, not yet reviewed', `<button class="small primary" onclick="reviewSuggested()">Review</button>`) : '')
    + (analysing ? reviewItem(`Reading ${analysing} source${analysing === 1 ? '' : 's'}`, 'new findings will appear as each source finishes', `${FWAVE.queued ? `<button class="small primary" title="Move the first few of these to the front of the whole queue so this project becomes usable now. Free — it changes the order only, not the provider, model or cost." onclick="firstWave()">⏫ Start ${Math.min(FWAVE.queued, 6)} now</button> <span class="muted text-xs">Free — changes queue order only.</span>` : '<span class="muted text-xs">No action needed.</span>'}`) : '');
  syncFindingsReview();
  loadWorkbench();
}
// CL-2: the REVIEW entry's "Review" button lands here — sets the workbench to the suggested filter with a
// clean slate (no leftover search/facets from whatever the user was doing before) and scrolls it into view.
globalThis.reviewSuggested = function reviewSuggested() {
  $('#fbStatus').value = 'suggested';
  for (const id of ['fbQ', 'fbImp', 'fbUsed', 'fbStale', 'fbArea']) { const el = $('#' + id); if (el) el.value = ''; }
  FB.source = null; FB.offset = 0;
  loadWorkbench();
  setTimeout(() => { const el = $('#fbBar'); if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' }); }, 50);
}
// The Sources tab's "N suggested findings waiting for review" link lands HERE, on that source's suggestions —
// before 0.60.1 it only switched tabs, so it dropped the user into whatever filter the workbench happened to hold
// (usually `approved`) and looked like a dead end.
globalThis.openSourceSuggestions = async function openSourceSuggestions(sid, status) {
  FB.source = sid; FB.offset = 0;
  showView('findings');
  const sel = $('#fbStatus'); if (sel) sel.value = status || 'suggested';
  for (const id of ['fbQ', 'fbImp', 'fbUsed', 'fbStale', 'fbArea']) { const el = $('#' + id); if (el) el.value = ''; }
  loadWorkbench();
  setTimeout(() => { const el = $('#notes'); if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' }); }, 120);
}
globalThis.clearFindingSource = function clearFindingSource() { FB.source = null; FB.offset = 0; loadWorkbench(); }
// S4: the Findings workbench — server-side filters, facets, sort, paging; use badges; the low-value sweep
globalThis.FB = { offset: 0, limit: 100, source: null, loaded: false };
globalThis.FGRP = { collapsed: new Set() };   // remembers which source-groups the user closed by hand (title -> closed)
// C1: DESIGN.md's Workbench-row rule caps a normal row at two visible badges; this row used to show up to
// five (plan/chat/claim/stale/area). The three "where this got used" signals are really one fact — whether
// anything downstream relies on this finding — so they collapse into a single badge that keeps all three
// pieces of detail in its title tooltip rather than losing them. Area/topic is categorical metadata, not an
// attention signal, so it moves into the meaning line as plain text instead of a third pill. That leaves at
// most two badges: the used-summary, and stale-source when it applies — the one that's actually actionable.
globalThis.useBadges = function useBadges(n) {
  const u = n.used || {}; const used = [], why = [];
  // SM-3: 🧠 used to prefix this exact text, so "🧠 weak" read as "this finding is weak" when it actually
  // names the strength of the Claim the finding feeds. 🧠 is reserved for the Research nav item now; every
  // use-badge here is plain text, and the Claim entry names its subject instead of leaving it ambiguous.
  if (u.plan) { used.push('in plan'); why.push('cited as evidence by the Master Plan'); }
  if (u.chat) { used.push(`cited ${u.chat}×`); why.push(`cited in ${u.chat} chat answer${u.chat === 1 ? '' : 's'}`); }
  if (u.claim) { used.push(`Claim: ${esc(u.claim)}`); why.push(`became or evidences ${u.claim} Claim${u.claim === 1 ? '' : 's'}`); }
  const b = [];
  if (used.length) b.push(`<span class="tag" title="${esc(why.join(' · '))}">${used.join(' ')}</span>`);
  // CL-6: the warn glyph is redundant with the status-warn colour the tag already carries -- the word says it.
  if (n.source_stale) b.push(`<span class="tag status-warn" title="its source was analysed against older inputs">stale source</span>`);
  return b.join(' ');
}
// CL-5: the status filter used to be an unlabeled <select> buried in a row of six other unlabeled selects.
// It is the one choice people actually reach for constantly (it's how the suggested-review flow gets here), so
// it now renders as a chip row — like Sources' own status chips — with the <select> kept, hidden, purely as
// the value store every other bit of code here already reads/writes via $('#fbStatus').value.
const FB_STATUS_CHIPS = [['approved', 'Approved'], ['suggested', 'Suggested'], ['reserve', 'Reserve'], ['dismissed', 'Dismissed'], ['all', 'All']];
globalThis.renderFbStatusChips = function renderFbStatusChips(cur) {
  const el = $('#fbStatusChips'); if (!el) return;
  cur = cur || $('#fbStatus').value;
  el.innerHTML = FB_STATUS_CHIPS.map(([k, l]) => `<span class="chipf ${cur === k ? 'on' : ''}" onclick="setFbStatus('${k}')">${l}</span>`).join('');
}
globalThis.setFbStatus = function setFbStatus(v) { $('#fbStatus').value = v; loadWorkbench(); }
globalThis.loadWorkbench = async function loadWorkbench(reset = true) {
  if (reset) FB.offset = 0;
  const p = new URLSearchParams({ limit: FB.limit, offset: FB.offset, status: $('#fbStatus').value, sort: $('#fbSort').value });
  if (FB.source) p.set('source_id', FB.source);
  for (const [k, id] of [['q', 'fbQ'], ['min_importance', 'fbImp'], ['used', 'fbUsed'], ['stale', 'fbStale'], ['area', 'fbArea']]) { const v = $('#' + id).value; if (v) p.set(k, v); }
  if (!FB.loaded) $('#notes').innerHTML = listState('loading', { label: 'Loading findings…' });
  let r; try { r = await api(`/api/projects/${state.project.id}/findings?` + p); } catch (e) { $('#notes').innerHTML = listState('failed', { message: "Couldn't load findings.", retry: 'loadWorkbench()' }); return; }
  FB.loaded = true;
  // area facet options (keep the current choice)
  const sel = $('#fbArea'); const cur = sel.value; const areas = Object.entries(r.facets.area || {}).sort((a, b) => b[1] - a[1]);
  sel.innerHTML = `<option value="">any area</option>` + areas.map(([a, n]) => `<option value="${esc(a)}">${esc(a)} (${n})</option>`).join(''); sel.value = cur;
  const f = r.facets; const st = $('#fbStatus').value;
  renderFbStatusChips(st);
  $('#fbSrcChip').innerHTML = FB.source ? `<div class="row muted" style="font-size:12.5px;padding:2px 0"><span class="grow">Showing one source only</span><button class="small ghost" onclick="clearFindingSource()">show every source</button></div>` : '';
  const bg = r.badges || {};
  // 0.61.5: use/staleness/area come from a cache that is deliberately allowed to lag the rows, so the counts say
  // when they are lagging instead of reading as current. An unknown count is never printed as zero.
  $('#fbCount').textContent = `${r.total} finding${r.total === 1 ? '' : 's'}`
    + (f.used && bg.known ? ` · plan ${f.used.plan || 0} · chat ${f.used.chat || 0} · Claims ${f.used.claim || 0}` : '')
    + (bg.note ? ` · ${bg.note}` : '');
  // Fire-and-forget, and explicitly swallowed: tonight's banners were shipped without a human able to look at the
  // browser (0.58.10), so a failure in this decoration must not be able to take the findings list down with it.
  try { const q = loadQuality(st); if (q && q.catch) q.catch(() => { const el = $('#fbQual'); if (el) el.innerHTML = ''; }); }
  catch (e) { const el = $('#fbQual'); if (el) el.innerHTML = ''; }
  const sw = r.low_value_sweep || {};
  $('#fbSweep').innerHTML = sw.count && !sw.pending && st === 'approved' ? reviewItem(`Review ${sw.count} low-value finding${sw.count === 1 ? '' : 's'}`, `${esc(sw.line)}; nothing has used them`, `<button class="small" onclick="$('#fbImp').value='';$('#fbUsed').value='never';$('#fbSort').value='importance';loadWorkbench()">Review them</button><button class="small danger" onclick="sweepLow(${JSON.stringify(sw.note_ids)})">Dismiss all ${sw.count}</button>`) : '';
  syncFindingsReview();
  const rows = r.findings || [];
  const bySrc = []; const idx = {};
  for (const n of rows) { const k = n.source_title || 'Pinned from chat'; if (!(k in idx)) { idx[k] = bySrc.length; bySrc.push([k, n.source_id, []]); } bySrc[idx[k]][2].push(n); }
  // 0.63.27 — Kyle: "it's unclear in the app how to approve or reject sometimes." On the `suggested` filter, where
  // the approving actually happens, these were a bare ✓ and ✕ with NO label and NO title — two glyphs. The Claims
  // workbench one tab away says "Accept" and "Reject" in words, so the same verdict was spoken in one place and
  // mimed in the other. And ✓ already means "this happened" elsewhere in this file (✓ already in your library, ✓
  // added, ✓ attached), so the same glyph was both a status and a command. The verb goes on the button.
  // CL-1: per-row Approve was `.primary` on every row of a 16,450-row workbench. It is the actual work, so
  // it stays -- but plain, not primary; the one primary on this surface is #fbBulk's bulk Approve above the
  // list (CL-2), which is what "one dominant primary action per decision region" asks for at this scale.
  const act = n => st === 'approved' || st === 'all' && n.status === 'approved' ? `<button class="small ghost" title="Remove it from the project's approved findings" onclick="noteStatus(${n.id},'dismissed')">Dismiss</button>`
    : n.status === 'suggested' ? `<button class="small" title="Keep it — approved findings feed exports, the plan and Claims" onclick="noteStatus(${n.id},'approved')">Approve</button><button class="small ghost" title="Not worth keeping (nothing is deleted — it stays as dismissed)" onclick="noteStatus(${n.id},'dismissed')">Dismiss</button>`
    : n.status === 'reserve' ? `<button class="small" title="Keep it — approved findings feed exports, the plan and Claims" onclick="noteStatus(${n.id},'approved')">Approve</button><button class="small" title="Move it into the review queue to decide later" onclick="noteStatus(${n.id},'suggested')">To review</button><button class="small ghost" title="Not worth keeping (nothing is deleted — it stays as dismissed)" onclick="noteStatus(${n.id},'dismissed')">Dismiss</button>`
    : `<button class="small ghost" title="Put it back in the review queue" onclick="noteStatus(${n.id},'suggested')">↩ Restore</button>`;
  // PRODUCT-ORGANIZATION.md #1: this list already groups by source (nothing new there) — what was missing was any
  // way to collapse a group, so a project with many sources was still one long scroll of open groups.
  if (FGRP.collapsed === 'all') FGRP.collapsed = new Set(bySrc.map(([title]) => title));
  const grpSearching = !!($('#fbQ').value || $('#fbImp').value || $('#fbUsed').value || $('#fbStale').value || $('#fbArea').value);
  $('#fbGroupCtl').hidden = !(bySrc.length > 1);
  // CL-2: bulk approve/dismiss for the suggested filter used to live above a separate, now-removed 100-card
  // block fed by its own top-of-page fetch; this uses the same page of rows the workbench is already showing,
  // so "shown" always means what's actually on screen.
  const bulkIds = rows.map(n => n.id);
  $('#fbBulk').innerHTML = (st === 'suggested' && rows.length) ? `<div class="row" style="gap:6px;margin:0 0 10px;flex-wrap:wrap">
      <button class="small primary" title="${r.total > rows.length ? `Approve the ${rows.length} shown here (of ${r.total})` : 'Approve all of them'}" onclick="bulkNotes(${JSON.stringify(bulkIds)},'approved')">Approve ${r.total > rows.length ? rows.length + ' shown' : 'all'}</button>
      <button class="small" onclick="bulkNotes(${JSON.stringify(bulkIds)},'dismissed')">Dismiss ${r.total > rows.length ? rows.length + ' shown' : 'all'}</button>
    </div>` : '';
  $('#notes').innerHTML = rows.length ? bySrc.map(([title, sid, list]) => {
    const open = grpSearching || bySrc.length <= 4 || !FGRP.collapsed.has(title);
    const keyJs = JSON.stringify(title).replace(/"/g, '&quot;');
    return `<details class="fgroup" ${open ? 'open' : ''} ontoggle="this.open?FGRP.collapsed.delete(${keyJs}):FGRP.collapsed.add(${keyJs})"><summary class="gh"><b>${esc(title)}</b><span>${list.length}</span>${sid ? `<button class="small ghost" title="only this source" onclick="event.preventDefault();$('#fbQ').value='';FB.source=null;loadWorkbenchSource('${sid}')">filter</button><button class="small ghost" title="Everything this source gave the project" onclick="event.preventDefault();sourceDrawer('${sid}')">source ↗</button>` : ''}</summary>` +
      list.map(n => findingCard({ ...n, _badges: useBadges(n) }, act(n))).join('') + `</details>`; }).join('')
    : `<div class="empty">${r.total ? '' : st === 'approved' && !$('#fbQ').value && !$('#fbUsed').value ? 'Nothing approved yet. Approve suggestions above, or ask questions in a chat and pin the answers worth keeping.' : 'No findings match these filters.'}</div>`;
  const pages = Math.ceil(r.total / FB.limit);
  $('#fbPager').innerHTML = pages > 1 ? `<button class="small ghost" ${FB.offset === 0 ? 'disabled' : ''} onclick="FB.offset=Math.max(0,FB.offset-FB.limit);loadWorkbench(false)">‹ prev</button><span class="muted" style="margin:0 8px">${Math.floor(FB.offset / FB.limit) + 1} / ${pages}</span><button class="small ghost" ${FB.offset + FB.limit >= r.total ? 'disabled' : ''} onclick="FB.offset+=FB.limit;loadWorkbench(false)">next ›</button>` : '';
}
globalThis.loadWorkbenchSource = async function loadWorkbenchSource(sid) { const p = new URLSearchParams({ limit: 200, status: 'all', source_id: sid }); const r = await api(`/api/projects/${state.project.id}/findings?` + p); $('#fbCount').textContent = `${r.total} from this source (all statuses)`; $('#notes').innerHTML = (r.findings || []).map(n => findingCard({ ...n, _badges: useBadges(n) }, `<span class="muted" style="font-size:11px">${esc(n.status)}</span>`)).join(''); $('#fbPager').innerHTML = `<button class="small ghost" onclick="loadWorkbench()">‹ back to all</button>`; }
// F3 (0.58.0): the trash review. Near-duplicates and vacuous findings, each with its reason and the finding that
// survives. Read-only until the user presses the button, and the button is the same /api/notes/bulk-status every
// other status change goes through — there is no second door.
globalThis.QUAL = null;
globalThis.loadQuality = async function loadQuality(st) {
  // 0.61.2: the summary asks for the previous answer and refreshes behind the request — on a 12,800-finding
  // project this pass takes 11.5 s, and it was being asked for on every visit to the tab.
  const el = $('#fbQual'); if (!el) return;
  if (st === 'reserve') return loadPromotable(el);
  // 0.58.9: `suggested` is where the filter helps MOST — before a finding is approved rather than after — and the
  // pile grows now that 0.58.1 raised the cap. Same surface, same door, one extra status.
  if (st !== 'approved' && st !== 'suggested') { el.innerHTML = ''; return; }
  let s; try { s = await api(`/api/projects/${state.project.id}/findings/quality?summary=1&status=${st}`); } catch (e) { el.innerHTML = ''; return; }
  if (s && s.pending) { el.innerHTML = reviewItem('Checking for repeats', 'the check runs in the background and never blocks this page', '<span class="muted text-xs">It normally appears within a couple of minutes.</span>'); syncFindingsReview(); return; }
  if (!s || !s.flagged) { el.innerHTML = ''; syncFindingsReview(); return; }
  const bits = [];
  // 0.59.0, Kyle: "even duplicate data is useful somehow". Right — and this app already agrees: claims.assess
  // counts independent sources agreeing as corroborative sufficiency. So a repeat WITHIN one source is redundancy,
  // and the same fact from several sources is evidence. Only the first is offered for a sweep.
  if (s.duplicates) bits.push(`${s.duplicates} the same source said twice`);
  const vac = s.flagged - s.duplicates; if (vac > 0) bits.push(`${vac} that name nothing specific`);
  const corr = (s.corroborated || {}).findings || 0;
  el.innerHTML = reviewItem(`${s.flagged} finding${s.flagged === 1 ? '' : 's'} need${s.flagged === 1 ? 's' : ''} a quality check`, `${esc(bits.join(' · '))}${s.protected ? ` · ${s.protected} protected` : ''}${corr ? ` · ${corr} independently confirmed and kept` : ''}`, `<button class="small" onclick="openQuality('${st}')">Review</button>${s.as_of_current === false ? ' <span class="muted text-xs">Counted a moment ago; refreshing.</span>' : ''}`);
  syncFindingsReview();
}
// F5 (0.58.5): `reserve` is what the cap withheld — findings already paid for, never exported or planned on.
// The filter can now say which of them are not repeats of something approved and do name something specific.
globalThis.loadPromotable = async function loadPromotable(el) {
  let r; try { r = await api(`/api/projects/${state.project.id}/findings/reserve-promotable?limit=400`); } catch (e) { el.innerHTML = ''; return; }
  if (!r.reserve) { el.innerHTML = ''; syncFindingsReview(); return; }
  const sk = Object.entries(r.skipped || {}).map(([k, v]) => `${v} ${k === 'already_covered' ? 'already covered by an approved finding' : (r.rules ? '' : '') + k.replace(/_/g, ' ')}`).join(' · ');
  el.innerHTML = reviewItem(`${r.promotable} of ${r.reserve} withheld findings may be worth keeping`, `they were extracted beyond the cap${sk ? `; skipping ${esc(sk)}` : ''}`, r.promotable ? `<button class="small" onclick="openPromotable()">Review</button><button class="small primary" onclick="promoteReserve(${JSON.stringify(r.rows.map(x => x.id))})">Approve all ${r.promotable}</button>` : '<span class="muted text-xs">Nothing is ready to promote.</span>');
  syncFindingsReview();
}
globalThis.openPromotable = async function openPromotable() {
  let r; try { r = await api(`/api/projects/${state.project.id}/findings/reserve-promotable?limit=400`); } catch (e) { return toast('could not load them'); }
  $('#dlgBody').innerHTML = `<h3 style="margin:0 0 4px">Withheld findings worth keeping</h3>
    <p class="muted" style="margin:0 0 10px">${esc(r.note)}</p>
    ${(r.rows || []).map(x => `<label class="row" style="align-items:flex-start;gap:8px;padding:6px 8px"><input type="checkbox" class="pchk" value="${x.id}" checked>
      <span class="grow">${esc((x.content || '').slice(0, 260))}<br><span class="muted" style="font-size:11px">${esc(x.why)}${x.importance ? ` · rated ${x.importance}/5` : ''}</span></span></label>`).join('')}
    <div class="row" style="margin-top:12px;gap:8px"><button class="small primary" onclick="promoteReserve([...document.querySelectorAll('.pchk:checked')].map(c=>+c.value))">Approve the ticked ones</button></div>`;
  dlg.showModal();
}
globalThis.promoteReserve = async function promoteReserve(ids) {
  if (!ids || !ids.length) return toast('nothing ticked');
  await post('/api/notes/bulk-status', { note_ids: ids, status: 'approved' });
  try { dlg.close(); } catch (e) { /* the banner path has no dialog open */ }
  toast(`${ids.length} approved`); loadNotes();
}
globalThis.openQuality = async function openQuality(st) {   // opened deliberately: this one waits for a current answer
  st = st || $('#fbStatus').value || 'approved';
  let r; try { r = await api(`/api/projects/${state.project.id}/findings/quality?limit=400&status=${st}`); } catch (e) { return toast('could not load the review'); }
  globalThis.QUAL = r;
  const groups = {};
  for (const row of (r.rows || [])) { const k = (row.flags || ['no_specifics'])[0]; (groups[k] = groups[k] || []).push(row); }
  const order = ['duplicate', 'generic_only', 'no_specifics', 'echoes_title', 'too_short'];
  const keepOf = id => (r.rows.find(x => x.id === id) || {}).content;
  const body = `<h3 style="margin:0 0 4px">Tidy up findings</h3>
    <p class="muted" style="margin:0 0 10px">${esc(r.note)}</p>
    <div class="muted" style="font-size:12px;margin-bottom:10px">${r.findings} findings · ${r.flagged} flagged${r.protected ? ` · ${r.protected} protected` : ''}</div>
    ${order.filter(k => groups[k]).map(k => `<details class="fgroup" open><summary class="gh"><b>${esc(r.rules[k])}</b><span>${groups[k].length}</span></summary>
      ${groups[k].map(row => `<label class="row" style="align-items:flex-start;gap:8px;padding:6px 8px">
        <input type="checkbox" class="qchk" value="${row.id}" ${row.pre_select ? 'checked' : ''} ${row.protected ? 'disabled' : ''}>
        <span class="grow"><span>${esc((row.content || '').slice(0, 260))}</span>
        ${row.keep_instead ? `<br><span class="muted" style="font-size:11px">keeping instead: ${esc((keepOf(row.keep_instead) || '').slice(0, 160) || '#' + row.keep_instead)}</span>` : ''}
        ${row.protected ? `<br><span class="muted" style="font-size:11px">🔒 ${esc(row.protected)}</span>` : ''}</span></label>`).join('')}
    </details>`).join('')}
    <div class="row" style="margin-top:12px;gap:8px"><button class="small danger" onclick="sweepQuality()">Dismiss the ticked ones</button>
      <button class="small ghost" onclick="document.querySelectorAll('.qchk:not([disabled])').forEach(c=>c.checked=false)">Untick all</button></div>`;
  $('#dlgBody').innerHTML = body; dlg.showModal();
}
globalThis.sweepQuality = async function sweepQuality() {
  const ids = [...document.querySelectorAll('.qchk:checked')].map(c => +c.value);
  if (!ids.length) return toast('nothing ticked');
  if (!confirm(`Dismiss ${ids.length} finding${ids.length === 1 ? '' : 's'}? They stay retrievable under status "dismissed", and nothing your plan, chats or Claims use is in this list. The repeat check catches rewordings, not paraphrases — skim first.`)) return;
  await post('/api/notes/bulk-status', { note_ids: ids, status: 'dismissed' });
  dlg.close(); toast(`${ids.length} dismissed`); loadNotes();
}
globalThis.sweepLow = async function sweepLow(ids) { if (!confirm(`Dismiss ${ids.length} approved findings rated ≤ 2 that nothing ever used? They stay retrievable under status "dismissed".`)) return; await post('/api/notes/bulk-status', { note_ids: ids, status: 'dismissed' }); toast(`${ids.length} dismissed`); loadNotes(); }
globalThis.ATTRIB = /^(?:(?:the\s+)?(?:speaker|host|he|she|they|[A-Z][\w'.-]+(?:\s[A-Z][\w'.-]+)?)\s+(?:says|said|states|stated|recommends|recommended|advises|advised|suggests|suggested|argues|argued|notes|noted|explains|explained|emphasi[sz]es|claims|believes|thinks)\s+(?:that\s+)?)/i;
globalThis.splitFinding = function splitFinding(n) {
  let raw = n.content.replace(/\s*\[\d+\]\s*/g, ' ').replace(/\s+/g, ' ').trim();
  // legacy rows embedded the quote in the text: drop it (the chip's "quote" link still has it)
  raw = raw.replace(/\s*[—–-]\s*[“"][^”"]{5,}[”"]\s*$/, '').trim();
  if (n.title) {
    let body = raw;
    if (body.toLowerCase().startsWith(n.title.toLowerCase().replace(/[.!?]$/, ''))) body = body.slice(n.title.length).replace(/^[\s:.—–-]+/, '');
    return { title: n.title.replace(ATTRIB, m => m.charAt(0) === m.charAt(0).toUpperCase() ? '' : ''), body };
  }
  const stripped = raw.replace(ATTRIB, '');
  let m = stripped.match(/^(.{12,90}?[.!?])(\s|$)/);
  let t, rest;
  if (m) { t = m[1]; rest = stripped.slice(m[1].length).trim(); }
  else {
    // cut at the first clause boundary (: — , ;) that is outside parentheses, between 25 and 80 chars
    let depth = 0, cut = -1;
    for (let i = 0; i < Math.min(stripped.length, 80); i++) {
      const ch = stripped[i]; if (ch === '(') depth++; else if (ch === ')') depth--;
      if (depth === 0 && i >= 25 && (ch === ':' || ch === ';' || ch === '—' || ch === '–' || (ch === ',' && stripped[i + 1] === ' '))) { cut = i; break; }
    }
    if (cut < 0) { const sp = stripped.lastIndexOf(' ', 70); cut = sp > 25 ? sp : 70; t = stripped.slice(0, cut) + '…'; }
    else t = stripped.slice(0, cut);
    rest = stripped.slice(cut).replace(/^[\s,;:—–-]+/, '').trim();
  }
  t = t.replace(/[.!?]$/, ''); t = t.charAt(0).toUpperCase() + t.slice(1);
  return { title: t, body: rest };
}
// CL-3: DESIGN.md §6's Workbench-row rule — title line, one meaning line underneath, ≤2 badges, fixed row
// height, depth in a drawer/expand rather than the row growing into a card — already governs Sources and (via
// C1's useBadges()) the badges here. This row was still five to six lines: importance dots, title, a 2–3 line
// body, a wrapping badge/area/citation line, and a quote toggle. It's now two lines — title (truncating), then
// body (truncating) with its badges and source trailing on the same line — with area, the full citation list and
// the quote moved into a click-to-open detail strip instead of always being on screen.
globalThis.findingCard = function findingCard(n, actions) {
  const c = (n.citations || [])[0];
  const { title, body } = splitFinding(n);
  const imp = n.importance ? `<span class="fi" title="importance ${n.importance}/5">${'●'.repeat(n.importance)}<span class="dim">${'●'.repeat(5 - n.importance)}</span></span>` : '<span class="fi"></span>';
  const srcChip = !c ? '' : c.removed ? `<span class="chip" title="Evidence source removed">⚠ ${esc(c.title || 'source')} — removed</span>`
    : `<span class="chip" title="${esc(c.title || '')}${c.timestamp ? ' @ ' + c.timestamp : ''}">▶ ${esc(c.title && c.title.length > 24 ? c.title.slice(0, 22) + '…' : c.title || '')}${c.timestamp ? ' @ ' + c.timestamp : ''}</span>`;
  const extraCitations = (n.citations || []).length > 1;
  const hasDetail = !!(n.area || c?.snippet || extraCitations);
  const detail = !hasDetail ? '' : `<div class="detail" hidden>
      ${n.area ? `<span class="muted" title="Research Area">Area: ${esc(n.area)}</span> ` : ''}
      ${(n.citations || []).map(x => x.removed ? `<span class="chip" title="Evidence source removed">⚠ ${esc(x.title || 'source')} — removed</span>` : `<a class="chip" href="${esc(x.link)}" target="_blank">▶ ${esc(x.title)} @ ${x.timestamp}</a>`).join('')}
      ${c?.snippet ? `<div class="quote">“${esc(c.snippet)}”</div>` : ''}
    </div>`;
  return `<div class="f">${imp}<div class="main">
      <div class="ttl">${esc(title)}</div>
      <div class="row2">${body ? `<span class="txt">${esc(body)}</span>` : ''}${n._badges ? n._badges : ''}${srcChip}${hasDetail ? `<a href="#" class="qtoggle" title="area, full source list and quote" onclick="const d=this.closest('.main').querySelector('.detail');d.hidden=!d.hidden;return false">⋯</a>` : ''}</div>
      ${detail}
    </div><div class="act">${actions}</div></div>`;
}
globalThis.noteStatus = async function noteStatus(id, status) { await post(`/api/notes/${id}/status`, { status }); loadNotes(); }
globalThis.bulkNotes = async function bulkNotes(ids, status) {
  if (!ids || !ids.length) return toast('nothing to do');
  await post('/api/notes/bulk-status', { note_ids: ids, status });
  // Say what happened BEFORE the reload: loadNotes() destroys the button that was pressed (there is
  // nothing left to approve, so the whole block re-renders without it) and takes several seconds. Kyle
  // approved 59 findings, it worked, and the app told him nothing — so he reported the button as broken.
  const n = ids.length, word = status === 'approved' ? 'approved' : status === 'dismissed' ? 'dismissed' : `moved to ${status}`;
  toast(`✓ ${n} finding${n === 1 ? '' : 's'} ${word}`);
  loadNotes();
}
// Now vs background: the same analysis through two transports. Wording is deliberate — the background option may take
// up to 24 hours (never "within hours") and the ~50% discount applies to model cost only.
globalThis.transportChoiceHtml = function transportChoiceHtml(est, onNow, onBg, verb) {
  const money = v => '~$' + (+v).toFixed(2);
  const rec = est.recommended || 'now';
  const badge = k => rec === k ? ' <span class="chip" title="recommended for this amount of work">recommended</span>' : '';
  const basis = est.basis === 'token count' ? 'exact token count' : est.basis === 'mixed' ? 'partly token-counted' : 'estimate';
  const n = est.sources || 0;
  return `<div class="card" style="margin:6px 0 10px">
    <div class="muted" style="margin-bottom:6px">${verb} ${n} source${n === 1 ? '' : 's'} (${est.items || 0} window${est.items === 1 ? '' : 's'}) · ${basis} · model cost only</div>
    <div class="row" style="gap:10px;align-items:stretch;flex-wrap:wrap">
      <button class="small ${rec === 'now' ? 'primary' : ''}" style="flex:1;min-width:220px;text-align:left;padding:8px 10px" onclick="${onNow}"><b>${esc(est.choices?.now?.label || 'Analyze now')}</b> · ${money(est.now)}${badge('now')}<div class="muted" style="font-weight:normal">${esc(est.choices?.now?.detail || 'Faster · standard model cost')}</div></button>
      <button class="small ${rec === 'background' ? 'primary' : ''}" style="flex:1;min-width:220px;text-align:left;padding:8px 10px" onclick="${onBg}"><b>${esc(est.choices?.background?.label || 'Analyze in background')}</b> · ${money(est.background)}${badge('background')}<div class="muted" style="font-weight:normal">${esc(est.choices?.background?.detail || 'Up to 24 hours · ~50% lower model cost')}</div></button>
      <button class="small ghost" onclick="$('#sugMsg').innerHTML=''">Cancel</button></div></div>`;
}
globalThis.analyzeChooser = async function analyzeChooser(force) {
  $('#sugMsg').innerHTML = '<span class="spin"></span> pricing…';
  let est;
  try { est = await post(`/api/projects/${state.project.id}/suggest/estimate`, { force }); } catch (e) { $('#sugMsg').textContent = 'Could not price the analysis: ' + (e.message || e); return; }
  if (!est.items) { $('#sugMsg').textContent = 'Every source has already been analysed for this project.'; return; }
  $('#sugMsg').innerHTML = transportChoiceHtml(est, `suggestNow(${force},'interactive')`, `suggestNow(${force},'batch')`, force ? 'Re-analyse' : 'Analyse');
}
globalThis.suggestNow = async function suggestNow(force, transport = 'interactive') {
  const r = await post(`/api/projects/${state.project.id}/suggest`, { force, transport });
  if (!r.job) { $('#sugMsg').textContent = 'Every source has already been analysed for this project.'; return; }
  if (transport === 'batch') { $('#sugMsg').innerHTML = `Queued in the background for ${r.sources} source${r.sources === 1 ? '' : 's'} — findings appear here as each source completes (up to 24 hours). Progress is in the Sources view.`; loadJobs(); setTimeout(loadNotes, 4000); return; }
  if (r.fast) { $('#sugMsg').innerHTML = `<span class="spin"></span> fast wave: ${r.fast.length} source${r.fast.length === 1 ? '' : 's'} will land first; their findings are provisional while ${r.warm.length} remaining source${r.warm.length === 1 ? '' : 's'} continue on the warm path. Later evidence can correct the early picture.`; loadJobs(); setTimeout(loadNotes, 4000); return; }
  $('#sugMsg').innerHTML = `<span class="spin"></span> reading ${r.sources} source${r.sources === 1 ? '' : 's'}…`;
  const tick = async () => { const j = await api('/api/jobs/' + r.job); if (j.status === 'done' || j.status === 'failed') { await loadNotes(); } else { $('#sugMsg').innerHTML = `<span class="spin"></span> ${esc(j.message || 'working…')}`; setTimeout(tick, 2500); } };
  setTimeout(tick, 2000);
}

// ---- settings ----
globalThis.saveProject = async function saveProject() {
  const p = await put('/api/projects/' + state.project.id, { name: $('#epName').value, brief: $('#epBrief').value, context: $('#epContext').value, goal: $('#epGoal').value, audience: $('#epAudience').value, output_pref: $('#epOutput').value, source_prefs: $('#epSourcePrefs').value, questions: $('#epQuestions').value.split('\n').map(t => t.trim()).filter(Boolean), tags: $('#epTags').value.split(',').map(t => t.trim()).filter(Boolean) });
  state.project = p; $('#wsName').textContent = p.name; $('#wsFoot').textContent = (p.brief || '').slice(0, 140); $('#saveMsg').textContent = 'Saved ✓'; setTimeout(() => $('#saveMsg').textContent = '', 2000);
  STALE.left = 0; await loadStaleness();
  if (STALE.data && STALE.data.anything_stale) toast(`Saved. ${STALE.data.stale_sources ? STALE.data.stale_sources + ' source analyses' : ''}${STALE.data.stale_sources && STALE.data.plan.status === 'stale' ? ' and ' : ''}${STALE.data.plan.status === 'stale' ? 'the Master Plan' : ''} now reflect an older brief — nothing is re-run until you ask (see Findings / Plan).`);
}
// 0.62.9 — Kyle: "I want to bulk remove some content that we are no longer pursuing but I dont know how." By
// CHANNEL, never by keyword: a keyword sweep on his project selected his own coaching notes and his core training,
// because general acquisition material uses the industries he dropped as examples.
globalThis.RET = { channels: [], picked: new Set() };
globalThis.loadRetireChannels = async function loadRetireChannels() {
  const box = $('#retList'); box.textContent = 'reading the project…';
  try {
    const r = await api(`/api/projects/${state.project.id}/retire/channels`);
    globalThis.RET = { channels: r.channels || [], picked: new Set() };
    box.innerHTML = RET.channels.map(c => `<label class="row" style="gap:6px;padding:2px 0">
      <input type="checkbox" onchange="retToggle(${JSON.stringify(c.channel).replace(/"/g, '&quot;')}, this.checked)">
      <span class="grow">${esc(c.channel)}</span>
      <span class="muted">${c.sources} source${c.sources === 1 ? '' : 's'} · ${c.hours} h · ${c.findings} findings</span></label>`).join('')
      || '<div class="muted">no channels</div>';
  } catch (e) { box.textContent = 'could not read: ' + (e.message || e); }
}
globalThis.retToggle = function retToggle(ch, on) { on ? RET.picked.add(ch) : RET.picked.delete(ch); retPreview(); }
globalThis.retPreview = async function retPreview() {
  const box = $('#retPreview');
  if (!RET.picked.size) { box.innerHTML = ''; return; }
  box.textContent = 'working out what that would do…';
  try {
    const r = await post(`/api/projects/${state.project.id}/retire/preview`, { channels: [...RET.picked] });
    box.innerHTML = `<div class="banner"><b>${r.sources} sources (${r.hours} h) would leave this project.</b>
      <div class="mt-1">${r.findings} findings dismissed · <b>${r.claims_losing_all_evidence}</b> Claims would lose every piece of evidence the project still holds and are rejected · ${r.claims_partly_affected} keep some evidence and are re-assessed.</div>
      <div class="muted mt-1">Reversible: ${esc(r.reversible)}</div>
      <div style="margin-top:6px"><button class="small danger" onclick="retApply()">Retire these ${r.sources} sources</button></div></div>`;
  } catch (e) { box.textContent = 'could not preview: ' + (e.message || e); }
}
globalThis.retApply = async function retApply() {
  const reason = ($('#retReason').value || '').trim();
  if (!confirm(`Retire ${RET.picked.size} channel(s) from this project? Sources stay in your library and this is reversible.`)) return;
  const box = $('#retPreview'); box.textContent = 'retiring…';
  try {
    const r = await post(`/api/projects/${state.project.id}/retire`, { channels: [...RET.picked], reason });
    box.innerHTML = `<div class="banner"><b>Done.</b> ${r.sources_removed} sources left the project, ${r.findings_dismissed} findings dismissed, ${r.claims_rejected} Claims rejected. Recorded as a project decision.</div>`;
    RET.picked = new Set();
    loadRetireChannels(); loadSources(); loadJobs();
  } catch (e) { box.textContent = 'could not retire: ' + (e.message || e); }
}
globalThis.deleteProject = async function deleteProject() { if (!confirm('Delete this project, its chats and findings?')) return; await del('/api/projects/' + state.project.id); location.hash = ''; goHome(); }

// ---- facts ----
globalThis.renderFacts = function renderFacts(facts) {
  $('#facts').innerHTML = facts.map(f => `<div class="row" style="padding:4px 0;border-bottom:1px solid var(--line)"><span class="tag" style="flex:0 0 auto">${esc(f.kind)}</span><span class="grow">${esc(f.content)}</span><a href="#" class="muted" onclick="del('/api/facts/${f.id}').then(()=>api('/api/projects/'+state.project.id).then(p=>renderFacts(p.facts)));return false">remove</a></div>`).join('') || '<div class="muted">none yet</div>';
}
globalThis.addFact = async function addFact() {
  const t = $('#factText').value.trim(); if (!t) return;
  await post(`/api/projects/${state.project.id}/facts`, { kind: $('#factKind').value, content: t }); $('#factText').value = '';
  const p = await api('/api/projects/' + state.project.id); renderFacts(p.facts);
}

// ---- master plan ----
globalThis.STATUSES = ['not_started', 'ready', 'blocked', 'in_progress', 'complete', 'needs_research', 'needs_decision'];
globalThis.stLabel = s => (s || 'not_started').replace(/_/g, ' ');
globalThis.planState = null;


export const moduleName = "research";
