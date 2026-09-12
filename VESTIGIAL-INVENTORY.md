# Vestigial and friction inventory

Updated 2026-09-12 during pre-T1 gate verification. This is a bounded inventory, not a new
parallel roadmap. `PRODUCT-SCHEDULER.md` decides admission. “Vestigial” means the current
purpose is unclear, duplicated, historically superseded, or expensive to maintain; it does
not mean safe to delete without evidence.

## Remove from the working repository after recoverable archival

| Surface | Evidence | Cost/risk | Disposition |
|---|---|---|---|
| `_to_delete/` | 432 MB; old update tarballs, Git lock copies, database journals, drafts, samples and stray document copies | Bloats scans/backups and makes artifacts look current | Move as one recoverable unit outside the repo, verify Git state, then delete only after Kyle is satisfied. Never inspect/open database journals. |
| `Claude outputs/` | The root folder now contains an untracked `T1-DESIGN-AUDIT-2026-09-12.md` handoff artifact; older snapshots are archived | A collaborator can read an unreviewed draft as current product truth, or a broad stage can publish it accidentally | Preserve the current untracked audit until the Claude design set is reviewed as one coherent unit. The reconciled, tracked copy is `docs/T1-DESIGN-AUDIT-2026-09-12.md`; archive or remove the root copy only after explicit comparison. |
| `_scratch/` | No `_scratch/` directory exists in the current checkout | A recreated scratch directory could become an untracked second source of durable state | No action required; use system temporary directories for scratch work. |
| `VIDEOS/` local recordings | Five September 3 screen recordings, about 3.0 GB total; no code or documentation references them by path; `git ls-files VIDEOS` and the compact GitHub tree both return zero entries | Binary recordings still expand local scans and backups, while Git no longer carries them | Index removal and ignore policy are complete. Preserve the local recordings for now; delete or move them only through the recoverable cleanup decision with owner approval. |

## Archive or label, not blindly delete

| Surface | Evidence | Cost/risk | Disposition / revisit trigger |
|---|---|---|---|
| `Dockerfile`, `fly.toml`, README cloud deployment | Current product contract is local/single-user; cloud and multi-user are parked; current auth is one shared token | Encourages an unsafe unsupported deployment and creates a second operating model | Operational cloud directions were removed from the current README; its exact prior form is archived. Move packaging to archive when no current user depends on it. Revisit only after project-scoped authorization and cloud architecture are admitted. |
| `SCHEDULER.md` | Design exploration says nothing built, while older handoffs called it current | Confuses runtime scheduling design with product priorities | Bannered PARKED. `PRODUCT-SCHEDULER.md` is the product queue. Revisit only after its four prerequisite measurements and an admission checkpoint. |
| `FIELD-MAP-RUNG.md`, `SOURCE-CAPABILITY-RUNG.md` | Idea/rung notes; the latter is partially shipped | Unfinished checklists look like assigned work | Bannered PARKED/PARTIALLY SHIPPED. Preserve as idea records; reconcile against code only if admitted. |
| Old root `CLAUDE.md` and `HANDOFF.md` narratives | Approximately 200 KB and 37 KB, with stale VM bridge, mission and delivery assumptions | High context cost; conflicting instructions | Replaced with compact current documents; exact originals preserved under `docs/archive/*-pre-foundation.md`. |
| `docs/archive/EXPANSION.md` | Historical universal release diary | Future sessions can keep appending and recreate parallel truth | Keep read-only as evidence; new measurements go to HARDENING and current state/handoff files. |

## Keep as measured evidence or compatibility machinery

| Surface | Why it looks vestigial | Why it stays / trigger |
|---|---|---|
| Retrieval reranker, findings prefilter, Planner v3 and their eval commands | Built but disabled | They preserve measured negative decisions and regression comparisons. Delete only when HARDENING retains reproducible evidence and no release/closeout gate imports the implementation. |
| Legacy database migrations and fixtures | Old versions are no longer produced | Existing installations must still upgrade and tests prove that contract. Remove only with an explicit minimum-supported-version decision and export path. |
| Legacy analysis/status rendering | Migrated rows still exist and remain reviewable | Removing the path would hide or misrepresent preserved research. Retire after live counts reach zero and a verified migration/export handles every row. |
| Schema compatibility fallback | Normally off | It is an explicit degraded rollback hatch with health accounting. Revisit after a measured period of zero use and a replacement recovery path. |
| External batch materialization/recovery | Some paid partial results cannot form a complete source | This is integrity-preserving recovery state, not dead code. R4/R5 must reuse it without letting partial sources appear complete. |

## Confirmed maintenance friction fixed in candidate 0.63.36

- Endpoint tests started a session-wide worker pool while tests changed global database settings. They now
  suppress background workers and explicitly execute the exact jobs needed by two endpoint tests.
