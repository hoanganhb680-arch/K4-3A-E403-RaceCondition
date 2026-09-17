from __future__ import annotations

import json
from typing import Any

from app.database import decode_vector, get_conn, row_to_dict
from app.services.teacher_flow import ensure_default_workspace


QUESTION_STEP_SEC = 12
TRANSCRIPT_STEP_SEC = 6


def _status_rank(status: str) -> int:
    return {"NEEDS_TEACHER_REVIEW": 0, "MONITOR": 1, "AI_TUTOR_HANDLED": 2}.get(status, 3)


def realtime_demo_state(
    session_id: str = "vlearn-pack",
    elapsed_sec: int = 0,
    top_k: int = 8,
) -> dict[str, Any]:
    ensure_default_workspace(session_id=session_id)
    elapsed_sec = max(0, int(elapsed_sec))
    top_k = max(1, min(int(top_k), 20))

    with get_conn() as conn:
        session_row = conn.execute(
            "SELECT * FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        question_rows = conn.execute(
            """
            SELECT q.id AS question_id, q.cluster_id, q.text, q.similarity,
                   m.id AS message_id, m.display_name, m.user_id, m.event_time,
                   m.lecture_title, m.created_at
            FROM questions q
            JOIN messages m ON m.id = q.message_id
            WHERE q.session_id = ?
            ORDER BY m.rowid
            """,
            (session_id,),
        ).fetchall()
        cluster_rows = conn.execute(
            """
            SELECT *
            FROM question_clusters
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchall()
        transcript_rows = conn.execute(
            """
            SELECT id, source, chunk_index, text
            FROM transcript_chunks
            WHERE session_id = ?
            ORDER BY source, chunk_index
            """,
            (session_id,),
        ).fetchall()

    timed_questions: list[dict[str, Any]] = []
    visible_by_cluster: dict[str, list[dict[str, Any]]] = {}
    for index, row in enumerate(question_rows):
        time_sec = index * QUESTION_STEP_SEC + 8
        question = row_to_dict(row)
        question["time_sec"] = time_sec
        question["display_name"] = question["display_name"] or question["user_id"] or "Học viên"
        if time_sec <= elapsed_sec:
            timed_questions.append(question)
            visible_by_cluster.setdefault(question["cluster_id"], []).append(question)

    clusters: list[dict[str, Any]] = []
    for row in cluster_rows:
        cluster = row_to_dict(row)
        visible_questions = visible_by_cluster.get(cluster["id"], [])
        if not visible_questions:
            continue
        cluster["frequency"] = len(visible_questions)
        cluster["askers"] = _unique([item["display_name"] for item in visible_questions])
        cluster["sample_questions"] = _unique([item["text"] for item in visible_questions])[:4]
        cluster["student_questions"] = visible_questions
        try:
            cluster["retrieval_context"] = json.loads(cluster["retrieval_context"] or "[]")
        except json.JSONDecodeError:
            cluster["retrieval_context"] = []
        cluster.pop("representative_embedding", None)
        clusters.append(cluster)

    clusters.sort(
        key=lambda item: (
            _status_rank(item["status"]),
            -item["frequency"],
            -float(item.get("priority_score") or item.get("confidence") or 0),
        )
    )

    transcript_window = []
    for index, row in enumerate(transcript_rows):
        start_sec = index * TRANSCRIPT_STEP_SEC
        if start_sec <= elapsed_sec:
            item = row_to_dict(row)
            item["start_sec"] = start_sec
            item["end_sec"] = start_sec + TRANSCRIPT_STEP_SEC
            transcript_window.append(item)

    total_duration_sec = max(
        (len(question_rows) - 1) * QUESTION_STEP_SEC + 45 if question_rows else 0,
        (len(transcript_rows) - 1) * TRANSCRIPT_STEP_SEC + 30 if transcript_rows else 0,
    )

    return {
        "session_id": session_id,
        "meeting": row_to_dict(session_row) if session_row else None,
        "elapsed_sec": elapsed_sec,
        "total_duration_sec": total_duration_sec,
        "progress": round(min(elapsed_sec / max(total_duration_sec, 1), 1), 4),
        "summary": {
            "visible_questions": len(timed_questions),
            "visible_clusters": len(clusters),
            "visible_transcript_chunks": len(transcript_window),
            "total_questions": len(question_rows),
            "total_clusters": len(cluster_rows),
            "total_transcript_chunks": len(transcript_rows),
        },
        "live_questions": timed_questions[-20:],
        "live_clusters": clusters[:top_k],
        "live_transcript": transcript_window[-8:],
    }


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
