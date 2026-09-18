from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Any

from app.database import get_conn, reset_db
from app.services.ai import chunk_text, embedding_many
from app.services.pipeline import add_message, add_transcript, canonical_question_text, create_session, process_session


DEFAULT_PACK_DIR = Path(
    os.getenv(
        "VLEARN_PACK_DIR",
        r"C:\Users\hoang\K4-3A-Day05-06-AI-Product-Hackathon\data\vlearn-pack",
    )
)
DEFAULT_SESSION_ID = "vlearn-d01"
LEGACY_SESSION_ID = "vlearn-pack"


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


def _all_matching_turns(
    csv_path: Path,
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
    return turns, skipped_presets, skipped_cohort


def _lecture_sort_key(code: str) -> tuple[int, str]:
    digits = "".join(char for char in code if char.isdigit())
    return (int(digits) if digits else 999, code)


def _session_id_for_lecture(lecture_code: str, fallback_index: int) -> str:
    clean = "".join(char.lower() for char in lecture_code if char.isalnum())
    return f"vlearn-{clean or f'lecture-{fallback_index:02d}'}"


def _session_title_for_lecture(lecture_code: str, lecture_title: str) -> str:
    title = lecture_title.strip() if lecture_title else lecture_code
    return f"VLearn {lecture_code} - {title}" if lecture_code else f"VLearn - {title}"


def _meeting_date(index: int) -> str:
    return f"2026-09-{10 + index:02d}"


def _group_turns_by_lecture(turns: list[dict[str, Any]]) -> list[tuple[str, str, list[dict[str, Any]]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    titles: dict[str, str] = {}
    for turn in turns:
        metadata = turn["metadata"]
        code = metadata.get("lecture_code") or f"lecture-{len(grouped) + 1:02d}"
        grouped.setdefault(code, []).append(turn)
        titles.setdefault(code, metadata.get("lecture_title") or code)
    return [(code, titles.get(code, code), grouped[code]) for code in sorted(grouped, key=_lecture_sort_key)]


def _balanced_lecture_groups(
    turns: list[dict[str, Any]],
    max_turns: int,
    max_turns_per_lecture: int,
) -> list[tuple[str, str, list[dict[str, Any]], int]]:
    groups = _group_turns_by_lecture(turns)
    if not groups or max_turns <= 0:
        return []

    available_by_group = [len(lecture_turns) for _, _, lecture_turns in groups]
    target_total = min(max_turns, sum(available_by_group))
    if max_turns_per_lecture > 0:
        target_total = min(target_total, max_turns_per_lecture * len(groups))

    selected_counts = [0] * len(groups)
    remaining = target_total
    active_indexes = set(range(len(groups)))
    while remaining > 0 and active_indexes:
        quota = max(1, remaining // len(active_indexes))
        progressed = False
        for index in list(sorted(active_indexes)):
            lecture_cap = available_by_group[index]
            if max_turns_per_lecture > 0:
                lecture_cap = min(lecture_cap, max_turns_per_lecture)
            room = lecture_cap - selected_counts[index]
            if room <= 0:
                active_indexes.remove(index)
                continue
            take = min(room, quota, remaining)
            selected_counts[index] += take
            remaining -= take
            progressed = progressed or take > 0
            if selected_counts[index] >= lecture_cap:
                active_indexes.remove(index)
            if remaining <= 0:
                break
        if not progressed:
            break

    balanced: list[tuple[str, str, list[dict[str, Any]], int]] = []
    for (code, title, lecture_turns), selected_count in zip(groups, selected_counts):
        if selected_count > 0:
            balanced.append((code, title, lecture_turns[:selected_count], len(lecture_turns)))
    return balanced


def _add_turn(
    session_id: str,
    turn: dict[str, Any],
    question_message_vector: list[float] | None = None,
    question_cluster_vector: list[float] | None = None,
    reply_vector: list[float] | None = None,
) -> None:
    metadata = turn["metadata"]
    add_message(
        session_id,
        turn["student"],
        turn["question"],
        turn["student"],
        "student",
        **metadata,
        source_type="vlearn_student_question",
        embedding_vector=question_message_vector,
        question_embedding_vector=question_cluster_vector,
    )
    add_message(
        session_id,
        f"tutor_{metadata['turn_id']}",
        turn["reply"],
        "AI Tutor",
        "assistant",
        **metadata,
        source_type="vlearn_tutor_reply",
        embedding_vector=reply_vector,
    )


def _turn_vectors(turns: list[dict[str, Any]]) -> tuple[list[list[float]], list[list[float]], list[list[float]]]:
    question_texts = [turn["question"] for turn in turns]
    canonical_questions = [canonical_question_text(turn["question"]) for turn in turns]
    reply_texts = [turn["reply"] for turn in turns]
    return (
        embedding_many(question_texts),
        embedding_many(canonical_questions),
        embedding_many(reply_texts),
    )


def _import_vlearn_pack_by_lecture(
    base: Path,
    csv_path: Path,
    transcript_dir: Path,
    max_turns: int,
    cohort_hint: str,
    include_presets: bool,
    transcript_limit: int,
    process_after_import: bool,
    max_turns_per_lecture: int,
) -> dict[str, Any]:
    reset_db()
    turns, skipped_presets, skipped_cohort = _all_matching_turns(csv_path, cohort_hint, include_presets)
    lecture_groups = _balanced_lecture_groups(turns, max_turns, max_turns_per_lecture)
    transcript_files = sorted(transcript_dir.glob("transcript-*-clean.md"))[:transcript_limit]

    sessions: list[dict[str, Any]] = []
    total_transcript_chunks = 0
    total_clusters = 0
    imported_turns = 0

    for index, (lecture_code, lecture_title, lecture_turns, available_turns) in enumerate(lecture_groups):
        session_id = _session_id_for_lecture(lecture_code, index + 1)
        create_session(
            _session_title_for_lecture(lecture_code, lecture_title),
            session_id,
            course_title="AI Fundamentals",
            meeting_date=_meeting_date(index),
            start_time="09:00",
            end_time="10:30",
            platform="VLearn Live",
            status="completed",
        )

        question_message_vectors, question_cluster_vectors, reply_vectors = _turn_vectors(lecture_turns)
        for turn, question_message_vector, question_cluster_vector, reply_vector in zip(
            lecture_turns,
            question_message_vectors,
            question_cluster_vectors,
            reply_vectors,
        ):
            _add_turn(session_id, turn, question_message_vector, question_cluster_vector, reply_vector)
            imported_turns += 1

        transcript_chunks = 0
        transcript_file = transcript_files[index] if index < len(transcript_files) else None
        if transcript_file:
            text = transcript_file.read_text(encoding="utf-8")
            chunks = chunk_text(text, max_words=58, overlap=10)
            result = add_transcript(session_id, transcript_file.stem, text, embedding_many(chunks))
            transcript_chunks = int(result["chunks"])
            total_transcript_chunks += transcript_chunks

        clusters = process_session(session_id, top_k=5) if process_after_import else []
        total_clusters += len(clusters)
        sessions.append(
            {
                "session_id": session_id,
                "lecture_code": lecture_code,
                "lecture_title": lecture_title,
                "imported_turns": len(lecture_turns),
                "available_turns": available_turns,
                "transcript_file": transcript_file.name if transcript_file else None,
                "transcript_chunks": transcript_chunks,
                "clusters": len(clusters),
            }
        )

    return {
        "ok": True,
        "mode": "split_by_lecture",
        "default_session_id": sessions[0]["session_id"] if sessions else DEFAULT_SESSION_ID,
        "pack_dir": str(base),
        "sessions": sessions,
        "session_count": len(sessions),
        "imported_turns": imported_turns,
        "student_messages": imported_turns,
        "tutor_messages": imported_turns,
        "transcript_files": len(transcript_files),
        "transcript_chunks": total_transcript_chunks,
        "clusters": total_clusters,
        "skipped_presets": skipped_presets,
        "skipped_other_cohort": skipped_cohort,
        "embeddings_saved_to_sqlite": {
            "messages": imported_turns * 2,
            "questions": imported_turns,
            "clusters": total_clusters,
            "transcript_chunks": total_transcript_chunks,
        },
    }


def import_vlearn_pack(
    pack_dir: str | Path | None = None,
    session_id: str = DEFAULT_SESSION_ID,
    max_turns: int = 2000,
    cohort_hint: str = "K4",
    include_presets: bool = False,
    transcript_limit: int = 6,
    process_after_import: bool = True,
    split_by_lecture: bool = False,
    max_turns_per_lecture: int = 80,
) -> dict[str, Any]:
    base = Path(pack_dir) if pack_dir else DEFAULT_PACK_DIR
    csv_path = base / "chatlog" / "tutor_turns.csv"
    transcript_dir = base / "transcript"
    if not csv_path.exists():
        raise FileNotFoundError(f"Missing chatlog CSV: {csv_path}")
    if not transcript_dir.exists():
        raise FileNotFoundError(f"Missing transcript folder: {transcript_dir}")

    if split_by_lecture:
        return _import_vlearn_pack_by_lecture(
            base=base,
            csv_path=csv_path,
            transcript_dir=transcript_dir,
            max_turns=max_turns,
            cohort_hint=cohort_hint,
            include_presets=include_presets,
            transcript_limit=transcript_limit,
            process_after_import=process_after_import,
            max_turns_per_lecture=max_turns_per_lecture,
        )

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
    question_message_vectors, question_cluster_vectors, reply_vectors = _turn_vectors(turns)
    for turn, question_message_vector, question_cluster_vector, reply_vector in zip(
        turns,
        question_message_vectors,
        question_cluster_vectors,
        reply_vectors,
    ):
        metadata = turn["metadata"]
        add_message(
            session_id,
            turn["student"],
            turn["question"],
            turn["student"],
            "student",
            **metadata,
            source_type="vlearn_student_question",
            embedding_vector=question_message_vector,
            question_embedding_vector=question_cluster_vector,
        )
        add_message(
            session_id,
            f"tutor_{metadata['turn_id']}",
            turn["reply"],
            "AI Tutor",
            "assistant",
            **metadata,
            source_type="vlearn_tutor_reply",
            embedding_vector=reply_vector,
        )
        imported_turns += 1

    transcript_files = sorted(transcript_dir.glob("transcript-*-clean.md"))[:transcript_limit]
    transcript_chunks = 0
    for path in transcript_files:
        text = path.read_text(encoding="utf-8")
        chunks = chunk_text(text, max_words=58, overlap=10)
        result = add_transcript(session_id, path.stem, text, embedding_many(chunks))
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
