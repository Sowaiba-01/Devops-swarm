"""
Secret redaction.

Everything an agent produces — tool stdout, stderr, LLM text — is streamed to
browsers over a WebSocket and persisted to Postgres. Sandbox commands embed a
GitHub token in the clone/push remote URL, and git happily echoes that URL back
in its error messages. Without this module a single failed `git push` leaks a
repo-scoped credential into the database and every open dashboard tab.

`register_secret()` is called with every live credential; `redact()` is applied
at the single choke point where agent output leaves the process.
"""

from __future__ import annotations

import re
import threading

# Credentials registered at runtime (installation tokens, PATs).
_dynamic_secrets: set[str] = set()
_lock = threading.Lock()

MASK = "***REDACTED***"

# Minimum length before we treat a registered value as a secret. Short strings
# would match everywhere and mangle unrelated output.
_MIN_SECRET_LEN = 8

# Structural patterns, applied even for credentials we were never told about.
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # https://x-access-token:ghs_xxx@github.com/... and https://user:pass@host
    (re.compile(r"(https?://)[^/\s:@]+:[^/\s@]+@"), r"\1" + MASK + "@"),
    # GitHub token families: ghp_, gho_, ghu_, ghs_, ghr_, github_pat_
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}\b"), MASK),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"), MASK),
    # Groq / OpenAI style keys
    (re.compile(r"\bgsk_[A-Za-z0-9]{20,}\b"), MASK),
    (re.compile(r"\bsk-[A-Za-z0-9\-_]{20,}\b"), MASK),
    # E2B
    (re.compile(r"\be2b_[A-Za-z0-9]{20,}\b"), MASK),
    # Authorization headers echoed in verbose curl/http output
    (re.compile(r"(?i)(authorization\s*:\s*(?:bearer|token)\s+)\S+"), r"\1" + MASK),
    # PEM private keys
    (
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
            re.DOTALL,
        ),
        MASK,
    ),
)


def register_secret(value: str | None) -> None:
    """Register a live credential so it is scrubbed from all agent output."""
    if not value or len(value) < _MIN_SECRET_LEN:
        return
    with _lock:
        _dynamic_secrets.add(value)


def forget_secret(value: str | None) -> None:
    """Drop a credential once its run is finished."""
    if not value:
        return
    with _lock:
        _dynamic_secrets.discard(value)


def redact(text: str | None) -> str:
    """Remove every known and structurally-recognisable credential from `text`."""
    if not text:
        return ""

    with _lock:
        # Longest first so a token that contains another is replaced whole.
        secrets = sorted(_dynamic_secrets, key=len, reverse=True)

    for secret in secrets:
        if secret in text:
            text = text.replace(secret, MASK)

    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)

    return text


def redact_mapping(data: dict) -> dict:
    """Recursively redact string values in a JSON-ish structure."""

    def _walk(value):
        if isinstance(value, str):
            return redact(value)
        if isinstance(value, dict):
            return {k: _walk(v) for k, v in value.items()}
        if isinstance(value, list | tuple):
            return [_walk(v) for v in value]
        return value

    return {k: _walk(v) for k, v in data.items()}


def _reset_for_tests() -> None:
    with _lock:
        _dynamic_secrets.clear()
