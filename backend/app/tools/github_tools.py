"""
GitHub App tools.

Provides a factory `make_github_tools(token, owner, repo)` that returns
a list of LangChain @tool functions pre-bound to a specific installation
token + repository.  Call `get_installation_token(installation_id)` once
per run to obtain the token.
"""

import base64
import time
import logging
from typing import Any

import httpx
import jwt as pyjwt
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from langchain_core.tools import tool

from app.config import settings

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
HEADERS_BASE = {"Accept": "application/vnd.github.v3+json", "X-GitHub-Api-Version": "2022-11-28"}


# ---------------------------------------------------------------------------
# GitHub App JWT + installation token helpers
# ---------------------------------------------------------------------------

def _create_app_jwt() -> str:
    """Create a short-lived JWT signed with the GitHub App private key."""
    private_key = load_pem_private_key(
        settings.github_private_key_pem.encode(),
        password=None,
    )
    now = int(time.time())
    payload = {
        "iat": now - 60,   # issued slightly in the past to handle clock drift
        "exp": now + 540,  # valid for 9 minutes
        "iss": settings.GITHUB_APP_ID,
    }
    return pyjwt.encode(payload, private_key, algorithm="RS256")  # type: ignore[arg-type]


async def get_installation_token(installation_id: int) -> str:
    """Exchange the App JWT for a short-lived installation access token."""
    app_jwt = _create_app_jwt()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{GITHUB_API}/app/installations/{installation_id}/access_tokens",
            headers={**HEADERS_BASE, "Authorization": f"Bearer {app_jwt}"},
        )
        resp.raise_for_status()
        return resp.json()["token"]


# ---------------------------------------------------------------------------
# Tool factory
# ---------------------------------------------------------------------------

