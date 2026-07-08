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
        git_check = _run(f"test -d {WORKSPACE}/.git && echo GIT_OK || echo NO_GIT")
        if "GIT_OK" in git_check:
            return f"Workspace already set up at {WORKSPACE} (reusing existing clone)."

        clone_url = f"https://x-access-token:{token}@github.com/{owner}/{repo}.git"
        _run(f"rm -rf {WORKSPACE}")
        result = _run(f"git clone {clone_url} {WORKSPACE} 2>&1", timeout=120)

        verify = _run(f"test -d {WORKSPACE}/.git && echo GIT_OK || echo NO_GIT")
        if "NO_GIT" in verify:
            return f"CLONE FAILED — no .git directory found. Clone output: {result}"

        _run(f'cd {WORKSPACE} && git config user.email "swarm@devops-bot.ai"')
        _run(f'cd {WORKSPACE} && git config user.name "DevOps Swarm"')

        ls_result = _run(f"ls {WORKSPACE}")
        files = ls_result.lower()

        if "requirements.txt" in files:
            install = _run(f"cd {WORKSPACE} && pip install -r requirements.txt -q 2>&1", timeout=180)
            return f"Cloned {owner}/{repo}. Installed Python deps.\n{install}"
        elif "package.json" in files:
            install = _run(f"cd {WORKSPACE} && npm install --silent 2>&1", timeout=180)
            return f"Cloned {owner}/{repo}. Installed Node deps.\n{install}"
        elif "go.mod" in files:
            install = _run(f"cd {WORKSPACE} && go mod download 2>&1", timeout=120)
            return f"Cloned {owner}/{repo}. Downloaded Go modules.\n{install}"
        elif "cargo.toml" in files or "Cargo.toml" in ls_result:
            install = _run(f"cd {WORKSPACE} && cargo fetch 2>&1", timeout=180)
            return f"Cloned {owner}/{repo}. Fetched Rust crates.\n{install}"
        return f"Cloned {owner}/{repo}. No dependency file found — ready to code."

    # ------------------------------------------------------------------ #
    @tool
    def run_command(command: str) -> str:
        """
        Run any shell command inside the sandbox workspace.
        Always runs from /workspace.
        Args:
            command: Shell command, e.g. 'pytest tests/ -v' or 'pip install requests'
        """
        return _run(f"cd {WORKSPACE} && {command}", timeout=180)

    # ------------------------------------------------------------------ #
    @tool
    def read_file(path: str) -> str:
        """
        Read the contents of a file in the sandbox.
        Args:
            path: Path relative to /workspace or absolute
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
            path: Relative path, e.g. 'src/auth.py' or 'tests/test_auth.py'
            content: Full file content
        """
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
        List files/directories at a path inside the sandbox.
        Args:
            path: Path relative to /workspace, or empty for root.
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
    def find_in_files(pattern: str, file_extensions: str = "py,js,ts,go,java,rs") -> str:
        """
        Search for a string/regex pattern across all source files in the workspace.
        Use this to understand existing code patterns, find imports, and locate functions
        BEFORE writing new code — so your code matches the repo's style.
        Args:
            pattern: String or regex to search for, e.g. 'def authenticate' or 'import express'
            file_extensions: Comma-separated file extensions to search (default: py,js,ts,go,java,rs)
        """
        includes = " ".join(
            f"--include='*.{ext.strip()}'" for ext in file_extensions.split(",")
        )
        cmd = f"grep -rn {includes} '{pattern}' {WORKSPACE} 2>&1 | grep -v '.git' | head -40"
        result = _run(cmd)
        if not result.strip() or "exit_code: 1" in result:
            return f"No matches found for '{pattern}'."
        return result

    # ------------------------------------------------------------------ #
    @tool
    def search_web(query: str) -> str:
        """
        Search the web for documentation, library APIs, error solutions, or best practices.
        Use this when unsure about library syntax, encountering an unfamiliar error,
        or need to know the correct way to implement something.
        Args:
            query: Search query, e.g. 'fastapi rate limiting middleware example'
                   or 'python requests retry on timeout'
        """
        safe_query = query.replace('"', '\\"').replace("\\", "\\\\")
        script = """
import urllib.request, urllib.parse, json, sys

try:
    q = urllib.parse.quote(QUERY_PLACEHOLDER)
    url = f"https://api.duckduckgo.com/?q={q}&format=json&no_html=1&skip_disambig=1"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=12) as r:
        data = json.loads(r.read())

    results = []
    if data.get("Abstract"):
        results.append(f"SUMMARY:\\n{data['Abstract']}")
        if data.get("AbstractURL"):
            results.append(f"Source: {data['AbstractURL']}")
    if data.get("Answer"):
        results.append(f"DIRECT ANSWER:\\n{data['Answer']}")
    for t in data.get("RelatedTopics", [])[:6]:
        if isinstance(t, dict) and t.get("Text"):
            results.append(f"• {t['Text'][:300]}")
            if t.get("FirstURL"):
                results.append(f"  -> {t['FirstURL']}")
    if results:
        print("\\n".join(results))
    else:
        print("No instant results. Use fetch_url() with a specific documentation URL.")
except Exception as e:
    print(f"Search error: {e}. Try fetch_url() with a direct URL.")
""".replace("QUERY_PLACEHOLDER", f'"{safe_query}"')
        _sbx().files.write("/tmp/_search.py", script)
        return _run("python3 /tmp/_search.py", timeout=18)

    # ------------------------------------------------------------------ #
    @tool
    def fetch_url(url: str) -> str:
        """
        Fetch and read the text content of any URL.
        Use this to read official documentation, Stack Overflow answers, GitHub READMEs,
        or any web page relevant to the implementation.
        Returns the first 4000 characters of readable text content.
        Args:
            url: Full URL, e.g. 'https://fastapi.tiangolo.com/tutorial/middleware/'
        """
        script = f"""
import urllib.request, re, html as html_mod, sys

try:
    req = urllib.request.Request(
        "{url}",
        headers={{
            "User-Agent": "Mozilla/5.0 (compatible; DevOpsSwarm/1.0)",
            "Accept": "text/html,text/plain,*/*",
        }}
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        raw = r.read().decode("utf-8", errors="replace")

    # Strip scripts and styles first
    text = re.sub(r"<script[^>]*>.*?</script>", " ", raw, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_mod.unescape(text)
    text = re.sub(r"[ \\t]+", " ", text)
    text = re.sub(r"\\n{{3,}}", "\\n\\n", text)
    text = text.strip()
    print(text[:4000] if text else "Page returned empty content.")
except Exception as e:
    print(f"Failed to fetch {url}: {{e}}")
"""
        _sbx().files.write("/tmp/_fetch.py", script)
        return _run("python3 /tmp/_fetch.py", timeout=22)

    # ------------------------------------------------------------------ #
    @tool
    def install_package(package_name: str) -> str:
        """
        Install a Python pip package or Node npm package inside the sandbox.
        Use this when run_tests() fails with ModuleNotFoundError or similar import errors.
        Args:
            package_name: Package name, e.g. 'requests', 'pytest-asyncio', 'lodash'
        """
        ls_result = _run(f"ls {WORKSPACE}")
        if "package.json" in ls_result.lower():
            return _run(f"cd {WORKSPACE} && npm install {package_name} 2>&1", timeout=120)
        return _run(f"pip install {package_name} -q 2>&1", timeout=120)

    # ------------------------------------------------------------------ #
    @tool
    def run_linter() -> str:
        """
        Run a static linter on the workspace to catch syntax errors, unused imports,
        and style issues BEFORE committing. Auto-detects Python/JS/TS/Go.
        Always run this before git_commit_all().
        """
        ls_result = _run(f"ls {WORKSPACE}")
        files = ls_result.lower()

        if "requirements.txt" in files or any(f.endswith(".py") for f in ls_result.split()):
            _run("pip install flake8 -q 2>&1")
            return _run(
                f"cd {WORKSPACE} && flake8 . --max-line-length=120 "
                f"--exclude=.git,__pycache__,node_modules,.venv "
                f"--count --statistics 2>&1 | head -50"
            )
        elif "package.json" in files:
            has_eslint = _run("which eslint 2>/dev/null")
            if "eslint" in has_eslint:
                return _run(f"cd {WORKSPACE} && eslint . --ext .js,.ts 2>&1 | head -50")
            return _run(
                f"cd {WORKSPACE} && find . \\( -name '*.js' -o -name '*.ts' \\) "
                f"-not -path './node_modules/*' | xargs -I{{}} node --check {{}} 2>&1 | head -30"
            )
        elif "go.mod" in files:
            return _run(f"cd {WORKSPACE} && go vet ./... 2>&1")
        elif "cargo.toml" in files or "Cargo.toml" in ls_result:
            return _run(f"cd {WORKSPACE} && cargo check 2>&1 | head -40", timeout=120)
        return "No recognisable project type — skipping linter."

    # ------------------------------------------------------------------ #
    @tool
    def get_git_diff() -> str:
        """
        Get the current git diff of all uncommitted changes in the workspace.
        Use this to review what has been changed before committing.
        """
        return _run(f"cd {WORKSPACE} && git diff HEAD 2>&1")

    # ------------------------------------------------------------------ #
    @tool
    def run_tests() -> str:
        """
        Auto-detect and run the project test suite.
        Returns full output including pass/fail counts and error details.
        If tests fail with ModuleNotFoundError, use install_package() then retry.
        """
        ls_result = _run(f"ls {WORKSPACE}")
        files = ls_result.lower()

        if "pytest" in _run("cd /workspace && pip show pytest 2>/dev/null"):
            return _run(f"cd {WORKSPACE} && pytest --tb=short -q 2>&1", timeout=300)
        if "package.json" in files:
            return _run(f"cd {WORKSPACE} && npm test -- --watchAll=false 2>&1", timeout=300)
        if "go.mod" in files:
            return _run(f"cd {WORKSPACE} && go test ./... 2>&1", timeout=300)
        if "cargo.toml" in files or "Cargo.toml" in ls_result:
            return _run(f"cd {WORKSPACE} && cargo test 2>&1", timeout=300)
        return _run(f"cd {WORKSPACE} && python -m pytest --tb=short -q 2>&1", timeout=300)

    # ------------------------------------------------------------------ #
    @tool
    def git_commit_all(message: str) -> str:
        """
        Stage all changes and create a git commit.
        Args:
            message: Descriptive commit message, e.g. 'feat: add rate limiting middleware'
        """
        return _run(f"cd {WORKSPACE} && git add -A && git commit -m '{message}' 2>&1")

    # ------------------------------------------------------------------ #
    @tool
    def git_push(branch: str) -> str:
        """
        Push the current commits to the remote branch on GitHub.
        Args:
            branch: Remote branch name, e.g. 'swarm/issue-5-add-rate-limiting'
        """
        push_url = f"https://x-access-token:{token}@github.com/{owner}/{repo}.git"
        return _run(
            f"cd {WORKSPACE} && "
            f"git remote set-url origin {push_url} && "
            f"git push origin HEAD:{branch} 2>&1"
        )

    # ------------------------------------------------------------------ #
    @tool
    def run_security_scan() -> str:
        """
        Run security analysis: bandit for Python, plus universal secret pattern scan.
        Detects hardcoded credentials, SQL injection risks, path traversal, etc.
        """
        ls_result = _run(f"ls {WORKSPACE}")
        files = ls_result.lower()
        results = []

        if "requirements.txt" in files or any(f.endswith(".py") for f in ls_result.split()):
            _run("pip install bandit -q 2>&1")
            bandit = _run(
                f"cd {WORKSPACE} && bandit -r . -ll -f txt "
                f"--exclude .git,__pycache__,.venv 2>&1 | head -60"
            )
            results.append(f"=== Python Security (bandit) ===\n{bandit}")

        # Scan for hardcoded secrets in any language
        secret_scan = _run(
            f"grep -rn --include='*.py' --include='*.js' --include='*.ts' --include='*.go' "
            f"-E '(password|secret|api_key|token|private_key)\\s*=\\s*[\"\\'][^\"\\']{{8,}}[\"\\']' "
            f"{WORKSPACE} 2>&1 | grep -v '.git' | grep -v 'test_' | head -20"
        )
        if secret_scan.strip() and "exit_code: 1" not in secret_scan:
            results.append(f"=== ⚠️  Potential Hardcoded Secrets ===\n{secret_scan}")
        else:
            results.append("=== Hardcoded Secrets: None detected ===")

        return "\n\n".join(results) if results else "Security scan complete — no issues."

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
