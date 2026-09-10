# Neuro Search hardening — final verdict (0.24.0, `hardening-complete`)

*Mission (as set at the start): make Neuro Search boringly reliable.* A research project must survive crashes, model
changes, API outages, brief changes, re-ingestion, retries and months of work without losing state, duplicating work,
silently going stale, or producing artifacts whose origin cannot be explained. Then optimise so the best-value model
does each task; every optimisation must prove one of: more reliable · higher quality · faster · cheaper.

**The hardening workstream is closed.** This file is now a record: the verdict table below is the final state of every
rung, the experimental-feature inventory says what is on, off, deferred or dead, and the mission declaration at the end
evaluates the original mission clause by clause. Sections after that are the rung-by-rung history, kept as evidence.
Two commands enforce the state going forward — `neurosearch doctor` (seconds: install, DB, backups, schemas, contracts,
flags, provider circuits, fake smoke) and `neurosearch release-check` (minutes: every deterministic gate, writes
`evals/release/release-check-<version>-<sha>-<stamp>.{json,txt}`; the Health console shows the last result).

## Final verdict table

| Rung | Mission | Verdict | Evidence |
|---|---|---|---|
| A | Make it provable | **DONE** — frozen Golden Project, `NEUROSEARCH_FAKE_AI=1`, Tier 1 eval with frozen totals (answer 34 calls / 165,365 tokens since 0.24.1, findings 9 / 30,297, plan 2 / 11,026), validators (quotes, citations, plan evidence), verified backups, migration fixtures | `neurosearch eval`; `evals/baseline-0.17.3-849bd0d-sonnet-4-6.json` |
| B | Trust the data | **DONE** — project-relative analysis (`project_source_analysis`), provenance columns on every AI artifact, deletion cascade | `tests/test_indestructible.py` provenance tests; schema registry |
| C | Staleness | **DONE** — artifacts carry the source/brief/facts revisions they were built from; CURRENT / STALE-STILL-USABLE / REBUILDING / SUPERSEDED; rebuild through the budget valve with an estimate; chats stay historical | `test_staleness_exit_criteria` |
| D | Survive interruption | **DONE** — transactional ingestion stages with resume, job leases + heartbeats, `job_events`, one findings job per source, `external_pending` re-attach (never resubmit), dependency/failure propagation, cancellation, budget/retry waits, crash matrix + 40-source crash-recovery equivalence | crash matrix + equivalence tests in `test_indestructible.py`; release-check gate “crash/recovery matrix + 40-source equivalence” |
| E | Modernise AI | **DONE** — task router (`AIRequest` → contract → provider adapter), adapters reject unsupported knobs; Sonnet 5 on rank.relevance + findings.extract (thinking disabled), 4.6 kept elsewhere by decision | `evals/ranking-compare/20260906-182701-afe6143/`, `evals/findings-compare/20260906-184147-5753ad6/`, `evals/migration-compare/20260906-190947-ff042e9/` |
| F | Deterministic AI | **DONE, Planner V3 NOT PROMOTED** — structured outputs with versioned schemas on findings.extract, rank.relevance, planner.update, discover.quick (live PASS); `_repair_json` is a fallback only; the decomposed planner failed its promotion gate and stays experimental | `evals/mission-f-closeout/20260906-205402-d2e8b74/`, `…/20260906-212919-e75e78d-resume-of-20260906-205402/` |
| G | Cut cost safely | **DONE** — Message Batches for background findings with tentative recovery (never claim by count alone), explicit transport, estimates; cache layout: Tier 1 cache-read rate 2.1% → 23.4%; chat tail breakpoint OFF by decision; ranking not batched | `evals/batch-smoke/20260907-091438-70f55c9-live.txt` (real provider, exact 50% model cost); release-check gates “cache layout: …” |
| H | Cut cost intelligently | **MEASURED, DEFERRED** — findings window pre-filter passes every quality gate (100% window recall, 12/12 nuggets, 57% skippable tokens) but loses money on the background-batch path at current prices (−15% net, 0.77× leverage vs required ≥+10% / ≥1.25×); off, no live run; ranking agreement never started | `tests/fixtures/golden/prefilter/`; `neurosearch eval --prefilter`; release-check gate “H1 prefilter economic gate still FAILS on the batch path” (it must keep failing for the feature to stay off) |
| I | Retrieval | **MEASURED, RERANKER KILLED** — hard retrieval fixture + live production-embedding baseline kept as permanent regression coverage (MRR 0.9093, R@1 86.7%, exact locator 87.2%); the Haiku candidate-only reranker held every safety gate but failed every frozen improvement gate (MRR 0.8903, R@1 83.3%, +1.67 s, +$0.0027/query); production retrieval unchanged (FTS + embeddings + RRF) | `evals/retrieval/baseline-retrieval-0.22.0+i15-live.json`, `evals/retrieval/rerank-compare-20260907-115218-live.txt`; release-check gate “retrieval regression baseline (fake tier) unchanged” |
| J | External failure | **DONE** — `safe_fetch()` boundary (pinned validated connection, per-hop revalidation, size/decoded/time limits, 16 typed block reasons; 54 tests); durable circuit breakers per provider:operation with the zero-cost `provider_wait` state (15 tests); NO_FALLBACK as a contract invariant on every AI task with requested/actual/fallback_used/reason/policy-version audit on every invocation and artifact (13 tests) | `tests/test_safe_fetch.py`, `tests/test_j2_breakers.py`, `tests/test_j3_fallback.py` |
| K | Health | **DONE (as scoped)** — Settings → Health shows database, backups, workers/leases, jobs, structured outputs, evidence, providers (breakers), network boundary, experimental flags, last release check, app version; `neurosearch doctor` is the CLI form | `db.health()`; `neurosearch doctor` |
| L | Safe change | **DONE (deterministic part), Playwright DEFERRED by decision** — `neurosearch release-check` runs pytest, Tier 1 frozen numbers, schema/contract registry, migration fixtures, crash/recovery matrix + equivalence, retrieval regression, cache-layout regression, frozen economic gates, backup→restore round trip, experimental flags off; writes a machine-readable artifact. No E2E browser suite; UI stays a single file without a build | `evals/release/` |

## Experimental-feature inventory (mirrors `release.EXPERIMENTAL_FLAGS`; `neurosearch doctor` fails if any of these is on)

