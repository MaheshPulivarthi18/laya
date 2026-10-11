# Copyright 2026 Aayush Chawla
# SPDX-License-Identifier: Apache-2.0

"""The n8n token: resolution at startup, the route table that accepts it,
log/enforce staging, and the readiness check that switches enforcement on.

This file is excluded from the conftest auth bypass, so requests here go
through the real `require_engine_auth`.
"""

import os
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from laya.main import app
from laya.security import keychain, n8n_auth
from laya.security.keychain import (
    N8N_TOKEN_ENV,
    ensure_n8n_token,
    get_n8n_token,
    store_engine_token,
    store_n8n_token,
)

APP_TOKEN = "lyae_test_app_token"
N8N_TOKEN = "lyan_test_n8n_token"


@pytest.fixture(autouse=True)
def tokens(monkeypatch, tmp_path):
    """Known app and n8n tokens, no pinned state, isolated settings.json, log mode."""
    monkeypatch.setattr(keychain, "_process_engine_token", None)
    monkeypatch.setattr(keychain, "_process_n8n_token", None)
    monkeypatch.setattr(keychain, "_n8n_token_source", None)
    monkeypatch.delenv(N8N_TOKEN_ENV, raising=False)
    monkeypatch.delenv(n8n_auth.HATCH_ENV, raising=False)
    store_engine_token(APP_TOKEN)
    store_n8n_token(N8N_TOKEN)
    n8n_auth.reset_rejection_stats()

    import laya.config as config
    settings_file = tmp_path / "settings.json"
    monkeypatch.setattr(config, "LAYA_CONFIG_FILE", settings_file)
    config.save_settings(config.load_settings())
    yield


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _set_mode(mode: str) -> None:
    import laya.config as config
    settings = config.load_settings()
    settings["n8n_auth"] = {"mode": mode, "enforced_since": None}
    config.save_settings(settings)


# ---------------------------------------------------------------------------
# Token resolution
# ---------------------------------------------------------------------------

def test_env_token_wins_is_pinned_and_removed_from_environment(monkeypatch):
    monkeypatch.setenv(N8N_TOKEN_ENV, "env_n8n_token")
    assert ensure_n8n_token() == "env_n8n_token"
    assert N8N_TOKEN_ENV not in os.environ
    assert get_n8n_token() == "env_n8n_token"
    assert keychain.n8n_token_source() == "env"
    # Resolving again keeps the pinned token even though the variable is gone.
    assert ensure_n8n_token() == "env_n8n_token"


def test_keychain_token_is_used_without_env():
    assert ensure_n8n_token() == N8N_TOKEN
    assert keychain.n8n_token_source() == "keychain"


def test_minted_token_is_pinned_when_keychain_write_fails(monkeypatch):
    keychain.delete_n8n_token()
    monkeypatch.setattr(keychain, "store_n8n_token", lambda token: False)
    token = ensure_n8n_token()
    assert token
    assert get_n8n_token() == token
    assert keychain.n8n_token_source() == "memory"


# ---------------------------------------------------------------------------
# Route table: the four n8n routes accept either credential
# ---------------------------------------------------------------------------

EVENT = {
    "event_id": "evt_n8n_auth_1",
    "timestamp": "2026-02-22T14:30:00Z",
    "source": {"platform": "jira", "raw_event_type": "issue_created"},
    "actor": {"name": "Bot", "email": "bot@example.com"},
    "subject": {"type": "ticket", "id": "TEST-1", "title": "Test"},
    "content": {"body": "Test body"},
}
INGESTION_ERROR = {
    "workflow_id": "wf_test_123",
    "error_message": "Network timeout to source",
    "occurred_at": "2026-02-22T14:30:00Z",
}


async def _call_n8n_route(client: AsyncClient, route: str, headers: dict):
    if route == "events":
        return await client.post("/events", json=EVENT, headers=headers)
    if route == "ingestion-errors":
        return await client.post("/ingestion-errors", json=INGESTION_ERROR, headers=headers)
    if route == "repos":
        return await client.get("/repos?platform=github", headers=headers)
    if route == "metadata":
        return await client.get("/metadata/slack-channels:wf_missing", headers=headers)
    raise AssertionError(route)


OK_STATUSES = {"events": 202, "ingestion-errors": 202, "repos": 200, "metadata": 200}
N8N_ROUTE_NAMES = ["events", "ingestion-errors", "repos", "metadata"]


