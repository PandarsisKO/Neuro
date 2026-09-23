"""P11: a conversation saved from an outside AI lands in the project's Chats (Kyle, 2026-09-22).

Kyle, after his first real save from ChatGPT: "chats from ChatGPT should just land in chats... naturally." The save
already worked — a context fact and an intake — but it surfaced only halfway down Settings, where nobody looks for a
conversation. So every successful `sync_conversation_to_project` also writes ONE readable message into a Neuro chat:

- one Neuro chat per outside conversation: the id is derived from (client, conversation_ref), so a second save from
  the same ChatGPT conversation appends to the same chat; a save with no conversation_ref gets its own chat;
- the message says what was saved, in the person's terms — what they decided (with their own words), facts, open
  questions, what is waiting for review, the material the outside AI read, and that AI's own reading, labelled as
  not evidence. It is a record of the save, not the transcript (the transcript is never sent unless asked for);
- it is an ordinary chat: the owner can open it and keep talking to the project there, and the saved summary is part
  of that chat's history.

Mirroring is a courtesy on top of a save that has already committed: any failure here is logged and swallowed,
never turned into a failed save.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any

from . import access, db

log = logging.getLogger(__name__)

HEADINGS = (
    ("decision", "Decided"), ("change", "Changed"), ("reaffirmation", "Reaffirmed"), ("constraint", "Constraints"),
    ("requirement", "Requirements"), ("commitment", "Commitments"), ("deadline", "Deadlines"), ("rejected", "Ruled out"),
    ("counterpart_position", "Their position"), ("concern", "Concerns"), ("open_question", "Still open"),
    ("preference", "Personal preferences"), ("context", "Facts"),
)


def app_name(label: str | None) -> str:
    low = (label or "").lower()
    if "chatgpt" in low or "openai" in low:
        return "ChatGPT"
    if "claude" in low:
        return "Claude"
    return label or "an AI app"


def conversation_id(client_id: str, conversation_ref: str | None, client_request_id: str) -> str:
    key = f"{client_id}|{conversation_ref or 'req:' + client_request_id}"
    return "ext-" + hashlib.sha1(key.encode()).hexdigest()[:24]


def _clip(s: str, n: int) -> str:
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def render(app: str, who: str, body: dict[str, Any], receipt: dict[str, Any]) -> str:
    lines = [f"**Saved from {app}**" + (f" by {who}" if who else "")]
    groups: dict[str, list[str]] = {}
    review: list[str] = []
    words = {" ".join((c.get("content") or "").split()).lower(): c.get("user_text") or ""
             for c in body.get("state") or [] if c.get("user_text")}
    for f in receipt.get("facts") or []:
        text = _clip(f.get("content") or "", 240)
        if f.get("status") == "proposed":
            review.append(text + ("  (suggested by " + app + ")" if f.get("explicitness") == "inferred" else ""))
            continue
        key = "reaffirmation" if f.get("op") == "reaffirm" else ("change" if f.get("op") == "supersede" else f.get("kind") or "context")
        said = _clip(f.get("user_text") or words.get(" ".join((f.get("content") or "").split()).lower(), ""), 160)
        groups.setdefault(key, []).append(text + (f"  — you said: “{said}”" if said and said.lower() not in text.lower() else ""))
    for key, title in HEADINGS:
        if groups.get(key):
            lines.append(f"\n**{title}**")
            lines += [f"• {t}" for t in groups[key]]
    if review:
        lines.append("\n**Waiting for your review** (Settings → Waiting for your review)")
        lines += [f"• {t}" for t in review]
    mats = body.get("materials") or []
    if mats:
        lines.append(f"\n**Material {app} read**")
        for m in mats:
            n = len(m.get("units") or [])
            lines.append(f"• {_clip(m.get('title') or m.get('material_type') or 'material', 120)}" + (f" ({n} part{'s' if n != 1 else ''})" if n else ""))
    nfiles = (receipt.get("counts") or {}).get("files") or 0
    if nfiles:
        lines.append(f"• {nfiles} original file{'s' if nfiles != 1 else ''} kept")
    analysis = [a.get("text") or "" for a in body.get("analysis") or [] if (a.get("text") or "").strip()]
    if analysis:
        lines.append(f"\n**{app}'s own reading** (kept apart, not evidence)")
        lines += [f"• {_clip(t, 400)}" for t in analysis]
    attention = receipt.get("needs_attention") or []
    if attention:
        lines.append(f"\n**Needs your attention:** {len(attention)} item{'s' if len(attention) != 1 else ''} (see Settings)")
    if len(lines) == 1:
        lines.append("\nNothing new — everything in this save was already in the project.")
    return "\n".join(lines)


def _title(app: str, body: dict[str, Any], receipt: dict[str, Any]) -> str:
    facts = [f for f in receipt.get("facts") or [] if f.get("status") != "proposed"] or list(receipt.get("facts") or [])
    topic = (facts[0].get("content") if facts else None) or next((m.get("title") for m in body.get("materials") or [] if m.get("title")), None)
    return f"{app} · " + (_clip(topic, 60) if topic else "saved conversation")


def record(principal: access.Principal, project_id: str, body: dict[str, Any], receipt: dict[str, Any]) -> str | None:
    """Write the save into the project's Chats. Returns the Neuro conversation id, or None if mirroring failed."""
    try:
        app = app_name(principal.client_label)
        actor = access.get_actor(principal.actor_id) or {}
        who = actor.get("name") or principal.actor_name or ""
        cid = conversation_id(principal.client_id, body.get("conversation_ref"), body.get("client_request_id") or "")
        existing = db.connect().execute("SELECT project_id FROM conversations WHERE id=?", (cid,)).fetchone()
        if existing and existing["project_id"] != project_id:
            # the same outside conversation saved to a second project: that project gets its own chat
            cid = conversation_id(principal.client_id, f"{body.get('conversation_ref')}|{project_id}", body.get("client_request_id") or "")
        db.save_message(cid, "assistant", render(app, who, body, receipt), None, title=_title(app, body, receipt),
                        project_id=project_id,
                        meta={"kind": "external_sync", "client": app, "by": who, "intake_id": receipt.get("intake_id")})
        return cid
    except Exception:                                   # a courtesy on a committed save — never fail the save
        log.exception("could not mirror an external save into Chats (project %s)", project_id)
        return None


