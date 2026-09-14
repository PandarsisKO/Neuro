# T4 execution plan — from "proven through a bridge" to a native, budgeted, scheduled executor

Written 2026-09-14 for a Sonnet session (or Codex) to execute rung by rung. Every rung is independently
shippable, has a gate, names its files, and says what it must NOT do. Current code and tests outrank this
document; if they disagree, fix the document. Kyle's constraints: stay inside a stated dollar budget per run,
never exhaust it in one go, and disclose any spend the app's ledger did not capture.

## Where T4 stands (read before touching anything)

- `neurosearch/t4.py` — selector v2 (`select()`: ranked chunks + `by_source` rollup + `source_relevance()`),
  `plan()` (a $0 routing dry run). Executes nothing. 11 + 7 + 7 tests in `tests/test_t4_*.py`.
- `neurosearch/findings.py` — `suggest_for_source(..., substance_floor=None)`: the probe is built, tested, and
  validated live (`docs/T4-ADMISSION-2026-09-14.md`, "Live validation"). `suggest_for_project()` and the
  `suggest_findings` job kind do NOT yet pass the floor through.
- The 20 sources run for real so far ran through a cross-environment bridge because this Cowork device shell
  cannot reach `api.anthropic.com`. The bridge is scratch, not product. Everything below runs natively on
  Kyle's Mac through the app's own workers. Do not rebuild the bridge.
- Measured facts to design against: substance probe at floor 30 lost nothing on 20 sources; v2 relevance
  Spearman 0.62 vs substance; relevance is weak on spreadsheets; today's unranked cost per suggested finding
  was $0.009, ranked+probed was $0.005; Sonnet 5 is $2/$10 per M tokens, Haiku 4.5 is $1/$5; a typical
  transcript window costs ~$0.05–0.06 on Sonnet.

## Rung E1 — thread the floor through the job path ($0)

Goal: `substance_floor` reaches `suggest_for_source` from a job payload, so the executor never calls
`findings` directly.

- `findings.suggest_for_project(...)`: add `substance_floor: int | None = None`, pass it to every
  `suggest_for_source` call. No default change.
- `jobs.run_job`, `kind == "suggest_findings"`: pass `substance_floor=payload.get("substance_floor")`.
- Tests: `tests/test_findings_substance_floor.py` gains one test — a `suggest_findings` job with
  `substance_floor=30` in its payload stops a low first window (reuse `_install`, run via `jobs.run_job` on a
  fake-AI project). One test that a payload without the key is byte-for-byte the old path.
- Gate: focused tests green; full suite no new failures. Nothing else changes.

## Rung E2 — `t4.execute()`: the executor, budgeted and dry-run-first ($0 to build)

Goal: one function and one job kind that turn `select()['by_source']` into `suggest_findings` work, under a
dollar cap, with a $0 dry run that prints exactly what a live run would do.

