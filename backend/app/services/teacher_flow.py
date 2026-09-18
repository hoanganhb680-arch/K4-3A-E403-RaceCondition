from __future__ import annotations

import json
import threading
from typing import Any

from app.database import get_conn, row_to_dict
from app.services.pipeline import create_session, dashboard, new_id, process_session, refresh_session_embeddings
from app.services.vlearn_importer import DEFAULT_SESSION_ID, import_vlearn_pack


_workspace_lock = threading.Lock()

DEFAULT_TEACHER_ID = "teacher"
DEFAULT_MEETINGS = [
    {
        "id": "ai-fundamentals-day01",
        "title": "AI Fundamentals - Day 01: AI/ML/DL",
        "course_title": "AI Fundamentals",
        "meeting_date": "2026-09-14",
        "start_time": "08:00",
        "end_time": "09:30",
        "platform": "VLearn Live",
        "status": "completed",
    },
    {
        "id": DEFAULT_SESSION_ID,
        "title": "AI Fundamentals - Lecture 03: LLM",
        "course_title": "AI Fundamentals",
        "meeting_date": "2026-09-15",
        "start_time": "09:00",
        "end_time": "10:30",
        "platform": "VLearn Live",
        "status": "completed",
    },
    {
        "id": "ai-fundamentals-day03",
        "title": "AI Fundamentals - Day 03: RAG & Agents",
        "course_title": "AI Fundamentals",
        "meeting_date": "2026-09-16",
        "start_time": "14:00",
        "end_time": "15:30",
        "platform": "VLearn Live",
        "status": "scheduled",
    },
]


def ensure_schedule() -> None:
    for meeting in DEFAULT_MEETINGS:
        create_session(
            meeting["title"],
            meeting["id"],
            meeting["course_title"],
            meeting["meeting_date"],
            meeting["start_time"],
            meeting["end_time"],
            meeting["platform"],
            meeting["status"],
        )


def list_teacher_schedule() -> dict[str, Any]:
    ensure_schedule()
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT s.*,
                   (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id) AS chat_messages,
                   (SELECT COUNT(*) FROM question_clusters qc WHERE qc.session_id = s.id) AS question_clusters,
                   (SELECT COUNT(*) FROM question_summaries qs WHERE qs.session_id = s.id) AS saved_summaries
            FROM sessions s
            ORDER BY s.meeting_date ASC, s.start_time ASC
            """
        ).fetchall()

    days: dict[str, dict[str, Any]] = {}
    for row in rows:
        meeting = row_to_dict(row)
        date = meeting["meeting_date"]
        days.setdefault(date, {"date": date, "meetings": []})["meetings"].append(meeting)
    return {"days": list(days.values())}


def ensure_default_workspace(
    session_id: str = DEFAULT_SESSION_ID,
    max_turns: int = 240,
    transcript_limit: int = 3,
    refresh_embeddings: bool = False,
) -> dict[str, Any]:
    ensure_schedule()
    with _workspace_lock:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS total FROM messages WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            total = int(row["total"]) if row else 0

        if total == 0 and session_id == DEFAULT_SESSION_ID:
            import_vlearn_pack(
                session_id=session_id,
                max_turns=max_turns,
                cohort_hint="K4",
                include_presets=False,
                transcript_limit=transcript_limit,
                process_after_import=True,
            )
            data = dashboard(session_id)
            data["embedding_refresh"] = {"changed_total": 0, "refreshed": {}}
            return data

    refresh_result = {"changed_total": 0, "refreshed": {}, "target_dimension": None}
    if refresh_embeddings:
        refresh_result = refresh_session_embeddings(session_id)
    data = dashboard(session_id)
    data["embedding_refresh"] = refresh_result
    return data


def _student_questions_by_cluster(conn: Any, session_id: str) -> dict[str, list[dict[str, Any]]]:
    rows = conn.execute(
        """
        SELECT q.cluster_id, q.text, m.display_name, m.user_id, m.created_at
        FROM questions q
        JOIN messages m ON m.id = q.message_id
        WHERE q.session_id = ?
        ORDER BY m.rowid
        """,
        (session_id,),
    ).fetchall()

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["cluster_id"], []).append(
            {
                "text": row["text"],
                "display_name": row["display_name"] or row["user_id"] or "Học viên",
                "user_id": row["user_id"],
                "created_at": row["created_at"],
            }
        )
    return grouped


def create_question_summary(
    session_id: str = DEFAULT_SESSION_ID,
    teacher_id: str = DEFAULT_TEACHER_ID,
    top_k: int = 10,
) -> dict[str, Any]:
    ensure_default_workspace(session_id=session_id, refresh_embeddings=True)
    process_session(session_id, top_k=5)
    data = dashboard(session_id)
    ranked_clusters = sorted(
        data["clusters"],
        key=lambda cluster: (-cluster["frequency"], cluster["status"], -cluster["confidence"]),
    )[:top_k]

    summary_id = new_id("summary")
    title = f"Top {top_k} nhóm câu hỏi học viên hỏi nhiều nhất"
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO question_summaries
            (id, session_id, teacher_id, title, top_k, total_clusters)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (summary_id, session_id, teacher_id, title, top_k, len(data["clusters"])),
        )
        for index, cluster in enumerate(ranked_clusters, start=1):
            conn.execute(
                """
                INSERT INTO summary_items
                (id, summary_id, cluster_id, rank, question, frequency, askers_json,
                 sample_questions_json, student_questions_json, status, confidence)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id("summary_item"),
                    summary_id,
                    cluster["id"],
                    index,
                    cluster["representative_question"],
                    cluster["frequency"],
                    json.dumps(cluster.get("askers", []), ensure_ascii=False),
                    json.dumps(cluster.get("sample_questions", []), ensure_ascii=False),
                    json.dumps(cluster.get("student_questions", []), ensure_ascii=False),
                    cluster["status"],
                    cluster["confidence"],
                ),
            )
    return get_question_summary(summary_id)


