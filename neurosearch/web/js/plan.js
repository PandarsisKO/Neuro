globalThis.loadPlan = async function loadPlan() {
  loadStaleness();
  const r = await api(`/api/projects/${state.project.id}/plan`);
  globalThis.planState = r;
  $('#nPlan').textContent = r.plan ? `v${r.plan.version}` : '';
  if (!r.plan) return renderNoPlan();
  renderPlan(r);
}
globalThis.renderNoPlan = function renderNoPlan() {
  const p = state.project;
  $('#planWrap').innerHTML = `<h2>Master Plan</h2>
    <div class="empty" style="margin-bottom:14px">Research answers <i>what do we need to know?</i> The Master Plan answers <i>given everything we know, how do we accomplish this?</i> — goal, recommended approach and alternatives, first steps you can start today, phases, dependencies, decisions (now vs later), tools, costs, risks with mitigations, beginner gotchas, what to ignore for now, open questions, and a ready-to-start checklist. Every recommendation is tied to its evidence and rated for confidence.</div>
    <div class="card"><b>Before building: tell the planner about the project</b>
      <div class="muted">Budget, deadline, your experience level, tools and accounts you already have, anything already decided. The more it knows, the more practical the plan.</div>
      <textarea id="planCtx" style="margin-top:8px;min-height:100px" placeholder="e.g. Budget ~$500. Need it live by end of October. I've never set up DNS before. We already pay for Google Workspace.">${esc(p.context || '')}</textarea>
      <div class="muted" style="margin-top:6px">${p.n_sources} sources · ${$('#nFindings').textContent || 0} findings · ${$('#nChats').textContent || 0} chats will be used.</div>
      <div class="row" style="margin-top:10px"><button class="primary" id="buildBtn" onclick="buildPlan()">Build Master Plan</button><span class="muted" id="buildMsg"></span></div>
    </div>`;
}
globalThis.buildPlan = async function buildPlan(instructions) {
  const btn = $('#buildBtn'); if (btn) btn.disabled = true;
  const ctx = $('#planCtx'); if (ctx) { await put('/api/projects/' + state.project.id, { name: state.project.name, context: ctx.value }); state.project.context = ctx.value; $('#epContext').value = ctx.value; }
  const msg = $('#buildMsg');
  const t0 = Date.now(), tick = m => { if (msg) msg.innerHTML = `<span class="spin"></span> ${esc(m || 'reading the research…')} · ${Math.round((Date.now() - t0) / 1000)}s <span class="muted">(analysis first, then the plan — usually 1–3 min)</span>`; };
  tick();
  try {
    const r = await post(`/api/projects/${state.project.id}/plan/build`, { instructions: instructions || null, background: true });
    for (;;) {
      await new Promise(res => setTimeout(res, 2500));
      const j = await api(`/api/jobs/${r.job_id}`).catch(() => null);
      if (!j) { tick('reconnecting…'); continue; }
      if (j.status === 'done') break;
      if (j.status === 'failed') throw new Error(j.message || 'plan build failed');
      tick(j.message);
    }
    await loadPlan();
  } catch (e) { if (msg) msg.textContent = 'error: ' + e.message; if (btn) btn.disabled = false; else toast(e.message, 'err'); }
}
globalThis.ev = function ev(ids, emap) {
  if (!ids?.length) return '';
  const parts = ids.map(i => emap[i]).filter(Boolean).map(e => e.removed ? `<span title="Evidence source removed">⚠ ${esc(e.label)} (source removed)</span>` : e.link ? `<a href="${esc(e.link)}" target="_blank">${esc(e.label)}</a>` : esc(e.label));
  return parts.length ? `<div class="ev muted">based on: ${parts.join(' · ')}</div>` : '';
}
globalThis.statusSel = function statusSel(key) {
  const cur = planState.plan.items[key]?.status || 'not_started';
  return `<select onchange="setItem('${key}', this.value)">${STATUSES.map(s => `<option value="${s}" ${s === cur ? 'selected' : ''}>${stLabel(s)}</option>`).join('')}</select>`;
}
globalThis.setItem = async function setItem(key, status) { await put(`/api/plans/${planState.plan.id}/items/${encodeURIComponent(key)}`, { status }); planState.plan.items[key] = { status }; }
globalThis.basis = function basis(x) { return x.basis ? `<span class="basis">basis: ${esc(x.basis)}${x.confidence ? ' · confidence: ' + esc(x.confidence.replace('_', ' ')) : ''}</span>` : ''; }
globalThis.renderPlan = function renderPlan(r) {
  const pl = r.plan, p = pl.plan, E = p._evidence || {}, started = pl.status === 'started';
  const pending = pl.updates.filter(u => u.status === 'pending'), accepted = pl.updates.filter(u => u.status === 'accepted');
  const an = p.analysis || {}, facts = (state.project.facts || []);
  let h = `<div class="row mb-3"><h2 style="margin:0;flex:1">Master Plan <span class="muted" style="font-weight:400;font-size:13px">v${pl.version} · ${esc(p._generated || '')} · ${started ? '🚀 started' : 'planning'}</span></h2>
    <button class="small" onclick="checkUpdates()">Check for updates</button>
    <a class="chip fixed" href="/api/projects/${state.project.id}/plan.md" target="_blank">⬇ .md</a>
    <a class="chip fixed" href="/api/projects/${state.project.id}/plan.html" target="_blank">⬇ Share page</a></div>`;
  if (pending.length || accepted.length) {
    h += `<div class="banner"><b>Master Plan has ${pending.length} suggested update${pending.length === 1 ? '' : 's'}</b>` +
      pending.map(u => `<div class="upd"><div class="muted">${esc(u.section)}</div>${u.previous ? `<div class="prev">${esc(u.previous)}</div>` : ''}<div><b>${esc(u.proposed)}</b></div><div class="muted">Why: ${esc(u.reason || '')}</div>
        <div class="row" style="margin-top:6px"><button class="small primary" onclick="updStatus(${u.id},'accepted')">Accept change</button><button class="small" onclick="updStatus(${u.id},'rejected')">Keep current plan</button><button class="small ghost" onclick="researchThis(${JSON.stringify(u.section + ': ' + u.proposed + ' — is this right? What does the research say?').replace(/"/g, '&quot;')})">Research further</button></div></div>`).join('') +
      (accepted.length ? `<div class="row mt-2"><span class="muted">${accepted.length} accepted, not yet applied.</span><button class="small primary" onclick="applyUpdates()">Apply accepted changes (rebuilds plan)</button></div>` : '') + `</div>`;
  }

  // ---------- START HERE: the short version ----------
  const rd = p.ready || {};
  const weekItem = (t, i) => { const done = planState.plan.items['this_week.' + i]?.status === 'complete';
    return `<label class="wk ${done ? 'done' : ''}"><input type="checkbox" ${done ? 'checked' : ''} onchange="setItem('this_week.${i}', this.checked ? 'complete' : 'not_started'); this.closest('.wk').classList.toggle('done', this.checked)"><div><b>${esc(t.action)}</b>${t.time ? ` <span class="tag">${esc(t.time)}</span>` : ''}<div class="muted">${esc(t.why || '')}</div></div></label>`; };
  h += `<div class="start">
    <div class="startcol">
      <div class="starth">🎯 Start here</div>
      ${an.verdict ? `<p class="verdict">${esc(an.verdict)}</p>` : ''}
      ${(p.approach || {}).recommended ? `<p><b>Approach:</b> ${esc(p.approach.recommended)}</p>` : ''}
      <p><b>Initial cost:</b> ${esc(rd.initial_cost || '?')}${rd.blockers?.length ? ` · <b class="status-bad">Blocked by:</b> ${rd.blockers.map(esc).join('; ')}` : ''}${rd.need_before?.length ? ` · <b>Need first:</b> ${rd.need_before.map(esc).join('; ')}` : ''}</p>
      ${started ? '<span class="tag">🚀 project started</span>' : `<button class="primary" onclick="startProject()">Start project</button> <span class="muted">marks the first steps ready and switches to execution</span>`}
    </div>
    <div class="startcol">
      <div class="starth">📅 This week</div>
      ${(p.this_week || []).length ? p.this_week.map(weekItem).join('') : `<ol>${(rd.first_three || []).map(x => `<li>${esc(x)}</li>`).join('')}</ol>`}
    </div>
  </div>`;

  // ---------- REFINE: guided questions ----------
  const qs = p.refine_questions || [];
  if (qs.length) {
    const answered = q => facts.find(f => f.content.startsWith('Q: ' + q.question));
    const n = qs.filter(answered).length;
    h += `<div class="refine"><div class="row"><div class="starth grow">💬 Make this plan yours <span class="muted" style="font-weight:400">— ${n} of ${qs.length} answered</span></div>
      ${n ? `<button class="small primary" onclick="rebuildWithAnswers()">↻ Rebuild plan with my answers</button>` : ''}</div>
      <div class="muted" style="margin-bottom:6px">These are the things only you know. Each answer you save becomes a project fact; rebuild when you've answered a few and the plan will be tighter and more specific.</div>` +
      qs.map((q, i) => { const a = answered(q); return `<div class="rq ${a ? 'answered' : ''}" id="rq-${i}">
        <div><b>${esc(q.question)}</b> <span class="muted">— ${esc(q.why || '')}</span></div>
        ${a ? `<div class="ans">✓ ${esc(a.content.split('\nA: ')[1] || a.content)} <button class="small ghost" onclick="delFactByContent(${JSON.stringify(a.content).replace(/"/g, '&quot;')})">change</button></div>`
            : `<div class="row" style="margin-top:4px;flex-wrap:wrap">${(q.options || []).map(o => `<button class="small" onclick="answerQ(${i}, ${JSON.stringify(o).replace(/"/g, '&quot;')})">${esc(o)}</button>`).join('')}
               <input placeholder="${q.options?.length ? 'or type your own…' : 'your answer…'}" style="flex:1;min-width:180px" onkeydown="if(event.key==='Enter'){answerQ(${i}, this.value)}">
               <button class="small ghost" onclick="researchThis(${JSON.stringify(q.question + ' — help me think this through for my project. What do the sources say, and what should I consider?').replace(/"/g, '&quot;')})">Discuss</button></div>`}
      </div>`; }).join('') + `</div>`;
  }

  // ---------- TABS ----------
  const tab = planState.tab || 'overview';
  const tabs = [['overview', 'Where you stand'], ['do', 'Do this'], ['decide', 'Decide'], ['money', 'Money & tools'], ['watch', 'Watch out'], ['evidence', 'Evidence']];
  h += `<div class="ptabs">${tabs.map(([k, l]) => `<button class="${tab === k ? 'on' : ''}" onclick="planState.tab='${k}';renderPlan(planState)">${l}</button>`).join('')}</div><div class="plan">`;

  if (tab === 'overview') {
    const cell = x => `<b>${esc(x.point || '')}</b>${x.so_what ? `<div class="muted">${esc(x.so_what)}</div>` : ''}${ev(x.evidence, E)}`;
    const col = (title, arr, cls) => `<div class="swot ${cls}"><div class="swh">${title}</div>${(arr || []).map(x => `<div class="swi">${cell(x)}</div>`).join('') || '<div class="muted">—</div>'}</div>`;
    const g = p.goal || {}, a = p.approach || {};
    h += `<h2>Goal</h2><p>${esc(g.outcome || '')}</p>${g.constraints?.length ? `<p><b>Constraints:</b> ${g.constraints.map(esc).join('; ')}</p>` : ''}${g.success?.length ? `<p><b>Success looks like:</b> ${g.success.map(esc).join('; ')}</p>` : ''}${ev(g.evidence, E)}`;
    if (an.situation) h += `<h2>Where you stand</h2><p>${esc(an.situation)}</p>`;
    if (an.swot) h += `<div class="swotgrid">${col('Strengths', an.swot.strengths, 's')}${col('Weaknesses', an.swot.weaknesses, 'w')}${col('Opportunities', an.swot.opportunities, 'o')}${col('Threats', an.swot.threats, 't')}</div>`;
    if (an.readiness?.length) h += `<p><b>Readiness</b></p><div class="row" style="flex-wrap:wrap;gap:6px">${an.readiness.map(r => `<span class="chip" title="${esc(r.note || '')}"><span class="conf ${r.level === 'ready' ? 'high' : r.level === 'partly' ? 'medium' : 'needs_research'}">●</span> ${esc(r.area)} <span class="muted">· ${esc(r.level)}${r.note ? ' — ' + esc(r.note) : ''}</span></span>`).join('')}</div>`;
    if (an.options?.length) h += `<h2>Paths compared</h2><table><tr><th>Path</th><th>Cost</th><th>Time to result</th><th>Risk</th><th>Fit</th><th>Why</th></tr>${an.options.map(o => `<tr><td><b>${esc(o.path)}</b><div class="muted">${esc(o.summary || '')}</div></td><td>${esc(o.cost || '')}</td><td>${esc(o.time_to_result || '')}</td><td><span class="tag ${esc(o.risk || '')}">${esc(o.risk || '')}</span></td><td class="status-warn">${'●'.repeat(+o.fit || 0)}</td><td>${esc(o.why_fit || '')}${ev(o.evidence, E)}</td></tr>`).join('')}</table>`;
    h += `<h2>Recommended approach</h2><p class="k">${esc(a.recommended || '')}</p><p>${esc(a.why || '')}</p>` +
      (a.alternatives?.length ? `<p class="muted">Alternatives considered:</p><ul>${a.alternatives.map(x => `<li><b>${esc(x.option)}</b> — ${esc(x.why_not)}</li>`).join('')}</ul>` : '') + basis(a) + ev(a.evidence, E);
    if (p.confidence?.length) h += `<h2>Plan confidence</h2><ul>${p.confidence.map(x => `<li><b>${esc(x.area)}</b>: <span class="conf ${x.level}">${esc((x.level || '').replace('_', ' '))}</span> — ${esc(x.note || '')}</li>`).join('')}</ul>`;
  }
  if (tab === 'do') {
    h += `<h2>First steps</h2>` + (p.first_steps || []).map((s, i) => `<div class="item"><div style="flex:0 0 22px;color:var(--muted)">${i + 1}.</div><div class="body"><span class="k">${esc(s.action)}</span>${s.today ? '<span class="tag">today</span>' : ''}<div class="muted">${esc(s.detail || '')}</div>${ev(s.evidence, E)}</div>${statusSel('first_steps.' + i)}</div>`).join('');
    if (p.phases?.length) { h += `<h2>Phases</h2>`; p.phases.forEach((ph, i) => { h += `<details ${i === 0 ? 'open' : ''}><summary><b>Phase ${i + 1} — ${esc(ph.name)}</b> <span class="muted">${esc(ph.objective || '')}</span></summary>` +
        (ph.tasks || []).map((t, j) => `<div class="item"><div class="body">${esc(t.task)}${t.detail ? `<div class="muted">${esc(t.detail)}</div>` : ''}</div>${statusSel(`phases.${i}.tasks.${j}`)}</div>`).join('') +
        (ph.dependencies?.length ? `<div class="muted" style="margin-top:6px">Depends on: ${ph.dependencies.map(esc).join('; ')}</div>` : '') + (ph.decisions?.length ? `<div class="muted">Decisions needed: ${ph.decisions.map(esc).join('; ')}</div>` : '') + (ph.outcome ? `<div class="muted">Outcome: ${esc(ph.outcome)}</div>` : '') + `</details>`; }); }
    if (p.dependencies?.length) h += `<h2>Dependencies</h2>` + p.dependencies.map((d, i) => `<div class="item"><div class="body">${d.blocking ? '<span class="tag blocking">blocking</span> ' : '<span class="tag">non-blocking</span> '}${esc(d.item)}${d.note ? `<div class="muted">${esc(d.note)}</div>` : ''}</div>${statusSel('dependencies.' + i)}</div>`).join('');
    if (p.defer?.length) h += `<h2>Not yet</h2><ul>${p.defer.map(d => `<li>${esc(d.item)} <span class="muted">— ${esc(d.until || '')}</span></li>`).join('')}</ul>`;
  }
  if (tab === 'decide') {
    if (p.decisions?.length) h += `<h2>Decisions to make</h2>` + p.decisions.map((d, i) => `<div class="item"><div class="body"><span class="tag ${d.when}">${d.when === 'now' ? 'decide now' : 'decide later'}</span> <span class="k">${esc(d.decision)}</span><div class="muted">Options: ${(d.options || []).map(esc).join(' · ')}</div><div><b>Recommended:</b> ${esc(d.recommended || '')} — ${esc(d.why || '')}</div>${d.by_phase ? `<div class="muted">Needed by: ${esc(d.by_phase)}</div>` : ''}${basis(d)}${ev(d.evidence, E)}<div class="mt-1"><button class="small ghost" onclick="researchThis(${JSON.stringify('Help me decide: ' + d.decision + '. Options: ' + (d.options || []).join(', ') + '. What do the sources say and what fits my situation?').replace(/"/g, '&quot;')})">Discuss</button></div></div>${statusSel('decisions.' + i)}</div>`).join('');
    if (p.open_questions?.length) h += `<h2>Open questions</h2>` + p.open_questions.map((q, i) => `<div class="item"><div class="body"><span class="tag ${q.category}">${({ blocking: 'blocking', soon: 'important soon', nice: 'nice to know' })[q.category] || esc(q.category || '')}</span> <span class="k">${esc(q.question)}</span><div class="muted">${esc(q.why || '')}</div><div class="mt-1"><button class="small" onclick="researchThis(${JSON.stringify(q.research_prompt || q.question).replace(/"/g, '&quot;')})">Research this</button></div></div>${statusSel('open_questions.' + i)}</div>`).join('');
    if (an.assumptions?.length) h += `<h2>Assumptions this plan rests on</h2>` + an.assumptions.map(x => `<div class="item"><div class="body"><span class="k">${esc(x.assumption)}</span><div class="muted">If wrong: ${esc(x.if_wrong || '')} · How to check: ${esc(x.how_to_check || '')}</div></div></div>`).join('');
    if (!p.decisions?.length && !p.open_questions?.length) h += '<p class="muted">Nothing to decide right now.</p>';
  }
  if (tab === 'money') {
    if (p.tools?.length) h += `<h2>Tools & services</h2><table><tr><th>Need</th><th>Tool</th><th>Free</th><th>Premium</th><th>Cost</th><th>Tier</th><th>Why</th></tr>` + p.tools.map(t => `<tr><td>${esc(t.need)}</td><td>${esc(t.tool)}</td><td>${esc(t.free_option || '—')}</td><td>${esc(t.premium_option || '—')}</td><td>${esc(t.cost || '—')}</td><td>${esc(t.tier || '')}</td><td>${esc(t.why || '')}${ev(t.evidence, E)}</td></tr>`).join('') + `</table>`;
    const c = p.costs; if (c) { h += `<h2>Costs</h2><p>Minimum viable budget: <b>${esc(c.minimum || '?')}</b> · Recommended: <b>${esc(c.recommended || '?')}</b> · Premium: <b>${esc(c.premium || '?')}</b></p>`; for (const [k, l] of [['upfront', 'Upfront'], ['recurring', 'Recurring'], ['optional', 'Optional upgrades'], ['services', 'Professional services']]) if (c[k]?.length) h += `<p><b>${l}:</b> ${c[k].map(x => `${esc(x.item)} (${esc(x.amount)})`).join('; ')}</p>`;
      if (c.contingency) h += `<p><b>Contingency:</b> ${esc(c.contingency)}</p>`; h += `${c.note ? `<p class="muted">${esc(c.note)}</p>` : ''}${ev(c.evidence, E)}`; }
    if (!p.tools?.length && !p.costs) h += '<p class="muted">No cost or tooling detail in this plan.</p>';
  }
  if (tab === 'watch') {
    if (p.risks?.length) h += `<h2>Risks</h2>` + [...p.risks].sort((x, y) => ({ high: 0, medium: 1, low: 2 }[x.priority] ?? 1) - ({ high: 0, medium: 1, low: 2 }[y.priority] ?? 1)).map(r => `<div class="item"><div class="body"><span class="k">${esc(r.risk)}</span><span class="tag ${r.priority}">${esc(r.priority || 'medium')}</span><div class="muted">Mitigation: ${esc(r.mitigation || '')}</div></div></div>`).join('');
    if (an.failure_patterns?.length) h += `<h2>Why people fail at this <span class="muted" style="font-weight:400;font-size:13px">— per the sources</span></h2>` + an.failure_patterns.map(x => `<div class="item"><div class="body"><span class="k">${esc(x.pattern)}</span>${x.seen_in ? ` <span class="muted">(${esc(x.seen_in)})</span>` : ''}<div class="muted">Avoid: ${esc(x.avoid || '')}</div>${ev(x.evidence, E)}</div></div>`).join('');
    if (p.gotchas?.length) h += `<h2>Beginner gotchas</h2>` + p.gotchas.map(g => `<div class="item"><div class="body"><span class="k">${esc(g.gotcha)}</span><div class="muted">${esc(g.avoid || '')}</div></div></div>`).join('');
  }
  if (tab === 'evidence') {
    // 2026-09-14 - a mature project's evidence map can run into the thousands (Kyle's laundromat plan: 1,804
    // entries). Rendered flat, that was an unbroken wall of same-weight chips with no search, no grouping, no way
    // to find one thing - and 16 of them read as literally identical text ("F22 · pinned finding research",
    // "F23 · pinned finding research", ...) because uncited findings all fell back to the same placeholder label
    // (fixed at the source in planner.py's _evidence()). Grouped by id prefix (U/F/S/C - facts, pinned findings,
    // sources, research chunks) behind collapsible sections, plus a text filter, so the same data is navigable at
    // any scale instead of a scroll-forever wall.
    const evs = Object.entries(E);
    if (!evs.length) { h += '<p class="muted">No evidence map.</p>'; }
    else {
      const GROUP_LABEL = { U: 'Facts you told us', F: 'Pinned findings', S: 'Sources', C: 'Research chunks' };
      const groups = {};
      for (const [id, e] of evs) { const prefix = id.replace(/\d+$/, ''); (groups[prefix] = groups[prefix] || []).push([id, e]); }
      const order = [...new Set(['U', 'F', 'S', 'C', ...Object.keys(groups)])];
      h += `<h2>Evidence used by this plan <span class="muted" style="font-weight:400;font-size:13px">— ${evs.length} total</span></h2>
        <input id="evFilter" placeholder="Filter evidence by title…" oninput="filterEvidence(this.value)" style="width:100%;margin-bottom:10px">`;
      for (const prefix of order) {
        const items = groups[prefix]; if (!items?.length) continue;
        h += `<details class="evgroup" ${items.length <= 30 ? 'open' : ''}><summary><b>${esc(GROUP_LABEL[prefix] || prefix)}</b> <span class="muted">(${items.length})</span></summary>
          <div class="muted evchips">${items.map(([id, e]) => `<span class="chip" data-evtext="${esc((id + ' ' + e.label).toLowerCase())}">${id} · ${e.link ? `<a href="${esc(e.link)}" target="_blank">${esc(e.label)}</a>` : esc(e.label)}</span>`).join(' ')}</div>
        </details>`;
      }
    }
  }
  h += `</div>`;
  $('#planWrap').innerHTML = h;
}
globalThis.filterEvidence = function filterEvidence(q) {
  q = q.trim().toLowerCase();
  document.querySelectorAll('.evgroup').forEach(group => {
    let anyVisible = false;
    group.querySelectorAll('.chip').forEach(chip => {
      const match = !q || (chip.dataset.evtext || '').includes(q);
      chip.style.display = match ? '' : 'none';
      if (match) anyVisible = true;
    });
    group.style.display = anyVisible ? '' : 'none';
    if (q && anyVisible) group.open = true;
  });
}
globalThis.answerQ = async function answerQ(i, text) {
  text = (text || '').trim(); if (!text) return;
  const q = planState.plan.plan.refine_questions[i];
  const kind = q.kind === 'decision' ? 'decision' : q.kind === 'preference' ? 'requirement' : 'context';
  await post(`/api/projects/${state.project.id}/facts`, { kind, content: `Q: ${q.question}\nA: ${text}` });
  state.project = await api('/api/projects/' + state.project.id); renderPlan(planState);
}
globalThis.delFactByContent = async function delFactByContent(content) {
  const f = (state.project.facts || []).find(x => x.content === content); if (!f) return;
  await del('/api/facts/' + f.id); state.project = await api('/api/projects/' + state.project.id); renderPlan(planState);
}
globalThis.rebuildWithAnswers = async function rebuildWithAnswers() {
  const qs = planState.plan.plan.refine_questions || [], facts = state.project.facts || [];
  const answers = qs.map(q => facts.find(f => f.content.startsWith('Q: ' + q.question))).filter(Boolean).map(f => f.content.replace('\n', ' → '));
  $('#planWrap').insertAdjacentHTML('afterbegin', '<div class="muted" id="buildMsg"><span class="spin"></span> rebuilding with your answers…</div>');
  await buildPlan('The user answered these questions — fold them in, drop the questions that are now answered, and ask the next most useful ones:\n' + answers.join('\n'));
}

