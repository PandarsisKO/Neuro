"""Foundation phase 1/2: lifecycle, cost boundaries, attribution and stale-client gates.

All data is temporary. Blocking workers and transports are controlled by Events, not live providers.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import threading
import time

os.environ.setdefault('NEUROSEARCH_DATA_DIR', tempfile.mkdtemp(prefix='ns_foundation_'))
os.environ['NEUROSEARCH_FAKE_AI'] = '1'

import pytest
from neurosearch import api, claude_code as CC, db, jobs, providers
from neurosearch.config import Settings, settings

ROOT = pathlib.Path(__file__).resolve().parent.parent

@pytest.fixture
def fresh(tmp_path, monkeypatch):
    data = tmp_path / 'data'; data.mkdir()
    monkeypatch.setattr(settings, 'data_dir', data)
    monkeypatch.setattr(settings, 'fake_ai', True)
    monkeypatch.setattr(settings, 'ai_profile', 'local')
    monkeypatch.setattr(settings, 'local_api_fallback', False)
    monkeypatch.setattr(settings, 'daily_budget', 1000)
    db.close_thread_connection(); db.init_db()
    providers.set_policy(None)
    CC._state['health'] = None; CC._state['by_model'] = {}
    yield data
    providers.set_policy(None)
    CC._state['health'] = None; CC._state['by_model'] = {}
    db.close_thread_connection()


def test_paid_fallback_requires_explicit_opt_in(monkeypatch):
    monkeypatch.delenv('NEUROSEARCH_LOCAL_API_FALLBACK', raising=False)
    assert Settings().local_api_fallback is False
    for value in ('false', 'garbage', '0'):
        monkeypatch.setenv('NEUROSEARCH_LOCAL_API_FALLBACK', value)
        assert Settings().local_api_fallback is False
    monkeypatch.setenv('NEUROSEARCH_LOCAL_API_FALLBACK', 'true')
    assert Settings().local_api_fallback is True


@pytest.mark.parametrize('mode', ['timeout', 'limit', 'not_installed', 'error'])
@pytest.mark.parametrize('cached_ready', [True, False])
def test_local_failure_never_opens_paid_transport(fresh, monkeypatch, mode, cached_ready):
    monkeypatch.setenv(CC.FAKE_ENV, mode)
    if cached_ready:
        CC._state['health'] = {'state': 'ready', 'checked_at': 1e12}
    with pytest.raises(providers.ProviderError):
        providers.invoke_structured('rank.relevance', system='PROJECT: x', usage_kind='rank', messages=[{'role': 'user', 'content': 'VIDEOS:\n[0] Debt'}])
    rows = db.connect().execute('SELECT provider, state FROM invocations').fetchall()
    assert rows and all(x['provider'] == CC.PROVIDER for x in rows)
    assert all(x['state'] == 'failed' for x in rows)
    assert 'paid fallback off' in CC.status_line()


def test_local_failure_parks_same_job_without_attempt_or_paid_call(fresh, monkeypatch):
    monkeypatch.setenv(CC.FAKE_ENV, 'timeout')
    CC._state['health'] = {'state': 'ready', 'checked_at': 1e12}
    j = db.create_job('rank_proposed', {})
    claimed = db.claim_job()
    assert claimed['id'] == j['id']
    def run(job):
        # execute supplies context even when an implementation adapter is replaced.
        return providers.invoke_structured('rank.relevance', system='PROJECT: x', usage_kind='rank', messages=[{'role': 'user', 'content': 'VIDEOS:\n[0] Debt'}])
    monkeypatch.setattr(jobs, 'run_job', run)
    assert jobs.execute(claimed) == 'queued'
    after = db.get_job(j['id'])
    assert after['attempts'] == 0 and after['wait_reason'] == 'provider'
    assert 'no paid API fallback' in after['message']
    row = db.connect().execute('SELECT * FROM invocations').fetchone()
    assert row['job_id'] == j['id'] and row['run_id'] == claimed['run_id']
    assert row['state'] == 'failed' and row['provider'] == CC.PROVIDER


def test_shutdown_keeps_survivor_and_refuses_new_generation(fresh, monkeypatch):
    release = threading.Event(); entered = threading.Event()
    def blocking():
        entered.set(); release.wait(5)
    t = threading.Thread(target=blocking, name='ns-worker-blocked', daemon=True)
    monkeypatch.setattr(jobs, '_threads', [t])
    t.start(); assert entered.wait(1)
    try:
        with pytest.raises(RuntimeError, match='shutdown incomplete'):
            jobs.stop_workers(timeout=.01)
        assert t in jobs._threads and jobs._stop.is_set()
        with pytest.raises(RuntimeError, match='second generation'):
            jobs.start_workers()
        assert jobs._stop.is_set(), 'a failed restart must not revive stopped workers'
    finally:
        release.set(); t.join(2); jobs.stop_workers(timeout=1)
    assert jobs._threads == []


def test_lifespan_converts_bounded_worker_survivor_to_recovery_warning(fresh, monkeypatch, caplog):
    """ASGI shutdown remains clean when a provider worker exceeds the drain bound."""
    @contextlib.asynccontextmanager
    async def fake_sessions():
        yield
    monkeypatch.setattr(api.mcp.session_manager, 'run', fake_sessions)
    monkeypatch.setattr(jobs, 'start_workers', lambda: None)
    monkeypatch.setattr(jobs, 'stop_workers', lambda: (_ for _ in ()).throw(RuntimeError('Worker shutdown incomplete: ns-worker-local-ai-0')))
    warnings = []
    monkeypatch.setattr(api.log, 'warning', lambda message, *args: warnings.append(message % args if args else message))

    async def exercise():
        async with api.lifespan(api.app):
            pass
    asyncio.run(exercise())
    assert any('startup recovery will reconcile it' in message for message in warnings)


def test_native_worker_restart_recovers_inflight_fake_provider_job(fresh):
    """A real worker process dies inside provider work; its replacement resumes once."""
    project = db.create_project("restart", "find useful debt sources")
    job = db.create_job("discover", {"project_id": project["id"], "refine": "debt", "mode": "web_only"})
    env = {**os.environ, "NEUROSEARCH_DATA_DIR": str(fresh), "NEUROSEARCH_FAKE_AI": "1",
           "NEUROSEARCH_AI_PROFILE": "cloud", "NEUROSEARCH_WORKERS": "1",
           "NEUROSEARCH_FAKE_AI_DELAY": "5"}

    # Run the checked-out code with the interpreter that is executing the
    # suite.  A clean worktree need not contain its own .venv directory.
    command = [sys.executable, "-m", "neurosearch.cli", "worker", "--n", "1"]
    first = subprocess.Popen(command,
                             cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.time() + 8
        in_flight = 0
        while time.time() < deadline:
            in_flight = db.connect().execute(
                "SELECT COUNT(*) FROM invocations WHERE job_id=? AND state='in_flight'", (job["id"],)
            ).fetchone()[0]
            if (db.get_job(job["id"]) or {}).get("status") == "running" and in_flight:
                break
            time.sleep(.05)
        assert db.get_job(job["id"])["status"] == "running"
        assert in_flight == 1, "kill only after the provider attempt is durably in flight"
    finally:
        first.terminate(); first.wait(timeout=5)

    env["NEUROSEARCH_FAKE_AI_DELAY"] = "0"
    second = subprocess.Popen(command,
                              cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.time() + 10
        while time.time() < deadline and (db.get_job(job["id"]) or {}).get("status") != "done":
            time.sleep(.05)
        assert db.get_job(job["id"])["status"] == "done"
    finally:
        second.terminate(); second.wait(timeout=5)

    rows = db.connect().execute("SELECT state, COUNT(*) n FROM invocations WHERE job_id=? GROUP BY state", (job["id"],)).fetchall()
    states = {r["state"]: r["n"] for r in rows}
    assert states == {"completed": 2, "outcome_unknown": 1}
    assert len(db.list_discoveries(project["id"])) >= 1


def test_worker_database_is_bound_before_first_connection_and_closed(fresh, tmp_path, monkeypatch):
    path = settings.db_path
    entered = threading.Event(); proceed = threading.Event(); result = {}
    def body():
        entered.set(); assert proceed.wait(2)
        conn = db.connect(); result['conn'] = conn
        result['path'] = conn.execute('PRAGMA database_list').fetchone()['file']
    t = threading.Thread(target=jobs._thread_main, args=(body, path))
    t.start(); assert entered.wait(1)
    monkeypatch.setattr(settings, 'data_dir', tmp_path / 'other')
    proceed.set(); t.join(3)
    assert not t.is_alive() and result['path'] == str(path)
    import sqlite3
    with pytest.raises(sqlite3.ProgrammingError, match='closed'):
        result['conn'].execute('SELECT 1')
    assert not (tmp_path / 'other').exists()


def test_lease_keeper_survives_stop_admission_until_work_drains(fresh, monkeypatch):
    beat = threading.Event()
    monkeypatch.setattr(jobs, '_running', {'job': 'run'})
    monkeypatch.setattr(db, 'heartbeat', lambda *args: beat.set() or True)
    jobs._stop.set(); jobs._lease_stop.clear()
    t = threading.Thread(target=jobs._lease_loop, args=(.01,), daemon=True)
    t.start()
    try:
        assert beat.wait(1), 'stopping queue admission must not abandon a running lease'
    finally:
        jobs._lease_stop.set(); t.join(2)
    assert not t.is_alive()


def test_stale_client_refused_before_endpoint_side_effects():
    called = []; sent = []
    async def endpoint(scope, receive, send):
        called.append(True)
        await send({'type': 'http.response.start', 'status': 200, 'headers': []})
        await send({'type': 'http.response.body', 'body': b'{}'})
    async def receive(): return {'type': 'http.request', 'body': b''}
    async def send(message): sent.append(message)
    middleware = api.ClientVersionMiddleware(endpoint)
    scope = {'type': 'http', 'method': 'POST', 'path': '/api/test-side-effect', 'headers': [(b'x-neurosearch-ui-version', b'old')]}
    asyncio.run(middleware(scope, receive, send))
    assert not called and sent[0]['status'] == 409
    assert json.loads(sent[1]['body'])['code'] == 'client_version_mismatch'
    from neurosearch import __version__
    for headers in ([], [(b'x-neurosearch-ui-version', __version__.encode())]):
        sent.clear(); called.clear()
        asyncio.run(middleware({**scope, 'headers': headers}, receive, send))
        assert called and sent[0]['status'] == 200
        assert (b'x-neurosearch-version', __version__.encode()) in sent[0]['headers']


def test_frontend_stale_response_blocks_next_request_and_keeps_one_notice(tmp_path):
    html = (ROOT / 'neurosearch/web/js/state.js').read_text()
    code = html.split('globalThis.staleClientVersion = null;')[1].split('globalThis.checkVersion = async function checkVersion()')[0]
    script = """
