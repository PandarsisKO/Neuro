# Neuro Search — architecture map for Claude Code (current state, 0.63.2)

Python 3.11+ / FastAPI / SQLite (FTS5 + numpy vectors) / single-file vanilla-JS UI / MV3 Chrome extension. Package `neurosearch/`.
History and evidence live in `HARDENING.md` (final verdict table, experimental-feature inventory, rung-by-rung record) and `evals/`.

**New session? Read `HANDOFF.md` first** — the front door: reading order, how Kyle works with a session, the delivery ritual, where things stand, what "done" means.

## Standing rules (never break these)

- **Never write to `data/neurosearch.db` from outside the running app** (a mount from another OS/VM corrupts the WAL). Use the API/CLI. Hourly verified snapshots → `data/backups/`.
- Schema is additive (`CREATE … IF NOT EXISTS` + column adds in `db.py`); no migration tool. Migration fixtures in `tests/fixtures/db/`.
- **The model decision engine (0.54.0).** Every task runs the CHEAPEST tier (`contracts.TIERS`, ordered by `usage.PRICES` — note `claude-sonnet-4-6` $3/$15 ranks ABOVE `claude-sonnet-5` $2/$10) unless its contract names one of four reasons: `capability:<what>` (fact) · `evidence:<path>` (measured) · `irreversible` (debt) · `user:<who/why>` (opinion). Anything above the cheapest tier with no reason is a CONFIG ERROR refused by `release-check` — that refusal is the engine. `neurosearch models` prints the decision table. **`reversible` means the CONSEQUENCES are undoable, not that the call is cheap to repeat** (`rank.relevance` chooses which 20 of 400 videos enter the corpus, so it is irreversible however cheap re-ranking is). Everything at the cheapest tier must be reversible AND have a `gate`. Gate `tests/test_r6_model_policy.py`.
- **The local provider runs the CONTRACT's model (0.52.0).** `InferenceContract.local_model` (None = the contract's own model, the default for every task) is what Claude Code runs, via `contract.model_for(executed_by)`; `providers.routing_for` records `local_model`/`api_model` on the artifact whenever they differ. `NEUROSEARCH_CLAUDE_CODE_MODEL` is still honoured as a global override but `doctor` now names every task it overrides. Before this, one .env line silently replaced every per-task model — `findings.extract` and `rank.relevance`, both pinned to Sonnet 5 by measured comparisons (E2.1/E2.2), ran on Haiku 4.5 on every local call with nothing recording it. A cheaper model is often right; it has to be a declared decision, never a side effect. Gate `tests/test_r4_local_model.py`.
- `providers.invoke(task, …)` / `invoke_structured` are the ONLY entry points for model calls; never pass model/max_tokens/headers at call sites. Every task has an `InferenceContract` in `contracts.py` with `fallback="NO_FALLBACK"` — there is no model-substitution code path and none may be added.
- **Every model comparison pins its transport (0.56.3, extended 0.56.5).** `migration.run_migration_compare`, `evals.run_findings_compare` and `evals.run_ranking_compare` all force `settings.ai_profile="cloud"` + policy `api_only` for their run (`evals.pin_api_transport` / `migration._force_api_transport`, restored on every exit path) and verify each arm's returned model (`arm_model_ok` / `_assert_arm_model`), failing on the FIRST offender. `findings.extract` and `rank.relevance` are `local_capable`, so the two commands that would decide Haiku for findings were the worst affected: both arms routed to the local CLI and neither ran the model it was handed.
 `migration.run_migration_compare` forces `settings.ai_profile="cloud"` + policy `api_only` for its whole run (`_force_api_transport`, restored on every exit path) and verifies each arm with `_assert_arm_model`, failing on the FIRST arm whose returned model is not the one it asked for. With `NEUROSEARCH_AI_PROFILE=local` in `.env`, every `local_capable` task (`planner.update`, `claims.extract`, `findings.extract`, `rank.relevance`) routed to Claude Code instead: both arms of `planner.update` printed `$0.0000 · returned claude-haiku-4-5` regardless of the model set, and the *shared inputs* every other arm is judged against were written by the local model rather than the production findings contract. `local` vs `api` is a transport, never a model.
