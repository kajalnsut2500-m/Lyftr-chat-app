"""Settings, read from environment variables on every call."""
import os
from dataclasses import dataclass, field

DEFAULT_SYSTEM_PROMPT = "You are a helpful, concise assistant."


@dataclass
class Settings:
    api_keys: list = field(default_factory=list)
    database_url: str = "sqlite:///./app.db"
    allowed_origins: list = field(default_factory=lambda: ["http://localhost:3000"])
    enable_failure_simulation: bool = False
    model: str = "gemini/gemini-3.5-flash-lite"
    timeout: int = 30


def get_settings() -> Settings:
    keys = [k.strip() for k in os.getenv("LLM_API_KEYS", "").split(",") if k.strip()]
    origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",") if o.strip()]
    return Settings(
        api_keys=keys,
        database_url=os.getenv("DATABASE_URL", "sqlite:///./app.db"),
        allowed_origins=origins,
        enable_failure_simulation=os.getenv("ENABLE_FAILURE_SIMULATION", "false").strip().lower() == "true",
        model=os.getenv("LLM_MODEL", "gemini/gemini-2.0-flash"),
        timeout=int(os.getenv("LLM_TIMEOUT", "30")),
    )
