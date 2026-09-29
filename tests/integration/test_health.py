from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_liveness(client) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["app"] == "AgentHU"


def test_readiness_reports_dependency_checks(client) -> None:
    response = client.get("/health/ready")
    assert response.status_code in (200, 503)
    body = response.json()
    assert body["checks"]["database"] == "ok"
    # In-memory storage is always ready in tests.
    assert body["checks"]["object_storage"] == "ok"