- **A provider that returns a model nobody asked for is a silent substitution (0.56.3).** The app has no model-substitution code path, so a mismatch always arrives from OUTSIDE it — the local Claude Code CLI served `claude-haiku-4-5` for a call pinned to `claude-sonnet-4-6`. `providers.routing_for` compares the returned id against the requested one (`contracts.same_model`: a dated snapshot of the alias is not a substitution), stamps `model_mismatch` on the artifact, and counts it via `db.bump_model_mismatch` → `db.model_mismatches()`, surfaced in `db.health()["model_routing"]` and warned by `release-check`/`doctor`. Recording `actual_model` was never enough: nothing read it. Gate `tests/test_s1_arm_preflight.py`.
- **An arm that cannot run must fail before anything is paid for (0.56.2).** `migration.task_arms` builds no `candidate-adaptive` arm for a candidate that cannot do adaptive thinking (`supports_adaptive` = Claude 5 only, mirroring `contracts.validate`), and `migration.validate_arms` constructs EVERY arm's contracts before the first paid call — the arm-level twin of `preflight`, and it fails free the same way. 0.56.1's `--candidate-model claude-haiku-4-5` built an adaptive Haiku arm; the ContractError landed after two planner arms had been billed, so $0.39 of finished measurement died with the run. `run_migration_compare` now also writes its report from a `stage_error` path, so a stage that dies anyway leaves the completed stages measured and reported instead of discarded. Gate `tests/test_s1_arm_preflight.py`.
- **A per-pass cap is not a budget (0.51.0).** `claims.FAST_GROUPS` bounded one paid fast pass to 16 claims and nothing bounded passes per hour, so a paid pass was queued every ~5 min all day (32% of a month's spend). Any lane that can re-queue itself needs a RATE limit that the "enough work accumulated" test cannot bypass (`claims.FAST_MIN_INTERVAL_S`). `db.BACKGROUND_KINDS` (`extract_claims`) is paused by `background_paused` **whatever lane it runs on** — a control that exempts the thing it exists to stop is worse than no control. `usage.SPEND_RATE_CEILING` ($/rolling hour, maintained by `usage.record`) holds ONLY paid background (`db.RATE_HELD_POLICIES` + `BACKGROUND_KINDS`) — never chat, ingestion, transcription or local work — expires on its own, and is released by the user via `POST /api/usage/rate-resume`. Gate `tests/test_r3_spend_rate.py`.
- **Account gates are cached beliefs, not facts:** `providers:billing_until` and `providers:spend_cap_until` block the queue, and only a SUCCESSFUL call (`db.clear_account_gates()`, called by `providers`) or the user's explicit Re-check (`POST /api/usage/recheck`) may retire one. Never set a gate without a path back — `spend_cap_until` had none until 0.46.4 and a Console limit raise could not unblock the app. The same rule covers `claude_code.health`'s 10-minute cache (Re-check forces a fresh probe, 0.46.5) and a job's `message` (claiming clears a stale `paused:%` one, 0.46.5). **`extract_claims` runs on the `slow` lane** (p90 ~2 h against only 3 AI worker slots).
- `safe_fetch.safe_fetch()` is the ONLY way to fetch a user-supplied URL (yt-dlp is the documented exception). No second fetch path, no caller-side limits.
- Batch results enter the DB only through `batches.materialize_ready`; never claim a provider batch by count alone.
- Frozen numbers (Tier 1 totals, retrieval baseline, prefilter/rerank gates) are decisions: never re-tune an experiment to a fixture; changing a frozen value is recorded in HARDENING.md.
- API keys only in `.env`; cookies server-side (`data/cookies/`); Instagram only via the extension session, cap 40; no account cookies for bulk YouTube downloads by default.
- Eval policy: Tier 1 (`NEUROSEARCH_FAKE_AI=1 neurosearch eval`) + pytest always; live paid evals only for a major model replacement, a major AI-affecting architecture change, or a regression investigation.
- `project_sources.excluded=1` is a durable "removed from this project" marker: every membership query (direct, collection, tag) subtracts it; an explicit add lifts it. Never derive membership without it.
- New test modules must sort AFTER `tests/test_core.py` (it builds the shared settings/DB at import).

## Modules

| Area | Modules | Notes |
|---|---|---|
| Config / storage | `config.py`, `db.py`, `logctx.py`, `usage.py` | settings from env/.env; `db.py` holds the schema and all SQL, `db.tx()`/`db.batch()`, `backup()`+`verify_database`, `integrity_check`, `health()`; `logctx` correlates log lines (job/run/project/source/task/model); `usage` = spend ledger, budgets, `guard()` → `BudgetPaused`, cache pricing |
| Ingestion (incl. **S8 caption recovery 0.47.0**: `ingest.recover_caption_text` appends a video's caption to the transcript ONLY when the spoken track is under `SILENT_TRANSCRIPT_CHARS`, behind an explicit marker segment — music-only shorts/reels; `low`-lane backfill via `…/sources/caption-recovery`) | `ingest.py`, `media.py`, `documents.py`, `sheets.py`, `webpage.py`, `transcribe.py`, `chunking.py`, `embeddings.py`, `courses.py` | staged (`metadata → transcript → chunks → embeddings → ready`), each stage transactional, resume at first incomplete stage; `media.canonical_url` before any dedupe; documents/sheets use page/sheet locators; `webpage.fetch` goes through `safe_fetch` |
| Network boundary | `safe_fetch.py`, `htmltree.py` | pinned validated connection (all A/AAAA answers checked, Host+SNI kept), manual revalidated redirects, wire/decoded/time limits per content class (`LIMITS`), `FetchBlocked(reason)` → Health `network`; hooks `RESOLVER`/`CONNECT` for tests |
| Jobs | `jobs.py`, `breakers.py`, `batches.py` | durable SQLite queue: leases + heartbeats, `job_events`, `blocked_by`/dependency policies, `dedupe_key`, cancel at safe boundaries, `crash_point` hooks; `submit_external` → `external_pending` (re-attach, never resubmit); derived statuses blocked / retry_wait / budget_wait / rate_limit_wait / provider_wait / external_* / cancelling. `breakers`: circuit per provider:operation (`anthropic:messages`, `anthropic:batches`, `openai:embeddings`, `openai:transcription`), 3 transient failures → OPEN, single-worker probe, `provider_wait` jobs cost 0 attempts/$0 and wake on close. `batches`: Message Batches for background findings (cohorts, `batch_items`, tentative recovery of unknown handles, `estimate`, `ui_state`) |
| AI plumbing | `providers.py`, `contracts.py`, `schemas.py`, `claude_code.py`, `fake_ai.py`, `fake_batches.py` | `_Ledgered` wraps every client call: breaker gate → invocation ledger row per attempt (`invocations`, incl. `outcome_unknown` after a dead run) → typed retries per contract (`classify_error`; SPEND_CAP/BILLING/AUTH… never retried, never trip a breaker) → `ProviderError`. `routing_json` = requested/actual model + fallback audit stored on every artifact. `schemas.REGISTRY` = versioned structured-output schemas (`provider_schema` strips client-only constraints; `schemas.clamp` applies those same bounds locally as truncation, never rejection; `check_provider_compat`). `NEUROSEARCH_FAKE_AI=1` swaps in content-aware fakes (outage/rerank/prefilter/batch knobs) |
| AI tasks | `sources_value.py` (S2 $0 value spine: findings/Claims/plan/chat/priority → `value_score`, `matters` rule, label; S3 `digest`/`used_in` = the source drawer's one request), `findings_view.py` (S4 $0 findings query: filters/facets/sort/paging, use badges, low-value sweep), `claims_view.py` (R7 $0 Claims workbench: filters/facets/sort/paging over the full claim set, `plain()` one-line translation, batch accept/reject, `for_source` = chat's "Why this answer"), `community.py` (G7 community evidence, $0), `works.py` (G6 canonical works, $0), `claims.py` + `knowledge.py` (G5 research state), `library.py` (G4 profiles + recall), `findings.py` (+`prefilter.py`, off), `relevance.py`, `qa.py`, `planner.py` (V1, production) / `planner_v3.py` (off), `discover.py`, `export.py`, `search.py` (+`rerank.py`, off), `evidence.py`, `staleness.py` | findings/relevance write project-relative artifacts to `project_source_analysis` with `input_hash` + provenance; `qa.chat_system_blocks` builds the chat prompt in cache order (stable prefix → breakpoints → `PROJECT_STATE_BLOCK`); `search` = FTS + embeddings + RRF; `evidence` validates quotes/citations/plan evidence at runtime → Health; `staleness.assess/rebuild/triage/accept` = CURRENT / STALE / current_accepted / REBUILDING with cost estimates; S1 triage tiers rebuild_matters · rebuild_transcript · accept · retry_failed (`accepted_hash` on the analysis row) |
| Surfaces | `api.py`, `web/index.html` (`UI_VERSION`), `mcp_server.py`, `cli.py`, `extension/` | endpoints are plain `def` (threadpool); projects are the unit (chats, sources, findings, plan, settings, Health); extension = course import, "Send this page", Instagram session |
| Proofs | `evals.py`, `retrieval_eval.py`, `prefilter_eval.py`, `cache_layout.py`, `migration.py`, `closeout.py`, `batch_smoke.py`, `release.py` | `neurosearch eval` (Tier 1 on the frozen Golden Project `tests/fixtures/golden/`, `--ranking`, `--findings-compare`, `--migration-compare`, `--retrieval [--rerank]`, `--prefilter`, `--cache-layout`); `neurosearch closeout` (Mission F); `neurosearch batch-smoke --live` (the one tiny paid adapter check); `neurosearch doctor` (fast diagnostic); `neurosearch release-check` (heavyweight deterministic gate → `evals/release/`) |

## Source capability — what a master source has given us (C1, 0.58.2)

`candidates.creator_yield(project_id)` ($0, derived on read, no schema change, no model) → channel → `sources`,
`findings`, `claims`, `evidence`, `classes`, `per_source`, `proven`. `candidates._potential` gained a
`_creator_term`: before this it scored a known-but-uncaptured item out of 100 from the words in its own title and
600 characters of description and **nothing else**, so a video from a channel whose sixty siblings had produced
hundreds of findings and closed evidence targets scored exactly the same as one from a channel that had never
yielded anything. With a partial-ingest pattern (60 of 598, plus 107, 93, 398 unstarted) those remainders are
reservoirs of known character, and the pool was treating them as a flat list of strangers.

**Calibrated 2026-09-10 (0.58.7).** `CREATOR_STRONG_PER_SOURCE = 8.0` was an absolute bar and it does not survive
real projects, because findings-per-source is a property of the domain and of source length, not of a creator's
merit: measured per-source medians were 12.0 for "buying businesses" (112 creators, max 48.2), 6.1 for "web app
design", 9.4 for "real estate" — so 8.0 marked nearly everyone in one project and almost nobody in another.
`proven` is now the project's OWN top quartile (`CREATOR_PROVEN_QUANTILE` 0.75) over creators with at least
`CREATOR_MIN_SOURCES` (3) read sources and 10 findings; it self-calibrates, always names someone, and states
something true in a sentence. On the live corpus that gives 13 of 112 proven, 3 of 17, 1 of 9. Two ranking fixes
from the same measurement: **no rate is projected from fewer than 3 read sources** (one video with 24 findings was
producing a promise of ~240 from the next ten — `expected_findings` is now null with the reason given), and the
untapped-count bonus is capped at +8 as a tie-break, because a large remainder is not evidence that it is worth
reading.

Two rules keep it honest. **Absence is never evidence** — a creator with no yield gets no penalty anywhere, because
a channel that never supplied authoritative evidence may simply never have been asked (`CREATOR_MAX_BONUS` is a
bonus only, capped at 25 so it cannot dominate the word signals). And the profile is **project-scoped**: G4 forbids
building a *global* Source Profile from project findings, and a yield profile is by construction built from project
findings, so it stays inside the project that produced it exactly as `project_reuse` does — a finding is an
interpretation written against one brief and does not become a fact about a channel by being averaged. Cross-project
aggregation is a separate decision needing its own argument. The wanted-evidence-class bonus reads the project's own
open targets (`preferred_classes`), so "it has supplied experiential evidence before, which is what this question
needs" is a measurement, not a similarity. API `GET /api/projects/{id}/source-yield`. Gate
`tests/test_s4_source_capability.py`. Rest of the rung: `SOURCE-CAPABILITY-RUNG.md`.

**C2 — where to look (0.58.3).** `candidates.where_to_look(project_id, target)` answers the question gap analysis
never could: not *what is missing* but *where to go for it*. `untapped_by_creator` counts what the project knows of
each master source but has not read (skipped at the cutoff + Candidate Index rows); a creator is only recommended
when it has **both** a yield history here **and** something unread — a proven channel with nothing left is not a
place to look, and an untapped channel with no history is just a list. Every reason cites a number ("312 findings
from 12 sources", "14 known but unread"), `expected_findings` is an explicit extrapolation from this project's own
history with that source, and the action points at the existing pool filtered to that creator. It is DB-only, so it runs on `pursue(external=False)` where the UI promises no *web search* — but it is **not a step**: `escalation.steps` is the LADDER (project evidence → library → candidates → external), every entry is somewhere the app actually looked, and `research_view`'s `already_checked` renders straight from it. A recommendation is not a search, so it rides alongside as `escalation.where_to_look`. Putting it in `steps` broke the frozen G5 gate and would have reported advice as a check. API `GET /api/projects/{id}/where-to-look[?target_id=]`. **C3 (0.58.4):** a "Where to look · $0" button on every
open question in the Research tab opens the ranked list and jumps straight into the existing
Sources → 🔎 Known, not captured view filtered to that creator (`poolFilter`) — the pool's `q` already matches
creator, so no second surface was added.

**The UI has a syntax gate now (0.58.4).** `web/index.html` is ~295 KB with ~247 KB of inline JavaScript and no
build step, so a stray brace shipped silently and surfaced as a blank panel in the browser; nothing checked it.
`release_check` now extracts the inline script and runs `node --check`, and also asserts `UI_VERSION` equals the
package version (the third leg of the delivery ritual, previously only checked by eye). It WARNS rather than fails
where no JavaScript engine exists — a missing `node` is a fact about the machine, and a gate that fails for that
reason teaches people to ignore gates. Gate `tests/test_s5_ui_syntax.py`.

## Accelerate: one button per distinct purchase (0.59.2)

Kyle: *"two of the spend options are identical and worthless — 'most valuable first' and 'do all' are the same."*
True, twice over: `order="value"` SORTS the set it is given, so with n = the whole queue the sort changed nothing;
and the value came from `sources_value.compute(project_id)`, which is empty with no project in scope, so even a
subset was often ordered by a column of zeros. `jobs.accelerate_options()` now returns SETS — `waiting_on` (a
priority source or a source with a value score, the same two signals `claims.triage` uses), `most_valuable`,
`cheapest` (fewest windows = most jobs cleared per dollar), `all` — each with its criterion and its own price,
**cheapest first, with identical sets collapsed** so the same purchase can never appear twice under two names. Under
six queued jobs, only `all` is offered. `accelerate(option=)` buys exactly the set that was priced, with no
re-derivation, so the confirmation cannot drift from the button.

**Why a long queue feels serialised** (`backlog()["pools"]`): `start_workers` partitions the AI workers by execution
policy — the local pool claims `LOCAL_POLICIES`, the api pool claims `API_POLICIES` — and ordinary findings work is
created `local_preferred`. So **the API worker is idle by construction** whenever the backlog is ordinary work,
however long it is, and accelerating is the only thing that gives it anything to claim. That is a defensible design
(it never spends without being asked) but it was never stated anywhere, which is why the queue read as a stall.
The banner now says it. Gate `tests/test_s8_accelerate_options.py`.

## Spend: local is free only when we can show it is (0.59.0)

**The measurement.** 2026-09-10, from Kyle's own data: app ledger **$111.96** month-to-date, local Claude Code path
booked as `saved` **$210.55**, his Anthropic Console **$312.40**. The first two sum to within 3% of the third. L1
recorded every local call as `cost=0` with the avoided spend in `saved`, on the assumption the CLI runs on a
subscription — nothing ever checked. Those were real charges, and being booked at zero made them invisible to the
daily budget, the monthly budget, `SPEND_RATE_CEILING` and Health simultaneously (all four read `cost`). He topped up
credit for a week while the app told him he had spent a third of what he had.

- **THE CAUSE (0.59.1): the app was handing its own API key to the CLI.** `config.load_dotenv()` copies `.env` into
  `os.environ`, and `claude_code._run` passed the whole environment to the subprocess — so `ANTHROPIC_API_KEY`
  reached the Claude Code CLI on every call and the CLI used it in preference to the user's subscription login.
  `claude login` could not fix it; the app overrode the login every invocation. `_run` now subtracts
  `CLI_CREDENTIAL_VARS` from the subprocess environment. With no CLI login the CLI errors, `_run` raises
  `LocalUnavailable` and `providers.route` falls back to the API where the call is RECORDED — visible and paid
  instead of hidden and paid.
- `claude_code.billing_mode()` → `subscription` | `api_key` | `unknown`; `NEUROSEARCH_LOCAL_BILLING` overrides.
  Since the key is no longer passed, a key in our own environment says nothing about who pays, so the default is
  `subscription` and the check became EMPIRICAL: `reconcile()` shows `recorded` beside `likely_total`, and the
  Console should track `recorded` from here on. **`unknown` is still treated as BILLED** — assuming free is the
  specific error that hid $200, and `claude_code.local_is_free()` is the only gate.
- `usage.record_anthropic` prices a local call as real `cost` unless it is free, in which case it stays `cost=0` with
  `saved`. Exactly one of the two is ever non-zero, so `recorded + local_if_billed` never double-counts.
- `usage.reconcile(days)` reports `recorded` / `local_if_billed` / `likely_total` for today, the week, the month and
  per day — history is NOT rewritten, both numbers sit side by side so a month that looked like $112 can be
  recognised as $312. `GET /api/usage/reconcile`; Health `spend`; `release-check` warns when the profile is local and
  billing is not a subscription.
- **A weekly budget exists** (`weekly_budget`, rolling 7 days, off unless set) because Kyle measures this in weeks,
  and **`usage.rate_ceiling()` is settable** (`spend_rate_ceiling`): the $6/hour default is ~$1,000/week, which is a
  runaway detector rather than a budget. `POST /api/usage/spend-settings`.
Gate `tests/test_s7_local_billing.py`.

## The fix pass (0.61.0)

Nine faults, every one found by measuring Kyle's live data or by looking at his actual screen rather than by
reading the code.

**A clause made only of generic words could produce a "strong" match.** 0.60.2 fixed the matcher and the Airbnb
video came back anyway. His goal splits into six clauses whose most distinctive words are `auditing` (15 sources),
`cognitive` (16), `reusable` (28), `architecture` (38) — and then `improving` (85) and `designing` (125). Every bad
match comes from the last two, and no matcher can help: a video about Airbnb income genuinely does discuss
improving and designing things. Rarity cannot separate them either — `improving` is in 6.9% of the library, `ux` in
5.2%. So the fault is in the QUERY. `bootstrap.query_strength` marks a search weak when **every** word in it is
common (`library.query_anchor` now reports `too_common`, an absolute judgement that needs no distribution) or when
its rarest word is above the median of the goal's own searches (`WEAK_QUERY_QUANTILE`, relative, so 85 sources is
generic in a 1,229-source library and distinctive in a 90-source one). A hit that matched only weak searches can
never be `strong`, is tagged `generic match`, and is held back from the card behind "show them anyway" — never
deleted. A word too RARE to anchor on is the opposite of generic and is never caught by this.

**A re-scan could not take a suggestion away.** `upsert_project_reuse` only inserted or updated, so a row the fixed
matcher no longer produces stayed on the card for ever. `db.retire_project_reuse` retires the `suggested` rows a
scan did not reproduce — a suggested row's only author is the scan, so a scan that no longer makes it may withdraw
it; rows the USER decided on are never touched, and `retired` keeps the row so the count stays explainable.

**A progress callback erased a terminal failure message.** Four failed jobs read `[download] Finished downloading
playlist: Mark J Kohler`; the real reason ("metadata fetch timed out after 4 min") was in `job_events` all along.
yt-dlp went on downloading after the job had failed and reported over the top of it. `db.update_job` now refuses to
touch a job in `JOB_TERMINAL` unless a status is being set deliberately, and `jobs.run_job` clears the progress
hook in its `finally`. **A diagnosis a later callback can erase is not a diagnosis.**

**The Master Plan could not build** — see the HARDENING.md entry: `ALL_SUCCESS` over 199 ingest jobs became
`ALL_TERMINAL` (changed frozen decision, with its gate rewritten and its reasoning recorded).

**14 failed sources, every one unclassified.** A deleted video, a carousel with no video track, a 403 and a network
timeout were indistinguishable, so the hopeless could not be told from the retryable. `db.FAILURE_CLASSES` (ordered,
deterministic, no model) classifies as the failure is recorded, `failure_is_permanent` is the distinction the UI
needs to offer "retire" rather than "retry all", `backfill_failure_classes` runs once at start for rows already on
the books, and `browser_solvable:*` — owned by `acquire` — is never overwritten. Health carries the split.

**A warning banner that said zero:** "⚠ 0 sources analysed against older inputs · 15 re-analysing". The headline is
now built from what is actually non-zero, and the garbled "Three answers, not one bill" line is gone.

**The Findings tab re-ran five whole-project passes every four seconds** while any source was being read
(`/findings`, `/findings/quality`, `/staleness`, `/staleness/triage`, the project row). It now asks the 13 ms
`/tick` "did anything change?" first — the machinery the Sources view has had since 0.46.2 — and still reconciles
fully every `RECONCILE_EVERY` ticks.

**`discover.check_links` no longer runs under the fake provider.** It was the one thing in the app that reached the
real network from a deterministic test, and it duly made a Tier 1 test flaky by timing rather than by logic.
Gate `tests/test_s14_fix_pass.py`.

## The lock-up: a pass worth having is not worth having in a request (0.61.2–0.61.4)

Kyle: *"the app is locked up or failing to load for me. very slow right now."* Measured on his machine while it was
unresponsive rather than guessed, against the 16,962-note project: `/findings/quality?summary=1` **11.5 s**,
`/findings` **2.0 s**, and until 0.61.0 the tab re-asked every four seconds. Beside a 627 MB database sat a
**111.8 MB write-ahead log**, static — SQLite auto-checkpoints at ~4 MB but only when no reader holds an older
snapshot, and this app keeps a long-lived connection per thread while several threads run multi-second passes, so
the checkpoint had been starved for days; `journal_size_limit` was -1, so even a successful checkpoint never gave
the file back. Fixed live: 112 MB → 1.2 MB.

- **`cache.py` gained single flight and stale-while-revalidate.** Every concurrent miss on the same key used to run
  its own copy of the 11.5 s pass. `get_or_compute` now computes once per (key, revision) and the rest wait;
  `get_stale_ok` returns the previous value at once with `current: False` and refreshes in a background thread. A
  cache whose key moves faster than its value can be computed is not a cache, so `findings_quality.summary`
  defaults to `warm=False` and an uncomputed project SAYS so (`{"pending": True}`) instead of blocking a screen.
- **`db.WAL_LIMIT_BYTES` / `checkpoint_wal()`** with `journal_size_limit` set on every connection, run by a
  `_housekeeping_loop` every 120 s; Health `storage` reports `wal_mb` and whether it is over the threshold.
- **0.61.4 — the workbench assembles its rows once.** `/findings` measured **23.2 s cold, 4.3 s warm** after the
  quality pass was fixed, and the remaining cost was `findings_view.query` re-assembling every note on every
  request: every row loaded with its full text, every citations blob parsed, every derived field rebuilt.
  `findings_view.decorated(project_id)` caches the assembly on `db.project_view_revision` — deliberately
  `get_or_compute`, not the stale-tolerant variant, because a page of findings must never show a status the user
  just changed. Filtering and sorting 17,000 dicts costs milliseconds; assembling them was the whole bill. The
  housekeeping loop warms `research_view.areas`, `findings_view.decorated` and `findings_quality.summary` for the 8
  most recently updated projects, so the first visit after a restart is warm too.

Gate `tests/test_s15_lockup.py`.

## A usage row is dated when the money was spent (0.62.3)

Reconciling Kyle's month against his Anthropic Console, 2026-09-10, produced two anomalies that looked like
different bugs and were one. His Console billed **$149.25 on Sep 9** and the app recorded **$19.75**. The next day
the app recorded **$30.23** against a Console figure of **$17.93** — the app claiming MORE than he was charged,
which no amount of hidden spend can explain.

**1,284 batch rows worth $23.18 were written between 15:49 and 16:12 on Sep 10, 647 of them inside a single
minute**, for results Anthropic had computed and charged for the day before. `usage.record` stamped `time.time()`,
so a Message Batch is dated when the app *collects* it. The day the money was spent read low; the day it was
collected read high; and `usage:rate_blocked_until` fired that afternoon (`rate_at_block` $17.43, peak rolling hour
$23.30 against a $6 ceiling) **holding paid background work because of money that was already gone.**

- `usage.record` / `record_anthropic` take an explicit **`ts`** — when the spend was incurred. Everything defaults
  to now, which is right for an interactive call and wrong for a batch.
- **`batch_items.result_at`** (additive) records when a provider result actually arrived, set the moment the raw
  result is persisted. `updated_at` cannot serve: it moves again when the item becomes `materialized`, so by the
  time the ledger row is written the collection moment has been overwritten.
- **A backdated row never touches the rate gate** (`usage.late_booking`). A rate ceiling is a statement about
  spending *now*; late news about the past cannot be un-spent by holding work today. It still counts towards the
  daily, weekly and monthly TOTALS, which is where late news belongs.
- `reconcile` admits two things it used to hide: **`batch_dating`** says how much batch spend is still dated by
  collection (rows written before this release cannot be recovered by arithmetic, so the report says so rather than
  presenting them as clean), and **`mixed_basis`** names a window that rests on two accounting bases — on
  2026-09-10 the same day held $3.48 of local calls priced as charged beside $96.16 booked as avoided, because
  `local_is_free()` flipped part-way through it, and the report showed one number.

This is what makes a spend limit mean something: before it, the daily budget, the weekly budget and the hourly
ceiling all read a column that was wrong in both directions — firing on phantoms, and by the same token able to
miss a real runaway whose spend arrived late. Gate `tests/test_s18_ledger_dating.py`.

## A discovery pass paid seven minutes to read a few counts (0.62.1–0.62.2)

Kyle: *"the search took much longer than the ~10 seconds advertised."* It took **195 s**, and **432 s** on the run
right after 3,314 findings were approved — for a library-only Discover with no model call, no web request and no
dollars. He assumed the library pass. So did I. 0.62.1 added stage timing to `library.recall` and `discover` rather
than reasoning about which stage looked expensive, and it settled the question:

```
discover.research_state   431.6 s
discover.library            0.9 s     ← the pass we both blamed, warm
recall.search               6.9 s     p50, cold
recall.mentions/anchor/profiles/scope   milliseconds
```

The seven minutes were `claims.ensure` running BEFORE any discovering: `harvest` over 17,119 notes, every one of
4,331 Claims assessed, then the whole knowledge map, tension detection, community synthesis and every evidence
target — so that a discovery pass could read some counts and a list of open questions to steer itself.

- **Half of it was arithmetic.** `ensure` called `assess_project` and then `knowledge.refresh`, which opens by
  calling `assess_project` itself. Every Claim in the project was assessed **twice per call** — 8,662 times instead
  of 4,331 — for identical results.
- **`claims.ensure_cheap`** is what a caller that only STEERS should use: it reads the map that exists
  (`knowledge.state_map`, no recompute — `state()` falls back to `refresh()` when a project has no nodes, and a
  steering caller must never trigger that) and queues the real pass as a **`refresh_research`** job on the `low`
  lane, deduped per project so a second request cannot queue a second copy. A project with no map at all still
  pays once, because there is nothing to steer by and the pass is small by definition.
- Discover's reply says how current its steering was (`research.as_of`) instead of implying it is live.

**A pass worth having is not worth having in a request** — the third time that sentence has been the fix this week
(0.61.2 the findings-quality pass, 0.61.4/0.62.0 the findings rows, this). And the third time the stage I would have
optimised on inspection was not the stage that cost anything. Gate `tests/test_s17_steering_cost.py`.

## A rung that cannot run is not a rung (0.63.2)

0.63.1 gave the chat's attach button permission to pay for OCR. It still did not read Kyle's two screenshots.
Measured, not guessed: I staged one of the PNGs and looked at it — a dense CIM detail page, price, SDE, location,
a 300-word About paragraph — and then listed his venv: **no `PIL`, no `pyobjc`.** `./start` re-runs
`pip install -e '.[dev]'`, and he had not relaunched since those dependencies were added in 0.63.0, so
`images._for_model` raised `ImportError` inside the `try` that guards the model rung, the exception was logged and
swallowed, and a **missing dependency was reported to him as an image with no text in it.**

Two separate faults, and they need separate fixes:

* **The paid rung no longer depends on Pillow being there.** Pillow is how an image gets downscaled and converted,
  and that is worth doing — tokens scale with pixels. But Anthropic accepts png/jpeg/gif/webp and downscales
  oversized images itself, so when Pillow is absent an already-acceptable file is sent as it is. More tokens than
  necessary beats *"nothing could read your screenshot"*. A `.heic` still cannot go without conversion, and now
  fails saying so.
* **The sentence must not make a claim nothing measured.** `images.ocr` distinguishes *no rung ran* from *a rung ran
  and found nothing* by whether any entry in `engines_tried` carries a character count. The first case says
  "nothing on this machine could read this image" and names what was tried; only the second says there is no text in
  it. `read_image_with_model` returns `engines_tried` on the failure path too, because `{chars: 0, engine: "none"}`
  is unactionable on its own.

**And the title backfill renamed nothing.** `POST /api/conversations/retitle` reported `changed: 0` across his 42
chats. Not a titling failure: `db.get_messages(limit=1)` is a **tail** — `ORDER BY id DESC LIMIT n`, reversed,
because a chat view wants the latest turns — so asking it for one message returned the *newest*, an assistant reply
in 41 of the 42, and the scan for a user message found nothing. Every test passed because a test conversation has
one message, where the head and the tail are the same row. `db.first_user_message(conversation_id)` is now its own
query, and S26 builds real threads (question → answer → follow-up) rather than single messages.

The general rule this is an instance of: **a ladder rung whose failure is indistinguishable from its answer is worse
than not having the rung.** Every `except` around an engine must record what happened and the caller must be able to
read it — the cost of swallowing it here was two unusable screenshots and a chat that could not answer.

## Who asked, and what to call it (0.63.1)

**Images: uploading never pays, but attaching does.** Kyle attached two iPhone screenshots of a CIM to a chat and
got *"I can't see what's actually in them."* Measured on his database: both sources were `ready`, both pictures
kept on disk, both with **zero chunks** and the description *"no readable text found by the free local OCR on this
machine"* — neither Apple Vision (its dependency ships in 0.63.0 and installs on the next `./start`) nor tesseract
(absent on macOS) was there, and 0.63.0 refused to pay. The rule was right for a bulk upload and wrong for the case
he actually used: **an image attached to a question you are waiting on IS the ask.** `ingest_local_file(…,
ocr_paid=True)` is set only on the `immediate` upload path — the chat's attach button — so a bulk drop of
screenshots still spends nothing. And the two failures now read differently, because they are different problems:
*"no text found in it"* is about the image, *"nothing could read it: no free OCR on this machine yet"* is about the
install.

**Chat titles: the shape was already in his data.** *"can you find a better way for the chats to name themselves?
the names are too wordy."* They were `question[:80]` — measured across his 40 most recent chats, mean **54
characters** with a hard cluster at exactly 60, cut mid-word (`how would I tell claude to design the web app as if
Apple, T`). The good titles in the same list were the ones he had renamed by hand: **"CPA Fees"**, **"Emails with
Josh"**, **"CPA Cim Stanislaus"**, **"Fax Machine to Modern Tools"** — short noun phrases, 2–4 words.

`titles.for_question` ($0, no model call) reproduces that shape, and every rule in it exists because a measured
output was bad without it, on his own 23 real questions: keeping pronouns and the verbs of asking gave `Deal I Need
You` and `Questions That We Did`; splitting at a comma before stripping scaffolding gave `Describe a Modern` and
lost the website; trimming in the wrong order gave `Claude to Effectively Audit the`. The caps (4 content words, 34
characters) were chosen by comparison — 5/38 produced `Claude to Design the Web App as If` and `Gotchas Red Flags
Warnings to Out`, so the tighter cap is the better title, not a compromise. Results: `Deal to Evaluate` ·
`B2B Businesses to Buy` · `Stanislaus CPA Deal` · `Pay Ourselves` · `Understand Seller Financing at 10%`.

No model call on purpose: a one-line title is the last thing worth paying for, it would add latency to the first
message of every chat, and a wrong one takes a click to rename — which is where his good titles came from.
`POST /api/conversations/retitle` backfills the old ones (preview by default) and **never touches a title the user
typed**, which `titles.looks_autogenerated` is what distinguishes. Gate `tests/test_s26_chat_titles.py`.

## A question is the user's, not the answer's (0.63.0)

Kyle, minutes apart, two live faults.

**"chats are failing to save, I was chatting, it did not complete its response, and I lost the chat because I
looked at sources."** `qa.ask` wrote BOTH messages at the very end of the turn — after the model call, after
citations, after findings. A conversation row is created by its first `save_message`, so a turn that raised or was
abandoned saved nothing at all: not the answer, and **not the question he had typed.** The whole chat vanished.
The question is now saved the moment it arrives, before anything can fail (`saved_user` stops the late path writing
it twice), and `qa.save_failure` records the assistant's side of a turn that did not finish — keeping whatever text
had already been streamed, marked so it can never read as a finished answer. Both `/api/ask` and `/api/ask/stream`
call it; the stream endpoint accumulates its own deltas so a mid-answer failure keeps the half that arrived.

**"we seem to be getting 'error: FOREIGN KEY constraint failed' a lot today."** Measured in his job history: every
occurrence is `rank_proposed` — 9 of them, newest 23:01, oldest Sep 8. That job reads a collection's proposed
sources, spends minutes ranking (p50 384 s), then writes a relevance artifact per source. If a source is deleted or
replaced in between — exactly what approving a review, discarding one, or retiring a direction does — the write
lands on a dangling foreign key, and because the writes share one `db.batch()`, **one vanished source voided the
entire ranking**: minutes of paid work discarded under an error that named neither table nor row.
`db.analysis_writable` asks the question explicitly and `upsert_analysis` skips when a parent has gone —
**a source that no longer exists has not failed, it has left** — and `relevance.rank_collection` reports the count
in the review note.

## Images as sources, with OCR (0.63.0)

Kyle: *"one major flaw is we do not allow PNGs or other image types to be uploaded or used in chats. we need this
with OCR for screenshots etc."* Correct: `ingest_local_file` ended at `raise RuntimeError("unsupported file type:
.png")`.

`images.py` reads an image cheapest-first and reports which rung answered:

1. **Apple Vision** (`pyobjc-framework-Vision`) — free, local, no network, and the strongest of the three on UI
   screenshots. It is a **pip** install rather than a system package, and that is the deciding property, not the
   quality: Kyle does no terminal work, so an OCR path needing `brew install` is a path he cannot use.
2. **tesseract** when the binary is on PATH — free, local, and what the test environment has, so it is the rung the
   automated tests exercise.
3. **the model** (`image.read`, cheapest tier, new contract) — only when no local engine exists or a local engine
   returned under `THIN_TEXT_CHARS`. Images are downscaled to `MODEL_MAX_EDGE` first, since tokens scale with pixels.

**Uploading never pays.** `ingest_image` runs with `allow_model=False`; an image no free engine could read becomes a
source that says so, and `POST /api/sources/{id}/read-image` is the explicit priced verb — the same rule as every
other spend here. **An image with no readable text is still a source**, because the picture being there, named and
viewable, is the one thing always true; and the picture is KEPT at `images_dir/<source_id><ext>`, named by id so
`GET /api/sources/{id}/image` handles no user-supplied path and there is nothing to traverse. Platform `image`, one
segment (an image has no interior position to cite), then the ordinary transcript → chunk → embed path, so search,
findings, Claims and citations treat a screenshot exactly like a transcript. Chat attachment needed no API change:
the upload route already treats anything non-media as immediate.

Gates `tests/test_s24_lost_chat_and_fk.py`, `tests/test_s25_images.py`.

## Retiring a direction (0.62.9)

Kyle: *"I want to bulk remove some content that we are no longer pursuing in the large project but I dont know how.
we need to essentially get rid of ALL CPA and laundromat specific content."* He had abandoned two candidate
industries and the app had no way to say so — the only tool was removing sources one at a time, which at 64 sources
is tedious and, on its own, **wrong**.

`retire.py` ($0, no model, no network), and the measurement changed the design twice before a line was written:

- **A keyword sweep is not safe.** Matching "cpa"/"accounting firm" on his project selects 43 sources — including
  *How To Acquire Your First Business With $0 (FREE COURSE)*, *Best Boring Businesses to Buy in 2026*, his own
  *Gio Kyle and Zach first coaching call* and his own acquisition notes, because general acquisition training uses
  accounting firms as an example industry. **So retirement is by CHANNEL or explicit source id, never by keyword.**
  A channel is a publisher's whole body of work, which is the unit that corresponds to "a direction we explored":
  Laundromat Resource 25 sources / 1,059 findings, Jason On Firms Podcast 7 / 74 — against LYFE Accounting 13 / 448
  and Sherman My CPA Coach 16 / 429, which are general small-business tax knowledge and were KEPT.
- **Removing sources does not remove what was derived from them.** `db.remove_project_sources` is a membership
  marker by design (0.34.2), so on his two sets it would have left **1,775 findings** attached to sources no longer
  in the project and **2,509 Claims with no evidence inside it at all** — a research state asserting things nothing
  in the project supports. So retiring is three coordinated steps, and `preview` reports the claim count *before*
  anything happens, because "44 sources" is not enough for an informed decision and "1,664 Claims lose all their
  evidence" is.

**Nothing is deleted, ever.** Sources keep their place in the global library (another project can still use them —
there is a test), findings are `dismissed`, Claims are `rejected` with `application` carrying the reason, and
`claim_evidence` rows are untouched so the decision can be explained and undone. The reason is also written to
`project_facts` as a `rejected` decision, because *"we are no longer pursuing X"* is exactly the durable project
state the research layer is for. Bulk SQL rather than a loop over `claims.set_status` — that calls `assess()` per
Claim, and 2,509 assessments is the pass that cost 431 s in a request (0.62.2) — so the statuses are set in one
statement each and the research state is re-derived by the queued `refresh_research` job. It counts as a HUMAN
decision under 0.62.8's rule, so it drops the research caches rather than being served stale.

API `GET /api/projects/{id}/retire/channels`, `POST …/retire/preview`, `POST …/retire`; UI a "🧹 Retire a
direction" card in project Settings that lists every channel with its sources, hours and findings, previews the
consequence, and needs a reason in the user's own words. Gate `tests/test_s23_retire.py`.

## A read may be a moment old; your own verdict may not (0.62.8)

The clean re-measurement Kyle asked for, **with the job queue idle** — and it found one cause behind four slow
surfaces:

```
research/overview?full=1     38.7 s cold   33.4 s WARM
/research (full state)       75.5 s cold   63.1 s warm
claims workbench (100)       14.8 s cold   47.9 s warm
findings (100)               55.1 s cold    1.7 s warm
```

Sampling `db.project_research_revision` every 2.5 s explained all of it at once: the claim count was moving
**15,792 → 15,800 → 15,811** — about four a second — because `harvest` was turning the 3,314 findings Kyle had just
had approved into Claims. Legitimate $0 work with no model call, but a strictly revision-keyed cache recomputes on
every read for as long as it runs, and the areas/overview pass costs tens of seconds at 15,800 Claims. The third
surface to learn 0.61.2's lesson: **a cache whose key changes faster than its value can be computed is not a
cache.** (The 55 s on findings was a genuine cold build after a restart; warm is 1.7 s, and its decorations were
already stale-tolerant.)

**Then the gates corrected the fix, which is the part worth keeping.** Making the read stale-tolerant broke two
frozen tests about a person dismissing a watch-out and accepting a Claim — and they were right to break. Serving
someone the answer from before their own click is not "a moment old", it is wrong.

So the rule is by **AUTHOR, not by age**: background churn is served stale with `as_of_current: False` and
`recomputing: True` beside it; a recorded human decision drops the entry, so the next read recomputes.
`research_view.user_changed` is that lever, called from `claims.set_status`, `knowledge.set_target_status` and
`knowledge.set_tension_status` — and a failure to drop the cache can never fail the decision, because the status is
the durable thing and the cache is not.

**Named, not fixed:** the pass itself is still tens of seconds at 15,800 Claims, and `knowledge.state` (75 s) and
`claims_view.query` (48 s) have no cache of their own — they benefit only because both call `areas()`. Making the
pass cheap is a separate rung. Gate `tests/test_s22_stale_research.py`.

## A 5.9 MB request, and two passes that ran inside one (0.62.7)

**Measured through Kyle's browser, 17,119 findings:** the Research tab loads from a single request, and that request
had grown to **5,858 KB served in 23.7 s**. By key: `questions` **4,802 KB over 2,703 targets** (2,667 of them open,
so filtering by status saves nothing) · `area_of_claim` **854 KB over 15,499 claims** · watch-outs 146 KB ·
everything else ~60 KB. Inside one question, `actions` alone accounts for 1,311 KB across the list.

Third instance of one defect — **a list nobody re-measured after the corpus grew** (findings were 8 MB before
0.60.1, the sources list 4.6 MB before 0.46.3) — and the two keys needed different answers:

- **`area_of_claim` is dropped outright.** Grep `web/index.html` for it: zero hits. It is an index `areas()` builds
  for its own use, and `claims_view.query` already carries a per-row `area` for the rows on screen. Still available
  behind `area_map=1`.
- **`questions` is bounded, never filtered** — `QUESTIONS_INLINE_MAX` 200, in the same order the Overview's `next`
  list uses, with `questions_total` and `questions_truncated` beside it. The full list pages from
  `GET …/research/questions?offset=&limit=&area=`, and **focusing an area re-fetches for that area**, because an
  area whose questions all sit past the page boundary must not read as empty. The Questions pane also stopped
  rendering every open question as a card — 2,667 cards, the same DOM problem 0.46.3 fixed for Sources.
- The R2 frozen gate asserted byte-equality with the separate endpoints; it is updated with its reasoning recorded
  in HARDENING.md. R2 promised ONE pass instead of four, and that is intact — what is no longer promised is that
  the pass returns every row.

**And `settle_all` stopped running inside the request.** Materialising a cohort is a full findings write per source
— validation, quote checking, note insertion — and recovering Kyle's 410 stranded cohorts took minutes on a
single-process server while writing 1,284 ledger rows. `POST /api/batches/settle-all` now queues a `settle_batches`
job (priority lane, `local_only` because settlement makes no model call — the answers are already in hand), deduped
so a second click cannot start a second settlement, with `background=false` kept for the CLI. Fourth time this week
the fix has been the same sentence.

Gate `tests/test_s21_payload_and_settle.py`.

## Work in flight is still work (0.62.6)

Chasing the last big spend lever, and it was not where I said it was. Two claims of mine died to arithmetic before
the real defect appeared — recorded because both were the kind of thing that reads as obvious:

**"Prompt caching on the batch findings path is broken and fixing it is the biggest remaining saving."** Wrong.
Today's batch findings reconstruct exactly against the ledger ($23.18): **uncached input 57.5%, output 29.4%, cache
writes 12.8%, cache reads 0.3%** — 10,376 uncached input and 1,061 output tokens per call. Turning caching OFF on
that path would cost **$0.03 more**, not less: the 25% premium on 1,855 cache-write tokens per call almost exactly
equals the 90% saved on 540 read tokens. The 5-minute ephemeral cache cannot help a batch that runs for hours, and
the numbers say it also cannot hurt. Input is the transcript and output is the findings — both are the work.

**"71% of findings spend is repeat analysis, so most of it is waste."** Half wrong, and the half that was right is
not waste. 589 of 1,173 sources have been analysed 2–6 times; the first pass over everything cost $107.50 and the
later passes $258.95. But of the 11,154 findings those later passes produced, **91% are genuinely new** at the same
0.35 similarity threshold `findings_quality` uses, and only 9% restate an earlier finding. The cap raise (0.58.1)
and brief edits genuinely produce more from material already ingested, at $0.026 per new finding — the normal rate.
That makes the findings cap a policy dial for Kyle, not a defect for me.

**The real defect was in the residue.** 166 sources were analysed twice *on 2026-09-10 alone*, for **$22.67**, and
every pair had one shape:

```
Copy of Acquisition Ace Deal Calculator
   pass: 13:28 → 13:30    4 windows   $1.768   [local]
   pass: 15:50 → 16:12   12 windows   $1.510   [batch]
   brief_rev d4da9549…  facts_rev 5fb2f4bc…   identical across both
```

15:50–16:12 is when 410 stranded batch cohorts were recovered and settled. Those were submitted, and charged, on
Sep 8–9; the results sat uncollected; and meanwhile the ordinary queue read the same sources again — because
`findings.is_current` only ever consulted the analysis ROW. **Work that had been bought but not yet collected was
invisible to the check whose entire job is to stop paying twice.**

`db.batch_coverage(source_id, input_hash)` answers it with no new state: `findings.batch_requests` already builds a
`custom_id` of `fw-<source12>-<window>-<inputhash12>`, so the same inputs always produce the same ids, and
`submitted` (with the provider) or `succeeded` (persisted here, not yet written) both mean the money is spent.
`suggest_for_source` skips with the reason stated in plain words.

**The hash is what makes the guard safe rather than blunt, and it holds even under `force`.** A stale rebuild, a
brief edit and a deep read all change `input_hash`, so none of them match and none are blocked; a match means the
answer to exactly this question is already paid for and on its way. A gate on the id FORMAT needs a test that fails
if the format moves, so there is one. Gate `tests/test_s20_no_double_read.py`.

## The rung Discover never had: seen, and never read (0.62.5)

Kyle, after four releases of me fixing the matcher: *"what I wanted was to search for content we chose not to
ingest but that the app has seen at some point, like videos that were ranked but not chosen for transcription. if
we do not find things there, then web, youtube, social media, academic papers etc."*

That ladder already existed — `knowledge.pursue` has climbed project → library → candidates → external since G5.
**Discover went library → catalogues → web and skipped the candidates rung entirely.** Measured on his live
database, the rung it skipped is an order of magnitude larger than the one it was searching:

```
seen and never ingested   10,319 candidates + 558 sources skipped at the cutoff
library scope (searched)     387 sources outside the project
```

| query | in the seen pool | what is actually in there |
|---|---|---|
| quality of earnings | 1 | an Acquisition Lab Quality-of-Earnings advisor |
| due diligence | 19 | business-acquisition interviews, all of them |
| sba | 43 | Ben Kelly, Acquiring Minds |
| cpa | 13 + 8 skipped | Hector Garcia CPA, LYFE Accounting, Matt Bontrager |

Against which the library pass offered six short-term-rental tax videos. **The material he wanted was in the
database the whole time, one table away from the one being searched** — and four releases of matcher work could
never have found it, because it was never in the pool being matched.

`candidates.seen_for_query` adds no data model (G3: extend, never duplicate). `candidates.search` is the metadata
FTS; `_potential` is the existing $0 scan that ranks an uncaptured item against THIS project's open questions,
vocabulary and creator yield; sources skipped at the ingest cutoff are searched in the same pass because to a user
they are the same thing. The subject word decides what is searched — a title is a few words long, so ANDing every
query term finds nothing, and 0.62.0's anchor already knows which word names the subject.

**Project grounding enters as RANKING, never as a filter.** That is the distinction 0.62.4's failed experiment
missed: everything found stays findable, and the project decides the order. UI: an "👁 Already seen, never read"
block above the library block, each row with what it is, why it is known, its potential score and a "Read this"
button that queues the existing acquire path. Gate `tests/test_s19_seen_rung.py`.

## Your library is exhausted on this subject, and the card said the opposite (0.62.4)

Kyle, after the anchor fix landed and every result was on-topic for the word: *"discover search still is useless."*
He was right, and it was not a ranking failure. The six results were all real-estate tax videos in a
business-acquisition project. Measured on his live data:

| term | in library | already in THIS project | outside it |
|---|---|---|---|
| cpa | 130 | **115 (88%)** | 15 |
| sba | 212 | 191 (90%) | 21 |
| quality of earnings | 27 | 25 (93%) | 2 |
| addbacks | 7 | **7 (100%)** | 0 |

Library recall can only offer what the project does NOT have (Invariant D), so on its own subject this project has
a pool of leftovers: 8 sources mention "cpa" twice or more outside it, seven of them about short-term rentals. The
list was not a bad ranking of a good pool — **it was nearly the whole pool.** And the card was headed *"In your
library — no new acquisition needed"*, which is a false claim about the dregs, and is what made it read as useless
rather than merely thin.

`library.coverage_of(project_id, term)` reports it and `recall` returns it as `owned`: how many sources discuss the
term, how many this project already holds, how many are left. Above `OWNED_SATURATED_SHARE` (0.6) it says so in
plain words — the subject is already absorbed, the web is where anything new will come from, and the useful move is
to search inside the project rather than acquire more. The header becomes "What is left in your library", and
saturation **never suppresses the web search**: it is the reason to run it.

**Two measured ideas were discarded on the way.** Concatenating the refine text with the project brief is what
0.50.0 already proved wrong (a long query raises the coverage denominator until good passages fall below
`MIN_COVERAGE`). And scoring candidates by overlap with a project-vocabulary model built from term *lift* over its
own sources produced `gov, moneywise, university, smith, kenny, sweatpants` — channel names and noise, and it
separated nothing: all eight candidates scored 0 or 1 of 18. The one-line cause of the off-domain results is still
`_library_query`'s `if refine: return refine`, which throws the project away; the honest fix for that is not a
longer query, and it remains open.

## "Modern CPA" returned house-flipping videos (0.62.0)

Kyle: *"discover feature still isnt working ... NONE of the results are valuable to the search at all."* Every one
of the eight results matched the word **modern**, and the app said so in its own explanation line. Measured on his
live library (1,229 sources with chunks): **"modern" is in 128 sources, "cpa" in 130** — so the anchor rule, which
picks the query's rarest word, decided what his search was about **by a margin of two sources**, and picked the word
that names nothing.

Scored against a target set (sources mentioning CPA 3+ times or in the title — 45 of them):

| rule | returns | on target | precision | recall |
|---|---|---|---|---|
| shipped (anchor "modern") | 128 | 3 | **2%** | 7% |
| require every query term | 11 | 3 | 27% | 7% |
| anchor "cpa", any mention | 130 | 45 | 35% | 100% |
| **anchor "cpa", ≥2 mentions** | 73 | 45 | **62%** | **100%** |

- **The obvious fix was measured first and rejected again.** Requiring all terms looks four times better than what
  shipped and throws away 93% of the right answers. Same lesson as 0.58.6/0.58.7/0.59.3/0.60.2.
- **`ANCHOR_MIN_MENTIONS` = 2 — aboutness, not presence.** 66% of the sources containing "modern" contain it in
  exactly ONE chunk of a whole transcript, against 44% for "cpa". Requiring the anchor twice is +27 points of
  precision **at no cost in recall**: every on-target source mentions its own subject more than once.
  `source_mentions` is the per-source count (cached on the library revision like `sources_with_term`), and
  `ANCHOR_MENTION_MIN_CHUNKS` = 3 turns the floor OFF for a short source, where one mention is a large share of
  everything it contains.
- **`GENERIC_MODIFIERS` is a list, not a threshold, and that is the honest form.** Nothing countable separates
  "modern" from "cpa" here: equal rarity, equally often in titles (2 each), and mentions-per-source prefers "cpa"
  (2.35 v 1.66) but prefers **"designing"** (6.54, in 41% of the library) over both — a coincidence, not a rule. The
  real difference is that "modern" is a modifier: it attaches to any topic in any field and denotes none. Used for
  anchor CHOICE only — these words still match, still score, still count towards coverage — and skipped only while
  another content word survives, so a search made entirely of modifiers gets `all_generic` and the vague-query
  answer instead of an anchor picked from among them. This is an **assumption**, not a measurement, and belongs in
  the assumption ledger.
- **Two share bars, because they are two different claims.** `ANCHOR_TOO_COMMON_SHARE` 0.5 ("in MOST of the
  library") is absolute — 9 sources in 11 really is most — so it is never guarded. `ANCHOR_MAX_DF_SHARE` 0.25 (was
  0.5) is a CALIBRATION against the measured distribution (accountant 49.6%, designing 40.8%, improving 26.6%,
  seller 25.6%, complex 20.9% · workflows 14.3%, auditing 11.6%, cpa 10.6%, ui 10.2%, ux 5.9%, laundromat 5.3%,
  reusable 2.4% — everything that names a topic sits at or below a quarter), so it waits for
  `ANCHOR_SHARE_MIN_LIBRARY` 40 sources. 0.62.0's first attempt guarded BOTH and silently switched off the
  generic-query judgement in small libraries; the frozen 0.61.0 gate caught it.
- **Discover finally has the weak-query judgement.** It was built in 0.61.0 and lived only in the project-bootstrap
  scan, which is why Discover answered a vague search with eight confident rows. A vague search now says so above
  the results, every hit is tagged `generic match`, none can be `strong`, and none can suppress the web search —
  nothing is hidden, it is labelled. `bootstrap.query_strength` treats `all_generic` exactly like `too_common`.

Gate `tests/test_s16_anchor_aboutness.py`.

## The Findings workbench assembles its rows once (0.61.4–0.62.0)

`/findings` measured **23.2 s cold / 4.3 s warm** on the 16,962-note project after the lock-up work, then **9.3 s /
19.9 s** at 0.61.4 — *warm slower than cold*, because 0.61.4 cached the whole assembly on `db.project_view_revision`,
which is the SOURCES fingerprint and carries a global `jobs` component: during a run it moves whenever any job
anywhere does, so an assembly costing seconds was retired before it could be reused. The quality-pass failure one
layer along, and the same sentence applies — a cache whose key changes faster than its value can be computed is not
a cache.

Split by what each part actually depends on. `findings_view.rows_only` (the notes with their citations parsed) is
keyed on the new **`db.project_notes_revision`** — count, newest, and a count per status, which moves when a finding
lands or a status changes and *not* on a job heartbeat. `findings_view.decorations` (plan/chat/Claim use, source
staleness, research area) stays on the full view revision, because that is what it genuinely depends on, and is
stale-tolerant: a badge a moment out of date is honest, a status the user just changed is not. It blocks only when
the user filters or sorts ON one of those dimensions — then they have asked for it. `warm=True` on a cold project is
deliberate: an empty map would read as "never used", which is a false statement rather than a slow one. The reply
carries `badges.known/current/pending` and the workbench prints "still being counted" or "from a moment ago" rather
than an unknown as a zero.

## Library recall: the rare word decides (0.60.2)

Kyle, testing a new AI-UI/UX project against a library built mostly from business and real-estate research: *"it
clearly is pulling bad data ... is this searching against the global library? global library is useful but only if
its utilizing the projects criteria/brief/tags/chat."* The Starting-Research card offered **"How To Make $3,000/mo
From Airbnb With $0"** as the project's one **strong** match, pre-ticked. Three faults, all measured on his own
library (1,219 sources with chunks, the query he actually typed):

- **`library._tokens` required three characters, so "ux" was never a query term.** The UI's own line said "2 of 3
  query terms" — the query had silently become "enterprise complex workflows". Two-letter words are the domain
  anchors of whole fields (ux, ui, ai, qa, 3d). Now two characters, must contain a letter (so "2026" is not a
  topic), and `bootstrap._content_tokens` delegates to it so the two cannot drift apart.
- **Coverage counted the UNION of the best three passages**, so a source could cover a query by mentioning
  different words in three unrelated places: 44 of the 63 passing sources did so only that way. `recall` now also
  reports `passage_coverage` (the best single passage), and `bootstrap._band` requires it for **`strong`** — the
  band that gets pre-ticked, so the one that misleads.
- **Every term counted the same**, so matching the two most generic words was enough. `query_anchor` picks the
  query's rarest term — counted in SOURCES via `sources_with_term` (one long video repeating a word must not make
  it common) — and a source that never says it anywhere is not suggested, with the count reported
  (`rejected.no_anchor_term`) and the reason in plain words.

**The obvious fix was measured first and does nothing.** IDF-weighting the terms rejects **none** of the 63: his
query's words have similar rarity (idf enterprise 2.62, ux 2.95, complex 1.80, workflows 2.79). The anchor rule
takes 66 → 25 and `strong` 8 → 1 (Pencil & Paper, a UX design studio), rejecting Alex Hormozi ×4, a laundromat
podcast, "How AI is breaking the SaaS business model" and "If I Wanted to Become a Millionaire in 2026". Same
lesson as 0.58.6/0.58.7/0.59.3: the plausible fix was mine, and the data said otherwise.

Two guards, both of which turn the rule OFF (so neither can invent a false negative), and both structural
judgements rather than calibrations: `ANCHOR_MAX_TERMS` 8 — a whole brief is prose, not a phrase, and its rarest
word is incidental (`bootstrap._clauses` already splits a goal for the same reason); and `ANCHOR_MIN_SOURCES` 2 — a
word only one source uses cannot separate topics, and requiring it made the rule reject every hit in the
nine-source test fixture. The anchor is checked against the **whole source**, not the three retrieved passages: a
source can be about your distinctive term without using it in the chunks that happened to score highest, which is
a property of retrieval, not of the source. **Tags now feed the scan** (`queries_for`) — the cheapest of the
project signals he named, and simply never read. Chat and research state are a separate decision. Gate
`tests/test_s12_recall_precision.py`.

**Suggested links are checked for free (same release).** *"discover is routinely suggesting content that has 404
issues"* — with `https://37signals.com/blog` failing in the queue after he pressed Add. A URL from Discover's first
pass is a *remembered* address, and the paid `discover.verify` is a model with a search tool being asked whether a
list is fine, which it says more readily than it should. `discover.check_link` / `check_links` ($0, bounded, same
`safe_fetch` boundary, 4 threads, `LINK_MAX` 24) records the answer on the row (`discoveries.link_check`), and on a
404 tries the site root once and OFFERS it — never substitutes it, because a machine must not rewrite a URL a
model proposed. A dead row loses its Add button and says "that address is gone"; a **403 keeps its link** and says
the page is probably there, because a server refusing us is not a missing page.

## Sharing without the research (0.60.0)

Kyle: *"our chats are really good for depth and citing sources ... but when I want to share with my wife or a
friend, they will not care about the sources, the names of the people and what they said."* That is a different
READER, not a shorter answer, so `qa.share_variant` gained `mode=`: `cited` (C0, unchanged, the default — markers
kept, sources re-attached by the client) and **`plain`** — no markers, no creator or source names, none of the
research vocabulary (`PLAIN_TELLS`: "according to", "the transcript", "one source"), copied as text alone because
attaching the source list is the thing it exists to remove. `qa.share_conversation` does the same for a WHOLE chat
(`conversation_material`: newest turns within `SHARE_CONVERSATION_CHARS`/`_MAX_MESSAGES`, truncation reported, one
call over what was already written — never a research pass). `POST /api/conversations/{id}/share`; Share ▾ gains
three plain entries and the chat header a "Share this chat ▾".

**The uncertainty may not be laundered.** Stripping the machinery makes a text message sound settled for free, so
the original is read with the provenance vocabulary (`HEDGE_RESEARCH`) and the retelling with ordinary words
(`HEDGE_PLAIN`) — if the first hedged and the second does not, the result says so and points at the cited version.
Conditions ("only when it is on full standby") are deliberately NOT hedges: a warning that fires either way gets
ignored. Names, markers and tells are **checked, not merely requested**, with one corrective retry naming what
leaked; markers are then cut outright, a name can only be reported, because a name cannot be removed from a
sentence. And the chat prompt now forbids opening praise outright ("great question"), so the preamble is not
written in the first place — Tier 1 chat totals re-frozen 196,951 → **200,052** (calls unchanged at 34), migration
chat arm 210,014 → 213,112, the seventh such re-freeze. Gate `tests/test_s10_plain_share.py`.

## Screens that were never re-measured at 12,000 findings (0.60.1)

Kyle: *"when I see 'XYZ suggested findings waiting for review' and click on it, it takes me to findings tab, but
nothing loads."* Two faults, one symptom, and the same shape as the Sources view before R2 — a payload nobody
re-measured after the corpus grew.

- **`/api/projects/{id}` returned every finding in full.** Measured on his database: 10,384 approved + 1,383
  suggested, **~8 MB**, fetched by the Findings, Chats, Settings and Plan views before any of them drew anything.
  Now bounded by `api.NOTES_INLINE_MAX` (200) with `?notes=all` for a caller that needs everything, plus exact
  `counts` (`db.note_counts`, one GROUP BY) and `notes_truncated` — truncation is never silent. The Findings view
  also stopped downloading every source (`limit=2000`) just to count what was being read: `analysing`
  (`db.sources_being_analysed` + `db.analysis_jobs_queued`) comes from the server.
- **The yellow link only switched tabs**, landing in whatever filter the workbench held (normally `approved`).
  `openSourceSuggestions(sid, status)` sets `FB.source` + status, so it lands on that source's suggestions, with a
  chip to clear it. The Suggested block is now the same server-paged query the workbench uses and says when it is
  showing a page ("the 100 most important of 1,383") rather than implying it is showing everything.

Also from the same session: **Discover's add buttons all look the same** (the colour used to depend on `d.kind`,
which encoded nothing a reader could see) and **every add acknowledges the click** — disabled, "⏳ adding…", then
"added ✓" plus a toast, restored on failure, since the work is queued and there is nothing else to show. And the
**Sources progress box collapses** to what is actually moving (running, failed, bumped, banners) with one line
counting the rest — it changes what the box draws, never what the workers do. Gate
`tests/test_s11_findings_tab.py`.

