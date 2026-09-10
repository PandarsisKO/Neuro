"""Cost per unit of value (0.59.3) — $0, deterministic, no model call, no network.

Kyle, on the overnight work: *"the volume of data is always valuable, just HOW is something we want to keep
checking that we are improving against."* Every spend surface the app had answers a different question — `totals`
says how much, `reconcile` says how much was really charged, `rate_last_hour` says how fast. None of them says
whether the money bought anything. So a change like raising the findings cap from 12 to 20, or moving findings to
Haiku, could only ever be judged on whether the bill went up, which is the wrong axis: a change that costs 40%
more and produces twice as much is a good change, and a change that costs the same and produces nothing is not.

The unit of account here is a **thing the project can use** — a finding, a kept finding, a corroborated finding, a
Claim, a source read, a chat answer — and the number is dollars per one of those.

Three rules keep it honest.

1. **Spend is attributed by kind, never spread.** `$ per finding` divides the `findings` spend by the findings
   produced; it never divides the whole bill. Every kind that no unit claims is reported by name under
   `unattributed`, and `attributed + unattributed == total_charged` always, so the report reconciles against the
   bill instead of quietly explaining part of it.
2. **Charged, not recorded.** The cost of a row is `cost` plus, when the local path is billed (0.59.0), the `saved`
   figure a local call booked instead of a cost. Dividing recorded-only spend by output would have made the local
   path look free and every local unit cost $0 — the same error that hid $200.
3. **A count of zero is not a cost of infinity.** With spend and no output, `per_unit` is `None` with the reason
   stated, and with output and no spend it is `0.0` — a harvested Claim really is free.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any

from . import db

WINDOWS = ("today", "week", "month", "all")

# unit -> what it is, and which usage kinds paid for it
UNITS: dict[str, dict[str, Any]] = {
    "finding": {
        "kinds": ("findings",), "label": "finding written",
        "what": "every finding a model wrote for a source, whatever status it ended in",
    },
    "kept_finding": {
        "kinds": ("findings",), "label": "finding kept",
        "what": "approved or suggested — a finding the project can actually use",
    },
    "corroborated_finding": {
        "kinds": ("findings",), "label": "finding corroborated",
        "what": "a finding several independent sources agree on (findings_quality's strongest positive)",
        "needs_quality": True, "project_only": True,
    },
    "claim": {
        "kinds": ("claims",), "label": "Claim tracked",
        "what": "every Claim in the research state, including the ones harvested from findings for $0",
    },
    "normalized_claim": {
        "kinds": ("claims",), "label": "Claim normalized",
        "what": "a Claim the paid contract actually rewrote (the only thing `claims` spend buys)",
    },
    "source": {
        "kinds": ("whisper", "embed", "rank"), "label": "source read",
        "what": "a source taken from a URL to ready: transcription, embeddings and the ranking that chose it",
        "global_only": True,
    },
    "answer": {
        "kinds": ("answer",), "label": "chat answer",
        "what": "one assistant reply in a project chat",
    },
}

# Why a per-unit number can be wrong in a direction worth knowing about. Reported with every result.
CAVEATS = (
    "Promoting a withheld finding resets its created_at (db.set_note_status), so a sweep of the reserve pile "
    "shows up as findings 'written' today. The finding was paid for when it was written, not when it was promoted.",
    "Corroboration is a property of the whole corpus, so a finding written today can become corroborated "
    "tomorrow without any new spend. The count only ever rises for a past window.",
    "Transcription and embedding rows carry no project, so `source` is a whole-app number and is omitted from a "
    "per-project report rather than guessed at.",
    "Cache reads and the batch discount are already inside `cost`, so a cheaper unit cost can mean better cache "
    "layout rather than better output.",
    "A local (Claude Code) row's dollars are an ESTIMATE priced from its tokens, not an amount Anthropic invoiced, "
    "and they are priced at the CONTRACT's model rather than the model the CLI returned. `estimated_share` says "
    "how much of a window rests on that estimate; `by_model` refuses to divide where the basis is unknown.",
)


# ------------------------------------------------------------------ windows and the charged-cost expression

def window_start(window: str = "month", days: int | None = None) -> float:
    """Seconds since the epoch. `days` overrides `window` with a rolling window of that many days."""
    now = datetime.now()
    if days is not None:
        return (now - timedelta(days=int(days))).timestamp()
    if window == "today":
        return datetime(now.year, now.month, now.day).timestamp()
    if window == "week":
        return (now - timedelta(days=7)).timestamp()
    if window == "month":
        return datetime(now.year, now.month, 1).timestamp()
    return 0.0


def billed_local() -> bool:
    """True when a Claude Code call is a real charge. `unknown` counts as billed — assuming free is the specific
    error that hid $200 (0.59.0), so this defers entirely to `claude_code.local_is_free`."""
    try:
        from . import claude_code
        return not claude_code.local_is_free()
    except Exception:  # noqa: BLE001
        return True


def charged_expr(billed: bool | None = None) -> str:
    """The SQL for what a usage row actually cost the account."""
    if billed is None:
        billed = billed_local()
    if billed:
        return "(cost + CASE WHEN transport='local' THEN COALESCE(saved,0) ELSE 0 END)"
    return "cost"


def estimated_share(start: float, project_id: str | None = None, billed: bool | None = None) -> dict[str, Any]:
    """How much of the window's charge is a token-priced estimate (the local path) rather than a metered API call.
    A ratio built on estimates is still worth having — it is what caught the missing $200 — but it must say so."""
    q = (f"SELECT COALESCE(SUM({charged_expr(billed)}),0) total, "
         f"COALESCE(SUM(CASE WHEN transport='local' THEN {charged_expr(billed)} ELSE 0 END),0) local "
         "FROM usage WHERE ts>=?")
    args: list[Any] = [start]
    if project_id:
        q += " AND project_id=?"
        args.append(project_id)
    r = db.connect().execute(q, args).fetchone()
    total, local = float(r["total"] or 0), float(r["local"] or 0)
    return {"total": round(total, 6), "estimated": round(local, 6),
            "share": round(local / total, 4) if total else 0.0}


def spend_by_kind(start: float, project_id: str | None = None, billed: bool | None = None) -> dict[str, float]:
    q = f"SELECT kind, COALESCE(SUM({charged_expr(billed)}),0) c FROM usage WHERE ts>=?"
    args: list[Any] = [start]
    if project_id:
        q += " AND project_id=?"
        args.append(project_id)
    q += " GROUP BY kind"
    return {r["kind"]: round(float(r["c"] or 0), 6) for r in db.connect().execute(q, args).fetchall()}


# ------------------------------------------------------------------ counting the things that were produced

def _findings_counts(start: float, project_id: str | None) -> dict[str, int]:
    """`model IS NOT NULL` is what separates a machine-written finding from a note pinned by hand in chat — only
    the first kind was paid for, and only the first kind belongs in a denominator."""
    q = ("SELECT COALESCE(status,'approved') s, COUNT(*) n FROM project_notes "
         "WHERE created_at>=? AND model IS NOT NULL")
    args: list[Any] = [start]
    if project_id:
        q += " AND project_id=?"
        args.append(project_id)
    q += " GROUP BY s"
    by = {r["s"]: int(r["n"]) for r in db.connect().execute(q, args).fetchall()}
    total = sum(by.values())
    kept = by.get("approved", 0) + by.get("suggested", 0)
    return {"written": total, "kept": kept, "reserve": by.get("reserve", 0),
            "dismissed": by.get("dismissed", 0), "by_status": by}


def _claims_counts(start: float, project_id: str | None) -> dict[str, int]:
    q = "SELECT normalized, COUNT(*) n FROM project_claims WHERE created_at>=?"
    args: list[Any] = [start]
    if project_id:
        q += " AND project_id=?"
        args.append(project_id)
    q += " GROUP BY normalized"
    by = {int(r["normalized"] or 0): int(r["n"]) for r in db.connect().execute(q, args).fetchall()}
    return {"tracked": sum(by.values()), "normalized": by.get(1, 0), "harvested": by.get(0, 0)}


def _sources_ready(start: float) -> int:
    row = db.connect().execute("SELECT COUNT(*) n FROM sources WHERE status='ready' AND updated_at>=?",
                               (start,)).fetchone()
    return int(row["n"] or 0)


def _answers(start: float, project_id: str | None) -> int:
    q = ("SELECT COUNT(*) n FROM messages m JOIN conversations c ON c.id=m.conversation_id "
         "WHERE m.role='assistant' AND m.created_at>=?")
    args: list[Any] = [start]
    if project_id:
        q += " AND c.project_id=?"
        args.append(project_id)
    return int(db.connect().execute(q, args).fetchone()["n"] or 0)


def corroborated_in_window(project_id: str, start: float) -> dict[str, Any]:
    """How many findings created in this window are corroborated by another source. Uses the same cached
    `findings_quality` pass the Findings workbench uses, and is a FLOOR for the same reason (lexical, no
    embeddings) — the module publishes that limit and this inherits it."""
    from . import findings_quality
    ids = findings_quality.corroborated_ids(project_id)
    if not ids:
        return {"count": 0, "total_corroborated": 0}
    rows = db.connect().execute(
        "SELECT id FROM project_notes WHERE project_id=? AND created_at>=? AND model IS NOT NULL",
        (project_id, start)).fetchall()
    n = sum(1 for r in rows if int(r["id"]) in ids)
    return {"count": n, "total_corroborated": len(ids)}


def counts(start: float, project_id: str | None = None, include_quality: bool = False) -> dict[str, Any]:
    f = _findings_counts(start, project_id)
    c = _claims_counts(start, project_id)
    out: dict[str, Any] = {
        "finding": f["written"], "kept_finding": f["kept"], "claim": c["tracked"],
        "normalized_claim": c["normalized"], "answer": _answers(start, project_id),
        "detail": {"findings": f, "claims": c},
    }
    if not project_id:
        out["source"] = _sources_ready(start)
    if project_id and include_quality:
        try:
            out["corroborated_finding"] = corroborated_in_window(project_id, start)["count"]
        except Exception as e:  # noqa: BLE001 — a quality pass must never take the money report down
            out["detail"]["corroborated_error"] = str(e)[:160]
    return out


# ------------------------------------------------------------------ the report

def _per_unit(cost: float, n: int) -> tuple[float | None, str | None]:
    if n > 0:
        return round(cost / n, 6), None
    if cost > 0:
        return None, "spend with nothing to show for it in this window"
    return None, "nothing spent and nothing produced"


def unit_costs(window: str = "month", project_id: str | None = None, days: int | None = None,
               include_quality: bool = False) -> dict[str, Any]:
    """Dollars per unit of value for one window. The report reconciles: `attributed` + `unattributed` is the whole
    charged bill for the window, so no spend can hide behind a flattering ratio."""
    t0 = time.time()
    start = window_start(window, days)
    billed = billed_local()
    by_kind = spend_by_kind(start, project_id, billed)
    n = counts(start, project_id, include_quality)
    total = round(sum(by_kind.values()), 6)

    rows: list[dict[str, Any]] = []
    claimed: set[str] = set()
    for unit, spec in UNITS.items():
        if project_id and spec.get("global_only"):
            continue
        if not project_id and spec.get("project_only"):
            continue
        if spec.get("needs_quality") and unit not in n:
            continue
        cost = round(sum(by_kind.get(k, 0.0) for k in spec["kinds"]), 6)
        claimed.update(spec["kinds"])
        count = int(n.get(unit, 0))
        per, why = _per_unit(cost, count)
        rows.append({"unit": unit, "label": spec["label"], "what": spec["what"], "kinds": list(spec["kinds"]),
                     "cost": cost, "count": count, "per_unit": per, "per_unit_unavailable": why})
    unattributed = {k: v for k, v in by_kind.items() if k not in claimed and v}
    return {
        "window": window if days is None else f"last {days} days", "since": start, "project_id": project_id,
        "local_billed": billed, "rows": rows,
        "total_charged": total,
        "attributed": round(sum(v for k, v in by_kind.items() if k in claimed), 6),
        "unattributed": {"total": round(sum(unattributed.values()), 6), "by_kind": unattributed,
                         "note": ("Spend no unit of value claims. Discovery, planning, profiles and reranking are "
                                  "real work; they are listed here rather than folded into another unit's ratio.")},
        "spend_by_kind": by_kind, "counts": n,
        "estimated": estimated_share(start, project_id, billed),
        "caveats": list(CAVEATS),
        "how_to_read": ("Each row divides the spend of its own kinds by the things that kind produced. Compare a "
                        "row against the same row in an earlier window, never against another row: a Claim and a "
                        "finding are not the same size of thing."),
        "ms": round((time.time() - t0) * 1000, 1),
    }


def price_basis(start: float, kinds: tuple[str, ...], project_id: str | None = None,
                billed: bool | None = None) -> dict[str, dict[str, Any]]:
    """For each model that DID the work, which models' rates produced its dollars.

    This exists because the live data made the mistake for me. On Kyle's corpus a naive per-model split said
    findings cost $0.0231 each on Haiku against $0.0071 on Sonnet 5 — Haiku, at a fifth of the token price,
    somehow three times dearer per finding. The cause is `usage.record_anthropic`'s local branch: it writes the
    model the CLI returned into `model` and prices the tokens at the CONTRACT's model, because the avoided-spend
    figure is only meaningful against the model that would otherwise have run. Every one of those Haiku rows was
    Sonnet-priced. Reported as a per-model verdict it reads as a reason to stop using Haiku, which is the opposite
    of what the numbers support. `price_model` (0.59.3) records the basis from now on; where it is missing, the
    honest answer is that this comparison cannot be made from these rows."""
    ph = ",".join("?" for _ in kinds)
    q = (f"SELECT COALESCE(model,'?') m, COALESCE(price_model, CASE WHEN transport='local' THEN NULL ELSE model END) pm, "
         f"COALESCE(SUM({charged_expr(billed)}),0) c, COUNT(*) n FROM usage WHERE ts>=? AND kind IN ({ph})")
    args: list[Any] = [start, *kinds]
    if project_id:
        q += " AND project_id=?"
        args.append(project_id)
    out: dict[str, dict[str, Any]] = {}
    for r in db.connect().execute(q + " GROUP BY m, pm", args).fetchall():
        row = out.setdefault(str(r["m"]), {"cost": 0.0, "calls": 0, "bases": {}})
        cost = round(float(r["c"] or 0), 6)
        row["cost"] = round(row["cost"] + cost, 6)
        row["calls"] += int(r["n"])
        row["bases"][r["pm"] or "unknown"] = round(row["bases"].get(r["pm"] or "unknown", 0.0) + cost, 6)
    for model, row in out.items():
        bases = row["bases"]
        foreign = {b: v for b, v in bases.items() if b != model and v}
        row["mixed_basis"] = bool(foreign)
        row["foreign_basis"] = foreign
        row["comparable"] = not foreign
        if foreign:
            unknown = foreign.get("unknown", 0.0)
            row["why_not_comparable"] = (
                f"${round(sum(foreign.values()), 2)} of this model's spend was priced at another model's rates"
                + (" (basis not recorded — rows written before 0.59.3 on the local path)" if unknown else "")
                + ". Dividing it by this model's output would compare the wrong two things.")
    return out


def by_model(unit: str = "finding", window: str = "month", project_id: str | None = None,
             days: int | None = None) -> dict[str, Any]:
    """The same ratio, per model. Only the units whose output records the model that wrote it can answer this —
    `project_notes.model` and `project_claims.model` — which is what makes a Haiku-versus-Sonnet decision
    checkable after the fact instead of only in an eval.

    A row is only given a `per_unit` when its dollars were priced at its own rates (`price_basis`). Otherwise the
    row carries the cost, the count and the reason the division would lie."""
    spec = UNITS.get(unit)
    if spec is None or unit not in ("finding", "kept_finding", "claim", "normalized_claim"):
        return {"unit": unit, "supported": False,
                "reason": "only findings and Claims record the model that produced them",
                "supported_units": ["finding", "kept_finding", "claim", "normalized_claim"]}
    start = window_start(window, days)
    billed = billed_local()
    basis = price_basis(start, spec["kinds"], project_id, billed)

    if unit.endswith("claim"):
        cq = "SELECT COALESCE(model,'?') m, COUNT(*) n FROM project_claims WHERE created_at>=?"
        cargs: list[Any] = [start]
        if unit == "normalized_claim":
            cq += " AND normalized=1"
        if project_id:
            cq += " AND project_id=?"
            cargs.append(project_id)
    else:
        cq = "SELECT COALESCE(model,'?') m, COUNT(*) n FROM project_notes WHERE created_at>=? AND model IS NOT NULL"
        cargs = [start]
        if unit == "kept_finding":
            cq += " AND COALESCE(status,'approved') IN ('approved','suggested')"
        if project_id:
            cq += " AND project_id=?"
            cargs.append(project_id)
    count_by = {str(r["m"]): int(r["n"]) for r in db.connect().execute(cq + " GROUP BY m", cargs).fetchall()}

    rows = []
    for model in sorted(set(basis) | set(count_by)):
        b = basis.get(model) or {"cost": 0.0, "calls": 0, "bases": {}, "comparable": True}
        count = count_by.get(model, 0)
        if b.get("comparable", True):
            per, why = _per_unit(b["cost"], count)
        else:
            per, why = None, b.get("why_not_comparable")
        rows.append({"model": model, "cost": b["cost"], "calls": b["calls"], "count": count, "per_unit": per,
                     "per_unit_unavailable": why, "comparable": bool(b.get("comparable", True)),
                     "price_basis": b.get("bases", {})})
    rows.sort(key=lambda r: (r["per_unit"] is None, r["per_unit"] if r["per_unit"] is not None else 0))
    comparable = [r for r in rows if r["per_unit"] is not None]
    return {"unit": unit, "supported": True, "label": spec["label"], "window": window, "since": start,
            "project_id": project_id, "local_billed": billed, "rows": rows,
            "comparable_models": len(comparable),
            "verdict": (None if len(comparable) < 2 else
                        f"{comparable[0]['model']} is the cheapest per {spec['label']} in this window "
                        f"(${comparable[0]['per_unit']:.4f} against ${comparable[-1]['per_unit']:.4f})"),
            "note": ("Cost comes from the usage ledger, the count from the model recorded on the output itself. A "
                     "model that produced output in this window with its spend in an earlier one (a batch, a "
                     "promoted reserve note) shows a count with no cost — that is the windows failing to line up, "
                     "not a free lunch."),
            "caveats": list(CAVEATS)}


def trend(unit: str = "kept_finding", days: int = 14, project_id: str | None = None) -> dict[str, Any]:
    """Per-day cost per unit, so a change of policy can be seen landing. Local dates throughout, matching
    `usage.reconcile`'s per-day rows."""
    spec = UNITS.get(unit)
    if spec is None:
        return {"unit": unit, "supported": False, "reason": "unknown unit", "units": list(UNITS)}
    if project_id and spec.get("global_only"):
        return {"unit": unit, "supported": False, "reason": "this unit has no per-project spend"}
    billed = billed_local()
    start = window_start("all", days)
    kinds = spec["kinds"]
    ph = ",".join("?" for _ in kinds)
    q = (f"SELECT date(ts,'unixepoch','localtime') d, COALESCE(SUM({charged_expr(billed)}),0) c "
         f"FROM usage WHERE ts>=? AND kind IN ({ph})")
    args: list[Any] = [start, *kinds]
    if project_id:
        q += " AND project_id=?"
        args.append(project_id)
    cost_by = {r["d"]: round(float(r["c"] or 0), 6) for r in db.connect().execute(q + " GROUP BY d", args).fetchall()}

    if unit in ("finding", "kept_finding"):
        cq = ("SELECT date(created_at,'unixepoch','localtime') d, COUNT(*) n FROM project_notes "
              "WHERE created_at>=? AND model IS NOT NULL")
        cargs: list[Any] = [start]
        if unit == "kept_finding":
            cq += " AND COALESCE(status,'approved') IN ('approved','suggested')"
    elif unit in ("claim", "normalized_claim"):
        cq = "SELECT date(created_at,'unixepoch','localtime') d, COUNT(*) n FROM project_claims WHERE created_at>=?"
        cargs = [start]
        if unit == "normalized_claim":
            cq += " AND normalized=1"
    elif unit == "source":
        cq = ("SELECT date(updated_at,'unixepoch','localtime') d, COUNT(*) n FROM sources "
              "WHERE status='ready' AND updated_at>=?")
        cargs = [start]
    elif unit == "answer":
        cq = ("SELECT date(m.created_at,'unixepoch','localtime') d, COUNT(*) n FROM messages m "
              "JOIN conversations c ON c.id=m.conversation_id WHERE m.role='assistant' AND m.created_at>=?")
        cargs = [start]
    else:
        return {"unit": unit, "supported": False, "reason": "no per-day count exists for this unit"}
    if project_id:
        cq += " AND c.project_id=?" if unit == "answer" else " AND project_id=?"
        cargs.append(project_id)
    count_by = {r["d"]: int(r["n"]) for r in db.connect().execute(cq + " GROUP BY d", cargs).fetchall()}

    rows = []
    for day in sorted(set(cost_by) | set(count_by), reverse=True):
        cost, n = cost_by.get(day, 0.0), count_by.get(day, 0)
        per, why = _per_unit(cost, n)
        rows.append({"day": day, "cost": cost, "count": n, "per_unit": per, "per_unit_unavailable": why})
    return {"unit": unit, "supported": True, "label": spec["label"], "days": days, "project_id": project_id,
            "local_billed": billed, "rows": rows, "caveats": list(CAVEATS)}


