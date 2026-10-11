# Copyright 2026 Aayush Chawla
# SPDX-License-Identifier: Apache-2.0

"""Engine API authentication dependency.

Every REST route takes the app bearer token (`Authorization: Bearer`). The
few routes the bundled n8n workflows call also take the n8n token in the
`X-Laya-N8n-Token` header, and nothing else does: a caller holding only the
n8n token cannot reach any other route. On those routes a request with
neither credential is handled according to the n8n enforcement mode
(`security/n8n_auth.py`): logged and let through in `log` mode, rejected in
`enforce` mode.
"""

from __future__ import annotations

import hmac

import structlog
from fastapi import HTTPException, Request, status

from laya.security import n8n_auth
from laya.security.keychain import get_engine_token

log = structlog.get_logger()

# Routes the bundled n8n workflows call. Exact (method, path) matches; the
# UI also calls GET /repos, so each route accepts either credential.
N8N_ROUTES: set[tuple[str, str]] = {
    ("POST", "/events"),
    ("GET", "/repos"),
    ("POST", "/ingestion-errors"),
}

# n8n reads single metadata keys (GET /metadata/{key}). Listing (`/metadata`)
# and writing metadata are app-token only: a metadata write can repoint a
# workflow's config (e.g. the Bitbucket Server URL its credential is sent to).
_N8N_METADATA_PREFIX = "/metadata/"

# Vendor OAuth redirects arrive from the user's browser with no bearer header.
VENDOR_OAUTH_EXEMPT_ROUTES: set[tuple[str, str]] = {
    ("GET", "/egress/connections/oauth/callback"),
}


def is_n8n_route(method: str, path: str) -> bool:
    """True for the routes that accept the n8n token as well as the app token."""
    if (method, path) in N8N_ROUTES:
        return True
    return method == "GET" and path.startswith(_N8N_METADATA_PREFIX) and len(path) > len(_N8N_METADATA_PREFIX)


def is_auth_exempt(method: str, path: str) -> bool:
    """True for routes that take no credential at all (the vendor OAuth callback)."""
    return (method, path) in VENDOR_OAUTH_EXEMPT_ROUTES


def _unauthorized(detail: str = "Unauthorized") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def bearer_matches(request: Request) -> bool:
    """True when the request carries the app bearer token."""
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.lower().startswith("bearer "):
        return False
    presented = auth_header[7:].strip()
    expected = get_engine_token()
    # Compare as bytes: hmac.compare_digest raises TypeError on non-ASCII str,
    # and header values are latin-1 decoded, so a bearer containing bytes
    # >= 0x80 would surface as a 500 instead of a 401.
    return bool(expected) and hmac.compare_digest(
        presented.encode("utf-8"), expected.encode("utf-8")
    )


async def require_engine_auth(request: Request) -> str:
    """Authenticate an incoming REST request.

    Returns the app token, "n8n" when the n8n token was used, or "" when the
    route is exempt or let through in n8n log mode. GET /health is exempted at
    the router inclusion level in main.py.
    """
    path = request.url.path.rstrip("/")
    method = request.method
    if is_auth_exempt(method, path):
        return ""

    if bearer_matches(request):
        return request.headers["authorization"][7:].strip()

    if is_n8n_route(method, path):
        if n8n_auth.header_matches(request):
            return "n8n"
        enforced = n8n_auth.get_mode() == n8n_auth.MODE_ENFORCE
        n8n_auth.record_rejection(request, enforced=enforced)
        if not enforced:
            return ""
        raise _unauthorized(
            "n8n token missing or invalid. Check the n8n engine credential status "
            "under Settings → Integrations → n8n."
        )

    log.warning("engine_auth_failed", path=path, method=method)
    raise _unauthorized()
