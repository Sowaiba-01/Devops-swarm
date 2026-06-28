"""
E2B Sandbox tools.

Each run gets its own long-lived E2B sandbox (created lazily on first coder
invocation).  Sandbox instances are stored in the module-level `_sandboxes`
dict, keyed by run_id, so they survive across agent node calls within the
same run.

`make_e2b_tools(run_id, token, owner, repo)` returns LangChain tools that
are pre-bound to the sandbox for that run.
"""

import asyncio
import logging
from typing import Dict

from e2b_code_interpreter import Sandbox
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# run_id -> Sandbox instance
_sandboxes: Dict[str, Sandbox] = {}


def get_or_create_sandbox(run_id: str) -> Sandbox:
    """Return the existing sandbox for this run, or create a new one."""
    if run_id not in _sandboxes:
        logger.info("Creating E2B sandbox for run_id=%s", run_id)
        sbx = Sandbox(timeout=1800)   # 30 minutes — survives long runs
        _sandboxes[run_id] = sbx
    return _sandboxes[run_id]


def close_sandbox(run_id: str) -> None:
    """Kill and remove the sandbox for a completed run."""
    sbx = _sandboxes.pop(run_id, None)
    if sbx:
        try:
            sbx.kill()
        except Exception:
            pass


def make_e2b_tools(run_id: str, token: str, owner: str, repo: str):
    """
    Return LangChain tools pre-bound to the E2B sandbox for this run.

    The repo is cloned into /workspace on the first call to `setup_workspace`.
    Subsequent tool calls work inside that directory.
    """
    WORKSPACE = "/workspace"

    def _sbx() -> Sandbox:
        return get_or_create_sandbox(run_id)

    def _run(cmd: str, timeout: int = 120) -> str:
        try:
            result = _sbx().commands.run(cmd, timeout=timeout)
            out_parts = []
            if result.stdout:
                out_parts.append(f"stdout:\n{result.stdout.strip()}")
            if result.stderr:
                out_parts.append(f"stderr:\n{result.stderr.strip()}")
            out_parts.append(f"exit_code: {result.exit_code}")
            return "\n".join(out_parts)
        except Exception as e:
            # E2B raises CommandExitException on non-zero exit codes.
            # Extract the actual stdout/stderr from the exception so callers
            # can still inspect the real error message (e.g. "fatal: not a git repo").
            stdout = getattr(e, "stdout", "") or ""
            stderr = getattr(e, "stderr", "") or ""
            exit_code = getattr(e, "exit_code", "?")
            parts = [f"ERROR exit_code={exit_code}: {e}"]
            if stdout:
                parts.append(f"stdout:\n{stdout.strip()}")
            if stderr:
                parts.append(f"stderr:\n{stderr.strip()}")
            return "\n".join(parts)

    # ------------------------------------------------------------------ #
    @tool
    def setup_workspace() -> str:
        """
        Clone the repository into the sandbox and install dependencies.
        Must be called once before any other sandbox tools.
        """
        # Check if already cloned (idempotent on retry iterations)
        git_check = _run(f"test -d {WORKSPACE}/.git && echo GIT_OK || echo NO_GIT")
        if "GIT_OK" in git_check:
            return f"Workspace already set up at {WORKSPACE} (reusing existing clone)."

        clone_url = f"https://x-access-token:{token}@github.com/{owner}/{repo}.git"

        # Remove /workspace if it exists but has no .git (stale empty dir)
        _run(f"rm -rf {WORKSPACE}")

        result = _run(f"git clone {clone_url} {WORKSPACE} 2>&1", timeout=120)

        # Verify clone actually worked
        verify = _run(f"test -d {WORKSPACE}/.git && echo GIT_OK || echo NO_GIT")
        if "NO_GIT" in verify:
            return f"CLONE FAILED — no .git directory found. Clone output: {result}"

        # Configure git identity inside sandbox
        _run(f'cd {WORKSPACE} && git config user.email "swarm@devops-bot.ai"')
        _run(f'cd {WORKSPACE} && git config user.name "DevOps Swarm"')

        # Detect language and install deps
        ls_result = _run(f"ls {WORKSPACE}")
        files = ls_result.lower()

        if "requirements.txt" in files:
            install = _run(f"cd {WORKSPACE} && pip install -r requirements.txt -q 2>&1", timeout=180)
            return f"Cloned {owner}/{repo} to {WORKSPACE}. Installed Python deps.\n{install}"
        elif "package.json" in files:
            install = _run(f"cd {WORKSPACE} && npm install --silent 2>&1", timeout=180)
            return f"Cloned {owner}/{repo} to {WORKSPACE}. Installed Node deps.\n{install}"
        elif "go.mod" in files:
            install = _run(f"cd {WORKSPACE} && go mod download 2>&1", timeout=120)
            return f"Cloned {owner}/{repo} to {WORKSPACE}. Downloaded Go modules.\n{install}"
        return f"Cloned {owner}/{repo} to {WORKSPACE}. No dependency file found — ready to code."

    # ------------------------------------------------------------------ #
    @tool
    def run_command(command: str) -> str:
        """
        Run a shell command inside the sandbox workspace.
        Always runs from /workspace.
        Args:
            command: Shell command to execute, e.g. 'pytest tests/ -v'
        """
        return _run(f"cd {WORKSPACE} && {command}", timeout=180)

    # ------------------------------------------------------------------ #
    @tool
    def read_file(path: str) -> str:
        """
        Read the contents of a file in the sandbox.
        Args:
            path: Absolute path or path relative to /workspace
        """
        abs_path = path if path.startswith("/") else f"{WORKSPACE}/{path}"
        try:
            content = _sbx().files.read(abs_path)
            return content
        except Exception as e:
            return f"ERROR reading {abs_path}: {e}"

    # ------------------------------------------------------------------ #
    @tool
    def write_file(path: str, content: str) -> str:
        """
        Write (create or overwrite) a file in the sandbox workspace.
        Args:
            path: File path relative to /workspace, e.g. 'hello.py' or 'src/utils.py'
            content: Full file content
        """
        # Always write inside WORKSPACE — strip any leading slash or /workspace prefix
        clean = path.lstrip("/")
        if clean.startswith("workspace/"):
            clean = clean[len("workspace/"):]
        abs_path = f"{WORKSPACE}/{clean}"
        try:
            _sbx().files.write(abs_path, content)
            return f"Written: {abs_path}"
        except Exception as e:
            return f"ERROR writing {abs_path}: {e}"

    # ------------------------------------------------------------------ #
    @tool
    def list_files(path: str = "") -> str:
        """
        List files/directories at the given path inside the sandbox.
        Args:
            path: Path relative to /workspace, or empty for workspace root.
        """
        abs_path = f"{WORKSPACE}/{path}".rstrip("/")
        try:
            items = _sbx().files.list(abs_path)
            lines = []
            for item in items:
                icon = "📁" if item.type == "dir" else "📄"
                lines.append(f"{icon} {item.name}")
            return "\n".join(lines) if lines else "(empty)"
        except Exception as e:
            return f"ERROR listing {abs_path}: {e}"

    # ------------------------------------------------------------------ #
    @tool
    def get_git_diff() -> str:
        """
        Get the current git diff of all uncommitted changes in the workspace.
        Use this to review what the Coder has changed so far.
        """
        return _run(f"cd {WORKSPACE} && git diff HEAD 2>&1")

    # ------------------------------------------------------------------ #
    @tool
    def run_tests() -> str:
        """
        Auto-detect and run the project's test suite.
        Returns full test output including pass/fail counts.
        """
        ls_result = _run(f"ls {WORKSPACE}")
        files = ls_result.lower()

        if "pytest" in _run("cd /workspace && pip show pytest 2>/dev/null"):
            return _run(f"cd {WORKSPACE} && pytest --tb=short -q 2>&1", timeout=300)
        if "package.json" in files:
            return _run(f"cd {WORKSPACE} && npm test -- --watchAll=false 2>&1", timeout=300)
        if "go.mod" in files:
            return _run(f"cd {WORKSPACE} && go test ./... 2>&1", timeout=300)
        # Fallback
        return _run(f"cd {WORKSPACE} && python -m pytest --tb=short -q 2>&1", timeout=300)

    # ------------------------------------------------------------------ #
    @tool
    def git_commit_all(message: str) -> str:
        """
        Stage all changes and create a git commit.
        Args:
            message: Commit message
        """
        out = _run(
            f"cd {WORKSPACE} && git add -A && git commit -m '{message}' 2>&1"
        )
        return out

    # ------------------------------------------------------------------ #
    @tool
    def git_push(branch: str) -> str:
        """
        Push the current sandbox commits to the remote branch.
        Args:
            branch: Remote branch name to push to
        """
        push_url = f"https://x-access-token:{token}@github.com/{owner}/{repo}.git"
        out = _run(
            f"cd {WORKSPACE} && "
            f"git remote set-url origin {push_url} && "
            f"git push origin HEAD:{branch} 2>&1"
        )
        return out

    # ------------------------------------------------------------------ #
    @tool
    def run_security_scan() -> str:
        """
        Run a static security analysis on the workspace using bandit (Python)
        or a basic pattern scan for other languages.
        """
        # Install bandit if Python project
        install = _run("pip install bandit -q 2>&1")
        result = _run(f"cd {WORKSPACE} && bandit -r . -ll 2>&1", timeout=120)
        if "command not found" in result:
            return "bandit not available; skipping security scan."
        return result

    return [
        setup_workspace,
        run_command,
        read_file,
        write_file,
        list_files,
        get_git_diff,
        run_tests,
        git_commit_all,
        git_push,
        run_security_scan,
    ]
