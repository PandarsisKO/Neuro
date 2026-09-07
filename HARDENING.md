# Neuro Search hardening roadmap

*Mission: make Neuro Search boringly reliable.* A research project must survive crashes, model changes, API outages,
brief changes, re-ingestion, retries and months of work without losing state, duplicating work, silently going stale,
or producing artifacts whose origin cannot be explained. Then optimise so the best-value model does each task.
Every optimisation must prove one of: more reliable · higher quality · faster · cheaper.

**Rule: do not climb a rung until its exit test passes.**

| Rung | Mission | Deliverable | Status |
|---|---|---|---|
| A | Make it provable | Frozen Golden Project, `NEUROSEARCH_FAKE_AI=1`, `neurosearch eval`, quote + citation + plan-evidence validators, verified backups, migration fixtures, canonical URLs, correlated logs, baseline | **COMPLETE (0.15.0 + A.1 closeout in 0.15.1), pending the live baseline** |
| B | Trust the data | `project_source_analysis` (project-relative summary/substance/relevance off the global source row), provenance columns (model, provider, prompt_version, schema_version, source/brief/facts revisions), deletion cascade | **COMPLETE (0.16.0)** |
| C | Staleness | Artifacts know the revisions they were built from; CURRENT / STALE-STILL-USABLE / REBUILDING / SUPERSEDED; rebuild shows a cost estimate and goes through the budget valve; chats stay historical | **COMPLETE (0.16.0)** — exit test `test_staleness_exit_criteria` |
| D | Survive interruption | Ingestion stages (metadata → transcript → chunks → embeddings → ready, each transactional, resume from the last completed), job leases + heartbeats, `job_events`, one findings job per source, `external_pending` for parked work (re-attach, never resubmit), dependency policies + failure propagation, cancellation semantics, budget/retry waits, crash matrix + 40-source crash-recovery equivalence | **COMPLETE (0.17.0)** |
| E | Modernise AI | Task router (`AIRequest(task, latency_class, quality_class, schema)` → inference profile → provider adapter); adapters reject unsupported knobs loudly; then Sonnet 4.6 → Sonnet 5 as the router's first use, with an explicit thinking policy per task and `max_tokens` re-sized per task after recounting (Sonnet 5: new tokenizer ≈ +30% tokens, adaptive thinking on by default and billed inside `max_tokens`, `temperature`/`top_p` rejected) | **COMPLETE (0.18.0)** — rank.relevance + findings.extract on Sonnet 5 (thinking disabled); the other tasks stay on 4.6 by decision, tooling kept |
| F | Deterministic AI | Structured outputs with versioned schemas (FindingV2, RankingV2, DiscoveryV2, SituationAnalysisV3, PlanPhaseV3, …); the planner split into several small schema'd calls over the same cached material; `_repair_json` demoted to fallback | **COMPLETE (0.19.0) — WITH PLANNER V3 NOT PROMOTED**: structured outputs shipped and passed live on findings.extract, rank.relevance, planner.update, discover.quick; the optional decomposed planner failed its promotion gate and stays experimental behind its flag; V1 remains the production planner |
| G | Cut cost safely | Message Batches for background work (bulk findings, stale rebuilds, evals) — batch is a scheduling choice, not a different operation; same schema/prompt/provenance either way; prompt reorder so volatile findings/facts sit after the stable prefix | **COMPLETE (0.20.0+g5)** — batch findings live PASS (exact 50% model cost, real provider); cache layout: Tier 1 cache read rate 2.1% → 23.4%, chat write premium removed (tail breakpoint OFF by default); ranking not batched, no adaptive breakpoint logic, by decision |
| H | Cut cost intelligently | Luna/Haiku only behind validators: window pre-filter for findings gated on ≥99% relevant-window recall on the golden corpus; ranking with two-pass agreement; never findings extraction itself | |
| I | Retrieval | Reranker on the top 40 first; query rewriting only if recall gain beats the added round-trip; embedding-large only if the eval moves; vector index only on evidence of a bottleneck | |
| J | External failure | `safe_fetch()` (SSRF, private ranges, size/redirect/timeout limits, decompression bombs) for everything except yt-dlp; circuit breakers per provider; per-task fallback policy with `requested_model` / `actual_model` / `fallback_reason` in provenance; Discover-verify holds rather than falls back | |
| K | Health | Health console (database, backups, workers, leases, providers, quality, efficiency) — the start of it ships in Settings → Health in 0.15.0 | started |
| L | Safe change | UI split into ES modules (still no build), fake-AI Playwright end-to-end, release gates: Tier 1 eval → unit → migration → crash/recovery → E2E → RC → Tier 2 eval → cost regression → backup restore | |

## Mission A status

