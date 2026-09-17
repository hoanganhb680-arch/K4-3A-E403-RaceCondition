from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Any

from app.database import get_conn, reset_db
from app.services.pipeline import add_message, add_transcript, create_session, process_session


DEFAULT_PACK_DIR = Path(
    os.getenv(
        "VLEARN_PACK_DIR",
        r"C:\Users\hoang\K4-3A-Day05-06-AI-Product-Hackathon\data\vlearn-pack",
    )
)
DEFAULT_SESSION_ID = "vlearn-pack"


def _clean_text(value: str, limit: int | None = None) -> str:
    text = " ".join((value or "").replace("\ufeff", "").split())
    if limit and len(text) > limit:
        return text[: limit - 1].rstrip() + "…"
    return text


def _bool_value(value: str) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def _int_value(value: str) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _row_metadata(row: dict[str, str], turn_id: str) -> dict[str, Any]:
    return {
        "turn_id": turn_id,
        "event_time": row.get("asked_at_vn") or None,
        "lecture_code": row.get("lecture_code") or None,
        "lecture_title": row.get("lecture_title") or None,
        "course_id": row.get("course_id") or None,
        "reply_ms": _int_value(row.get("reply_ms", "")),
        "rating": row.get("rating") or None,
        "move_used": row.get("move_used") or None,
    }


def _selected_turns(
    csv_path: Path,
    max_turns: int,
    cohort_hint: str,
    include_presets: bool,
) -> tuple[list[dict[str, Any]], int, int]:
    turns: list[dict[str, Any]] = []
    skipped_presets = 0
    skipped_cohort = 0
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if cohort_hint and row.get("cohort_hint") != cohort_hint:
                skipped_cohort += 1
                continue
            if not include_presets and _bool_value(row.get("is_preset", "")):
                skipped_presets += 1
                continue

            question = _clean_text(row.get("student_question", ""), limit=700)
            reply = _clean_text(row.get("tutor_reply", ""), limit=1100)
            if not question or not reply:
                continue

            turn_id = row.get("turn_id") or f"turn_{len(turns) + 1}"
            student = row.get("student") or f"S{len(turns) + 1:04d}"
            turns.append(
                {
                    "student": student,
                    "question": question,
                    "reply": reply,
                    "metadata": _row_metadata(row, turn_id),
                }
            )
            if len(turns) >= max_turns:
                break
    return turns, skipped_presets, skipped_cohort


def import_vlearn_pack(
    pack_dir: str | Path | None = None,
    session_id: str = DEFAULT_SESSION_ID,
    max_turns: int = 240,
    cohort_hint: str = "K4",
    include_presets: bool = False,
    transcript_limit: int = 3,
    process_after_import: bool = True,
) -> dict[str, Any]:
    base = Path(pack_dir) if pack_dir else DEFAULT_PACK_DIR
    csv_path = base / "chatlog" / "tutor_turns.csv"
    transcript_dir = base / "transcript"
    if not csv_path.exists():
        raise FileNotFoundError(f"Missing chatlog CSV: {csv_path}")
    if not transcript_dir.exists():
        raise FileNotFoundError(f"Missing transcript folder: {transcript_dir}")

    reset_db()
    create_session(
        "AI Fundamentals - Lecture 03: LLM",
        session_id,
        course_title="AI Fundamentals",
        meeting_date="2026-09-15",
        start_time="09:00",
        end_time="10:30",
        platform="VLearn Live",
        status="completed",
    )

    turns, skipped_presets, skipped_cohort = _selected_turns(csv_path, max_turns, cohort_hint, include_presets)
    imported_turns = 0
    for turn in turns:
        metadata = turn["metadata"]
        add_message(
            session_id,
            turn["student"],
            turn["question"],
            turn["student"],
            "student",
            **metadata,
            source_type="vlearn_student_question",
        )
        add_message(
            session_id,
            f"tutor_{metadata['turn_id']}",
            turn["reply"],
            "AI Tutor",
            "assistant",
            **metadata,
            source_type="vlearn_tutor_reply",
        )
        imported_turns += 1

    transcript_files = sorted(transcript_dir.glob("transcript-*-clean.md"))[:transcript_limit]
    transcript_chunks = 0
    for path in transcript_files:
        text = path.read_text(encoding="utf-8")
        result = add_transcript(session_id, path.stem, text)
        transcript_chunks += int(result["chunks"])

    clusters = process_session(session_id, top_k=5) if process_after_import else []
    return {
        "ok": True,
        "session_id": session_id,
        "pack_dir": str(base),
        "imported_turns": imported_turns,
        "student_messages": imported_turns,
        "tutor_messages": imported_turns,
        "transcript_files": len(transcript_files),
        "transcript_chunks": transcript_chunks,
        "clusters": len(clusters),
        "skipped_presets": skipped_presets,
        "skipped_other_cohort": skipped_cohort,
        "embeddings_saved_to_sqlite": {
            "messages": imported_turns * 2,
            "questions": sum(cluster.get("frequency", 0) for cluster in clusters),
            "clusters": len(clusters),
            "transcript_chunks": transcript_chunks,
        },
    }


def backfill_vlearn_metadata(
    pack_dir: str | Path | None = None,
    session_id: str = DEFAULT_SESSION_ID,
    max_turns: int = 240,
    cohort_hint: str = "K4",
    include_presets: bool = False,
) -> dict[str, Any]:
    base = Path(pack_dir) if pack_dir else DEFAULT_PACK_DIR
    csv_path = base / "chatlog" / "tutor_turns.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"Missing chatlog CSV: {csv_path}")

    turns, skipped_presets, skipped_cohort = _selected_turns(csv_path, max_turns, cohort_hint, include_presets)
    updated_student = 0
    updated_tutor = 0

    def update_one(conn: Any, role: str, content: str, source_type: str, metadata: dict[str, Any]) -> bool:
        row = conn.execute(
            """
            SELECT id
            FROM messages
            WHERE session_id = ?
              AND role = ?
              AND content = ?
              AND turn_id IS NULL
            ORDER BY rowid
            LIMIT 1
            """,
            (session_id, role, content),
        ).fetchone()
        if not row:
            return False
        conn.execute(
            """
            UPDATE messages
            SET turn_id = ?, event_time = ?, lecture_code = ?, lecture_title = ?,
                course_id = ?, reply_ms = ?, rating = ?, move_used = ?, source_type = ?
            WHERE id = ?
            """,
            (
                metadata["turn_id"],
                metadata["event_time"],
                metadata["lecture_code"],
                metadata["lecture_title"],
                metadata["course_id"],
                metadata["reply_ms"],
                metadata["rating"],
                metadata["move_used"],
                source_type,
                row["id"],
            ),
        )
        return True

    with get_conn() as conn:
        for turn in turns:
            metadata = turn["metadata"]
            if update_one(conn, "student", turn["question"], "vlearn_student_question", metadata):
                updated_student += 1
            if update_one(conn, "assistant", turn["reply"], "vlearn_tutor_reply", metadata):
                updated_tutor += 1

    return {
        "ok": True,
        "session_id": session_id,
        "matched_turns": len(turns),
        "updated_student_messages": updated_student,
        "updated_tutor_messages": updated_tutor,
        "skipped_presets": skipped_presets,
        "skipped_other_cohort": skipped_cohort,
    }