def make_github_tools(token: str, owner: str, repo: str):
    """
    Return a list of LangChain tools pre-bound to the given GitHub
    installation token and repository.
    """
    auth_headers = {**HEADERS_BASE, "Authorization": f"Bearer {token}"}

    # ------------------------------------------------------------------ #
    @tool
    def get_file_contents(path: str) -> str:
        """
        Fetch the raw content of a file from the repository.
        Args:
            path: File path relative to repo root, e.g. 'src/main.py'
        """
        url = f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}"
        with httpx.Client() as c:
            resp = c.get(url, headers=auth_headers)
        if resp.status_code == 404:
            return f"ERROR: File not found: {path}"
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return f"ERROR: {path} is a directory. Use list_directory instead."
        raw = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        return raw

    # ------------------------------------------------------------------ #
    @tool
    def list_directory(path: str = "") -> str:
        """
        List files and directories at the given path in the repository.
        Args:
            path: Directory path relative to repo root. Empty string = root.
        """
        url = f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}"
        with httpx.Client() as c:
            resp = c.get(url, headers=auth_headers)
        if resp.status_code == 404:
            return f"ERROR: Path not found: {path}"
        resp.raise_for_status()
        items = resp.json()
        if not isinstance(items, list):
            return f"ERROR: {path} is a file. Use get_file_contents instead."
        lines = []
        for item in items:
            icon = "📁" if item["type"] == "dir" else "📄"
            lines.append(f"{icon} {item['path']} ({item['type']})")
        return "\n".join(lines) if lines else "(empty directory)"

    # ------------------------------------------------------------------ #
    @tool
    def search_code(query: str) -> str:
        """
        Search for code in the repository using GitHub code search.
        Args:
            query: Search query, e.g. 'def authenticate' or 'class UserModel'
        """
        url = f"{GITHUB_API}/search/code"
        params = {"q": f"{query} repo:{owner}/{repo}", "per_page": 10}
        with httpx.Client() as c:
            resp = c.get(url, headers=auth_headers, params=params)
        resp.raise_for_status()
        items = resp.json().get("items", [])
        if not items:
            return "No results found."
        lines = [f"- {item['path']}" for item in items]
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    @tool
    def get_repo_structure(depth: int = 2) -> str:
        """
        Get a tree view of the repository structure.
        Args:
            depth: How many directory levels to show (1–3 recommended).
        """
        url = f"{GITHUB_API}/repos/{owner}/{repo}/git/trees/HEAD"
        params = {"recursive": "1"}
        with httpx.Client() as c:
            resp = c.get(url, headers=auth_headers, params=params)
        resp.raise_for_status()
        tree = resp.json().get("tree", [])
        lines = []
        for node in tree:
            parts = node["path"].split("/")
            if len(parts) <= depth:
                indent = "  " * (len(parts) - 1)
                icon = "📁" if node["type"] == "tree" else "📄"
                lines.append(f"{indent}{icon} {parts[-1]}")
        return "\n".join(lines[:200])  # cap at 200 lines

    # ------------------------------------------------------------------ #
    @tool
    def create_branch(branch_name: str, base_branch: str = "main") -> str:
        """
        Create a new branch in the repository.
        Args:
            branch_name: Name of the new branch, e.g. 'fix/issue-42'
            base_branch: Branch to branch off from (default: main)
        """
        # Get base branch SHA
        with httpx.Client() as c:
            ref_resp = c.get(
                f"{GITHUB_API}/repos/{owner}/{repo}/git/ref/heads/{base_branch}",
                headers=auth_headers,
            )
            if ref_resp.status_code == 404:
                # Try 'master' as fallback
                ref_resp = c.get(
                    f"{GITHUB_API}/repos/{owner}/{repo}/git/ref/heads/master",
                    headers=auth_headers,
                )
            ref_resp.raise_for_status()
            sha = ref_resp.json()["object"]["sha"]

            create_resp = c.post(
                f"{GITHUB_API}/repos/{owner}/{repo}/git/refs",
                headers=auth_headers,
                json={"ref": f"refs/heads/{branch_name}", "sha": sha},
            )
            if create_resp.status_code == 422:
                return f"Branch '{branch_name}' already exists."
            create_resp.raise_for_status()
        return f"Branch '{branch_name}' created from '{base_branch}' (SHA: {sha[:7]})."

    # ------------------------------------------------------------------ #
    @tool
    def create_or_update_file(
        path: str,
        content: str,
        commit_message: str,
        branch: str,
    ) -> str:
        """
        Create or update a file in the repository on the given branch.
        Args:
            path: File path relative to repo root
            content: Full file content (text)
            commit_message: Git commit message
            branch: Branch name to commit to
        """
        encoded = base64.b64encode(content.encode()).decode()
        url = f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}"

        # Try to get existing file SHA (needed for updates)
        sha: str | None = None
        with httpx.Client() as c:
            get_resp = c.get(url, headers={**auth_headers, "ref": branch})
            if get_resp.status_code == 200:
                sha = get_resp.json().get("sha")

            payload: dict[str, Any] = {
                "message": commit_message,
                "content": encoded,
                "branch": branch,
            }
            if sha:
                payload["sha"] = sha

            put_resp = c.put(url, headers=auth_headers, json=payload)
            put_resp.raise_for_status()

        action = "Updated" if sha else "Created"
        return f"{action} file '{path}' on branch '{branch}'."

    # ------------------------------------------------------------------ #
    @tool
    def create_pull_request(
        title: str,
        body: str,
        head_branch: str,
        base_branch: str = "main",
        draft: bool = True,
    ) -> str:
        """
        Open a pull request in the repository.
        Args:
            title: PR title
            body: PR description (Markdown supported)
            head_branch: The branch containing the changes
            base_branch: Target branch (default: main)
            draft: Whether to create as a draft PR (default: True)
        """
        url = f"{GITHUB_API}/repos/{owner}/{repo}/pulls"

        with httpx.Client() as c:
            # Auto-detect actual default branch (handles main vs master)
            repo_resp = c.get(f"{GITHUB_API}/repos/{owner}/{repo}", headers=auth_headers)
            if repo_resp.status_code == 200:
                base_branch = repo_resp.json().get("default_branch", base_branch)

            payload = {
                "title": title,
                "body": body[:65000],   # GitHub caps PR body at 65536 chars
                "head": head_branch,
                "base": base_branch,
                "draft": draft,
            }
            resp = c.post(url, headers=auth_headers, json=payload)
            if not resp.is_success:
                return f"PR creation failed ({resp.status_code}): {resp.text[:500]}"
            pr = resp.json()
        return f"PR #{pr['number']} created: {pr['html_url']}"

    # ------------------------------------------------------------------ #
    @tool
    def add_issue_comment(issue_number: int, body: str) -> str:
        """
        Post a comment on the GitHub issue.
        Args:
            issue_number: The issue number
            body: Comment text (Markdown supported)
        """
        url = f"{GITHUB_API}/repos/{owner}/{repo}/issues/{issue_number}/comments"
        with httpx.Client() as c:
            resp = c.post(url, headers=auth_headers, json={"body": body})
            resp.raise_for_status()
        return "Comment posted."

    return [
        get_file_contents,
        list_directory,
        search_code,
        get_repo_structure,
        create_branch,
        create_or_update_file,
        create_pull_request,
        add_issue_comment,
    ]
