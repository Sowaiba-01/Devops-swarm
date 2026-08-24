"""
Authentication and authorization.

The /trigger endpoint spends the operator's GitHub credentials against an
arbitrary repository. Leaving it unauthenticated means anyone who can reach the
service can push branches and open pull requests as the operator. Two controls
apply: an API key on every mutating endpoint, and an allowlist of repositories
the swarm is permitted to touch.
"""

from __future__ import annotations

import hashlib
import hmac
import re

from fastapi import Depends, Header, HTTPException, Query, WebSocket, status

from app.config import settings

_REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")

UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Missing or invalid API key",
    headers={"WWW-Authenticate": "ApiKey"},
)


def _key_valid(candidate: str | None) -> bool:
    if not candidate:
        return False
    # compare_digest against every key so timing does not reveal which matched.
    return any(hmac.compare_digest(candidate, known) for known in settings.api_keys_set)


async def require_api_key(x_api_key: str | None = Header(default=None)) -> str:
    """
    FastAPI dependency guarding mutating endpoints.

    When no API_KEYS are configured the service is open — allowed in
    development, rejected at startup in production by Settings validation.
    """
    if not settings.auth_required:
        return "anonymous"
    if not _key_valid(x_api_key):
        raise UNAUTHORIZED
    # Identify the caller by key fingerprint, never by the key itself.
    return hashlib.sha256(x_api_key.encode()).hexdigest()[:16]  # type: ignore[union-attr]


async def require_api_key_ws(
    websocket: WebSocket, api_key: str | None = Query(default=None)
) -> str:
    """
    WebSocket variant. Browsers cannot set headers on a WebSocket handshake, so
    the key arrives as a query parameter and the socket is closed on failure.
    """
    if not settings.auth_required:
        return "anonymous"
    if not _key_valid(api_key):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid API key")
        raise UNAUTHORIZED
    return hashlib.sha256(api_key.encode()).hexdigest()[:16]  # type: ignore[union-attr]


def parse_repo(full_name: str) -> tuple[str, str]:
    """
    Validate and split an "owner/repo" string.

    The parts land in shell commands and URLs downstream, so anything outside
    the character set GitHub actually permits is rejected here rather than
    escaped later.
    """
    parts = full_name.strip().split("/")
    if len(parts) != 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="repo must be in 'owner/repo-name' form",
        )
    owner, repo = parts[0].strip(), parts[1].strip()
    if not _REPO_RE.match(owner) or not _REPO_RE.match(repo):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="repo contains characters GitHub does not allow",
        )
    return owner, repo


def require_repo_allowed(owner: str, repo: str) -> None:
    if not settings.repo_allowed(owner, repo):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Repository '{owner}/{repo}' is not in REPO_ALLOWLIST",
        )


def verify_github_signature(payload: bytes, signature_header: str | None) -> bool:
    """Constant-time HMAC-SHA256 check of a GitHub webhook delivery."""
    secret = settings.GITHUB_WEBHOOK_SECRET
    if not secret:
        # An unset secret must never mean "accept everything".
        return False
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header.removeprefix("sha256="))


ApiKeyDep = Depends(require_api_key)