## Cost per unit of value (0.59.3)

Kyle, after the overnight run: *"the volume of data is always valuable, just HOW is something we want to keep
checking that we are improving against."* `totals` says how much, `reconcile` says how much was really charged,
`rate_last_hour` says how fast — none of them says whether the money bought anything, so raising the findings cap
from 12 to 20 could only be judged on whether the bill went up. `cost_value.py` ($0, deterministic, no model call,
no network) divides spend by **things the project can use**: a finding written, a finding kept, a finding
corroborated, a Claim tracked, a Claim normalized, a source read, a chat answer.

Three rules:

- **Spend is attributed by kind, never spread.** `$ per finding` divides the `findings` spend by the findings
  produced, never the whole bill. Every kind no unit claims is named under `unattributed`, and
  `attributed + unattributed == total_charged` for the window — the report reconciles against the bill instead of
  explaining part of it.
- **Charged, not recorded** (0.59.0): a row costs `cost` plus, when the local path is billed, the `saved` it booked
  instead. Dividing recorded-only spend by output would have priced every local finding at $0.
- **A count of zero is not a cost of infinity.** Spend with no output gives `per_unit: None` with the reason;
  output with no spend gives `0.0`, because a harvested Claim really is free.

**The measurement, running the shipped module against a snapshot of Kyle's own database (2026-09-10 05:58, month
to date):** $367.20 charged — `findings` $205.34, **`claims` $114.25 (31% of everything, the second largest line
and nobody had looked at it)**, `rank` + `whisper` + `embed` $26.59, `answer` $16.13, and $4.89 across
discover/plan/profile that no unit claims (1.3% unattributed). Per unit: **$0.0167 per finding written, $0.0174 per
finding kept, $0.0150 per normalized Claim, $0.0219 per source read, $0.155 per chat answer.**

