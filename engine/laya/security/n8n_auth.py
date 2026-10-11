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
import json
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


# ---------------------------------------------------------------------------
# Readiness: when is it safe to enforce?
# ---------------------------------------------------------------------------

# Human-readable reasons enforcement is still off, shown on the Settings panel.
_last_unmet: list[str] = []


async def unmet_conditions() -> list[str]:
    """Return what still blocks enforcement; empty means every workflow carries the token.

    Conditions (all must hold):
    - the engine's token came from the launcher environment, which is the
      only case where n8n is known to hold the same value;
    - the shared error handler is deployed at the bundled template version;
    - every ingestion template that has at least one clone is recorded at its
      bundled version, i.e. the header-sending version has been pushed;
    - no clone is flagged with a failed update.

    A fresh install (no clones and no version record) is ready as soon as the
    token condition holds: there is nothing deployed that could lose events.
    """
    from laya.db.sqlite import get_db
    from laya.integrations import n8n_bootstrap as nb

    unmet: list[str] = []
    if n8n_token_source() != "env":
        unmet.append(
            "The n8n token was not supplied by the launcher, so n8n may not have it "
            "(set LAYA_N8N_TOKEN on both the engine and n8n)."
        )

    db = await get_db()
    clone_rows = await db.execute_fetchall(
        """SELECT platform, source_type, workflow_update_error
           FROM sources WHERE connection_id IS NOT NULL AND workflow_id IS NOT NULL""",
    )
    versions = nb._load_deployed_versions()
    if not clone_rows and not versions:
        return unmet

    handler_version = nb.error_handler_bundled_version()
    if handler_version and (
        not versions.get(nb._ERROR_HANDLER_ID_KEY)
        or versions.get(nb._ERROR_HANDLER_NAME) != handler_version
    ):
        unmet.append("The shared error handler workflow is not at the bundled version yet.")

    bundled: dict[str, str | None] = {}
    if nb.WORKFLOWS_DIR.exists():
        for wf_file in nb.WORKFLOWS_DIR.glob("*.json"):
            try:
                data = json.loads(wf_file.read_text(encoding="utf-8"))
            except Exception:
                continue
            bundled[data.get("name", "")] = (data.get("meta") or {}).get("laya_version")

    from laya.integrations.platforms import PLATFORMS

    type_to_template: dict[tuple[str, str], str] = {}
    for platform_key, config in PLATFORMS.items():
        for wf_name in config.get("workflows", []):
            kind = "executor" if "executor" in wf_name.lower() else "ingestion"
            type_to_template[(platform_key, kind)] = wf_name

    stale: list[str] = []
    for row in clone_rows:
        if row["source_type"] != "ingestion":
            continue
        name = type_to_template.get((row["platform"], row["source_type"]))
        if name and name in bundled and versions.get(name) != bundled[name] and name not in stale:
            stale.append(name)
    if stale:
        unmet.append(
            "These templates have not been pushed to their clones yet: " + ", ".join(sorted(stale)) + "."
        )

    flagged = sum(1 for row in clone_rows if row["workflow_update_error"])
    if flagged:
        unmet.append(
            f"{flagged} workflow{'s' if flagged != 1 else ''} failed to update "
            "(see the workflow list below)."
        )
    return unmet


async def evaluate_readiness() -> dict:
    """Switch to `enforce` when nothing blocks it. Never switches back.

    Returns {"mode": ..., "unmet": [...]} for the caller's log or response.
    """
    global _last_unmet
    if hatch_active() or get_mode() == MODE_ENFORCE:
        _last_unmet = []
        return {"mode": get_mode(), "unmet": []}
    try:
        unmet = await unmet_conditions()
    except Exception as e:
        log.warning("n8n_auth_readiness_check_failed", error=str(e))
        return {"mode": MODE_LOG, "unmet": _last_unmet}
    _last_unmet = unmet
    if unmet:
        log.info("n8n_auth_not_ready", unmet=unmet)
        return {"mode": MODE_LOG, "unmet": unmet}
    set_enforced()
    return {"mode": MODE_ENFORCE, "unmet": []}


async def status_report() -> dict:
    """`status()` plus the live readiness picture, for the Settings n8n panel."""
    from laya.db.sqlite import get_db
    from laya.integrations.n8n_bootstrap import get_error_handler_update_error

    report = status()
    report["unmet"] = [] if report["mode"] == MODE_ENFORCE else await unmet_conditions()
    report["error_handler_update_error"] = await get_error_handler_update_error()
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT COUNT(*) AS n FROM sources WHERE workflow_update_error IS NOT NULL",
    )
    report["flagged_clones"] = rows[0]["n"] if rows else 0
    return report
