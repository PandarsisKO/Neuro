# State of the App — 2026-09-14 10:16 PT

Current orientation source for the Neuro Search mission; older state files remain archived evidence.

- Tested code baseline is `3ca18be`. App/package version is `0.63.90`.
- `repo-check` reports one pre-existing WARNING (`KEEP AWAKE - overnight.command` outside the root allowlist —
  Kyle's own operational file, unrelated to any mission and untouched). Commit-bound `release-check --no-pytest`
  is FAIL, for three pre-existing, unrelated-to-T3 reasons that were already present at the prior commit and are
  unaffected by anything landed today: a Tier 1 `calculator_ok` failure tied to fake-OpenAI-embeddings breaker
  state leaking across test order, the root-hygiene warning above, and the documented
  `test_s43_foundation.py` native-worker-restart timing race. Every deterministic proof either mission could
  affect — schema registry, contracts, web JS modules, Tier 1 frozen totals, retrieval baseline, cache layout,
  H1 gates, backup/restore round trip — passes. Artifact:
  `evals/release/release-check-0.63.90-3ec5fff-20260914-171629.json`.
- Full pytest passes **1,382 of 1,397 tests** (15 pre-existing failures, none introduced today; one additional
  `test_s12_recall_precision.py` row observed as a test-order flake — passes in isolation). Focused T3/review
  coverage is 26 passed.
- Claude owns design/audit/browser surfaces; Codex owns backend/reliability/T1–T3. Claims remains paused; R8/R9
  triggers unchanged.

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

**Next gate:** T4 (Batch Research Executor) is the next item on the Transcript Intelligence ladder, but it
needs its own design/storage review (selector vs. executor separation, reuse of R4/R5 durable-unit and
bounded-concurrency infrastructure) before implementation starts — this gate closure authorizes trusting T3's
output, not a particular T4 implementation.

`origin/backup/2026-09-13-clean` is a separate history-free snapshot; protected `VIDEOS/`, `data/`, and
`_to_delete/` paths are absent as of the last verified check.