```
MISSION A — MAKE NEURO SEARCH PROVABLE        COMPLETE, pending live baseline

A.1 CLOSEOUT (0.15.1)
[ ] Run the immutable Sonnet 4.6 live baseline        ← Kyle, on the Mac: neurosearch eval --live --baseline
[x] Preserve rejected finding diagnostics             validation_events (finding_validation_failed: candidate title/quote/finding, claimed locator, reason, model, prompt_version); /api/validation-events
[x] Replace silent invalid-citation stripping         one repair round → else the answer is rendered unchanged with a visible warning, persisted in messages.meta
[x] Define planner evidence validation behaviour      unknown evidence ids are removed deterministically (they are optional decoration), recorded as plan_evidence_removed; a plan never becomes current pointing at nothing
[x] Confirm fake providers cannot inspect eval expectations   test: fake_ai.py may read nothing but the prompt (and an audio sidecar)
[x] Baseline is immutable and self-describing         evals/baseline-<version>-<sha>-<model>.json, refuses to overwrite without --force; carries app version, git sha, provider, requested/returned models, prompt versions, request params, thinking policy, tokens by task, validators, validation events
[x] Report separates PIPELINE QUALITY from MODEL QUALITY (fake runs say "not evaluated")
[x] Restore test (backup → fresh data dir → app reads everything back), canonical-URL corpus, /api/health behind auth, FAKE AI banner, log redaction

MISSION B — TRUST THE DATA                    COMPLETE (0.16.0)
MISSION C — STALENESS                         COMPLETE (0.16.0, shipped with B)

B/C CLOSEOUT (0.16.1)
[x] Source-analysis provenance is per task      project_source_analysis keyed (project, source, analysis_kind ∈ relevance|summary); each row has its own model/provider/prompt_version/input_hash; 0.16.0 rows split once at startup
[x] Exact input_hash per artifact               findings: transcript revision + steering + prompt; relevance: title + description + duration(min) + brief + prompt (view count deliberately excluded); stored on analyses and findings; staleness compares the hash and explains the delta with the revisions
[x] Legacy analyses are LEGACY_UNVERIFIED        migrated 0.15 values are preserved, shown with "⚠ legacy analysis", counted as rebuildable, never CURRENT; a fresh analysis replaces them
[x] Plan rebuild waits for its research         jobs.blocked_by: the plan job is not claimable until every findings job it depends on is done; if one fails/cancels the plan job fails with "upstream job … failed" instead of planning over stale evidence — the first use of dependency-aware scheduling (Mission D generalises it)
[x] REBUILDING derives from real job state       queued/running → REBUILDING (with "waiting for budget" when parked); failed → STALE + "last rebuild failed: …"; cancelled → STALE; done → CURRENT. Tests: test_rebuilding_derives_from_job_state, test_plan_rebuild_waits_for_research

MISSION D — MAKE WORK INDESTRUCTIBLE          COMPLETE (0.17.0) — exit gate: test_crash_recovery_equivalence_40_sources (3 seeds)

D CLOSEOUT (0.17.1)
[x] Ambiguous paid calls are modelled          `invocations` ledger: intent → in_flight before the network call, completed/failed after; a run that dies mid-call has its in-flight rows marked OUTCOME_UNKNOWN on recovery (job event + Health count). Invariant: no PREVENTABLE duplicate paid work, and every ambiguous external execution is detectable and accounted for — exactly-once is a database property, not an API property.
[x] Cancel ≠ delete                             cancel stops further processing and keeps completed stages (Retry resumes, never re-transcribes); delete_source removes the durable artifacts. Test: cancel right after transcription → retry → ready with one transcription paid.
[x] Dependency cycle guard                      self / direct / transitive cycles rejected at creation and rewiring (db.DependencyCycle); duplicates collapse; retry rewiring records previous → now in job_events (dependency_rewired).

E0 PREFLIGHT (0.17.2)
[x] SDK retries owned by Neuro Search           clients are built with max_retries=0; providers._Ledgered retries typed transient errors (RATE_LIMIT/TIMEOUT/OVERLOADED/CONNECTION) per task policy, one `invocations` row per transport attempt sharing logical_id (task → logical invocation → attempt); exhausted/permanent failures surface as providers.ProviderError(error_type)
[x] Typed provider errors                       providers.classify_error by exception class/status, never message text; job-level retry branches on the type (legacy regex kept only for yt-dlp text)
[x] Flaky test isolated                         the two barrier tests run on a private database (isolated_db fixture) away from the API client's worker threads
[x] pytest × 20 clean, neurosearch eval × 10 clean
[x] Report carries run metadata for the freeze  logical calls vs transport attempts, outcome_unknown count, returned model ids (0.17.3 — report metadata only, no pipeline change)
[x] Live Sonnet 4.6 baseline                     evals/baseline-0.17.3-849bd0d-sonnet-4-6.json @ 5af87dc, tag sonnet-4.6-baseline — $1.2958, Tier 1 PASS, 135 logical / 136 attempts (one chat transport retry), outcome_unknown 0, returned claude-sonnet-4-6. FREEZE in force: prompts, prompt assembly, retrieval, chunking, embeddings, fixtures, validators, cache layout, worker count, retry policy, max_tokens, thinking configuration.

E1 gate — router equivalence: the same model, inputs and inference settings through the contract system must reproduce the 0.17.x results (fake Tier 1 byte-for-byte on tokens/validators; live within noise). If introducing contracts moves the numbers, E1 has a bug. No prompt changes in E1.
E2 — shadow migration task by task (relevance, findings, chat, discover.quick, discover.verify, planner.analysis, planner.build, plan.update): same prompt + same inputs + different model first; per-task quality/tokens/thinking/reliability/economics/performance; migrate only what passes; a mixed 4.6/5 release is legitimate. Prompt tuning for Sonnet 5 only after the like-for-like comparison.

MISSION E — MODEL PLATFORM + SONNET 5          IN PROGRESS (0.18.0)

E1 INFERENCE CONTRACTS (0.18.0-e1)             COMPLETE — router equivalence proven
[x] contracts.py: one InferenceContract per task (provider, configured model, thinking, effort, max_output_tokens, timeout, max_attempts/backoff, interactive, batch_allowed, fallback_allowed, schema, quality_floor); `neurosearch contracts` prints the table
[x] providers.invoke(task, system, messages, tools, stream) is the only way product code calls a model; call sites carry no model/max_tokens/headers any more
[x] adapters: Claude 4.x → the 0.17.3 request shape byte for byte; Claude 5 → thinking stated explicitly (adaptive is on by default there), effort in output_config; temperature/top_p/top_k rejected loudly; contract validation rejects adaptive thinking on Claude 4, effort without adaptive, too-small budgets
[x] configured_model vs returned_model on every invocation row
[x] per-task experiment overrides: NEUROSEARCH_TASK_{MODEL,THINKING,EFFORT,MAX_TOKENS}_<TASK>; `neurosearch eval --task-model findings.extract=claude-sonnet-5 --task-thinking planner.build=adaptive:high`
[x] E1 GATE: fake Tier 1 before/after contracts identical — volume (182,214 in / 5,677 out / 5,701 cached), quality, validators, invocations by task all byte-equal (test_router_equivalence_fake_tier1); request-shape test proves the 4.6 request carries exactly {model, max_tokens, system, messages, extra_headers}
[x] Claude 5 adapter compatibility: thinking-first responses are parsed by block type everywhere (providers.text_of; findings, ranking, chat, Discover, planner, export); tool loops pass thinking blocks back complete and unchanged (test_tool_loop_preserves_thinking_blocks_unchanged)
[ ] Live router equivalence: `neurosearch eval --live --compare evals/baseline-0.17.3-849bd0d-sonnet-4-6.json` on 0.18.0-e1. STRUCTURAL equivalence is the bar — same contracts, same configured/returned model, same prompt-version hashes, same retrieval inputs, Tier 1 passes, validators do not regress, no unexplained provider behaviour. Billing categories (input vs cache read vs cache write) and total cost are NOT expected to match: cache state differs between runs. E2 tokenizer deltas will be measured with the provider's token-counting endpoint on canonical requests, not from billing rows.

E2 SHADOW MIGRATION                            COMPLETE (0.18.0) — migrated what was proven; the rest deferred by decision, not failed
[x] E2.0 ranking-eval infrastructure (0.18.0-e2.0): frozen rank.relevance fixture tests/fixtures/golden/ranking.json (79 graded candidates against the
    Golden SBA brief: relevant/moderate/weak/irrelevant/clickbait/authoritative-low-view/popular-irrelevant/duplicate; built by build_ranking.py, a test
    proves it is byte-frozen) · `neurosearch eval --ranking [--live] [--task-model rank.relevance=…] [--baseline] [--compare f]` invokes the real task
    through relevance.rank_collection → providers.invoke under its contract and reports P@10, R@10, R@20, P@20 (+ strict grade-3 variants), NDCG@20,
    per-category mean rank/score, schema validity (batches/failed/repaired), unscored candidates, tokens, cost per 100 candidates, latency, configured vs
    returned model · baselines are evals/baseline-rank-<version>-<sha>-<model>.json and never compare across eval types · fake ranker is a lexical
    stand-in (brief-word overlap) so Tier 1 proves the fixture, never the model. No prompt, contract or model-default change.
[x] E2.0b one-command comparison (0.18.0-e2.1): `neurosearch eval --ranking-compare --live` ranks the fixture with claude-sonnet-4-6 then
    claude-sonnet-5 (both thinking=disabled; only the model override differs), preflights each model with the token-counting endpoint
    (canonical input tokens → tokenizer delta; an unknown model id aborts before any paid call), saves evals/ranking-compare/<stamp>-<sha>/
    {baseline-*.json, candidate-*.json, comparison.json, comparison.txt}, freezes evals/baseline-rank-<version>-<sha>-sonnet-4-6.json if
    absent, prints the side-by-side (quality + category + validity = decision gate; tokens/cost/latency = supporting) and a verdict:
    PASS — migrate / PASS WITH CAVEAT / FAIL — keep 4.6 (evals.ranking_verdict; tolerances in QUALITY_TOLERANCE). Never changes a default.
    rank.relevance provenance now records the contract model (identical unless an override is set). Sonnet 5 priced $2/$10 in usage.PRICES.
[x] E2.1 rank.relevance MIGRATED (0.18.0-e2.2): live `--ranking-compare` passed → contracts.RANK_MODEL = claude-sonnet-5, thinking explicitly
    disabled, prompt rank-f38f9a9c and max_out 6000 unchanged; every other task still follows settings.answer_model (mixed release). Baseline
    evals/baseline-rank-*-sonnet-4-6.json and evals/ranking-compare/* are kept as the record. Regression test:
    test_rank_relevance_production_contract_is_sonnet_5_thinking_disabled (request carries thinking={"type":"disabled"}, no effort).
[x] E2.2 tooling: `neurosearch eval --findings-compare --live` ingests the Golden Project once, runs the findings workload (8 sources,
    9 windows, same brief/prompt 18b5db69/validators/window size) with claude-sonnet-4-6 then claude-sonnet-5 (thinking disabled; second
    pass forced past the input_hash idempotency), preflights both model ids via token counting (canonical input tokens → tokenizer delta),
    saves evals/findings-compare/<stamp>-<sha>/{baseline-*, candidate-*, comparison.json, comparison.txt}, freezes
    evals/baseline-findings-<version>-<sha>-sonnet-4-6.json if absent. Compares golden evidence recall + every planted nugget individually
    (lost/gained), quote validity, rejected, findings per source/window, summary/substance validity, truncations/parse failures/no-JSON
    (= incomplete outputs), fence repairs, outcome_unknown, configured/returned model, billed tokens, cost, cost per source-hour, latency.
    Verdict (evals.findings_verdict): hard gates = quote validity ≥ 0.98, stored re-check 1.0, incomplete outputs 0, every source analysed,
    outcome_unknown 0, returned model = configured, evidence recall not below baseline − 0.10, fewer than 2 nuggets lost; findings count is
    NEVER a gate (caveat under 70% of baseline); cost/latency caveat only. findings.OBSERVER + findings._last_call are read-only diagnostics.
[x] E2.2 findings.extract MIGRATED (0.18.0-e2.3): live `--findings-compare` was a clear PASS → contracts.FINDINGS_MODEL = claude-sonnet-5,
    thinking explicitly disabled, prompt findings-18b5db69 and max_out 4000 unchanged. Baseline evals/baseline-findings-*-sonnet-4-6.json and
    evals/findings-compare/* kept as the record. Regression test: test_migrated_contracts_are_sonnet_5_thinking_disabled (both migrated tasks
    send thinking={"type":"disabled"}, no effort; every other task still sends the plain 4.6 request shape).
[x] E2.3 tooling (0.18.0-e2.4): `neurosearch eval --migration-compare --live` — one command for every remaining task, identical frozen inputs
    per arm (Golden ingested once, findings once on the production Sonnet 5 contract, approved; project state restored between arms), preflight
    of both model ids, expected maximum spend printed first, eval-only budget written into the temporary DB (real budget untouched):
      planner.analysis + planner.build   4.6 · 5 disabled · 5 adaptive/medium — frozen deterministic rubric tests/fixtures/golden/planner_rubric.json
                                         (24 plan checks + 11 analysis checks: risks, assumptions, dependencies, first steps, contradictions, open
                                         questions, completeness; structure minimums; grounding = research-basis items carrying evidence ids).
                                         Adaptive is recommended ONLY if it beats disabled by ≥0.10 on the rubric, removes a failure mode
                                         (truncation / JSON repair) or lifts completeness ≥0.25 — equal quality → disabled.
      planner.update                     4.6 · 5 disabled — frozen current plan = the 4.6 arm's plan + one new lender finding + one user fact;
                                         gate = the update addresses the new finding, well-formed JSON, no repair/truncation
      export.synthesis                   4.6 · 5 disabled — gate = every citation link exists in the material, all six sections, no truncation
      answer.chat (+ answer.repair)      4.6 · 5 disabled — hard gates: citation validity, cites-expected-source (−0.10), contradiction handling
                                         and gap detection (losing 2 questions fails, 1 caveats), repair rounds (+2 fails), incomplete answers,
                                         outcome_unknown, returned model; repair judged on repair success and migrates with chat
      discover.quick / discover.verify   stay on 4.6 (no frozen exit test) — excluded
    Saves evals/migration-compare/<stamp>-<sha>/{planner-*, planner.update-*, export.synthesis-*(.md), answer.chat-*, comparison.json, comparison.txt};
    prints one PASS / PASS WITH CAVEAT / FAIL per task plus a recommended setting; changes nothing (contracts stay until migrated by hand).
    Read-only observer hooks: qa.OBSERVER, planner.OBSERVER (+_parse_json events), export._last_call — Tier 1 byte-equal.
[—] E2.3 live comparison NOT RUN — by decision (Kyle, 0.18.0): enough evidence gathered; the consolidated $3–5 live run is not required.

MISSION E OUTCOME (0.18.0)
  Production model assignments (contracts.py):
    rank.relevance     claude-sonnet-5, thinking disabled   (E2.1, live ranking comparison PASS)
    findings.extract   claude-sonnet-5, thinking disabled   (E2.2, live findings comparison clear PASS)
    answer.chat, answer.repair, export.synthesis, planner.analysis, planner.build, planner.update,
    discover.quick, discover.verify              claude-sonnet-4-6 — INTENTIONALLY DEFERRED, not failed
  Tooling kept for later (Sonnet 4.6 retirement, or an intentional revisit): `neurosearch eval --ranking-compare`,
  `--findings-compare`, `--migration-compare` (+ planner_rubric.json), all `--live`-capable, all changing nothing by themselves.

EVAL POLICY from here on (Kyle, 0.18.0)
  - Required on every change: automated Tier 1 eval (fakes), unit + integration tests (pytest), crash/recovery suite.
  - Live paid evals only for: a major model replacement, a major architectural change affecting AI behaviour, or the
    investigation of a detected regression. Never a routine step; never something Kyle has to operate by hand.
[ ] E2.3 findings.extract (thinking disabled) — needs its own fixture-level comparison next
  order: rank.relevance → findings.extract (both with thinking=disabled to preserve the 4.6 no-thinking behaviour) → chat → discover → planner (adaptive thinking experiments only there, effort via output_config)
  0.19.0 structured outputs + planner decomposition · 0.20.0 batch economics · 0.21.0 cheap routing — each independently measurable
  E1 — inference contracts per task (provider, model, thinking policy, effort, max_output_tokens, schema, timeout, retry policy, interactive/background, batch_allowed, fallback_allowed, quality_floor) on top of providers.py + the invocation ledger
  E2 — the 4.6 → 5 migration as the router's first experiment: live 4.6 baseline frozen first, then Sonnet 5 on the same corpus/prompts/inputs, compared per task (input tokens, visible output, thinking, cost Δ, validators, completion). Worker count unchanged until the comparison is done.
```

