"""
GitHub REST tools and App authentication.

Behaviour changes worth calling out:

* `create_or_update_file` previously sent the target branch as an HTTP *header*
  (`headers={..., "ref": branch}`). GitHub ignores unknown headers, so the call
  fetched the default branch's blob SHA and every update to a non-default branch
  failed with a 409 conflict. It is a query parameter.
* Every request now retries idempotent failures with backoff and honours
  `Retry-After` / `X-RateLimit-Reset`, instead of surfacing a raw
  `HTTPStatusError` traceback into the agent's context window.
* Connections are pooled rather than opening a fresh TLS session per call.
"""

from __future__ import annotations

import base64
import time
from typing import Any

import httpx
import jwt as pyjwt
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from langchain_core.tools import tool

from app.config import settings
from app.core.logging import get_logger
from app.core.redaction import redact, register_secret

logger = get_logger(__name__)

GITHUB_API = "https://api.github.com"
BASE_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": f"devops-swarm/{settings.VERSION}",
}

MAX_ATTEMPTS = 3
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
REQUEST_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
_LIMITS = httpx.Limits(max_connections=20, max_keepalive_connections=10)


class GitHubError(RuntimeError):
    """A GitHub call failed in a way the agent should be told about."""


# ── App authentication ─────────────────────────────────────────────────


def create_app_jwt() -> str:
    """Short-lived JWT signed with the GitHub App private key."""
    if not settings.GITHUB_APP_ID or not settings.GITHUB_PRIVATE_KEY:
        raise GitHubError("GITHUB_APP_ID and GITHUB_PRIVATE_KEY must be configured")
    private_key = load_pem_private_key(settings.github_private_key_pem.encode(), password=None)
    now = int(time.time())
    payload = {"iat": now - 60, "exp": now + 540, "iss": settings.GITHUB_APP_ID}
    return pyjwt.encode(payload, private_key, algorithm="RS256")  # type: ignore[arg-type]


async def get_installation_token(installation_id: int) -> str:
    """Exchange the App JWT for an installation access token."""
    app_jwt = create_app_jwt()
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        response = await client.post(
            f"{GITHUB_API}/app/installations/{installation_id}/access_tokens",
            headers={**BASE_HEADERS, "Authorization": f"Bearer {app_jwt}"},
        )
        if response.status_code >= 400:
            raise GitHubError(
                f"Installation token request failed ({response.status_code}): "
                f"{redact(response.text)[:300]}"
            )
        token = response.json()["token"]
    # Register before the token is used anywhere it might be echoed back.
    register_secret(token)
    return token


# ── Transport ──────────────────────────────────────────────────────────


def _request(
    client: httpx.Client,
    method: str,
    url: str,
    **kwargs: Any,
) -> httpx.Response:
    """Issue a request, retrying transient failures with backoff."""
    last: httpx.Response | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = client.request(method, url, **kwargs)
        except httpx.RequestError as exc:
            if attempt == MAX_ATTEMPTS:
                raise GitHubError(f"Network error calling GitHub: {exc}") from exc
            time.sleep(min(2**attempt, 8))
            continue

        if response.status_code not in RETRY_STATUSES:
            return response

        last = response
        if attempt == MAX_ATTEMPTS:
            break

        # Prefer the server's own guidance over a fixed backoff.
        delay = float(response.headers.get("Retry-After", 0) or 0)
        if not delay and response.headers.get("X-RateLimit-Remaining") == "0":
            reset = int(response.headers.get("X-RateLimit-Reset", 0) or 0)
            delay = max(0.0, reset - time.time())
        time.sleep(min(delay or 2**attempt, 30))

    assert last is not None
    return last


def _client(token: str) -> httpx.Client:
    return httpx.Client(
        headers={**BASE_HEADERS, "Authorization": f"Bearer {token}"},
        timeout=REQUEST_TIMEOUT,
        limits=_LIMITS,
        follow_redirects=True,
    )


def _fail(action: str, response: httpx.Response) -> str:
    detail = redact(response.text)[:300]
    logger.warning("GitHub %s failed with %d", action, response.status_code)
    return f"ERROR: {action} failed ({response.status_code}): {detail}"


# ── Tool factory ───────────────────────────────────────────────────────