@pytest.mark.asyncio
@pytest.mark.parametrize("route", N8N_ROUTE_NAMES)
async def test_app_bearer_is_accepted(db, route):
    async with _client() as client:
        resp = await _call_n8n_route(client, route, {"Authorization": f"Bearer {APP_TOKEN}"})
    assert resp.status_code == OK_STATUSES[route]


@pytest.mark.asyncio
@pytest.mark.parametrize("route", N8N_ROUTE_NAMES)
async def test_n8n_header_is_accepted(db, route):
    async with _client() as client:
        resp = await _call_n8n_route(client, route, {n8n_auth.HEADER_NAME: N8N_TOKEN})
    assert resp.status_code == OK_STATUSES[route]
    assert n8n_auth.rejection_stats()[0] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("route", N8N_ROUTE_NAMES)
async def test_missing_token_proceeds_and_is_counted_in_log_mode(db, route):
    _set_mode("log")
    async with _client() as client:
        resp = await _call_n8n_route(client, route, {})
    assert resp.status_code == OK_STATUSES[route]
    count, last = n8n_auth.rejection_stats()
    assert count == 1
    assert last


@pytest.mark.asyncio
@pytest.mark.parametrize("route", N8N_ROUTE_NAMES)
async def test_missing_or_wrong_token_is_rejected_in_enforce_mode(db, route):
    _set_mode("enforce")
    async with _client() as client:
        missing = await _call_n8n_route(client, route, {})
        wrong = await _call_n8n_route(client, route, {n8n_auth.HEADER_NAME: "nope"})
    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert "n8n token" in missing.json()["detail"]
    assert n8n_auth.rejection_stats()[0] == 2


@pytest.mark.asyncio
async def test_n8n_token_grants_nothing_on_other_routes(db):
    _set_mode("enforce")
    headers = {n8n_auth.HEADER_NAME: N8N_TOKEN}
    async with _client() as client:
        assert (await client.get("/settings", headers=headers)).status_code == 401
        assert (await client.put("/repos", json={"repos": []}, headers=headers)).status_code == 401
        assert (await client.get("/metadata", headers=headers)).status_code == 401
        assert (await client.get("/events/dead", headers=headers)).status_code == 401
        assert (await client.get("/ingestion-errors", headers=headers)).status_code == 401
        anon = await client.put(
            "/metadata/slack-channels:wf_1", json={"value": {}}, headers=headers,
        )
        assert anon.status_code == 401


@pytest.mark.asyncio
async def test_hatch_forces_log_mode(db, monkeypatch):
    _set_mode("enforce")
    monkeypatch.setenv(n8n_auth.HATCH_ENV, "off")
    assert n8n_auth.get_mode() == "log"
    assert n8n_auth.status()["hatch_active"] is True
    async with _client() as client:
        resp = await _call_n8n_route(client, "events", {})
    assert resp.status_code == 202


