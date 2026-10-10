"""The production compose overlay is the fail-closed deployment form
(external review #4).

The dev stack defaults ENVIRONMENT=local, which opts out of the weak-secret
guards; these pins keep the overlay that makes them unavoidable from being
quietly loosened. The executed proofs live in CI's docker-build job (bare
image boot probe + compose render gate); the Settings-level guard itself is
pinned in test_config_security.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
OVERLAY = REPO_ROOT / "docker-compose.prod.yml"


class _ComposeLoader(yaml.SafeLoader):
    """SafeLoader plus docker compose's `!reset` tag (empties the node)."""


def _reset_tag(loader: yaml.Loader, node: yaml.Node) -> list[Any]:
    assert isinstance(node, yaml.SequenceNode)
    return loader.construct_sequence(node)


_ComposeLoader.add_constructor("!reset", _reset_tag)


def _overlay_services() -> dict:
    spec = yaml.load(OVERLAY.read_text(encoding="utf-8"), Loader=_ComposeLoader)
    assert isinstance(spec, dict)
    services = spec["services"]
    assert isinstance(services, dict)
    return services


def test_overlay_pins_production_environment() -> None:
    services = _overlay_services()
    for name in ("api", "worker"):
        environment = services[name]["environment"]
        # A literal, not an interpolation: ambient ENVIRONMENT=local must not
        # be able to opt the production stack out of the guards.
        assert environment["ENVIRONMENT"] == "production"


def test_overlay_secrets_have_no_defaults() -> None:
    services = _overlay_services()
    for name in ("api", "worker"):
        environment = services[name]["environment"]
        for key in ("SECRET_KEY", "S3_SECRET_KEY"):
            value = environment[key]
            # `${VAR:?message}` — required at render time, no fallback the
            # Settings guard could be tempted to accept.
            assert isinstance(value, str)
            assert value.startswith(f"${{{key}:?"), value


def test_overlay_runs_image_code_not_host_checkouts() -> None:
    services = _overlay_services()
    # The base worker bind-mounts ./backend; a host without a checkout would
    # get an empty directory shadowing the image's code. Production resets
    # the mount entirely.
    assert services["worker"]["volumes"] == []
    assert "volumes" not in services["api"]