## Rung G — asynchronous / batched AI + cache layout (0.20.0 → 0.20.0+g5: COMPLETE)
Abstraction: a logical work item = one findings window (`findings.batch_requests` → stable `custom_id`
`fw-<source12>-<window>-<inputhash12>`, frozen request params) → a **cohort** (the set of items submitted together, `batch_items`
table, cohort_no) → one provider batch per cohort. Cohort sizing is a transport choice; cohort 2+ carries only the items that
failed in cohort 1 with the SAME custom_ids and params (`batch_retry_planned`), up to `batches.MAX_COHORTS` (3) — after that the
job fails visibly naming the source/window; every source whose windows all succeeded stays materialised.
Equivalence: both transports end in `findings.materialize()` (validation, quote check, notes, analysis, provenance, atomic write).
The equivalence test runs all 9 golden sources (10 windows) interactively, then the same items through the real queue
(park → poll → materialise) and requires identical semantic artifacts (notes text/evidence/quote validation, analyses, schema
version, prompt/input hashes); only `transport`/`batch_id` differ and they are asserted EXPLICITLY ('batch', msgbatch_…).
Durability invariants (measured with fakes, tests/test_indestructible.py::test_batch_*): intent persisted (kv `batch:intent:<job#cohort>`
+ planned ledger rows) before submission; handle persisted → `external_pending`; crash after the provider accepted the batch but
before we stored its id → recovery re-attaches (one provider batch, never two; fake: exact client_ref; real API: `AnthropicBatch._attach`
heuristic = unknown batch created after our intent with our item count, confirmed by custom_id match at result time, event
`external_reattached` where=recovery_heuristic); every result mapped by custom_id (unknown ids counted, missing ids errored);
succeeded/errored/expired/canceled handled per item; raw provider results persisted locally in `batch_items.raw` the moment the batch
ends (before any materialisation; crash after persist → second run uses the local copy, no provider re-read); cancellation harvests
what completed (`batches.cancel_job`: provider cancel → persist_results → materialize_ready → `batch_cancelled`) and never destroys
completed valid results. Structured output + quote validation are the same code path as sync (`providers.structured`,
`findings.materialize`); the raw message is rehydrated (`batches._Msg`) so `usage.record_anthropic` sees real token counts.
Economics: `usage.record(transport="batch")` prices model tokens at `BATCH_MULT` 0.5 and records `saved` = full interactive price −
actual; `batches.estimate()` reports now / background / discount and the note "model cost only … batches may take up to 24 hours";
UI wording rule: "Analyze now — faster, standard API price" / "Analyze in background — up to 24 hours, ~50% lower model cost" (never
"within hours"). Cache: batch requests carry the same breakpoint placement as interactive (`findings._system_blocks`) with
`ttl="1h"`; cache_read/cache_write are surfaced per batch in the job result and treated as an optimisation, never assumed.
Fake measurements (0.20.0+g1, golden project, 9 sources / 10 windows): interactive 10 calls 31188 in / 2803 out = $0.135609;
batch 10 items 1 cohort = $0.067805 (ratio 0.5000, saved $0.067805), 37 notes identical, provenance transport='batch';
partial failure: cohort 2 = 1 item (the failed window only), 8 sources materialised before the retry was submitted; max-cohorts
give-up: job failed, 8/9 sources kept; crash-before-persist: 1 provider batch, re-attached; crash-after-persist: results read
from the local copy; cancel: prefix of completed items materialised, rest explicitly `canceled`. Full suite 143 tests, 6/6 green
runs; Tier 1 frozen numbers unchanged.
G1 review refinement (0.20.0+g2) — unknown-handle recovery on the real API never claims by count alone. The intent kv carries an
`attempted` mark set immediately before `batches.create`; without it recovery does nothing (we never reached the provider). With it:
known persisted id → normal re-attach; otherwise plausible batches (unknown to `batch_items`, created after the intent, same request
count, not previously rejected) become tentative CANDIDATES — the job parks on handle `tentative:<job#cohort>` (derived status
`external_tentative` for one candidate, `external_handle_ambiguous` for several), ledger rows are NOT started, nothing is cancelled
or mutated (`cancel_job` leaves candidates untouched). `check()` on the tentative handle retrieves each candidate; an ended one has
its results read (read-only) and the returned custom_id SET compared with ours: exact match → `_attach(where=verified_custom_ids)`
+ persist from the already-read results (one results read); mismatch → `external_candidate_rejected` (expected/returned/overlap)
and the id is remembered in `batch:rejected:<ref>` so it is never a candidate again; no candidate left → `db.unpark_external`
(`external_recovery_resubmit`) and the job submits afresh. History: `external_candidates`, `external_observing`,
`external_candidate_rejected`, `external_reattached`, `external_recovery_no_candidate`, `external_recovery_resubmit` in job_events.
Fake coverage (`NEUROSEARCH_FAKE_BATCH_NO_CLIENT_REF=1` makes the fake behave like the real API): two same-sized batches created in
the recovery window → both observed, neither attached while processing, foreign one rejected, ours adopted, 2 provider batches total,
foreign untouched; foreign-only → rejected, then resubmitted, still untouched; stub test: count+time alone never attaches.
G2 (0.20.0+g2) — now vs background is an explicit per-request choice. `POST /suggest {transport: interactive|batch}` creates
`suggest_findings` or `suggest_findings_batch` (default interactive; auto-analysis after ingest stays interactive; nothing converts a
findings job into a batch job). `POST /suggest/estimate` → `batches.estimate()`: both quotes (model cost only), `basis` 'token count'
(provider count_tokens over the canonical requests, cached in kv `tokcount:<custom_id>` — the custom_id embeds the input hash, so
a cached count is exact until inputs change; at most `MAX_COUNT_CALLS`=12 uncached calls per estimate, the rest 'mixed'/'estimate'
via the character formula; counting failure never blocks the UI), `recommended` = background when items ≥ `BULK_THRESHOLD_ITEMS`
(one constant, env `NEUROSEARCH_BATCH_BULK_THRESHOLD`, default 6 windows) else now, and the exact UI wording in `batches.CHOICES`
("Analyze now — Faster · standard model cost" / "Analyze in background — Up to 24 hours · ~50% lower model cost"). The Findings
view's "Analyse new… / Re-analyse all…" open the chooser with both priced options and the recommendation badge. Job rows carry
`batch` = `batches.ui_state(job)`: queued / submitting → processing (with "retrying N items (round k)") → verifying (tentative) →
materializing → complete | partial_failure | failed | canceled ("N sources with complete results kept"); progress bar = sources landed.
`db.sources_being_analysed` counts a batch job's sources only until each one's findings land.
G3 (0.20.0+g2) — stale rebuilds through either transport. `staleness.assess` treats `suggest_findings_batch` (queued/running/
external_pending) as REBUILDING per not-yet-landed source with note "in background · <ui label>", and quotes `findings_background`
/ `total_background` next to the interactive figures (plan never batched). `staleness.rebuild(..., transport=)`: interactive = one
job per stale source (unchanged); batch = ONE `suggest_findings_batch` job for all stale sources (force, reason=stale); the plan job is
`blocked_by` it and `dependency_report` counts `external_pending` as pending, so the plan waits exactly as for synchronous jobs
(tests: plan not claimable while the batch is out; blocked → done after the batch job completes; plan v2 current). Stale cards:
"Rebuild now · $X" / "Rebuild in background · $Y model cost"; plan card: "Re-analyse now + rebuild · $total" / "Re-analyse in
background + rebuild · $total_background". Completed sources are current + usable while another item retries in a later round.
Live smoke (0.20.0+g3): `neurosearch batch-smoke --live` → `batch_smoke.run`: eval-only database (temp dir, deleted afterwards,
$1 eval budget in its own kv), golden `yt01` only (one findings window), preflight of the production findings model, token-counted
standard vs batch quote printed before submission, ONE real Message Batch item through the normal queue (`external_pending`, handle
persisted, intent cleared), polling through `AnthropicBatch.check` (15 s, `--timeout-min` 60; a timeout is a FAIL that never cancels
the batch), raw result persisted in `batch_items.raw` before materialisation, custom_id verified (counts.succeeded 1, unknown 0),
ledger row completed with the batch id, `findings.materialize` via the job (findings-v2 validation + quote validator inside),
provenance transport=batch + batch id on the analysis and every note, evidence counters, zero schema events, usage row priced by
the returned model: actual cost == 50% of (in + 1.25·cache write + 0.1·cache read)·pin + out·pout, saved recorded, estimate within
2× of actual, job history without re-attach/retry/cancel → `evals/batch-smoke/<stamp>-<sha>-<tier>.{json,txt}` and PASS | FAIL.
The fake tier (`neurosearch batch-smoke`) runs the identical flow and is a pytest test. Not exercised live, by decision: crash
timing and forced ambiguity (the fake/crash coverage owns that window).
LIVE RESULT (2026-09-07, `evals/batch-smoke/20260907-091438-70f55c9-live.txt`, Batch smoke PASS): a real Sonnet 5 Message Batch
completed; the one expected custom_id returned exactly; external_pending lifecycle held; the raw provider result was persisted
before materialisation; the normal findings.materialize path completed; 10 findings written and quote-validated; provenance
transport=batch + provider batch id; zero schema mismatch/fallback/truncation/refusal events; standard model-rate cost $0.016218,
actual batch cost $0.008109 — an exact 50% provider model-cost reduction; no retry, re-attach or cancel occurred.
**Message Batch implementation portion of Rung G: COMPLETE (0.20.0+g3).** No further batch live testing is required. Ranking is
not batched (by decision). The prompt/cache-order optimisation is the separate second portion of Rung G (below).