**And the first thing it did was contradict me.** Reading a five-hour-old backup earlier in the pass, cost per kept
finding for 2026-09-10 came out at $0.0089 against $0.0168 the day before, and I wrote that down as the cap raise
and the local path paying off. Against the 05:58 snapshot the same day is **$0.0259 — the most expensive day of the
month per kept finding** ($0.0054 Sep 7 → $0.0157 → $0.0168 → $0.0259), and **97.5% of that day's charge is the
local path**, which is priced from tokens rather than metered. So the honest reading is the opposite of the one I
had already typed: nothing here shows the cap raise making findings cheaper per kept finding, and the local path
being billed is pushing the number up. That is the whole point of the panel, and it is why `estimated` sits next to
every window.

**It found a reporting bug in the ledger before it found anything about the models.** A naive per-model split said
findings cost **$0.0231 each on Haiku against $0.0071 on Sonnet 5** — Haiku, at a fifth of the token price, three
times dearer. The cause is `usage.record_anthropic`'s local branch: it writes the model the CLI *returned* into
`model` and prices the tokens at the **contract's** model, because avoided spend is only meaningful against the
model that would otherwise have run. All 513 local Haiku findings rows were Sonnet-priced. Printed as a per-model
verdict that reads as a reason to stop using Haiku, which is the opposite of what the data supports. So:
`usage.price_model` (new, additive) records the basis from now on, and `cost_value.price_basis` reports, per model
that did the work, which models' rates produced its dollars — **a row whose basis is foreign or unrecorded carries
its cost and its count but no `per_unit`, with the reason stated.** A number that cannot be trusted is not rounded
down, it is withheld.

