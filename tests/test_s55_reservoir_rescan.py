"""S55 — CR3/CR4 (PRODUCT-INTELLIGENCE-MISSION.md §13, EXECUTION-LADDER.md): known-reservoir rescan and
change detection. MONITOR only -- these gates prove detection/reconciliation, never acquisition: no test here
asserts a `sources` row is created, and `enumerate` is always a fake (zero network, zero provider/model calls).

The cross-project gate (`test_a_second_project_reconciles_into_its_own_candidate_index_without_re_seeing_a_dup`)
is the one Kyle's overnight-mission corrections required: reservoir-scan state must be project-scoped, not a
bare per-collection key, or a second project attaching to an already-scanned, unchanged reservoir would never
receive the candidates a first project already discovered.
"""
from __future__ import annotations

import pytest

from neurosearch import candidates, db, reservoir


def _entries(n: int, *, start: int = 1, prefix: str = "vid") -> list[dict]:
    return [{"id": f"{prefix}{i}", "url": f"https://www.youtube.com/watch?v={prefix}{i}", "title": f"Video {i}",
             "duration": 100 + i, "view_count": 10 * i} for i in range(start, start + n)]


def _fake_enumerate(entries: list[dict]):
    def enumerate_fn(url: str):
        return {"id": "UCabc", "title": "Some Channel", "url": url}, entries
    return enumerate_fn


@pytest.fixture()
def project_with_collection():
    db.init_db()
    pid = db.create_project("S55 project", brief="reservoir rescan gate")["id"]
    col = db.upsert_collection("channel", "UCabc", "https://www.youtube.com/channel/UCabc", "Some Channel")
    db.add_project_collections(pid, [col["id"]])
    return pid, col["id"]


def test_first_rescan_finds_new_and_second_identical_rescan_finds_nothing(project_with_collection):
    pid, cid = project_with_collection
    entries = _entries(5)

    r1 = reservoir.rescan(pid, cid, enumerate=_fake_enumerate(entries))
    assert r1["changed"] is True and r1["new"] == 5 and r1["total"] == 5
    assert len(r1["candidate_ids"]) == 5

    r2 = reservoir.rescan(pid, cid, enumerate=_fake_enumerate(entries))
    assert r2["changed"] is False and r2["new"] == 0
    assert r2["candidate_ids"] == []   # true no-op: no remember() call, no writes


def test_a_sixth_entry_appearing_is_the_only_new_one(project_with_collection):
    pid, cid = project_with_collection
    reservoir.rescan(pid, cid, enumerate=_fake_enumerate(_entries(5)))
    r = reservoir.rescan(pid, cid, enumerate=_fake_enumerate(_entries(6)))
    assert r["changed"] is True and r["new"] == 1 and r["total"] == 6


def test_a_dismissed_candidate_stays_dismissed_across_rescans(project_with_collection):
    pid, cid = project_with_collection
    entries = _entries(3)
    r1 = reservoir.rescan(pid, cid, enumerate=_fake_enumerate(entries))
    cand_id = r1["candidate_ids"][0]
    candidates.mark(pid, [cand_id], "user_dismissed", reason="not relevant")

    row = db.connect().execute("SELECT state FROM candidate_projects WHERE candidate_id=? AND project_id=?",
                               (cand_id, pid)).fetchone()
    assert row["state"] == "user_dismissed"

    reservoir.rescan(pid, cid, enumerate=_fake_enumerate(_entries(4)))   # a change (4th entry) triggers a real pass
    row2 = db.connect().execute("SELECT state FROM candidate_projects WHERE candidate_id=? AND project_id=?",
                                (cand_id, pid)).fetchone()
    assert row2["state"] == "user_dismissed", "remember() must never touch an existing candidate_projects state"


def test_already_in_library_entries_get_their_source_id_resolved(project_with_collection):
    pid, cid = project_with_collection
    src = db.upsert_source(platform="youtube", external_id="vid1", url="https://www.youtube.com/watch?v=vid1", title="Video 1")
    r = reservoir.rescan(pid, cid, enumerate=_fake_enumerate(_entries(2)))
    assert r["new"] == 2
    row = db.connect().execute("SELECT source_id FROM candidates WHERE platform='youtube' AND external_id='vid1'").fetchone()
    assert row["source_id"] == src["id"]


def test_origin_carries_the_collection_id(project_with_collection):
    pid, cid = project_with_collection
    r = reservoir.rescan(pid, cid, enumerate=_fake_enumerate(_entries(1)))
    # The candidate is global; its discovery origin belongs to this project.
    # Another test/project may already know vid1 through ordinary exploration.
    row = db.connect().execute("SELECT origin FROM candidate_projects WHERE candidate_id=? AND project_id=?",
                               (r["candidate_ids"][0], pid)).fetchone()
    import json
    origin = json.loads(row["origin"])
    assert origin["kind"] == "reservoir_rescan" and origin["collection_id"] == cid


