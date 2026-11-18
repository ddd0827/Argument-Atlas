from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from .config import DB_PATH
from .models import Analysis


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@contextmanager
def _connection() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _connection() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS analyses (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                stance TEXT NOT NULL,
                thesis TEXT NOT NULL,
                node_count INTEGER NOT NULL,
                source_text TEXT NOT NULL,
                result_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS chats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                analysis_id TEXT NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
                node_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_chats_analysis
                ON chats(analysis_id, id);
            """
        )


def save_analysis(analysis: Analysis, source_text: str) -> dict:
    record_id = uuid.uuid4().hex[:10]
    created_at = _now()
    with _connection() as conn:
        conn.execute(
            """
            INSERT INTO analyses
                (id, title, stance, thesis, node_count, source_text, result_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record_id,
                analysis.title,
                analysis.stance,
                analysis.thesis,
                len(analysis.nodes),
                source_text,
                analysis.model_dump_json(),
                created_at,
            ),
        )
    return {"id": record_id, "created_at": created_at}


def list_analyses(limit: int = 40) -> list[dict]:
    with _connection() as conn:
        rows = conn.execute(
            """
            SELECT id, title, stance, thesis, node_count, created_at
            FROM analyses
            ORDER BY created_at DESC, rowid DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_analysis(record_id: str) -> dict | None:
    with _connection() as conn:
        row = conn.execute(
            "SELECT * FROM analyses WHERE id = ?", (record_id,)
        ).fetchone()
        if row is None:
            return None
        chat_rows = conn.execute(
            """
            SELECT node_id, role, content
            FROM chats
            WHERE analysis_id = ?
            ORDER BY id
            """,
            (record_id,),
        ).fetchall()

    chats: dict[str, list[dict]] = {}
    for chat in chat_rows:
        chats.setdefault(chat["node_id"], []).append(
            {"role": chat["role"], "content": chat["content"]}
        )

    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "source_text": row["source_text"],
        "analysis": json.loads(row["result_json"]),
        "chats": chats,
    }


def delete_analysis(record_id: str) -> bool:
    with _connection() as conn:
        cursor = conn.execute("DELETE FROM analyses WHERE id = ?", (record_id,))
    return cursor.rowcount > 0


def save_chat_pair(
    analysis_id: str, node_id: str, user_message: str, assistant_message: str
) -> None:
    now = _now()
    with _connection() as conn:
        conn.executemany(
            """
            INSERT INTO chats (analysis_id, node_id, role, content, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (analysis_id, node_id, "user", user_message, now),
                (analysis_id, node_id, "assistant", assistant_message, now),
            ],
        )
