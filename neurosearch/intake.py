"""P11 EA-4/EA-5 — External Intake Events and processed-material ingestion (EXTERNAL-AI-ACCESS-MISSION.md §21–§25,
§52–§55; plan §6).

One external turn can carry several distinct things — a screenshot, a PDF, an email, a decision, the assistant's own
reading of them. They stay DISTINCT (one `intake_items` row each) and are grouped under one durable, idempotent
`external_intakes` row carrying who/which client/which project/which request. The pattern is `source_captures`'
(db.create_or_get_capture_ingest_request): the event is not the source, one source can be reached by many events,
and an item and the job that processes it are created in one transaction.

Two ingestion paths, one knowledge architecture (§22, §53):
  Path B (processed): the client already read the material (vision, OCR, PDF text, transcription, page reading).
         Its extraction is stored as a normal Neuro source through `ingest.store_transcript` — the same chunking,
         dedupe and indexing as everything else — and NOTHING re-reads it: no OCR, no transcription, no refetch.
  Path A (raw): bytes Neuro must read itself go through the existing `ingest_file` job, unchanged.
A raw artifact attached to a processed item is kept as that item's retained original (§25), not read again.

The assistant's interpretation is stored as an interpretation item and never becomes a source or evidence (§23, §33).
Processing runs on the existing job queue (`intake_item` jobs); there is no second job system. Statuses are derived
from the jobs and written back when they change; an intake that never finalises, or an item that fails, surfaces as
`needs_review` — it never disappears (§52).
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

from . import access, db, ledger
from .access import AccessError, Authorization
from .config import settings
from .external_schemas import check

ORPHAN_S = 2 * 3600
PLATFORM = {"pdf": "document", "url": "web", "spreadsheet": "spreadsheet", "transcript": "media",
            "correspondence": "correspondence", "image": "screenshot", "text": "note"}
MIN_CLASS = {"correspondence": "correspondence"}          # a class the material type itself implies (raise-only)
ITEM_KINDS = ("raw_artifact", "processed_material", "user_state", "interpretation")


# ------------------------------------------------------------------ rows

def _row(intake_id: str) -> dict[str, Any] | None:
    r = db.connect().execute("SELECT * FROM external_intakes WHERE id=?", (intake_id,)).fetchone()
    return dict(r) if r else None


def _owned(auth: Authorization, intake_id: str | None) -> dict[str, Any]:
    """An intake is visible to the actor who created it, in its own project. Anything else does not exist here."""
    it = _row(intake_id) if intake_id else None
    if not it or it["project_id"] != auth.project_id or it["actor_id"] != auth.principal.actor_id:
        raise AccessError("not_found", "no such intake")
    return it


def _items(intake_id: str) -> list[dict[str, Any]]:
    return [dict(r) for r in db.connect().execute("SELECT * FROM intake_items WHERE intake_id=? ORDER BY created_at, id", (intake_id,)).fetchall()]


# ------------------------------------------------------------------ create

def create(auth: Authorization, args: dict[str, Any]) -> dict[str, Any]:
    req = str(args.get("client_request_id") or "")
    if len(req) < 8:
        raise AccessError("invalid", "client_request_id (≥ 8 chars, resent verbatim on retry) is required")
    p = auth.principal
    existing = db.connect().execute("SELECT * FROM external_intakes WHERE client_id=? AND client_request_id=?", (p.client_id, req)).fetchone()
    if existing:
        if existing["project_id"] != auth.project_id or existing["actor_id"] != p.actor_id:
            raise AccessError("invalid", "that client_request_id was already used for a different intake")
        return {**status(dict(existing)), "idempotent_replay": True}
    iid, t = db.new_id(), time.time()
    with db.tx() as conn:
        conn.execute("INSERT INTO external_intakes (id, project_id, actor_id, client_id, credential_id, client_request_id, status, "
                     "base_revision, conversation_ref, created_at, updated_at) VALUES (?,?,?,?,?,?, 'received', ?,?,?,?)",
                     (iid, auth.project_id, p.actor_id, p.client_id, p.credential_id, req,
                      None if args.get("base_revision") is None else str(args.get("base_revision")),
                      (str(args.get("conversation_ref")) if args.get("conversation_ref") else None), t, t))
    return status(_row(iid))  # type: ignore[arg-type]


def _check_open(it: dict[str, Any]) -> None:
    if it["finalized_at"] is not None:
        raise AccessError("conflict", "this intake is already finalized; start a new one")


def _item_replay(intake_id: str, item_request_id: str | None) -> dict[str, Any] | None:
    if not item_request_id:
        return None
    r = db.connect().execute("SELECT * FROM intake_items WHERE intake_id=? AND json_extract(payload, '$._item_request_id')=?",
                             (intake_id, item_request_id)).fetchone()
    return dict(r) if r else None


def _new_item(it: dict[str, Any], kind: str, *, job_payload: dict[str, Any] | None = None, job_kind: str = "intake_item",
              **cols: Any) -> dict[str, Any]:
    """Item + its processing job in ONE transaction (the capture-request idiom): a committed item always has its job."""
    iid, t = db.new_id(), time.time()
    job = None
    with db.batch():
        if job_payload is not None:
            job = db.create_job(job_kind, {**job_payload, "item_id": iid, "project_id": it["project_id"]})
        cols = {**cols, "id": iid, "intake_id": it["id"], "kind": kind, "created_at": t, "updated_at": t,
                "ingest_job_id": job["id"] if job else None,
                "status": "queued" if job else "ready"}
        names = ", ".join(cols)
        with db.tx() as conn:
            conn.execute(f"INSERT INTO intake_items ({names}) VALUES ({', '.join('?' * len(cols))})", tuple(cols.values()))
            conn.execute("UPDATE external_intakes SET status=CASE WHEN status='received' THEN 'routing' ELSE status END, updated_at=? WHERE id=?", (t, it["id"]))
    return dict(db.connect().execute("SELECT * FROM intake_items WHERE id=?", (iid,)).fetchone())


# ------------------------------------------------------------------ Path B: processed material

def add_processed(auth: Authorization, args: dict[str, Any]) -> dict[str, Any]:
    it = _owned(auth, args.get("intake_id"))
    _check_open(it)
    material = check("external.material.v1", args.get("material"))
    replay = _item_replay(it["id"], args.get("item_request_id"))
    if replay:
        return {"item": _item_out(replay), "idempotent_replay": True}
    payload = {"material": material, "_item_request_id": args.get("item_request_id")}
    item = _new_item(it, "processed_material", job_payload={"mode": "processed"},
                     material_type=material["material_type"], producer=material["producer"][:200],
                     extraction_method=material["extraction_method"], confidence=material.get("confidence"),
                     payload=json.dumps(payload))
    return {"item": _item_out(item)}


def _page_of(locator: str | None, default: int) -> float:
    m = re.search(r"(\d+)", locator or "")
    return float(m.group(1)) if m else float(default)


def _segments(material: dict[str, Any]) -> list[dict[str, Any]]:
    mt = material["material_type"]
    segs: list[dict[str, Any]] = []
    if mt == "correspondence" and material.get("correspondence"):
        c = material["correspondence"]
        head = " · ".join(x for x in (f"From: {c.get('from')}" if c.get("from") else "", f"To: {', '.join(c.get('to') or [])}" if c.get("to") else "",
                                       f"Date: {c.get('date')}" if c.get("date") else "", f"Subject: {c.get('subject')}" if c.get("subject") else "") if x)
        if head:
            segs.append({"start": 0.0, "end": 0.0, "text": head})
    for i, u in enumerate(material["units"], start=1):
        text = u["text"].strip()
        if u.get("speaker"):
            text = f"{u['speaker']}: {text}"
        if mt == "transcript":
            start = float(u.get("start") or 0.0)
            end = float(u.get("end") if u.get("end") is not None else start)
        elif mt == "pdf":
            start = end = _page_of(u.get("locator"), i)
        else:
            start = end = float(i)
        segs.append({"start": start, "end": end, "text": text})
    if mt == "spreadsheet" and material.get("table"):
        tb = material["table"]
        cols = tb.get("columns") or []
        for r_i, row in enumerate(tb.get("rows") or [], start=1):
            cells = "; ".join(f"{cols[j] if j < len(cols) else f'col{j + 1}'}: {v}" for j, v in enumerate(row) if v not in (None, ""))
            if cells:
                segs.append({"start": float(len(segs) + 1), "end": float(len(segs) + 1), "text": f"{tb.get('sheet') or 'sheet'} row {r_i}: {cells}"})
    return segs


def _store_processed(item: dict[str, Any], it: dict[str, Any]) -> dict[str, Any]:
    from . import ingest, media
    material = json.loads(item["payload"])["material"]
    segs = _segments(material)
    fp = "sha256:" + hashlib.sha256(json.dumps([material["material_type"], material["title"], [s["text"] for s in segs]]).encode()).hexdigest()
    url = material.get("canonical_url") or ""
    platform = PLATFORM[material["material_type"]]
    if material["material_type"] == "url" and url.startswith("http"):
        url = media.canonical_url(url)
        ext_id = re.sub(r"^https?://(www\.)?", "", url).rstrip("/")
    else:
        ext_id = f"x:{fp[7:23]}"
        url = url or f"external://{ext_id}"
    payload = {"platform": platform, "external_id": ext_id, "url": url, "title": material["title"][:500],
               "channel": (material.get("correspondence") or {}).get("from") or material["producer"],
               "transcript_kind": f"external:{material['extraction_method']}", "language": material.get("language"),
               "published_at": (material.get("correspondence") or {}).get("date"),
               "fingerprint": fp, "segments": segs}
    res = ingest.store_transcript(payload, tags=["external"], project_id=it["project_id"])
    sid = res["source_id"]
    db.set_acquisition_provenance(sid, "external_processed")
    declared = material.get("client_declared_class")
    floor = MIN_CLASS.get(material["material_type"])
    wanted = access.merge_declared(floor, declared) if (floor or declared) else None
    if wanted:
        access.raise_source_class(sid, wanted)
    return {"source_id": sid, "already_ingested": bool(res.get("already_ingested")), "segments": len(segs)}


# ------------------------------------------------------------------ Path A: raw artifacts (§55)

def attach(auth: Authorization, args: dict[str, Any], *, upload: tuple[str, bytes, str | None] | None = None) -> dict[str, Any]:
    """`upload` = (filename, bytes, content_type) for the multipart transport; otherwise `artifact_ref` must be a
    resolvable reference (signed_url through safe_fetch). A raw artifact attached to a processed item (`item_id`) is
    retained as that item's original and NOT read again (§25, §53)."""
    it = _owned(auth, args.get("intake_id"))
    _check_open(it)
    ref = check("external.artifact_ref.v1", args.get("artifact_ref") or {"kind": "multipart"})
    replay = _item_replay(it["id"], args.get("item_request_id"))
    if replay:
        return {"item": _item_out(replay), "idempotent_replay": True}
    declared = args.get("client_declared_class")
    if declared is not None:
        access._check_class_list([declared])
    target = None
    if args.get("item_id"):
        target = db.connect().execute("SELECT * FROM intake_items WHERE id=? AND intake_id=?", (args["item_id"], it["id"])).fetchone()
        if not target:
            raise AccessError("not_found", "no such item in this intake")
    if upload is None and ref["kind"] == "signed_url":
        # Kyle's review (2026-09-22): a client's file reference (e.g. a temporary download URL) is NOT the original.
        # It is fetched NOW, while it is still valid — through safe_fetch — validated, hashed, deduped and kept in
        # Neuro's own storage. A reference that cannot be materialised becomes a failed item (needs_review); Neuro
        # never claims an original it does not hold.
        if not ref.get("url"):
            raise AccessError("invalid", "a signed_url artifact_ref needs url")
        name = ref.get("filename") or "artifact"
        try:
            data, ctype, final_url = _fetch_now(ref)
            name = ref.get("filename") or Path(final_url.split("?")[0]).name or "artifact"
            _validate(name, data, ctype)
        except AccessError as e:
            item = _new_item(it, "raw_artifact", artifact_ref=json.dumps({k: v for k, v in ref.items() if k != "url"}),
                             content_type=ref.get("content_type"), payload=json.dumps({"_item_request_id": args.get("item_request_id"),
                             "declared": declared, "retain_for": target["id"] if target else None, "name": name}))
            with db.tx() as conn:
                conn.execute("UPDATE intake_items SET status='failed', error=?, updated_at=? WHERE id=?", (e.message[:500], time.time(), item["id"]))
            item = {**item, "status": "failed", "error": e.message[:500]}
            return {"item": _item_out(item)}
        upload = (name, data, ctype)
        ref = {k: v for k, v in ref.items() if k != "url"}         # the temporary URL is not kept; the bytes are
    elif upload is None:
        raise AccessError("capability_missing", f"artifact_ref kind {ref['kind']!r} is not supported by this server yet; "
                                                "use multipart upload or a signed_url")
    name, data, ctype = upload
    _validate(name, data, ctype)
    path, digest = _save(name, data)
    if ref.get("sha256") and ref["sha256"] != digest:
        raise AccessError("invalid", "the artifact does not match the sha256 the client declared")
    payload = {"_item_request_id": args.get("item_request_id"), "declared": declared, "name": name,
               "retain_for": target["id"] if target else None}
    ref_kept = json.dumps({**ref, "filename": name}) if ref.get("kind") != "multipart" else json.dumps({"kind": "multipart", "filename": name})
    if target is not None:                     # retained original of processed material: kept, never re-read
        item = _new_item(it, "raw_artifact", artifact_ref=ref_kept,
                         sha256=digest, bytes=len(data), content_type=ctype, payload=json.dumps({**payload, "path": str(path)}))
        return {"item": _item_out(item), "retained_as_original_of": target["id"]}
    item = _new_item(it, "raw_artifact", job_payload={"mode": "raw"}, artifact_ref=ref_kept,
                     sha256=digest, bytes=len(data), content_type=ctype, payload=json.dumps({**payload, "path": str(path)}))
    return {"item": _item_out(item)}


