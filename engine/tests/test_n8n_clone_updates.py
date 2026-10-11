# Copyright 2026 Aayush Chawla
# SPDX-License-Identifier: Apache-2.0

"""Per-clone workflow update tracking: failure reasons, flagged-row retry,
version bookkeeping, and the shared platform-credential matcher."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from laya.integrations import n8n_bootstrap as nb

BASE = "http://localhost:45678"
KEY = "test-key"


def _response(status_code: int, payload=None, text: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload if payload is not None else {}
    resp.text = text
    return resp


def _client(get=None, put=None, post=None) -> MagicMock:
    client = MagicMock()
    client.get = AsyncMock(return_value=get or _response(200, {"active": False, "nodes": []}))
    client.put = AsyncMock(return_value=put or _response(200, {}))
    client.post = AsyncMock(return_value=post or _response(200, {}))
    return client


async def _insert_clone(db, source_id="src_1", wf_id="wf_1", platform="jira",
                        source_type="ingestion", error=None):
    await db.execute(
        "INSERT INTO egress_connections (connection_id, platform, name, n8n_credential_id, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, 'now', 'now')",
        ("conn_1", platform, "Work", "cred_1"),
    )
    await db.execute(
        "INSERT INTO sources (source_id, name, platform, workflow_id, space_id, source_type, "
        "connection_id, workflow_update_error) VALUES (?, ?, ?, ?, 'default', ?, 'conn_1', ?)",
        (source_id, "Laya Jira - Work (Ingestion)", platform, wf_id, source_type, error),
    )
    await db.commit()


async def _row(db, source_id="src_1"):
    rows = await db.execute_fetchall(
        "SELECT * FROM sources WHERE source_id = ?", (source_id,)
    )
    return rows[0]


@pytest.mark.asyncio
class TestUpdateWorkflowReasons:
    async def test_success_returns_ok_and_no_reason(self):
        with patch.object(nb, "get_client", return_value=_client()):
            assert await nb._update_workflow(BASE, KEY, "wf_1", {"nodes": []}) == (True, None)

    async def test_missing_workflow(self):
        with patch.object(nb, "get_client", return_value=_client(get=_response(404))):
            ok, reason = await nb._update_workflow(BASE, KEY, "wf_1", {"nodes": []})
        assert ok is False
        assert reason == nb.REASON_WORKFLOW_MISSING

    async def test_put_rejected_includes_status_and_detail(self):
        client = _client(put=_response(400, text="settings must be an object"))
        with patch.object(nb, "get_client", return_value=client):
            ok, reason = await nb._update_workflow(BASE, KEY, "wf_1", {"nodes": []})
        assert ok is False
        assert reason.startswith("n8n rejected the update (HTTP 400")
        assert "settings must be an object" in reason

    async def test_transport_error_is_unreachable(self):
        client = _client()
        client.get = AsyncMock(side_effect=RuntimeError("boom"))
        with patch.object(nb, "get_client", return_value=client):
            ok, reason = await nb._update_workflow(BASE, KEY, "wf_1", {"nodes": []})
        assert (ok, reason) == (False, nb.REASON_N8N_UNREACHABLE)


@pytest.mark.asyncio
class TestUpdateClone:
    def _ctx(self):
        return nb.PropagationContext(
            base_url=BASE, api_key=KEY, template_data_map={}, type_to_template={},
            conn_cred_map={"conn_1": ("cred_1", "Work")}, error_handler_id="eh_1",
        )

    async def test_failure_is_recorded_on_the_row(self, db):
        await _insert_clone(db)
        row = await _row(db)
        with patch.object(nb, "_update_workflow", new=AsyncMock(return_value=(False, "nope"))):
            ok, reason = await nb.update_clone(row, {"nodes": []}, self._ctx())
        assert (ok, reason) == (False, "nope")
        after = await _row(db)
        assert after["workflow_update_error"] == "nope"
        assert after["workflow_update_failed_at"] is not None

    async def test_success_clears_a_previous_failure(self, db):
        await _insert_clone(db, error="old failure")
        row = await _row(db)
        with patch.object(nb, "_update_workflow", new=AsyncMock(return_value=(True, None))):
            ok, _ = await nb.update_clone(row, {"nodes": []}, self._ctx())
        assert ok
        after = await _row(db)
        assert after["workflow_update_error"] is None
        assert after["workflow_update_failed_at"] is None

    async def test_pushes_template_with_clone_name_handler_and_credential(self, db):
        await _insert_clone(db)
        row = await _row(db)
        template = {
            "name": "Laya - Jira Ingestion",
            "nodes": [{"name": "Jira", "type": "n8n-nodes-base.jiraTrigger",
                       "credentials": {"jiraSoftwareCloudApi": {"id": "jiraSoftwareCloudApi", "name": "x"}}}],
        }
        update = AsyncMock(return_value=(True, None))
        with patch.object(nb, "_update_workflow", new=update):
            await nb.update_clone(row, template, self._ctx())
        pushed = update.call_args.args[3]
        assert pushed["name"] == "Laya Jira - Work (Ingestion)"
        assert pushed["settings"]["errorWorkflow"] == "eh_1"
        assert pushed["nodes"][0]["credentials"]["jiraSoftwareCloudApi"] == {"id": "cred_1", "name": "Work"}
        assert template["nodes"][0]["credentials"]["jiraSoftwareCloudApi"]["id"] == "jiraSoftwareCloudApi"

    async def test_unexpected_exception_is_recorded_not_raised(self, db):
        await _insert_clone(db)
        row = await _row(db)
        with patch.object(nb, "_update_workflow", new=AsyncMock(side_effect=RuntimeError("x"))):
            ok, reason = await nb.update_clone(row, {"nodes": []}, self._ctx())
        assert (ok, reason) == (False, nb.REASON_N8N_UNREACHABLE)
        assert (await _row(db))["workflow_update_error"] == nb.REASON_N8N_UNREACHABLE


@pytest.mark.asyncio
class TestPropagateToClones:
    def _templates(self, tmp_path):
        (tmp_path / "jira-ingestion.json").write_text(json.dumps(
            {"name": "Laya - Jira Ingestion", "meta": {"laya_version": "2"}, "nodes": []}))
        return tmp_path

    async def test_flagged_clone_is_retried_without_a_version_change(self, db, tmp_path):
        await _insert_clone(db, error="earlier failure")
        update = AsyncMock(return_value=(True, None))
        with patch.object(nb, "WORKFLOWS_DIR", self._templates(tmp_path)), \
             patch.object(nb, "_get_error_handler_id", return_value=None), \
             patch.object(nb, "_update_workflow", new=update):
            updated = await nb._propagate_to_clones(BASE, KEY, [])
        assert updated == 1
        assert (await _row(db))["workflow_update_error"] is None

    async def test_unchanged_unflagged_clone_is_skipped(self, db, tmp_path):
        await _insert_clone(db)
        update = AsyncMock(return_value=(True, None))
        with patch.object(nb, "WORKFLOWS_DIR", self._templates(tmp_path)), \
             patch.object(nb, "_get_error_handler_id", return_value=None), \
             patch.object(nb, "_update_workflow", new=update):
            updated = await nb._propagate_to_clones(BASE, KEY, [])
        assert updated == 0
        update.assert_not_called()

    async def test_force_pushes_every_clone(self, db, tmp_path):
        await _insert_clone(db)
        update = AsyncMock(return_value=(True, None))
        with patch.object(nb, "WORKFLOWS_DIR", self._templates(tmp_path)), \
             patch.object(nb, "_get_error_handler_id", return_value=None), \
             patch.object(nb, "_update_workflow", new=update):
            updated = await nb._propagate_to_clones(BASE, KEY, [], force=True)
        assert updated == 1


@pytest.mark.asyncio
class TestImportWorkflowsVersionBookkeeping:
    def _setup(self, tmp_path):
        wf_dir = tmp_path / "workflows"
        wf_dir.mkdir()
        (wf_dir / "jira-ingestion.json").write_text(json.dumps(
            {"name": "Laya - Jira Ingestion", "meta": {"laya_version": "2"}, "nodes": []}))
        return wf_dir, tmp_path / "workflow_versions.json"

    async def test_versions_saved_after_propagation_returns(self, tmp_path):
        wf_dir, versions_file = self._setup(tmp_path)
        with patch.object(nb, "WORKFLOWS_DIR", wf_dir), \
             patch.object(nb, "_VERSIONS_FILE", versions_file), \
             patch.object(nb, "get_api_key", return_value=KEY), \
             patch.object(nb, "_ensure_error_handler_workflow", new=AsyncMock(return_value="eh")), \
             patch.object(nb, "_propagate_to_clones", new=AsyncMock(return_value=0)):
            await nb.import_workflows(BASE)
        assert json.loads(versions_file.read_text())["Laya - Jira Ingestion"] == "2"

    async def test_versions_not_saved_when_propagation_raises(self, tmp_path):
        wf_dir, versions_file = self._setup(tmp_path)
        with patch.object(nb, "WORKFLOWS_DIR", wf_dir), \
             patch.object(nb, "_VERSIONS_FILE", versions_file), \
             patch.object(nb, "get_api_key", return_value=KEY), \
             patch.object(nb, "_ensure_error_handler_workflow", new=AsyncMock(return_value="eh")), \
             patch.object(nb, "_propagate_to_clones", new=AsyncMock(side_effect=RuntimeError("db"))):
            await nb.import_workflows(BASE)
        assert not versions_file.exists()


@pytest.mark.asyncio
class TestErrorHandlerVersionBookkeeping:
    def _setup(self, tmp_path):
        wf_dir = tmp_path / "workflows"
        wf_dir.mkdir()
        (wf_dir / nb._ERROR_HANDLER_FILENAME).write_text(json.dumps(
            {"name": nb._ERROR_HANDLER_NAME, "meta": {"laya_version": "2"}, "nodes": []}))
        versions_file = tmp_path / "workflow_versions.json"
        versions_file.write_text(json.dumps({nb._ERROR_HANDLER_ID_KEY: "eh_1", nb._ERROR_HANDLER_NAME: "1"}))
        return wf_dir, versions_file

    async def test_failed_update_keeps_old_version_and_records_error(self, db, tmp_path):
        wf_dir, versions_file = self._setup(tmp_path)
        with patch.object(nb, "WORKFLOWS_DIR", wf_dir), \
             patch.object(nb, "_VERSIONS_FILE", versions_file), \
             patch.object(nb, "_get_existing_workflows",
                          new=AsyncMock(return_value={nb._ERROR_HANDLER_NAME: {"id": "eh_1"}})), \
             patch.object(nb, "_update_workflow", new=AsyncMock(return_value=(False, "HTTP 500"))):
            handler_id = await nb._ensure_error_handler_workflow(BASE, KEY)
        assert handler_id == "eh_1"
        assert json.loads(versions_file.read_text())[nb._ERROR_HANDLER_NAME] == "1"
        assert await nb.get_error_handler_update_error() == "HTTP 500"

    async def test_successful_update_saves_version_and_clears_error(self, db, tmp_path):
        wf_dir, versions_file = self._setup(tmp_path)
        await nb._set_error_handler_update_error("stale")
        with patch.object(nb, "WORKFLOWS_DIR", wf_dir), \
             patch.object(nb, "_VERSIONS_FILE", versions_file), \
             patch.object(nb, "_get_existing_workflows",
                          new=AsyncMock(return_value={nb._ERROR_HANDLER_NAME: {"id": "eh_1"}})), \
             patch.object(nb, "_update_workflow", new=AsyncMock(return_value=(True, None))):
            await nb._ensure_error_handler_workflow(BASE, KEY)
        assert json.loads(versions_file.read_text())[nb._ERROR_HANDLER_NAME] == "2"
        assert await nb.get_error_handler_update_error() is None


class TestInjectPlatformCredential:
    def test_gmail_binds_native_trigger_and_http_nodes(self):
        nodes = [
            {"name": "Trigger", "type": "n8n-nodes-base.gmailTrigger", "parameters": {}},
            {"name": "Archive", "type": "n8n-nodes-base.httpRequest",
             "parameters": {"nodeCredentialType": "gmailOAuth2"}},
            {"name": "POST to Laya Engine", "type": "n8n-nodes-base.httpRequest", "parameters": {}},
        ]
        assert nb.inject_platform_credential(nodes, "gmail", "c1", "Me") == 2
        assert nodes[0]["credentials"]["gmailOAuth2"] == {"id": "c1", "name": "Me"}
        assert nodes[1]["credentials"]["gmailOAuth2"] == {"id": "c1", "name": "Me"}
        assert "credentials" not in nodes[2]

    def test_jira_binds_placeholder_slot(self):
        nodes = [{"name": "Jira", "type": "n8n-nodes-base.jira", "parameters": {},
                  "credentials": {"jiraSoftwareCloudApi": {"id": "jiraSoftwareCloudApi", "name": "Jira"}}}]
        assert nb.inject_platform_credential(nodes, "jira", "c2", "Work") == 1
        assert nodes[0]["credentials"]["jiraSoftwareCloudApi"]["id"] == "c2"

    def test_bitbucket_server_never_sprays_across_http_nodes(self):
        nodes = [
            {"name": "List PRs", "type": "n8n-nodes-base.httpRequest",
             "parameters": {"authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth"},
             "credentials": {"httpHeaderAuth": {"id": "REPLACED_AT_CLONE", "name": "Bitbucket Server"}}},
            {"name": "POST to Laya Engine", "type": "n8n-nodes-base.httpRequest", "parameters": {}},
            {"name": "Code", "type": "n8n-nodes-base.code", "parameters": {}},
        ]
        assert nb.inject_platform_credential(nodes, "bitbucket_server", "c3", "Srv") == 1
        assert nodes[0]["credentials"]["httpHeaderAuth"] == {"id": "c3", "name": "Srv"}
        assert "credentials" not in nodes[1]
        assert "credentials" not in nodes[2]

    def test_unknown_platform_binds_nothing(self):
        nodes = [{"name": "X", "type": "n8n-nodes-base.httpRequest", "parameters": {}}]
        assert nb.inject_platform_credential(nodes, "nope", "c", "n") == 0


@pytest.mark.asyncio
class TestUpdateSourceWorkflowEndpoint:
    async def _post(self, source_id: str):
        from laya.main import app
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(f"/sources/{source_id}/update-workflow")

    async def test_unknown_source_is_404(self, db):
        resp = await self._post("src_missing")
        assert resp.status_code == 404

    async def test_returns_refreshed_row(self, db, tmp_path):
        await _insert_clone(db, error="earlier failure")
        (tmp_path / "jira-ingestion.json").write_text(json.dumps(
            {"name": "Laya - Jira Ingestion", "meta": {"laya_version": "2"}, "nodes": []}))
        with patch.object(nb, "WORKFLOWS_DIR", tmp_path), \
             patch.object(nb, "_get_error_handler_id", return_value=None), \
             patch.object(nb, "_update_workflow", new=AsyncMock(return_value=(True, None))), \
             patch("laya.security.keychain.get_api_key", return_value=KEY), \
             patch("laya.config.get_n8n_config", return_value={"base_url": BASE}):
            resp = await self._post("src_1")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["source_id"] == "src_1"
        assert body["workflow_update_error"] is None

    async def test_failure_reason_is_returned(self, db, tmp_path):
        await _insert_clone(db)
        (tmp_path / "jira-ingestion.json").write_text(json.dumps(
            {"name": "Laya - Jira Ingestion", "meta": {"laya_version": "2"}, "nodes": []}))
        with patch.object(nb, "WORKFLOWS_DIR", tmp_path), \
             patch.object(nb, "_get_error_handler_id", return_value=None), \
             patch.object(nb, "_update_workflow",
                          new=AsyncMock(return_value=(False, nb.REASON_WORKFLOW_MISSING))), \
             patch("laya.security.keychain.get_api_key", return_value=KEY), \
             patch("laya.config.get_n8n_config", return_value={"base_url": BASE}):
            resp = await self._post("src_1")
        assert resp.status_code == 200
        assert resp.json()["workflow_update_error"] == nb.REASON_WORKFLOW_MISSING
        assert resp.json()["workflow_update_failed_at"]
