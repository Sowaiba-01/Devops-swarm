"""HTTP surface: pagination, filtering, validation, error shape."""

from __future__ import annotations

import datetime as dt

import pytest

from app.db.models import utcnow


class TestHealth:
    async def test_health_reports_real_database_state(self, client):
        response = await client.get("/health")
        assert response.status_code == 200
        body = response.json()
        # The old handler returned a hardcoded "ok" regardless of the database.
        assert body["database"] == "up"
        assert body["status"] == "ok"
        assert "runs_in_flight" in body

    async def test_liveness_does_no_io(self, client):
        assert (await client.get("/health/live")).json() == {"status": "alive"}

    async def test_every_response_carries_a_request_id(self, client):
        response = await client.get("/health/live")
        assert response.headers.get("X-Request-ID")

    async def test_security_headers_are_present(self, client):
        headers = (await client.get("/health/live")).headers
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["X-Frame-Options"] == "DENY"


class TestListRuns:
    async def test_empty_database_returns_an_empty_page(self, client):
        body = (await client.get("/runs")).json()
        assert body["runs"] == []
        assert body["page"]["total"] == 0

    async def test_total_counts_all_matches_not_just_the_page(self, client, make_run):
        for i in range(25):
            await make_run(id=f"{i:08d}-0000-0000-0000-000000000000", issue_number=i)

        body = (await client.get("/runs?limit=10")).json()
        assert len(body["runs"]) == 10
        # Previously this reported len(page) — the counter stuck at the page size.
        assert body["page"]["total"] == 25
        assert body["page"]["has_more"] is True

    async def test_the_last_page_reports_no_more(self, client, make_run):
        for i in range(5):
            await make_run(id=f"{i:08d}-0000-0000-0000-000000000000", issue_number=i)
        body = (await client.get("/runs?limit=10")).json()
        assert body["page"]["has_more"] is False

    async def test_results_are_newest_first(self, client, make_run):
        old = utcnow() - dt.timedelta(hours=2)
        await make_run(id="aaaaaaaa-0000-0000-0000-000000000000", issue_number=1, created_at=old)
        await make_run(id="bbbbbbbb-0000-0000-0000-000000000000", issue_number=2)
        runs = (await client.get("/runs")).json()["runs"]
        assert runs[0]["issue_number"] == 2

    async def test_status_filter_applies_to_the_count_as_well(self, client, make_run):
        await make_run(id="aaaaaaaa-0000-0000-0000-000000000000", status="success")
        await make_run(id="bbbbbbbb-0000-0000-0000-000000000000", status="failed")
        await make_run(id="cccccccc-0000-0000-0000-000000000000", status="failed")

        body = (await client.get("/runs?status=failed")).json()
        assert body["page"]["total"] == 2
        assert {r["status"] for r in body["runs"]} == {"failed"}

    async def test_an_unknown_status_is_rejected(self, client):
        response = await client.get("/runs?status=bogus")
        assert response.status_code == 422

    @pytest.mark.parametrize("limit", [0, -1, 10_000])
    async def test_limit_is_bounded(self, client, limit):
        # An unbounded limit is a trivial memory-exhaustion vector.
        assert (await client.get(f"/runs?limit={limit}")).status_code == 422

    async def test_repo_filter(self, client, make_run):
        await make_run(
            id="aaaaaaaa-0000-0000-0000-000000000000", repo_owner="acme", repo_name="api"
        )
        await make_run(
            id="bbbbbbbb-0000-0000-0000-000000000000", repo_owner="other", repo_name="app"
        )
        body = (await client.get("/runs?repo=acme/api")).json()
        assert body["page"]["total"] == 1


class TestRunDetail:
    async def test_a_missing_run_is_a_404_with_a_request_id(self, client):
        response = await client.get("/runs/99999999-9999-9999-9999-999999999999")
        assert response.status_code == 404
        assert response.json()["request_id"]

    async def test_detail_includes_the_error_message(self, client, make_run):
        await make_run(status="failed", error_message="boom")
        response = await client.get("/runs/11111111-1111-1111-1111-111111111111")
        assert response.json()["error_message"] == "boom"

    async def test_timestamps_carry_a_timezone_offset(self, client, make_run):
        await make_run()
        created = (await client.get("/runs/11111111-1111-1111-1111-111111111111")).json()[
            "created_at"
        ]
        # Naive timestamps are parsed as local time by the browser, which made
        # every duration in the dashboard wrong by the client's UTC offset.
        assert created.endswith("Z") or "+" in created[10:]


