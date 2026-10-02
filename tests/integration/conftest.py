"""Shared fixtures for integration tests.

``no_arq`` moved here from test_materials.py: it is a real pytest fixture
(used in test signatures only), so importing it cross-module made it look
like an unused import to ruff's F401 — which silently broke fixture
resolution for every consumer outside the defining module.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def no_arq(monkeypatch):
    """Upload/consent endpoints enqueue best-effort; tests must not hit Redis."""

    class _Boom:
        async def enqueue_job(self, *a, **k):
            raise RuntimeError("no redis in tests")

    async def _fake_pool():
        return _Boom()

    monkeypatch.setattr("backend.api.v1.files.get_arq_pool", _fake_pool)
    monkeypatch.setattr("backend.api.v1.material.get_arq_pool", _fake_pool)
