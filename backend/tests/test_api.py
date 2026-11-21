def chat(client, sid, msg, headers=None, **extra):
    return client.post("/chat", json={"session_id": sid, "message": msg, **extra}, headers=headers or {})


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "keys_configured": 2, "cache_enabled": True}


def test_live_then_cache_in_new_session(client):
    a = chat(client, "s1", "What is the capital of France?").json()
    b = chat(client, "s2", "What is the capital of France?").json()
    assert a["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert a["metadata"]["key_id"] == "key_1"
    assert b["metadata"]["resolution_source"] == "LLM_CACHE"
    assert b["metadata"]["key_id"] is None and b["metadata"]["fallback_attempts"] == 0
    assert a["reply"] == b["reply"]
    assert a["metadata"]["input_tokens"] == b["metadata"]["input_tokens"]


def test_different_message_not_cached(client):
    chat(client, "s1", "hello there")
    r = chat(client, "s2", "a completely different message").json()
    assert r["metadata"]["resolution_source"] == "LIVE_INFERENCE"


def test_tokens_are_per_request(client):
    # The mock provider reports fixed usage, so this checks the contract shape:
    # integers per request, and equal first messages in new sessions report equal tokens.
    a = chat(client, "s1", "hi").json()["metadata"]
    b = chat(client, "s1", "hi again please").json()["metadata"]
    c = chat(client, "s2", "hi").json()["metadata"]
    for m in (a, b, c):
        assert isinstance(m["input_tokens"], int) and isinstance(m["output_tokens"], int)
    assert c["input_tokens"] == a["input_tokens"]
    assert b["output_tokens"] == a["output_tokens"]  # per request, never a running total


def test_multi_turn_history_and_isolation(client):
    chat(client, "a", "first")
    chat(client, "a", "second")
    chat(client, "b", "other session")
    msgs = client.get("/sessions/a/messages").json()["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    assert "metadata" in msgs[1] and "metadata" not in msgs[0]
    assert all(m["role"] != "system" for m in msgs)
    assert len(client.get("/sessions/b/messages").json()["messages"]) == 2


def test_unknown_session_404(client):
    r = client.get("/sessions/nope/messages")
    assert r.status_code == 404 and r.json() == {"detail": "session not found"}


def test_validation_422(client):
    assert chat(client, "s", "   ").status_code == 422
    assert client.post("/chat", json={"message": "hi"}).status_code == 422
    assert chat(client, "s", "x" * 4001).status_code == 422
    assert client.post("/chat", content="{bad json", headers={"content-type": "application/json"}).status_code == 422
    assert client.get("/sessions/s/messages").status_code == 404  # nothing stored


def test_simulated_failover(client):
    r = chat(client, "s", "fo test", headers={"X-Simulate-Failure": "key_1=429"})
    assert r.status_code == 200
    m = r.json()["metadata"]
    assert m["key_id"] == "key_2" and m["fallback_attempts"] == 1


def test_simulated_500(client):
    r = chat(client, "s", "fo 500", headers={"X-Simulate-Failure": "key_1=500"})
    assert r.json()["metadata"]["key_id"] == "key_2"


def test_all_keys_fail_503_not_stored(client):
    r = chat(client, "s", "boom", headers={"X-Simulate-Failure": "*=429"})
    assert r.status_code == 503 and r.json() == {"detail": "all providers unavailable"}
    assert client.get("/sessions/s/messages").status_code == 404


def test_real_failover_on_provider_error(client):
    client.broken_keys.add("fake-key-1")
    r = chat(client, "s", "real failover")
    assert r.status_code == 200 and r.json()["metadata"]["key_id"] == "key_2"
    client.broken_keys.add("fake-key-2")
    assert chat(client, "s2", "both broken").status_code == 503


def test_simulation_disabled_ignores_header(client, monkeypatch):
    monkeypatch.setenv("ENABLE_FAILURE_SIMULATION", "false")
    r = chat(client, "s", "ignored header", headers={"X-Simulate-Failure": "*=429"})
    assert r.status_code == 200


def test_system_prompt_changes_cache_key(client):
    chat(client, "a", "same message", system_prompt="Be a pirate")
    r = chat(client, "b", "same message").json()
    assert r["metadata"]["resolution_source"] == "LIVE_INFERENCE"
