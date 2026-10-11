# Copyright 2026 Aayush Chawla
# SPDX-License-Identifier: Apache-2.0

"""Authentication of the bundled n8n workflows' calls to the engine.

n8n presents a token of its own, separate from the app bearer token, in the
`X-Laya-N8n-Token` header. The token is accepted only on the routes the
workflows call (see `engine_auth.N8N_ROUTES`), so a compromised n8n can post
events and ingestion errors and read repos and single metadata keys, and
nothing else.

Enforcement is staged. Existing installs have clones running the previous
template, which sends no header, until the startup propagation pushes the new
one. In `log` mode a missing or wrong token is logged and counted and the
request proceeds; in `enforce` mode it is rejected. `evaluate_readiness`
switches to `enforce` once every workflow is known to carry the header, and
the mode is never switched back automatically.
"""

from __future__ import annotations

import hmac
import os

import structlog
from fastapi import Request

from laya.config import load_settings, save_settings
from laya.db.timeutil import db_now
from laya.security.keychain import get_n8n_token, n8n_token_source

log = structlog.get_logger()

HEADER_NAME = "X-Laya-N8n-Token"

# Recovery hatch: `LAYA_N8N_AUTH=off` keeps the engine in log mode for this
# session no matter what settings.json says. For an operator whose n8n lost
# the token (hand-started n8n, wrong environment) and who needs ingestion back
# before fixing it.
HATCH_ENV = "LAYA_N8N_AUTH"

MODE_LOG = "log"
MODE_ENFORCE = "enforce"

# Rejections observed since the engine started. Shown on the Settings n8n
# panel so a drifted token is visible even in log mode.
_rejected_since_start = 0
_last_rejected_at: str | None = None


def hatch_active() -> bool:
    """True when `LAYA_N8N_AUTH=off` forces log mode for this session."""
    return os.environ.get(HATCH_ENV, "").strip().lower() == "off"


def get_mode() -> str:
    """Effective enforcement mode: the hatch wins, else settings.json `n8n_auth.mode`."""
    if hatch_active():
        return MODE_LOG
    mode = (load_settings().get("n8n_auth") or {}).get("mode")
    return MODE_ENFORCE if mode == MODE_ENFORCE else MODE_LOG


def set_enforced() -> None:
    """Persist `enforce` mode with the time it was switched on."""
    settings = load_settings()
    settings["n8n_auth"] = {"mode": MODE_ENFORCE, "enforced_since": db_now()}
    save_settings(settings)
    log.info("n8n_auth_enforced")


def header_matches(request: Request) -> bool:
    """True when the request carries the current n8n token."""
    presented = request.headers.get(HEADER_NAME, "").strip()
    expected = get_n8n_token()
    if not presented or not expected:
        return False
    # Compare as bytes: hmac.compare_digest raises TypeError on non-ASCII str,
    # and header values are latin-1 decoded.
    return hmac.compare_digest(presented.encode("utf-8"), expected.encode("utf-8"))


def record_rejection(request: Request, *, enforced: bool) -> None:
    """Count a request on an n8n route that carried neither credential."""
    global _rejected_since_start, _last_rejected_at
    _rejected_since_start += 1
    _last_rejected_at = db_now()
    log.warning(
        "n8n_auth_missing",
        path=request.url.path,
        method=request.method,
        mode=MODE_ENFORCE if enforced else MODE_LOG,
        rejected=enforced,
    )


def rejection_stats() -> tuple[int, str | None]:
    """(rejections since start, time of the last one)."""
    return _rejected_since_start, _last_rejected_at


def reset_rejection_stats() -> None:
    """Clear the in-memory counters (tests)."""
    global _rejected_since_start, _last_rejected_at
    _rejected_since_start = 0
    _last_rejected_at = None


def status() -> dict:
    """Snapshot for the Settings n8n panel."""
    settings = load_settings().get("n8n_auth") or {}
    count, last = rejection_stats()
    return {
        "mode": get_mode(),
        "enforced_since": settings.get("enforced_since"),
        "hatch_active": hatch_active(),
        "token_source": n8n_token_source(),
        "rejected_since_start": count,
        "last_rejected_at": last,
    }