MAX_UPLOAD = 60 * 1024 * 1024


def _save(name: str, data: bytes) -> tuple[Path, str]:
    if len(data) > MAX_UPLOAD:
        raise AccessError("invalid", f"artifact is larger than {MAX_UPLOAD // (1024 * 1024)} MB")
    if not data:
        raise AccessError("invalid", "empty artifact")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(name or "artifact").name)[-120:] or "artifact"
    d = settings.media_dir
    d.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(data).hexdigest()
    existing = next(iter(sorted(d.glob(f"intake_{digest[:12]}_*"))), None)     # identical bytes are kept once
    if existing is not None and hashlib.sha256(existing.read_bytes()).hexdigest() == digest:
        return existing, digest
    path = d / f"intake_{digest[:12]}_{safe}"
    path.write_bytes(data)
    return path, digest


# What an external client may hand over as an original (sniffed from the bytes, never trusted from a declared type).
_MAGIC = ((b"%PDF-", "pdf"), (b"\x89PNG\r\n\x1a\n", "png"), (b"\xff\xd8\xff", "jpeg"), (b"GIF8", "gif"), (b"PK\x03\x04", "zip-office"),
          (b"\xd0\xcf\x11\xe0", "ole-office"), (b"ID3", "mp3"), (b"OggS", "ogg"), (b"fLaC", "flac"), (b"\x1aE\xdf\xa3", "webm/mkv"))
