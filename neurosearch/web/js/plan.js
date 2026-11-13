globalThis.loadPlan = async function loadPlan() {
  const projectId = state.project.id;
  loadStaleness();
  const r = await api(`/api/projects/${projectId}/plan`);
  if (state.project?.id !== projectId) return;
  if (globalThis.planState?.plan?.project_id === projectId) {
    r.tab = planState.tab;
    r.showChanges = $('#planChanges')?.open;
    r.showQuestions = $('#planQuestions')?.open;
  }
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
globalThis.statusSel = function statusSel(key, label = 'Item') {
  const cur = planState.plan.items[key]?.status || 'not_started';
  const statuses = STATUSES.includes(cur) ? STATUSES : [...STATUSES, cur];
  return `<select aria-label="Status for ${esc(label)}" data-plan-item="${key}" onchange="setItem('${key}', this)">${statuses.map(s => `<option value="${esc(s)}" ${s === cur ? 'selected' : ''}>${stLabel(s)}</option>`).join('')}</select>`;
}
globalThis.setItem = async function setItem(key, control) {
  const original = planState;
  const controls = [...$('#planWrap').querySelectorAll('[data-plan-item]')];
  for (const el of controls) el.disabled = true;
  try {
    await put(`/api/plans/${original.plan.id}/items/${encodeURIComponent(key)}`, { status: control.value });
    if (planState !== original || state.project?.id !== original.plan.project_id) return;
    const updated = await api(`/api/projects/${original.plan.project_id}/plan`);
    if (planState !== original || state.project?.id !== original.plan.project_id) return;
    updated.tab = original.tab;
    updated.showChanges = $('#planChanges')?.open;
    updated.showQuestions = $('#planQuestions')?.open;
    globalThis.planState = updated;
    renderPlan(updated);
    const updatedControls = [...$('#planWrap').querySelectorAll('[data-plan-item]')];
    (updatedControls.find(el => el.dataset.planItem === key) || updatedControls[0] || $('#planNextHeading'))?.focus();
  } catch (e) {
    control.value = original.plan.items[key]?.status || 'not_started';
    toast(e.message || 'Could not update the plan.', 'err');
  } finally { for (const el of controls) el.disabled = false; }
}
globalThis.basis = function basis(x) { return x.basis ? `<span class="basis">basis: ${esc(x.basis)}${x.confidence ? ' · confidence: ' + esc(x.confidence.replace('_', ' ')) : ''}</span>` : ''; }
globalThis.planUpdateEvidence = function planUpdateEvidence(update) {
  const evidence = update.claim_evidence;
  if (!evidence && update.verified_evidence?.length) return `<details class="mt-2"><summary>Evidence behind this update</summary>
    ${update.verified_evidence.map(p => `<div>${p.link && !p.stale ? claimEvidenceLink(p) : esc(p.title)}
      ${p.stale ? '<span class="tag status-warn">Source revised or unavailable</span>' : ''}
      <blockquote class="quote">${esc(p.excerpt)}</blockquote></div>`).join('')}</details>`;
  if (!evidence) return '<p class="muted">No verified passage is recorded.</p>';
  const passages = [...evidence.counter, ...evidence.supporting].filter(p => p.locator && p.excerpt);
  const relations = { SUPPORTS: 'Supports', CONTRADICTS: 'Contradicts', QUALIFIES: 'Qualifies',
    INTERPRETS: 'Interprets', EXPERIENTIAL: 'Firsthand experience' };
  return `<details class="mt-2"><summary>Evidence behind this update</summary>
    <p>${esc(evidence.text)}</p>
    ${passages.map(p => `<div>${esc(relations[p.relation] || p.relation)} · ${claimEvidenceLink(p)}
      ${p.stale ? '<span class="tag status-warn">Source revised</span>' : ''}
      <blockquote class="quote">${esc(p.excerpt)}</blockquote></div>`).join('') || '<p class="muted">No located passage is recorded.</p>'}
  </details>`;
}
function planAction(item, evidence) {
  const detail = item.detail || item.why;
  return `<div class="plan-action">
    <div class="body"><strong>${esc(item.label)}</strong>${item.time ? ` <span class="muted">· ${esc(item.time)}</span>` : ''}
      ${item.unmet?.length ? `<div class="status-warn">Waiting for ${item.unmet.map(esc).join(', ')}</div>` : ''}
      ${detail ? `<div class="muted">${esc(detail)}</div>` : ''}${ev(item.evidence, evidence)}
    </div>${statusSel(item.key, item.label)}
  </div>`;
}

function planDeadlines(deadlines) {
  const next = deadlines[0];
  return `<section class="plan-deadlines">
    ${next ? `<div class="plan-attention"><strong>Confirmed deadline</strong> · <time datetime="${esc(next.date)}">${esc(next.date)}</time>
      <div>${esc(next.label)}</div>${next.consequence ? `<div class="muted">${esc(next.consequence)}</div>` : ''}
      ${next.fallback ? `<div class="muted">Fallback · ${esc(next.fallback)}</div>` : ''}</div>` : ''}
    <details><summary>${next ? 'Manage deadlines' : 'Add a confirmed deadline'}</summary>
      ${deadlines.map(d => `<div class="row plan-attention"><span class="grow">${esc(d.date)} · ${esc(d.label)}</span>
        <button class="small ghost" onclick="removePlanDeadline(${d.id})">Remove</button></div>`).join('')}
      <form class="plan-form" onsubmit="event.preventDefault(); savePlanDeadline(this)">
        <label>What’s due <input name="label" required maxlength="250"></label>
        <label>Deadline <input name="date" type="date" required></label>
        <label>Consequence if missed <input name="consequence" maxlength="500"></label>
        <label>Fallback <input name="fallback" maxlength="500"></label>
        <button class="small primary" type="submit">Save deadline</button>
      </form></details>
  </section>`;
}
globalThis.savePlanDeadline = async function savePlanDeadline(form) {
  const projectId = state.project.id, data = Object.fromEntries(new FormData(form));
  if (!data.label.trim()) return;
  const button = form.querySelector('button');
  button.disabled = true;
  try {
    await post(`/api/projects/${projectId}/facts`, { kind: 'deadline', content: JSON.stringify(data) });
    if (state.project.id === projectId) await loadPlan();
  } catch (e) { toast(e.message, 'err'); }
  finally { button.disabled = false; }
}
globalThis.removePlanDeadline = async function removePlanDeadline(id) {
  if (!confirm('Remove this confirmed deadline?')) return;
  const projectId = state.project.id;
  try {
    await del('/api/facts/' + id);
    if (state.project.id === projectId) await loadPlan();
  } catch (e) { toast(e.message, 'err'); }
}
globalThis.recordPlanDecision = async function recordPlanDecision(index, form) {
  const projectId = state.project.id, planId = planState.plan.id, button = form.querySelector('button');
  const data = Object.fromEntries(new FormData(form));
  button.disabled = true;
  try {
    await post(`/api/plans/${planId}/decisions/${index}`, data);
    if (state.project.id === projectId) await loadPlan();
  } catch (e) { toast(e.message, 'err'); }
  finally { button.disabled = false; }
}

function planFocus(r, evidence) {
  const { plan: row, execution } = r;
  const p = row.plan, phase = execution.phase, ready = p.ready || {}, goal = p.goal || {};
  const approach = p.approach || {}, started = row.status === 'started';
  const open = key => !['complete', 'done'].includes(row.items[key]?.status);
  const decisions = (p.decisions || []).map((d, i) => ({ ...d, key: `decisions.${i}` }))
    .filter(d => open(d.key) && (d.when === 'now' || (d.id && phase?.decisions?.includes(d.id))
      || (d.by_phase && [phase?.id, phase?.name].includes(d.by_phase))));
  const blockers = (p.dependencies || []).map((d, i) => ({ ...d, key: `dependencies.${i}` }))
    .filter(d => d.blocking && open(d.key));
  const questions = (p.open_questions || []).map((q, i) => ({ ...q, key: `open_questions.${i}` }))
    .filter(q => q.category === 'blocking' && open(q.key));
  const alerts = [...new Set([...(ready.blockers || []), ...(ready.need_before || [])])]
    .filter(label => !(p.dependencies || []).some(d => d.item?.trim().toLowerCase() === label.trim().toLowerCase()));
  const actions = `<section aria-labelledby="planNextHeading"><h3 id="planNextHeading" tabindex="-1">Next actions</h3>
    ${execution.next_actions.length ? execution.next_actions.map(item => planAction(item, evidence)).join('') :
      '<p class="muted">No unfinished actions are listed for this milestone.</p>'}
    ${execution.completed ? `<p class="muted">${execution.completed} of ${Object.keys(execution.tasks).length} actions complete</p>` : ''}
    <button class="small ghost" onclick="selectPlanTab('do')">View all work</button></section>`;
  const attention = decisions.length || blockers.length || questions.length || alerts.length ? `<section><h3>Needs attention</h3>
    ${decisions.map(d => `<details class="plan-attention"><summary>${esc(d.decision)}</summary>
      ${d.recommended ? `<p><strong>Recommendation</strong> · ${esc(d.recommended)}${d.why ? ` — ${esc(d.why)}` : ''}</p>` : ''}
      ${d.by_phase ? `<p class="muted">Needed for ${esc(d.by_phase)}</p>` : ''}
      ${d.options?.length ? `<p class="muted">Options · ${d.options.map(esc).join(' · ')}</p>` : ''}
      ${ev(d.evidence, evidence)}<button class="small ghost" onclick="selectPlanTab('decide')">Review decision</button></details>`).join('')}
    ${blockers.map(d => `<div class="plan-attention"><strong>${esc(d.item)}</strong>${d.note ? `<div class="muted">${esc(d.note)}</div>` : ''}
      <button class="small ghost" onclick="selectPlanTab('do')">Review dependency</button></div>`).join('')}
    ${questions.map(q => `<div class="plan-attention"><strong>${esc(q.question)}</strong>${q.why ? `<div class="muted">${esc(q.why)}</div>` : ''}</div>`).join('')}
    ${alerts.map(label => `<div class="plan-attention">${esc(label)}</div>`).join('')}
    <button class="small ghost" onclick="selectPlanTab('decide')">View decisions and questions</button></section>` : '';
  return `<section class="plan-focus">
    ${goal.outcome ? `<p class="plan-goal">${esc(goal.outcome)}</p>` : ''}
    ${approach.recommended ? `<details class="plan-approach"><summary>${esc(approach.recommended)}</summary>
      ${approach.why ? `<p>${esc(approach.why)}</p>` : ''}${ev(approach.evidence, evidence)}</details>` : ''}
    <div class="plan-milestone">
      <div class="muted">${phase ? 'Next milestone' : 'Plan progress'}</div>
      <h3>${esc(phase?.outcome || phase?.objective || phase?.name ||
        (Object.keys(execution.tasks).length && !execution.next_actions.length ? 'Scheduled actions complete' : 'First actions'))}</h3>
      ${phase?.name && phase?.name !== (phase.outcome || phase.objective || phase.name) ? `<div class="muted">${esc(phase.name)}</div>` : ''}
      ${goal.success?.length ? `<details class="plan-approach"><summary>Success criteria</summary><ul>${goal.success.map(x => `<li>${esc(x)}</li>`).join('')}</ul></details>` : ''}
      ${!started ? '<button class="small primary mt-2" onclick="startProject()">Start project</button>' : ''}
    </div>
    ${planDeadlines(r.deadlines || [])}
    <div class="plan-focus-grid${attention ? ' has-attention' : ''}">${!started && attention ? attention + actions : actions + attention}</div>
    ${p._progress_review?.length ? `<details class="plan-attention"><summary>Review progress from the previous plan (${p._progress_review.length})</summary>
      <p class="muted">These entries need a match before their status can be carried forward. The previous version retains the original progress.</p>
      <ul>${p._progress_review.map(x => `<li>${esc(x.label)} · ${esc(stLabel(x.status))}</li>`).join('')}</ul></details>` : ''}
  </section>`;
}

globalThis.selectPlanTab = function selectPlanTab(tab) {
  planState.tab = tab;
  renderPlan(planState);
  $('#planTabs').scrollIntoView?.({ block: 'nearest' });
  $('#planTabs').querySelector('.on')?.focus({ preventScroll: true });
}

globalThis.renderPlan = function renderPlan(r) {
  const pl = r.plan, p = pl.plan, E = p._evidence || {}, started = pl.status === 'started';
  const pending = pl.updates.filter(u => u.status === 'pending'), accepted = pl.updates.filter(u => u.status === 'accepted' && !u.applied_plan_id);
  const rejected = pl.updates.filter(u => u.status === 'rejected');
  const an = p.analysis || {}, facts = (state.project.facts || []);
  const execution = r.execution;
  let h = `<div class="row mb-3 plan-header"><h2 style="margin:0;flex:1">Master Plan <span class="muted" style="font-weight:400;font-size:13px">v${pl.version} · ${esc(p._generated || '')} · ${started ? '🚀 started' : 'planning'}</span></h2>
    <button class="small" onclick="checkUpdates(this)">Check for updates</button>
    <a class="chip fixed" href="/api/projects/${state.project.id}/plan.md" target="_blank">⬇ .md</a>
    <a class="chip fixed" href="/api/projects/${state.project.id}/plan.html" target="_blank">⬇ Share page</a></div>`;
  h += planFocus(r, E);
  if (pending.length || accepted.length) {
    h += `<details class="plan-changes" id="planChanges" ${r.showChanges ? 'open' : ''}><summary>Plan changes · ${pending.length} to review${accepted.length ? ` · ${accepted.length} ready to apply` : ''}</summary>` +
      pending.map(u => `<div class="upd"><div class="muted">${esc(u.section)}</div>${u.previous ? `<div class="prev">${esc(u.previous)}</div>` : ''}<div><b>${esc(u.proposed)}</b></div><div class="muted">Why: ${esc(u.reason || '')}</div>${planUpdateEvidence(u)}
        <div class="row" style="margin-top:6px"><button class="small primary" onclick="updStatus(${u.id},'accepted')">Accept change</button><button class="small" onclick="updStatus(${u.id},'rejected')">Keep current plan</button><button class="small ghost" onclick="researchThis(${JSON.stringify(u.section + ': ' + u.proposed + ' — is this right? What does the research say?').replace(/"/g, '&quot;')})">Research further</button></div></div>`).join('') +
      (accepted.length ? `<div class="row mt-2"><span class="muted">${accepted.length} accepted, not yet applied.</span>${r.can_apply_exact ? '<button class="small primary" onclick="applyUpdates(this, true)">Apply exact edits</button>' : ''}<button class="small" onclick="applyUpdates(this)">Rebuild with accepted changes</button></div>` : '') + `</details>`;
  }

  if (r.versions?.length > 1) {
    h += `<details class="plan-changes"><summary>Version history · ${r.versions.length} versions</summary>
      <ul>${r.versions.map(v => `<li>Version ${v.version} · ${esc(new Date(v.created_at * 1000).toLocaleDateString())}${v.label === 'current' ? ' · Current' : ''}</li>`).join('')}</ul>
      ${(r.applied_updates || []).map(u => `<p><b>Applied in v${u.version}</b> · ${esc(u.proposed)}</p>`).join('')}</details>`;
  }

  if (rejected.length) {
    h += `<details class="mb-3"><summary>Kept current plan (${rejected.length})</summary>
      ${rejected.map(u => `<p><b>${esc(u.section)}</b> · ${esc(u.proposed)}
        ${u.decision_reason ? `<br>Decision reason · ${esc(u.decision_reason)}` : ''}</p>`).join('')}</details>`;
  }
  // ---------- REFINE: guided questions ----------
  const qs = p.refine_questions || [];
  if (qs.length) {
    const answered = q => facts.find(f => f.content.startsWith('Q: ' + q.question));
    const n = qs.filter(answered).length;
    h += `<details class="refine" id="planQuestions" ${r.showQuestions ? 'open' : ''}><summary>Questions for you · ${n} of ${qs.length} answered</summary><div class="row">
      ${n ? `<button class="small primary" onclick="rebuildWithAnswers()">↻ Rebuild plan with my answers</button>` : ''}</div>
      <div class="muted" style="margin-bottom:6px">These are the things only you know. Each answer you save becomes a project fact; rebuild when you've answered a few and the plan will be tighter and more specific.</div>` +
      qs.map((q, i) => { const a = answered(q); return `<div class="rq ${a ? 'answered' : ''}" id="rq-${i}">
        <div><b>${esc(q.question)}</b> <span class="muted">— ${esc(q.why || '')}</span></div>
        ${a ? `<div class="ans">✓ ${esc(a.content.split('\nA: ')[1] || a.content)} <button class="small ghost" onclick="delFactByContent(${JSON.stringify(a.content).replace(/"/g, '&quot;')})">change</button></div>`
            : `<div class="row" style="margin-top:4px;flex-wrap:wrap">${(q.options || []).map(o => `<button class="small" onclick="answerQ(${i}, ${JSON.stringify(o).replace(/"/g, '&quot;')})">${esc(o)}</button>`).join('')}
               <input placeholder="${q.options?.length ? 'or type your own…' : 'your answer…'}" style="flex:1;min-width:180px" onkeydown="if(event.key==='Enter'){answerQ(${i}, this.value)}">
               <button class="small ghost" onclick="researchThis(${JSON.stringify(q.question + ' — help me think this through for my project. What do the sources say, and what should I consider?').replace(/"/g, '&quot;')})">Discuss</button></div>`}
      </div>`; }).join('') + `</details>`;
  }

  // ---------- TABS ----------
  const tab = planState.tab || 'do';
  const tabs = [['overview', 'Where you stand'], ['do', 'Do this'], ['decide', 'Decide'], ['money', 'Money & tools'], ['watch', 'Watch out'], ['evidence', 'Evidence']];
  h += `<div class="ptabs" id="planTabs" aria-label="Plan sections">${tabs.map(([k, l]) => `<button class="${tab === k ? 'on' : ''}" aria-pressed="${tab === k}" onclick="selectPlanTab('${k}')">${l}</button>`).join('')}</div><div class="plan">`;

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
    const tasks = Object.entries(execution.tasks);
    const taskById = Object.fromEntries(tasks.filter(([, task]) => task.id).map(([, task]) => [task.id, task.label]));
    const decisionById = Object.fromEntries((p.decisions || []).filter(d => d.id).map(d => [d.id, d.decision]));
    const standalone = tasks.filter(([, item]) => item.phase == null);
    if (standalone.length) h += '<h2>Standalone actions</h2>' + standalone.map(([key, item]) => planAction({ key, ...item }, E)).join('');
    if (p.phases?.length) {
      h += '<h2>Phases</h2>';
      p.phases.forEach((phase, i) => {
        h += `<details ${i === execution.phase_index ? 'open' : ''}><summary><b>${esc(phase.name)}</b>
          <span class="muted">${esc(phase.objective || '')}</span></summary>
          ${tasks.filter(([, item]) => item.phase === i).map(([key, item]) => planAction({ key, ...item }, E)).join('')}
          ${phase.dependencies?.length ? `<p class="muted">Depends on ${phase.dependencies.map(dep => esc(taskById[dep] || dep)).join(', ')}</p>` : ''}
          ${phase.decisions?.length ? `<p class="muted">Decisions needed · ${phase.decisions.map(d => esc(decisionById[d] || d)).join(', ')}</p>` : ''}
          ${phase.outcome ? `<p class="muted">Outcome · ${esc(phase.outcome)}</p>` : ''}
        </details>`;
      });
    }
    if (p.dependencies?.length) h += `<h2>Dependencies</h2>` + p.dependencies.map((d, i) => `<div class="item"><div class="body">${d.blocking ? '<span class="tag blocking">blocking</span> ' : '<span class="tag">non-blocking</span> '}${esc(d.item)}${d.note ? `<div class="muted">${esc(d.note)}</div>` : ''}</div>${statusSel('dependencies.' + i)}</div>`).join('');
    if (p.defer?.length) h += `<h2>Not yet</h2><ul>${p.defer.map(d => `<li>${esc(d.item)} <span class="muted">— ${esc(d.until || '')}</span></li>`).join('')}</ul>`;
  }
  if (tab === 'decide') {
    if (p.decisions?.length) h += `<h2>Decisions to make</h2>` + p.decisions.map((d, i) => `<div class="item"><div class="body"><span class="tag ${d.when}">${d.when === 'now' ? 'decide now' : 'decide later'}</span> <span class="k">${esc(d.decision)}</span><div class="muted">Options: ${(d.options || []).map(esc).join(' · ')}</div><div><b>Recommended:</b> ${esc(d.recommended || '')} — ${esc(d.why || '')}</div>${d.by_phase ? `<div class="muted">Needed by: ${esc(d.by_phase)}</div>` : ''}${basis(d)}${ev(d.evidence, E)}<div class="mt-1"><button class="small ghost" onclick="researchThis(${JSON.stringify('Help me decide: ' + d.decision + '. Options: ' + (d.options || []).join(', ') + '. What do the sources say and what fits my situation?').replace(/"/g, '&quot;')})">Discuss</button></div></div>${statusSel('decisions.' + i, d.decision)}
      ${['complete', 'done'].includes(pl.items['decisions.' + i]?.status) ? `<div class="muted">${esc(pl.items['decisions.' + i]?.note || '')}</div>` :
        `<details><summary>Record decision</summary><form class="plan-form" onsubmit="event.preventDefault(); recordPlanDecision(${i}, this)">
          <label>Your choice <input name="choice" maxlength="500" required></label>
          <label>Why <input name="reason" maxlength="1000"></label><button class="small primary" type="submit">Save decision</button>
        </form></details>`}</div>`).join('');
    if (p.open_questions?.length) h += `<h2>Open questions</h2>` + p.open_questions.map((q, i) => `<div class="item"><div class="body"><span class="tag ${q.category}">${({ blocking: 'blocking', soon: 'important soon', nice: 'nice to know' })[q.category] || esc(q.category || '')}</span> <span class="k">${esc(q.question)}</span><div class="muted">${esc(q.why || '')}</div><div class="mt-1"><button class="small" onclick="researchThis(${JSON.stringify(q.research_prompt || q.question).replace(/"/g, '&quot;')})">Research this</button></div></div>${statusSel('open_questions.' + i, q.question)}</div>`).join('');
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
    const cited = new Set();
    const collect = item => {
      if (!item || typeof item !== 'object') return;
      for (const [key, value] of Object.entries(item)) {
        if (key === 'evidence' && Array.isArray(value)) value.forEach(id => cited.add(id));
        else if (!key.startsWith('_')) collect(value);
      }
    };
    collect(p);
    const evs = Object.entries(E);
    if (!evs.length) { h += '<p class="muted">No evidence map.</p>'; }
    else {
      const GROUP_LABEL = { U: 'Other project facts', F: 'Other findings', S: 'Other sources', C: 'Other research passages' };
      const groups = {};
      for (const [id, e] of evs) { if (cited.has(id)) continue; const prefix = id.replace(/\d+$/, ''); (groups[prefix] = groups[prefix] || []).push([id, e]); }
      const order = [...new Set(['U', 'F', 'S', 'C', ...Object.keys(groups)])];
      h += `<h2>Evidence <span class="muted" style="font-weight:400;font-size:13px">— ${evs.filter(([id]) => cited.has(id)).length} cited · ${evs.length} available</span></h2>
        <input id="evFilter" placeholder="Filter evidence by title…" oninput="filterEvidence(this.value)" style="width:100%;margin-bottom:10px">`;
      groups.cited = evs.filter(([id]) => cited.has(id));
      for (const prefix of ['cited', ...order]) {
        const items = groups[prefix]; if (!items?.length) continue;
        h += `<details class="evgroup" ${prefix === 'cited' ? 'open' : ''}><summary><b>${esc(prefix === 'cited' ? 'Cited in this plan' : GROUP_LABEL[prefix] || prefix)}</b> <span class="muted">(${items.length})</span></summary>
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
  state.project = await api('/api/projects/' + state.project.id); planState.showQuestions = true; renderPlan(planState);
}
globalThis.delFactByContent = async function delFactByContent(content) {
  const f = (state.project.facts || []).find(x => x.content === content); if (!f) return;
  await del('/api/facts/' + f.id); state.project = await api('/api/projects/' + state.project.id); planState.showQuestions = true; renderPlan(planState);
}
globalThis.rebuildWithAnswers = async function rebuildWithAnswers() {
  const qs = planState.plan.plan.refine_questions || [], facts = state.project.facts || [];
  const answers = qs.map(q => facts.find(f => f.content.startsWith('Q: ' + q.question))).filter(Boolean).map(f => f.content.replace('\n', ' → '));
  $('#planWrap').insertAdjacentHTML('afterbegin', '<div class="muted" id="buildMsg"><span class="spin"></span> rebuilding with your answers…</div>');
  await buildPlan('The user answered these questions — fold them in, drop the questions that are now answered, and ask the next most useful ones:\n' + answers.join('\n'));
}

globalThis.checkUpdates = async function checkUpdates(button) {
  if (button) button.disabled = true;
  $('#planWrap').insertAdjacentHTML('afterbegin', '<div class="muted" id="chk"><span class="spin"></span> comparing new research against the plan…</div>');
  try {
    const r = await post(`/api/projects/${state.project.id}/plan/check-updates`);
    await loadPlan();
    if (r.updates.length && $('#planChanges')) $('#planChanges').open = true;
    if (!r.updates.length) $('#planWrap').insertAdjacentHTML('afterbegin', '<div class="muted mb-2">No new changes to review.</div>');
  } catch (e) { toast(e.message || e, 'err'); $('#chk')?.remove(); }
  finally { if (button) button.disabled = false; }
}
globalThis.updStatus = async function updStatus(id, status) {
  const reason = status === 'rejected' ? prompt('Why keep the current plan? (Optional)', '') : '';
  if (reason === null) return;
  await post(`/api/plan-updates/${id}`, { status, ...(reason ? { reason } : {}) });
  await loadPlan();
  $('#planChanges')?.querySelector('summary')?.focus();
}
globalThis.applyUpdates = async function applyUpdates(button, exact = false) {
  if (button) button.disabled = true;
  const projectId = state.project.id, planId = planState.plan.id;
  $('#planWrap').insertAdjacentHTML('afterbegin', `<div class="muted"><span class="spin"></span> ${exact ? 'saving accepted edits…' : 'rebuilding with accepted changes…'}</div>`);
  try { await post(`/api/projects/${projectId}/plan/apply`, exact ? { exact_plan_id: planId } : undefined); }
  catch (e) { toast(e.message, 'err'); }
  await loadPlan();
}
globalThis.startProject = async function startProject() { await post(`/api/plans/${planState.plan.id}/start`); await loadPlan(); }
globalThis.researchThis = async function researchThis(q) {
  const c = await post('/api/conversations', { project_id: state.project.id, title: q.slice(0, 60) });
  await loadChats(); await selectChat(c.id); $('#q').value = q; $('#q').focus();
}

route();


export const moduleName = "plan";
