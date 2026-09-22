"""P11 EA-9 — bring Neuro in LATE: catch-up sync of what mattered in an external conversation (Kyle, 2026-09-22).

Product principle: *Neuro must be available when the user remembers it, not only when the conversation starts.* A person
talks freely with their AI, then says "save what matters to Neuro", "check all of this against Neuro", or "send our
decision to Neuro". The client assembles a STRUCTURED handoff of the durable, project-relevant state from the
conversation so far; Neuro stores it through the existing P11 paths — never the raw transcript unless the person
explicitly asks for an archive — and answers with a short receipt.

It adds no new state model: one idempotent intake (intake.py) groups the materials, retained originals and the
assistant's analysis; the user's own statements go through apply_state/facts.py exactly like sync_project_state.
The classifications stay apart — user statement ≠ evidence ≠ external extraction ≠ assistant interpretation.

Late project binding (no project needed when the conversation starts; Kyle's review, 2026-09-22):
  - project_id (the user chose it, or it was confirmed earlier in this conversation) → write;
  - a name the USER said (`project_named_by_user`) that matches exactly one permitted project → write;
  - an inferred hint with one clear match → `confirm_project` with that suggestion, NOTHING written;
  - anything else → `needs_project` with the permitted candidates, NOTHING written.
  Unpermitted projects never appear. The client keeps a confirmed binding in its own conversation context; Neuro keeps
  no per-conversation state for it.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from . import access, claims, db, facts, intake
from .access import AccessError, Principal
from .external_schemas import check

# Presentation chatter is not project memory (§30, §50). The client is told not to send it; this is the backstop for a
# short item that is plainly an instruction about wording or format rather than about the project.
_CHATTER = re.compile(
    r"^\s*(please\s+)?(make (it|this|that|the (email|message|reply|draft|text))\s+(shorter|longer|warmer|friendlier|punchier|clearer|"
    r"simpler|more (formal|casual|polite|concise|direct)|less (formal|casual|wordy))|try again|redo (it|that)|rewrite (it|this|that)|"
    r"reword|rephrase|shorten (it|this|that)|reformat|format (it|this|that)|(give|show) me \d+ (versions|options|drafts)|"
    r"use a (warmer|different|friendlier|more formal) tone|change the tone|fix the (grammar|formatting|typos?))\b", re.I)
CHATTER_MAX = 90
LABEL = {"decision": ("decision", "decisions"), "constraint": ("constraint", "constraints"), "requirement": ("requirement", "requirements"),
         "rejected": ("rejected option", "rejected options"), "commitment": ("commitment", "commitments"), "deadline": ("deadline", "deadlines"),
         "counterpart_position": ("counterpart position", "counterpart positions"), "concern": ("concern", "concerns"),
         "open_question": ("open question", "open questions"), "preference": ("personal preference", "personal preferences"),
         "context": ("fact", "facts"), "reaffirmation": ("reaffirmation", "reaffirmations"), "change": ("change", "changes")}


def is_chatter(text: str) -> bool:
    return len(text.strip()) <= CHATTER_MAX and bool(_CHATTER.match(text))


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[\s.!?;:,]+$", "", (s or "").strip().lower()))


# ------------------------------------------------------------------ late project binding

def candidates(principal: Principal, hint: str | None) -> list[dict[str, Any]]:
    """Permitted projects only, best match first. A match is a name hit or a shared-word overlap with name + brief."""
    rows = access.granted_projects(principal)
    briefs = {r["id"]: (db.get_project(r["id"]) or {}).get("brief") or "" for r in rows}
    h = _norm(hint or "")
    out = []
    for r in rows:
        name = _norm(r["name"])
        score = 0.0
        if h:
            if h == name:
                score = 3.0
            elif h in name or (name and name in h):
                score = 2.0
            else:
                score = claims.overlap(h, f"{r['name']} {briefs[r['id']]}")
        out.append({"project_id": r["id"], "name": r["name"], "role": r["role"], "match": round(score, 3)})
    out.sort(key=lambda x: (-x["match"], x["name"].lower()))
    return out


def resolve(principal: Principal, project_id: str | None, hint: str | None,
            named_by_user: bool = False) -> tuple[str | None, str, list[dict[str, Any]]]:
    """→ (project_id to write to, or None; 'write' | 'confirm_project' | 'needs_project'; candidates)."""
    if project_id:
        return project_id, "write", []
    c = candidates(principal, hint)
    strong = [x for x in c if x["match"] >= 2.0]
    if hint and len(strong) == 1:
        return (strong[0]["project_id"], "write", c) if named_by_user else (None, "confirm_project", strong)
    return None, "needs_project", [x for x in c if x["match"] > 0][:8] or c[:8]


# ------------------------------------------------------------------ the sync

def _derived_id(req: str, i: int, ch: dict[str, Any]) -> str:
    h = hashlib.sha256(json.dumps([req, i, ch.get("op"), ch.get("kind"), ch.get("fact_id"), ch.get("content")], sort_keys=True).encode()).hexdigest()
    return f"cs:{h[:24]}"


def sync(principal: Principal, args: dict[str, Any], apply_state: Any, envelope: Any) -> dict[str, Any]:
    body = check("external.conversation_sync.v1", args)
    pid, how, cands = resolve(principal, body.get("project_id"), body.get("project_hint"), bool(body.get("project_named_by_user")))
    if pid is None:
        if how == "confirm_project":
            return envelope({"status": "confirm_project", "saved": False, "suggestion": cands[0], "candidates": cands,
                             "ask": f"This looks like the {cands[0]['name']} project. Save it there?"})
        return envelope({"status": "needs_project", "saved": False, "candidates": cands,
                         "ask": "Which Neuro project should this go to?" if cands else "You have no Neuro projects you can save to."})
    auth = access.authorize(principal, pid, "sync_conversation_to_project")
    req = body["client_request_id"]

    prior = db.connect().execute("SELECT * FROM external_intakes WHERE client_id=? AND client_request_id=?", (principal.client_id, req)).fetchone()
    if prior and prior["receipt"]:
        if prior["project_id"] != pid:
            raise AccessError("invalid", "that client_request_id was already used for a different project")
        return envelope({**json.loads(prior["receipt"]), "idempotent_replay": True}, auth=auth)

    # ---- user statements: drop chatter, derive request ids. Whether something is already known, restated (a
    # reaffirmation) or would replace project truth is decided in apply_state, the one write path for user state.
    changes, skipped = [], {"presentation": 0, "already_known": 0}
    for i, ch in enumerate(body.get("state") or []):
        ch = dict(ch)
        text = ch.get("content") or ""
        if text and is_chatter(text):
            skipped["presentation"] += 1
            continue
        ch.setdefault("client_request_id", _derived_id(req, i, ch))
        changes.append(ch)

    # ---- one intake groups the materials, originals and analysis of this sync
    it = intake.create(auth, {"client_request_id": req, "conversation_ref": body.get("conversation_ref"), "base_revision": body.get("base_revision")})
    iid = it["intake_id"]
    items: list[str] = []
    for i, m in enumerate(body.get("materials") or []):
        items.append(intake.add_processed(auth, {"intake_id": iid, "material": m, "item_request_id": f"{req}:m{i}"})["item"]["item_id"])
    if body.get("archive_transcript"):                      # only on the person's explicit request (schema-enforced)
        text = body["archive_transcript"]["text"]
        intake.add_processed(auth, {"intake_id": iid, "item_request_id": f"{req}:archive", "material": {
            "material_type": "text", "title": "Conversation archive (saved on request)", "producer": principal.client_label or "external client",
            "extraction_method": "manual", "client_declared_class": "restricted",      # a whole conversation: closed until the owner classifies it
            "units": [{"locator": f"part {n + 1}", "text": text[k:k + 8000]} for n, k in enumerate(range(0, len(text), 8000))]}})
    files_out = []
    for i, f in enumerate(body.get("files") or []):
        target = f.get("original_of_material")
        if target is not None and not (0 <= target < len(items)):
            raise AccessError("invalid", f"files[{i}].original_of_material points at no material")
        r = intake.attach(auth, {"intake_id": iid, "artifact_ref": f["artifact_ref"], "item_request_id": f"{req}:f{i}",
                                 "item_id": items[target] if target is not None else None,
                                 "client_declared_class": f.get("client_declared_class")})
        files_out.append(r["item"]["item_id"])

    fin = intake.finalize(auth, {"intake_id": iid, "user_state": changes or None, "interpretations": body.get("analysis") or None,
                                 "base_revision": body.get("base_revision")}, apply_state=apply_state)
    state = fin.get("state") or {"applied": [], "conflicts": [], "refused": [], "skipped": []}
    skipped["already_known"] += len(state.get("skipped") or [])

    # ---- receipt: what was saved, in the person's terms; machinery only when something needs them
    counts: dict[str, int] = {}
    proposed = []
    for a in state["applied"]:
        f = a["fact"]
        if a["status"] == "proposed":
            proposed.append(f["content"])
            continue
        k = "reaffirmation" if a["op"] == "reaffirm" else ("change" if a["op"] == "supersede" else f["kind"])
        counts[k] = counts.get(k, 0) + 1
    n_mat = len(body.get("materials") or [])
    parts = [f"{n} {LABEL.get(k, (k, k + 's'))[0 if n == 1 else 1]}" for k, n in counts.items()]
    if n_mat:
        parts.append(f"{n_mat} processed material{'s' if n_mat != 1 else ''}")
    if proposed:
        parts.append(f"{len(proposed)} suggestion{'s' if len(proposed) != 1 else ''} to review")
    name = (db.get_project(pid) or {}).get("name")
    attention = []
    for c in state["conflicts"]:
        attention.append({"kind": "conflict", "fact_id": c["fact_id"], "reason": c["reason"], "current": c.get("current"),
                          "proposed": c.get("proposed")})
    for r in state.get("refused") or []:
        attention.append({"kind": "needs_user_words", **r})
    for i in fin.get("items") or []:
        if i["status"] == "failed":
            attention.append({"kind": "material_failed", "item_id": i["item_id"], "error": i.get("error")})
    receipt = {"status": "saved", "saved": True, "project": {"project_id": pid, "name": name},
               "summary": (f"Saved to {name}: " + ", ".join(parts)) if parts else f"Nothing new to save to {name}",
               "counts": {**counts, "materials": n_mat, "analysis": len(body.get("analysis") or []), "suggestions_to_review": len(proposed),
                          "files": len(files_out)},
               "skipped": skipped, "needs_attention": attention, "intake_id": iid, "intake_status": fin["status"],
               "facts": [{"op": a["op"], **a["fact"]} for a in state["applied"]],
               "next": "To check this against the project, call consult_project with the same project_id now."}
    with db.tx() as conn:
        conn.execute("UPDATE external_intakes SET receipt=? WHERE id=?", (json.dumps(receipt, default=str), iid))
    return envelope(receipt, auth=auth)
