"""T6 — the assumption ledger: a registry of constants that encode a judgement about the data.

Not every constant in this codebase belongs here — only the ones where a different number would change product
behavior and the current number came from a measurement (or, honestly, a guess) rather than from a law. The
brief this answers: "never keep a number nobody has re-checked." Four times in two days a plausible constant was
contradicted by Kyle's own data before this registry existed (see TRANSCRIPT-INTELLIGENCE-MISSION.md T6); the
registry does not re-run those measurements automatically (that is future, per-assumption work — see
`how_to_verify` on each entry), it makes them discoverable and keeps the codebase honest about which ones have
never been checked against live data at all.

Read-only. No database write, provider call, queue, or UI mutation. Values are resolved live via ``getattr`` on
the owning module every time ``list_assumptions()`` runs, so an entry can never silently drift from the code it
describes — if the constant's name or module changes, resolution fails loudly (`value: "ERROR: ..."`) instead of
showing a stale number.

Gate (per T6's own mission text): drift *warns*, never fails a release — a moved number is a fact about data, not
a bug, and a gate that fails for that reason teaches people to ignore gates. This first slice reports whether
each assumption has ever been measured against live data; it does not yet re-run each measurement automatically
(`how_to_verify` documents the manual check until a specific assumption's automated re-check earns its own rung).
"""
from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Any


@dataclass(frozen=True)
class Assumption:
    name: str                 # the constant's name, as it appears in source
    module: str                # dotted module path owning the constant, e.g. "neurosearch.findings_quality"
    attr: str                   # attribute name on that module
    why: str                    # one line: what judgement this number encodes
    measured: bool               # True only if a specific live-data measurement is cited in `evidence`
    evidence: str                # what was measured, when, on what corpus — or "not yet measured" if measured=False
    how_to_verify: str          # the concrete check that would re-validate this against CURRENT live data
    kind: str = "threshold"      # "threshold" | "default" | "budget" | "weight"


# ---------------------------------------------------------------------------------------------------------------
# Registry. Each entry's `evidence` is a pointer, not a duplicate — the full measurement writeup lives as a code
# comment beside the constant itself (see the module it names); duplicating that prose here would create the
# exact "two live copies of the same fact" problem QUALITY-CONTRACT.md §3.2 warns about.
# ---------------------------------------------------------------------------------------------------------------
REGISTRY: tuple[Assumption, ...] = (
    Assumption(
        name="NEAR_JACCARD", module="neurosearch.findings_quality", attr="NEAR_JACCARD",
        why="shingle-Jaccard boundary between 'same proposition reworded' and 'same topic, different content'",
        measured=True,
        evidence="calibrated 2026-09-10 against 10,380 approved findings in one live project (read-only, hourly "
                  "backup); sampled score bands 0.25-0.62, found the boundary at 0.35, not the originally assumed 0.62",
        how_to_verify="re-sample duplicate-candidate pairs across score bands on the current largest project's "
                        "approved findings and check the boundary still separates genuine reworded duplicates from "
                        "same-topic-different-content pairs",
    ),
    Assumption(
        name="CONTAIN_RATIO", module="neurosearch.findings_quality", attr="CONTAIN_RATIO",
        why="containment ratio above which one finding's content words are 'almost wholly inside' another's",
        measured=True,
        evidence="sampled on the same 2026-09-10 corpus; kept because it catches real duplicates Jaccard misses "
                  "(a shorter restatement of a longer finding, Jaccard as low as 0.12) at high sampled precision",
        how_to_verify="sample containment-only duplicate candidates (high CONTAIN_RATIO, low NEAR_JACCARD) on the "
                        "current corpus and confirm they are still genuine restatements, not coincidental overlap",
    ),
    Assumption(
        name="SET_JACCARD", module="neurosearch.findings_quality", attr="SET_JACCARD",
        why="bag-of-words Jaccard boundary for paraphrase duplicates that reorder content words (3-grams miss these)",
        measured=True,
        evidence="sampled 2026-09-10: bands 0.55-0.65 and 0.45-0.55 true duplicates, 0.35-0.45 mostly true, "
                  "0.30-0.35 clearly mixed; 0.50 chosen conservatively since a false duplicate costs a real finding",
        how_to_verify="sample set-Jaccard-only duplicate candidates on the current corpus at and near 0.50 and "
                        "confirm the precision/recall tradeoff still favors the conservative side",
    ),
    Assumption(
        name="SET_MIN_SHARED", module="neurosearch.findings_quality", attr="SET_MIN_SHARED",
        why="the measured floor of the set-Jaccard approach — genuine duplicates below this score exist and are "
             "not caught by any lexical threshold in this file",
        measured=True,
        evidence="three genuine duplicates found by hand score 0.33, 0.20, and 0.18 on set-Jaccard; no lexical "
                  "threshold separates those from findings that merely share vocabulary — catching them needs "
                  "embeddings, a separate measured decision, not this constant",
        how_to_verify="this constant documents a known gap, not a tunable boundary; re-verify by hand-sampling "
                        "low-set-Jaccard pairs on the current corpus to confirm the gap is still real and still "
                        "requires embeddings rather than a better lexical threshold",
    ),
    Assumption(
        name="PAIR_BUDGET", module="neurosearch.findings_quality", attr="PAIR_BUDGET",
        why="the pair-comparison budget below which duplicate clustering completes fully rather than reporting a "
             "partial-budget warning",
        measured=True,
        evidence="measured 2026-09-13 on the then-16,450-finding project: 8,000,000 stopped partial (1,502 "
                  "clusters); 12,000,000 and 16,000,000 both produced the identical complete 1,503-cluster "
                  "signature (11.862s and 11.937s) — 12M chosen as the smallest ceiling that matched the full result",
        how_to_verify="re-run duplicate review on the current largest project's finding count and confirm no "
                        "partial-budget warning fires, and that raising the budget further does not change the "
                        "cluster count or signature",
    ),
    Assumption(
        name="TITLE_ECHO", module="neurosearch.findings_quality", attr="TITLE_ECHO",
        why="share of a finding's content words already present in its source's title, above which the finding is "
             "flagged as vacuous title-echo rather than real content",
        measured=False,
        evidence="not yet measured against live data — currently a stated value with no cited sampling",
        how_to_verify="sample findings flagged as title-echo at and near this threshold on a live project and "
                        "confirm they read as adding no information beyond the source title",
    ),
    Assumption(
        name="SHORT_CONTENT_TOKENS", module="neurosearch.findings_quality", attr="SHORT_CONTENT_TOKENS",
        why="content-word count below which a finding is flagged as saying almost nothing",
        measured=False,
        evidence="not yet measured against live data — currently a stated value with no cited sampling",
        how_to_verify="sample findings at and near this content-word count on a live project and confirm they "
                        "read as genuinely thin rather than merely concise",
    ),
    Assumption(
        name="local unit concurrency default", module="neurosearch.concurrency", attr="_LOCAL_UNIT_CONCURRENCY_DEFAULT",
        why="default number of concurrently in-flight local (Claude Code / subscription) work units per task group "
             "when NEUROSEARCH_LOCAL_UNIT_CONCURRENCY is unset",
        measured=False,
        evidence="not yet measured — chosen as a small, conservative starting bound (clamped to [1,4] regardless "
                  "of configured value); Kyle raised his own instance to 4 on 2026-09-14 by direct request, which "
                  "is exactly the kind of local override this ledger exists to surface rather than hide in .env",
        how_to_verify="measure wall-clock throughput for a fixed batch of local research work units at "
                        "concurrency 1, 2, 3, and 4 on the actual machine running the worker, and confirm the "
                        "default still reflects a reasonable floor rather than a stale guess",
        kind="default",
    ),
    Assumption(
        name="api unit concurrency default", module="neurosearch.concurrency", attr="_API_UNIT_CONCURRENCY_DEFAULT",
        why="default number of concurrently in-flight paid-API work units per task group when "
             "NEUROSEARCH_API_UNIT_CONCURRENCY is unset",
        measured=False,
        evidence="not yet measured — chosen as a small, conservative starting bound (clamped to [1,4])",
        how_to_verify="measure API rate-limit headroom and cost-per-minute at concurrency 1 through 4 on a real "
                        "provider account and confirm the default is not needlessly conservative or too aggressive",
        kind="default",
    ),
)


