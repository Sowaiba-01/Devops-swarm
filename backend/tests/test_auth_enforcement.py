"""
End-to-end checks that the trigger endpoint is actually gated.

`/trigger` spends the operator's GitHub credentials against whatever repository
it is handed. The unit tests cover the pieces; these drive the real HTTP stack
so a wiring mistake — a dependency dropped from the decorator, a router included
before the middleware — cannot pass silently.
"""

from __future__ import annotations

import pytest

from app.config import Settings


@pytest.fixture
def auth_required(monkeypatch):
    """Configure the running app as if it required an API key."""
    configured = Settings(
        API_KEYS="secret-key-one,secret-key-two",
        REPO_ALLOWLIST="octocat/hello-world",
        GITHUB_PAT="ghp_testtokentesttokentesttoken1234",
    )
    monkeypatch.setattr("app.core.security.settings", configured)
    monkeypatch.setattr("app.api.runs.settings", configured)
    return configured


BODY = {
    "repo": "octocat/hello-world",
    "issue_number": 1,
    "issue_title": "Fix the thing",
    "issue_body": "details",
}


class TestApiKeyGate:
    async def test_trigger_without_a_key_is_rejected(self, client, auth_required):
        response = await client.post("/trigger", json=BODY)
        assert response.status_code == 401
        assert response.headers.get("WWW-Authenticate") == "ApiKey"

    async def test_trigger_with_a_wrong_key_is_rejected(self, client, auth_required):
        response = await client.post("/trigger", json=BODY, headers={"X-API-Key": "guessed"})
        assert response.status_code == 401

    async def test_cancel_is_gated_too(self, client, auth_required, make_run):
        run = await make_run()
        response = await client.post(f"/runs/{run.id}/cancel")
        assert response.status_code == 401

    async def test_read_endpoints_stay_open(self, client, auth_required):
        # Reads are not credential-spending operations; gating them would break
        # the dashboard without improving the security posture.
        assert (await client.get("/runs")).status_code == 200
        assert (await client.get("/runs/stats")).status_code == 200

    async def test_no_run_is_recorded_when_authentication_fails(
        self, client, auth_required, session
    ):
        await client.post("/trigger", json=BODY)
        from app.db import repository

        _, total = await repository.list_runs(session, limit=10, offset=0)
        assert total == 0


class TestRepoAllowlistGate:
    async def test_a_repository_outside_the_allowlist_is_refused(self, client, auth_required):
        response = await client.post(
            "/trigger",
            json={**BODY, "repo": "attacker/private-repo"},
            headers={"X-API-Key": "secret-key-one"},
        )
        assert response.status_code == 403
        assert "REPO_ALLOWLIST" in response.json()["detail"]

    async def test_a_valid_key_and_allowlisted_repo_is_accepted(
        self, client, auth_required, monkeypatch
    ):
        # Stub the executor: acceptance is the contract under test, not whether
        # a real swarm run can reach GitHub.
        submitted: list[str] = []
        monkeypatch.setattr(
            "app.api.runs.executor.submit",
            lambda run_id, state, source="api": submitted.append(run_id),
        )

        response = await client.post("/trigger", json=BODY, headers={"X-API-Key": "secret-key-two"})
        assert response.status_code == 202
        payload = response.json()
        assert payload["status"] == "accepted"
        assert payload["stream_url"] == f"/ws/{payload['run_id']}"
        assert submitted == [payload["run_id"]]


class TestCancelSemantics:
    async def test_cancelling_a_finished_run_conflicts(self, client, make_run):
        run = await make_run(status="success")
        response = await client.post(f"/runs/{run.id}/cancel")
        assert response.status_code == 409

    async def test_cancelling_a_live_run_marks_it_cancelled(self, client, make_run):
        run = await make_run(status="running")
        response = await client.post(f"/runs/{run.id}/cancel")
        assert response.status_code == 200
        assert response.json()["status"] == "cancelled"
