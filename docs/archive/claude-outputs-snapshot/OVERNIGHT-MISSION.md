# Overnight mission — 2026-09-10, 21:15 PDT → 10:00 PDT

Starting state: `1896030`, tag `v0.57.0`, working tree clean, release-check PASS, app running.

## Mission

**Make findings trustworthy at volume, and teach gap analysis where to look.**

Kyle's objective, in his words: *"as many findings as possible provided they aren't trash."* Today established that
the volume half is a model/cap question and the trash half **has no mechanism at all** — 13,480 findings, 12,614
auto-approved, 12 dismissed, and nothing anywhere checks whether a finding is vacuous or a near-duplicate. Build the
missing half first, then relax the cap that exists only because the filter did not.

Second thread, from tonight: gap analysis starts every search from nothing, because no master-source aggregation
exists. Give it the memory it should already have.

## Safety rules for unattended work

1. **$0. No paid model call, no `--live` anything.** This is enforced by circumstance as well as policy: the cloud
   sandbox has no API key, I will not move Kyle's key into it, and the device VM's egress proxy blocks
   `api.anthropic.com` (measured today). Every test runs under `NEUROSEARCH_FAKE_AI=1`.
2. **Kyle's queue is live and must keep running.** Therefore **no changes to `db.claim_job`, job claiming, lanes, or
   `jobs.execute`'s claim path tonight.** That is the highest-risk surface in the app and it is processing his
   sources while he sleeps. The SCHEDULER rung is design-only for exactly this reason.
3. **Nothing auto-deletes, auto-dismisses or auto-hides any finding.** Every filter output is a review surface.
4. **Never touch `.env`, `data/`, or any project row.** No writes to `data/neurosearch.db` from outside the app, ever.
5. **Every rung passes the full ritual before it reaches the Mac**: version bump ×3 → full pytest → Tier 1 →
   `release-check` PASS → bundle → extract → commit → tag. A rung that fails its gate is **not** extracted; the
   previous version stays in place and I move to the next rung or stop.
6. **Frozen numbers unchanged.** Any deliberate change is recorded in HARDENING.md with its reason.
7. **If the device link drops** (Mac asleep, app closed) I keep building in the cloud and queue the deliveries; a
   dropped link is never a reason to skip a gate.
8. **Stop condition:** two consecutive rungs failing their gates, or any release-check failure I cannot explain →
   stop shipping, write up what happened, leave the last good version running.
9. **State after every rung** goes into HANDOFF.md, so a fresh session resumes exactly where this one stopped.

## The ladder

Ordered so that a stop at any point leaves everything below it shipped and working.

| # | rung | what lands | risk |
|---|---|---|---|
| **F1** | Near-duplicate findings | `findings_quality.py`: cluster a project's findings by cosine similarity over embeddings that already exist. Read-only query, no schema change. | low — new module, nothing else reads it yet |
| **F2** | Vacuity signals | Deterministic, $0: no specific referent (number, name, proper noun), restates the source title, generic-verb-only, below a length floor. Same module, same read-only surface. | low |
| **F3** | The sweep surface | One API + UI list: "likely trash", grouped by reason, with the existing batch accept/reject path — never a new one. Kyle's judgement is the only thing that removes a finding. | low–medium — touches `index.html` |
| **F4** | Let the cap out | With a filter in place, the length-aware cap and `reserve` are doing quality control they were never good at. Raise the cap and/or promote reserve. **This changes how many findings future sources produce**, so it is the one rung with live behavioural effect. | medium — gated on F1–F3 and on Kyle's answer |
| **C1** | Master-source term in `_potential` | The smallest useful slice of SOURCE-CAPABILITY-RUNG: a known-but-uncaptured source stops being scored only on its own 600 characters. | low |
| **C2** | Project-scoped yield profile | The rest of that rung: evidence classes, claim types, density, targets closed, coverage, cadence — per master source, project-scoped per the G4 split. Read model + gap routing. | medium |
| **D1** | `suggest_findings` yields on book-length sources | A known debt from today, same `jobs.Yield` pattern already shipped for claims and ranking. | low |
| **S0** | SCHEDULER admission — **design only, no code** | Today's root cause: the app has no notion of admission. Written up properly for a session Kyle is awake for. | none |

## What is deliberately NOT in this ladder

- The **$0.45 Haiku findings test** — it needs Kyle's key and his double-click; I cannot and should not run it.
- The **field map rung** — needs live catalogue calls and a measurement decision (reference lists vs headings) that
  should be made with evidence, not overnight.
- **OCR for caption-less shorts** — heavy ingestion work against his live data.
- **Anything in the claim path.** See rule 2.