def _resolve(a: Assumption) -> dict[str, Any]:
    try:
        mod = import_module(a.module)
        value = getattr(mod, a.attr)
    except Exception as exc:  # pragma: no cover - reported, never raised, per the read-only/fail-open contract
        value = f"ERROR: {exc.__class__.__name__}: {exc}"
    return {
        "name": a.name, "module": a.module, "attr": a.attr, "value": value, "kind": a.kind,
        "why": a.why, "measured": a.measured, "evidence": a.evidence, "how_to_verify": a.how_to_verify,
    }


def list_assumptions() -> list[dict[str, Any]]:
    """Resolve every registered assumption's CURRENT live value. Never raises; a resolution failure is reported
    as an ``ERROR: ...`` value for that one entry, not a crash of the whole ledger."""
    return [_resolve(a) for a in REGISTRY]


def summary() -> dict[str, Any]:
    """One-line-worthy counts for the Health section. Always informational — never a pass/fail verdict."""
    rows = list_assumptions()
    errored = [r for r in rows if isinstance(r["value"], str) and r["value"].startswith("ERROR: ")]
    return {
        "total": len(rows),
        "measured": sum(1 for r in rows if r["measured"]),
        "unmeasured": sum(1 for r in rows if not r["measured"]),
        "resolution_errors": len(errored),
    }


def render(rows: list[dict[str, Any]] | None = None, *, as_json: bool = False) -> str:
    rows = list_assumptions() if rows is None else rows
    if as_json:
        import json
        return json.dumps({"assumptions": rows, "summary": summary()}, indent=2, sort_keys=False) + "\n"
    s = summary()
    lines = [f"assumptions: {s['total']} registered, {s['measured']} measured against live data, "
             f"{s['unmeasured']} not yet measured" + (f", {s['resolution_errors']} FAILED TO RESOLVE"
                                                        if s["resolution_errors"] else "")]
    for r in rows:
        tag = "MEASURED  " if r["measured"] else "unmeasured"
        lines.append(f"  {tag}  {r['name']} = {r['value']!r}  ({r['module']}.{r['attr']})")
        lines.append(f"              why: {r['why']}")
        if not r["measured"]:
            lines.append(f"              verify: {r['how_to_verify']}")
    return "\n".join(lines) + "\n"