### Rung G, second portion — prompt-cache layout (0.20.0+g4; fakes/Tier 1 only, no live run yet)
Measured first (`neurosearch eval --cache-layout`; the fake now simulates the provider's cache exactly — `fake_ai._simulate_cache`:
prefix = tools → system blocks → message blocks, exact-prefix hits, longest hit read, the rest up to the last breakpoint written,
≥1024-token minimum, read + write + plain == total; tools billed by size like text). Baseline (0.20.0+g3 layout), golden project:
  findings 10 windows: 0 read / 0 write — rules + project + source framing ≈ 750 tokens, under the provider minimum, uncacheable.
  chat, 4 turns with a finding pinned + a fact recorded after turn 2: 0 read, 17,070 of 17,073 tokens WRITTEN — every turn re-wrote the
  whole prompt at 1.25× and never read anything: (a) the system block was not marked (its chars were under CACHE_MIN_CHARS, and the
  tool definitions, which precede it in the cache order, were not counted), (b) findings/facts lived INSIDE the one system block, so
  any pin/fact invalidated the whole prefix, (c) the conversation-tail breakpoint never hits across turns because history is stored
  without the excerpts that were sent. Input cost index 1.25 for chat (worse than no caching). New conversation, 3 turns: same.
  planner: 44% read (research material shared by both passes) — already right.
