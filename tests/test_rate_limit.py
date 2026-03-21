"""Tests for the rate-limit middleware and the /api/runs/trigger endpoint."""
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_trigger_endpoint_returns_200_when_under_limit() -> None:
    """A single request well under the rate limit should return 200 + queued."""
    payload = {"org_id": "org-test-123"}
    response = client.post("/api/runs/trigger", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "queued"
    assert data["org_id"] == "org-test-123"


def test_trigger_endpoint_accepts_extra_run_params() -> None:
    """Extra run_params should be accepted and the response shape preserved."""
    payload = {
        "org_id": "org-abc",
        "run_params": {"model": "gpt-4o", "max_tokens": 1024},
    }
    response = client.post("/api/runs/trigger", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "queued"
    assert data["org_id"] == "org-abc"


def test_trigger_endpoint_requires_org_id() -> None:
    """Requests missing org_id must be rejected with 422 Unprocessable Entity."""
    response = client.post("/api/runs/trigger", json={})
    assert response.status_code == 422


def test_rate_limit_middleware_blocks_excessive_requests() -> None:
    """After exceeding max_requests within the window the middleware returns 429."""
    from app.api.middleware import RateLimitMiddleware
    from fastapi import FastAPI
    from app.api.routes import runs as runs_module

    tight_app = FastAPI()
    tight_app.add_middleware(RateLimitMiddleware, max_requests=3, window_seconds=60)
    tight_app.include_router(runs_module.router, prefix="/api/runs")

    tight_client = TestClient(tight_app)
    payload = {"org_id": "org-burst"}

    for _ in range(3):
        r = tight_client.post("/api/runs/trigger", json=payload)
        assert r.status_code == 200

    r = tight_client.post("/api/runs/trigger", json=payload)
    assert r.status_code == 429