_REFUSED = ((b"MZ", "windows executable"), (b"\x7fELF", "executable"), (b"\xca\xfe\xba\xbe", "executable"),
            (b"\xcf\xfa\xed\xfe", "executable"), (b"#!", "script"))


def _validate(name: str, data: bytes, ctype: str | None) -> str:
    if not data:
        raise AccessError("invalid", "empty artifact")
    if len(data) > MAX_UPLOAD:
        raise AccessError("invalid", f"artifact is larger than {MAX_UPLOAD // (1024 * 1024)} MB")
    head = data[:16]
    for sig, what in _REFUSED:
        if head.startswith(sig):
            raise AccessError("invalid", f"refused: the file is a {what}")
    for sig, what in _MAGIC:
        if head.startswith(sig):
            return what
    if head[4:8] == b"ftyp":
        return "mp4/m4a/heic"
    if head.startswith(b"RIFF") and data[8:12] in (b"WAVE", b"WEBP", b"AVI "):
        return data[8:12].decode().strip().lower()
    try:
        data[:65536].decode("utf-8")
        return "text"
    except UnicodeDecodeError:
        raise AccessError("invalid", "unrecognised file type (not a document, image, spreadsheet, audio/video or text file)")


def _fetch_now(ref: dict[str, Any]) -> tuple[bytes, str, str]:
    from . import safe_fetch
    try:
        res = safe_fetch.safe_fetch(ref["url"], content_class="document")
    except safe_fetch.FetchBlocked as e:
        raise AccessError("invalid", f"could not fetch the file: {e}")
    except Exception as e:  # noqa: BLE001 — an expired link or a network failure is a failed item, never a crash
        raise AccessError("invalid", f"could not fetch the file (the link may have expired): {type(e).__name__}")
    if res.status >= 400:
        raise AccessError("invalid", f"could not fetch the file: HTTP {res.status}")
    return res.body, res.content_type, res.url


