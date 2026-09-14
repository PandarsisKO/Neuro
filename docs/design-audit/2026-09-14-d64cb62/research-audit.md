# Research/Chat surface — first-pass audit, 2026-09-14 (overnight, post-ladder)

**Mode:** `AUDIT.md` §3 FULL AUDIT, scoped to the Research and Chat surfaces only — the one part of the app the
F0→P1 ladder explicitly never touched (`ladder.md`'s own scope note: "Research was not touched by any landed
rung"). **Baseline:** current build, `v0.63.73` after this pass's one landed fix. **Method:** read `DESIGN.md`
§8's Research/Chat direction and the actual `resPane`/`renderShell` routing in `neurosearch/web/js/research.js`
before judging anything live, per §2 — the IA turned out more deliberate than a first live click-through
suggested (see the corrected read below). Live-walked Overview, Open questions, Watch-outs, Areas, Claims, and
Research tools on the audit instance (dark theme), plus one live Chat exchange including its "why this answer"
evidence panel.

## Corrected read: the six-tab IA is intentional, not drifted

An initial pass (going by screen position rather than the tab's actual key) mis-clicked into "Research tools"
believing it was "Open questions," and read that tab's raw `corroborative sufficiency` / `n independent
supporting source(s)` language as jargon leaking into a low-tier surface. Reading `renderShell()`/`resPane()`
directly corrected this: `#resMap` (the "Knowledge Map" with that engine-detail language) lives inside
`#paneTools` — "Research tools" — which `DESIGN.md` §8 explicitly scopes as the advanced tier ("Advanced:
Claims, provenance, diagnostics, engine detail"). `renderQuestionsPane()`, `renderWatchoutsPane()`, and
`renderAreasPane()` are all written in genuinely plain language ("What is not settled yet, in plain language:
what would settle it, what the evidence says now, what is missing, and where to look"), matching `DESIGN.md`'s
direction well. Worth recording precisely so a future audit doesn't repeat the same mis-click — and worth
recording as a strength: the plain-language tiers hold up under direct source reading, not just a glance.

## Finding — RESOLVED this pass

**Truncated evidence titles cut mid-word with no marker (Medium, mechanical, fixed).** Two sites hard-truncated
source titles with a bare `.slice()`/`[:n]` and no ellipsis: `research.js`'s `claimCard()` evidence chips (34
chars) and `claims.py`'s "N source(s) repeat another source's passage" why-string (40 chars). Live evidence
before the fix: a Claims-tab citation chip read "How To Use Codex To Build Insanely" (missing the rest of the
title) and a why-string read "...do not count as corroboration: The stupid simple way to learn UI/UX des" — a
source title cut off mid-word. Both are in the "Research tools" advanced tier, where engine detail is expected,
but garbled mid-word cutoffs aren't legible engine detail, they're a rendering bug. Fixed with a small `trunc()`
helper (JS) and an equivalent inline helper (Python) that both append "…" when truncating. Landed as commit
`3a0e459`, `UI_VERSION` 0.63.72 → 0.63.73, live-verified on the audit instance after a restart (the audit
instance runs without `--reload` by design).

## Findings — flagged, not fixed this pass

- **Possible duplicate citation on the same Claim (Low/Medium, needs backend investigation).** The first Claim
  card walked in "Ai-assisted design" showed two separate evidence chips with the *exact same* source URL
  (`medium.muz.li/.../d5d200899129`) and the same `@ § 3` locator, both truncated to the same title. Confirmed
  in the live DOM after the truncation fix (two distinct `<a class="chip">` elements, identical `href`). This
  could be legitimate — two different findings citing the same passage — or a real gap in evidence
  deduplication when a Claim absorbs findings from multiple sources. Not chased further this pass: it needs
  someone who knows `claim_evidence`'s insert path to say which, and touching that path without that context
  risked a worse mistake than leaving it flagged.
- **Watch-outs read as one template repeated with the topic swapped (Low, content/product judgment, not a bug).**
  Ten-plus Watch-outs cards ("Ai-assisted design," "Cognitive load," "Everything else," "Interaction patterns,"
  "Visual hierarchy," "Off-topic source," "Progressive disclosure," "Design tokens," "Information architecture,"
  "Claude design skills") share the identical sentence shape — "`<Topic>`: no authoritative or expert voice yet
  ... If you leave it: Advice stays one-sided; the Master Plan cannot weigh the other side" — with only the
  topic name changed. Each individually reads fine; stacked in the full Watch-outs list (37 total, most of this
  shape) they read as one generated paragraph repeated, which works against `DESIGN.md` §1.5's progressive
  disclosure and signal-to-noise goals the more of them a user scrolls past. This is a content-generation
  pattern in whatever module classifies "single-perspective" issues, not a rendering bug — a real fix means
  either varying the phrasing or grouping same-shape watch-outs together, which is a product/copy decision
  beyond this pass's scope, not a mechanical one. Recording the evidence rather than redesigning it unilaterally
  overnight, per `AUDIT.md` §1.2 ("evidence first, diagnosis second, redesign third").
- **"Everything else" area micro-clusters (Not a finding — already disclosed in-product).** The Overview/Areas
  panes show several single-word "areas" ("action," "adding," "against," "button," "buttons") with one Claim
  each — looked like naive keyword-clustering noise at first glance. `renderAreasPane()`'s own copy already
  explains this: "'Everything else' holds Claims whose harvested topic was a single generic word — a
  normalisation pass (Research tools) is what labels those." The product already discloses the limitation and
  names its own fix path (the "Normalise Claims" button). Recorded here only so a future pass doesn't re-flag
  it as new.

## Strength worth preserving

**Chat's "why this answer" evidence panel is well executed.** Per-Claim breakdown in plain language (e.g. "thin
evidence — not yet decided (needs more evidence first) · cause and effect · this exact passage"), correct
weak/strong badges, an inline Accept action, and citation pills that stay visually secondary until opened —
matches `DESIGN.md`'s "Citations and evidence available but visually secondary until needed" almost exactly.
No changes recommended here.

## Deterministic gates

26/26 (`test_s44`, `test_s50`, `test_s5`) plus the four Claims-focused suites (`test_k6_claims`,
`test_o2_claims_workbench`, `test_p3_claim_triage`, `test_r7_claims_yield` — 26/26) pass on the landed fix.
`test_core`/`test_indestructible`: the same 12 pre-existing sandbox-environment failures as every prior rung,
none new.

## Conclusion

First-pass Research/Chat audit: one real, mechanical bug found and fixed (truncation without an ellipsis); one
plausible data-quality issue flagged for someone with `claim_evidence` context to check; one content-repetition
issue flagged as a product/copy decision, not mechanically fixable tonight; one apparent issue turned out to
already be disclosed in-product. The IA itself, read from source rather than assumed from a screen position,
matches `DESIGN.md`'s stated mental model better than a first click-through suggested. Chat's evidence panel is a
genuine strength. Nothing here rises to a size that needs a multi-rung ladder — the one landed fix is the whole
of it.
