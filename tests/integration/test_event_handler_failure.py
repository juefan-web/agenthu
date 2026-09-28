from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_handler_db_failure_does_not_lose_the_event(client, auth_headers) -> None:
    """A DB-level handler failure must not roll back the raw Event (C1).

    The handler raises a PostgreSQL error (1/0), which poisons the surrounding
    transaction unless the handler ran inside a SAVEPOINT. Without the
    savepoint the failure cascades into the audit write and the outer commit,
    losing the just-inserted Event — the exact regression this file guards.
    """

    from sqlalchemy import text

    from backend.services.event_handlers import _HANDLERS, register

    @register("integration.handler_boom")
    def boom(session, event) -> None:
        session.execute(text("SELECT 1/0"))

    try:
        response = client.post(
            "/v1/events",
            json={"type": "integration.handler_boom", "source": "manual", "data": {"probe": 1}},
            headers=auth_headers,
        )
        assert response.status_code == 201, response.text

        listed = client.get(
            "/v1/events", params={"type": "integration.handler_boom"}, headers=auth_headers
        )
        assert listed.status_code == 200
        assert listed.json()["total"] == 1
    finally:
        _HANDLERS.pop("integration.handler_boom", None)
