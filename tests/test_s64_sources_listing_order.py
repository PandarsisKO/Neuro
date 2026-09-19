"""S64 — a capped source listing keeps what was added LAST (0.63.93). (Sorts after test_core.)

Kyle, 2026-09-18, after importing a course: "the sorting of our sources page makes it very difficult to find the
most recent content". The page's default sort is now "recently added" (client side), but the server list it reads
is capped (2,000 rows for a project, 500 for the library picker) and was ordered by PUBLISH date — which a course
lesson or a document does not carry — so past the cap the rows just added would have been the first ones cut,
before the page could sort anything. `db.list_sources` orders by `created_at` now.
"""
from __future__ import annotations

import time

from neurosearch import db

H = {"Authorization": "Bearer t0k"}


def test_a_capped_listing_keeps_the_most_recently_added_row_even_without_a_publish_date(client):
    p = client.post("/api/projects", headers=H, json={"name": "Listing order", "brief": "b"}).json()
    t0 = time.time()
    old_video = db.upsert_source(platform="youtube", external_id="s64old", url="https://www.youtube.com/watch?v=s64old00000",
                                 title="Old but published yesterday", status="ready", published_at="2026-09-17")
    new_doc = db.upsert_source(platform="document", external_id="s64doc", url="https://drive.google.com/file/d/S64DOC/view",
                               title="Bonus worksheet added just now", status="ready", published_at=None)
    with db.tx() as conn:   # upsert stamps created_at itself; the order under test is "added an hour apart"
        conn.execute("UPDATE sources SET created_at=? WHERE id=?", (t0 - 3600, old_video["id"]))
        conn.execute("UPDATE sources SET created_at=? WHERE id=?", (t0, new_doc["id"]))
    ids = {old_video["id"], new_doc["id"]}
    rows = db.list_sources(limit=1, ids=ids)
    assert [r["id"] for r in rows] == [new_doc["id"]], "the row added last survives a cap of one, publish date or not"
    rows = db.list_sources(limit=10, ids=ids)
    assert [r["id"] for r in rows] == [new_doc["id"], old_video["id"]]
    # the API the page reads returns the same order for the project
    db.add_project_sources(p["id"], list(ids))
    got = [r["id"] for r in client.get(f"/api/sources?project_id={p['id']}&limit=1", headers=H).json()]
    assert got == [new_doc["id"]]


def test_clear_failed_can_be_narrowed_to_members_only(client):
    """2026-09-18: 22 of Kyle's 41 failed sources were members-only YouTube videos (no retry can help); the other
    19 were timeouts and not-founds he may still retry. `error_classes` clears exactly the hopeless class."""
    p = client.post("/api/projects", headers=H, json={"name": "Members only", "brief": "b"}).json()
    mo = db.upsert_source(platform="youtube", external_id="s64mo1", url="https://www.youtube.com/watch?v=s64mo100000", title="Lesson 5 | Members",
                          status="failed", error="Join this channel to get access to members-only content", error_class="members_only")
    to = db.upsert_source(platform="youtube", external_id="s64to1", url="https://www.youtube.com/watch?v=s64to100000", title="Timed out",
                          status="failed", error="timed out", error_class="timed_out")
    db.add_project_sources(p["id"], [mo["id"], to["id"]])
    r = client.post("/api/sources/clear-failed-in-project", headers=H, json={"project_id": p["id"], "error_classes": ["members_only"]}).json()
    assert r["cleared"] == 1 and r["deleted"] == 1
    left = {s["id"] for s in client.get(f"/api/sources?project_id={p['id']}&status=failed", headers=H).json()}
    assert left == {to["id"]}, "the retryable failure is untouched"
    assert db.get_source(mo["id"]) is None