def backfill() -> int:
    """Give every past conversation save its chat, once. Runs inside the app at startup (never from a second
    process), is idempotent (a save whose intake already has a chat message is skipped), and rebuilds the body from
    what Neuro kept: the receipt's facts, the processed materials and the client's interpretations."""
    import json
    conn = db.connect()
    done = set()
    for r in conn.execute("SELECT meta FROM messages WHERE meta LIKE '%external_sync%'").fetchall():
        try:
            done.add(json.loads(r["meta"] or "{}").get("intake_id"))
        except ValueError:
            pass
    n = 0
    rows = conn.execute("SELECT i.*, c.label AS client_label FROM external_intakes i LEFT JOIN external_clients c ON c.id=i.client_id "
                        "WHERE i.receipt IS NOT NULL ORDER BY i.created_at").fetchall()
    for row in rows:
        if row["id"] in done:
            continue
        try:
            receipt = json.loads(row["receipt"] or "{}")
        except ValueError:
            continue
        if not receipt.get("saved"):
            continue
        mats, analysis = [], []
        for it in conn.execute("SELECT kind, payload FROM intake_items WHERE intake_id=? ORDER BY created_at", (row["id"],)).fetchall():
            try:
                p = json.loads(it["payload"] or "{}")
            except ValueError:
                continue
            if it["kind"] == "processed_material" and isinstance(p.get("material"), dict):
                mats.append(p["material"])
            elif it["kind"] == "interpretation" and p.get("text"):
                analysis.append({"text": p["text"]})
        principal = access.Principal(credential_id=row["credential_id"], actor_id=row["actor_id"], client_id=row["client_id"],
                                     client_label=row["client_label"] or "")
        body = {"conversation_ref": row["conversation_ref"], "client_request_id": row["client_request_id"],
                "materials": mats, "analysis": analysis}
        if record(principal, row["project_id"], body, receipt):
            n += 1
    return n
