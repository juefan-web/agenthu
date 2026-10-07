"""Zero-trust client-source resolution (P0-5 frozen ruling 2).

``client_ip`` is the single seam through which the login/recover rate-limit
keys and the audit IP face resolve a client address. The socket peer is the
default; X-Forwarded-For is consulted only when the peer is an explicitly
configured trusted proxy (``Settings.trusted_proxies``), and then the chain
is walked right-to-left SKIPPING trusted proxies — the first untrusted entry
is the proxy-attested client. Client-controlled leftmost entries and deeper
proxy chains cannot defeat the walk, and an unconfigured proxy list ignores
the header everywhere: fail closed against spoofed login sources.
"""

from __future__ import annotations

from starlette.requests import Request

from backend.config import get_settings


def client_ip(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    if peer == "unknown":
        return peer
    trusted = get_settings().trusted_proxies
    if not trusted or peer not in trusted:
        return peer
    forwarded = request.headers.get("x-forwarded-for", "")
    for entry in reversed([part.strip() for part in forwarded.split(",")]):
        if entry and entry not in trusted:
            return entry
    return peer