Changed layout (content preserved exactly — `tests/test_indestructible.py::test_cache_layout_preserves_request_content_exactly`
compares the multiset of non-empty lines over tools + system + messages against a verbatim copy of the previous builder, for chat
with/without web rule and with/without full-context material, and for every golden source's findings prompt):
  chat `qa.chat_system_blocks`: [1] rules + web rule + project identity/brief/tool guidance/steering → breakpoint (tools counted
  toward the minimum) · [2] full-context material when it fits → breakpoint · [3] `PROJECT_STATE_BLOCK` = pinned findings + facts,
  AFTER the prefix, unmarked. Same lines, same meaning; retrieval, tools, models, schemas, provenance untouched.
  findings `_system_blocks`: [rules] [project framing → breakpoint] [source framing → breakpoint] (`HEAD_SEP` split of the same head
  text; batch requests get the same layout with the 1h ttl; custom_ids/input hashes unchanged) — the project block is byte-identical
  across a project's sources so bulk analysis can share one prefix once rules + project framing reach the minimum (not the case for
  the small golden project; long steering makes it so).
After (same eval): chat 4 turns 4,020 read (24%; the 1,340-token stable prefix read on turns 2–4, INCLUDING after the pin/fact),
cost index 0.979; new conversation 35% read, 0.843; overall 21% read, input cost index 0.905 (baseline 1.026). Tier 1: cache read
rate 23.4% (baseline 2.1%), answer task 44,220 cached tokens (baseline 0). Totals invariant: Tier 1 answer 141,225 / findings 30,297 /
plan 11,026 / grand 207,444 identical under the old and new layout; the router-equivalence and migration-compare gates now freeze
these transport-invariant totals (the cache split is asserted separately).
Decision (0.20.0+g5, Kyle): the conversation-tail breakpoint (`usage.mark_last`, wrapped by `qa._tail_breakpoint`) is OFF by default.
It writes the volatile per-turn remainder at 1.25× and can never produce a cross-turn hit (history is stored without the excerpts
that were sent), so it only pays back when the same turn makes another call (tool round, citation repair) — break-even ≈ one extra
round per four turns; the default is optimised for the common single-call turn. `NEUROSEARCH_CHAT_TAIL_BREAKPOINT=1` re-enables it
for experimentation or tool-heavy workloads; no adaptive/predictive breakpoint logic, by decision. The eval keeps measuring the
ON variant beside the default.
Final layout policy: stable project prefix (tools + rules + project identity/brief/guidance/steering) → cache; reusable full-context
material → cache when it fits; pinned findings/facts → after the prefix, not cached; conversation/request tail → not cached by
default; findings [rules][project→bp][source→bp]; batch requests 1h ttl.
Before / after (golden project, `neurosearch eval --cache-layout`, input cost index: 1.000 = every input token at full price):
  chat 4 turns with mid-chat pin+fact:   old 1.250 (0 read, all written)  →  new 0.808 (24% read; only the 1,340-token prefix ever written, once)
  new conversation, 3 turns:             old 1.250                          →  new 0.682 (35% read, zero writes; tail ON would be 0.843)
  planner (2 passes):                    0.714 unchanged                     findings: 1.000 unchanged (under the provider minimum for this fixture)
  overall:                               old 1.026                          →  new 0.844
  Tier 1: cache read rate 2.1% → 23.4%; cache writes 141,225 → 5,752 tokens on the answer task; answer-task fake cost $0.4048 → $0.3331
  (−17.7%); totals invariant (answer 141,225 / findings 30,297 / plan 11,026 / grand 207,444).
Not measured live, by decision: the simulator models the provider's prefix rules, the content-equivalence gate proves the model
sees the same information, and Tier 1 is green — this is not a case for a manual eval. The real tokenizer counts tool schemas and
rules larger than the fake, so the stable chat prefix clears the 1024-token minimum more easily live.
**Prompt/cache-order portion of Rung G: COMPLETE. Rung G: COMPLETE (0.20.0+g5).**

## Mission F — deterministic AI (approved 0.18.0; invariant: malformed model-generated JSON is no longer a normal failure mode)

Decisions (Kyle): `jsonschema` approved (registry/fake/test validation; provider-enforced structured output is the production
guarantee — never hand-written validators); planner decomposition behind a temporary flag for one release, old path removed after;
schemas keep internal `$ref`/`$defs` (only external refs, allOf/oneOf/not are unsupported) with a provider-compat preflight; typed
handling still needed for max_tokens, refusal, transport/provider failures, unsupported schemas, tool failures and the citations
incompatibility; `discover.verify` stays on its citation-capable free-text path (citations + output_config.format → 400).

