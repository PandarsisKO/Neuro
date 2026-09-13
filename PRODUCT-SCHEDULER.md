# Neuro Search product scheduler

Authority: Kyle's `DEVELOPMENT-OPERATING-SYSTEM.md`. Updated 2026-09-13. This is distinct from the parked runtime scheduler design in SCHEDULER.md.

## NOW — one active effort

Kyle's 2026-09-13 override: split `neurosearch/web/index.html` into static CSS and native ES modules,
without a build step or visual/behavior changes. ACTIVE: CSS extraction first, then state/API/shared formatting,
view modules and bootstrap/router in independently mergeable steps. Acceptance: affected frontend gates after
each step; full pytest, Tier 1 and commit-bound release-check at release boundaries. Initial CSS landing is
Kyle's direction-check checkpoint before the JavaScript split. Progress and isolation details: `HANDOFF.md`.

## SUSPENDED — RESUME FIRST

D2/F1 is suspended at a safe committed boundary (0.63.57, base `30ee4f4`): mechanical inline-style
retirement is complete; F1 step 3's eight-control SVG sprite remains next. Collision is Yellow: both efforts
share frontend source and design gates. Resume by finding CSS in `styles.css` and JavaScript in its then-current
modules, re-running S50/S44/S5 plus affected gates, and recording a Resume Delta. No backend/T1 work is in flight;
the T1 cohort and release closeout are complete. Interruption cost is low.

The following earlier suspension is historical. The previously uncommitted Codex
Bootstrap/resources/UI fix set is committed on `main` (`21bb117`, `5fc2ad6`,
`d95f4b3`) and its focused tests are part of the full release suite. Claude's
F0/D1 design work is likewise merged (`79c4446`); `DESIGN.md`, `AUDIT.md`,
`DESIGN-MISSION.md`, the Apple reference sourcebook, and the evidence baseline
are tracked. Local `INSPIRATION/`, `Claude outputs/`, `SCREENSHOT AUDIT/`, and
`.audit-compare-tmp/` material remains preserved as non-authoritative evidence;
do not silently delete it.

## NEXT — admitted priorities (maximum three)

1. Continue D2 (`ladder.md` F1–P1) one bounded design surface at a time, using
   Claude's ownership boundaries and append-only handoff rules. The completed
   T1 cohort is recorded in `docs/T1-ADMISSION-2026-09-12.md` and
   `evals/t1/cohort-20260913-105835.json`.
2. Continue the deliberately deferred, non-blocking R8 retention observation; revisit after 2026-10-11 17:28 PT and admit no retention cutoff before then.
3. Preserve R9(c)'s numeric revisit trigger and keep `bge-m3` reserved for a
   later full-space migration gate. See `docs/R9-ADMISSION-2026-09-11.md` and
   `docs/PRE-T1-GATE-AUDIT-2026-09-12.md`.

The governing downstream sequence is R4 → R4 abuse gate → R5 → concurrency gate → R6 → R7 → formal Foundation
closeout → Transcript Intelligence. R6 and R7 share Foundation Phase 9 but require separate implementation and evidence.

## PARKED

- Transcript Intelligence: T1 is complete after the explicit R9(c) deferral. T2 remains the next product rung and is not admitted until its own design and state-model gate are reviewed. T4 reuses R4/R5.
- External AI access and multi-user/sharing: permissions boundary unresolved; no implementation admission.
- Project Inbox, cloud/infrastructure expansion, new acquisition classes, additional Bootstrap, Research/Discover/Planner expansion.
- Consolidated stale/risky Findings review and unrelated Findings redesign: real usability pain; revisit at Foundation admission checkpoint unless it blocks current work.
- Phrase-aware retrieval: measured failure of "quality of earnings"; two word-list fixes rejected. Revisit with a real-query quality experiment after current foundation effort.
- FIELD-MAP-RUNG and remaining SOURCE-CAPABILITY-RUNG scope: idea records, not active queues.

## REJECTED / REVISIT ON TRIGGER

Retrieval reranker, batch-path findings prefilter and Planner v3 remain off. Use HARDENING.md's measured decisions. Additional stores/services and infrastructure retain SPEED-MISSION.md §H's numeric triggers. Do not reopen an experiment simply because another session proposes it.

## DONE

- Existing speed R0–R3 and shipped product features: preserved; no restart.
- 0.63.35 local probe/model/timeout fixes: released historical baseline.
- Historical mission archival at f345726: completed.

0.63.36–0.63.39 are DONE. R8 immediate evidence is complete; its 30-day retention sample continues without
blocking the ladder. R8 retention is deliberately deferred until after 2026-10-11 17:28 PT with no deletion or cutoff admitted. R9(a) embedding decision is complete: `bge-m3` is selected from an isolated frozen-fixture scorecard. R9(b) is complete with Llama 3.1 8B adopted for short classification and all other candidates rejected. R9(c) is explicitly deferred with a numeric revisit trigger; T1 is the active rung.
R4 and its 66-case abuse gate are complete in 0.63.40. R5 and its deterministic concurrency gate are complete in
0.63.41. R6 and its Fast/Warm admission gate are complete in 0.63.42. R7 and its novelty/residual gate are complete
in 0.63.43. The authenticated Foundation closeout observation is complete: current queue was empty, integrity and
backup were healthy, release check passed, and interactive endpoint p90 was at most 0.58s in the observed sample.
T1's implementation, three-pass 73,037-attempt derived-vector backfill, zero-candidate preview, semantic cohort, and
full release gate are complete in 0.63.56; see `docs/T1-ADMISSION-2026-09-12.md`.

