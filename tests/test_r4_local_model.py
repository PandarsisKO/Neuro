"""0.52.0 — the local provider runs the CONTRACT's model, not one global .env line.

CLAUDE.md has carried this rule since L1: *"never a model substitution — there is no model-substitution code path
and none may be added."* It was not true. `claude_code.create` passed `settings.claude_code_model` for every task
regardless of its contract, so on Kyle's machine `findings.extract` — pinned to Sonnet 5 by the E2.2 comparison —
ran on Haiku 4.5 for every local call (59% of them), and nothing recorded that it had. The experiment was running
without either of us knowing, and without a way to tell which model produced which finding.

The fix is not "forbid Haiku". A cheaper model is often the right choice, and the free subscription is worth
using. The fix is that the choice must be DECLARED per task and RECORDED on the artifact, so the difference
between "Haiku because we measured it" and "Haiku because of one line in .env" is visible. (Sorts after test_r3.)"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("NEUROSEARCH_DATA_DIR", tempfile.mkdtemp(prefix="ns_lm_"))
os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"
os.environ["NEUROSEARCH_FAKE_AI"] = "1"

import pytest  # noqa: E402

from neurosearch import claude_code as CC  # noqa: E402
from neurosearch import contracts, db, providers, release  # noqa: E402
from neurosearch.config import settings  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    data = tmp_path / "data"; data.mkdir(); (data / "media").mkdir()
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "fake_ai", True)
    db._local.conn = None
    db.init_db()
    yield
    db._local.conn = None


def test_by_default_local_runs_exactly_what_the_contract_asks_for():
    """No substitution is the DEFAULT, not an option — every local-capable task, unconfigured."""
    for c in contracts.all_contracts():
        if c.local_capable:
            assert c.model_for("local") == c.model, f"{c.task} would silently change model when it runs locally"
    # and the two models chosen by measurement are the ones that must never drift by accident
    assert contracts.contract("findings.extract").model_for("local") == "claude-sonnet-5"
    assert contracts.contract("rank.relevance").model_for("local") == "claude-sonnet-5"


def test_a_declared_local_model_is_allowed_and_is_recorded(monkeypatch):
    """Declaring a cheaper local model is a legitimate trade — provided the artifact says so."""
    base = contracts.contract("claims.extract")
    cheap = contracts.replace(base, local_model="claude-haiku-4-5")
    monkeypatch.setattr(contracts, "contract", lambda t: cheap if t == "claims.extract" else base)
    assert cheap.model_for("local") == "claude-haiku-4-5"
    assert cheap.model_for("api") == base.model, "the API model is untouched by a local declaration"

    providers._tl.route = {"executed_by": "local", "reason": "local_preferred", "fallback_reason": None}
    r = providers.routing_for("claims.extract", "claude-haiku-4-5-20251001")
    assert r["requested_model"] == "claude-haiku-4-5"
    assert r["local_model"] == "claude-haiku-4-5" and r["api_model"] == base.model
    assert r["executed_by"] == "local" and r["fallback_used"] is False
    # the same contract on the API records the API model and no local keys at all
    providers._tl.route = {"executed_by": "api", "reason": "cloud_profile", "fallback_reason": None}
    r2 = providers.routing_for("claims.extract", base.model)
    assert r2["requested_model"] == base.model and "local_model" not in r2


def test_the_call_asks_for_the_contract_model_not_the_env_line(monkeypatch):
    seen = {}

    def fake_run(prompt, system=None, model=None, timeout=None, schema=None):
        seen["model"] = model
        return CC.LocalResponse("{}", {"input_tokens": 1, "output_tokens": 1}, str(model), "s", None)

    monkeypatch.setattr(CC, "_run", fake_run)
    monkeypatch.setattr(CC, "fake_mode", lambda: None)
    monkeypatch.setattr(settings, "claude_code_model", None)
    CC.create(messages=[{"role": "user", "content": "x"}], extra_headers={"x-neurosearch-task": "findings.extract"})
    assert seen["model"] == "claude-sonnet-5", "the pinned, measured model must be what actually runs"
    # the global override still works — it is a supported way to keep the subscription usable — but it is explicit
    monkeypatch.setattr(settings, "claude_code_model", "claude-haiku-4-5")
    CC.create(messages=[{"role": "user", "content": "x"}], extra_headers={"x-neurosearch-task": "findings.extract"})
    assert seen["model"] == "claude-haiku-4-5"


def test_doctor_names_every_task_a_global_override_is_overriding(monkeypatch):
    monkeypatch.setattr(settings, "claude_code_model", "claude-haiku-4-5")
    rep = release.doctor(progress=lambda *a: None, fake_smoke=False)
    line = next((c for c in rep["checks"] if "local model override" in c["check"]), None)
    assert line is not None, "a silent global substitution must be reported"
    assert "findings.extract" in str(line["detail"]) and "rank.relevance" in str(line["detail"])
    assert line["result"] != "PASS", "a global override of measured per-task models is not a pass"
    # with no override, doctor reports what each local task will actually run
    monkeypatch.setattr(settings, "claude_code_model", None)
    rep2 = release.doctor(progress=lambda *a: None, fake_smoke=False)
    line2 = next(c for c in rep2["checks"] if "local model follows each contract" in c["check"])
    assert line2["result"] == "PASS" and "findings.extract" in str(line2["detail"])


def test_pin_api_transport_forces_findings_extract_off_local(monkeypatch):
    """L-02 (EXECUTION-LADDER.md): providers.route() ignores settings.fake_ai entirely -- it decides local-vs-api
    purely from ai_profile / policy / claude_code.health(). On a machine whose .env sets
    NEUROSEARCH_AI_PROFILE=local (Kyle's), a Tier-1 eval that only sets fake_ai=True still routed local_capable
    tasks to the real `claude` CLI. `evals.pin_api_transport()` is the fix `cli.eval_cmd` now applies for every
    non---live run: it forces the policy to api_only so route() returns "api" regardless of ai_profile, and
    `unpin_api_transport` restores the developer's own profile afterward."""
    from neurosearch import evals
    monkeypatch.setattr(settings, "ai_profile", "local")
    assert providers.route("findings.extract")[0] == "local", "sanity: this task would route local unpinned"
    was, mod = evals.pin_api_transport()
    try:
        assert providers.route("findings.extract") == ("api", "policy:api_only")
    finally:
        evals.unpin_api_transport(was, mod)
    assert settings.ai_profile == "local", "unpin must restore the developer's own profile"
    assert providers.route("findings.extract")[0] == "local", "and routing must go back to how it was"