| Feature | Flag | Default | Status | Evidence | Revisit condition | Deletion candidate? |
|---|---|---|---|---|---|---|
| Planner V3 (decomposed schema'd planner) | `NEUROSEARCH_PLANNER_V3` (`settings.planner_v3`) | off | **not promoted** — V1 is the production planner | `evals/mission-f-closeout/…/planner-v3.json` vs `planner-v1.json`: V3 failed its promotion gate (hard failures named in `closeout.planner_decision`) | A planner quality problem V1 cannot solve, then re-run the Mission F closeout comparison unchanged | Yes, if not revisited within two product releases — `planner_v3.py` + its schemas + `closeout.py` V3 branch |
| Findings window pre-filter (Haiku keep/uncertain/drop) | `NEUROSEARCH_FINDINGS_PREFILTER` (`settings.findings_prefilter`) | off | **deferred (economics)** — quality proven, money lost on the batch path | `neurosearch eval --prefilter`; frozen gates `BACKGROUND_MIN_NET_SHARE=0.10`, `BACKGROUND_MIN_LEVERAGE=1.25`; measured −15% / 0.77× | A Haiku-class price drop or an interactive-only findings mode; re-run `economics()` — if it passes, enable interactively first | No — keep; the module is small and the fixture is permanent regression coverage |
| Retrieval reranker (Haiku, candidates only, depth 11) | `NEUROSEARCH_RETRIEVAL_RERANK` (`settings.retrieval_rerank`) | off | **killed (measured live)** | `evals/retrieval/rerank-compare-20260907-115218-live.txt`: every frozen improvement gate failed | Only a new retrieval fixture on which the baseline demonstrably fails; never re-tune the existing comparison | Yes — `rerank.py`, the `retrieval.rerank` contract and the `search(rerank=)` path can go once `retrieval_eval.run_rerank_compare` is no longer wanted as a template |
| Chat tail cache breakpoint | `NEUROSEARCH_CHAT_TAIL_BREAKPOINT` | `0` | **off by decision** — write premium removed; no adaptive/predictive breakpoint logic allowed | Rung G cache-layout measurement (`neurosearch eval --cache-layout`) | Multi-turn chat becomes the dominant cost AND a measured session shows the write premium repaid; measure before flipping | Maybe — the env read and `qa._tail_breakpoint` are a dozen lines; delete if still off after the next cost review |
| Schema compatibility fallback (structured-output rollback hatch) | `NEUROSEARCH_SCHEMA_COMPAT_FALLBACK` | empty | **rollback-only** — never on in normal operation | Mission F: `schema_fallbacks` floor 0 in Tier 1; `_repair_json` path covered by tests | A provider-side structured-output regression; on for one release, off again | No — this is the escape hatch |
| Fake AI test mode | `NEUROSEARCH_FAKE_AI` (`settings.fake_ai`) | off | **test mode** — evals, tests, `doctor` smoke and `release-check` proofs run under it; never in production | fake-isolation lint in tests; `doctor` fails if on | n/a | No |

## Mission declaration

| Mission clause | Verdict | How it is enforced |
|---|---|---|
| survive crashes | **Met** | transactional stages, leases/heartbeats, crash matrix + 40-source equivalence (Rung D); release-check “crash/recovery matrix + 40-source equivalence” |
| survive retries | **Met** | per-contract attempt limits, typed non-transient errors never retried, `retry_after` honoured (E, J2) |
| survive provider outages | **Met** | durable breakers per operation, `provider_wait` at 0 attempts / 0 invocations / $0, automatic wake (J2); batch re-attach (G) |
| survive model changes | **Met** | contracts pin models; router with loud rejection of unsupported knobs; frozen live comparisons per migration (E); NO_FALLBACK audit (J3) |
| survive brief / source changes and re-ingestion | **Met** | revision-aware staleness states, budgeted rebuilds, project-relative analysis (B, C) |
| months of work without losing state | **Met** | verified backups, migration fixtures, backup→restore round trip in release-check (A, L) |
| without duplicating expensive work | **Met** | one findings job per source, `external_pending`/tentative batch recovery (never resubmit, never claim by count), cache layout (D, G) |
| without silently going stale | **Met** | CURRENT / STALE-STILL-USABLE / REBUILDING / SUPERSEDED on every artifact, shown in the UI (C) |
| without unexplained provenance | **Met** | model, provider, prompt/schema versions, source/brief/facts revisions, requested/actual model, fallback policy on every invocation and artifact (B, F, J3) |
| best-value model per task, proven | **Met, with three honest negatives** | Sonnet 5 adopted where it won (E); batches adopted (G); pre-filter deferred, reranker killed, Planner V3 not promoted — each on frozen gates, none re-tuned |

**Declaration:** the original hardening mission is complete. Every clause is met by a mechanism with a deterministic
test or a frozen live measurement behind it, and `release-check` re-proves the deterministic ones on demand.

**Known limitations (accepted, not hidden):**

- No browser end-to-end suite; the single-file UI is exercised by API tests and a fake-AI smoke, not Playwright.
- Provider outage handling was proven under fakes only (the live batch smoke is the only paid proof of Rung G/J).
- `safe_fetch` covers every fetch except yt-dlp, which keeps its own network stack by decision.
- The Tier 1 frozen totals are token counts from the fake provider; live Tier 2 numbers exist only as the dated
  artifacts in `evals/` and are not re-run by `release-check` (paid runs are reserved for major model or architecture changes).
- The Health console is a read-only status page; there is no alerting.
- `release-check` gates are frozen at their 0.24.0 values; changing a frozen number is itself a decision to record here.

## Post-closeout fixes

**0.36.0 — B3 candidate links (no frozen numbers changed).** New additive table `candidate_links`; the chat's `research_state` TOOL output gained a line (tool output is not in the frozen prefix; Tier 1 verified unchanged).

**0.54.0 — the model decision engine (frozen ASSERTIONS changed; frozen NUMBERS unchanged).** Fourteen tasks sat on `claude-sonnet-4-6` ($3/$15) rather than the cheaper, newer `claude-sonnet-5` ($2/$10) because E2.3's comparison was never run (line 211 above). `contracts.TIERS` + `tier_reason` now require every task to be at the cheapest tier (`claude-haiku-4-5`) or name one of `capability:` / `evidence:` / `irreversible` / `user:`; `release-check` refuses anything else. Seven tasks moved to Haiku; the rest moved 4.6 → Sonnet 5. Changed assertions: `test_core.test_router_equivalence_fake_tier1` no longer asserts "every non-migrated task follows settings.answer_model" (it asserts `policy_violations() == []` and that no task is on 4.6); `test_core.test_migrated_contracts_are_sonnet_5_thinking_disabled`, `test_claude5_contract_adapter_and_validation`, `test_contract_reproduces_0_17_3_request_shape`, `test_migration_compare_one_command` and `test_j3_fallback.test_general_task_failure_never_substitutes_sonnet5` now assert against the contract's own model rather than a hardcoded one. Tier 1 totals unchanged (answer 34 / 196,951, findings 9 / 30,297, plan 2 / 11,026) — the fake prices at list and counts tokens from text, so a tier change does not move them. `rank.relevance` was reclassified `reversible=False` mid-implementation when its own frozen tests caught the error: it selects which sources enter the corpus, so its consequences are not undoable however cheap re-ranking is.

**0.35.1 — Share ▾ (no frozen numbers changed).** New task `answer.share` (interactive); the chat prompt is untouched so Tier 1 stays 34 / 196,951.

**0.35.0 — G6P2 (no frozen numbers changed).** Role weighting applies only to platform `book` chunks; the golden fixture has none, so the retrieval baseline is unchanged. Book deep links moved from `url#href#fragment` to `#book/<sid>/<ordinal>` (in-app).

**0.34.2 — removal is a durable exclusion (`project_sources.excluded`, additive); force-clear of failed sources cancels resurrecting jobs. No frozen numbers changed.

**0.34.1 — account usage limit is a pause, not N failures (no frozen numbers changed).** Anthropic's Console usage limit (400 `invalid_request_error` naming the regain date) → SPEND_CAP → jobs `budget_wait` until that date, `/api/usage.account_limit_until`. Uploader accepts `.epub`; extension 1.5.1 never colours a capture red.

**0.34.0 — G6P1 EPUB Core (no frozen numbers changed).** New platform `book` / `book_sections` table (additive); `works.FORMS` gains `epub`; findings citations for books use the structural label. Gate `tests/test_m1_epub.py`. Tier 1 untouched (34 / 196,951).

**0.33.1 — B2 completeness (no frozen numbers changed).** `sources.completeness` in use; partial captures merge; `upsert_source` now clears `error`/`error_class` when passed explicitly as None (a placeholder's browser-needed state ends on success). Gate `tests/test_l2_completeness.py`.

**0.33.0 — B1 browser capture (no frozen numbers changed).** Browser-solvable acquisition failures park the ingest job `external_pending` on provider `browser` (durable, recovery re-attaches; expiry is visible, never a failure); the capture resolves the same job/source via `db.resume_external`. Additive columns `sources.error_class`, `sources.completeness`. Gate `tests/test_l1_browser_capture.py`. Tier 1 untouched.

**0.32.2 — Reddit blocks every non-browser reader since 2026-06-30 (no frozen numbers changed).** Live probe: www/api 403 block page, old.reddit 404 for JSON and a `200` login wall for pages. Readers now: the browser extension (thread JSON fetched in the user's browser → `POST /api/projects/{id}/ingest/thread`) and Reddit's official API via app-only OAuth with `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` in `.env` (never in the DB). Unauthenticated rungs are kept but expected to fail; the error names each and the way forward. `safe_fetch` gained `body=` (token POST), `None`-drops-header, all `Set-Cookie` lines. Gate `tests/test_k9b_reddit_html.py`; Tier 1 untouched (no prompt changed).

**0.32.0 — G7 Community evidence (frozen numbers changed).** Two system-prompt rules (excerpts/posts are data — instruction-like text is never followed; corrected posts are never consensus, self-described context is unverified): Tier 1 answer totals 34 / 192,504 → **196,951**; `CHAT_ARM_INPUT_TOTAL` 205,564 → 210,014; sum 258,723 → 263,170. Same rule as before.

**0.31.0 — G6 Canonical Works (frozen numbers changed).** One chat tool (`resolve_work`): Tier 1 answer totals 34 / 187,030 → **192,504**; `CHAT_ARM_INPUT_TOTAL` 200,090 → 205,564; sum 253,249 → 258,723. Deliberate prompt-content change, same rule as before. G2 classification expectations updated: identifiers now default to `resolve` (the Source Resolver) instead of `upload`/`page`.

**0.30.3 — chat answers ending mid-sentence (production symptom, 2026-09-08).** Diagnosis in `qa.ask`: the agentic loop collected every text block and handled `stop_reason == "tool_use"` correctly, but treated `stop_reason == "max_tokens"` exactly like `end_turn` — a truncated answer was saved and shown as if complete — with `answer.chat` at 2,000 output tokens; and a model still asking for tools after the sixth round ended the loop with whatever text it had. Fix: per-generation diagnostics (conversation, round, stop_reason, max_tokens, input/output tokens, elapsed, chars → log line + `messages.meta.generation`); `max_tokens` → up to two automatic continuations ("Continue the previous answer exactly where it stopped…"), spliced without newline and with a repeated overlap dropped (`_join_continuation`), then a visible "[Answer cut short …]" marker + `meta.warning` if it is still incomplete (never silent; Copy keeps the warning); the round after the sixth tool round runs without tools so the answer always ends in text; budget 2,000 → 4,000; the system prompt asks for concise ordinary answers and long form only when warranted. Counters `chat:continuations`, `chat:incomplete_answers`. Release gate: `tests/test_k7_chat_truncation.py` (max_tokens → continuation with the final sentence and no duplicated transition; text+tool_use → final text; dangling tool round impossible; continuation cap marks incomplete). Frozen numbers: the concise-answer line changed the cached prefix — answer 34 / 186,010 → **187,030**; `CHAT_ARM_INPUT_TOTAL` 199,070 → 200,090; sum 252,229 → 253,249. Platform fix in the same release: `schemas.clamp` — bounds the provider strips (maxItems/maxLength) clamp locally before validation instead of rejecting a paid response (0.30.2 lost an evaluation call on `missing_areas` > 8).

**0.29.0 — G5 Research Intelligence (frozen numbers changed).** Two chat tools (`research_state`, `propose_claim`) and a `Research state` line in the volatile state block: Tier 1 answer totals 34 calls / 175,395 → **186,010** tokens; `CHAT_ARM_INPUT_TOTAL` 188,458 → 199,070; sum 241,614 → 252,229. Findings, plan and retrieval baselines unchanged; cache-layout equivalence gate re-derived (the legacy block now formats the research line too). Deliberate prompt-content change, same rule as 0.24.1/0.27.0/0.28.0.

**0.24.1 — chat retrieval grounding (regression found in production use, 2026-09-07).** Symptom: five uploaded PDFs "not surfacing" in a 449-source project. Diagnosis (read-only, via the API): the PDFs were fully ingested, chunked and embedded and ranked first on matching queries; the failure was structural — every chat turn retrieved 14 excerpts from the *latest message text* only, so an 11-question message got one retrieval, meta follow-ups ("list the PDFs you see") retrieved on their own words, and the model had no inventory and no way to search again, so it described the excerpts as the library. Fix, all on the existing paths: `search_library` / `list_sources` / `set_source_priority` chat tools; library inventory in the volatile state block; project-relative priority sources with reserved excerpt slots (`search.PRIORITY_RESERVE`); follow-up query grounding without a model call; in-chat attachments read immediately through `ingest_local_file` and pinned into the same turn; embedding failure no longer fails a readable document; one-word-per-line PDF reflow. 13 new tests (263 total). Tier 1 chat totals re-frozen: answer 34 calls / 141,225 → **165,365** tokens (tool definitions + inventory; cached prefix in production), findings and plan unchanged; `CHAT_ARM_INPUT_TOTAL` 154,288 → 178,428. Recorded decision: frozen numbers changed for a deliberate prompt-content change, verified by the cache-layout equivalence gate (now derived from the live `PROJECT_BLOCK`, so the gate tests the split, not the wording).

---

# History (rung-by-rung record)

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

## Rung J — external failure (COMPLETE 0.23.0+j3)
J1 `safe_fetch.py` is the ONE boundary for ordinary URL fetching (`webpage.fetch` → pages and linked documents/PDFs); yt-dlp
stays separate by design (its own extractor/cookie/redirect logic; documented exception). Pipeline for the initial URL AND every
redirect hop: parse → http/https only → no userinfo → normalised host/port (idna, browser shorthand like 127.1 canonicalised) →
resolve A + AAAA → reject if ANY answer is unsafe → connect to the VALIDATED, PINNED address with the original hostname kept for the
HTTP Host header and for TLS SNI/certificate verification (`_PinnedHTTP` / `_PinnedHTTPS` over http.client: no second, uncontrolled
resolution between validation and the socket, so DNS rebinding cannot move the connection) → stream under limits. Blocked:
loopback, RFC1918/private, link-local, unspecified, multicast, reserved/non-global, IPv6 equivalents (::1, fe80::, fc00::/7),
IPv4-mapped and 6to4 forms, cloud metadata (169.254.169.254, fd00:ec2::254, 100.100.100.200, metadata.google.internal and friends),
localhost/.localhost/.local names, file:/ftp:/gopher:/data:/javascript: and schemeless links, embedded credentials, bad ports.
Redirects are followed manually (MAX_REDIRECTS 5, configurable) and each target revalidated; no automatic retries; no environment
proxies (the client never reads proxy variables); connect/read timeouts plus a total wall-clock deadline (60 s default, 60 s for
webpage.fetch). Sizes: an oversized Content-Length is refused before reading, the stream is counted regardless (chunked responses
too), gzip/deflate are decoded incrementally under a separate DECODED ceiling (a 30 KB → 30 MB gzip bomb stops at the ceiling),
br/zstd are refused (never requested). Limits live in ONE table by content class — html 5 MB wire / 10 MB decoded, document 60 MB /
120 MB (env-overridable) — chosen from the response Content-Type or pinned by the caller; callers never carry numbers.
Diagnostics: `FetchBlocked(reason ∈ scheme|userinfo|host|port|dns|private_address|metadata|redirect_limit|redirect_target|too_large|
decoded_too_large|encoding|timeout|connect|status|protocol)` → validation event `fetch_blocked` {reason, host, hop} + kv counter →
Health `network.fetch_blocked`; the user-facing message never names the refused address. A blocked fetch fails the job without
transport retries (by design: retrying a refused destination is pointless; a user can retry a flaky public site).
Tests (tests/test_safe_fetch.py, 54, local ThreadingHTTPServer + RESOLVER/CONNECT hooks, no real network): every private/metadata
literal and name above; mixed public+private answers; bad schemes/userinfo/ports/dns; public HTML + PDF + gzip + deflate success
through the pinned address with the original Host; redirects to private/metadata/file blocked at hop 1; redirect-chain limit;
oversized Content-Length; 12.8 MB chunked body cut off; gzip bomb; unsupported encoding; slow body vs deadline; central per-class
limits; Health recording; webpage.fetch/read_page through the boundary; HTTPS pinned connect + SNI at the unit level; and the
rebinding proof: a name answering public first and 127.0.0.1 afterwards is resolved exactly once and connected at the validated
public answer, and a redirect back to that name is revalidated and blocked.
Implementation constraints found: (1) HTTPS end-to-end is unit-tested (pinned socket + SNI), not served locally — no certificates in
the harness; (2) no outbound proxy support in this client (trust_env-equivalent off) — if proxies are ever wanted they must be added
deliberately and validated like a destination; (3) hosts with several answers are all validated and the first IPv4 answer is pinned
(IPv6-only hosts pin their v6 answer); (4) `.local` and `.localhost` names are refused by name as belt-and-braces.

### J2 — durable circuit breakers per provider:operation (0.23.0+j2)
`breakers.py` + table `circuit_breakers` (operation PK, state closed|open|half_open, consecutive transient failures, opened_at,
next_probe_at, last_error_type/at, last_success_at, probe_owner + probe_expires_at, generation, updated_at). Keys: anthropic:messages
(EVERY Anthropic message task — never per model), anthropic:batches, openai:embeddings, openai:transcription. Policy, deterministic and
small: 3 consecutive TRANSIENT failures → OPEN (generation +1; next_probe_at = the provider's retry-after when it gave one, else a
cooldown of 60 s doubling per generation up to 15 min); at next_probe_at exactly ONE worker leases the half-open probe (atomic
UPDATE guarded by generation; lease 120 s, released if the prober never reports); probe success → CLOSED + every job parked on the
operation woken; probe transient failure → OPEN again, longer cooldown; a success or failure from a stale generation is ignored;
a stray success from a non-prober does not close a half-open circuit. Wired in `providers._Ledgered` (gate BEFORE any invocation
row — a refused call costs 0 attempts, 0 invocations, $0 — every transport attempt's transient failure is counted, every real
success recorded) and `providers._GatedBatches` (Message Batches create/retrieve/results/cancel/list behind anthropic:batches;
batches.py keeps its per-item ledger). Classification (`providers.classify_error`): transient = connection, timeout, 5xx/529
overload, ordinary 429 WITH a retry window; NOT transient and never breaker input = auth, permission, billing (402 / "credit
balance"), invalid request, refusal, schema mismatch, the user's own budget pause, and SPEND_CAP = a 429 with no retry window
naming a spend/usage limit (`enforced_spend_limit_reached`) — typed failures that stop, not cycles. `retry_after_of()` honours
Retry-After (seconds or HTTP-date) as next_probe_at. Jobs: `breakers.ProviderUnavailable` (raised by the gate) or a
ProviderError whose operation is now open → `db.park_provider_wait`: status queued, wait_reason='provider', wait_operation,
not_before=next_probe_at, NO attempt counted, event `provider_wait`; derived status `provider_wait` (distinct from retry /
budget / rate-limit / dependency waits); `db.wake_provider_wait(op)` on close; lease recovery and restarts never touch it
(it holds no lease). Propagates like BudgetPaused through findings/relevance/ingest loops. Health `providers`: "Anthropic
Messages · Healthy / Waiting · provider temporarily unavailable · next check after 11:42 AM / Checking", waiting-job count;
job detail `provider_wait` = "Waiting for Anthropic Messages — provider temporarily unavailable. Next check after 11:42 AM."
(never "retry 3/3 failed: 529"). SDK retries stay off (max_retries=0) so the breaker sees every attempt.
Tests (tests/test_j2_breakers.py, 15, injected outages via `fake_ai.OUTAGES[operation]` + `FakeAPIError` shaped like the SDK's):
threshold opens only the affected operation (messages open ≠ batches, transcription open ≠ embeddings); auth / permission /
invalid / billing / spend-cap / schema-mismatch never open one; 429 honours retry-after (next probe ≈ 90 s) and spend cap is typed
SPEND_CAP; exactly one half-open probe lease, a second worker parks; probe success closes and releases two parked jobs; a
non-prober's success does not close; a failed probe reopens with generation 3 and a longer cooldown; an expired probe lease
passes to another worker; a stale generation's success is ignored; provider_wait = 0 attempts, 0 invocations, $0, plain-language
message, survives restart + lease recovery, and the parked job completes as the probe once the circuit may be tested; batch
submission parks on anthropic:batches while interactive messages still flow; Health and job diagnostics expose operation, state
and next check without provider internals.

### J3 — fallback is an explicit contract invariant (0.23.0+j3)
Every AI contract declares `fallback` (NO_FALLBACK — the only implemented policy) and `fallback_candidates` (must be empty under
NO_FALLBACK); `contracts.validate` rejects NO_FALLBACK + candidates, VALIDATED (declared but not implemented: it would need
named candidates, schema/tools/thinking compatibility, task validators, the routing decision in provenance and its own quality
gate), and unknown policies. Every existing Anthropic task — answer.chat, answer.repair, findings.extract, rank.relevance,
discover.quick, discover.verify, planner.analysis/build/update, export.synthesis, all Planner V3 components, findings.prefilter,
retrieval.rerank — plus embed/transcribe is NO_FALLBACK. `FALLBACK_POLICY_VERSION = fallback-policy-v1`.
Router invariant: there is no fallback code path. A requested-model failure — transient exhaustion, circuit open (→ provider_wait),
half-open probe failure (→ reopened breaker), auth / permission / billing / spend cap / invalid request (→ typed failure), refusal or
schema mismatch (→ typed OutputError / SchemaMismatch) — never substitutes another model; Sonnet 5 findings/ranking never fall back
to settings.answer_model and 4.6 tasks never fall back to Sonnet 5. An explicit per-task override (NEUROSEARCH_TASK_MODEL_*) IS
the requested model, not a fallback.
Provenance: `providers.routing_for(task, actual_model)` → {requested_model (the model Neuro Search intentionally selected: contract
+ explicit override), actual_model (what the provider reported — a versioned snapshot of a requested alias is NOT a fallback),
fallback_used (False: the router's only decision), fallback_reason (null on the normal path), fallback_policy, fallback_policy_version}
stored as JSON `routing` on project_source_analysis, project_notes, plans (V1 and V3) and discoveries; invocations carry
`fallback_used = 0` and `fallback_policy_version` on every row, with `model` = requested and `returned_model` = actual.
Tests (tests/test_j3_fallback.py, 13): every contract explicit + contradictory configs rejected; Sonnet 5 findings failure never asks
4.6 (and writes no artifact); ranking Sonnet 5 failure never substitutes; 4.6 chat failure never asks Sonnet 5; open circuit parks
with zero invocations; auth / billing / spend cap / invalid request typed, same model only; refusal + schema failures same model only
(reranker refusal → original ordering); explicit override = requested model, fallback_used False; versioned alias → actual_model,
fallback_used False; every artifact table and every completed invocation carries the audit; no automatic-fallback symbol exists in providers.
**Rung J: COMPLETE (0.23.0+j3)** — the network boundary, durable per-operation circuit breakers with a zero-cost provider_wait, and an
explicit no-fallback routing invariant with full audit. Discover-verify already holds rather than falls back.

## Rung I — retrieval (COMPLETE 0.22.0+i3: hard baseline kept; reranker measured live, NOT adopted; retrieval unchanged)
Premise (Kyle): retrieval is already strong on the golden questions (R@10 100%, R@5 96.9%, MRR 0.922, locator 80% in Tier 1), so a
reranker is an EXPERIMENT with a hard kill gate — first prove there is headroom. I1 = a harder frozen fixture that exposes ordering
and localisation mistakes Recall@10 hides. `tests/fixtures/golden/retrieval/` (build.py, committed): four distractor sources added
to the golden project — pop_weak (popular, vague, partly wrong: "five percent down", "personal guarantee is a myth", "closing in
thirty days", "rebrand and raise prices"), dscr_numbers (1.20 / 1.15 / 1.25 / 1.35 / 1.10 / 1.5 for different loan products in
neighbouring chunks), startup_wc ("working capital" as runway, "peg your valuation"), hvac_ops ("standby" generators, service
"notes", parts "seller", "first ninety days" for new hires) — and 30 queries in six categories (authority, numeric, contradiction,
terminology, buried, same_concept) graded per source AND per chunk locator (±120 s media / exact page), with hard negatives
(a hard-negative source ranking above the first expected hit = a false positive). Two "reverse" queries make the distractors the
answer so the grading cannot be gamed by down-weighting them.
`neurosearch eval --retrieval [--baseline]` (`retrieval_eval.py`) runs PRODUCTION `search.search` (FTS5 + vectors, RRF, per-source
cap — untouched) and reports Recall@1/3/5/10, candidate Recall@40, MRR, NDCG@10, expected-source mean/median first rank, locator
accuracy, exact-locator-at-first-hit, hard-negative false positives, per-category breakdown, the mistakes, and per query the
top-40 candidate set (this corpus fuses 7–18 candidates per query) — the ONLY thing I2 may reorder. `retrieval_eval.compare`
tracks per-query rank changes, improved/worsened/same and top-10 overlap. Baseline frozen at evals/retrieval/
baseline-retrieval-0.22.0+i1-fake.json and asserted by `test_retrieval_baseline_is_frozen`.
Baseline (fake tier = FTS + the fake's hashed lexical vectors; 2 ms/query):
  R@1 80.0% · R@3 93.3% · R@5 96.7% · R@10 100% · candidates@40 100% · MRR 0.8736 · NDCG@10 0.8155 · first rank mean 1.5 / median 1 ·
  not-first 6/30 · locator 94.9% (any top-10 hit) · exact locator at the source's first hit 82.0% · hard-negative FPs 2 (2 queries).
  by category: authority R@1 66.7% MRR 0.743 (2 HN-FPs: pop_weak outranks yt01/yt03 on "first ninety days" and "closing in thirty
  days" — the distractor literally contains the query's words); buried R@1 60% MRR 0.750 (off-market deals: startup_wc/hvac_ops
  first; building on a longer term: yt01 first); terminology exact locator 62.5% ("seller stay on": article first); numeric and
  contradiction 100% R@1; same_concept R@1 87.5%.
Headroom (ceilings if ordering were perfect within the retrieved candidates — candidate recall is 100%, so a reranker CAN reach
them): MRR +0.126 (6.3× the +0.02 adoption bar), R@3 +6.7 pp (one miss is all the slack against the +5 pp bar), exact locator
+18 pp (the +10 pp bar is reachable), 2 hard-negative FPs to zero. So there IS headroom — concentrated in six queries.
Two honest caveats before I2: (1) this baseline is FTS + LEXICAL fake vectors; real text-embedding-3-small already resolves some
of these lexical failures, so the live baseline (embeddings only — no Anthropic calls, cents) is the real reference and the fake
can only prove a reranker's mechanics (candidate-only, deterministic fallback, provenance, rank-change tracking), never its
quality; (2) there is no reranker in the current provider set — an LLM listwise rerank on Haiku over ~15 truncated candidates
per chat turn is ≈ 2–4k input tokens ($0.002–0.004) and ~1–2 s of added latency per question, which the cost/latency gate must
weigh against a retrieval layer that is already right first time 80% of the time on the hard set and 92%+ on the golden set.
I1.5 (0.22.0+i15): the real-embeddings baseline — `neurosearch eval --retrieval --live --baseline` runs the SAME frozen fixture through
production chunking, FTS5 and text-embedding-3-small (OPENAI_API_KEY only; the report asserts `anthropic calls 0`; ≈ 30k embedding
tokens ≈ $0.001) and saves evals/retrieval/baseline-retrieval-<version>-live.json. Decision gate FROZEN before the result (Kyle,
`retrieval_eval.GATE`): build I2 only if candidate recall stays 100% AND at least one of MRR headroom ≥ 0.03 · R@3 headroom ≥ 5 pp ·
exact first-hit locator headroom ≥ 10 pp · ≥ 2 ordering/hard-negative mistakes whose target is in the candidates; else close Rung I
and keep the fixture as the permanent regression test. The report also gives the candidate position of every first expected
target and the smallest rerank depth that preserves 100% candidate recall (+2 margin) — I2, if built, reranks that many, not an
assumed 15. Fake-tier reference: deepest target position 8 → depth 10; gate passes on every criterion (that is the lexical-vector
headroom the live run will confirm or shrink).
I1.5 LIVE RESULT (b5768c0, evals/retrieval/baseline-retrieval-0.22.0+i15-live.json, text-embedding-3-small, anthropic calls 0, 22k
embedding tokens ≈ $0.0004): R@1 86.7% · R@3 93.3% · R@5 93.3% · R@10 100% · candidates 100% · MRR 0.9093 · NDCG@10 0.8501 · exact
first-hit locator 87.2% · hard-negative FPs 1 · not-first 4 · deepest expected target at candidate position 9. Gate: MRR headroom
+0.0907 ✓ · R@3 +6.7 pp ✓ · exact locator +12.8 pp ✓ · 4 fixable ordering mistakes ✓ → BUILD I2 at depth 11 (9 + 2 margin).
Numeric, buried and contradiction queries are solved; the remaining mistakes are authority ("first ninety days" → yt02 first,
"closing in thirty days" → rank 8 with pop_weak above), same_concept ("assignable" rank 5, "lender documents" rank 1) and
terminology localisation ("seller stay on" exact 0/2).
I2 built (0.22.0+i2; OFF by default, NEUROSEARCH_RETRIEVAL_RERANK=1; no live run yet): `rerank.py` — contract `retrieval.rerank`
(`contracts.RERANK_MODEL` claude-haiku-4-5, thinking off, 120 output tokens, ONE attempt, 20 s timeout, schema `retrieval-rerank-v1`
= {order: [candidate numbers]}), `RERANK_DEPTH = 11`, `TEXT_CHARS = 700` per candidate (title, channel, locator, text). `search.search(...,
rerank=)` reorders the first 11 hits and leaves the tail in RRF order; the result is validated as an exact permutation of 1..n
(duplicates, omissions, unknown or non-integer numbers, refusal, truncation, schema mismatch, provider error, budget pause or any
exception → the RRF ordering, byte for byte, plus `rerank_fallback` event/counter → Health `rerank`). Reordered hits carry
`rerank = {from, to, version, model}`; usage kind `rerank`. FTS, embeddings, RRF weights, chunking, candidate generation, answer
prompts and downstream K are untouched. Fake: `fake_ai._rerank` (question-word overlap; knobs NEUROSEARCH_FAKE_RERANK=identity|
reverse|dupes|missing|unknown|garbage|refuse|error|truncate) proves containment, permutation validation, every fail-closed path,
provenance and accounting — never quality. Under the fake the comparison correctly returns KILL.
`neurosearch eval --retrieval --rerank [--live]` (`retrieval_eval.run_rerank_compare`): baseline and candidate on the SAME database and
candidates; per-query before/after rank, exact locator and hard-negative FP; improved/worsened/unchanged; top-11 overlap;
containment and fallback-restores-ordering checks on every query; latency, tokens, cost per query (as billed and at the
configured model's list price); artifact evals/retrieval/rerank-compare-<stamp>-<tier>.{json,txt}. Adoption rule FROZEN
(`LIVE_BASELINE`, `HARD_GATES`, `MEANINGFUL`, `FIXABLE_IMPROVED_MIN`): hard — R@10 100%, candidate recall 100%, exact locator ≥ 87.2%,
hard-negative FPs ≤ 1, candidate set unchanged on every query, every fallback restores the original ordering; meaningful — at
least one of MRR ≥ 0.9293, R@3 ≥ 98.3%, exact locator ≥ 97.2%; and ≥ 2 of the 4 fixable ordering mistakes improved. Verdict ADOPT
or KILL. One live comparison, then a decision; no repeated tuning to the fixture.
LIVE RESULT (0e3118a, evals/retrieval/rerank-compare-20260907-115218-live.{json,txt}): **KILL.**
  baseline production retrieval: R@1 86.7% · R@3 93.3% · R@5 93.3% · R@10 100% · candidates 100% · MRR 0.9093 · NDCG@10 0.8501 ·
    exact first-hit locator 87.2% · hard-negative FPs 1
  Haiku reranker (depth 11): R@1 83.3% · R@3 93.3% · R@5 96.7% · R@10 100% · candidates 100% · MRR 0.8903 · NDCG@10 0.8501 · exact
    locator 92.3% · hard-negative FPs 0 · 3 queries improved, 4 worsened, 23 unchanged · 3 of the 4 known fixable mistakes improved ·
    +1.67 s mean latency per query · $0.00270 per query · 0 fallbacks.
  It held every hard safety gate and fixed some edge cases (the hard-negative FP, +5.1 pp exact locator) but failed EVERY frozen
  meaningful-improvement gate (MRR ≥ 0.9293 ✗ · R@3 ≥ 98.3% ✗ · exact locator ≥ 97.2% ✗) and worsened Recall@1 and MRR (−0.019).
  The added model call, latency and cost are not justified. No tuning, no rerun, no depth or prompt change, no other reranker.
Decision (Kyle): production retrieval stays FTS5 + text-embedding-3-small → RRF → existing top-K. `retrieval.rerank` stays OFF
by default; the implementation and its tests remain behind the flag as the measured record. The hard fixture and the live
production-embedding baseline are permanent regression coverage (`neurosearch eval --retrieval`, `test_retrieval_baseline_is_frozen`).
Known remaining weaknesses, monitored rather than patched: authority discrimination, a few same-concept ordering cases,
terminology localisation.
**Rung I: COMPLETE — RERANKER MEASURED, NOT ADOPTED (0.22.0+i3).** No further live testing is required.
 behind a pluggable stage (off = today's ordering byte-for-byte), deterministic
fallback on any failure, provenance (reranker version), adoption gate = R@10 not down, every golden evidence target reachable,
zero citation/evidence regressions, locator not down, AND MRR ≥ +0.02 or R@3 ≥ +5 pp or locator ≥ +10 pp — else kill. Downstream
context reduction (top 10 → top 5) is a separate follow-up experiment, not part of I2.

## Rung H — cut cost intelligently (H1 findings pre-filter built under fakes, 0.21.0+h1; not yet enabled, no live run)
Scope decision (Kyle): the findings window pre-filter first — findings carries large transcript windows into Sonnet 5; ranking is
cheap and performing, so two-pass ranking agreement is deferred. Design: a conservative REJECTION filter, never a findings
generator, never a source-quality score. `findings.prefilter` contract (`contracts.PREFILTER_MODEL` claude-haiku-4-5, thinking off,
200 output tokens, schema `prefilter-v1` = {decision: keep|uncertain|drop, reason}) answers one question per window: does this
window have ANY plausible value to the brief? keep → findings.extract · uncertain → findings.extract · drop → skipped. Any
provider error, timeout, refusal, truncation, malformed/invalid output or unexpected exception fails OPEN to `uncertain` (event
`prefilter_fail_open`, kv counter, Health). Off unless NEUROSEARCH_FINDINGS_PREFILTER=1; the unfiltered path is the rollback;
findings.extract itself is untouched (Sonnet 5 remains the extractor). Auto-analysis, interactive and batch transports all go
through `findings.window_plan` → kept window indexes keep their original numbering (custom_ids and prompts of kept windows are
byte-identical to the unfiltered path; a batch source with non-contiguous kept windows materialises normally).
Provenance + invalidation: `window_decisions` rows keyed by input hash = window text + brief revision + prompt version + schema +
configured model + sample size (a change to any re-evaluates; same inputs reuse the stored row, no second call); decision, reason,
fail-open reason, configured/returned model, tokens, cost; the analysis row's `prefilter` column summarises keep/uncertain/drop/
fail_open/model/prompt/schema/cost per source. Anomaly signal: a source losing ≥80% of ≥3 windows → `prefilter_aggressive` event +
counter → Health `prefilter.aggressive_sources_flagged` (flagged, never overridden — no hidden quota).
Labeled window fixture (`tests/fixtures/golden/prefilter/`, generated by build.py, frozen by test): the golden project's 10 windows
(vlog + sourdough irrelevant) + beekeeping (2 long irrelevant windows), marathon (1 long irrelevant), mixed (window 0 restaurant
marketing = irrelevant; window 1 the owner's acquisition story with a planted seller-transition nugget), tangent (one 28k-char window
that is 95% rambling with ONE buried working-capital-peg nugget — the hard recall case). 16 windows, 10 relevant, 12 planted
nuggets (10 golden + 2 new), 348k chars. Gates on this small fixture are absolute — 100% relevant-window recall, 0 false negatives,
every nugget's window kept, no relevant source emptied, evidence recall with the filter ≥ without — and are NOT a statistical
99% claim; the labeled set grows before that is said.
`neurosearch eval --prefilter` (fakes; the fake filter is lexical on the brief's vocabulary and blind to the labels — it reads only the
prompt) measures per mode: keep/uncertain/drop, fail-open, recall, FN, nuggets reachable, sources emptied, windows and extractor
tokens skipped, filter tokens/cost (Haiku list price), avoided extractor cost (Sonnet 5 list price incl. ~600 output tokens/window),
NET saved, leverage = avoided / filter cost, evidence recall with the filter, returned model, contract provenance. Verdict = the
production mode (`prefilter.SAMPLE_CHARS`, default 0 = whole window); other modes are experiments.
Measured (0.21.0+h2, fakes, CURRENT list prices — Haiku 4.5 $1/$5, Sonnet 5 $2/$10 per Mtok, Message Batches ×0.5 — against the
transport the product would actually have used; `usage.PRICES` corrected from Haiku $0.8/$4):
  quality (whole window, production mode): keep 7 · uncertain 3 · drop 6 · fail-open 0 · recall 100% · FN 0 · nuggets 12/12 reachable ·
    no relevant source emptied · windows skipped 6/16 (38%) · extractor input tokens avoided 56,952/99,222 (57%) · filter spent
    95,690 in / 323 out · tangent → uncertain (kept), mixed → [drop, keep], beekeeping → [drop, drop]. All quality gates PASS.
  interactive bulk (Haiku standard + Sonnet 5 standard on kept  vs  Sonnet 5 standard):  baseline $0.2944 → $0.2418 · NET +$0.0526
    (+17.9%) · leverage 1.54× · break-even irrelevant token share 33%.
  background bulk (Haiku standard + Sonnet 5 BATCH on kept  vs  Sonnet 5 batch):  baseline $0.1472 → $0.1696 · NET −$0.0224 (−15.2%) ·
    leverage 0.77× · break-even irrelevant share 66% — batched Sonnet 5 costs the same per token as standard Haiku, so the filter is
    a second full read of every window at the extractor's own batch rate. FAILS the ≥10% / ≥1.25× gate.
  background, filter itself batched (Haiku batch + Sonnet 5 batch on kept  vs  Sonnet 5 batch):  $0.1472 → $0.1209 · NET +$0.0263 (+17.9%) ·
    leverage 1.54× · break-even 33% — but TWO sequential provider batches (the findings batch can only be formed after the filter
    batch ends), each up to 24 h. Clears the numbers on this 57%-irrelevant fixture; does not clear "no pathological latency".
  sampled 8,000 chars (experiment): +38–48% on every path — and misses the buried tangent nugget (FN 1). The quality gates refuse it.
Recommendation (0.21.0+h2): **DEFER / KILL H1 as a production feature — do not run a live comparison.** Rung G moved the bulk
workload to batching, where the filter's only single-stage configuration loses money below a 66% irrelevant share; the two-stage
configuration pays only for corpora ≥33% irrelevant by tokens and doubles the worst-case latency. The interactive path saves ~18%
on such corpora, but G2 recommends background for anything ≥ BULK_THRESHOLD_ITEMS windows, so "interactive bulk" is the
override case, not the product's path; and the ranking step already removes most off-topic candidates before ingestion, so real
corpora are unlikely to reach a 33% irrelevant share. The code stays (off by default, fail-open, fully tested, fixture + eval
frozen) as the measured record; revisit only if (a) a cheaper filter model or a batch-native filter changes the price ratio, or
(b) a measured bulk ingest shows ≥40% irrelevant tokens after ranking. `neurosearch eval --prefilter` now reports the economic
gate beside the quality gates and returns FAIL for the production mode — by design.
Ranking agreement (the other H item) stays deferred: ranking is cheap and Sonnet 5 ranking is performing.

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


## 0.38.0 — L1 local provider: what is and is not frozen

Tier 1 totals (34 / 196,951 etc.) are per task and prompt, not per provider, and remain frozen; the fake local provider answers with the same fixture outputs. The ledger's `saved` on `transport='local'` rows ("avoided spend") is NEW and UNFROZEN — informational, priced at the contract's API model. The default profile is cloud, so no live behaviour changed at 0.38.0. Not yet recorded: the CLI model each task actually ran on and its timings (first live run on the Mac), and Golden-Project quality with the local provider (run `neurosearch eval` under `NEUROSEARCH_AI_PROFILE=local`, unfrozen).


## 0.56.2 — changed assertion (recorded)

`tests/test_r9_claims_arm.py::test_the_candidate_model_actually_reaches_this_command`
`len(arms["planner"]) == 3` → `== 2` for a **Haiku** candidate, plus a new `== 3` assertion for a Sonnet 5 candidate.

The old assertion was wrong, not merely outdated: with `candidate="claude-haiku-4-5"` it asserted the existence of a
`candidate-adaptive` arm that `contracts.validate` refuses on sight (adaptive thinking is Claude 5 only). It passed
because `task_arms` built the arm unconditionally and nothing constructed its contract until the live run reached it —
which is precisely how the first live Haiku comparison died after paying for two planner arms. Three arms is a fact
about the candidate model, so the test now asserts it against both kinds of candidate.

Live evidence bought before that crash (kept — the per-arm JSON survived at
`evals/migration-compare/20260909-180341-b9dc1d0/`): baseline `claude-sonnet-4-6` vs candidate `claude-haiku-4-5` on
the planner, $0.39 total.

| | rubric | structure | refs | repaired | truncated | cost | s |
|---|---|---|---|---|---|---|---|
| planner.analysis · sonnet-4-6 | 1.0 (11/11) | 1.0 | 80 | 0 | 0 | $0.1060 | 111.8 |
| planner.analysis · haiku-4-5 | 0.909 (10/11) | 0.875 | 60 | 1 | 1 | $0.0440 | 84.8 |
| planner.build · sonnet-4-6 | 1.0 (24/24) | 1.0 | 44 | 0 | 0 | $0.1538 | 178.3 |
| planner.build · haiku-4-5 | 0.958 (23/24) | **0.5** | 84 | 1 | 1 | $0.0878 | 173.5 |

Haiku is ~2.4× cheaper and ~1.3× faster, and its rubric score is within tolerance (`RUBRIC_TOLERANCE` 0.10) on both
tasks. The failure is STRUCTURAL, not judgemental: both Haiku passes hit `max_tokens` (7,000 then 16,000) and needed
JSON repair, and the repaired `planner.build` lost `this_week`, `open_questions`, `refine_questions` and `gotchas`
entirely — `structure 0.5`, four sections at 0 items. The plan it produced reads as competent and is missing half its
scaffolding. n=1, and the planner is held at Sonnet 5 by a `user` reason (Kyle's), so this changes no default; it does
say that any future Haiku planner arm needs a much larger `max_output_tokens` before its quality can be judged at all.


## 0.56.3 — the second live Haiku attempt, and why it was also invalid

Stopped by Kyle mid-run on the evidence below. Spend before the stop: the planner arms on the API (real), everything
local at $0.

```
[planner.update · baseline]  9 updates · $0.0000 · 86.93s · returned claude-haiku-4-5-20251001
[planner.update · candidate] 6 updates · $0.0000 · 41.31s · returned claude-haiku-4-5-20251001
```

The baseline arm asked for `claude-sonnet-4-6`. Both arms ran Haiku, locally, for free. `.env` carries
`NEUROSEARCH_AI_PROFILE=local`, so `providers.route` sent every `local_capable` task to Claude Code, and the CLI
served a model neither arm requested. Three consequences, in increasing order of seriousness:

1. `planner.update` compared one model against itself.
2. `claims.extract` — the arm the run exists for — is `local_capable` and would have done the same.
3. `findings.extract` is `local_capable` too, so the **shared frozen inputs** were written by local Haiku while the
   report recorded them under the production Sonnet 5 contract. 58 approved findings this run against 60 in the
   previous one is that non-determinism showing.

Fixes: the comparison pins its transport (`_force_api_transport`) and checks every arm's returned model
(`_assert_arm_model`, fails on the first offender rather than at the verdict).

The wider finding is not about the eval. `providers.routing_for` had recorded `actual_model` since L1 and set
`fallback_used: False` unconditionally, so a provider returning the wrong model looked exactly like a provider
returning the right one. The app has no substitution path of its own — every mismatch therefore comes from outside
it, which is precisely what nobody was watching for. `model_mismatch` on the artifact, a kv counter, a `health()`
section and a `release-check` warning close that. **Open question for Kyle's live database:** whether
`findings.extract` and `claims.extract` have been running on local Haiku in normal use while their contracts pinned
Sonnet 5 — the new counter answers it going forward, but says nothing about work already done. `HANDOFF.md` carries
this as an open debt.


## 0.57.0 — research catalogues (Crossref + OpenAlex)

Added on Kyle's request after a friend sent a list of scholarly APIs. Two things in that list were out of date and
one was a trap:

- **OpenAlex is no longer keyless.** Since 2026-02-13 a free key is required; the `mailto` parameter and the polite
  pool were retired for credit-based limits, and an unkeyed caller gets 100 credits and then HTTP 409. So
  `available()` reports it off without a key instead of discovering this mid-query.
- **Semantic Scholar's "no key needed" is theoretical.** Independent measurement (2026-08) found the unauthenticated
  pool returning 0/6 successes on `/paper/search` and 1/6 on `/paper/batch`; the advertised 1,000 req/s is shared
  across every anonymous caller on earth. A key buys a guaranteed 1 req/s. Not implemented: it overlaps OpenAlex
  almost entirely and would be the slowest path for the least new coverage.
- **Scopus / Web of Science** are subscription-only. Skipped.

The build is cost-NEGATIVE for Discover: `discover` proposes sources from a model's memory and then pays
`discover.verify` (web-search tool) to check they exist. A catalogue record exists by construction, so those results
skip the verify pass entirely.

### Two mistakes caught by the frozen gates

1. **The catalogue step was put on the internal escalation path.** `pursue(external=False)` is what the UI labels
   *"Search my existing research … No web search"*, and `tests/test_k6_claims.py::test_g5_acceptance_gate_end_to_end`
   freezes that sequence as network-free. A free request is still a request, so the step moved to the external path,
   where it runs *before* the paid Discover job. The frozen assertion was preserved, not edited — it was right.
2. **A recorded-but-skipped step was reported to the user as checked.** `research_view.questions` listed the raw
   word `catalogue` in `already_checked` even for questions the catalogue was never queried for. The existing
   `external` filter was generalised to every optional step, and the label map gained a plain-language entry. The
   escalation record still keeps skipped steps with their reason — that is diagnostics; `already_checked` is a claim
   to the user, and it now only claims what happened.

Gate `tests/test_s2_scholar.py` (31 tests, all against a canned `safe_fetch` — no network anywhere). 633 passed,
Tier 1 PASS, frozen totals unchanged.


## 0.58.1 — changed frozen values (recorded): the findings cap

`findings.CAP_BASE` 12 → **20**, `CAP_PER_WINDOW` 8 → **12**, `CAP_MAX` 120 → **200**, all now env-configurable with
the old trio kept as `CAP_DEFAULTS_BEFORE`.

**Why the old numbers were not load-bearing.** The cap was doing two jobs. Stopping a book from burying a project in
900 notes is real and is kept. Quality control is the other, and the cap was never equipped for it: it withheld
findings *already paid for* (`reserve`) on the basis of source LENGTH, which correlates with nothing about whether a
finding is any good. 0.58.0 built the check that answers that question, so the cap goes back to one job.

**The measurement that says 12 was too low.** From the live-database audit the same day (see the 0.56.3 entry),
length-matched to 10–40 minute sources: Haiku wrote 15.6 findings per source, Sonnet 5 wrote 11.3, and the raw 8×
`reserve` gap (11.5% vs 1.4%) collapsed to 0.6% → 1.1% once source length was controlled. A base of 12 was clipping
ordinary sources, not only books.

**Why raising it is safe.** `select_findings` is monotone in the cap — a larger cap moves rows from `reserve` into
`suggested`, never the reverse, and never loses one (`test_raising_the_cap_only_ever_adds`). Nothing already stored
moves. And it is reversible with no code change:
`NEUROSEARCH_FINDINGS_CAP_BASE=12 NEUROSEARCH_FINDINGS_CAP_PER_WINDOW=8 NEUROSEARCH_FINDINGS_CAP_MAX=120`.

### Three D1 tests re-framed, not deleted

`tests/test_n3_deep_findings.py`: `test_cap_grows_with_length_and_is_bounded`,
`test_one_window_source_is_exactly_the_old_top_twelve` (renamed `..._the_top_cap_by_importance`) and
`test_short_source_has_no_reserve_and_unchanged_count` asserted the literals 12 / 20 / 36 / 120. What the D1 rung
actually froze is the SHAPE — one window is the base, each further window adds the increment, a long source
saturates at the max, a one-window source is the top-N by importance — and the numbers were incidental to it. The
tests now assert the shape against the constants, so tuning the cap does not re-break them and a change to the shape
still does. Tier 1 frozen totals unchanged (the cap governs how many findings are KEPT, not how many calls are
made); `Tier 1: PASS`.


## 0.58.6 — the trash filter, calibrated against the live corpus (and two bugs only real data could find)

F1 shipped in 0.58.0 with two guessed constants. Both were wrong, and the suite could not tell, because a fixture
with three findings exercises neither. Measured read-only from the app's own hourly backup
(`data/backups/neurosearch-20260909-2229.db`) — the live database was never opened.

**Finding 1: the filter found essentially nothing.** 4 of 12,614 approved findings vacuity-flagged (0.03%), 0
duplicates. The vacuity result turned out to be CORRECT — sampling twelve findings at random shows Kyle's are
specific and substantive (median 189 characters, e.g. *"Total project cost includes not just the purchase price but
working capital and SBA/due diligence fees, so the 10% is calculated on that combined figure"*). There is no filler
to catch. That is worth knowing on its own: the trash problem was never vacuous findings.

**Finding 2: `CLUSTER_MAX = 400` made duplicate detection useless at the only scale that matters.** It compared the
first 400 findings of a project. The 10,380-finding project contains, demonstrably, hundreds of duplicates —
including two byte-identical pairs — and the filter reported zero. Replaced by blocking: pairs are only considered
when they share a content word whose document frequency is at or below `BLOCK_DF_SHARE` (2%) of the project, with
one code path and a small-project escape (`BLOCK_MIN_NOTES` 600, below which everything is compared, because with
five findings every word looks common).

**Finding 3: `NEAR_JACCARD = 0.62` was far too strict.** Distribution over ~13k candidate pairs: median 0.031,
p95 0.152, p99 0.348. Sampling the bands:

| jaccard band | pairs | what the samples are |
|---|---|---|
| ≥ 0.62 | 18 | duplicates |
| 0.45–0.62 | 48 | duplicates |
| 0.35–0.45 | 67 | duplicates — "up from $1.25 million" vs "Increased from $1.25 million"; two orderings of the same passive-loss rule |
| 0.25–0.35 | 151 | **mixed** — "high-risk industries get worse credit access" vs "the six-digit industry code affects loan approval" share vocabulary and say different things |
| containment ≥ 0.85, jaccard < 0.45 | 90 | duplicates, incl. a jaccard of 0.12 (a short restatement of a long finding) |

So the boundary is **0.35**, measured; `CONTAIN_RATIO` 0.85 is kept because it catches real duplicates Jaccard
misses. `PAIR_BUDGET` raised 400k → 8M: at 400k the pass logged that it was partial and returned 78 duplicates,
which is exactly the quiet half-answer this codebase refuses. It converges at **192 duplicates in 169 groups
(1.8% of the project), in 3.8 s**, so `review()` is now cached on `db.project_view_revision` per `cache.py` —
revision, never a clock.

**What Kyle should take from this:** his findings are not full of trash. 1.8% are genuine repeats worth clearing
(the biggest group is four restatements of the same FICO SBSS pre-screen fact from four videos), and the mechanism
now exists for when 0.58.1's higher cap increases volume. The number to watch is the duplicate rate as the cap
takes effect, not the vacuity rate.


## 0.58.7 — the capability profile, calibrated (same class of error as 0.58.6)

`CREATOR_STRONG_PER_SOURCE = 8.0` shipped in 0.58.2 as a guess. Measured read-only against the live backup:

| project | creators | per-source median | p75 | max |
|---|---|---|---|---|
| I want to start buying businesses… | 112 | 12.0 | 19.0 | 48.2 (Walker Deibel, 771 findings / 16 sources) |
| Design beautiful and modern web apps… | 17 | 6.1 | 9.8 | 13.7 |
| Real Estate Investment Strategy | 9 | 9.4 | 11.0 | 11.4 |

An absolute bar of 8.0 therefore marked **nearly all 112** creators "proven" in one project and a handful in
another — it was measuring the domain, not the source. `proven` is now the project's own top quartile over creators
with ≥3 read sources and ≥10 findings: 13 of 112, 3 of 17, 1 of 9. Self-calibrating, always identifies someone (a
bar nobody clears is not a bar), and explainable — "gives you more per video than three quarters of your sources".

Two ranking defects the same measurement exposed:

- **A rate projected from one source.** "Acquiring Minds — 1 video read, 24 findings" was producing *"reading the
  next 10 would be worth roughly 240 findings"*. `expected_findings` is now null below 3 read sources, with the
  reason stated in the row.
- **The unread pile outranking measured yield.** The untapped bonus was up to +15 on a `left // 10` scale, which
  saturated for every creator with 150+ unread — and many sit at exactly 380 (a listing artefact), so it ordered by
  noise. Capped at +8 on `left // 25`: a tie-break, not a reason. A large remainder is not evidence it is worth
  reading.

Gate additions in `tests/test_s4_source_capability.py`: the relative bar, the one-lucky-source case, no projection
from a thin sample, and yield outranking pile size.


## 0.58.8 — paraphrases, and the honest floor of a lexical filter

Chasing an implausibly clean number. F5 reported **all 571** withheld `reserve` findings as promotable with **zero**
overlapping an approved finding. Zero is a strong claim, so it was checked by hand instead of trusted — and it was
wrong in the way that matters. Scanning reserve against approved findings *from the same source*, the most similar
pairs are unmistakably the same fact:

```
J=0.10  RESERVE : SBA loan repayment data shows acquired small businesses have a 95%+ five-year success rate…
        APPROVED: SBA loan repayment data confirms acquired small businesses succeed at 95%+ over 5 years…
J=0.06  RESERVE : Posting regular progress updates on LinkedIn/Facebook/Instagram/Twitter attracts investors…
        APPROVED: Posting real-time updates on LinkedIn, Facebook, or Instagram about the buying process draws…
```

**Diagnosis:** 3-gram shingles catch near-VERBATIM repeats and miss PARAPHRASES, because a 3-gram of content words
rarely survives a reordering. The approved-vs-approved duplicates found in 0.58.6 were near-verbatim (the model
producing almost identical text from different videos); reserve-vs-approved pairs come from the SAME generation pass
and are reworded, so they scored 0.06–0.10.

**Fix:** a set (bag-of-words) Jaccard alongside, `SET_JACCARD = 0.50`. Sampled bands on the live corpus:

| set-jaccard | pairs | verdict on the samples |
|---|---|---|
| 0.55–0.65 | 189 | true duplicates |
| 0.45–0.55 | 352 | true duplicates |
| 0.35–0.45 | ~500 | mostly true |
| 0.30–0.35 | 856 | **mixed** — two DIFFERENT off-topic videos, each described as off-topic, score 0.33 |

0.50 is the conservative pick: a false duplicate costs a real finding. Effect: **192 → 441 duplicates (1.8% → 4.2%),
360 groups, 5.0 s.** The set measure alone is worth 249 of them.

**The floor, now published rather than left to be discovered.** The three hand-found duplicates above score 0.33,
0.20 and 0.18 on set-Jaccard. No lexical threshold separates them from findings that merely share vocabulary, so
`review()["limits"]` states that this is a floor on the duplicates present and never a ceiling, and `promotable()`
warns to skim before approving in bulk. Catching paraphrases properly needs embeddings — one call per finding,
about $0.013 for 13,000 findings. That is now a costed decision for Kyle rather than an assumption in either
direction.

**And the corrected F5 answer:** of 541 withheld findings, 1 duplicates something approved. The cap really did
withhold different facts rather than restatements, so promoting them is close to free value — with the paraphrase
caveat attached.


## 0.59.1 — the cause: Neuro Search was handing its own API key to the Claude Code CLI

0.59.0 measured the symptom ($210.55 of "free" local calls inside a $312.40 month the app reported as $111.96) and
made local calls count as spend. This is the cause, and it is one line.

`config.py` calls `load_dotenv()`, which copies every entry in `.env` — including `ANTHROPIC_API_KEY` — into
`os.environ`. `claude_code._run` then built the subprocess environment as *everything except `NEUROSEARCH_*`* and
handed it to the `claude` binary. The CLI prefers an API key when it is given one, so **every local call was billed
to the API account, and `claude login` could not have fixed it — the app overrode the login on every invocation.**

`_run` now subtracts `CLI_CREDENTIAL_VARS` (`ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `CLAUDE_API_KEY`,
`ANTHROPIC_ADMIN_KEY`). The CLI falls back to its own stored auth, which is the subscription. If there is no login
the CLI errors, `_run` raises `LocalUnavailable`, and `providers.route` falls back to the API — where the call is
recorded as real spend. The failure mode is *visible and paid*, never *hidden and paid*.

`billing_mode()` changed with it: a key in our own environment no longer implies anything about who pays, so the
default is `subscription` and the verification is empirical rather than inferred — Health shows `recorded` beside
`likely charged`, and the Console should track `recorded` from now on. `NEUROSEARCH_LOCAL_BILLING` still overrides,
and `unknown` still counts as billed.

Gate: `test_the_cli_never_receives_an_api_key` asserts on the environment the subprocess is actually given (every
credential absent, `PATH` intact), plus a guard that every name in `CLI_CREDENTIAL_VARS` is really a credential,
since that list is subtracted from a working environment.

**Expected effect on Kyle's bill:** the local path was 908 calls and $210.55 of the month. If his CLI has a
subscription login, that goes to zero. The number to watch is whether his Console total now tracks `recorded`.

## 0.59.3 — cost per unit of value, and the per-model number it refused to print

Kyle set the axis: *"the volume of data is always valuable, just HOW is something we want to keep checking that we
are improving against."* Everything the app measured about money answered a different question — `totals` how
much, `reconcile` how much was really charged, `rate_last_hour` how fast. So the two decisions actually on the
table (the findings cap 12 → 20; findings on Haiku) could only be argued on whether the bill rose, which is the
wrong axis: 40% more spend for twice the output is a good trade and the same spend for nothing is not.

`cost_value.py` divides spend by things the project can use. Measured on his own backup (2026-09-10 05:13,
month to date, charged = recorded + billed local):

| kind | charged | unit | produced | each |
|---|---|---|---|---|
| findings | $164.95 | finding written | 11,286 | **$0.0146** |
| | | finding kept | 10,715 | **$0.0154** |
| claims | $114.18 | Claim tracked | 11,469 | $0.0100 |
| | | Claim normalized | 7,619 | **$0.0150** |
| rank + whisper + embed | $26.59 | source read | 1,214 | **$0.0219** |
| answer | $16.13 | chat answer | 104 | **$0.155** |
| discover + plan + profile | $4.89 | *unattributed* | — | — |
| **total** | **$326.74** | | | 1.5% unattributed |

Two things worth acting on fell straight out of it. **Claim extraction is 35% of the bill** — $114 for 7,619
normalized Claims — and nothing in the session had looked at it, because it never appeared as a line anywhere.
And cost per kept finding by day: $0.0054 (Sep 7) → $0.0157 → $0.0168 (Sep 9) → **$0.0089 (Sep 10)**, the drop
coinciding with the raised cap and the local path.

**The number it would not print.** A naive per-model split said findings cost **$0.0231 each on Haiku against
$0.0071 on Sonnet 5**: Haiku, at a fifth of the token price, apparently three times dearer per finding — and
plausible enough to act on, since Haiku's calls really were the expensive ones ($0.188/call against $0.042). The
cause was in the ledger, not the model. `usage.record_anthropic`'s local branch writes the model the CLI *returned*
into `usage.model` and prices the tokens at the **contract's** model, because the avoided-spend figure is only
meaningful against the model that would otherwise have run. All 513 local Haiku findings rows were Sonnet-5-priced,
uncached, on ~47k-token windows. Reported as a per-model verdict it argues for exactly the wrong decision.

So the fix is in two parts, and the second is the general rule:

- `usage.price_model` (additive column, defaults to `model`) records which model's rates produced a row's dollars,
  set to the contract's model on the local path. From 0.59.3 the basis is a fact, not an inference.
- `cost_value.price_basis` reports, per model that did the work, which models' rates paid for it. **A row whose
  basis is foreign or unrecorded carries its cost and its count and no `per_unit`, with the reason in the row.**
  Historical local rows are `unknown` and stay unknown — the contract's model was never stored, and inventing a
  basis to fill the column would be the same class of error as the $0 local cost.

Same shape as 0.58.6 and 0.58.7: a constant or a ratio computed from real data contradicted a plausible guess, and
the plausible guess was mine. The difference here is that the wrong number was not a threshold I could re-tune but
a verdict about a model — so the module withholds it rather than rounding it down.

Also recorded honestly rather than smoothed over: `estimated` (what share of a window's charge is priced from
tokens on the local path instead of metered by the API), and three counting caveats that can move a ratio in a
direction worth knowing about — `db.set_note_status` resets `created_at`, so promoting reserve findings shows as
findings "written" today; corroboration is a corpus property, so a past window's corroborated count can only rise;
and transcription and embedding rows carry no project, so `$ per source` is a whole-app number and is omitted from
a per-project report rather than guessed. Gate `tests/test_s9_cost_value.py` (23).
