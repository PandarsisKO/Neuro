"""Offline R8a measurement: synthetic DB, 5,000 posts, no network/models/capture.

Run with the desired checkout on PYTHONPATH. Optionally set CATALOG_FIXTURE_FETCH_DELAY
(e.g. 0.01 seconds per mocked page) to sample foreground writes between worker turns.
One-shot timings are evidence, not a machine-independent performance threshold.
"""
import json
import math
import os
import threading
import time
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# Allocate our own empty scratch instance BEFORE importing application config. Never
# accept a caller-provided data directory, dotenv or credentials for this measurement.
os.environ["NEUROSEARCH_DATA_DIR"] = tempfile.mkdtemp(prefix="neuro-catalog-perf-")
os.environ["PYTHON_DOTENV_DISABLED"] = "true"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"
for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
    os.environ.pop(key, None)

from neurosearch import candidates, community, db, ingest, jobs, knowledge, providers, resources, safe_fetch
from neurosearch.config import settings

assert settings.fake_ai
settings.auto_suggest = False
settings.data_dir.mkdir(parents=True, exist_ok=True)
db.init_db()

def forbidden(*_a, **_kw):
    raise AssertionError("network/model/acquisition is forbidden in metadata measurement")

safe_fetch.safe_fetch = providers.invoke = ingest.ingest_url = community.read_reddit_thread = forbidden
pid = db.create_project("Synthetic acquisition research", brief="Buying a small accounting practice: owner transition, staffing, client retention and debt service.")["id"]
knowledge.add_target(pid, "What staffing and retention problems did buyers of accounting practices encounter?")
url = "https://www.reddit.com/r/smallbusiness/"
routed = resources.route(resources.classify(url), pid)
cid = routed["collection_id"]
holds = []
worker_holds = []
original_hold = db._note_write_hold

def note_hold(conn, t0, what):
    if conn.in_transaction:
        holds.append(time.perf_counter() - t0)
        if threading.current_thread() is threading.main_thread():
            worker_holds.append(time.perf_counter() - t0)
    original_hold(conn, t0, what)

db._note_write_hold = note_hold

def page(_sub, after, **_kw):
    assert not db.connect().in_transaction
    if delay := float(os.environ.get("CATALOG_FIXTURE_FETCH_DELAY", "0")):
        time.sleep(delay)
    n = int(after) if after else 0
    rows = [{"external_id": f"reddit:p{i:04}", "url": url + f"comments/p{i:04}/title/",
             "title": f"Owner staffing and accounting practice retention {i}",
             "description": "I bought a practice and lost three clients during the employee transition. Budget repairs and debt service before closing.",
             "creator": f"owner{i % 100}", "observed_metadata": True,
             "metadata": {"score": i % 70, "comment_count": i % 13, "created_utc": 1780000000 + i},
             "published_at": "2026-05-28"} for i in range(n * 100, (n + 1) * 100)]
    return rows, str(n + 1) if n < 49 else None

community.enumerate_subreddit_page = page
start = threading.Barrier(2)
finished = threading.Event()
foreground = []

def foreground_writes():
    try:
        start.wait(timeout=5)
        while not finished.is_set() and len(foreground) < 1000:
            t = time.perf_counter()
            db.create_conversation(pid, "Synthetic foreground responsiveness")
            foreground.append(time.perf_counter() - t)
            finished.wait(0.002)
    finally:
        db.close_thread_connection()

t0 = time.perf_counter()
with ThreadPoolExecutor(max_workers=1) as pool:
    pending = pool.submit(foreground_writes)
    start.wait(timeout=5)
    try:
        for n in range(50):
            claim = db.claim_job(("explore",), worker_id="offline-perf")
            assert claim and claim["id"] == routed["job_id"]
            assert jobs.execute(claim, "offline-perf") == ("queued" if n < 49 else "done")
    finally:
        finished.set()
    pending.result(timeout=10)
scan_seconds = time.perf_counter() - t0
assert len(db.collection_candidate_ids(cid)) == 5000
assert not db.project_source_ids(pid, ready_only=False)

scorings = []
original_potential = candidates._potential
def potential(*a, **kw):
    scorings.append(1)
    return original_potential(*a, **kw)
candidates._potential = potential
queries = []
db.connect().set_trace_callback(lambda sql: queries.append(1))
t0 = time.perf_counter()
view = candidates.catalog(pid, cid)
cold = time.perf_counter() - t0
cold_queries, cold_scores = len(queries), len(scorings)
warm = []
for _ in range(20):
    t0 = time.perf_counter()
    candidates.catalog(pid, cid)
    warm.append(time.perf_counter() - t0)
warm_queries = (len(queries) - cold_queries) / 20
warm_scores = len(scorings) - cold_scores
db.connect().set_trace_callback(None)
later = db.create_project("Synthetic second project")["id"]
t0 = time.perf_counter()
community.attach_subreddit_catalog(later, url)
attach = time.perf_counter() - t0
assert not db.project_source_ids(later, ready_only=False)

def p90(values):
    return sorted(values)[max(0, math.ceil(len(values) * 0.9) - 1)] if values else None

print(json.dumps({"source_file": str(Path(candidates.__file__).resolve()), "rows": 5000, "worker_turns": 50,
                  "scan_seconds": scan_seconds, "foreground_samples": len(foreground),
                  "foreground_p90_ms": p90(foreground) * 1000, "foreground_max_ms": max(foreground) * 1000,
                  "max_write_hold_ms": max(holds) * 1000, "warning_threshold_ms": db.WRITE_HOLD_WARN_S * 1000,
                  "worker_max_tx_elapsed_ms": max(worker_holds) * 1000,
                  "fixture_fetch_delay_s": float(os.environ.get("CATALOG_FIXTURE_FETCH_DELAY", "0")),
                  "cold_review_ms": cold * 1000, "cold_queries": cold_queries, "cold_scores": cold_scores,
                  "warm_review_p90_ms": p90(warm) * 1000, "warm_queries": warm_queries, "warm_scores": warm_scores,
                  "second_attach_ms": attach * 1000, "default_rows": len(view["items"]),
                  "payload_bytes": len(json.dumps(view).encode())}, indent=2))
db.close_thread_connection()