Also reported: `estimated` — a local row's dollars are priced from tokens, not invoiced, so the share of a window
resting on that estimate is stated. `by_model` supports only the units whose OUTPUT records its model
(`project_notes.model`, `project_claims.model`), which is what makes a Haiku-vs-Sonnet decision checkable after the
fact rather than only in an eval. `findings_quality.corroborated_ids` (cached on the view revision like `review`)
is the index behind `$ per corroborated finding`; it is opt-in (`include_quality=1`) because it is a ~4 s clustering
pass. API `GET /api/usage/value[?window=|project_id=|days=|include_quality=]`, `…/value/by-model`, `…/value/trend`,
`…/value/report`; Health `cost_value` plus a "💵 Cost per unit of value" button in the Health console. Gate
`tests/test_s9_cost_value.py`.

## Account walls stop the queue (admission, 0.59.0)

`db.claim_job` consulted the background pause and the rate gate but **not** the account gates, so a walled account
did not stop the queue — it walked the queue through the wall: claim a paid job, get refused in 0.4 s, park it for
30 days, claim the next. Measured: **624 `BILLING` attempts on 2026-09-09 and 48 `SPEND_CAP` attempts inside 13
minutes on 2026-09-10.** Free, but it consumed worker slots free work could have used, made the Jobs panel read as a
catastrophe when the truth was "the account is capped", and buried the real spend rows in hundreds of refusals.
`db.account_gate_active()` + `ACCOUNT_HELD_POLICIES` (`api_requested`, `api_only` — unlike the rate ceiling this
holds `api_only` too, because nothing on the API can succeed); local and free work continues. A corrupt gate value
fails OPEN. Smallest useful slice of `SCHEDULER-ADMISSION.md`. Gate `tests/test_s6_account_admission.py`.