def list_question_summaries(session_id: str | None = None) -> list[dict[str, Any]]:
    ensure_schedule()
    if session_id:
        ensure_default_workspace(session_id=session_id)
    else:
        ensure_default_workspace(session_id=DEFAULT_SESSION_ID)

    where_clause = "WHERE qs.session_id = ?" if session_id else ""
    params = (session_id,) if session_id else ()
    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT qs.*,
                   COUNT(si.id) AS item_count,
                   s.title AS meeting_title,
                   s.course_title,
                   s.meeting_date,
                   s.start_time,
                   s.end_time,
                   s.platform
            FROM question_summaries qs
            LEFT JOIN summary_items si ON si.summary_id = qs.id
            JOIN sessions s ON s.id = qs.session_id
            {where_clause}
            GROUP BY qs.id
            ORDER BY qs.created_at DESC
            """,
            params,
        ).fetchall()
    return [row_to_dict(row) for row in rows]


def get_question_summary(summary_id: str) -> dict[str, Any]:
    with get_conn() as conn:
        summary_row = conn.execute(
            "SELECT * FROM question_summaries WHERE id = ?",
            (summary_id,),
        ).fetchone()
        if not summary_row:
            raise ValueError("Summary not found")
        session_row = conn.execute(
            """
            SELECT id, title, course_title, meeting_date, start_time, end_time, platform, status
            FROM sessions
            WHERE id = ?
            """,
            (summary_row["session_id"],),
        ).fetchone()
        item_rows = conn.execute(
            """
            SELECT * FROM summary_items
            WHERE summary_id = ?
            ORDER BY rank ASC
            """,
            (summary_id,),
        ).fetchall()
        question_rows_by_cluster = _student_questions_by_cluster(conn, summary_row["session_id"])

    summary = row_to_dict(summary_row)
    summary["meeting"] = row_to_dict(session_row) if session_row else None
    items = []
    backfill_student_questions: list[tuple[str, str]] = []
    for row in item_rows:
        item = row_to_dict(row)
        item["askers"] = json.loads(item.pop("askers_json"))
        item["sample_questions"] = json.loads(item.pop("sample_questions_json"))
        student_questions = json.loads(item.pop("student_questions_json", "[]") or "[]")
        if not student_questions:
            student_questions = question_rows_by_cluster.get(item["cluster_id"], [])
            if student_questions:
                backfill_student_questions.append(
                    (json.dumps(student_questions, ensure_ascii=False), item["id"])
                )
        item["student_questions"] = student_questions
        items.append(item)
    if backfill_student_questions:
        with get_conn() as conn:
            conn.executemany(
                "UPDATE summary_items SET student_questions_json = ? WHERE id = ?",
                backfill_student_questions,
            )
    summary["items"] = items
    summary["saved_to"] = {
        "database": "SQLite",
        "tables": ["question_summaries", "summary_items"],
    }
    return summary