globalThis.checkUpdates = async function checkUpdates() {
  $('#planWrap').insertAdjacentHTML('afterbegin', '<div class="muted" id="chk"><span class="spin"></span> comparing new research against the plan…</div>');
  try { const r = await post(`/api/projects/${state.project.id}/plan/check-updates`); await loadPlan(); if (!r.updates.length) $('#planWrap').insertAdjacentHTML('afterbegin', '<div class="muted mb-2">No material changes — the plan still holds.</div>'); }
  catch (e) { alert(e.message); $('#chk')?.remove(); }
}
globalThis.updStatus = async function updStatus(id, status) { await post(`/api/plan-updates/${id}`, { status }); await loadPlan(); }
globalThis.applyUpdates = async function applyUpdates() { $('#planWrap').insertAdjacentHTML('afterbegin', '<div class="muted"><span class="spin"></span> rebuilding the plan with the accepted changes…</div>'); try { await post(`/api/projects/${state.project.id}/plan/apply`); } catch (e) { alert(e.message); } await loadPlan(); }
globalThis.startProject = async function startProject() { await post(`/api/plans/${planState.plan.id}/start`); await loadPlan(); }
globalThis.researchThis = async function researchThis(q) {
  const c = await post('/api/conversations', { project_id: state.project.id, title: q.slice(0, 60) });
  await loadChats(); await selectChat(c.id); $('#q').value = q; $('#q').focus();
}

route();


export const moduleName = "plan";
