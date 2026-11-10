"""S113 — /api/usage/value/by-model accepts `days`, so a rolling 30-day spend can be split by model and billing basis.

Found in the 2026-11-10 cost audit: cost_value.by_model(days=) existed, but the endpoint dropped the parameter, and
"month" means since the 1st — an Oct 11-19 Claims sweep ($228, 77% of 30-day spend) could not be attributed by model
from the supported API. Read-only; changes no pricing, routing or stored data."""
from __future__ import annotations

import os

os.environ["NEUROSEARCH_APP_TOKEN"] = "t0k"

import pytest  # noqa: E402

from neurosearch import cost_value  # noqa: E402

H = {"Authorization": "Bearer t0k"}


def test_days_reaches_the_window(client, monkeypatch):
    seen = {}
    real = cost_value.by_model

    def spy(unit, window, project_id=None, days=None):
        seen.update(unit=unit, window=window, days=days)
        return real(unit, window, project_id, days=days)
    monkeypatch.setattr(cost_value, "by_model", spy)
    r = client.get("/api/usage/value/by-model", params={"unit": "claim", "days": 30}, headers=H)
    assert r.status_code == 200, r.text
    assert seen == {"unit": "claim", "window": "month", "days": 30}
    assert r.json()["since"] == pytest.approx(cost_value.window_start("month", 30), abs=5)


def test_without_days_nothing_changes(client):
    r = client.get("/api/usage/value/by-model", params={"unit": "claim"}, headers=H)
    assert r.status_code == 200
    assert r.json()["since"] == pytest.approx(cost_value.window_start("month"), abs=5)


def test_days_is_clamped_and_window_is_validated(client):
    big = client.get("/api/usage/value/by-model", params={"unit": "finding", "days": 99999}, headers=H).json()
    assert big["since"] == pytest.approx(cost_value.window_start("month", 180), abs=5)
    assert client.get("/api/usage/value/by-model", params={"window": "forever"}, headers=H).status_code == 400