## AUDIT ADDITIONS — 2026-09-11

These are bounded gaps found during the post-0.63.37 review. They are admitted as Foundation follow-ons; they do not reopen parked product missions.

1. **Graceful shutdown gate — complete 2026-09-11.** Clean live restart and native SIGTERM-during-provider recovery are covered. The worker fence remains intact; interrupted invocation uncertainty is recorded as `outcome_unknown`; durable output is not duplicated. Evidence: `docs/PLAN_FOUNDATION_RECOVERY_GATES.md`.
2. **Mutation replay/idempotency gate — complete 2026-09-11.** Queue, capture, session-ingest, collection, and candidate transitions were inventoried and covered; missing caption/metadata natural keys, capture replay, and session cookie-file reuse were fixed. Evidence: `docs/PLAN_FOUNDATION_RECOVERY_GATES.md`.
3. **Request-path purity and test isolation — complete in 0.63.39.** Read-only status/polling paths use a cached
   health snapshot and never start a Claude CLI probe. Explicit Re-check and actual local work remain the only probe
   initiators. Tests pin every experimental feature to its production-safe default before imports. The native
   restart gate kills only after an invocation is durably in flight. Combined Phase 1/2 suite: **115 passed**.
4. **Cold derived-state budget.** The first findings-quality scan can still hit the eight-million comparison budget and emit a partial-review warning. Keep the narrowed invalidation cache; measure cold-start cost and admit an indexed/blocking or persisted derived graph only if the agreed latency and memory trigger is crossed.
5. **Evidence and repository hygiene.** `.git/index.lock` is absent. The recordings remain on local disk but no
   `VIDEOS/**` path is tracked. Clean GitHub snapshots exclude `VIDEOS/`, `data/` and `_to_delete/`.
6. **R8 evidence checkpoint — observed 2026-09-11 17:28 PT.** Copied verified backups at 16:28 and 17:28 both pass
   integrity, contain `sqlite_stat1`, and are byte-identical in size (662,859,776 bytes) with 105,048 job-event rows
   and 4,394 distinct jobs. No growth was measurable across that hour. The 30-day sample remains open.

The historical next-order note is superseded. The current execution order is the T1 measurement slice in the existing
production embedding space, with R9(c)'s deferred long-window benchmark retained behind its numeric trigger. The 30-day job-event sample continues in
parallel; no deletion or retention cutoff is admitted before its 2026-10-11 17:28 PT trigger. The cold derived-state
change remains trigger-only.

R9(a) admission: `bge-m3` is selected after passing frozen latency, recall and MRR gates; `nomic-embed-text` is rejected on MRR. R9(b) is complete: Llama 3.1 8B is adopted for short classification, while Qwen3 8B, Qwen3 14B and gpt-oss-20b are rejected on the measured gate. R9(c) is explicitly deferred; see docs/R9-ADMISSION-2026-09-11.md.

## HANDOFF UPDATE — 2026-09-13 12:31 PT

Claude remains the owner of D2/F1 Audit and Design work. The frontend lane has since landed F1 items 2–3 (the
`width:auto` utility and named SVG icon sprite) on `main` through `a914cbf`/`b30420f`; the remaining `display:none`
scope still needs Claude's element-by-element design pass. Codex's backend reliability follow-up is committed at
`c513a46` with the explicit authenticated FTS5 recovery endpoint and health history, and its deterministic release
gate is recorded at `evals/release/release-check-0.63.59-c513a46-20260913-123106.json`. Keep the ownership split:
Claude advances frontend/design surfaces; Codex takes backend/reliability work and appends shared handoff notes.

## CURRENT CHECKPOINT — 2026-09-13

Claude's F1 final item (`display:none` → native `hidden`, including the CSS specificity guard) is now landed on
`main` at `696a0c6`/`509dad2`. UI version is `0.63.60`, and Rung F1 is closed. The next eligible design rung is
**F2**, the shared loading/empty/failed-state primitive for Findings first, then Sources and Chat history. Its
deterministic gates are `test_s44`, `test_s5`, and UI version checks; its behavioral gate requires first-paint
loading, clear-on-data, clear-on-error, and an explicit failed state on the audit instance. Claude owns this lane.
Codex's FTS5 recovery and test-isolation work remains complete and does not block F2.
The dead root-level `main/` worktree copy was moved intact out of the checkout in `45428d2`; `repo-check` and the
release-check for the cleaned tree are green at `82765db` (details in `HANDOFF.md`).
The follow-up isolation cleanup is validated at `d9e2914`: full pytest 1,364 passed, and the commit-bound release
gate is green. No Codex-owned rung is admitted while Claude's F2 design work is pending its boundary.