## Findings quality — the trash filter (F1–F3, 0.58.0)

`findings_quality.py` ($0, deterministic, **no model call, no network**) is the mechanism Kyle's objective
(*"as many findings as possible provided they aren't trash"*) needed and the app did not have: on 2026-09-10 his
live database held 13,480 findings, 12,614 auto-approved and **twelve** ever dismissed, with nothing anywhere
checking whether a finding was vacuous or a restatement of one already held. The length-aware cap in `findings.py`
was the only thing standing between him and noise, and it withholds findings already paid for (`reserve`) on the
basis of source length — a proxy for quality that knows nothing about quality. This module is the real check the
cap was standing in for, which is what makes relaxing the cap (F4) safe.

`vacuity(note, source_title)` → named rules (`no_specifics` · `too_short` · `echoes_title` · `generic_only`);
`clusters(notes, usage)` → union-find over content-word 3-gram Jaccard (`NEAR_JACCARD`) and near-containment
(`CONTAIN_RATIO`), each group naming a **keeper** and its duplicates. **Calibrated against the live corpus (0.58.6), and it found two bugs in the shipped guesses:** `CLUSTER_MAX = 400`
compared only a project's first 400 findings, so a 10,380-finding project containing byte-identical duplicates
reported ZERO — replaced by blocking on rare content words (`BLOCK_DF_SHARE` 2%, `BLOCK_MIN_NOTES` 600 below which
everything is compared); and `NEAR_JACCARD` 0.62 → **0.35**, measured by sampling the similarity bands (0.35–0.45
are all true duplicates, 0.25–0.35 is mixed). `PAIR_BUDGET` 400k → 8M because at 400k the pass logged itself as
partial. Result on the real corpus: **441 duplicates in 360 groups, 4.2%, in 5.0 s** (0.58.8 added `SET_JACCARD` 0.50 — a set/bag-of-words measure that catches PARAPHRASES shingles miss, worth +249 duplicates on its own) — so `review()` is cached on
`db.project_view_revision`. The vacuity rate is 0.03% and that is CORRECT: his findings are specific, and the trash
problem was never filler. **And it publishes its own floor (0.58.8):** three genuine duplicates found by hand score 0.33 / 0.20 / 0.18 on
every lexical measure here, below any threshold that would not also flag findings which merely share vocabulary. So
`review()["limits"]` says out loud that it reports a FLOOR on duplicates and never a ceiling, and catching
paraphrases properly would need embeddings (~$0.013 for 13k findings) — a measured decision for Kyle, not an
assumption. Evidence and the band tables are in HARDENING.md.

Lexical, not semantic, on purpose: findings
have no embeddings (only chunks do), so a semantic pass means an embedding call per finding — real money on 13,480
rows for a filter whose job is to save money. `NEAR_JACCARD` is where a measured semantic comparison would land.

**There is no quality score, and nothing is ever changed.** `review()` returns a list to sweep; the only door to a
status is the existing `POST /api/notes/bulk-status`. Four protections: a finding used in a plan step, a chat answer
or a Claim is **never listed** (`findings_view.usage_map`); one rated 4+ or already judged by hand is listed but
never pre-selected; a cluster always keeps one member; and a finding whose only complaint is length while it still
names something checkable is never pre-selected — brevity is not vacuity. API
`GET /api/projects/{id}/findings/quality[?summary=1|include_used=1]`; UI a 🧽 banner + review dialog in the Findings
workbench, on **both** `approved` and `suggested` (0.58.9 — before you approve is where it helps most, and 283 were sitting in that status). Health carries the per-project counts (`db.health()["findings_quality"]`), labelled as a floor. Gate `tests/test_s3_findings_quality.py`.

**F4 — the cap goes back to one job (0.58.1).** `findings.CAP_BASE/CAP_PER_WINDOW/CAP_MAX` are now env-configurable
and their defaults are **20 / 12 / 200** (were 12 / 8 / 120, kept as `CAP_DEFAULTS_BEFORE`). The cap had two jobs:
stopping a book from burying a project (real) and quality control (which it was never equipped for — it withheld
findings already paid for on the basis of source *length*). F1–F3 answers the quality question, so the cap keeps
only the first job. Measured justification: length-matched to 10–40 minute sources on Kyle's live corpus, Haiku
produced 15.6 findings/source against Sonnet 5's 11.3 and the raw 8× reserve gap collapsed to 0.6% → 1.1% once
length was controlled — the old base of 12 was clipping ordinary sources, not just books. `select_findings` is
monotone in the cap (a larger cap only moves rows from `reserve` to `suggested`, never the reverse, never loses
one), so raising it can only add. Reversible with no code change:
`NEUROSEARCH_FINDINGS_CAP_BASE=12 NEUROSEARCH_FINDINGS_CAP_PER_WINDOW=8 NEUROSEARCH_FINDINGS_CAP_MAX=120`.
Health reports the current cap, whether it was raised, and how to revert (`db.health()["findings_cap"]`).

**Duplicates are not all waste (0.59.0).** Kyle: *"even duplicate data is useful somehow."* Correct, and the app
already said so — `claims.assess` counts independent sources agreeing as **corroborative sufficiency**. So a cluster
means two opposite things: one source repeating itself is `redundant` (sweepable), several sources agreeing is
`corroborated` — evidence, never offered for dismissal, protected ahead of every other rule, and reported as a
positive (`review()["corroborated"]`). The largest cluster in Kyle's corpus is one SBA pre-screening fact from FOUR
creators; the first version offered all four for the bin. In `promotable()` this inverts the old rule outright: a
withheld finding that restates an approved one **from a different source** is the most valuable thing in the reserve
pile, sorts first, and corroboration outranks a vacuity flag. `NUMBER_WORDS` also fixed a real false positive —
"finance ten percent of the purchase price" was `no_specifics` for want of a numeral.

**F5 — what the cap already withheld (0.58.5).** F4 raises the cap for FUTURE sources; `findings_quality.promotable`
answers the other half — of the `reserve` findings already paid for and withheld, which would you actually want? A
reserve note is offered when it is not vacuous **and** not a near-duplicate of something already approved, and that
second test is why this is not "promote all": `clusters` runs across BOTH statuses, so a reserve note restating an
approved one is skipped rather than promoted into a duplicate. Promotes nothing itself — the sweep is
`POST /api/notes/bulk-status`. API `GET /api/projects/{id}/findings/reserve-promotable`; UI a 📥 banner (with
Approve-all) that replaces the 🧽 banner while the workbench is showing `reserve`.

## Research catalogues (0.57.0)

`scholar.py` ($0, **no model call anywhere**) is Crossref + OpenAlex behind one record shape. It exists because
`discover` proposes sources from a model's memory and then PAYS `discover.verify` (web-search tool) to check they
are real — a catalogue record is real by construction, so this pass makes Discover **cheaper**, not dearer.
`search`/`resolve_doi` go through `safe_fetch` like everything else (no client library, no second boundary);
`available()` is config only and never probes, so Health cannot spend someone else's free service.
**Credentials:** Crossref needs no account (`NEUROSEARCH_SCHOLAR_EMAIL` only earns the polite pool: 10 req/s single,
3 req/s list, since 2025-12-01); **OpenAlex has REQUIRED a free key since 2026-02-13** (`OPENALEX_API_KEY`; the
`mailto` parameter and the polite pool were retired for credits — unkeyed callers get 100 credits then HTTP 409), so
without it `ready_providers()` returns Crossref alone rather than failing mid-query. Semantic Scholar is
deliberately NOT implemented (overlaps OpenAlex, unauthenticated search fails in practice, a key buys 1 req/s).

**A record is metadata, never evidence.** Records become `candidates` (seen, not acquired — `url` is the OA PDF when
one exists so an Acquire click has something to ingest, `canonical_url` is always the DOI as identity) or
`discoveries` (`kind="paper"`, `verified_by=<provider>`, `fit` 4 with free full text / 3 without — never a confident
score invented from a relevance rank). Only `best_oa_location.pdf_url` / `open_access.oa_url` becomes a source, via
the ordinary `ingest_url` document path. Three wires:
- **Discover** — `scholar_pass` runs before the model pass and its results skip `discover.verify` entirely. It is
  gated by `scholar_wanted`: the user asked for literature (`SCHOLAR_HINT`) **or** an open evidence target declares
  `expert`/`authoritative` in `preferred_classes`. A corpus of YouTube channels about editing workflow gets nothing
  from Crossref, so it is not queried — that gate is the feature. New mode `scholar_only` needs no Anthropic key.
- **Gap** — `knowledge.pursue` gains a free `catalogue` step BEFORE the paid external Discover job
  (`scholar.for_target`), and only for targets that want literature; every hit is `candidates.link`ed to the target.
- **Ingestion / identity** — `works.find_copy` resolves a `scheme="doi"` identifier through the catalogue, so the
  long-standing *"resolved identity, unresolved access"* outcome can become `access="open_access"` with a queued
  ingest. A catalogue outage never changes the resolution outcome. `resources.classify` was NOT touched: a DOI
  already routed to `resolve`, which is the rule (extend, never duplicate) honoured by doing nothing.

API `GET /api/scholar/status`, `POST /api/projects/{id}/scholar/search`; Health `scholar`. Gate
`tests/test_s2_scholar.py` (28, all against a canned `safe_fetch` — no network).

## Universal resource input (G2, 0.26.0)

`resources.classify(text)` → `Classification(kind, actions, default_action)`; `resources.route(c, project_id, action)` → only standard paths (`ingest_url` review/non-review, `discover`). Containers (website, section, sitemap, feed, repository, community, folder) expose `explore` as an *unavailable* action until their rung ships and are fetched as a page only on an explicit `page` choice; chat returns them as `detected`. API: `POST /api/classify`, `POST /api/projects/{id}/add`. Never add a second classifier: extend `classify` and give the new kind actions.

## Global Library Intelligence (G4, 0.28.0)

`library.py`: `baseline(source_id)` ($0, cached, revision-aware; metadata + own top terms + deterministic `authority_signals` with basis + centroid (coarse) + farthest-point topic vectors) · `recall(project, query)` = chunk-level retrieval over ready sources OUTSIDE the project → grouped suggestions with passages/why/signals (never attached; works with zero enriched profiles — gated) · `want`/`enrich`/`enrich_wanted` (lazy `library.profile`, schema `source-profile-v1`, provenance + routing, stale on revision change) · `maybe_queue_batch` → `enrich_profiles_batch` job on the Rung G batch machinery. **Never** build a global profile from project findings/summaries/relevance; never enrich the whole library. `discover(mode=)` is library-first; chat tool `search_global_library`. Recall requires absolute term coverage (`MIN_COVERAGE`/`STRONG_COVERAGE`, 0.28.1) so off-topic questions return nothing. **Structured-output schemas must not carry string-length constraints** — `provider_schema` strips them, so the model cannot honour them and the result fails locally after being paid for (0.28.2 lost a 30-item batch this way).

## EPUB Core + Structure (G6P1 0.34.0, G6P2 0.35.0)

