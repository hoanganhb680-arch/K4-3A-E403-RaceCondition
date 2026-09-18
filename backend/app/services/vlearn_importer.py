from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Any

from app.database import reset_db
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

    imported_turns = 0
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

            student = row.get("student") or f"S{imported_turns + 1:04d}"
            turn_id = row.get("turn_id") or f"turn_{imported_turns + 1}"
            add_message(session_id, student, question, student, "student")
            add_message(session_id, f"tutor_{turn_id}", reply, "AI Tutor", "assistant")
            imported_turns += 1
            if imported_turns >= max_turns:
                break

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