class TestStats:
    async def test_counts_come_from_the_database_not_a_page_of_results(self, client, make_run):
        for i in range(3):
            await make_run(id=f"{i:08d}-0000-0000-0000-000000000000", status="success")
        await make_run(id="ffffffff-0000-0000-0000-000000000000", status="failed")

        body = (await client.get("/runs/stats")).json()
        assert body["total"] == 4
        assert body["success"] == 3
        assert body["success_rate"] == 75.0

    async def test_success_rate_is_zero_rather_than_a_division_error(self, client, make_run):
        await make_run(status="running")
        assert (await client.get("/runs/stats")).json()["success_rate"] == 0.0


class TestLogs:
    async def test_logs_for_a_missing_run_are_a_404(self, client):
        response = await client.get("/runs/99999999-9999-9999-9999-999999999999/logs")
        assert response.status_code == 404

    async def test_logs_replay_in_sequence_order(self, client, make_run):
        from app.db import repository

        run = await make_run()
        for i in range(5):
            await repository.append_log(
                run_id=run.id, agent="coder", log_type="thought", content=f"step {i}"
            )
        body = (await client.get(f"/runs/{run.id}/logs")).json()
        assert [entry["seq"] for entry in body["logs"]] == [1, 2, 3, 4, 5]
        assert body["last_seq"] == 5

    async def test_after_seq_returns_only_newer_events(self, client, make_run):
        from app.db import repository

        run = await make_run()
        for i in range(5):
            await repository.append_log(
                run_id=run.id, agent="coder", log_type="thought", content=f"step {i}"
            )
        body = (await client.get(f"/runs/{run.id}/logs?after_seq=3")).json()
        assert [entry["seq"] for entry in body["logs"]] == [4, 5]

    async def test_persisted_log_content_is_redacted(self, client, make_run):
        from app.core.redaction import register_secret
        from app.db import repository

        run = await make_run()
        register_secret("ghs_leakedtokenvalue1234567890")
        await repository.append_log(
            run_id=run.id,
            agent="coder",
            log_type="tool_result",
            content="remote: https://x-access-token:ghs_leakedtokenvalue1234567890@github.com/a/b",
        )
        body = (await client.get(f"/runs/{run.id}/logs")).json()
        assert "ghs_leakedtokenvalue1234567890" not in body["logs"][0]["content"]


class TestTriggerValidation:
    async def test_a_malformed_repo_is_rejected(self, client):
        response = await client.post(
            "/trigger",
            json={"repo": "not-a-repo", "issue_number": 1, "issue_title": "t"},
        )
        assert response.status_code == 422

    async def test_shell_metacharacters_in_the_repo_are_rejected(self, client):
        response = await client.post(
            "/trigger",
            json={"repo": "owner/repo;rm -rf /", "issue_number": 1, "issue_title": "t"},
        )
        assert response.status_code == 422

    async def test_a_missing_title_is_rejected(self, client):
        response = await client.post("/trigger", json={"repo": "a/b", "issue_number": 1})
        assert response.status_code == 422

    async def test_a_non_positive_issue_number_is_rejected(self, client):
        response = await client.post(
            "/trigger", json={"repo": "a/b", "issue_number": 0, "issue_title": "t"}
        )
        assert response.status_code == 422

    async def test_validation_errors_name_the_offending_field(self, client):
        response = await client.post("/trigger", json={"repo": "a/b", "issue_number": 1})
        assert any(e["field"] == "issue_title" for e in response.json()["errors"])


class TestWebhookAuth:
    async def test_an_unsigned_delivery_is_rejected(self, client):
        response = await client.post("/webhook", json={"action": "opened"})
        assert response.status_code == 401

    async def test_a_forged_signature_is_rejected(self, client):
        response = await client.post(
            "/webhook",
            json={"action": "opened"},
            headers={"X-Hub-Signature-256": "sha256=" + "0" * 64, "X-GitHub-Event": "issues"},
        )
        assert response.status_code == 401
