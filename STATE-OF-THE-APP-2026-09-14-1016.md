# State of the App — 2026-09-14 10:16 PT

Current orientation source for the Neuro Search mission; older state files remain archived evidence.

- Tested code baseline is `c127978`. App/package version is `0.63.90`.
- `repo-check` reports the same one pre-existing WARNING (`KEEP AWAKE - overnight.command` outside the root
  allowlist — Kyle's own operational file, unrelated to any mission and untouched). Commit-bound
  `release-check --no-pytest` is FAIL, for the same three pre-existing, unrelated reasons present at every prior
  checkpoint and unaffected by anything landed today: a Tier 1 `calculator_ok` failure tied to fake-OpenAI-
  embeddings breaker state leaking across test order, the root-hygiene warning above, and the documented
  `test_s43_foundation.py` native-worker-restart timing race. Every deterministic proof any mission landed today
  could affect passes. Artifact: `evals/release/release-check-0.63.90-e0e99f5-20260914-175024.json`.
- Full pytest passes **1,382 of 1,397 tests** (the same 15 pre-existing failures, none introduced today; one
  additional `test_s12_recall_precision.py` row observed as a test-order flake — passes in isolation). Focused
  T3/review coverage is 26 passed; focused T6 coverage is 8 passed (plus 19 passed in the concurrency suite the
  T6 refactor touched).
- Claude owns design/audit/browser surfaces and, per Kyle's "do 4/5/6 now" authorization, T4/T5/T6 of the
  Transcript Intelligence ladder; Codex owns backend/reliability/T1–T3. Claims remains paused; R8/R9 triggers
  unchanged.

**Design/audit:** D0/D1/F0 complete and frozen. Claude's full 22-finding declutter pass is complete through
rung 6 (commits `19ce0cd`, `875115f`, `ee52d1a`, `6f30e76`). No declutter queue remains; a future design pass
starts fresh against current `main`. `PRODUCT-SCHEDULER.md`'s "NOW" header is stale (still names the CSS/module
split, which is already committed); a reconciliation entry is appended there rather than rewriting its history.

**T3 (current active gate):** the pure, versioned, read-only Tier-0 extractor (`neurosearch/t3.py`,
`t3-tier0-v1`) remains free of any database, provider, queue, or UI path. Corpus-driven hardening now also
covers bare more/less comparatives following a short filler-verb list ("more use...", "more about..."), on top
of the earlier heading-label, harmless-narration, phone-shaped-ISBN, malformed-number, decimal-boundary, and
interrogative/procedure fixes. `neurosearch/t3_review.py` validates record structure and scores labeled rows
independently across chunks.

The provisional gold-labeled sample contains 15 project-balanced chunks and 63 reviewed spans, unaffected by
today's patch. The seeded review manifest contains 60 rows, 20 per retained project, all 15 kinds, `gold: null`,
and count-based triage flags (19 dense_multi_span, 9 negative_empty_row, 7 sentence_boundary_review, 3
cue_entity_review, 2 canonical_identifier_review). Both were generated from a copied verified backup in SQLite
`mode=ro`; the live database was never opened.

**T3 admission gate is CLOSED (2026-09-14 11:35 PT, commit `3ca18be`):** all 252 predicted records across
the 60-row seeded queue were manually adjudicated against source text; 0 false positives, every per-kind and
overall precision floor passes at 1.00 (floors are 0.85/0.90/0.95 by kind). Extraction output may now be
persisted, trusted by a selector, and used by T4. Two recall-only structural gaps (bracket-header-label
suppression on a chunk's first sentence; chunks with no terminal sentence punctuation) are documented in
`docs/T3-ADMISSION-2026-09-13.md` and deliberately left unpatched — neither affects precision, and either may
motivate a future narrow T3 recall rung.

**T6 admitted (2026-09-14, commit `e0e99f5`):** the assumption ledger's first slice
(`neurosearch/assumptions.py`) registers nine live constants (five measured with cited evidence, four
unmeasured), exposed via `neurosearch assumptions [--json]` and one informational `doctor()` check that warns
but never fails a release, per T6's own mission gate. T6 is explicitly parallel, not a prerequisite to T4/T5.
Full detail in `docs/T6-ADMISSION-2026-09-14.md`.

**T4 admitted, selector only (2026-09-14, commit `86ddab9`):** `neurosearch/t4.py` ranks genuinely
unexplained chunks (via T2's signals + T3's own extractor for cue-based prioritization) and open Evidence
Targets into a single reproducible, provenance-carrying work list. No executor is wired — nothing currently
calls `t4.select`'s output. Full detail in `docs/T4-ADMISSION-2026-09-14.md`.

**T5 admitted, propose only, no live spend (2026-09-14, commit `ed37393`):** `neurosearch/t5.py` proposes
adjudication candidates from real open, high-impact tension signals (`CONTRADICTION` -> sources disagree;
`NOVEL`/`WEAK_CONSENSUS` -> ambiguous evidence), each with a gate-admissible `evidence:` reason built from a
live `cost_value.by_model` comparison. No live provider call has been made anywhere in this pass; output is not
wired into any workflow. Full detail in `docs/T5-ADMISSION-2026-09-14.md`.

Kyle's "do 4/5/6 now" set (T4 selector, T5 trigger, T6 assumption ledger) is fully admitted, and Kyle
then asked to get T4 "fixed and shipped."

**T4 executor $0 dry run (2026-09-14, commit `c127978`):** added the `t4.research` contract and `t4.plan()`,
which routes every selected item through the same `contracts.contract()`/`providers.current_policy()` seam a
real executor would use, without calling `providers.route()` (that call's local branch can start a real Claude
Code health-probe spend). Kyle chose this $0 scope explicitly over a full live executor in one pass. Full detail
in `docs/T4-ADMISSION-2026-09-14.md`.

T4 now has both halves shipped: a tested selector and a tested, $0 executor routing seam. What remains for T4
to be fully live: wiring `providers.route()`, a real provider/local call, and a structured-delta write path —
not started, no target date. A live T5 adjudication call and the T4 novel-cluster/stale-Claim signals also
remain future, separately-admitted work.

`origin/backup/2026-09-13-clean` is a separate history-free snapshot; protected `VIDEOS/`, `data/`, and
`_to_delete/` paths are absent as of the last verified check.
