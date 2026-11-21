#!/usr/bin/env python3
"""Checks a running backend against the assignment contract. No dependencies.

Usage:  python3 scripts/check_contract.py [backend-url]
        (default http://localhost:8000; works on the deployed URL too)
"""
import json
import random
import string
import sys
import urllib.error
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")
results = []


def rnd(n=6):
    return "".join(random.choices(string.ascii_lowercase, k=n))


def call(method, path, body=None, headers=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    h = {"Content-Type": "application/json", **(headers or {})}
    req = urllib.request.Request(BASE + path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            txt = r.read().decode()
            return r.status, (json.loads(txt) if txt else None), dict(r.headers)
    except urllib.error.HTTPError as e:
        txt = e.read().decode()
        try:
            return e.code, json.loads(txt), dict(e.headers)
        except Exception:
            return e.code, txt, dict(e.headers)


def chat(sid, msg, headers=None, **extra):
    return call("POST", "/chat", {"session_id": sid, "message": msg, **extra}, headers)


def check(name, ok, detail=""):
    results.append((name, ok))
    print(("PASS  " if ok else "FAIL  ") + name + (f"   [{detail}]" if detail and not ok else ""))


def warn(name, detail):
    print("WARN  " + name + f"   [{detail}]")


print(f"Checking {BASE}\n")

# ---- health
s, b, _ = call("GET", "/health")
check("GET /health -> 200 with status ok, keys_configured >= 2, cache_enabled true",
      s == 200 and b.get("status") == "ok" and b.get("keys_configured", 0) >= 2 and b.get("cache_enabled") is True, f"{s} {b}")

# ---- live call + metadata contract
word = rnd(8)
msg1 = f"In one short sentence, what is the capital of France? Ref {word}"
sa = "chk-" + rnd()
s, a, _ = chat(sa, msg1)
meta_ok = False
if s == 200 and isinstance(a, dict):
    m = a.get("metadata", {})
    meta_ok = (
        a.get("session_id") == sa and a.get("reply")
        and m.get("resolution_source") == "LIVE_INFERENCE"
        and isinstance(m.get("model"), str) and isinstance(m.get("latency_ms"), int)
        and isinstance(m.get("input_tokens"), int) and isinstance(m.get("output_tokens"), int)
        and m.get("key_id") == "key_1" and m.get("fallback_attempts") == 0
    )
check("POST /chat live call returns reply + all metadata fields (LIVE_INFERENCE, key_1, 0 fallbacks)", bool(meta_ok), f"{s} {a}")
live_ms = a["metadata"]["latency_ms"] if meta_ok else None

# ---- cache hit in a NEW session
sb = "chk-" + rnd()
s, b2, _ = chat(sb, msg1)
hit_ok = s == 200 and b2["metadata"]["resolution_source"] == "LLM_CACHE" and b2["metadata"]["key_id"] is None \
    and b2["metadata"]["fallback_attempts"] == 0 and b2["reply"] == a.get("reply")
check("Same first message in a new session -> LLM_CACHE, identical reply, key_id null", bool(hit_ok), f"{s} {b2}")
if hit_ok:
    check("Cache hit has the same token usage as the stored response",
          b2["metadata"]["input_tokens"] == a["metadata"]["input_tokens"]
          and b2["metadata"]["output_tokens"] == a["metadata"]["output_tokens"])
    check("Cache hit is faster than the live call", b2["metadata"]["latency_ms"] < live_ms,
          f"hit {b2['metadata']['latency_ms']} ms vs live {live_ms} ms")

# ---- different message must not come from cache
s, c, _ = chat("chk-" + rnd(), f"Name one primary color. Ref {rnd(8)}")
check("A different message is NOT served from cache", s == 200 and c["metadata"]["resolution_source"] == "LIVE_INFERENCE", f"{s} {c}")

# ---- tokens are per request
m1, m2 = f"Reply with the single word ok. Ref {rnd(8)}", f"Reply with the single word ok. Ref {rnd(8)}"
_, t1, _ = chat("chk-" + rnd(), m1)
_, t2, _ = chat("chk-" + rnd(), m2)
try:
    close = abs(t1["metadata"]["input_tokens"] - t2["metadata"]["input_tokens"]) <= 3
except Exception:
    close = False
check("Equal-length first messages in new sessions report about the same input_tokens", close, f"{t1} {t2}")

# ---- multi-turn memory + isolation + history
name = "Zorba" + rnd(4)
sm = "chk-" + rnd()
chat(sm, f"My name is {name}. Just say hi.")
s, mem, _ = chat(sm, "What is my name? Answer with just the name.")
if s == 200 and name.lower() in mem["reply"].lower():
    check("Multi-turn: the bot remembers the earlier message", True)
else:
    warn("Multi-turn memory: reply did not contain the name (model may be paraphrasing, verify in the UI)", f"{s} {mem}")
s, h, _ = call("GET", f"/sessions/{sm}/messages")
roles = [x["role"] for x in h["messages"]] if s == 200 else []
check("GET /sessions/{id}/messages -> ordered history, no system prompt, metadata on assistant only",
      s == 200 and roles == ["user", "assistant", "user", "assistant"]
      and "metadata" in h["messages"][1] and "metadata" not in h["messages"][0], f"{s} {h}")
s, h2, _ = call("GET", f"/sessions/{sa}/messages")
check("Sessions are isolated (other session has only its own 2 messages)", s == 200 and len(h2["messages"]) == 2, f"{s} {h2}")
s, nf, _ = call("GET", "/sessions/does-not-exist-" + rnd() + "/messages")
check("Unknown session -> 404 {'detail': 'session not found'}", s == 404 and nf == {"detail": "session not found"}, f"{s} {nf}")

# ---- validation (422)
check("Blank message -> 422", chat("v1", "   ")[0] == 422)
check("Missing session_id -> 422", call("POST", "/chat", {"message": "hi"})[0] == 422)
check("Message over 4000 chars -> 422", chat("v2", "x" * 4001)[0] == 422)
check("Malformed JSON -> 422", call("POST", "/chat", raw=b"{bad json")[0] == 422)
s, nf2, _ = call("GET", "/sessions/v1/messages")
check("Rejected (422) requests are not stored in history", s == 404, f"{s} {nf2}")

# ---- failover with X-Simulate-Failure
s, f1, _ = chat("chk-" + rnd(), f"Say hello. Ref {rnd(8)}", {"X-Simulate-Failure": "key_1=429"})
check("X-Simulate-Failure: key_1=429 -> 200 answered by key_2, fallback_attempts 1",
      s == 200 and f1["metadata"]["key_id"] == "key_2" and f1["metadata"]["fallback_attempts"] == 1
      and f1["metadata"]["resolution_source"] == "LIVE_INFERENCE", f"{s} {f1}")
s, f2, _ = chat("chk-" + rnd(), f"Say hello again. Ref {rnd(8)}", {"X-Simulate-Failure": "key_1=500"})
check("X-Simulate-Failure: key_1=500 -> 200 answered by key_2", s == 200 and f2["metadata"]["key_id"] == "key_2", f"{s} {f2}")
sf = "chk-" + rnd()
s, f3, _ = chat(sf, f"Say hello once more. Ref {rnd(8)}", {"X-Simulate-Failure": "*=429"})
check("X-Simulate-Failure: *=429 -> 503 {'detail': 'all providers unavailable'}",
      s == 503 and f3 == {"detail": "all providers unavailable"}, f"{s} {f3}")
s, nf3, _ = call("GET", f"/sessions/{sf}/messages")
check("All-keys-failed request is not added to history", s == 404, f"{s}")

# ---- CORS
req = urllib.request.Request(BASE + "/chat", method="OPTIONS", headers={
    "Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST",
    "Access-Control-Request-Headers": "content-type,x-simulate-failure"})
try:
    with urllib.request.urlopen(req, timeout=30) as r:
        ok = r.status == 200 and "access-control-allow-origin" in {k.lower() for k in r.headers}
except urllib.error.HTTPError as e:
    ok = False
check("CORS preflight for http://localhost:3000 allowed (for the deployed site, ALLOWED_ORIGINS must list your Vercel URL)", ok)

passed = sum(1 for _, ok in results if ok)
print(f"\n{passed}/{len(results)} checks passed")
sys.exit(0 if passed == len(results) else 1)