```
F1+F2 SCHEMA REGISTRY + STRICT FINDINGS/RANKING     COMPLETE (0.19.0-f1)
[x] schemas.py registry                 versioned JSON schemas (findings-v2, rank-v2) with $defs; provider_schema() strips client-only constraints
                                        (min/max/length/pattern/format) for output_config.format; validate()/is_valid() use the FULL schema via jsonschema
[x] provider-compat preflight           schemas.check_provider_compat: internal $ref only, additionalProperties:false on every object, no allOf/oneOf/not;
                                        run from contracts.validate for every structured contract and in tests for every registry entry — an unsupported
                                        schema fails at contract time, never in a paid request
[x] contract ↔ schema binding           InferenceContract.schema = registry key (None = free text); request_params adds output_config.format (GA on 4.6 and 5;
                                        merged with effort for Claude 5); NEUROSEARCH_TASK_SCHEMA_<TASK>=none is the rollback switch
[x] schema_version in provenance/hash   findings.input_hash + relevance.input_hash include the schema version; analyses carry schema_version; staleness
                                        explains "output schema changed"
[x] fake conformance                    the fake validates its own structured outputs against the requested schema (a non-conformant fake is a test failure);
                                        NEUROSEARCH_FAKE_AI_BAD_JSON=1 breaks the JSON on purpose to exercise the fallback path
[x] strict findings + ranking           providers.structured(task, resp): strict json.loads + jsonschema validation; the legacy tolerant parsers
                                        (findings._legacy_parse, relevance.parse_scores) remain ONLY as observable emergency fallbacks
[x] typed truncation / refusal          providers.OutputError(TRUNCATED|REFUSED) + SchemaMismatch; a truncated structured output gets exactly one budget
                                        escalation (1.5× max_output_tokens, recorded) then is an error; refusal is never parsed
[x] fallback = degraded event           validation_events schema_fallback / output_truncated / output_refused; kv evidence:schema_fallbacks|schema_failures|
                                        output_truncated|output_refused → /api/health.structured_outputs → Settings → Health "Structured-output fallbacks";
                                        Tier 1 gates schema_fallbacks = output_truncated = output_refused = 0 (steady state zero)
[x] token counting includes the injected format instructions (count_tokens gets output_config) so E2-style canonical counts stay honest

F1/F2 CORRECTIONS (0.19.0-f3, Kyle)
[x] jsonschema is REQUIRED               schemas.check_installation() at app startup and CLI init: an incomplete checkout exits with
                                        "Neuro Search installation is incomplete: jsonschema is required by structured outputs. Run ./start …"
                                        — no machine validates less than another
[x] mismatch ≠ parse problem             providers.invoke_structured(): provider structured result → json.loads → FULL local validation → PASS store /
                                        FAIL SchemaMismatch. A mismatch on a normal completion is a BUG SIGNAL (schema_mismatch event + counter), retried
                                        once with a fresh completion, then a typed failure that propagates (schema_failure). Legacy parsing is NOT on
                                        this path. NEUROSEARCH_SCHEMA_COMPAT_FALLBACK=1 is the only, explicitly degraded escape hatch: the legacy parser
                                        may run but its result must pass the full local schema (schema_fallback event either way)
[x] bounded escalation                   truncation → one escalation through usage.guard, to min(1.5×, contract.max_output_ceiling); contracts without a
                                        ceiling never escalate; original/escalated/ceiling budgets recorded in the output_truncated event
[x] Health                               structured_outputs {mismatches, mismatches_recovered_by_retry, fallbacks, unrecovered, truncated, refused};
                                        Tier 1 gates mismatches = fallbacks = truncated = refused = 0

F3 PLANNER.UPDATE + DISCOVER.QUICK           COMPLETE (0.19.0-f3)
[x] planner.update                       schema plan-update-v2 ({"updates":[{section, previous, proposed, reason}]}); UPDATE_SYSTEM's output line now names
                                        that object (prompt hash changed, recorded in provenance); a misunderstood output is a typed failure that propagates
                                        (API 502 with the reason) — NEVER an innocent empty update list, not even on the legacy path; ceiling 6000
[x] discover.quick                       schema discovery-v2 (kind/depth enums, start_with objects); ceiling 5000
[x] discover.verify                      UNCHANGED, deliberately: citations (web_search) and output_config.format are incompatible (400). Boundary:
                                        discover.quick = structured · discover.verify = citation-compatible text/tool path. Not debt.
F4 DECOMPOSED PLANNER                        COMPLETE (0.19.0-f4) — behind NEUROSEARCH_PLANNER_V3=1; single-call planner is the rollback for one release
  planner_v3.py: research material (one cached system block shared by all five calls) → planner.situation (situation-v3, validated, then
  FROZEN: analysis_hash) → planner.core / planner.execution / planner.economics / planner.actions (plan-core/execution/economics/actions-v3),
  every component receiving the SAME frozen analysis + the id catalogue of the components before it → assemble() in deterministic Python into
  the EXISTING plan shape (no merge call). Every stateful object carries a stable semantic id (phase:financing, task:get-lender-prequalification,
  risk:customer-concentration, question:working-capital-peg); plan["_ids"] maps positional keys → ids; db.save_plan carries statuses by id, and
  planner_v3.reconcile_ids adopts the previous id when the model renamed a substantively identical item (token Jaccard ≥ 0.5), rewriting refs.
  Assembly checks: referenced phase/task/decision/option ids exist, task dependencies exist, no cycles, no self-dependency, evidence ids exist,
  risk mitigations point at real tasks/phases, this_week maps to real tasks, costs/tools tied to known phases, ids unique — any problem →
  PlanAssemblyError, plan_assembly_failed event, previous plan stays current. plan["_build"] telemetry: material tokens, per-component
  input/output/cache read/write/cost/seconds, totals, cache_read_share, analysis_hash — so F5 can answer "more reliable without multiplying cost?".
  plan["_components"] keeps the five generated documents. Migration tooling maps situation → planner.analysis and the four components →
  planner.build so the rubric comparison works on either planner.
  EXIT GATE (tests/test_core.py::test_planner_v3_*, all under the fakes — nothing for Kyle to run):
  [x] situation analysis schema-valid   [x] all four component schemas valid   [x] same analysis_hash used by all components
  [x] zero schema fallbacks/mismatches  [x] zero dangling evidence            [x] zero dangling dependencies   [x] zero dependency cycles
  [x] unique semantic ids               [x] task status survives an equivalent rebuild (reordered + renamed task keeps DONE)
  [x] deterministic assembly            [x] existing API/UI/export plan shape unchanged (every V1 key present; plan_markdown/plan_html work)
  [x] frozen planner rubric ≥ existing path (fakes)   [x] legacy planner selectable (flag off = V1, default)
  [x] incoherent components refused (dangling ref, cycle, self-dependency, duplicate id, missing evidence, bad option, bad phase) with the previous plan retained
F5 CLOSEOUT TOOLING                          COMPLETE (0.19.0-f5) — `neurosearch closeout --live` is the ONE command
  Deterministic phase (free, must pass before any paid call): pytest (whole suite incl. every Mission F test), schema registry
  provider-compatibility, Tier 1 with Planner V1 and with Planner V3 (zero mismatch/fallback/truncation/refusal gates), frozen planner
  rubric on both fake paths, V3 evidence/assembly, rubric V3 ≥ V1.
  Live phase, narrowly scoped to what Mission F changed (chat/repair/export/discover.verify are NOT retested): expected spend printed
  first (≈ $1.05, max ≈ $1.6), eval-only budget in the temporary DB, preflight of every model id, then
    findings.extract   production Sonnet 5 structured path — golden evidence recall (within 0.10 of the saved Sonnet 5 result), quote validity ≥ 0.98,
                       stored re-check 1.0, zero events, returned model
    rank.relevance     production Sonnet 5 structured path — quality inside the saved Sonnet 5 envelope (evals/ranking-compare candidate), zero
                       unscored, zero events
    planner.update     valid structured update on the frozen V1 plan + new finding/fact — addresses the new finding, well-formed, never
                       silent-empty, zero events
    discover.quick     schema-valid result, zero events (pass 1 only; no subjective judge)
    Planner V1 vs V3   identical frozen research — rubric (plan + analysis), evidence validity, completeness, assembly, dangling/cycles, cost
                       (+ cold-cache equivalent, since V1 builds first and warms the shared prefix), latency, tokens, cache write/read, cache
                       read share, per-component telemetry, number of calls
  Planner V3 hard gates (closeout.planner_decision): rubric ≥ V1 (plan and analysis), evidence validity 1.0, no assembly failure, no
  dangling/cyclic refs, no structured-output/assembly events, no truncation/parse/repair, telemetry present; cost > 3× or latency > 3× is
  pathological; anything less is a caveat; cache read share < 0.5 is a caveat. Status reconciliation is proven by the pytest step.
  Output: Mission F PASS / PASS WITH CAVEAT / FAIL + a separate PLANNER V3: PROMOTE / DO NOT PROMOTE; artifacts under
  evals/mission-f-closeout/<stamp>-<sha>/ (deterministic.json, findings.json, ranking.json, planner-v1.json, planner-v3.json, update.json,
  discover.json, closeout.json, closeout.txt). Changes nothing.
    DEPLOYMENT NOTE (0.19.0+f5): the 0.19.0-f4/-f5 update archives were built from the wrong directory, so package files landed at
    the repo root instead of neurosearch/ — the installed CLI never saw `closeout`. Fixed: stray root copies removed, versions are
    PEP 440 (`0.19.0+f5`; the dashed form made `pip install -e .` fail, which ./start used to hide), ./start now warns instead of
    silencing a failed reinstall and installs the `dev` extra (pytest); `neurosearch closeout` installs pytest itself if missing;
    test_version_is_pep440_and_consistent guards the version.
    F5 HARNESS FIX (0.19.0+f6) — the first live run exposed it: Planner V3 logged "vector search unavailable: CONNECTION" mid-comparison.
    Root cause: both planners rebuilt their research per arm (planner._evidence → search → OpenAI embed_query), and search() silently
    degraded to FTS-only on a vector failure, so the V1 and V3 arms did not receive identical input. Fixed:
    [x] planner.research_context(pid, strict=True) prepares the research ONCE; build_plan / build_plan_v3 accept research= and never
        re-retrieve; plans record _research_hash; strict retrieval failure raises search.RetrievalUnavailable; the non-strict production
        path counts evidence:retrieval_degraded (Health)
    [x] test_frozen_research_is_byte_identical_for_both_planners: same first system block byte-for-byte in every planner call of both arms,
        same hash, and a dead vector search after the freeze cannot alter either arm
    [x] resumable closeout: the run's database lives in its directory (data/), stages.json records every stage; `neurosearch closeout --live
        --resume` copies the previous database + completed artifacts, reuses findings / ranking / update / discover, reuses a planner arm only
        if its research_hash equals the frozen research, rebuilds the rest, and writes HISTORY (reused / invalidated + why / rebuilt) into
        the new run; the previous directory is never modified. Legacy runs (no stages.json / database) reuse their four surface artifacts
        with events recovered from their closeout.json and rebuild shared inputs + both planner arms
    [x] a dependency failure (transient provider error, RetrievalUnavailable) makes the stage INCOMPLETE, dependants are skipped, the verdict
        is INCOMPLETE and the V3 decision NOT DECIDED — never a promotion decision on a degraded fallback
    [x] enum casing: the original V3 attempt also logged one schema_mismatch before the connection died; the provider documents that
        enum/const capitalisation is not guaranteed under structured outputs, so providers.structured now normalises enum values
        case-insensitively (schemas.normalize_enums) before the full local validation — a value outside the enum is still a mismatch
    [x] legacy resume rejects artifacts that ran but failed (error / pass false): the first run's update and discover results, which died
        on the same connection failure, are rebuilt, not reused
[x] F5 live (resumed run) — RESULT (Kyle's decision, 0.19.0):
      findings.extract  PASS   rank.relevance  PASS   planner.update  PASS   discover.quick  PASS   Planner V1  PASS
      Planner V3        DO NOT PROMOTE

MISSION F OUTCOME (0.19.0): COMPLETE — WITH PLANNER V3 NOT PROMOTED
  The structured-output migration passed on every production surface it changed (schema-enforced generation + full local validation,
  zero mismatches / fallbacks / truncations / refusals on findings.extract, rank.relevance, planner.update and discover.quick).
  The optional decomposed planner (V3) was evaluated on frozen research against V1 and FAILED its promotion gate:
    planner.situation → options[].fit is locally constrained to an integer 1..5 (the provider-compatible schema cannot carry that
    constraint, so it is stripped from what the model sees); the live model read `fit` as a larger scale and returned 90 / 45 / 75,
    then 9 / 6 on the fresh-completion retry → SchemaMismatch twice → typed failure, V3 build not usable, DO NOT PROMOTE.
    The local validator rejected the outputs exactly as designed: provider structured-output guarantees do NOT replace the full
    local semantic/schema validation when provider-unsupported constraints are stripped. That is a success of the safety
    architecture, and a real defect of V3 as shipped.
  State: Planner V1 = production planner (default). Planner V3 = experimental / disabled behind NEUROSEARCH_PLANNER_V3 (not promoted,
  no tuning loop). No production model assignment or prompt was changed. Live closeout artifacts: evals/mission-f-closeout/
  20260906-205402-d2e8b74 (first run, invalidated by a retrieval/connection outage mid-V3) and its resumed run alongside it (the
  controlled comparison). No further Mission F live testing is required.
  If V3 is ever revisited, the FIRST known issue is `fit` scale semantics under provider-schema limitations: either describe the
  scale unmistakably in the prompt/schema description, or widen the schema and map the scale in assembly — and re-check every
  other stripped numeric constraint (importance 1-5, substance 0-100, score 0-100, fit 1-5 in discovery-v2) the same way.
  Minor eval-reporting cleanup for later (not blocking): closeout.planner_decision prints "V3 truncation / parse failure / JSON repair"
  for a component whose parse_failed flag was set by a schema mismatch; the line should name the actual failure kind (mismatch vs
  truncation vs repair) from the events.
 → release decision: if PROMOTE, NEUROSEARCH_PLANNER_V3 becomes the default for the next
    release with V1 as the rollback for one cycle; if DO NOT PROMOTE, the default stays V1 and V3 is recorded as not promoted — no tuning loop.
    Then Mission F closes and the ladder continues (Rung G); testing stays the guardrail, not the project.
[x] F4  decomposed planner behind NEUROSEARCH_PLANNER_V3 (stable semantic ids per component, evidence validated per component, same external plan format)
[x] F5  automated deterministic closeout + ONE live paid run (AI-affecting request/output change) against the existing baselines/rubric
```

