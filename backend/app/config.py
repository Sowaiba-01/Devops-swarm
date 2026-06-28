from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    # GitHub App (production webhook flow)
    GITHUB_APP_ID: str = ""
    GITHUB_PRIVATE_KEY: str = ""
    GITHUB_WEBHOOK_SECRET: str = ""

    # GitHub PAT — used for the /trigger test endpoint (no GitHub App needed)
    # Create at: github.com/settings/tokens  → classic token → check 'repo' scope
    GITHUB_PAT: str = ""

    # LLM — free at console.groq.com
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.3-70b-versatile"

    # Sandbox — free at e2b.dev
    E2B_API_KEY: str = ""

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://swarm:swarmpass@postgres:5432/devops_swarm"

    # CORS
    CORS_ORIGINS: str = "http://localhost:3000"

    # Swarm behavior
    MAX_CORRECTION_ITERATIONS: int = 3

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",")]

    @property
    def github_private_key_pem(self) -> str:
        return self.GITHUB_PRIVATE_KEY.replace("\\n", "\n")

    class Config:
        env_file = ".env"


settings = Settings()
