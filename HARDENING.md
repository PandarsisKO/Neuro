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
| D | Survive interruption | Ingestion stages (metadata → transcript → segments → chunks → embeddings → ready, each transactional, resume from the last completed), job leases + heartbeats, `job_events`, one findings job per source, `EXTERNAL_PENDING` state for parked work (re-attach, never resubmit) | |
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
MISSION D — SURVIVE INTERRUPTION              NEXT
```

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
