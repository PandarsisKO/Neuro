# Neuro Search hardening roadmap

*Mission: make Neuro Search boringly reliable.* A research project must survive crashes, model changes, API outages,
brief changes, re-ingestion, retries and months of work without losing state, duplicating work, silently going stale,
or producing artifacts whose origin cannot be explained. Then optimise so the best-value model does each task.
Every optimisation must prove one of: more reliable · higher quality · faster · cheaper.

**Rule: do not climb a rung until its exit test passes.**

| Rung | Mission | Deliverable | Status |
|---|---|---|---|
| A | Make it provable | Frozen Golden Project, `NEUROSEARCH_FAKE_AI=1`, `neurosearch eval`, quote + citation + plan-evidence validators, verified backups, migration fixtures, canonical URLs, correlated logs, baseline | **done in 0.15.0** (live baseline pending — see below) |
| B | Trust the data | `project_source_analysis` (project-relative summary/substance/relevance off the global source row), provenance columns (model, provider, prompt_version, schema_version, source/brief/facts revisions), deletion cascade | next |
| C | Staleness | Artifacts know the revisions they were built from; CURRENT / STALE-STILL-USABLE / REBUILDING / SUPERSEDED; rebuild shows a cost estimate and goes through the budget valve; chats stay historical | |
| D | Survive interruption | Ingestion stages (metadata → transcript → segments → chunks → embeddings → ready, each transactional, resume from the last completed), job leases + heartbeats, `job_events`, one findings job per source, `EXTERNAL_PENDING` state for parked work (re-attach, never resubmit) | |
| E | Modernise AI | Task router (`AIRequest(task, latency_class, quality_class, schema)` → inference profile → provider adapter); adapters reject unsupported knobs loudly; then Sonnet 4.6 → Sonnet 5 as the router's first use, with an explicit thinking policy per task and `max_tokens` re-sized per task after recounting (Sonnet 5: new tokenizer ≈ +30% tokens, adaptive thinking on by default and billed inside `max_tokens`, `temperature`/`top_p` rejected) | |
| F | Deterministic AI | Structured outputs with versioned schemas (FindingV2, RankingV2, DiscoveryV2, SituationAnalysisV3, PlanPhaseV3, …); the planner split into several small schema'd calls over the same cached material; `_repair_json` demoted to fallback | |
| G | Cut cost safely | Message Batches for background work (bulk findings, stale rebuilds, evals) — batch is a scheduling choice, not a different operation; same schema/prompt/provenance either way; prompt reorder so volatile findings/facts sit after the stable prefix | |
| H | Cut cost intelligently | Luna/Haiku only behind validators: window pre-filter for findings gated on ≥99% relevant-window recall on the golden corpus; ranking with two-pass agreement; never findings extraction itself | |
| I | Retrieval | Reranker on the top 40 first; query rewriting only if recall gain beats the added round-trip; embedding-large only if the eval moves; vector index only on evidence of a bottleneck | |
| J | External failure | `safe_fetch()` (SSRF, private ranges, size/redirect/timeout limits, decompression bombs) for everything except yt-dlp; circuit breakers per provider; per-task fallback policy with `requested_model` / `actual_model` / `fallback_reason` in provenance; Discover-verify holds rather than falls back | |
| K | Health | Health console (database, backups, workers, leases, providers, quality, efficiency) — the start of it ships in Settings → Health in 0.15.0 | started |
| L | Safe change | UI split into ES modules (still no build), fake-AI Playwright end-to-end, release gates: Tier 1 eval → unit → migration → crash/recovery → E2E → RC → Tier 2 eval → cost regression → backup restore | |

## Mission A in 0.15.0 — what shipped

- **Golden Project** — `tests/fixtures/golden/`: 9 frozen sources (three YouTube transcripts including a 92-minute one with nuggets buried in filler, a contrarian podcast, an article, a PDF, a calculator spreadsheet, two irrelevant sources), 35 questions with expected sources/locators/contradictions/gaps, 10 planted evidence quotes. Generated once by `build.py`; the files are what is frozen.
- **`NEUROSEARCH_FAKE_AI=1`** — the whole app (server, workers, CLI) runs on deterministic, content-aware fakes (`neurosearch/fake_ai.py`) through the single provider seam `neurosearch/providers.py`. Every model call declares its task (`extra_headers["x-neurosearch-task"]`), which is the router's future hook.
- **`neurosearch eval`** — retrieval Recall@5/10, MRR, locator accuracy; finding quote validity; stored findings re-verified; golden evidence recall; citation validity; gap detection; contradiction surfacing; plan evidence validity; calculator; tokens per task (input/output/cache read/cache write), cost, cost per source-hour, latency per phase; Tier-1 gates; `--baseline` / `--compare` / `--live`.
- **Validators at runtime** — `neurosearch/evidence.py`: a finding whose quote is not in its transcript window is rejected before it is stored; an answer's `[n]` outside the supplied excerpts is stripped and counted; a plan's dangling evidence ids are recorded. Counters in kv feed Health.
- **Verified backups** — every snapshot is reopened, `quick_check`ed and schema-checked before it counts; hourly integrity check of the live database; `/api/health`, `/api/backup`, Settings → Health.
- **Migration fixtures** — `tests/fixtures/db/`: databases created by 0.1.0, 0.12.0, 0.13.0 and 0.14.0's own schemas, each upgraded by the current `init_db()` in the test suite with row counts proven intact.
- **Canonical URLs** — `media.canonical_url`: youtu.be / `&t=` / `&list=` / `si=` / utm / host case / trailing slash all resolve to one identity before dedupe.
- **Correlated logs** — `neurosearch/logctx.py`: every line carries job/run/project/source/task/provider/model; `NEUROSEARCH_LOG_JSON=1` for shippers.

### Baseline (A10)

`evals/baseline-fake.json` is committed (Tier 1). The **Sonnet 4.6 baseline** must be captured on a machine with keys before the Sonnet 5 migration:

```bash
neurosearch eval --live --baseline        # ≈ $1, writes evals/baseline-claude-sonnet-4-6.json
```

Token counts per task are first-class in that file, so the tokenizer change shows as its own line when Sonnet 5 is compared with `neurosearch eval --live --compare evals/baseline-claude-sonnet-4-6.json`.
