"""
Application settings.

All configuration comes from environment variables (or a local .env file).
Settings are validated at import time so the process fails fast and loudly on
a bad configuration rather than halfway through a run.
"""

from __future__ import annotations

import functools
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "staging", "production"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        # Unknown keys in .env must not crash startup — operators add their own.
        extra="ignore",
        case_sensitive=True,
    )

    # ── Runtime ────────────────────────────────────────────────────────
    ENVIRONMENT: Environment = "development"
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: Literal["json", "console"] = "console"
    SERVICE_NAME: str = "devops-swarm"
    VERSION: str = "2.0.0"

    # ── GitHub App (production webhook flow) ───────────────────────────
    GITHUB_APP_ID: str = ""
    GITHUB_PRIVATE_KEY: str = ""
    GITHUB_WEBHOOK_SECRET: str = ""

    # ── GitHub PAT (manual /trigger flow) ──────────────────────────────
    GITHUB_PAT: str = ""

    # ── LLM ────────────────────────────────────────────────────────────
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    LLM_TEMPERATURE: float = 0.0
    LLM_MAX_RETRIES: int = 3
    LLM_TIMEOUT_SECONDS: int = 120

    # ── Sandbox ────────────────────────────────────────────────────────
    E2B_API_KEY: str = ""
    SANDBOX_TIMEOUT_SECONDS: int = 1800
    SANDBOX_COMMAND_TIMEOUT_SECONDS: int = 180
    SANDBOX_MAX_IDLE_SECONDS: int = 3600

    # ── Database ───────────────────────────────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://swarm:swarmpass@postgres:5432/devops_swarm"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_RECYCLE_SECONDS: int = 1800
    DB_ECHO: bool = False

    # ── HTTP surface ───────────────────────────────────────────────────
    CORS_ORIGINS: str = "http://localhost:3000"
    MAX_PAGE_SIZE: int = 100
    DEFAULT_PAGE_SIZE: int = 20

    # ── AuthN / AuthZ ──────────────────────────────────────────────────
    # Comma-separated list of API keys accepted on mutating endpoints.
    # Empty in development means "no auth"; empty in production is fatal.
    API_KEYS: str = ""
    # Comma-separated "owner/repo" entries the swarm may act on.
    # "*" allows everything (development only).
    REPO_ALLOWLIST: str = "*"

    # ── Rate limiting (token bucket, per client key) ────────────────────
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_TRIGGERS_PER_HOUR: int = 20
    RATE_LIMIT_READS_PER_MINUTE: int = 120

    # ── Swarm behaviour ────────────────────────────────────────────────
    MAX_CORRECTION_ITERATIONS: int = Field(default=3, ge=1, le=10)
    MAX_REACT_ITERATIONS: int = Field(default=25, ge=1, le=100)
    MAX_CONCURRENT_RUNS: int = Field(default=3, ge=1, le=50)
    GRAPH_RECURSION_LIMIT: int = Field(default=60, ge=10, le=500)
    # Characters of a tool result handed back to the model. The old value (450)
    # was small enough that the coder could not read a whole source file.
    TOOL_RESULT_CHAR_BUDGET: int = Field(default=6000, ge=500)
    PLAN_CHAR_BUDGET: int = Field(default=6000, ge=500)
    REPO_CONTEXT_CHAR_BUDGET: int = Field(default=8000, ge=500)

    # ── Derived ────────────────────────────────────────────────────────

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def api_keys_set(self) -> frozenset[str]:
        return frozenset(k.strip() for k in self.API_KEYS.split(",") if k.strip())

    @property
    def repo_allowlist_set(self) -> frozenset[str]:
        return frozenset(r.strip().lower() for r in self.REPO_ALLOWLIST.split(",") if r.strip())

    @property
    def auth_required(self) -> bool:
        return bool(self.api_keys_set)

    @property
    def github_private_key_pem(self) -> str:
        return self.GITHUB_PRIVATE_KEY.replace("\\n", "\n")

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    def repo_allowed(self, owner: str, repo: str) -> bool:
        allow = self.repo_allowlist_set
        if "*" in allow:
            return True
        return f"{owner}/{repo}".lower() in allow

    # ── Validation ─────────────────────────────────────────────────────

    @field_validator("LOG_LEVEL")
    @classmethod
    def _valid_log_level(cls, v: str) -> str:
        level = v.upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"LOG_LEVEL must be a standard level name, got {v!r}")
        return level

    @field_validator("DATABASE_URL")
    @classmethod
    def _async_driver(cls, v: str) -> str:
        if v.startswith("postgresql://"):
            # A sync URL silently breaks the async engine — fix it up.
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

    @model_validator(mode="after")
    def _production_requirements(self) -> Settings:
        if not self.is_production:
            return self

        problems: list[str] = []
        if not self.api_keys_set:
            problems.append("API_KEYS must be set in production (endpoints would be open)")
        if "*" in self.repo_allowlist_set:
            problems.append("REPO_ALLOWLIST must not be '*' in production")
        if "*" in self.cors_origins_list:
            problems.append("CORS_ORIGINS must not be '*' in production")
        if not self.GROQ_API_KEY:
            problems.append("GROQ_API_KEY is required")
        if not self.E2B_API_KEY:
            problems.append("E2B_API_KEY is required")
        if self.GITHUB_WEBHOOK_SECRET == "" and self.GITHUB_APP_ID:
            problems.append("GITHUB_WEBHOOK_SECRET is required when GITHUB_APP_ID is set")
        if problems:
            raise ValueError("Invalid production configuration:\n  - " + "\n  - ".join(problems))
        return self


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached accessor so tests can clear it and re-read the environment."""
    return Settings()


settings = get_settings()
