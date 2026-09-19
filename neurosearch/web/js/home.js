// ================= home =================
globalThis.loadSpend = async function loadSpend(quiet) {
  try {
    const u = await api('/api/usage', quiet ? { ack: false } : {});
    const h = $('#homeSpend'); if (h) h.innerHTML = statusBar(u);
    const sd = $('#sideSpend'); if (sd) sd.innerHTML = statusBar(u, true);
    state.usage = u; return u;
  } catch (e) { return null; }
}
globalThis.goHome = async function goHome() {
  loadSpend();
  state.project = null; state.conv = null;
  $('#ws').classList.remove('active'); $('#home').hidden = false;
  if (location.hash) history.replaceState(null, '', location.pathname);
  const [ps, st] = await Promise.all([api('/api/projects'), api('/api/stats')]);
  $('#homeStats').textContent = `${st.ready} sources · ${st.total_hours} h of material in the library.`;
  api('/api/stats/fun').then(f => { $('#homeFun').innerHTML = funCard(f, 'Your research in numbers'); }).catch(() => {});
  // M-1: a 0-source project previously read identically to an 876-source one -- an unambiguous,
  // data-grounded attention signal (no sources yet) plus a relative "last touched" reading, which is
  // more scannable than a bare calendar date, are the two the ladder asks for without inventing a
  // staleness threshold nothing in evidence supports.
  $('#projGrid').innerHTML = ps.map(p => `<div class="pcard" onclick="location.hash='#p/${p.id}/chats'">
      <div class="name">${esc(p.name)}</div><div class="brief">${esc(p.goal || p.brief || 'No brief yet')}</div>
      <div class="meta">${p.n_sources ? `${p.n_sources} sources · updated ${relTime(p.updated_at)}` : '<span class="tag warn">Needs sources</span>'}</div></div>`).join('')
    + `<div class="pcard new" onclick="newProjectDialog()">＋ New project</div>`;
}
globalThis.WIZ = { step: 0, data: {} };
globalThis.newProjectDialog = function newProjectDialog() { WIZ.step = 0; WIZ.data = {}; WIZ.open = {}; renderWizard(); dlg.showModal(); }
globalThis.wizField = function wizField(id, label, ph, rows) {
  const v = esc(WIZ.data[id] || '');
  return `<label class="muted" style="display:block;margin-top:10px">${label}</label>` + (rows ? `<textarea id="w_${id}" rows="${rows}" placeholder="${esc(ph)}">${v}</textarea>` : `<input id="w_${id}" placeholder="${esc(ph)}" value="${v}">`);
}
globalThis.wizCollect = function wizCollect() { document.querySelectorAll('#dlgBody [id^=w_]').forEach(el => WIZ.data[el.id.slice(2)] = el.value); }
globalThis.renderWizard = function renderWizard() {
  const open = WIZ.open || {};
  const sec = (key, title, inner) => `<details ${open[key] ? 'open' : ''} ontoggle="WIZ.open=WIZ.open||{};WIZ.open['${key}']=this.open" style="margin-top:12px;border:1px solid var(--line);border-radius:10px;padding:8px 12px"><summary style="cursor:pointer;color:var(--muted)">${title}</summary>${inner}</details>`;
  // BOOTSTRAP R1: name + goal is the whole required form. Everything below is optional and can equally be added
  // inside the project — the point is to start searching what the user already owns before asking them anything else.
  let body = `<h2 style="margin-bottom:2px">Start a project</h2><div class="muted">Two things get you going. Neuro Search starts searching the research you already have straight away; everything else is optional, now or later.</div>` +
    wizField('name', 'Project name', 'e.g. Personal Portfolio Redesign') +
    wizField('goal', 'What do you want to accomplish?', 'e.g. Build a modern portfolio website that showcases my video work and helps me apply for senior creative roles.', 3) +
    sec('u', 'Links to start with — videos, playlists, whole channels, podcasts', wizField('urls', 'One per line', 'https://www.youtube.com/watch?v=…\nhttps://www.youtube.com/@somechannel', 3)) +
    sec('q', 'Starting questions — each becomes a ready-made chat', wizField('questions', 'One per line', 'What do they say about raising average ticket?\nHow do they structure the sales process?', 3)) +
    sec('b', 'A longer brief, if the goal needs one', wizField('brief', 'What are you trying to find out?', 'e.g. How top service-business operators price, sell and scale.', 3)) +
    sec('s', 'Your situation — budget, deadline, experience, what you already have or decided',
      wizField('budget', 'Budget', 'e.g. under $500') + wizField('deadline', 'Deadline / timing', 'e.g. by end of October') +
      wizField('experience', 'Your experience with this', 'e.g. 5 years running the business, never built a sales system') +
      wizField('tools', 'Tools and accounts you already have', 'e.g. HubSpot, Google Workspace') +
      wizField('constraints', 'Hard constraints (must / must not)', 'e.g. no new hires this year', 2) +
      wizField('decided', 'Already decided or rejected', 'e.g. decided: keep HubSpot · rejected: outsourcing sales', 2)) +
    sec('o', 'Output — who it\'s for and what you want at the end', wizField('audience', 'Who is this for?', 'e.g. just me · my partner · a client') +
      wizField('output_pref', 'What do you want at the end?', 'e.g. a recommendation and a step-by-step plan · a comparison · a content brief', 2) +
      wizField('source_prefs', 'Source preferences', 'e.g. practitioners over marketers; nothing older than 2024'));
  body += `<div class="row" style="margin-top:14px;justify-content:flex-end"><button class="primary" id="wizCreate" onclick="createProject()">Start project</button></div>`;
  $('#dlgBody').innerHTML = body; $('#w_name')?.focus();
}
globalThis.createProject = async function createProject() {
  wizCollect();
  const d = WIZ.data; if (!(d.name || '').trim()) { $('#w_name')?.focus(); return; }
  if (!(d.goal || '').trim() && !(d.brief || '').trim()) { $('#w_goal')?.focus(); return; }
  const lines = t => (t || '').split('\n').map(x => x.trim()).filter(Boolean);
  const ctx = [['Budget', d.budget], ['Deadline', d.deadline], ['Experience', d.experience], ['Tools/accounts available', d.tools], ['Constraints', d.constraints], ['Already decided/rejected', d.decided]]
    .filter(([, v]) => v && v.trim()).map(([k, v]) => `${k}: ${v.trim()}`).join('\n');
  const facts = [];
  if (d.budget) facts.push({ kind: 'constraint', content: 'Budget: ' + d.budget.trim() });
  if (d.deadline) facts.push({ kind: 'constraint', content: 'Deadline: ' + d.deadline.trim() });
  lines(d.constraints).forEach(c => facts.push({ kind: 'constraint', content: c }));
  lines(d.decided).forEach(c => facts.push({ kind: /reject/i.test(c) ? 'rejected' : 'decision', content: c.replace(/^(decided|rejected)\s*:\s*/i, '') }));
  const btn = $('#wizCreate'); if (btn) { btn.disabled = true; btn.textContent = 'Starting…'; }
  const p = await post('/api/projects', { name: d.name.trim(), goal: d.goal || null, brief: d.brief || null, context: ctx || null, questions: lines(d.questions),
    facts, urls: lines(d.urls), source_prefs: d.source_prefs || null, audience: d.audience || null, output_pref: d.output_pref || null, tags: [] });
  dlg.close(); location.hash = `#p/${p.id}/sources`;   // the bootstrap scan lands here; the project is usable immediately
}

