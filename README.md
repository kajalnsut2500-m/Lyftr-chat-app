# Lyftr Chat: LLM chatbot with key failover and response caching

React frontend, FastAPI backend, LiteLLM gateway and SQLite storage.

## 1. Live URLs

- Frontend: `<your-frontend-url>`
- Backend: `<your-backend-url>`
- Health check: `<your-backend-url>/health`
- GitHub: `<your-repo-url>`

## 2. Run locally

### With Docker

```bash
cp .env.example .env     # then put 2 real Gemini keys in LLM_API_KEYS
make up                  # frontend :3000, backend :8000
make down                # stop (the SQLite volume is kept)
```

### Without Docker

```bash
# backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
export LLM_API_KEYS=key1,key2 ENABLE_FAILURE_SIMULATION=true DATABASE_URL=sqlite:///./app.db
uvicorn app.main:app --port 8000
# tests
python -m pytest -q

# frontend (second terminal)
cd frontend && npm install && npm run dev      # http://localhost:3000
```

### Environment variables

| Variable | Meaning |
| --- | --- |
| `LLM_API_KEYS` | Comma-separated key pool, at least 2. Ids are `key_1`, `key_2`, ... in order |
| `LLM_MODEL` | LiteLLM model name (default `gemini/gemini-2.0-flash`) |
| `DATABASE_URL` | SQLite location, e.g. `sqlite:////data/app.db` |
| `ALLOWED_ORIGINS` | Comma-separated CORS origins |
| `ENABLE_FAILURE_SIMULATION` | `true` enables the `X-Simulate-Failure` header |
| `LLM_TIMEOUT` | Seconds before one provider call times out (default 30) |
| `VITE_API_URL` | Frontend build argument: backend URL the browser calls |

## 3. Design decisions

**Key fallback.** `LLM_API_KEYS` is an ordered pool. For each request the backend calls
`litellm.completion` with `key_1`; if the call fails for any reason (429, quota, 5xx, timeout,
bad key, empty reply) it moves to `key_2`, and so on. LiteLLM's own retries are off so this loop
is the only retry path. `fallback_attempts` counts keys that failed before one answered. If every
key fails the API returns `503 {"detail": "all providers unavailable"}` and stores nothing.
Keys are never logged or returned.

**Caching.** LiteLLM's in-memory cache is enabled at startup. LiteLLM builds the cache key from the
model and the full message list (system prompt + history + new message); the API key is not part of
it, so a reply produced through `key_2` still serves later hits. A hit reports `LLM_CACHE`, returns
the identical reply and the usage stored with it, and has `key_id: null`. The cache is lost when the
backend restarts; chat history is not.

**SQLite session storage.** A `messages` table holds the history and a `sessions` table holds each
session's optional system prompt. The user message and the reply are written in one transaction only
after the model answers, so failed requests leave no history. The client sends only the new message;
the backend rebuilds the prompt from SQLite. The file lives on a Docker volume at `/data/app.db`.

**Failure simulation.** `X-Simulate-Failure: key_1=429` (or `key_1=429,key_2=500`, or `*=429`) makes the
listed keys fail for that one request. It is honoured only when `ENABLE_FAILURE_SIMULATION=true`, and
the cache is bypassed for that request so the failover is visible.

## 4. Verification

```bash
B=<backend-url>
# cache hit: send the same first message from two different sessions
curl -s $B/chat -H 'content-type: application/json' -d '{"session_id":"a1","message":"What is the capital of France?"}'
curl -s $B/chat -H 'content-type: application/json' -d '{"session_id":"a2","message":"What is the capital of France?"}'   # LLM_CACHE, key_id null

# failover: key_1 fails, key_2 answers
curl -s $B/chat -H 'content-type: application/json' -H 'X-Simulate-Failure: key_1=429' -d '{"session_id":"f1","message":"failover demo"}'

# every key fails -> 503, nothing stored
curl -s -i $B/chat -H 'content-type: application/json' -H 'X-Simulate-Failure: *=429' -d '{"session_id":"f2","message":"all fail"}'

# history and health
curl -s $B/sessions/a1/messages
curl -s $B/health
```

In the UI, each assistant reply shows its source, model, latency and the input/output tokens for that request.
The Settings panel has a field to send the `X-Simulate-Failure` header from the browser.

## 5. Setup Used

- Editor / AI tools: *(fill in: e.g. VS Code, Claude)*
- Python 3.12, FastAPI, LiteLLM, SQLite, React 18 + Vite, Docker, nginx

## 6. Bonus features

- Optional per-session system prompt (UI field and `system_prompt` in the request).
- Simulate-failure field in the UI for demos.
- Backend tests (`make test`) covering cache, failover, 422/404/503, multi-turn and session isolation.
