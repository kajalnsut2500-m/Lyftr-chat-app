import os

import litellm
import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("LLM_API_KEYS", "fake-key-1,fake-key-2")
os.environ.setdefault("ENABLE_FAILURE_SIMULATION", "true")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_app.db")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    monkeypatch.setenv("LLM_API_KEYS", "fake-key-1,fake-key-2")
    monkeypatch.setenv("ENABLE_FAILURE_SIMULATION", "true")
    from app import llm
    from app.main import app

    broken = set()

    def fake_kwargs(key):
        if key in broken:
            return {"mock_response": litellm.RateLimitError("rate limited", llm_provider="gemini", model="m")}
        return {"mock_response": "Paris is the capital of France."}

    monkeypatch.setattr(llm, "_extra_kwargs", fake_kwargs)
    with TestClient(app) as c:  # runs lifespan: creates DB + fresh cache
        c.broken_keys = broken
        yield c
