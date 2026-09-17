from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


BASE_DIR = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.getenv("VLEARN_DB_PATH", BASE_DIR / "vlearn_tutor.db"))


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                course_title TEXT NOT NULL DEFAULT 'AI Fundamentals',
                meeting_date TEXT NOT NULL DEFAULT '2026-09-15',
                start_time TEXT NOT NULL DEFAULT '09:00',
                end_time TEXT NOT NULL DEFAULT '10:30',
                platform TEXT NOT NULL DEFAULT 'VLearn Live',
                status TEXT NOT NULL DEFAULT 'scheduled',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                display_name TEXT NOT NULL DEFAULT '',
                role TEXT NOT NULL DEFAULT 'student',
                content TEXT NOT NULL,
                embedding TEXT NOT NULL DEFAULT '[]',
                is_question INTEGER NOT NULL DEFAULT 0,
                turn_id TEXT,
                event_time TEXT,
                lecture_code TEXT,
                lecture_title TEXT,
                course_id TEXT,
                reply_ms INTEGER,
                rating TEXT,
                move_used TEXT,
                source_type TEXT NOT NULL DEFAULT 'live_chat',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS question_clusters (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                representative_question TEXT NOT NULL,
                representative_embedding TEXT NOT NULL,
                frequency INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'NEEDS_TEACHER_REVIEW',
                confidence REAL NOT NULL DEFAULT 0,
                priority_score REAL NOT NULL DEFAULT 0,
                attention_reason TEXT NOT NULL DEFAULT '',
                retrieval_context TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS questions (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                cluster_id TEXT NOT NULL,
                text TEXT NOT NULL,
                embedding TEXT NOT NULL,
                similarity REAL NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE,
                FOREIGN KEY(message_id) REFERENCES messages(id) ON DELETE CASCADE,
                FOREIGN KEY(cluster_id) REFERENCES question_clusters(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS transcript_chunks (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                source TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                text TEXT NOT NULL,
                embedding TEXT NOT NULL,
                segment_id TEXT,
                transcript_order INTEGER,
                source_type TEXT NOT NULL DEFAULT 'lecture_transcript',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS answer_results (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                cluster_id TEXT NOT NULL,
                status TEXT NOT NULL,
                confidence REAL NOT NULL,
                evidence TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE,
                FOREIGN KEY(cluster_id) REFERENCES question_clusters(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS question_summaries (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                teacher_id TEXT NOT NULL DEFAULT 'teacher',
                title TEXT NOT NULL,
                top_k INTEGER NOT NULL,
                total_clusters INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS summary_items (
                id TEXT PRIMARY KEY,
                summary_id TEXT NOT NULL,
                cluster_id TEXT NOT NULL,
                rank INTEGER NOT NULL,
                question TEXT NOT NULL,
                frequency INTEGER NOT NULL,
                askers_json TEXT NOT NULL DEFAULT '[]',
                sample_questions_json TEXT NOT NULL DEFAULT '[]',
                student_questions_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0,
                priority_score REAL NOT NULL DEFAULT 0,
                attention_reason TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(summary_id) REFERENCES question_summaries(id) ON DELETE CASCADE,
                FOREIGN KEY(cluster_id) REFERENCES question_clusters(id) ON DELETE CASCADE
            );
            """
        )
        _ensure_column(conn, "messages", "display_name", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "messages", "role", "TEXT NOT NULL DEFAULT 'student'")
        _ensure_column(conn, "messages", "embedding", "TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(conn, "messages", "turn_id", "TEXT")
        _ensure_column(conn, "messages", "event_time", "TEXT")
        _ensure_column(conn, "messages", "lecture_code", "TEXT")
        _ensure_column(conn, "messages", "lecture_title", "TEXT")
        _ensure_column(conn, "messages", "course_id", "TEXT")
        _ensure_column(conn, "messages", "reply_ms", "INTEGER")
        _ensure_column(conn, "messages", "rating", "TEXT")
        _ensure_column(conn, "messages", "move_used", "TEXT")
        _ensure_column(conn, "messages", "source_type", "TEXT NOT NULL DEFAULT 'live_chat'")
        _ensure_column(conn, "question_clusters", "priority_score", "REAL NOT NULL DEFAULT 0")
        _ensure_column(conn, "question_clusters", "attention_reason", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "transcript_chunks", "segment_id", "TEXT")
        _ensure_column(conn, "transcript_chunks", "transcript_order", "INTEGER")
        _ensure_column(conn, "transcript_chunks", "source_type", "TEXT NOT NULL DEFAULT 'lecture_transcript'")
        _ensure_column(conn, "sessions", "course_title", "TEXT NOT NULL DEFAULT 'AI Fundamentals'")
        _ensure_column(conn, "sessions", "meeting_date", "TEXT NOT NULL DEFAULT '2026-09-15'")
        _ensure_column(conn, "sessions", "start_time", "TEXT NOT NULL DEFAULT '09:00'")
        _ensure_column(conn, "sessions", "end_time", "TEXT NOT NULL DEFAULT '10:30'")
        _ensure_column(conn, "sessions", "platform", "TEXT NOT NULL DEFAULT 'VLearn Live'")
        _ensure_column(conn, "sessions", "status", "TEXT NOT NULL DEFAULT 'scheduled'")
        _ensure_column(conn, "summary_items", "student_questions_json", "TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(conn, "summary_items", "priority_score", "REAL NOT NULL DEFAULT 0")
        _ensure_column(conn, "summary_items", "attention_reason", "TEXT NOT NULL DEFAULT ''")


def reset_db() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()
    init_db()


def encode_vector(vector: list[float]) -> str:
    return json.dumps(vector, separators=(",", ":"))


def decode_vector(raw: str) -> list[float]:
    return [float(value) for value in json.loads(raw)]