def _fetch_raw(item: dict[str, Any]) -> Path:
    from . import safe_fetch
    ref = json.loads(item["artifact_ref"])
    res = safe_fetch.safe_fetch(ref["url"], content_class="document")
    name = ref.get("filename") or Path(res.url.split("?")[0]).name or "artifact"
    path, digest = _save(name, res.body)
    if ref.get("sha256") and ref["sha256"] != digest:
        raise RuntimeError("the fetched artifact does not match the sha256 the client declared")
    with db.tx() as conn:
        conn.execute("UPDATE intake_items SET sha256=?, bytes=?, content_type=COALESCE(content_type, ?), updated_at=? WHERE id=?",
                     (digest, len(res.body), res.content_type, time.time(), item["id"]))
    return path


# ------------------------------------------------------------------ the job (runs on the existing queue)

def process_item(item_id: str, progress: Any = None) -> dict[str, Any]:
    r = db.connect().execute("SELECT * FROM intake_items WHERE id=?", (item_id,)).fetchone()
    if not r:
        return {"skipped": "intake item no longer exists"}
    item = dict(r)
    it = _row(item["intake_id"])
    if not it:
        return {"skipped": "intake no longer exists"}
    # the contributor's own act, carried out by the queue: attributed to them and their client (Kyle's ruling 2)
    with ledger.acting(it["actor_id"], client_id=it["client_id"], intake_id=it["id"], request_id=it["client_request_id"]):
        payload = json.loads(item["payload"] or "{}")
        if item["kind"] == "processed_material":
            out = _store_processed(item, it)
        elif item["kind"] == "raw_artifact":
            from . import ingest
            path = Path(payload["path"]) if payload.get("path") else _fetch_raw(item)
            if payload.get("retain_for"):
                out = {"retained": str(path.name)}
            else:
                res = ingest.ingest_local_file(path, title=None, tags=["external"], project_id=it["project_id"], original_name=payload.get("name") or path.name)
                out = {"source_id": res.get("source_id")}
                _apply_raw_class(out.get("source_id"), payload.get("declared"))
        else:
            return {"skipped": f"nothing to process for {item['kind']}"}
    with db.tx() as conn:
        conn.execute("UPDATE intake_items SET source_id=COALESCE(?, source_id), status='ready', error=NULL, updated_at=? WHERE id=?",
                     (out.get("source_id"), time.time(), item_id))
    return out


