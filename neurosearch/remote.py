"""Legacy remote-ingest compatibility path.

The supported product is local and single-user. Keep this module until command usage has been measured and any
dependent workflow identified; do not present it as a supported cloud deployment architecture.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

import httpx

from . import media
from .ingest import extract_transcript

log = logging.getLogger(__name__)


class RemoteClient:
    def __init__(self, base_url: str, token: str | None) -> None:
        self.base = base_url.rstrip("/")
        self.http = httpx.Client(base_url=self.base, timeout=120,
                                 headers={"Authorization": f"Bearer {token}"} if token else {})

    def project_id(self, name_or_id: str | None) -> str | None:
        if not name_or_id:
            return None
        for p in self.http.get("/api/projects").raise_for_status().json():
            if p["id"] == name_or_id or p["name"].lower() == name_or_id.lower():
                return p["id"]
        raise RuntimeError(f"remote has no project '{name_or_id}'")

    def existing_ids(self, platform: str) -> set[str]:
        rows = self.http.get("/api/sources", params={"status": "ready", "limit": 100000}).raise_for_status().json()
        return {r["external_id"] for r in rows if r["platform"] == platform}

    def import_payload(self, payload: dict[str, Any], tags: list[str], project_id: str | None,
                       collection: dict[str, Any] | None) -> dict[str, Any]:
        body = {"payload": payload, "tags": tags, "project_id": project_id, "collection": collection}
        r = self.http.post("/api/import", json=body)
        if r.status_code >= 400:
            raise RuntimeError(f"remote import failed: {r.text[:300]}")
        return r.json()


def ingest_remote(urls: list[str], base_url: str, token: str | None, tags: list[str] | None = None,
                  project: str | None = None, force: bool = False,
                  echo: Callable[[str], None] = print) -> dict[str, int]:
    client = RemoteClient(base_url, token)
    pid = client.project_id(project)
    tags = tags or []
    done = failed = skipped = 0
    for url in urls:
        kind = media.classify_url(url)
        if kind in ("playlist", "channel"):
            echo(f"listing {kind} {url} …")
            info, entries = media.enumerate_entries(url)
            collection = {"kind": kind, "external_id": info.get("id"), "url": info.get("url") or url, "title": info.get("title")}
            have = set() if force else client.existing_ids("youtube")
            items = [(e["url"], "youtube", e["id"]) for e in entries]
            echo(f"  {len(items)} videos, {sum(1 for _, _, i in items if i in have)} already on server")
        else:
            collection = None
            have = set()
            platform = "youtube" if kind == "video" else ("instagram" if kind == "instagram" else "media")
            items = [(url, platform, None)]
        for u, platform, ext in items:
            if ext and ext in have:
                skipped += 1
                continue
            try:
                payload = extract_transcript(u, platform, progress=lambda p, m: None)
                res = client.import_payload(payload, tags, pid, collection)
                done += 1
                echo(f"  ✓ {res.get('title')} ({res.get('chunks')} chunks, {res.get('transcript')})")
            except Exception as e:  # noqa: BLE001
                failed += 1
                echo(f"  ✗ {u}: {e}")
    echo(f"done: {done} imported, {skipped} skipped, {failed} failed")
    return {"imported": done, "skipped": skipped, "failed": failed}
