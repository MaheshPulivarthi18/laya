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