def _apply_raw_class(source_id: str | None, declared: str | None) -> None:
    if not source_id:
        return
    db.set_acquisition_provenance(source_id, "user_private")      # bytes a person handed over: private unless declared
    if declared:
        access.raise_source_class(source_id, declared)


# ------------------------------------------------------------------ finalize + status

def finalize(auth: Authorization, args: dict[str, Any], apply_state: Any = None) -> dict[str, Any]:
    it = _owned(auth, args.get("intake_id"))
    if it["finalized_at"] is not None:
        return {**status(it), "idempotent_replay": True}
    for interp in args.get("interpretations") or []:
        check("external.interpretation.v1", interp)
    state_result = None
    if args.get("user_state"):
        state_result = apply_state(auth, {"project_id": auth.project_id, "changes": args["user_state"],
                                          "base_revision": args.get("base_revision"), "intake_id": it["id"]})
    t = time.time()
    with db.tx() as conn:
        for interp in args.get("interpretations") or []:
            conn.execute("INSERT INTO intake_items (id, intake_id, kind, producer, payload, status, created_at, updated_at) "
                         "VALUES (?,?, 'interpretation', ?, ?, 'ready', ?, ?)",
                         (db.new_id(), it["id"], (interp.get("producer") or "")[:200] or None,
                          json.dumps({"text": interp["text"], "about_item_id": interp.get("about_item_id"), "is_evidence": False}), t, t))
        for f in (state_result or {}).get("applied") or []:
            conn.execute("INSERT INTO intake_items (id, intake_id, kind, fact_id, payload, status, created_at, updated_at) "
                         "VALUES (?,?, 'user_state', ?, ?, 'ready', ?, ?)", (db.new_id(), it["id"], f.get("fact_id"), json.dumps({"op": f.get("op")}), t, t))
        conn.execute("UPDATE external_intakes SET finalized_at=?, status=CASE WHEN status IN ('received','routing') THEN 'queued' ELSE status END, "
                     "updated_at=? WHERE id=?", (t, t, it["id"]))
        n = conn.execute("SELECT COUNT(*) FROM intake_items WHERE intake_id=?", (it["id"],)).fetchone()[0]
        ledger.record(conn, it["project_id"], event_type="intake_finalized", object_type="intake", object_id=it["id"], before=None,
                      after={"items": n}, floor={"standard"})
    out = status(_row(it["id"]))  # type: ignore[arg-type]
    if state_result is not None:
        out["state"] = state_result
    return out


