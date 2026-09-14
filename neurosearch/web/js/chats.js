// ---- chats ----
globalThis.loadChats = async function loadChats() {
  state.chats = await api('/api/conversations?project_id=' + state.project.id);
  $('#nChats').textContent = state.chats.length;
  const now = Date.now() / 1000, cRow = c => `<div class="c ${c.id === state.conv ? 'active' : ''}" onclick="selectChat('${c.id}')"><span>${esc(c.title || 'Untitled chat')}</span></div>`;
  const bands = [['Today', c => c.updated_at && now - c.updated_at < 86400], ['This week', c => c.updated_at && now - c.updated_at < 86400 * 7], ['Older', () => true]];
  let rest = state.chats;
  const grouped = bands.map(([label, test]) => { const match = rest.filter(test); rest = rest.filter(c => !test(c)); return [label, match]; }).filter(([, arr]) => arr.length);
  $('#chatList').innerHTML = `<div class="newc"><button class="small" style="width:100%" onclick="newChat()">＋ New chat</button></div>` +
    (grouped.length > 1 ? grouped.map(([label, arr]) => `<div class="chatGroupLabel">${label}</div>` + arr.map(cRow).join('')).join('') : state.chats.map(cRow).join(''));
}
globalThis.newChat = async function newChat() {
  const c = await post('/api/conversations', { project_id: state.project.id, title: null });
  await loadChats(); await selectChat(c.id); showView('chats');
}
globalThis.selectChat = async function selectChat(id, push = true) {
  state.conv = id;
  document.querySelectorAll('#chatList .c').forEach((el, i) => el.classList.toggle('active', state.chats[i]?.id === id));
  const c = state.chats.find(x => x.id === id);
  $('#chatTitle').textContent = c ? (c.title || 'Untitled chat') : 'New chat';
  if (id) {
    $('#chat').innerHTML = listState('loading', { label: 'Loading this chat…' });
    let ms; try { ms = await api('/api/conversations/' + id); }
    catch (e) { $('#chat').innerHTML = listState('failed', { message: "Couldn't load this chat.", retry: `selectChat('${id}', false)` }); if (push) showView('chats'); $('#q').focus(); return; }
    if (!ms.length) { emptyChat(); if (c?.title && (state.project.questions || []).includes(c.title)) $('#q').value = c.title; }
    else ms.forEach(m => addMsg(m.role, m.content, m.citations || [], { meta: m.meta || {}, no_pin: false }));
  } else emptyChat();
  if (push) { showView('chats'); }
  $('#q').focus();
}
globalThis.emptyChat = function emptyChat() {
  const p = state.project, n = +($('#nSources').textContent || p.n_sources || 0);
  $('#chat').innerHTML = `<div class="empty"><b>${esc(p.name)}</b> · ${n} source${n === 1 ? '' : 's'} in scope.<br><br>
    Every chat here only sees this project's sources, so you can run several independent lines of inquiry on the same material.
    Answers cite the source and the exact timestamp or page.<br><br>
    Things you can say: <i>paste a YouTube/playlist link</i> to add it · <i>“refocus the brief on …”</i> · <i>“pin that as a finding”</i>.
    ${(p.questions || []).length ? `<br><br>Starting questions:<br>${p.questions.map(q => `<a href="#" class="chip" onclick="$('#q').value=${JSON.stringify(q).replace(/"/g, '&quot;')};$('#q').focus();return false">${esc(q)}</a>`).join(' ')}` : ''}</div>`;
}
globalThis.renameChat = async function renameChat() {
  if (!state.conv) return; const c = state.chats.find(x => x.id === state.conv);
  const t = prompt('Chat title', c?.title || ''); if (t === null) return;
  await put('/api/conversations/' + state.conv, { title: t }); await loadChats(); $('#chatTitle').textContent = t || 'Untitled chat';
}
globalThis.deleteChat = async function deleteChat() {
  if (!state.conv || !confirm('Delete this chat?')) return;
  await del('/api/conversations/' + state.conv); state.conv = null; await loadChats(); await selectChat(state.chats[0]?.id || null);
}
globalThis.renderAnswer = function renderAnswer(text, cites) {
  const byN = Object.fromEntries(cites.map(c => [c.n, c]));
  return esc(text).replace(/\*\*([^*\n]+)\*\*/g, '<b>$1</b>').replace(/\[(\d{1,2})\]/g, (m, n) => byN[n] ? (byN[n].removed ? `<sup title="${esc(byN[n].title)} — this source was removed">[${n}⚠]</sup>` : `<a href="${esc(byN[n].link)}" target="_blank" title="${esc(byN[n].title)} @ ${byN[n].timestamp}"><sup>[${n}]</sup></a>`) : m);
}
globalThis.addMsg = function addMsg(role, text, cites = [], extra = {}) {
  const empty = $('#chat .empty'); if (empty) empty.remove();
  const d = document.createElement('div'); d.className = 'msg ' + role;
  if (role === 'user') d.textContent = text;
  else {
    let h = renderAnswer(text, cites);
    if (cites.length) h += `<div class="cites">` + cites.map(c => c.removed ? `<span class="chip" title="This source was deleted after the answer was written">⚠ [${c.n}] ${esc(c.title)} — source removed</span>` : `<a class="chip" href="${esc(c.link)}" target="_blank">[${c.n}] ${esc(c.title)} @ ${c.timestamp}</a>` + (c.source_id ? ` <a href="#" class="chip" title="See the Claims resting on this source" onclick="whyThisAnswer('${esc(c.source_id)}','${esc(c.timestamp || '')}');return false">why</a>` : '')).join('') + `</div>`;
    const val = extra.validation || extra.meta || {};
    if (val.warning) h += `<div class="web status-warn">⚠ ${esc(val.warning)}</div>`;
    else if (val.repaired) h += `<div class="web muted">✓ citations were corrected after a validation check</div>`;
    if (extra.web_sources?.length) h += `<div class="web">Web: ` + extra.web_sources.map(w => `<a href="${esc(w.url)}" target="_blank">${esc(w.title)}</a>`).join(' · ') + `</div>`;
    for (const a of extra.actions || []) {
      if (a.type === 'brief_updated') h += `<div class="web">✎ Brief updated: <i>${esc(a.brief)}</i></div>`;
      if (a.type === 'finding_saved') h += `<div class="web">📌 Pinned to findings.</div>`;
      if (a.type === 'gap_noted') h += `<div class="web">⚠ Gap recorded in findings. <button class="small ghost" title="Turns this into an Open question in Research, with the normal project → library → seen → web escalation" onclick="settleGap(${JSON.stringify(a.gap).replace(/"/g, '&quot;')})">Settle this</button></div>`;
      if (a.type === 'fact_recorded') h += `<div class="web">🗂 Recorded ${esc(a.kind)}: <i>${esc(a.content)}</i></div>`;
      if (a.type === 'library_searched') h += `<div class="web">🗄 Checked your global library for “${esc(a.query)}” · ${a.found} owned-but-unattached source${a.found === 1 ? '' : 's'}${a.found ? ': ' + (a.suggestions || []).map(s => `<button class="small" style="margin:2px" onclick="attachFromLibrary('${s.source_id}', this)">Add “${esc((s.title || '').slice(0, 40))}”</button>`).join('') : ''}</div>`;
      if (a.type === 'research_state') h += `<div class="web muted">Consulted the Knowledge Map · strong ${a.counts?.strong || 0} / developing ${a.counts?.developing || 0} / weak ${a.counts?.weak || 0} · ${a.tensions} open tension${a.tensions === 1 ? '' : 's'} · ${a.targets_open} open target${a.targets_open === 1 ? '' : 's'}</div>`;
      if (a.type === 'claim_proposed') h += `<div class="web">Proposed Claim (needs evidence): <i>${esc(a.text)}</i> — see Research</div>`;
      if (a.type === 'work_resolved') h += `<div class="web muted">📜 Resolved “${esc(a.text || '')}” → ${a.identity === 'resolved' ? esc(a.work || '') + ' · ' + esc(a.access || '') : 'identity unresolved'}</div>`;
      if (a.type === 'candidates_searched') h += `<div class="web muted">🗂 Checked what we've seen but not added for “${esc(a.query)}” · ${a.found} candidate${a.found === 1 ? '' : 's'}${a.found ? ' — see Sources → Library → Seen, not added' : ''}</div>`;
      if (a.type === 'searched') h += `<div class="web muted">🔎 Searched the library for “${esc(a.query)}”${a.filter ? ' in ' + esc(a.filter) : ''} · ${a.added} more excerpt${a.added === 1 ? '' : 's'}</div>`;
      if (a.type === 'priority_set') h += `<div class="web">★ ${a.priority ? 'Priority sources' : 'No longer priority'} (${a.count}): <i>${esc((a.titles || []).slice(0, 5).join('; '))}${a.count > 5 ? ' …' : ''}</i> — retrieval ${a.priority ? 'now favours them' : 'treats them normally'}</div>`;
      if (a.type === 'calculated') h += `<div class="web">🧮 Ran the spreadsheet with ${Object.entries(a.inputs || {}).map(([k, v]) => `${esc(k)} = ${esc(String(v))}`).join(', ') || 'current inputs'} → ${Object.entries(a.outputs || {}).slice(0, 6).map(([k, v]) => `<b>${esc(k)}</b>: ${typeof v === 'number' ? v.toLocaleString(undefined, { maximumFractionDigits: 2 }) : esc(String(v))}`).join(' · ')}</div>`;
    }
    if (extra.ingest_jobs?.length) h += `<div class="web ingest">` + extra.ingest_jobs.map(j => { const l = esc((j.url || '').replace(/^https?:\/\/(www\.)?/, '').slice(0, 48)); return j.job_id ? `<span class="chip" data-job="${j.job_id}" data-label="${l}">⏳ ${l}</span>` : `<span class="chip" title="${esc(j.detected?.detail || '')}" style="cursor:pointer" onclick="showView('sources');$('#inUrls').value='${esc(j.url || '')}';classifyInput()">🔍 ${l} — ${esc(j.detected?.label || 'detected')} · choose in Sources → Add</span>`; }).join('') + `</div>`;
    // Portable Answers (C0): one-click copy that keeps every source, its deep link and every evidence-status warning.
    const warns = [];
    if (val.warning) warns.push(val.warning);
    for (const a of extra.actions || []) if (a.type === 'gap_noted') warns.push('Research gap recorded: this answer identified something the sources do not yet cover.');
    h += `<div class="tools"><button class="small ghost" onclick="copyMenu(this)">⧉ Copy ▾</button><button class="small ghost" onclick="shareMenu(this)">↗ Share ▾</button>` + (cites.length && !extra.no_pin ? `<button class="small ghost" onclick="pinMsg(this)">📌 Pin to findings</button>` : '') + `<span class="muted copied text-xs"></span></div>`;
    d.innerHTML = h; d.dataset.text = text; d.dataset.cites = JSON.stringify(cites); d.dataset.warns = JSON.stringify(warns);
  }
  $('#chat').appendChild(d); d.scrollIntoView({ block: 'end' });
  return d;
}
// ---- Portable Answers and Evidence: every assistant message copies with human-readable citations + original deep links.
globalThis.citeLabel = function citeLabel(c) { return (c.title || 'Untitled source') + (c.timestamp ? ', ' + c.timestamp : ''); }
globalThis.exportMsg = function exportMsg(d, mode) {
  const text = d.dataset.text || '', cites = JSON.parse(d.dataset.cites || '[]'), warns = JSON.parse(d.dataset.warns || '[]');
  const byN = Object.fromEntries(cites.map(c => [c.n, c]));
  const used = cites.filter(c => new RegExp('\\[' + c.n + '\\]').test(text));
  const list = used.length ? used : cites;
  let body = text;
  if (mode === 'plain') body = body.replace(/\*\*([^*\n]+)\*\*/g, '$1').replace(/ ?\[(\d{1,2})\]/g, (m, n) => byN[n] ? ` (${citeLabel(byN[n])})` : m);
  if (mode === 'markdown') body = body.replace(/\[(\d{1,2})\]/g, (m, n) => byN[n] && byN[n].link ? `[[${n}]](${byN[n].link})` : m);
  const warnBlock = warns.length ? '\n\n' + warns.map(w => (mode === 'markdown' ? '> ⚠ ' : '⚠ ') + w).join('\n') : '';
  if (mode === 'response') return body + warnBlock;
  const src = list.map((c, i) => {
    const label = (c.removed ? '[source removed] ' : '') + citeLabel(c);
    if (mode === 'markdown') return `${i + 1}. ${c.link ? `[${label}](${c.link})` : label}`;
    return `${i + 1}. ${label}` + (c.link ? `\n   ${c.link}` : '');
  }).join('\n');
  const srcHead = mode === 'markdown' ? '\n\n### Sources\n' : '\n\nSources\n';
  return body + warnBlock + (list.length ? srcHead + src : '');
}
globalThis.copyMenu = function copyMenu(btn) {
  const bar = btn.parentElement; const open = bar.querySelector('.menu'); if (open) { open.remove(); return; }
  const m = document.createElement('div'); m.className = 'menu';
  m.innerHTML = [['sources', 'Copy response + sources'], ['response', 'Copy response'], ['plain', 'Copy plain text'], ['markdown', 'Copy Markdown']]
    .map(([k, l]) => `<button onclick="copyMsg(this,'${k}')">${l}</button>`).join('');
  bar.appendChild(m);
  setTimeout(() => document.addEventListener('click', function h(e) { if (!m.contains(e.target)) { m.remove(); document.removeEventListener('click', h); } }), 0);
}
// C0 Share ▾: a shorter version of the finished answer (one model call, never new research), copied WITH its sources and
// evidence warnings exactly like Copy ▾ — a warning must survive every variant.
globalThis.shareMenu = function shareMenu(btn) {
  const bar = btn.parentElement; const open = bar.querySelector('.menu'); if (open) { open.remove(); return; }
  const m = document.createElement('div'); m.className = 'menu';
  // 0.60.0: two audiences, not four lengths. The cited variants are for someone who may want to go and check;
  // the plain ones are for someone who just wants to know the thing (no markers, no names, no research voice).
  m.innerHTML = [['short|cited', 'Short + sources (2–3 sentences)'], ['medium|cited', 'Medium + sources (one paragraph)'], ['full|cited', 'Full answer + sources'],
                 ['sep', ''],
                 ['short|plain', '👥 Plain, short — no sources or names'], ['medium|plain', '👥 Plain, one paragraph'], ['long|plain', '👥 Plain, a few paragraphs']]
    .map(([k, l]) => k === 'sep' ? '<div style="border-top:1px solid var(--line);margin:4px 0"></div>' : `<button onclick="shareMsg(this,'${k}')">${l}</button>`).join('');
  bar.appendChild(m);
  setTimeout(() => document.addEventListener('click', function h(e) { if (!m.contains(e.target)) { m.remove(); document.removeEventListener('click', h); } }), 0);
}
// 0.61.0: which failure classes a retry can never help with (mirrors db.FAILURE_CLASSES).
globalThis.PERMANENT_FAILURES = new Set(['no_media', 'unavailable', 'not_found', 'uploaded_file']);
globalThis.SHARE_CACHE = {};
globalThis.toClipboard = async function toClipboard(txt) {
  try { await navigator.clipboard.writeText(txt); }
  catch (e) { const t = document.createElement('textarea'); t.value = txt; document.body.appendChild(t); t.select(); document.execCommand('copy'); t.remove(); }
}
globalThis.shareMsg = async function shareMsg(btn, spec) {
  const [length, mode] = spec.split('|');
  const d = btn.closest('.msg'); const menu = d.querySelector('.menu'); if (menu) menu.remove();
  const s = d.querySelector('.copied');
  if (length === 'full') return copyMsg(btn, 'sources');
  const key = (d.dataset.text || '').slice(0, 200) + '|' + spec;
  try {
    if (s) s.textContent = mode === 'plain' ? 'writing the plain version…' : 'writing the ' + length + ' version…';
    let v = SHARE_CACHE[key];
    if (!v) { v = await post('/api/share', { text: d.dataset.text || '', citations: JSON.parse(d.dataset.cites || '[]'), length, mode, project_id: state.project && state.project.id }); SHARE_CACHE[key] = v; }
    // A plain version is copied as TEXT ONLY — attaching the source list is the thing it exists to remove. The
    // uncertainty is not dropped with it: it is carried inside the prose, and the server says so when it is not.
    let out;
    if (mode === 'plain') { out = v.text; }
    else { const orig = d.dataset.text; d.dataset.text = v.text; out = exportMsg(d, 'sources'); d.dataset.text = orig; }
    await toClipboard(out);
    if (s) {
      s.textContent = (mode === 'plain'
        ? 'Copied the plain version — no sources or names'
        : `Copied ${length} version with ${(v.markers || []).length} source${(v.markers || []).length === 1 ? '' : 's'}`)
        + (v.warning ? ' · ⚠ ' + v.warning : '');
      setTimeout(() => s.textContent = '', v.warning ? 9000 : 4000);
    }
  } catch (e) { if (s) s.textContent = 'could not write the version: ' + e.message; }
}
// 0.60.0: the same thing for a whole chat. Kyle wants to send someone what came out of a conversation, not the
// back-and-forth — so this is one call over what was already written, never a new research pass.
globalThis.shareChatMenu = async function shareChatMenu(btn) {
  const bar = btn.parentElement; const open = bar.querySelector('.menu'); if (open) { open.remove(); return; }
  const m = document.createElement('div'); m.className = 'menu';
  m.innerHTML = [['long|plain', '👥 Plain retelling (a few paragraphs)'], ['medium|plain', '👥 Plain, one paragraph'], ['long|cited', 'With sources (a few paragraphs)']]
    .map(([k, l]) => `<button onclick="shareChat(this,'${k}')">${l}</button>`).join('');
  bar.appendChild(m);
  setTimeout(() => document.addEventListener('click', function h(e) { if (!m.contains(e.target)) { m.remove(); document.removeEventListener('click', h); } }), 0);
}
globalThis.shareChat = async function shareChat(btn, spec) {
  const [length, mode] = spec.split('|');
  const menu = btn.closest('.menu'); if (menu) menu.remove();
  if (!state.conv) return toast('open a chat first', 'err');
  const s = $('#shareChatMsg');
  try {
    if (s) s.textContent = 'reading the chat back…';
    const v = await post(`/api/conversations/${state.conv}/share`, { length, mode });
    await toClipboard(v.text);
    const cov = v.covered || {};
    if (s) {
      s.textContent = `Copied — ${cov.messages || 0} message${cov.messages === 1 ? '' : 's'} retold`
        + (mode === 'plain' ? ', no sources or names' : ' with sources')
        + (v.warning ? ' · ⚠ ' + v.warning : '');
      setTimeout(() => s.textContent = '', v.warning ? 12000 : 5000);
    }
  } catch (e) { if (s) s.textContent = 'could not retell the chat: ' + (e.message || e); }
}
globalThis.copyMsg = async function copyMsg(btn, mode) {
  const d = btn.closest('.msg'); const out = exportMsg(d, mode); const n = JSON.parse(d.dataset.cites || '[]').length;
  try { await navigator.clipboard.writeText(out); } catch (e) { const t = document.createElement('textarea'); t.value = out; document.body.appendChild(t); t.select(); document.execCommand('copy'); t.remove(); }
  const s = d.querySelector('.copied'); if (s) { s.textContent = mode === 'response' ? 'Copied' : `Copied with ${n} source${n === 1 ? '' : 's'}`; setTimeout(() => s.textContent = '', 2000); }
  const menu = d.querySelector('.menu'); if (menu) menu.remove();
}
// A new project's first findings must not queue behind another project's backlog (Kyle, live 2026-09-09:
// "the app is useless if I need to wait 24 hours"). Free: this changes queue ORDER only.
globalThis.FWAVE = { queued: 0 };
globalThis.firstWave = async function firstWave() {
  try {
    const r = await post(`/api/projects/${state.project.id}/findings/first-wave`, {});
    toast(r.promoted ? `⏫ ${r.promoted} moved to the front — they start within a minute` : 'nothing queued to move');
  } catch (e) { toast(e.message || e, 'err'); }
  loadJobs(); if (typeof loadNotes === 'function') loadNotes();
}
globalThis.pinMsg = async function pinMsg(btn) {
  const d = btn.closest('.msg');
  await post(`/api/projects/${state.project.id}/notes`, { content: d.dataset.text, citations: JSON.parse(d.dataset.cites) });
  btn.textContent = 'Pinned ✓'; btn.disabled = true; $('#nFindings').textContent = +($('#nFindings').textContent || 0) + 1;
}
// ---- attachments in chat (0.24.1): documents are read right away through the normal upload path and pinned into this turn's excerpts
state.attached = [];
globalThis.attachFiles = async function attachFiles(files) {
  for (const f of files) {
    const chip = document.createElement('span'); chip.className = 'chip'; chip.textContent = `⏳ ${f.name}`; $('#qAttach').appendChild(chip);
    const fd = new FormData(); fd.append('file', f); fd.append('project_id', state.project.id); fd.append('immediate', 'true');
    try {
      const r = await uiFetch('/api/ingest/file', { method: 'POST', body: fd }); const j = await r.json();
      if (!r.ok) throw new Error(j.detail || j.error || 'upload failed');
      if (j.immediate) { state.attached.push({ id: j.source_id, name: j.title || f.name }); chip.textContent = `📎 ${j.title || f.name} ✓`; chip.title = 'read and added to this project — will be used in your next question'; }
      else { chip.textContent = `⏳ ${f.name} — transcribing in the background`; chip.title = j.note || ''; }
    } catch (e) { chip.textContent = `✗ ${f.name}: ${e.message}`; chip.style.color = 'var(--bad)'; }
  }
  $('#qFile').value = ''; if (state.project) api('/api/projects/' + state.project.id).then(p => { state.project = p; $('#nSources').textContent = p.n_sources; }).catch(() => {});
}
// R1: one answer, narrated. The server streams phases and text; `done` carries the identical /api/ask payload,
// so the finished message is rendered from the real result (citations, actions, validation) — the streamed text is
// only what the user reads while it is being written.
globalThis.askStream = async function askStream(payload, onEvent) {
  const r = await uiFetch('/api/ask/stream', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
  if (r.status === 401) { location.reload(); return; }
  if (!r.ok || !r.body) { const j = await r.json().catch(() => ({})); throw new Error(j.error || j.detail || r.statusText); }
  const rd = r.body.getReader(), dec = new TextDecoder(); let buf = '';
  for (;;) {
    const { value, done } = await rd.read(); if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf('\n\n')) >= 0) {
      const frame = buf.slice(0, i); buf = buf.slice(i + 2);
      for (const line of frame.split('\n')) {
        if (!line.startsWith('data: ')) continue;                       // ": still working" heartbeats land here
        let ev; try { ev = JSON.parse(line.slice(6)); } catch (e) { continue; }
        onEvent(ev);
      }
    }
  }
}
globalThis.ask = async function ask() {
  const q = $('#q').value.trim(); if (!q) return;
  if (!state.conv) { const c = await post('/api/conversations', { project_id: state.project.id }); state.conv = c.id; await loadChats(); }
  const attached = state.attached.splice(0); $('#qAttach').innerHTML = '';
  $('#q').value = ''; addMsg('user', q + (attached.length ? `\n📎 ${attached.map(a => a.name).join(', ')}` : ''));
  const thinking = addMsg('assistant', '');
  const t0 = Date.now();
  let phase = "searching this project's sources…", live = '', tick = null;
  const paint = () => {
    const secs = Math.round((Date.now() - t0) / 1000);
    thinking.innerHTML = live
      ? `<div class="liveAnswer"></div><div class="muted" style="margin-top:6px"><span class="spin"></span> ${esc(phase)} · ${secs}s</div>`
      : `<span class="spin"></span> <span class="muted">${esc(phase)} · ${secs}s</span>`;
    if (live) thinking.querySelector('.liveAnswer').textContent = live;
    const sc = $('#chat'); if (sc) sc.scrollTop = sc.scrollHeight;
  };
  paint(); tick = setInterval(paint, 1000);          // the elapsed counter is the proof it is not frozen
  $('#askBtn').disabled = true;
  try {
    let r = null, err = null;
    await askStream({ question: q, project_id: state.project.id, conversation_id: state.conv, use_web: $('#useWeb').checked,
                      attached_source_ids: attached.length ? attached.map(a => a.id) : null },
      ev => {
        if (ev.type === 'phase') { phase = ev.label; paint(); }
        else if (ev.type === 'delta') { live += ev.text; paint(); }
        else if (ev.type === 'done') r = ev.result;
        else if (ev.type === 'error') err = ev.message;
      });
    clearInterval(tick); tick = null;
    if (err) throw new Error(err);
    if (!r) throw new Error('the answer stream ended before the answer did — nothing was saved; ask again');
    thinking.remove();
    const m = addMsg('assistant', r.answer, r.citations, r);
    const c = state.chats.find(x => x.id === state.conv);
    if (c && !c.title) { await put('/api/conversations/' + state.conv, { title: q.slice(0, 60) }); await loadChats(); $('#chatTitle').textContent = q.slice(0, 60); }
    if (r.ingest_jobs?.some(j => j.job_id)) watchIngest(m, r.ingest_jobs.filter(j => j.job_id).map(j => j.job_id));
    if ((r.actions || []).some(a => a.type === 'brief_updated')) { state.project.brief = r.project.brief; $('#epBrief').value = r.project.brief; $('#wsFoot').textContent = r.project.brief.slice(0, 140); }
    if ((r.actions || []).some(a => a.type !== 'brief_updated')) $('#nFindings').textContent = +($('#nFindings').textContent || 0) + 1;
  } catch (e) { if (tick) clearInterval(tick); thinking.innerHTML = `<span class="status-bad">${esc(e.message)}</span>`; }
  $('#askBtn').disabled = false;
}
globalThis.watchIngest = async function watchIngest(msgEl, jobIds) {
  const tick = async () => {
    let pending = 0;
    for (const id of jobIds) {
      const j = await api('/api/jobs/' + id).catch(() => null); if (!j) continue;
      const chip = msgEl.querySelector(`[data-job="${id}"]`); if (!chip) continue;
      const label = chip.dataset.label;
      if (j.status === 'done') { const r = j.result || {};
        const cnt = r.counts ? ` — ${r.counts.already_in_library || 0} already in your library, ${r.counts.new || 0} new` : '';
        chip.textContent = r.review ? `📋 ${r.title || label}: ${r.proposed} videos waiting for your approval in Sources${cnt}`
          : r.already_pending ? `⏳ ${r.title || label} — already being ingested for another project; it joins this one when it finishes`
          : r.failed ? `⚠ ${r.title || label} — attached, but its last acquisition failed (Retry it in Sources)`
          : r.already_ingested ? `✓ ${r.title || label} — already in your library, attached (nothing re-downloaded)`
          : `✓ ${r.title || label}` + (r.found ? ` (${r.found} videos, ${r.queued} queued${cnt})` : '');
        if (r.review) { chip.style.cursor = 'pointer'; chip.onclick = () => showView('sources'); } }
      else if (j.status === 'failed') { chip.textContent = `✗ ${label}`; chip.title = j.message || ''; }
      else { chip.textContent = `⏳ ${label} ${j.message ? '· ' + j.message : ''}`; pending++; }
    }
    if (pending) setTimeout(tick, 3000); else { const p = await api('/api/projects/' + state.project.id); state.project = p; $('#nSources').textContent = p.n_sources; }
  };
  setTimeout(tick, 1500);
}
$('#q').addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); ask(); } });



export const moduleName = "chats";