## Mission D in 0.17.0 — what shipped

- **D1 state machine** — stored: `queued | running | external_pending | done | failed | cancelled`; derived (`db.derived_status`): `blocked`, `retry_wait`, `budget_wait`, `rate_limit_wait`, `cancelling`. One execution owner at a time: a worker with the lease, an external provider, or nobody.
- **D2 leases** — `claim_job` is one atomic UPDATE setting `run_id`, `worker_id`, `claimed_at`, `heartbeat_at`, `lease_until`; progress reports heartbeat; a lease-keeper thread extends leases every 30 s; a recovery loop (and every start) re-queues running jobs whose lease expired with "resuming from the last completed stage". Terminal transitions are guarded by `run_id`, so a worker that lost its lease cannot finish someone else's run.
- **D3/D4 staged ingestion** — `sources.stage` ∈ listed → metadata → transcript → chunks → embeddings → ready; each stage's data and its marker commit together (`db.batch()`); a downloaded audio file is recorded (`sources.audio_path`) and reused; transcription is paid once; embeddings are granular (a chunk has its vector or it doesn't). `ingest_source` resumes at the first incomplete stage.
- **D5 idempotency** — `jobs.dedupe_key` (ingest:url, ingest_source:id, findings:project:source, rank:collection, plan:project, discover:project) collapses identical active requests; `suggest_for_source` skips when a current analysis exists for the same `input_hash`.
- **D6 dependencies** — `blocked_by` + `dependency_policy` (ALL_SUCCESS | ALL_TERMINAL | ANY_SUCCESS); an upstream failure fails the dependent with the report ("1/2 upstream jobs succeeded; failed: …"); retrying the upstream rewires and un-fails dependents; the UI shows "7/8 upstream done · 1 failed: X [Retry failed analysis]".
- **D7 `job_events`** — structured history per job (queued, claimed, stage, waits, lease_expired, recovered, external_*, cancel_requested, cancelled, done, failed, deduplicated, retried, unblocked); `/api/jobs/{id}/events`; ⋯ button on every job row.
- **D8 external parking** — `jobs.submit_external()` records intent → submits → parks (`external_pending`, no lease, handle/deadline durable); the external poller resumes finished work; a crash between the provider accepting and the handle being persisted is recovered by `find_by_ref` (re-attach, never resubmit). Proven with `FakeExternal` (durable file, findable by reference, cancellable); Anthropic Batch plugs into `jobs.EXTERNAL` in Rung G.
- **D9 runs** — every claim is a new `run_id`; events carry it; `attempts` counts only runs that ended in error.
- **D10 cancellation** — queued → cancelled now; running → `cancel_requested_at`, the job stops at its next safe boundary (`jobs.check_cancel()` between stages / windows) and writes nothing after; external → cancelled locally, result discarded on arrival; dependents follow the policy.
- **D11 waits** — `wait_reason` budget / rate_limit / retry; budget and rate-limit waits never count as attempts; Health shows expired leases, leased, external_pending.
- **D12 crash matrix** — `jobs.crash_point(name)` + `NEUROSEARCH_CRASH_AT` / `jobs.CRASH_AT`; `tests/crashkit.py` (fixture platform `fixture://`, a killable simulated worker, restart); `tests/test_indestructible.py` covers every crash point and the exit gate: 40 sources (20 captioned, 20 transcribed), ~35% crash probability at random points, three seeds — 0 duplicate sources/chunks/findings, 0 stuck running, exactly 20 transcriptions in the ledger (no preventable duplicate paid work — an ambiguous call is a separate, accounted case), every source ready, every analysis current, plan built after its dependencies, and the final project state byte-equal to the uninterrupted run.

