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
| E | Modernise AI | Task router (`AIRequest(task, latency_class, quality_class, schema)` → inference profile → provider adapter); adapters reject unsupported knobs loudly; then Sonnet 4.6 → Sonnet 5 as the router's first use, with an explicit thinking policy per task and `max_tokens` re-sized per task after recounting (Sonnet 5: new tokenizer ≈ +30% tokens, adaptive thinking on by default and billed inside `max_tokens`, `temperature`/`top_p` rejected) | |
| F | Deterministic AI | Structured outputs with versioned schemas (FindingV2, RankingV2, DiscoveryV2, SituationAnalysisV3, PlanPhaseV3, …); the planner split into several small schema'd calls over the same cached material; `_repair_json` demoted to fallback | |
| G | Cut cost safely | Message Batches for background work (bulk findings, stale rebuilds, evals) — batch is a scheduling choice, not a different operation; same schema/prompt/provenance either way; prompt reorder so volatile findings/facts sit after the stable prefix | |
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

E2 SHADOW MIGRATION                            NEXT — one task at a time, same prompt + same inputs, different model
  order: rank.relevance → findings.extract (both with thinking=disabled to preserve the 4.6 no-thinking behaviour) → chat → discover → planner (adaptive thinking experiments only there, effort via output_config)
  0.19.0 structured outputs + planner decomposition · 0.20.0 batch economics · 0.21.0 cheap routing — each independently measurable
  E1 — inference contracts per task (provider, model, thinking policy, effort, max_output_tokens, schema, timeout, retry policy, interactive/background, batch_allowed, fallback_allowed, quality_floor) on top of providers.py + the invocation ledger
  E2 — the 4.6 → 5 migration as the router's first experiment: live 4.6 baseline frozen first, then Sonnet 5 on the same corpus/prompts/inputs, compared per task (input tokens, visible output, thinking, cost Δ, validators, completion). Worker count unchanged until the comparison is done.
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