const assert = require('node:assert/strict');
const UI_VERSION = 'current';
let calls = 0, notices = 0; const elements = {};
const $ = key => elements[key]; const showVersion = () => {};
const location = {reload(){}};
const document = {createElement(){return {setAttribute(){},style:{},addEventListener(){}}}, body:{appendChild(el){notices++; elements['#verBanner']=el; elements['#reloadCurrentUI']={addEventListener(){}}}}};
const fetch = async () => {calls++; return {headers:new Headers({'X-Neurosearch-Version':'new'})};};
globalThis.staleClientVersion = null;
    """ + code + ";\n" + """
(async () => {
 await assert.rejects(uiFetch('/api/projects'), /out of date/);
 await assert.rejects(uiFetch('/api/projects', {method:'POST'}), /out of date/);
 assert.equal(calls, 1); assert.equal(notices, 1);
 showStaleClient('new'); assert.equal(notices, 1);
})().catch(e => {console.error(e); process.exit(1)});
"""
    file = tmp_path / 'version-test.cjs'; file.write_text(script)
    subprocess.run(['node', str(file)], check=True, capture_output=True, text=True)


def test_read_surfaces_do_not_launch_models_jobs_or_health_refresh(fresh, monkeypatch):
    """Phase 2 request-path purity: polling and status reads remain observation only."""
    project = db.create_project("pure reads", "observe without launching work")

    def forbidden(*args, **kwargs):
        raise AssertionError("a read-only request launched hidden work")

    monkeypatch.setattr(providers, "invoke", forbidden)
    monkeypatch.setattr(providers, "invoke_structured", forbidden)
    monkeypatch.setattr(CC, "health", forbidden)
    monkeypatch.setattr(db, "create_job", forbidden)

    assert api.api_version()["version"]
    assert api.api_usage()["local_ai"]["state"] == "unchecked"
    assert api.api_health()["local_ai"]["state"] == "unchecked"
    assert api.api_tick(project["id"])["rev"]
    assert api.api_project(project["id"])["id"] == project["id"]
    assert "sources" in api.api_staleness(project["id"])
    assert api.api_ai_backlog(project["id"])["line"] == "nothing waiting"
    assert api.api_sources(project_id=project["id"]) == []
