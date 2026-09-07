"""Shared fixtures. The FastAPI app (with its MCP mount) can only be started ONCE per process, so the API client is
session-scoped here and every module that talks to the app through HTTP uses this one instance."""
from __future__ import annotations

import pytest


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient
    from neurosearch.api import app
    with TestClient(app) as c:
        yield c
