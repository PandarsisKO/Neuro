"""Resolve the saved plan's task references for the UI, exports, and status storage."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
import json
from typing import Any, Iterable


def _text(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def task_layout(plan: dict) -> tuple[dict, dict, list[str]]:
    """Return canonical action rows, status aliases, and the saved weekly selection.

    Newer plans explicitly reference phase tasks. Older plans can share status
    only when their action wording matches one unique task in the other list.
    """
    phases = plan.get("phases") or []
    phase_tasks = {
        f"phases.{i}.tasks.{j}": {**task, "label": task.get("task", ""), "phase": i}
        for i, phase in enumerate(phases) for j, task in enumerate(phase.get("tasks") or [])
    }
    tasks = dict(phase_tasks)
    ids = {task["id"]: key for key, task in phase_tasks.items() if task.get("id")}
    names = defaultdict(list)
    for key, task in phase_tasks.items():
        names[_text(task["label"])].append(key)
    steps = plan.get("first_steps") or []
    step_names = Counter(_text(step.get("action")) for step in steps)
    aliases = {}
    known_aliases = plan.get("_task_aliases") or {}

    for i, step in enumerate(steps):
        key = f"first_steps.{i}"
        name = _text(step.get("action"))
        matches = names.get(name, []) if name and step_names[name] == 1 else []
        target = ids.get(step.get("task")) or known_aliases.get(key) or (matches[0] if len(matches) == 1 else key)
        if target == key:
            tasks[key] = {**step, "label": step.get("action", ""), "phase": None}
        else:
            aliases[key] = target
            task = tasks[target]
            task["today"] = bool(task.get("today") or step.get("today"))
            if not task.get("detail") and step.get("detail"):
                task["detail"] = step["detail"]
            if not task.get("evidence") and step.get("evidence"):
                task["evidence"] = step["evidence"]
        if target not in names[name]:
            names[name].append(target)

    week = []
    for i, item in enumerate(plan.get("this_week") or []):
        key = f"this_week.{i}"
        name = _text(item.get("action"))
        matches = names.get(name, []) if name else []
        target = ids.get(item.get("task")) or known_aliases.get(key) or (matches[0] if len(matches) == 1 else key)
        if target == key:
            tasks[key] = {**item, "label": item.get("action", ""), "phase": None}
        else:
            aliases[key] = target
        if target not in week:
            week.append(target)
        task = tasks[target]
        for field in ("time", "why"):
            if item.get(field) and not task.get(field):
                task[field] = item[field]
    return tasks, aliases, week


def _item_keys(plan: dict, tasks: dict, aliases: dict) -> tuple[dict, dict]:
    """Return comparable identities for the existing status-bearing fields."""
    keys = {key: ("action", _text(task["label"]), _text(task.get("detail") or task.get("why")))
            for key, task in tasks.items()}
    for group, field in (("dependencies", "item"), ("decisions", "decision"), ("open_questions", "question")):
        for i, item in enumerate(plan.get(group) or []):
            keys[f"{group}.{i}"] = (group, _text(item.get(field)), "")
    ids = defaultdict(set)
    for path, identity in (plan.get("_ids") or {}).items():
        key = aliases.get(path, path)
        if key in keys:
            ids[key].add(identity)
    return keys, ids


def canonical_items(rows: Iterable, aliases: dict) -> dict:
    """Read historic alias rows together. The newest status and latest saved note win."""
    items = {}
    for row in sorted(rows, key=lambda row: (row["updated_at"], row["key"] not in aliases)):
        key = aliases.get(row["key"], row["key"])
        prior = items.get(key, {})
        note = row["note"] if row["note"] is not None else prior.get("note")
        items[key] = {"status": row["status"], "note": note}
    return items


def carry_items(previous: dict, current: dict, rows: Iterable, *, exact_edit: bool = False) -> tuple[dict, list[dict]]:
    old_tasks, old_aliases, _ = task_layout(previous)
    new_tasks, new_aliases, _ = task_layout(current)
    old, old_ids = _item_keys(previous, old_tasks, old_aliases)
    new, new_ids = _item_keys(current, new_tasks, new_aliases)
    by_text = defaultdict(list)
    by_id = defaultdict(set)
    for key, identity in new.items():
        by_text[identity].append(key)
        for item_id in new_ids.get(key, ()):
            by_id[item_id].add(key)
    old_counts = Counter(old.values())
    carried, review = {}, []
    matches = defaultdict(list)
    for key, item in canonical_items(rows, old_aliases).items():
        identity = old.get(key)
        if exact_edit:
            paths = [key] + [path for path, target in old_aliases.items() if target == key]
            primary = new_aliases.get(key, key)
            candidates = {primary} if primary in new else {new_aliases.get(path, path) for path in paths} & new.keys()
        else:
            candidates = {target for item_id in old_ids.get(key, ()) for target in by_id[item_id]}
            if not candidates and identity and identity[1] and old_counts[identity] == 1:
                candidates = {target for target in by_text[identity]
                              if not old_ids.get(key) or not new_ids.get(target)}
        if len(candidates) == 1:
            matches[next(iter(candidates))].append((key, item))
        elif item["status"] != "not_started" or item["note"]:
            review.append({"label": (old_tasks.get(key) or {}).get("label") or key, "status": item["status"]})
    for target, entries in matches.items():
        if len(entries) == 1:
            carried[target] = entries[0][1]
        else:
            for key, item in entries:
                if item["status"] != "not_started" or item["note"]:
                    review.append({"label": (old_tasks.get(key) or {}).get("label") or key, "status": item["status"]})
    return carried, review


def execution_view(plan: dict, items: dict) -> dict:
    tasks, aliases, week = task_layout(plan)
    phases = plan.get("phases") or []

    def completed(key):
        return items.get(key, {}).get("status") in ("complete", "done")

    active = next((i for i, _ in enumerate(phases)
                   if any(task["phase"] == i and not completed(key) for key, task in tasks.items())), None)
    phase = phases[active] if active is not None else None
    task_ids = {task["id"]: key for key, task in tasks.items() if task.get("id")}
    first = [aliases.get(f"first_steps.{i}", f"first_steps.{i}") for i, _ in enumerate(plan.get("first_steps") or [])]
    next_keys = list(dict.fromkeys(week + first + [k for k, t in tasks.items() if active is not None and t["phase"] == active]))
    for key, task in tasks.items():
        task["unmet"] = [tasks[task_ids[dep]]["label"] for dep in (task.get("depends_on") or [])
                 if dep in task_ids and not completed(task_ids[dep])]
        task["blocked"] = bool(task["unmet"] or items.get(key, {}).get("status") in
                               ("blocked", "needs_research", "needs_decision"))
    ordered = []
    for key in next_keys:
        task = tasks[key]
        if completed(key) or (task["phase"] is not None and task["phase"] != active):
            continue
        ordered.append({"key": key, **task})
    ordered.sort(key=lambda task: (task["blocked"], items.get(task["key"], {}).get("status") != "in_progress"))
    return {"phase": {k: phase.get(k) for k in ("id", "name", "objective", "outcome", "decisions")} if phase else None,
            "phase_index": active, "next_actions": ordered[:5], "aliases": aliases,
            "tasks": tasks, "week": week, "completed": sum(completed(key) for key in tasks)}


def confirmed_deadlines(facts: Iterable) -> list[dict]:
    """Only explicit project facts establish hard deadlines."""
    deadlines = []
    for fact in facts:
        if fact.get("kind") != "deadline":
            continue
        try:
            item = json.loads(fact["content"])
            due = date.fromisoformat(item["date"]).isoformat()
            label = item["label"].strip()
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
        if label:
            deadlines.append({"id": fact["id"], "date": due, "label": label,
                              "consequence": str(item.get("consequence") or ""),
                              "fallback": str(item.get("fallback") or "")})
    return sorted(deadlines, key=lambda item: item["date"])


_ACTIVITY_DECISIONS = {"decision_recorded": "Decision recorded", "decision_changed": "Decision changed",
                       "decision_withdrawn": "Decision withdrawn"}
_ACTIVITY_SOURCES = {"source_revised": "Cited source revised", "source_removed": "Cited source removed"}
_ACTIVITY_TYPES = {*_ACTIVITY_DECISIONS, *_ACTIVITY_SOURCES, "plan_item_status_changed", "plan_version_created",
                   "finding_status_changed", "claim_assessment_changed", "claim_evidence_added"}


def recent_changes(project_id: str, plan_row: dict, since: int | None, until: int | None = None) -> dict:
    """Read a bounded project ledger page using the current plan's recorded citations."""
    from . import db, ledger
    from .decision_impact import decision_impact
    from .evidence import plan_evidence_ids

    top = ledger.cursor(project_id)
    if until is not None:
        top = min(top, until)
    if since is None or since > top:
        return {"cursor": top, "next_cursor": top, "changes": [], "more": False, "baseline": True}

    page = ledger.events(project_id, since=since, until=top, event_types=_ACTIVITY_TYPES, limit=50, classify=False)
    events = sorted(page["events"], key=lambda event: event["id"])
    plan = plan_row["plan"]
    evidence = plan.get("_evidence") or {}
    cited = {eid: evidence[eid] for eid in plan_evidence_ids(plan) if eid in evidence}
    sources = {ref["source_id"]: eid for eid, ref in cited.items() if ref.get("source_id")}
    findings = {str(ref["note_id"]): eid for eid, ref in cited.items() if ref.get("note_id") is not None}
    claim_ids = {e["object_id"] if e["object_type"] == "claim" else (e["after"] or {}).get("claim_id")
                 for e in events if e["object_type"] in ("claim", "claim_evidence")}
    impacts = decision_impact(project_id, sorted(claim_ids - {None})) if claim_ids else {}
    versions = {v["id"]: v["version"] for v in db.list_plans(project_id)}
    tasks, aliases, _ = task_layout(plan)
    project_decisions = {str(f["id"]) for f in db.list_facts(project_id, include_history=True)
                         if f["kind"] == "decision" and f["scope"] == "project"} if any(
                             e["event_type"] in _ACTIVITY_DECISIONS for e in events) else set()
    changes = []

    for event in events:
        kind, key = event["event_type"], event["object_id"]
        before, after = event["before"] or {}, event["after"] or {}
        change = {"at": event["created_at"]}
        if kind in _ACTIVITY_DECISIONS:
            if key not in project_decisions:
                continue
            target = after.get("superseded_by") or key
            detail = after.get("content") or before.get("content")
            if after.get("rationale"):
                detail = f"{detail} · {after['rationale']}"
            change.update(title=_ACTIVITY_DECISIONS[kind], detail=detail,
                          section="decisions", anchor=f"plan-fact-{target}")
        elif kind == "plan_version_created":
            change.update(title=f"Plan version {after.get('version')} saved", section="history",
                          anchor=f"plan-version-{after.get('version')}")
        elif kind == "plan_item_status_changed":
            plan_id, _, path = key.partition(":")
            if before.get("status") == after.get("status") or plan_id not in versions:
                continue
            detail = f"{before.get('status', '').replace('_', ' ')} → {after.get('status', '').replace('_', ' ')}"
            if plan_id == plan_row["id"]:
                path = aliases.get(path, path)
                task = tasks.get(path)
                group, _, index = path.partition(".")
                fields = {"decisions": "decision", "dependencies": "item", "open_questions": "question"}
                if task:
                    label = task["label"]
                elif group in fields and index.isdigit() and int(index) < len(plan.get(group) or []):
                    label = plan[group][int(index)].get(fields[group])
                else:
                    label = None
                change.update(title=label or "Plan item status changed", detail=detail,
                              section="decisions" if group in ("decisions", "open_questions") else "work",
                              anchor=f"plan-item-{path}")
            else:
                change.update(title=f"Task status changed in v{versions[plan_id]}", detail=detail,
                              section="history", anchor=f"plan-version-{versions[plan_id]}")
        elif kind in _ACTIVITY_SOURCES or kind == "finding_status_changed":
            eid = sources.get(key) if kind in _ACTIVITY_SOURCES else findings.get(key)
            if not eid:
                continue
            change.update(title=_ACTIVITY_SOURCES.get(kind, "Cited finding status changed"),
                          detail=cited[eid]["label"], section="evidence", anchor=f"plan-citation-{eid}")
        else:
            cid = key if event["object_type"] == "claim" else after.get("claim_id")
            if impacts.get(cid, {}).get("plan_impact") is not True:
                continue
            claim = db.connect().execute("SELECT text FROM project_claims WHERE id=? AND project_id=?",
                                         (cid, project_id)).fetchone()
            if not claim:
                continue
            title = "Evidence added to a linked claim" if kind == "claim_evidence_added" else "Linked claim reassessed"
            change.update(title=title, detail=claim["text"], section="evidence", claim_id=cid)
        changes.append(change)
    return {"cursor": top, "next_cursor": page["next_cursor"], "changes": changes, "more": page["more"], "baseline": False}