`epub.py` ($0, stdlib): `read_epub` = container → OPF (scan fallback) → metadata (title/subtitle/creators/publisher/language/date/modified/identifiers/ISBN/subjects/description/rights/package id/edition hint) → **spine order** (never ZIP order) → TOC (EPUB 3 nav or NCX; missing → headings + warning) → `_sections_of` per content document (split at h1–h4; anchor = heading id or nearest preceding id; roles from `epub:type`/titles) → `locators(book)` with `label` "Ch. N → Chapter · Section". `EpubProtected` when `encryption.xml` covers a content document — refused, never circumvented. `ingest.ingest_epub` (from `ingest_local_file` on `.epub`): platform `book`, one segment per section, chunks never cross a section, `book_sections` table, Work link by ISBN or title+creator (`form="epub"`, existing Work reused). Citations everywhere use `search.locator_for` → the structural label + an in-app deep link `#book/<source_id>/<ordinal>` (the UI's 📖 Read dialog opens at that section; Contents tree from `/api/sources/{id}.sections`). **G6P2:** `epub.ROLE_WEIGHT` multiplies a book chunk's retrieval score by its section's role (index/copyright never outrank the chapter; nothing discarded) and `findings._windows` skips `SKIP_FOR_FINDINGS` pages and orders body before back matter. Gate `tests/test_m1_epub.py`. Images/tables are text-only until G8.

## Browser-assisted acquisition (B1, 0.33.0)

`acquire.py` — `requires_browser` is a GENERIC capability state, never a Reddit state: an `AcquisitionFailure(adapter, cls)` is browser-solvable only when the adapter's row in `ADAPTERS` says so (reddit_thread: blocked/login_wall/challenge; web_page: + js_required/empty_render; document/youtube: never). `jobs.execute` parks such an `ingest_url` job `external_pending` (provider `browser`, handle = canonical URL, 14-day deadline that never fails the job) with a pending placeholder source (`sources.error_class = browser_solvable:<cls>`, plain-language `error`) so the project keeps it; the extension posts the capture (`POST /api/capture/{job_id}`: `reddit_thread_capture/1` = thread + comments + capture diagnostics, or `page_capture/1` = html) → `db.resume_external` → the SAME job re-runs `ingest.ingest_url(capture=)` and completes the SAME source. `/ingest/thread` and `/ingest/html` resolve a waiting request for the URL first. Global Library first: an owned thread the server cannot re-read is attached, not sent to the browser. Queue `GET /api/capture/pending`, presence `POST /api/extension/heartbeat` (kv only), `GET /api/projects/{id}/attention`. Extension 1.5: `background.js` heartbeat + badge, popup "wants this page" + contract producers (same-origin JSON first, rendered DOM fallback); the server is the only normalizer (`community.thread_from_capture`). Never put cookies in a capture; the session-cookie path stays `with-session`. Gate `tests/test_l1_browser_capture.py`. **B2 (0.33.1):** `community.completeness` → `sources.completeness` JSON (complete / partial / unknown; captured vs expected; `more` stubs; method) — a successful capture ≠ a complete one; a partial capture MERGES (never deletes what an earlier reading saw; only a complete reading marks vanished posts); `POST /api/sources/{id}/accept-partial` (accepted, never complete) and `/recapture` (forced re-read → the same source; the browser when the server cannot). Gate `tests/test_l2_completeness.py`.

## Community evidence (G7, 0.32.0; Reddit page fallback 0.32.2)

`community.py` — community is an EVIDENCE CLASS: a thread is ONE source (platform `community`, adapter by host; Reddit: **since 2026-06-30 Reddit blocks every non-browser reader and login-walls old.reddit**, so the readers are (1) the browser extension — "Send this page" on a thread fetches its `.json` in the user's browser and posts it to `POST /api/projects/{id}/ingest/thread` → `community.acquire_thread(listing=)`; (2) Reddit's official API via app-only OAuth when `REDDIT_CLIENT_ID`/`REDDIT_CLIENT_SECRET` are in `.env` (`_api_get` on oauth.reddit.com; the only server-side path for Explore). The unauthenticated `.json` ladder and `reddit_html.py` (old.reddit page → same thread/search shape) are kept but expected to fail; errors name each reading and the way forward; gate `tests/test_k9b_reddit_html.py`), posts are locators in `community_posts` (tree, author, self-described context never verified, score, edited/deleted/availability, corrections attached to what they correct, retrieved_at, revision). Deterministic multi-dimensional `signals` (never a trust score; upvotes = reaction), `prune` (jokes never become evidence; the tree stays), one chunk per post with the correction/injection markers in the retrievable text. `missions` from research state (MISSING_PERSPECTIVE → regret language), `explore` = metadata → Candidate Index → mission rank → review → acquire through `ingest_url`. `synthesize` = derived cross-thread states with exact provenance, recomputed on research refresh. Claims: post author = creator; firsthand by different people = independent; shared link = one lineage; community can never establish a governing rule (insufficient authority). Gate `tests/test_k9_community.py`.

## Canonical Works & Source Resolver (G6, 0.31.0)

`works.py` — GLOBAL `works` (family) → `work_versions` (first-class editions with `supersedes_id` + `change_kind`) → `work_manifestations` (typed relation to a source or candidate; `access`) ; PROJECT relevance only in `project_works` (never on the Work row). `extract_identifiers` ($0: SOP, IRS Pub, U.S.C./IRC/C.F.R., forms, DOI, ISBN) → `ensure_work` by the frozen signal order (identifier → exact normalized title+creator for non-regulatory kinds → new stub; **regulatory kinds never merge on title**) → `index_source` / `cite` / `find_copy` (project → library → candidates → external on request; outcomes incl. *resolved identity, unresolved access*). **Independence by lineage:** `claim_evidence.lineage_id`; copies/excerpts/quotes/derivatives of one Work are one line, the best primary manifestation represents it; a governing Claim resting on a quote while a primary is obtainable is not Strong. Freshness by version relationship (unknown/supersedes → needs_refresh, material → stale, rehost → nothing). `resources.classify` routes any identifier to `resolve` (never auto-acquires; `acquire` is explicit). Chat tool `resolve_work`. Gate `tests/test_k8_works.py`.

## Research Intelligence (G5, 0.29.0)

`claims.py` + `knowledge.py` = project research STATE (never library state). Claims are harvested for $0 from findings (`harvest`: a finding whose proposition already exists becomes evidence for that Claim; independence by passage overlap / creator), assessed deterministically (`assess`: **governing** sufficiency — one current authoritative source is Strong; **corroborative** — independent sources count, derivatives don't; Claim-relative freshness (`freshness_class` per `claims.FRESHNESS_RULES` → `freshness_status` current/needs_refresh/stale/uncertain/age_insensitive, a field separate from strength; the $0 guess errs to `uncertain`, never a false stale); `readiness` is separate from `strength`; every verdict has `strength_why`), and normalized lazily by the one contract `claims.extract` (schema `claim-set-v1`, groups of 20, idempotent by `extraction_hash`, queued by `maybe_extract` after findings jobs with a debounce — **never a paid call per finding**; the whole rung must work with zero extraction calls). Normalization is never corpus-wide: `claims.select_cohort` + `run_evaluation` (bounded, durable, measured — merges, hedges kept, over-generalizations, `imposed_by`, cost) is how it earns wider use; long-term lazy and importance-driven. Evidence rows freeze `source_revision` + `locator`; `db.replace_transcript` stales them. `knowledge.pursue(target)` is the mandated escalation project → `library.recall` → `candidates` (reranked against the TARGET, skipped ones resurfaced) → external (only on request); tensions NOVEL/CONTRADICTION/WEAK_CONSENSUS/STALE/MISSING_PERSPECTIVE; the map's `why` never counts sources. User facts (`record_fact`) are not Claims; `propose_claim` is for external assertions. Model output is proposed state: `status`/`application` change only through `claims.set_status`. Frozen gate: `tests/test_k6_claims.py` (10-point fixture).

## Deep content (D1–D3, 0.43.0)

`findings.py`: the suggested cap is length-aware (`cap_for` = 12 + 8/extra window, max 120; `COVERAGE_FLOOR` 3 per window via `select_findings`); overflow becomes **`reserve`** notes (never exported/planned/harvested; promote via note status; `GET …/notes?status=reserve`). **Read deeper** (`depth="deep"`): `DEEP_WINDOW_CHARS` 20k + `DEPTH_INSTRUCTION` in the user message only; `input_hash(…, depth)`, `project_source_analysis.depth`, `is_current(…, depth)`; `POST …/suggest {depth}` interactive only. `is_long` / `under_read` drive the Sources "📚 Deep content" chip. Mission doc `SOURCES-FINDINGS-MISSION.md` (S1–S5 queued). Gate `tests/test_n3_deep_findings.py`.

## Research view engine (R1/R3/R5/R6, 0.37.2)

`research_view.py` ($0, deterministic, no model calls) is the contract the redesigned Research tab renders (`RESEARCH-MISSION.md`, `RESEARCH-TAB.md` §7): `overview` (summary · ranked `next` across open questions + watch-outs · recently improved · `attention` · areas), `questions` (targets in plain language with cost-labelled actions), `watchouts` (tensions grouped into issues by kind × area, `underlying` for drill-down), `areas` (Jaccard clusters over multi-word topic nodes, named from those labels; tiny topics fold whole; lone-word bulk topics are placed Claim by Claim, the unplaceable in **Everything else**; `area_of_claim` is authoritative). Scoring constants live at the top of the module and are documented in RESEARCH-TAB.md §7; `attention` is what needs the user, never the Claim count (`#nResearch`). Endpoints `GET /api/projects/{id}/research/overview|questions|watchouts|areas`. Gate `tests/test_n1_research_view.py`. **R2 the shell (0.44.1):** the tab renders every pane from ONE request — `overview?full=1` returns the same questions/watch-outs/areas/`area_of_claim` in one `_load()` pass — with the heavy `/research` state lazy behind the Claims and Research-tools panes; panes Overview · Open questions · Watch-outs · Areas (Focus filters the others and the Claims workbench) · Claims · Research tools (the old map/tension/target lists, nothing removed); `POST /api/projects/{id}/tensions/bulk-status` gives a whole watch-out ISSUE one durable verdict. Gate `tests/test_n8_research_shell.py`. **R7 the Claims workbench (0.45.5):** `claims_view.py` — R2 moved the Claims tab under the shell but never rebuilt it (still `knowledge.state()`'s 300-cap raw list); `query()` filters/facets/sorts/pages the FULL claim set with one plain-language line per Claim (`plain()`: strength/freshness/status → a sentence, no glossary), `bulk_status()` = batch accept/reject, project-scoped, one refresh; `GET/POST /api/projects/{id}/claims[, /bulk-status]`. `for_source()` = "Why this answer" on a chat citation (`GET …/claims/for-source`, closest-locator match first); "Settle this" on a chat gap reuses the existing `/targets` endpoint, not a parallel path. Gate `tests/test_o2_claims_workbench.py`. **S6+R8 grouped views (0.45.6):** Sources/Findings/Claims lists now group instead of running flat — Sources by `channel` (already set per-platform: YouTube channel, subreddit, book creators, page domain), Findings by source (grouping existed since 0.43.0, only collapsibility was missing), Claims by the same `area_of_claim` the Overview/Areas panes use (`claims_view.query` now computes it unconditionally, not only when filtering to one area). `<details class="fgroup">` per group with remembered collapse state (`SRCG`/`FGRP`/`CWG`), Expand-all/Collapse-all, and a search or active filter always forces every group open. No schema change; PRODUCT-ORGANIZATION.md #1 taken narrowly (grouping only — #8 rescanning, #19/#21 adaptive triage and findings dedup stay NOT BUILT). **S1 fix — skipped-source metadata + backfill (0.45.7):** `ingest.ingest_source`'s cutoff-skip branch now saves the metadata `media.fetch_info` already fetched (thumbnail, channel, published date, description) instead of discarding it; `api_sources` runs the same `candidates._potential` scan `pool()` does for every `skipped` row, attaching `pool_potential` (`score`/`fits`/`why`) so the plain Sources list — not just the separate pool view — shows whether a pre-cutoff source is still worth ingesting. `ingest.refresh_skipped_metadata` + `POST …/sources/refresh-skipped-metadata` ("🔄 Refresh info" button) backfills thumbnails for sources that were already skipped before this fix, without changing their status. **S1 fix — extract_claims cancel + label (0.45.8):** `claims.extract()` now calls `jobs.check_cancel()` between per-group model calls (it never had, unlike `findings.py`/`ingest.py`) so a cancel request actually lands instead of running to completion regardless; `extract_claims` joined `jobs.RETRYABLE`; the Jobs panel shows "finding claims to track" instead of the raw kind name. **S1 fixes — jobs panel + ranking priority (0.45.9):** `api_project_jobs` no longer scans only the most-recently-created 400 jobs app-wide before filtering to the project (a genuinely active job could fall out of that window and vanish) — every active job for the project is always included, `limit` only bounds extra terminal-job history (`db.list_jobs` gained a `statuses` filter). `jobs`' `lane` column gained `priority` (alongside `normal`/`slow`): claimed ahead of `normal`-lane jobs regardless of age, same pool, same $0 cost — `rank_proposed` (scores a channel's videos for the Review card) now uses it at all 4 creation sites so it never queues behind a big findings/claims backlog. **S1 fix — a fourth 'low' lane (0.45.10):** lane order is now `priority < normal/slow < low` — `refresh_skipped_metadata` (the skipped-source backfill: speculative, content not yet known to matter) is tagged `low`, claimed only once nothing else is waiting, so it never displaces an actively transcribing `ingest_source` job or anything else at `normal`/`priority`. **S1 fix — lane backfill on startup (0.45.11):** the lane tags only applied to jobs created from then on; `db.init_db()` now also runs `_backfill_job_lanes` once per app start, correcting the lane on any currently-`queued` `rank_proposed`/`refresh_skipped_metadata` job that predates the feature — idempotent, touches only live queue rows, never job history. **S1 feature — manual "run this next" (0.45.12):** `jobs.bumped_at` outranks every lane; `POST /api/jobs/{id}/bump` sets it on a queued job, cleared the instant it's actually claimed (one-shot, not a standing pin); Jobs panel gets a "⏫ Start next" button. **S1 feature — "Check now" for a parked wait (0.45.13):** a SPEND_CAP/rate-limit banner's date is real (parsed from Anthropic's own error text) but frozen — nothing re-attempts the call before the stored `not_before`; `db.check_now(job_id)` clears the wait and bumps the job so the next worker cycle makes a fresh call; `POST /api/jobs/{id}/check-now`; Jobs panel shows "🔄 Check now" on timer-driven waits (`budget_wait`/`rate_limit_wait`/`provider_wait`/`retry_wait`), never on dependency-driven `blocked`. **S1 fix — the local-AI probe used the CLI's bare default model, not the pinned one (0.45.14):** `claude_code._probe()` hardcoded `model=None` for its health check while `create()` already honored `settings.claude_code_model` — so one unrelated (and separately-metered) default model running dry could report the WHOLE local path down even though the pinned model (`sonnet`, per Kyle's `.env`) had headroom the entire time; the probe now asks with the same pin real calls use.

## Project Bootstrap (Mission BOOTSTRAP R1–R3, 0.50.0)

`bootstrap.py` — a new project starts with what the user already owns. `queries_for(project)` splits the **goal**
into the facets worth searching ($0, deterministic: a long sentence is REPLACED by its clauses, never accompanied
by them — the whole goal as one query raises the coverage denominator until good passages fall under
`library.MIN_COVERAGE`); `scan()` runs `library.recall` per facet over the sources the project does NOT have,
merges by source, bands them (`strong` = matched ≥2 facets or coverage ≥ `STRONG_COVERAGE`), and persists
suggestions to the new **`project_reuse`** relationship table (`state` suggested|attached|dismissed, `band`,
`score`, `why` = the matched passages + terms, `origin` = the queries, `brief_revision`). `related_projects()`
explains a previous project by its useful subset ("17 of 143 · the overlap is …") — **never as a bundle to
import**. `decide()` attaches via `project_sources` (no copy, no re-acquisition, no new chunks) or dismisses.
**No generation call is ever made**; the only spend is one query embedding per facet. Job `bootstrap_scan`
(priority lane, deduped per project) fires automatically when a project is created with a goal. API
`POST/GET /api/projects/{id}/bootstrap`, `POST …/bootstrap/decide`. UI: two-field "Start a project", then the
Starting Research card above In-progress (strong pre-ticked, every reason a clickable passage).
**Deliberately not built** (see `BOOTSTRAP-MISSION.md` §B): global claims, cross-project *findings* (a finding is
an interpretation written against another project's brief — the portable layer is evidence, which is already
global), a new vector index, project lifecycle states. Gate `tests/test_r2_bootstrap.py` (Kyle's Finance→Website
scenario + the isolation invariants: no chat, fact, plan or finding text crosses a project boundary).

## Exploration + Candidate Index (G3, 0.27.0)

`explore.py`: `enumerate_feed` / `enumerate_sitemap` / `enumerate_website` (all through `safe_fetch`, bounded by `MAX_ITEMS`, `MAX_SITEMAPS`, `HOME_LINKS_MAX`; fail open per child) → `explore()` job → collection + proposed sources (G1 identity) + `candidates.remember` → `rank_proposed` → Review. `candidates.py` = the Discovery Candidate Index (seen, not acquired; global row + per-project state/relevance/reason/origin; `search` = gap recall over metadata FTS; `mark_by_source` on approve; `resolve_acquired` on any source creation). Candidates are NEVER evidence: nothing here touches chunks/FTS/embeddings. Chat tool `search_seen_sources`; API `/api/projects/{id}/candidates`, `/api/candidates/{id}/{dismiss,restore,acquire}` (acquire → `ingest_url`). **B3 (0.36.0):** `candidate_links` = why a known source matters (kind + ref: evidence_target/claim/tension/mission/discovery; open/satisfied/dismissed); `pursue` writes them, `resolve_acquired` satisfies them, `knowledge.known_evidence` / `capture_best` (attach → ingest job → browser when needed; never the web) surface and act on them; `/api/targets/{id}/{known,capture-best}`, `/api/candidates/{id}/dismiss-link`. **S5 (0.43.0):** `candidates.pool` = skipped pre-cutoff sources + candidates in one list with a $0 potential scan (`_potential`: links, fit to open questions/weak areas, vocabulary, review score, timeless vs dated); `GET /api/projects/{id}/pool`; the Sources chip 🔎 Known, not captured.

## Chat retrieval (0.24.1)

Each turn: `qa._retrieval_query` (a short or back-referring follow-up is grounded on the previous user question) → `_hits_for` (attached uploads first, then `search.search` with `priority_ids` — up to `search.PRIORITY_RESERVE` slots for the project's ★ priority sources, hits labelled) → 14 excerpts. The model then has `search_library` (more numbered excerpts, optional source filter; continues the [n] numbering, `qa.MAX_EXCERPTS` cap), `list_sources` (the real inventory) and `set_source_priority` (the user's "this is top tier" becomes `project_sources.priority`, project-relative; UI toggle `PUT /api/projects/{id}/priority`). The volatile state block carries `qa.inventory_block` (counts by kind + uploaded documents by title — never the video list). In-chat attachments go through `POST /api/ingest/file` with `immediate=true` (documents/spreadsheets/text parsed, chunked and embedded in the request via the normal `ingest_local_file` path; media still queues) and `ask(attached_source_ids=)` pins them into that turn. Embedding failure never fails a readable document (`ingest._embed_ready`, event `embeddings_deferred`). PDF pages that arrive one word per line are reflowed (`documents._reflow`). Fake knob `NEUROSEARCH_FAKE_CHAT_TOOL`. **Portable answers (C0):** every assistant message has `Copy ▾` (response + sources / response / plain text / Markdown) built client-side from the message's stored `citations` (title + `timestamp` locator + deep `link`) and its evidence-status warnings (`exportMsg` in index.html) — warnings must survive every variant; **Share ▾ (0.35.1):** short/medium variants via `qa.share_variant` on contract `answer.share` — one call over the finished answer, markers ⊆ the original's (strays removed + reported), sources and warnings re-attached client-side; `POST /api/share`; gate `tests/test_m2_share.py`. **Truncation-aware (0.30.3):** `stop_reason=max_tokens` → up to `CONTINUATIONS_MAX` automatic continuations spliced by `_join_continuation`, a visible marker + `meta.warning` if still incomplete, the round after `MAX_TOOL_ROUNDS` runs without tools; per-call diagnostics in `messages.meta.generation`; gate `tests/test_k7_chat_truncation.py`. Tier 1 chat totals re-frozen at 34 / 196,951 (0.32.0).

## Model routing (current)

**L1 Local-First AI (0.38.3, off by default):** `providers.route(task)` decides local (Claude Code, `claude_code.py`) vs API — never a model substitution — when `NEUROSEARCH_AI_PROFILE=local`, the contract is `local_capable` (the six structured tasks), the job's `execution_policy` allows it and `claude_code.health()` is ready; `LOCAL_UNAVAILABLE`/`LOCAL_LIMIT` fall back to the API with `routing_json.executed_by/fallback_reason`; local pool + API pool in `jobs.start_workers`; ledger `transport='local'`, cost 0, `saved` = avoided spend. Gate `tests/test_n2_local_ai.py`; spec `LOCAL-AI-PROVIDER.md`. **L3 (0.45.0):** `jobs.backlog` (time on Claude Code vs dollars on the API, via the shared `usage.estimate_source_findings`) + `jobs.accelerate` (move exactly the chosen jobs to `api_requested`; `order=queue|value`) behind `GET …/ai-backlog` and `POST …/accelerate` — buying speed is explicit, never implied by slowness; gate `tests/test_o1_accelerate.py`. L2 local-first chat is deliberately not built (EXPANSION: "a recommendation, not a rung"). Chat/streaming/embeddings/transcription/batches always stay on their API.

rank.relevance and findings.extract → `claude-sonnet-5` (thinking disabled); every other Anthropic task (incl. `library.profile`) → `settings.answer_model` (claude-sonnet-4-6); `findings.prefilter` / `retrieval.rerank` contracts exist on `claude-haiku-4-5` but their features are off. Structured outputs on findings.extract, rank.relevance, planner.update, discover.quick; discover.verify stays free-text. Per-task overrides `NEUROSEARCH_TASK_{MODEL,THINKING,MAX_TOKENS,SCHEMA}_<TASK>`; `neurosearch contracts` lists them.

## Experimental flags (all off; `neurosearch doctor` fails if any is on — see the inventory in HARDENING.md)

`NEUROSEARCH_PLANNER_V3` (not promoted) · `NEUROSEARCH_FINDINGS_PREFILTER` (deferred on economics) · `NEUROSEARCH_RETRIEVAL_RERANK` (killed live) · `NEUROSEARCH_CHAT_TAIL_BREAKPOINT` (off by decision) · `NEUROSEARCH_SCHEMA_COMPAT_FALLBACK` (rollback hatch only) · `NEUROSEARCH_FAKE_AI` (tests only). Registry: `release.EXPERIMENTAL_FLAGS`.

## Missions filed but not started

- **`EXTERNAL-AI-ACCESS-MISSION.md` (filed 2026-09-10).** External AI Access + bidirectional project intelligence:
  ChatGPT and Claude using Neuro Search as a private, persistent project intelligence layer — one cheap project
  orientation call, project-scoped search, evidence drill-down, and writes back in (correspondence, files, URLs,
  user decisions) through a **Project Inbox**, with per-identity project ACLs so possession of a credential does
  not expose every project. Its hard requirement: **external evidence, user-authored project state and
  AI-generated material stay distinct — AI interpretation can never become self-validating evidence.** §19 of that
  document records what already exists (17 MCP tools, `project_facts`, `search.search`, the jobs table, the file
  ingestion pipeline) and what in the brief is already outdated (auth is one shared token; there is no ACL layer at
  all, so every existing tool is an IDOR the moment a second identity exists).
- **`TRANSCRIPT-INTELLIGENCE-MISSION.md`** (revision 2, Kyle's eight corrections applied) — cheaper cumulative
  understanding of source material. Neither mission is scheduled; Kyle decides the order.

## Working here

**Performance:** `SPEED-MISSION.md` (filed 2026-09-09, rungs R0–R8) holds the measured latency baseline for the live app — queue wait dominates real compute ~50× (`suggest_findings`: 8.6 s of work, 479 s median wait), local is ~3× slower than the API on identical tasks, chat has no streaming (p90 51 s of blank spinner), and the 3 s Sources poll ships 2.34 MB while running ~2,000 queries in `staleness.assess`. It also records what measured as NOT a bottleneck (the 165 MB embedding matrix loads in 0.10 s warm; cross-project reuse applies to 2 sources of 823) — read §A before optimizing anything here. **R0 shipped (0.46.0):** `perf.py` is the in-memory timing ledger (bounded rolling samples, never a table — a row per request would add writes to the path the mission is unblocking), `PerfMiddleware` times every `/api` call under its route template, `db.job_timing`/`db.model_timing` derive work-vs-wait and per-provider latency from `jobs`/`invocations`, and `GET /api/perf` joins both so §A regenerates itself; Health console has the rows plus a "📊 Measure speed" button. `perf.mark(key, hit)` is the hook cache hit rates report through. **0.47.1:** `research_view.areas`/`overview` are cached on the research revision — uncached they did not return in 250 s on Kyle's live project and saturated the server, because the areas pass scales with the Claim pile automatic extraction keeps growing. **R6a claim routing (0.48.0):** `claims.triage` is a $0, model-free split on the two signals Kyle chose (answers an open evidence target; from a source he marked priority) — the important few go `lane=priority, execution_policy=api_requested` (bounded by `FAST_GROUPS`×`EXTRACT_GROUP`), the rest stay on the cheap `slow` lane. **The fast lane reorders, it never filters.** `dedupe_key_for` gained `:fast` so the bulk pass is not swallowed by the fast one. **R2 part 1 shipped (0.46.1):** `cache.py` is the derived-state cache keyed on a REVISION never a clock (in-process, bounded, `compute()` outside the lock); `db.project_research_revision` is the ~5 ms fingerprint (COUNT + MAX(updated_at) over claims/nodes/tensions/analyses/project, COUNT so deletions move it). It fixed `/api/sources` — **2.53 s → 0.35 s p50 live** — whose real cost was 0.45.7's own `pool_potential` scan re-running `research_view.questions`/`areas` on every 3 s poll, NOT `staleness.assess` as predicted (that was 11%). **R2 part 2 (0.46.2):** `staleness.assess` cached on `research|sources|jobs` (job churn must invalidate it or a source keeps claiming it is rebuilding); `db.project_view_revision` returns those plus `notes` (status counts — `project_notes` has no `updated_at`), with `sources`/`jobs` global on purpose because membership also comes via collections and tags. `GET /api/projects/{id}/tick` answers "did anything change?" in 13 ms and the Sources poll calls it before refreshing anything, with a full reconcile every 20 ticks. Cumulative: **2.53 s → 0.155 s p50, and 0.013 s for a poll where nothing changed.** **R2 part 3 (0.46.3):** the frontend rung — `description` clipped to `LIST_DESCRIPTION_CHARS` in the list only (it was 53% of the payload; `/api/sources/{id}` still returns it whole), collapsed groups build no DOM at all (`srcGroupToggled` fills one on first open), and an unchanged group is patched rather than rebuilt (`SRCG.html` comparison) so a refresh keeps scroll, focus and open/closed state. Payload 4.6 MB → 2.8 MB, render 669 ms → 162 ms open / 50 ms collapsed, 22,588 → 590 DOM nodes collapsed. §D is a per-layer stack verdict under an explicit open-source/local-first preference: KEEP SQLite/FTS5, the `jobs` table and `providers.invoke` (all three already beat what would replace them); ADOPT in-process caching and SSE; REJECT sqlite-vec, any vector DB, Valkey, Celery/brokers and AI gateways *for now*, each with a numeric revisit trigger in §H; TEST local runtimes (Ollama/llama.cpp) for embeddings and classification only, never for findings/claims quality.

Run: `pip install -e . && cp .env.example .env && neurosearch serve`. Tests: `pytest` (516). Before a release: `neurosearch release-check` (writes the artifact; the Health console shows the last result). Version lives in `neurosearch/__init__.py`, `pyproject.toml` and `UI_VERSION` in `web/index.html` (PEP 440). YouTube may block datacenter IPs — ingest from a laptop with the same CLI against the same `NEUROSEARCH_DATA_DIR`, or with `NEUROSEARCH_COOKIES_FILE`.
