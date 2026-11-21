"""SQLite storage for chat history and per-session system prompts."""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from .config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    metadata    TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages (session_id, id);
CREATE TABLE IF NOT EXISTS sessions (
    session_id    TEXT PRIMARY KEY,
    system_prompt TEXT,
    created_at    TEXT NOT NULL
);
"""


def _db_path() -> str:
    url = get_settings().database_url
    if url.startswith("sqlite:///"):
        return url[len("sqlite:///"):]
    return url


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect():
    conn = sqlite3.connect(_db_path(), timeout=10)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    path = _db_path()
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    with connect() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)


def check_db() -> bool:
    try:
        with connect() as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False


def session_exists(session_id: str) -> bool:
    with connect() as conn:
        row = conn.execute("SELECT 1 FROM messages WHERE session_id = ? LIMIT 1", (session_id,)).fetchone()
    return row is not None


def get_session_prompt(session_id: str):
    with connect() as conn:
        row = conn.execute("SELECT system_prompt FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    return row[0] if row else None


def get_history(session_id: str) -> list:
    with connect() as conn:
        rows = conn.execute(
            "SELECT role, content, metadata FROM messages WHERE session_id = ? ORDER BY id", (session_id,)
        ).fetchall()
    out = []
    for role, content, metadata in rows:
        item = {"role": role, "content": content}
        if metadata:
            item["metadata"] = json.loads(metadata)
        out.append(item)
    return out


def save_exchange(session_id, user_message, reply, metadata, system_prompt=None) -> None:
    """Save the system prompt, user message and assistant reply in ONE transaction."""
    now = _now()
    with connect() as conn:
        conn.execute(
            "INSERT INTO sessions (session_id, system_prompt, created_at) VALUES (?, ?, ?) "
            "ON CONFLICT(session_id) DO UPDATE SET system_prompt = COALESCE(excluded.system_prompt, sessions.system_prompt)",
            (session_id, system_prompt, now),
        )
        conn.execute(
            "INSERT INTO messages (session_id, role, content, metadata, created_at) VALUES (?, 'user', ?, NULL, ?)",
            (session_id, user_message, now),
        )
        conn.execute(
            "INSERT INTO messages (session_id, role, content, metadata, created_at) VALUES (?, 'assistant', ?, ?, ?)",
            (session_id, reply, json.dumps(metadata), _now()),
        )