def _link_retained(items: list[dict[str, Any]]) -> list[tuple[str, str]]:
    by_id = {i["id"]: i for i in items}
    out = []
    for i in items:
        if i["kind"] != "raw_artifact" or i.get("source_id"):
            continue
        tgt = by_id.get((json.loads(i["payload"] or "{}") or {}).get("retain_for") or "")
        if tgt and tgt.get("source_id"):
            out.append((tgt["source_id"], i["id"]))
            i["source_id"] = tgt["source_id"]
    return out


def _item_status(item: dict[str, Any]) -> tuple[str, str | None]:
    if not item.get("ingest_job_id"):
        return item["status"], item.get("error")
    j = db.get_job(item["ingest_job_id"])
    if not j:
        return "failed", "its processing job is gone"
    st = j["status"]
    if st == "done":
        return ("ready" if item["status"] == "ready" else "failed"), (None if item["status"] == "ready" else "finished without a result")
    if st in ("failed", "cancelled"):
        return "failed", (j.get("error") or j.get("message") or st)[:500]
    if st == "running":
        return "processing", None
    return "queued", None


def status(it: dict[str, Any]) -> dict[str, Any]:
    items = _items(it["id"])
    changed = []
    for item in items:
        st, err = _item_status(item)
        if (st, err) != (item["status"], item.get("error")):
            changed.append((st, err, item.get("source_id"), item["id"]))
            item["status"], item["error"] = st, err
    links = _link_retained(items)
    if links:
        with db.tx() as conn:
            conn.executemany("UPDATE intake_items SET source_id=? WHERE id=? AND source_id IS NULL", links)
    sts = [i["status"] for i in items]
    reason = None
    if any(s == "failed" for s in sts):
        new, reason = "needs_review", "an item could not be processed"
    elif it["finalized_at"] is None and time.time() - it["created_at"] > ORPHAN_S:
        new, reason = "needs_review", "never finalized by the client"
    elif it["finalized_at"] is not None and all(s == "ready" for s in sts):
        new = "ready"
    elif any(s in ("processing",) for s in sts):
        new = "processing"
    elif any(s == "queued" for s in sts):
        new = "queued" if it["finalized_at"] is not None or it["status"] != "received" else it["status"]
    else:
        new = it["status"] if it["finalized_at"] is None else "ready"
    if changed or new != it["status"]:
        t = time.time()
        with db.tx() as conn:
            for st, err, sid, iid in changed:
                conn.execute("UPDATE intake_items SET status=?, error=?, source_id=COALESCE(?, source_id), updated_at=? WHERE id=?", (st, err, sid, t, iid))
            if new != it["status"]:
                conn.execute("UPDATE external_intakes SET status=?, needs_review_reason=?, updated_at=? WHERE id=?", (new, reason, t, it["id"]))
                if new == "needs_review":
                    ledger.record(conn, it["project_id"], event_type="intake_needs_review", object_type="intake", object_id=it["id"],
                                  before={"status": it["status"]}, after={"status": new, "reason": reason}, floor={"standard"})
        it = {**it, "status": new, "needs_review_reason": reason}
    return {"intake_id": it["id"], "status": it["status"], "needs_review_reason": it.get("needs_review_reason"),
            "finalized": it["finalized_at"] is not None, "items": [_item_out(i) for i in items]}