## Missions B + C in 0.16.0 — what shipped

- **`project_source_analysis`** — summary, substance, relevance and relevance_why now live per (project, source) with provenance: model, provider, prompt_version (a hash of the prompt), schema_version, source_revision, brief_revision, facts_revision, timestamps. The global `sources` row keeps only objective facts (the legacy columns stay but are no longer written; existing values were copied into per-project rows once, marked `provider='migrated'`). Reads: the project-scoped sources listing, review cards (`proposed_sources(collection, project)`), the planner's evidence.
- **Revisions** — `sources.revision` = SHA-256 of the normalised transcript; `brief_revision` (brief + goal + audience + output + source prefs + questions + context), `facts_revision`, `source_set_revision` (which ready sources, at which revisions). Findings (`project_notes`), plans and discoveries record the revisions and model/prompt they were generated from.
- **Staleness** (`staleness.py`, `/api/projects/{id}/staleness`) — per-source findings status, plan status and discoveries status among CURRENT / STALE / REBUILDING / MISSING, with the reasons ("brief changed", "transcript changed", "3 sources added or changed since"); older plan versions are labelled SUPERSEDED. Pure computation, never launches anything. Chat messages are never marked.
- **Cost-aware rebuild** (`/rebuild-stale`) — the assessment quotes the estimate (per stale source from your observed cost per minute, plus a plan estimate) against the daily budget left; the rebuild queues one `suggest_findings` job per stale source and one `build_plan`, each passing `usage.guard` on its own — so an exhausted budget parks the remainder and every finished artifact is current individually. UI: warning cards at the top of Findings and Plan with [Re-analyse N stale] / [Rebuild plan] / [Leave stale] / [Raise budget], stale badges on the sidebar counts, and a toast after saving the brief saying what went stale (and that nothing re-ran).
- **Deletion correctness** — `delete_source` marks every finding citation, plan evidence entry (`_evidence[id].source_id`, new) and chat citation that pointed at the source as `removed` (title kept, link dropped), then deletes; analyses/segments/chunks cascade. The UI renders "⚠ … — source removed" instead of a dead link. Nothing dangles invisibly.

## Mission A in 0.15.0 — what shipped

- **Golden Project** — `tests/fixtures/golden/`: 9 frozen sources (three YouTube transcripts including a 92-minute one with nuggets buried in filler, a contrarian podcast, an article, a PDF, a calculator spreadsheet, two irrelevant sources), 35 questions with expected sources/locators/contradictions/gaps, 10 planted evidence quotes. Generated once by `build.py`; the files are what is frozen.
- **`NEUROSEARCH_FAKE_AI=1`** — the whole app (server, workers, CLI) runs on deterministic, content-aware fakes (`neurosearch/fake_ai.py`) through the single provider seam `neurosearch/providers.py`. Every model call declares its task (`extra_headers["x-neurosearch-task"]`), which is the router's future hook.
- **`neurosearch eval`** — retrieval Recall@5/10, MRR, locator accuracy; finding quote validity; stored findings re-verified; golden evidence recall; citation validity; gap detection; contradiction surfacing; plan evidence validity; calculator; tokens per task (input/output/cache read/cache write), cost, cost per source-hour, latency per phase; Tier-1 gates; `--baseline` / `--compare` / `--live`.
- **Validators at runtime** — `neurosearch/evidence.py`: a finding whose quote is not in its transcript window is rejected before it is stored (the candidate is kept in `validation_events`); an answer's `[n]` outside the supplied excerpts gets one repair round, else the answer is shown unchanged with a warning; a plan's unknown evidence ids are removed and recorded. Counters in kv feed Health.
- **Verified backups** — every snapshot is reopened, `quick_check`ed and schema-checked before it counts; hourly integrity check of the live database; `/api/health`, `/api/backup`, Settings → Health.
- **Migration fixtures** — `tests/fixtures/db/`: databases created by 0.1.0, 0.12.0, 0.13.0 and 0.14.0's own schemas, each upgraded by the current `init_db()` in the test suite with row counts proven intact.
- **Canonical URLs** — `media.canonical_url`: youtu.be / `&t=` / `&list=` / `si=` / utm / host case / trailing slash all resolve to one identity before dedupe.
- **Correlated logs** — `neurosearch/logctx.py`: every line carries job/run/project/source/task/provider/model; `NEUROSEARCH_LOG_JSON=1` for shippers.

### Baseline (A10)

The **Sonnet 4.6 baseline** must be captured on a machine with keys before any prompt, router, model or findings change:

```bash
neurosearch eval --live --baseline        # ≈ $1, writes evals/baseline-<version>-<git sha>-sonnet-4-6.json and refuses to overwrite it
git add evals && git commit -m "Sonnet 4.6 baseline"
```

Token counts per task are first-class in that file, so the tokenizer change shows as its own line when Sonnet 5 is compared with `neurosearch eval --live --compare evals/<that file>`. A fake-provider baseline (`neurosearch eval --baseline`) is worth committing too: it is what CI compares pipeline behaviour against.