def make_github_tools(*, token: str, owner: str, repo: str) -> list:
    """Build the GitHub toolset bound to one token and repository."""

    register_secret(token)
    repo_root = f"{GITHUB_API}/repos/{owner}/{repo}"

    def _default_branch(client: httpx.Client) -> str:
        response = _request(client, "GET", repo_root)
        if response.status_code == 200:
            return str(response.json().get("default_branch") or "main")
        return "main"

    # ------------------------------------------------------------------ #
    @tool
    def get_file_contents(path: str, ref: str = "") -> str:
        """
        Read a file from the repository.
        Args:
            path: Path relative to the repository root, e.g. 'src/main.py'
            ref: Optional branch, tag, or commit SHA
        """
        with _client(token) as client:
            response = _request(
                client,
                "GET",
                f"{repo_root}/contents/{path.lstrip('/')}",
                params={"ref": ref} if ref else None,
            )
            if response.status_code == 404:
                return f"ERROR: file not found: {path}"
            if response.status_code >= 400:
                return _fail(f"read {path}", response)
            data = response.json()
        if isinstance(data, list):
            return f"ERROR: {path} is a directory — use list_directory instead."
        if data.get("encoding") != "base64":
            return f"ERROR: {path} is not a text file GitHub will decode."
        raw = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        return raw[:20_000]

    # ------------------------------------------------------------------ #
    @tool
    def list_directory(path: str = "") -> str:
        """
        List a directory in the repository.
        Args:
            path: Directory relative to the repository root; empty for the root.
        """
        with _client(token) as client:
            response = _request(client, "GET", f"{repo_root}/contents/{path.lstrip('/')}")
            if response.status_code == 404:
                return f"ERROR: path not found: {path}"
            if response.status_code >= 400:
                return _fail(f"list {path}", response)
            items = response.json()
        if not isinstance(items, list):
            return f"ERROR: {path} is a file — use get_file_contents instead."
        return "\n".join(f"{i['type']:<4} {i['path']}" for i in items) or "(empty directory)"

    # ------------------------------------------------------------------ #
    @tool
    def search_code(query: str) -> str:
        """
        Search the repository's code.
        Args:
            query: Search terms, e.g. 'def authenticate'
        """
        with _client(token) as client:
            response = _request(
                client,
                "GET",
                f"{GITHUB_API}/search/code",
                params={"q": f"{query} repo:{owner}/{repo}", "per_page": 15},
            )
            if response.status_code >= 400:
                return _fail("code search", response)
            items = response.json().get("items", [])
        return "\n".join(f"- {i['path']}" for i in items) or "No results."

    # ------------------------------------------------------------------ #
    @tool
    def get_repo_structure(depth: int = 2) -> str:
        """
        Show the repository tree.
        Args:
            depth: Directory levels to include (1-4).
        """
        depth = max(1, min(depth, 4))
        with _client(token) as client:
            response = _request(
                client, "GET", f"{repo_root}/git/trees/HEAD", params={"recursive": "1"}
            )
            if response.status_code >= 400:
                return _fail("read tree", response)
            tree = response.json().get("tree", [])
        lines = [n["path"] for n in tree if len(n["path"].split("/")) <= depth]
        return "\n".join(lines[:300])

    # ------------------------------------------------------------------ #
    @tool
    def get_full_repo_context() -> str:
        """
        One-shot repository snapshot: the file tree plus key manifests.
        Call this before planning.
        """
        with _client(token) as client:
            response = _request(
                client, "GET", f"{repo_root}/git/trees/HEAD", params={"recursive": "1"}
            )
            if response.status_code >= 400:
                return _fail("read repository tree", response)
            payload = response.json()
            paths = [n["path"] for n in payload.get("tree", []) if n["type"] == "blob"]

            interesting = {
                "readme.md",
                "readme.rst",
                "requirements.txt",
                "pyproject.toml",
                "setup.py",
                "package.json",
                "go.mod",
                "cargo.toml",
                "pom.xml",
                "build.gradle",
                "makefile",
                "docker-compose.yml",
                ".env.example",
            }
            sections: list[str] = []
            budget = settings.REPO_CONTEXT_CHAR_BUDGET
            for path in paths:
                if path.lower() not in interesting or budget <= 0:
                    continue
                file_response = _request(client, "GET", f"{repo_root}/contents/{path}")
                if file_response.status_code != 200:
                    continue
                body = file_response.json()
                if body.get("encoding") != "base64":
                    continue
                text = base64.b64decode(body["content"]).decode("utf-8", errors="replace")
                slice_ = text[: min(2500, budget)]
                budget -= len(slice_)
                sections.append(f"=== {path} ===\n{slice_}")

        truncated = " (truncated)" if payload.get("truncated") else ""
        return (
            f"REPOSITORY: {owner}/{repo}\n"
            f"FILES: {len(paths)}{truncated}\n\n"
            f"FILE TREE:\n"
            + "\n".join(paths[:500])
            + "\n\n"
            + ("KEY FILES:\n" + "\n\n".join(sections) if sections else "")
        )

    # ------------------------------------------------------------------ #
    @tool
    def get_issue_comments(issue_number: int) -> str:
        """
        Read the comments on an issue for requirements added after it was opened.
        Args:
            issue_number: Issue number
        """
        with _client(token) as client:
            response = _request(
                client,
                "GET",
                f"{repo_root}/issues/{issue_number}/comments",
                params={"per_page": 20},
            )
            if response.status_code >= 400:
                return _fail("read issue comments", response)
            comments = response.json()
        if not comments:
            return "No comments on this issue."
        return "\n\n---\n\n".join(f"@{c['user']['login']}:\n{c['body'][:800]}" for c in comments)

    # ------------------------------------------------------------------ #
    @tool
    def create_branch(branch_name: str, base_branch: str = "") -> str:
        """
        Create a branch. Succeeds quietly if it already exists.
        Args:
            branch_name: New branch name
            base_branch: Branch to fork from; defaults to the repository default.
        """
        with _client(token) as client:
            base = base_branch or _default_branch(client)
            ref_response = _request(client, "GET", f"{repo_root}/git/ref/heads/{base}")
            if ref_response.status_code >= 400:
                return _fail(f"resolve base branch '{base}'", ref_response)
            sha = ref_response.json()["object"]["sha"]

            create_response = _request(
                client,
                "POST",
                f"{repo_root}/git/refs",
                json={"ref": f"refs/heads/{branch_name}", "sha": sha},
            )
            if create_response.status_code == 422:
                return f"Branch '{branch_name}' already exists."
            if create_response.status_code >= 400:
                return _fail(f"create branch '{branch_name}'", create_response)
        return f"Branch '{branch_name}' created from '{base}' at {sha[:7]}."

    # ------------------------------------------------------------------ #
    @tool
    def create_or_update_file(path: str, content: str, commit_message: str, branch: str) -> str:
        """
        Commit a file directly through the API.
        Args:
            path: Path relative to the repository root
            content: Complete file content
            commit_message: Commit message
            branch: Branch to commit to
        """
        url = f"{repo_root}/contents/{path.lstrip('/')}"
        with _client(token) as client:
            # `ref` is a query parameter. Sending it as a header silently
            # resolved the default branch and broke every non-default update.
            existing = _request(client, "GET", url, params={"ref": branch})
            sha = existing.json().get("sha") if existing.status_code == 200 else None

            payload: dict[str, Any] = {
                "message": commit_message,
                "content": base64.b64encode(content.encode()).decode(),
                "branch": branch,
            }
            if sha:
                payload["sha"] = sha

            response = _request(client, "PUT", url, json=payload)
            if response.status_code >= 400:
                return _fail(f"write {path}", response)
        return f"{'Updated' if sha else 'Created'} '{path}' on '{branch}'."

    # ------------------------------------------------------------------ #
    @tool
    def create_pull_request(
        title: str,
        body: str,
        head_branch: str,
        base_branch: str = "",
        draft: bool = True,
    ) -> str:
        """
        Open a pull request.
        Args:
            title: PR title
            body: PR description in Markdown
            head_branch: Branch containing the changes
            base_branch: Target branch; defaults to the repository default.
            draft: Open as a draft
        """
        with _client(token) as client:
            base = base_branch or _default_branch(client)
            response = _request(
                client,
                "POST",
                f"{repo_root}/pulls",
                json={
                    "title": title[:250],
                    "body": body[:60_000],
                    "head": head_branch,
                    "base": base,
                    "draft": draft,
                },
            )
            if response.status_code == 422 and "draft" in response.text.lower():
                # Private repos on the free plan reject draft PRs.
                response = _request(
                    client,
                    "POST",
                    f"{repo_root}/pulls",
                    json={
                        "title": title[:250],
                        "body": body[:60_000],
                        "head": head_branch,
                        "base": base,
                    },
                )
            if response.status_code >= 400:
                return _fail("create pull request", response)
            pr = response.json()
        return f"PR #{pr['number']} created: {pr['html_url']}"

    # ------------------------------------------------------------------ #
    @tool
    def add_issue_comment(issue_number: int, body: str) -> str:
        """
        Comment on an issue.
        Args:
            issue_number: Issue number
            body: Comment text in Markdown
        """
        with _client(token) as client:
            response = _request(
                client,
                "POST",
                f"{repo_root}/issues/{issue_number}/comments",
                json={"body": body[:60_000]},
            )
            if response.status_code >= 400:
                return _fail("post issue comment", response)
        return "Comment posted."

    return [
        get_file_contents,
        list_directory,
        search_code,
        get_repo_structure,
        get_full_repo_context,
        get_issue_comments,
        create_branch,
        create_or_update_file,
        create_pull_request,
        add_issue_comment,
    ]