- Workers used a mutable global database path and shutdown forgot surviving threads after two seconds.
  Worker generations now bind their path, close their own connections, refuse overlap, retain survivors,
  and keep leases alive while draining.
- Local-provider failure silently crossed onto paid transport. Paid fallback is now explicit opt-in;
  local failures park visibly by default and explicit Accelerate/API choices remain.
- The browser checked version only once and allowed a stale UI to mutate a newer server. First-party requests
  now carry a version, the server refuses mismatches before side effects, and visible tabs recheck.
- Tests/comments conflated `NO_FALLBACK` model policy with local-to-paid transport fallback. The two policies
  are now named and gated separately.
- The blocked-page test patched `httpx.Client`, a transport the application no longer uses. It now patches the
  real `safe_fetch` boundary.
- The discovery provenance test included catalogue rows while asserting model-routing fields. It now forces
  a model discovery and checks only model-generated rows.
- An OCR fallback test relied on an optional local binary while trying to test engine sequencing. Sequencing is
  now deterministic; separate tests still exercise the real native OCR engine on this Mac.
- Static UI gates existed as hand-picked lists. Candidate gates cover duplicate column-zero global functions,
  literal duplicate IDs, static inline handler references, and raw first-party fetch bypasses.
- `semantics.py` was an unreachable 0.61.0 prototype: no API, CLI, tests or imports used it. It could embed every
  finding and Claim regardless of active status and label a fixed bottom quartile “unexplained,” conflicting with
  the current active-only, multi-signal, measurement-first research policy. The module and its unused DB helpers
  were removed. Its additive `embedding` columns remain for existing-database and downgrade compatibility; Git
  history preserves the experiment.

## Confirmed runtime friction fixed in candidate 0.63.37

- The Findings quality and usage caches used the Sources view revision, including the global jobs heartbeat. A
  queue update could therefore retire an eight-million-comparison duplicate graph when no finding changed. Usage
  now keys only on findings/plan/chat/Claim inputs; lexical cluster membership keys only on findings, while current
  usage reselects the safe keeper without rebuilding the graph.
- List-style Jobs endpoints returned browser-captured page bodies stored in historical job payloads even though the
  polling panel never reads them. Lists now omit `_external_result` and say which field was omitted; the individual
  job endpoint retains the complete durable record.
- `extract_claims` could remain in user-facing `cancelling` after restart if a paused worker pool excluded it from
  the normal queued-cancellation sweep. Cancellation cleanup now runs before lane filtering and always reaches the
  terminal state.
- Five unreferenced screen recordings totaling about 3.0 GB were tracked by Git. The candidate keeps the local
  files but removes their index entries and ignores `VIDEOS/`; no recording is deleted and Git history is not
  rewritten.

## Investigate before changing

- The historical `outcome_unknown` rows: candidate attribution prevents adapters from dropping run context,
  but no log evidence proves the old lease-expiry hypothesis. Observe fresh runs before relabeling anything.
- Startup `pip install -e '.[dev]'` on every launch: convenient for self-updating dependencies, but it adds
  startup latency and couples normal use to packaging/network state. Measure warm launch time and failures;
  consider an install fingerprint only if this is material.
- `run-findings-haiku-test.command` and `run-haiku-comparison.command`: comparison helpers may be superseded by
  the current eval commands. Compare flags/output against `neurosearch eval` before archiving.
- Large single-file UI: static gates reduce regressions, but parse/review cost and global namespace collisions
  remain. Measure change frequency and defect rate before proposing a framework migration; a modular vanilla-JS
  extraction could be a smaller future step.
- Environment variables: `.env.example`, README, config and doctor have accumulated over many releases. Build a
  generated settings inventory before removing any variable; absence from README alone is not proof of disuse.
- `remote.py` is still imported by the CLI for cloud ingestion. Its Fly-era operating model conflicts with the
  current local-only contract, but an active import is not proof of active use. Measure command usage and identify
  any dependent workflow before archiving it with the cloud packaging.
- `data_backup_2026-09-03/` is an ignored 80 MB local database copy inside the checkout. It is not Git bloat, but it
  still expands filesystem scans and duplicates custody already handled by verified `data/backups/`. Confirm it is
  superseded by a verified snapshot before moving it into the same recoverable cleanup decision as `_to_delete/`.
- Generic “retention” language in the old R8 plan treated `job_events`, `invocations` and `usage` alike. They have
  different ownership: usage is the cost ledger, invocations are the provider audit trail, and job events are
  detailed operational history. Keep both ledgers. Measure at least 30 days of event growth and audit consumers
  before designing a terminal-job event rollup/archive.

## Cleanup gate

Before removing any candidate: identify every reference with `rg`, distinguish live data compatibility from
code history, preserve unique evidence, run affected gates, and record the change in FOUNDATION-HANDOFF and
HARDENING. File size and age are signals, not deletion authority.