@pytest.mark.asyncio
async def test_non_ascii_header_is_401_not_500(db):
    _set_mode("enforce")
    async with _client() as client:
        resp = await client.post(
            "/events", json=EVENT, headers={n8n_auth.HEADER_NAME.encode(): "tok\xe9n".encode("latin-1")},
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_vendor_oauth_callback_stays_exempt(db):
    _set_mode("enforce")
    async with _client() as client:
        resp = await client.get("/egress/connections/oauth/callback")
    assert resp.status_code != 401


# ---------------------------------------------------------------------------
# Readiness: log -> enforce, once, never back
# ---------------------------------------------------------------------------

import json

from laya.integrations import n8n_bootstrap as nb


@pytest.fixture
def workflows(monkeypatch, tmp_path):
    """A bundled template set (one ingestion template + the error handler) and an empty version record."""
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir()
    (wf_dir / "jira-ingestion.json").write_text(json.dumps(
        {"name": "Laya - Jira Ingestion", "meta": {"laya_version": "2"}, "nodes": []}))
    (wf_dir / nb._ERROR_HANDLER_FILENAME).write_text(json.dumps(
        {"name": nb._ERROR_HANDLER_NAME, "meta": {"laya_version": "5"}, "nodes": []}))
    versions_file = tmp_path / "workflow_versions.json"
    monkeypatch.setattr(nb, "WORKFLOWS_DIR", wf_dir)
    monkeypatch.setattr(nb, "_VERSIONS_FILE", versions_file)
    return versions_file


def _token_from(monkeypatch, source: str) -> None:
    monkeypatch.setattr(keychain, "_n8n_token_source", source)


async def _add_clone(db, error=None):
    await db.execute(
        "INSERT INTO sources (source_id, name, platform, workflow_id, space_id, source_type, "
        "connection_id, workflow_update_error) VALUES ('src_1', 'Jira', 'jira', 'wf_1', 'default', "
        "'ingestion', 'conn_1', ?)",
        (error,),
    )
    await db.commit()


def _write_versions(versions_file, *, template="2", handler="5", handler_id="eh_1"):
    versions_file.write_text(json.dumps({
        "Laya - Jira Ingestion": template,
        nb._ERROR_HANDLER_NAME: handler,
        nb._ERROR_HANDLER_ID_KEY: handler_id,
    }))


@pytest.mark.asyncio
async def test_fresh_install_enforces_immediately(db, workflows, monkeypatch):
    _token_from(monkeypatch, "env")
    result = await n8n_auth.evaluate_readiness()
    assert result == {"mode": "enforce", "unmet": []}
    assert n8n_auth.get_mode() == "enforce"
    assert n8n_auth.status()["enforced_since"]


@pytest.mark.asyncio
async def test_token_not_from_launcher_blocks_enforcement(db, workflows, monkeypatch):
    _token_from(monkeypatch, "keychain")
    result = await n8n_auth.evaluate_readiness()
    assert result["mode"] == "log"
    assert any("LAYA_N8N_TOKEN" in u for u in result["unmet"])


@pytest.mark.asyncio
async def test_stale_template_and_handler_block_until_pushed(db, workflows, monkeypatch):
    _token_from(monkeypatch, "env")
    await _add_clone(db)
    _write_versions(workflows, template="1", handler="4")
    result = await n8n_auth.evaluate_readiness()
    assert result["mode"] == "log"
    assert any("Laya - Jira Ingestion" in u for u in result["unmet"])
    assert any("error handler" in u for u in result["unmet"])

    _write_versions(workflows)
    result = await n8n_auth.evaluate_readiness()
    assert result == {"mode": "enforce", "unmet": []}


@pytest.mark.asyncio
async def test_flagged_clone_blocks_enforcement(db, workflows, monkeypatch):
    _token_from(monkeypatch, "env")
    await _add_clone(db, error="n8n rejected the update (HTTP 400)")
    _write_versions(workflows)
    result = await n8n_auth.evaluate_readiness()
    assert result["mode"] == "log"
    assert any("failed to update" in u for u in result["unmet"])


@pytest.mark.asyncio
async def test_enforcement_never_reverts(db, workflows, monkeypatch):
    _token_from(monkeypatch, "env")
    _write_versions(workflows)
    assert (await n8n_auth.evaluate_readiness())["mode"] == "enforce"
    await _add_clone(db, error="Workflow no longer exists in n8n")
    _token_from(monkeypatch, "keychain")
    assert (await n8n_auth.evaluate_readiness()) == {"mode": "enforce", "unmet": []}
    assert n8n_auth.get_mode() == "enforce"


@pytest.mark.asyncio
async def test_hatch_does_not_change_the_persisted_mode(db, workflows, monkeypatch):
    _token_from(monkeypatch, "env")
    monkeypatch.setenv(n8n_auth.HATCH_ENV, "off")
    assert (await n8n_auth.evaluate_readiness())["mode"] == "log"
    import laya.config as config
    assert config.load_settings()["n8n_auth"]["mode"] == "log"


@pytest.mark.asyncio
async def test_status_report_includes_readiness_and_flags(db, workflows, monkeypatch):
    _token_from(monkeypatch, "keychain")
    await _add_clone(db, error="boom")
    await nb._set_error_handler_update_error("handler boom")
    report = await n8n_auth.status_report()
    assert report["mode"] == "log"
    assert report["token_source"] == "keychain"
    assert report["flagged_clones"] == 1
    assert report["error_handler_update_error"] == "handler boom"
    assert report["unmet"]


@pytest.mark.asyncio
async def test_import_workflows_runs_the_readiness_check(db, workflows, monkeypatch):
    from unittest.mock import AsyncMock
    _token_from(monkeypatch, "env")
    with patch.object(nb, "get_api_key", return_value="k"), \
         patch.object(nb, "_ensure_error_handler_workflow", new=AsyncMock(return_value="eh_1")):
        await nb.import_workflows("http://localhost:45678")
    # No clones: the version record now exists, and the handler is not recorded
    # at the bundled version because its deployment was mocked away.
    result = await n8n_auth.evaluate_readiness()
    assert result["mode"] == "log"
    assert any("error handler" in u for u in result["unmet"])