- `neurosearch/t4.py`:
  ```python
  EXECUTE_VERSION = "t4-execute-v1"
  def execute(project_id: str, *, budget_usd: float, max_sources: int | None = None,
              substance_floor: int | None = 30, min_relevance: float | None = None,
              dry_run: bool = True, transport: str = "interactive") -> dict[str, Any]
  ```
  1. `selection = select(project_id)`; walk `selection["by_source"]` in order (relevance desc, then
     priority-1 count). Skip any source where `findings.is_current(project, source_id)` is true, and any
     with `relevance is None` UNLESS `min_relevance is None` (unscored sources are not "low" — T1's rule).
  2. Estimate each source with the pipeline's own estimator: `sum(usage.estimate_findings(len(user)) for
     each window of findings.canonical_requests(...))`, then multiply by `PROBE_DISCOUNT = 0.5` when
     `substance_floor` is set (measured: the probe halved spend). Stop adding sources when the running
     estimate would exceed `budget_usd` or `max_sources` is reached.
  3. `dry_run=True` (the default): return the plan — ordered sources with relevance, windows, estimate,
     cumulative estimate, and `"executed": False` — and write NOTHING. This is the `t4.plan()` contract
     extended to sources; `plan()` stays as it is.
  4. `dry_run=False`: `usage.guard(total_estimate)` first (the daily/monthly budget still governs), then
     `jobs.enqueue("suggest_findings", {"project_id", "source_ids": [...], "substance_floor",
     "t4_execute_version": EXECUTE_VERSION, "t4_selector_version": SELECTOR_VERSION}, lane="low")` — ONE
     job per source, so the ledger, cancellation, and retry stay per-source, and a dedupe_key
     (`f"t4:{project_id}:{source_id}:{findings.input_hash(project, source_id)}"`) means re-running the
     executor while a source is queued or in flight enqueues nothing (check `jobs.enqueue`'s existing dedupe
     support before inventing one). Return the plan plus job ids.
  5. `transport="batch"`: instead of `suggest_findings`, enqueue ONE `suggest_findings_batch` job for the
     whole selected list (`batches.run` already handles cohorts, settlement and materialisation). Half price,
     up to 24 h latency. `substance_floor` does not apply to batch (the batch path has no sequential probe);
     say so in the returned plan.
- CLI: `neurosearch t4 execute <project_id> --budget 5 [--max-sources N] [--floor 30] [--live] [--batch]`.
  Without `--live` it prints the dry run. With `--live` it prints the plan, the estimate, and asks for
  confirmation unless `--yes`.
- Tests (`tests/test_t4_execute.py`, fake AI): dry run writes nothing and enqueues nothing; the budget cap
  truncates the list at the right source; an already-current source is skipped; unscored relevance is not
  skipped by default; `--live` enqueues one `suggest_findings` per source with the floor in the payload;
  a second `--live` with nothing new enqueues nothing (dedupe); `usage.guard` blocking raises before any
  enqueue; batch mode enqueues one `suggest_findings_batch`.
- Gate: a `dry_run` on Kyle's real Buying Businesses project prints a sane list and costs $0 (check
  `cost_value.unit_costs()` before/after). Full suite no new failures. `docs/T4-ADMISSION-2026-09-14.md`
  gets an "Executor" section in the existing style.
- Non-goals: no new model call type, no `t4.research` contract call yet (the executor delegates to
  `findings.extract` under its existing contract), no structured deltas, no UI.

## Rung E3 — first native live run, throttled (~$3–5)

Goal: prove E2 on Kyle's Mac with the app's own workers and provider routing, not the bridge.

- Kyle runs, on his Mac, with the app's workers up: `neurosearch t4 execute <buying-businesses-id> --budget 3
  --floor 30` (dry run) → review → same with `--live`.
- Routing: `providers.route("findings.extract")` decides local Claude Code vs API per job. Before the live
  run, check `neurosearch health` shows the local provider's billing mode; if `claude_code.local_is_free()`
  is false, expect API spend at the estimate. If it is true, expect ~$0 and slower.
- After: record in the admission doc the real cost vs estimate (this calibrates `PROBE_DISCOUNT` and the
  estimator), sources run, substance distribution, findings suggested, and — the number the whole plan is
  for — cost per suggested finding. Compare against $0.005 (today's ranked+probed) and $0.009 (unranked).
- Gate: the estimate was within 30% of the recorded cost; no source was paid for twice (check
  `work_units` count == windows read); `is_current` is true for every completed source.

## Rung E4 — Kyle's kept-rate review (0$, ~20 minutes of Kyle)

Goal: turn "suggested" into "kept" so cost per KEPT finding exists. Nothing in this plan can measure quality
without it.

- Kyle reviews the suggested findings for: Buy then Build, How To Analyze M&A Broker CIMs, SBA LOANS: Signs
  of a GREAT business, How to Find Businesses to Buy NO ONE ELSE Knows About, and one low-substance source
  (the n8n course) as a control. Approve/dismiss in the Findings workbench as normal.
- Then: `cost_value.unit_costs(window="month")` and `cost_value.by_model()` report cost per kept finding
  by source and by model. Record the kept rate for substance ≥60 sources vs ≤30 sources in the admission
  doc. This number decides E5 and sets the default floor.
- Gate: at least 100 findings adjudicated across ≥4 sources.

## Rung E5 — Haiku vs Sonnet, decided by measurement (~$3)

Goal: settle the tier question with `cost_value.by_model`, as the mission doc requires — not by opinion.

- Pick 8 not-yet-current sources from v2's top 30 (2–3 windows each). Run 4 on Sonnet (the current
  `findings.extract` contract) and 4 on Haiku by temporarily registering a `findings.extract` variant
  contract at `CHEAP` — do this through `contracts.py`'s existing override mechanism if one exists, else a
  documented env override; NEVER by editing the production contract. Both with `substance_floor=30`.
- Kyle reviews all 8 (E4 rules). `cost_value.by_model()` → cost per kept finding per model, plus kept rate.
- Decision rule, written before the data: Haiku wins only if its cost per KEPT finding is lower AND its kept
  rate is within 10 points of Sonnet's. Otherwise Sonnet stays. Record the table and the decision in the
  admission doc; if Haiku wins, change `FINDINGS_MODEL` with a `tier_reason="evidence:..."` citing the run.
- Gate: `contracts.policy_violations()` empty after any change; `neurosearch models` shows the reason.

## Rung E6 — H1 pre-filter, evaluated then enabled (~$0.50)

Goal: the existing cheap drop-filter (`neurosearch/prefilter.py`, off by default) either earns its place or
stays off, on measured savings.

- Run `neurosearch eval --prefilter` on the labeled window fixture. It reports recall, drop rate, tokens
  avoided, filter cost and net savings.
- Enable (`NEUROSEARCH_FINDINGS_PREFILTER=1`) only if net savings are positive AND relevant-window recall
  is ≥ 0.98 on the fixture. Note the interaction: the probe already stops low-substance SOURCES after one
  window; H1 drops worthless WINDOWS inside sources that pass. They compose; measure them together on the
  next E3-style run.
- Gate: the eval artifact is committed under `evals/`; the decision is recorded.

## Rung E7 — the nightly refinery and the morning report

Goal: T4 runs without Kyle typing anything, and tells him what changed.

- Schedule: a housekeeping entry (see `jobs._housekeeping_loop` / `_backfill_research` for the existing
  pattern) that calls `t4.execute(project_id, budget_usd=settings.t4_nightly_budget, dry_run=False,
  transport="batch")` once per night per active project, when `settings.t4_nightly_budget > 0` (default 0 —
  off until Kyle turns it on). Batch transport by default: overnight work does not need interactive latency
  and costs half.
- Morning report: extend the existing report surface (find it: `grep -rn "morning\|digest" neurosearch/`)
  with a T4 section that leads with the coverage-state deltas from `t1.coverage_view` (how many chunks
  moved out of "no signal"), then sources read, findings suggested, spend vs budget, and sources the probe
  stopped (so a wrong stop is visible, not silent).
- Gate: one real night at a $2 budget; the report's spend matches the ledger; no source paid twice.

## Explicitly deferred (and what would un-defer each)

- **Structured deltas** (candidate Claims, contradictions, new Evidence Targets — the mission's full T4
  output): only if E4's review shows findings alone are missing something specific. Until then,
  `findings.extract` under `claims.set_status` as the only door is the executor's output.
- **`t4.research` contract as the executor's own call**: the contract exists and is gate-clean; it becomes
  the executor's task only when structured deltas need a prompt that `findings.extract` cannot express.
- **Brief-text embedding as the relevance basis** (better than the Claim centroid, especially for
  spreadsheets): needs the embedding provider reachable from the executing process — trivially true on
  Kyle's Mac. Do it in E2 or E3 if it takes under an hour: `embeddings.embed_query(project["brief"])`,
  cached in `kv` keyed by brief revision, and `source_relevance()` takes the max of centroid-similarity and
  brief-similarity. Re-run the 20-source backtest in the admission doc before switching.
- **T7 local NLP**: only if, after E7 has run for a week, the share of passages still unexplained after
  T4 stays above a number Kyle picks.

## Budget shape for the whole plan

E1–E2 $0. E3 ~$3–5. E4 $0. E5 ~$3. E6 ~$0.50. E7 first night ~$2. Total to a scheduled, measured, tier-
justified T4: **about $10–12**, spread over at least three sessions, never in one go. Scaling to the ~690
not-yet-current sources in Buying Businesses afterwards, with ranking + probe + batch pricing: on the order
of $25–40 — but by then it is a nightly budget Kyle sets, not a decision anyone makes for him.

## Rules for whoever executes this

1. Read `HANDOFF.md`'s tail and `git log --oneline -10` first; Codex commits between sessions.
2. Two commits per rung: `feat(t4): ...` with its tests and admission-doc section, then `docs: ...` with
   HANDOFF/STATE updates. Run focused tests, then the full suite in four chunks, then `repo-check`.
3. Any real spend: record before/after `cost_value.unit_costs()["total_charged"]` and put both numbers in
   the doc. If a run dies mid-way, count what was billed but not recorded and disclose it.
4. Never edit the production `findings.extract` contract to run an experiment; never call a provider from a
   test; never write research state from the selector or the dry run.