def report(project_id: str | None = None, include_quality: bool = False) -> dict[str, Any]:
    """Everything the panel needs in one request: three windows, the per-model split for findings and Claims, and
    a two-week trend for the unit that matters most (a finding you keep)."""
    out: dict[str, Any] = {"windows": {}, "project_id": project_id, "units": UNITS}
    for w in ("today", "week", "month"):
        out["windows"][w] = unit_costs(w, project_id, include_quality=include_quality)
    out["by_model"] = {u: by_model(u, "month", project_id) for u in ("finding", "kept_finding", "normalized_claim")}
    out["trend"] = trend("kept_finding", 14, project_id)
    out["caveats"] = list(CAVEATS)
    return out


def headline(project_id: str | None = None) -> dict[str, Any]:
    """One line for Health: what a kept finding cost this month, and this week, and whether that is moving."""
    m = unit_costs("month", project_id)
    w = unit_costs("week", project_id)

    def pick(rep: dict[str, Any], unit: str) -> dict[str, Any]:
        for r in rep["rows"]:
            if r["unit"] == unit:
                return r
        return {}
    mk, wk = pick(m, "kept_finding"), pick(w, "kept_finding")
    direction = None
    if mk.get("per_unit") and wk.get("per_unit"):
        direction = "cheaper" if wk["per_unit"] < mk["per_unit"] else ("dearer" if wk["per_unit"] > mk["per_unit"] else "flat")
    return {"month": {"per_kept_finding": mk.get("per_unit"), "kept": mk.get("count"), "cost": mk.get("cost")},
            "week": {"per_kept_finding": wk.get("per_unit"), "kept": wk.get("count"), "cost": wk.get("cost")},
            "week_vs_month": direction, "local_billed": m["local_billed"],
            "unattributed_month": m["unattributed"]["total"], "total_charged_month": m["total_charged"]}