def test_rescan_preserves_another_projects_distinct_discovery_origin(project_with_collection):
    """One shared candidate must retain both projects' independent provenance."""
    import json

    pid, collection_id = project_with_collection
    other_pid = db.create_project("S55 earlier exploration", brief="other project")["id"]
    entries = _entries(1, prefix="s55-origin-shared")
    entry = entries[0]
    earlier_origin = {"kind": "exploration", "query": "earlier independent search"}
    candidate_id = candidates.remember(
        [{"external_id": entry["id"], "url": entry["url"], "title": entry["title"]}],
        "youtube", other_pid, earlier_origin,
    )[0]

    scanned = reservoir.rescan(pid, collection_id, enumerate=_fake_enumerate(entries))
    assert scanned["candidate_ids"] == [candidate_id]
    origins = {
        row["project_id"]: json.loads(row["origin"])
        for row in db.connect().execute(
            "SELECT project_id, origin FROM candidate_projects "
            "WHERE candidate_id=? AND project_id IN (?,?)", (candidate_id, other_pid, pid),
        )
    }
    assert origins[other_pid] == earlier_origin
    assert origins[pid]["kind"] == "reservoir_rescan"
    assert origins[pid]["collection_id"] == collection_id


def test_zero_provider_calls_and_zero_jobs_enqueued(project_with_collection, monkeypatch):
    pid, cid = project_with_collection
    before = db.connect().execute("SELECT COUNT(*) n FROM jobs").fetchone()["n"]
    before_inv = db.connect().execute("SELECT COUNT(*) n FROM invocations").fetchone()["n"]
    reservoir.rescan(pid, cid, enumerate=_fake_enumerate(_entries(3)))
    after = db.connect().execute("SELECT COUNT(*) n FROM jobs").fetchone()["n"]
    after_inv = db.connect().execute("SELECT COUNT(*) n FROM invocations").fetchone()["n"]
    assert after == before and after_inv == before_inv


def test_enumerate_is_called_exactly_once_per_rescan(project_with_collection):
    pid, cid = project_with_collection
    calls = []
    def counting_enumerate(url):
        calls.append(url)
        return {"id": "UCabc", "title": "Some Channel", "url": url}, _entries(2)
    reservoir.rescan(pid, cid, enumerate=counting_enumerate)
    assert len(calls) == 1


def test_a_second_project_reconciles_into_its_own_candidate_index_without_re_seeing_a_dup():
    """Kyle's required cross-project regression: A and B share a reservoir. A scans first. The reservoir stays
    completely unchanged. B scans afterward and must still receive the candidates. A must not get duplicates.
    Neither project's candidate disposition leaks into the other."""
    db.init_db()
    pid_a = db.create_project("S55 project A", brief="a")["id"]
    pid_b = db.create_project("S55 project B", brief="b")["id"]
    col = db.upsert_collection("channel", "UCshared", "https://www.youtube.com/channel/UCshared", "Shared Channel")
    db.add_project_collections(pid_a, [col["id"]])
    db.add_project_collections(pid_b, [col["id"]])
    entries = _entries(4, prefix="crossproj")

    ra1 = reservoir.rescan(pid_a, col["id"], enumerate=_fake_enumerate(entries))
    assert ra1["changed"] is True and ra1["new"] == 4

    # A rescans again: nothing changed remotely AND A is already reconciled -> true no-op
    ra2 = reservoir.rescan(pid_a, col["id"], enumerate=_fake_enumerate(entries))
    assert ra2["changed"] is False and ra2["new"] == 0

    # B's FIRST rescan of the SAME, remotely-unchanged reservoir must still reconcile all 4 into B's own index --
    # a collection-only (non-project-scoped) fingerprint would have wrongly reported "unchanged" here and skipped it
    rb1 = reservoir.rescan(pid_b, col["id"], enumerate=_fake_enumerate(entries))
    assert rb1["changed"] is True and rb1["new"] == 4, \
        "a second project attaching to an unchanged shared reservoir must still receive its candidates"

    # global candidate rows are NOT duplicated -- same 4 (platform, external_id) rows regardless of who scanned
    n_candidates = db.connect().execute(
        "SELECT COUNT(*) n FROM candidates WHERE platform='youtube' AND external_id LIKE 'crossproj%'").fetchone()["n"]
    assert n_candidates == 4, "no duplicate global candidates from B's independent reconciliation"

    # each project has its OWN candidate_projects rows -- 4 for A, 4 for B, none shared/leaked
    n_a = db.connect().execute("SELECT COUNT(*) n FROM candidate_projects WHERE project_id=?", (pid_a,)).fetchone()["n"]
    n_b = db.connect().execute("SELECT COUNT(*) n FROM candidate_projects WHERE project_id=?", (pid_b,)).fetchone()["n"]
    assert n_a == 4 and n_b == 4

    # disposition does not leak: dismissing in B must not affect A's row for the same global candidate
    b_cand_id = rb1["candidate_ids"][0]
    candidates.mark(pid_b, [b_cand_id], "user_dismissed")
    a_state = db.connect().execute("SELECT state FROM candidate_projects WHERE candidate_id=? AND project_id=?",
                                   (b_cand_id, pid_a)).fetchone()["state"]
    assert a_state == "available", "B's dismissal must not leak into A's relationship row for the same candidate"

    # B rescanning again (unchanged) is now also a true no-op, scoped to B's own reconciliation state
    rb2 = reservoir.rescan(pid_b, col["id"], enumerate=_fake_enumerate(entries))
    assert rb2["changed"] is False and rb2["new"] == 0


