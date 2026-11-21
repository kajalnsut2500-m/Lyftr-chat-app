"""HTTP layer: /health, /chat, /sessions/{id}/messages."""
import logging
import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import db, llm
from .config import DEFAULT_SYSTEM_PROMPT, get_settings
from .schemas import ChatRequest, ChatResponse

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    llm.init_cache()
    yield


app = FastAPI(title="Lyftr Chat", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("unhandled error")
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


def parse_simulation(header: Optional[str]) -> dict:
    """'key_1=429,key_2=500' or '*=429' -> {'key_1': 429, ...}. Ignored unless enabled."""
    if not header or not get_settings().enable_failure_simulation:
        return {}
    out = {}
    for pair in header.split(","):
        name, _, status = pair.strip().partition("=")
        if name and status.strip() in {"429", "500", "502", "503"}:
            out[name.strip()] = int(status)
    return out


@app.get("/health")
def health():
    s = get_settings()
    if not db.check_db():
        return JSONResponse(status_code=503, content={"detail": "database unavailable"})
    if not s.api_keys:
        return JSONResponse(status_code=503, content={"detail": "no api keys configured"})
    return {"status": "ok", "keys_configured": len(s.api_keys), "cache_enabled": llm.cache_enabled()}


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, x_simulate_failure: Optional[str] = Header(default=None)):
    s = get_settings()
    start = time.perf_counter()
    system_prompt = req.system_prompt or db.get_session_prompt(req.session_id) or DEFAULT_SYSTEM_PROMPT
    history = [{"role": m["role"], "content": m["content"]} for m in db.get_history(req.session_id)]
    messages = [{"role": "system", "content": system_prompt}, *history, {"role": "user", "content": req.message}]
    try:
        result = llm.complete(messages, s.api_keys, s.model, parse_simulation(x_simulate_failure), s.timeout)
    except llm.AllProvidersUnavailable:
        return JSONResponse(status_code=503, content={"detail": "all providers unavailable"})
    metadata = {
        "resolution_source": result.source,
        "model": result.model,
        "latency_ms": max(1, int((time.perf_counter() - start) * 1000)),
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "key_id": result.key_id,
        "fallback_attempts": result.fallback_attempts,
    }
    db.save_exchange(req.session_id, req.message, result.reply, metadata, req.system_prompt)
    return {"session_id": req.session_id, "reply": result.reply, "metadata": metadata}


@app.get("/sessions/{session_id}/messages")
def session_messages(session_id: str):
    if not db.session_exists(session_id):
        return JSONResponse(status_code=404, content={"detail": "session not found"})
    return {"session_id": session_id, "messages": db.get_history(session_id)}