// ================= workspace =================
globalThis.openProject = async function openProject(id, view, conv) {
  const p = await api('/api/projects/' + id).catch(() => null);
  if (!p) return goHome();
  const fresh = !state.project || state.project.id !== id;
  state.project = p;
  if (fresh && globalThis.resetSourceProjectState) resetSourceProjectState();
  $('#home').hidden = true; $('#ws').classList.add('active');
  $('#wsName').textContent = p.name; loadSpend();
  // 0.63.12 — the exact count, not the length of a capped list: this said "200" for a project with 17,845.
  $('#nSources').textContent = p.n_sources;
  $('#nFindings').textContent = (p.counts && (p.counts.approved || 0)) || (p.notes || []).length;
  $('#epName').value = p.name; $('#epBrief').value = p.brief || ''; $('#epTags').value = (p.tags || []).join(', '); $('#epContext').value = p.context || '';
  $('#epGoal').value = p.goal || ''; $('#epAudience').value = p.audience || ''; $('#epOutput').value = p.output_pref || ''; $('#epSourcePrefs').value = p.source_prefs || ''; $('#epQuestions').value = (p.questions || []).join('\n');
  renderFacts(p.facts || []);
  $('#expFind').href = `/api/projects/${id}/findings.md`; $('#expPlan').href = `/api/projects/${id}/masterplan.md`; $('#expZip').href = `/api/projects/${id}/masterplan.zip`;
  $('#wsFoot').textContent = p.brief ? p.brief.slice(0, 140) + (p.brief.length > 140 ? '…' : '') : 'No brief yet — add one in Settings.';
  loadStaleness();
  await loadChats();
  if (fresh || view !== state.view || conv !== state.conv) {
    if (view === 'chats') await selectChat(conv || (state.chats[0] && state.chats[0].id) || null, false);
    showView(view, false);
  }
}
globalThis.showView = function showView(v, push = true) {
  state.view = v;
  document.querySelectorAll('aside nav .item').forEach(i => i.classList.toggle('active', i.dataset.view === v));
  document.querySelectorAll('#main .view').forEach(s => s.classList.toggle('active', s.id === 'view-' + v));
  if (v === 'sources') { loadSources(); loadJobs(); loadBoot(); }
  if (v === 'chats') api('/api/projects/' + state.project.id).then(p => { state.project = p; $('#nSources').textContent = p.n_sources; if ($('#chat .empty')) emptyChat(); });
  if (v === 'findings') loadNotes();
  if (v === 'research') loadResearch();
  if (v === 'plan') loadPlan();
  if (v === 'settings') { api('/api/projects/' + state.project.id).then(p => renderFacts(p.facts || [])); loadBudget(); loadHealth(); }
  if (push) setHash(v, v === 'chats' ? state.conv : null);
}



export const moduleName = "home";