def test_fingerprint_is_order_insensitive(project_with_collection):
    pid, cid = project_with_collection
    entries = _entries(4)
    reversed_entries = list(reversed(entries))
    assert reservoir.fingerprint(entries) == reservoir.fingerprint(reversed_entries)


def test_fingerprint_changes_on_a_genuinely_new_item_but_not_on_reorder(project_with_collection):
    pid, cid = project_with_collection
    entries = _entries(3)
    fp1 = reservoir.fingerprint(entries)
    fp_reordered = reservoir.fingerprint(list(reversed(entries)))
    fp_new_item = reservoir.fingerprint(_entries(4))
    assert fp1 == fp_reordered
    assert fp1 != fp_new_item


def test_a_disappeared_entry_never_invalidates_what_was_already_remembered(project_with_collection):
    pid, cid = project_with_collection
    r1 = reservoir.rescan(pid, cid, enumerate=_fake_enumerate(_entries(3)))
    assert r1["new"] == 3
    first_id = r1["candidate_ids"][0]

    # the reservoir now lists only entries 2-3 (entry 1 "disappeared") -- a fingerprint change triggers a pass,
    # but nothing already remembered about vid1 may be removed or invalidated by its absence from this listing
    r2 = reservoir.rescan(pid, cid, enumerate=_fake_enumerate(_entries(2, start=2)))
    assert r2["changed"] is True   # the set changed, so a pass ran -- that's fine, it must just do no harm
    still_there = db.connect().execute("SELECT id FROM candidates WHERE id=?", (first_id,)).fetchone()
    assert still_there is not None
    rel_row = db.connect().execute("SELECT state FROM candidate_projects WHERE candidate_id=? AND project_id=?",
                                   (first_id, pid)).fetchone()
    assert rel_row is not None and rel_row["state"] == "available"


def test_rescan_project_covers_every_attached_and_monitored_collection(project_with_collection):
    pid, cid = project_with_collection
    col2 = db.upsert_collection("playlist", "PLxyz", "https://www.youtube.com/playlist?list=PLxyz", "A playlist")
    db.add_project_collections(pid, [col2["id"]])
    # CR8: attachment alone is not enough post-policy -- both must be explicitly marked primary (or monitor=on)
    # to be covered by the bulk "every collection this project is attached to" path.
    db.set_collection_policy(pid, cid, source_role="primary")
    db.set_collection_policy(pid, col2["id"], source_role="primary")

    calls = {"UCabc": _entries(2, prefix="chanvid"), "PLxyz": _entries(3, prefix="plvid")}
    def enumerate_by_url(url: str):
        key = "UCabc" if "UCabc" in url else "PLxyz"
        return {"id": key}, calls[key]

    results = reservoir.rescan_project(pid, enumerate=enumerate_by_url)
    assert {r["collection_id"] for r in results} == {cid, col2["id"]}
    assert sum(r["new"] for r in results) == 5


def test_rescan_project_skips_attached_but_unmonitored_collections_without_enumerating_them(project_with_collection):
    """CR8 (2026-09-16 product decision): a collection this project is attached to but has not marked primary
    (and never explicitly turned monitoring on) is skipped entirely by the bulk rescan path -- not scanned and
    discarded, genuinely never enumerated. The single, explicit `reservoir.rescan(pid, cid, ...)` path (the
    CLI's --collection flag) stays ungated by design -- an explicit ask for one named collection still works."""
    pid, cid = project_with_collection   # default source_role='unspecified', monitor_policy='auto' -> inactive
    col2 = db.upsert_collection("playlist", "PLxyz", "https://www.youtube.com/playlist?list=PLxyz", "A playlist")
    db.add_project_collections(pid, [col2["id"]])
    db.set_collection_policy(pid, col2["id"], source_role="primary")   # only col2 is monitored

    calls = []
    def counting_enumerate(url: str):
        calls.append(url)
        key = "UCabc" if "UCabc" in url else "PLxyz"
        return {"id": key}, _entries(2, prefix=key)

    results = reservoir.rescan_project(pid, enumerate=counting_enumerate)
    assert {r["collection_id"] for r in results} == {col2["id"]}   # cid skipped entirely
    assert len(calls) == 1 and "PLxyz" in calls[0]   # enumerate was never called for the unmonitored collection

    # the explicit, single-collection path is unaffected by policy -- still works for cid directly
    explicit = reservoir.rescan(pid, cid, enumerate=lambda url: ({"id": "UCabc"}, _entries(1, prefix="explicit")))
    assert explicit["changed"] is True and explicit["new"] == 1


def test_rescan_project_with_no_attached_collections_returns_empty():
    db.init_db()
    pid = db.create_project("S55 lonely project", brief="no collections")["id"]
    assert reservoir.rescan_project(pid) == []