def get_status(auth: Authorization, args: dict[str, Any]) -> dict[str, Any]:
    return status(_owned(auth, args.get("intake_id")))


def _item_out(i: dict[str, Any]) -> dict[str, Any]:
    out = {"item_id": i["id"], "kind": i["kind"], "status": i["status"], "material_type": i.get("material_type"),
           "source_id": i.get("source_id"), "fact_id": i.get("fact_id"), "error": i.get("error")}
    if i["kind"] == "raw_artifact":
        out.update({"sha256": i.get("sha256"), "bytes": i.get("bytes")})
    return out


def inbox(project_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """The Project Inbox is a VIEW over intakes (§8, §52), for the local owner: newest first, needs_review on top."""
    rows = [dict(r) for r in db.connect().execute(
        "SELECT i.*, a.name AS actor_name, c.label AS client_label FROM external_intakes i "
        "LEFT JOIN external_actors a ON a.id=i.actor_id LEFT JOIN external_clients c ON c.id=i.client_id "
        "WHERE i.project_id=? ORDER BY (i.status='needs_review') DESC, i.created_at DESC LIMIT ?", (project_id, limit)).fetchall()]
    out = []
    for r in rows:
        s = status(r)
        out.append({**s, "by": r["actor_name"], "via": r["client_label"], "created_at": r["created_at"],
                    "interpretations": [json.loads(i["payload"])["text"] for i in _items(r["id"]) if i["kind"] == "interpretation"]})
    return out
