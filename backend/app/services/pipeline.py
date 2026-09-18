from __future__ import annotations

import json
import uuid
from typing import Any

from app.database import decode_vector, encode_vector, get_conn, row_to_dict
from app.services.ai import answer_status_many, chunk_text, cosine_similarity, embedding, embedding_many, is_question, normalize_text


DEDUP_THRESHOLD = 0.50


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def create_session(
    title: str,
    session_id: str | None = None,
    course_title: str = "AI Fundamentals",
    meeting_date: str = "2026-09-15",
    start_time: str = "09:00",
    end_time: str = "10:30",
    platform: str = "VLearn Live",
    status: str = "scheduled",
) -> dict[str, Any]:
    session_id = session_id or new_id("session")
    with get_conn() as conn:
        existing = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if existing:
            if title != "Auto-created session":
                conn.execute(
                    """
                    UPDATE sessions
                    SET title = ?, course_title = ?, meeting_date = ?, start_time = ?,
                        end_time = ?, platform = ?, status = ?
                    WHERE id = ?
                    """,
                    (title, course_title, meeting_date, start_time, end_time, platform, status, session_id),
                )
        else:
            conn.execute(
                """
                INSERT INTO sessions (id, title, course_title, meeting_date, start_time, end_time, platform, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (session_id, title, course_title, meeting_date, start_time, end_time, platform, status),
            )
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    return row_to_dict(row)


def add_message(
    session_id: str,
    user_id: str,
    content: str,
    display_name: str | None = None,
    role: str = "student",
) -> dict[str, Any]:
    clean_role = role if role in {"student", "teacher", "assistant"} else "student"
    question_flag = clean_role == "student" and is_question(content)
    message_vector = embedding(content)
    message_id = new_id("msg")
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO messages (id, session_id, user_id, display_name, role, content, embedding, is_question)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message_id,
                session_id,
                user_id,
                display_name or user_id,
                clean_role,
                content,
                encode_vector(message_vector),
                int(question_flag),
            ),
        )
    if question_flag:
        upsert_question(session_id, message_id, content)
    return {
        "id": message_id,
        "session_id": session_id,
        "display_name": display_name or user_id,
        "role": clean_role,
        "is_question": question_flag,
        "content": content,
    }


def upsert_question(session_id: str, message_id: str, text: str) -> dict[str, Any]:
    vector = embedding(text)
    cluster_id = None
    best_similarity = 0.0
    with get_conn() as conn:
        clusters = conn.execute(
            "SELECT * FROM question_clusters WHERE session_id = ?",
            (session_id,),
        ).fetchall()
        for cluster in clusters:
            similarity = cosine_similarity(vector, decode_vector(cluster["representative_embedding"]))
            if similarity > best_similarity and _can_merge_questions(text, cluster["representative_question"]):
                best_similarity = similarity
                cluster_id = cluster["id"]

        if cluster_id and best_similarity >= DEDUP_THRESHOLD:
            conn.execute(
                """
                UPDATE question_clusters
                SET frequency = frequency + 1, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (cluster_id,),
            )
        else:
            cluster_id = new_id("cluster")
            best_similarity = 1.0
            conn.execute(
                """
                INSERT INTO question_clusters
                (id, session_id, representative_question, representative_embedding, frequency)
                VALUES (?, ?, ?, ?, 1)
                """,
                (cluster_id, session_id, text, encode_vector(vector)),
            )

        question_id = new_id("question")
        conn.execute(
            """
            INSERT INTO questions (id, session_id, message_id, cluster_id, text, embedding, similarity)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (question_id, session_id, message_id, cluster_id, text, encode_vector(vector), best_similarity),
        )
    return {"id": question_id, "cluster_id": cluster_id, "similarity": best_similarity}


def _can_merge_questions(left: str, right: str) -> bool:
    left_norm = normalize_text(left)
    right_norm = normalize_text(right)
    conflict_pairs = [
        ("fine-tuning", "vector database"),
        ("temperature", "chi phí"),
        ("hội thoại", "token"),
    ]
    for first, second in conflict_pairs:
        left_has_first = first in left_norm
        right_has_first = first in right_norm
        left_has_second = second in left_norm
        right_has_second = second in right_norm
        if left_has_first != right_has_first and left_has_second != right_has_second:
            return False
    return True


def add_transcript(session_id: str, source: str, text: str) -> dict[str, Any]:
    chunks = chunk_text(text, max_words=58, overlap=10)
    with get_conn() as conn:
        conn.execute("DELETE FROM transcript_chunks WHERE session_id = ? AND source = ?", (session_id, source))
        for index, chunk in enumerate(chunks):
            conn.execute(
                """
                INSERT INTO transcript_chunks (id, session_id, source, chunk_index, text, embedding)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (new_id("chunk"), session_id, source, index, chunk, encode_vector(embedding(chunk))),
            )
    return {"session_id": session_id, "source": source, "chunks": len(chunks)}


def _question_details(session_id: str) -> dict[str, list[dict[str, Any]]]:
    with get_conn() as conn:
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
    details: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        details.setdefault(row["cluster_id"], []).append(row_to_dict(row))
    return details


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _enrich_cluster(cluster: dict[str, Any], details: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    cluster["retrieval_context"] = json.loads(cluster["retrieval_context"])
    question_rows = details.get(cluster["id"], [])
    cluster["askers"] = _unique([row["display_name"] or row["user_id"] for row in question_rows])
    cluster["sample_questions"] = _unique([row["text"] for row in question_rows])[:4]
    cluster["student_questions"] = [
        {
            "text": row["text"],
            "display_name": row["display_name"] or row["user_id"] or "Học viên",
            "user_id": row["user_id"],
            "created_at": row["created_at"],
        }
        for row in question_rows
    ]
    return cluster


def retrieve_context(session_id: str, cluster_id: str, question_vector: list[float], top_k: int) -> list[dict[str, Any]]:
    contexts: list[dict[str, Any]] = []
    with get_conn() as conn:
        transcript_rows = conn.execute(
            """
            SELECT id, source, chunk_index, text, embedding
            FROM transcript_chunks
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchall()
        chat_rows = conn.execute(
            """
            SELECT m.id, m.display_name, m.role, m.content, m.embedding
            FROM messages m
            WHERE m.session_id = ?
              AND m.id NOT IN (SELECT message_id FROM questions WHERE session_id = ? AND cluster_id = ?)
              AND (m.is_question = 0 OR m.role != 'student')
            ORDER BY m.rowid
            """,
            (session_id, session_id, cluster_id),
        ).fetchall()

    for row in transcript_rows:
        score = cosine_similarity(question_vector, decode_vector(row["embedding"]))
        contexts.append(
            {
                "id": row["id"],
                "kind": "transcript",
                "source": row["source"],
                "speaker": "Giảng viên",
                "chunk_index": row["chunk_index"],
                "text": row["text"],
                "score": round(score, 4),
            }
        )

    for row in chat_rows:
        row_vector = decode_vector(row["embedding"]) if row["embedding"] and row["embedding"] != "[]" else embedding(row["content"])
        score = cosine_similarity(question_vector, row_vector)
        contexts.append(
            {
                "id": row["id"],
                "kind": "chat_reply",
                "source": "chat",
                "speaker": row["display_name"],
                "role": row["role"],
                "text": row["content"],
                "score": round(score, 4),
            }
        )

    return sorted(contexts, key=lambda item: item["score"], reverse=True)[:top_k]


def _stored_vector_dim(raw: str | None) -> int:
    if not raw or raw == "[]":
        return 0
    try:
        return len(decode_vector(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return 0


def refresh_session_embeddings(session_id: str) -> dict[str, Any]:
    target_dim = len(embedding("kiem tra kich thuoc embedding cho VLearn Tutor"))
    tables = [
        ("messages", "content", "embedding"),
        ("questions", "text", "embedding"),
        ("question_clusters", "representative_question", "representative_embedding"),
        ("transcript_chunks", "text", "embedding"),
    ]
    refreshed: dict[str, int] = {}

    for table, text_column, embedding_column in tables:
        with get_conn() as conn:
            rows = conn.execute(
                f"""
                SELECT id, {text_column} AS source_text, {embedding_column} AS stored_embedding
                FROM {table}
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchall()

        pending = [
            {"id": row["id"], "text": row["source_text"]}
            for row in rows
            if _stored_vector_dim(row["stored_embedding"]) != target_dim
        ]
        refreshed[table] = len(pending)
        if not pending:
            continue

        vectors = embedding_many([item["text"] for item in pending])
        with get_conn() as conn:
            conn.executemany(
                f"UPDATE {table} SET {embedding_column} = ? WHERE id = ?",
                [
                    (encode_vector(vector), item["id"])
                    for item, vector in zip(pending, vectors)
                ],
            )

    return {
        "target_dimension": target_dim,
        "refreshed": refreshed,
        "changed_total": sum(refreshed.values()),
    }


def process_session(session_id: str, top_k: int = 5) -> list[dict[str, Any]]:
    with get_conn() as conn:
        clusters = conn.execute(
            "SELECT * FROM question_clusters WHERE session_id = ?",
            (session_id,),
        ).fetchall()

    work_items = []
    for cluster in clusters:
        question_vector = decode_vector(cluster["representative_embedding"])
        contexts = retrieve_context(session_id, cluster["id"], question_vector, top_k)
        work_items.append(
            {
                "cluster_id": cluster["id"],
                "question": cluster["representative_question"],
                "contexts": contexts,
            }
        )

    answers = answer_status_many(work_items)

    processed = []
    for item, answer in zip(work_items, answers):
        status, confidence, evidence = answer
        result_id = new_id("answer")
        with get_conn() as conn:
            conn.execute(
                """
                UPDATE question_clusters
                SET status = ?, confidence = ?, retrieval_context = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status, confidence, json.dumps(item["contexts"], ensure_ascii=False), item["cluster_id"]),
            )
            conn.execute(
                """
                INSERT INTO answer_results (id, session_id, cluster_id, status, confidence, evidence)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (result_id, session_id, item["cluster_id"], status, confidence, evidence),
            )
        processed.append(get_cluster(session_id, item["cluster_id"]))
    return processed


def get_cluster(session_id: str, cluster_id: str) -> dict[str, Any]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM question_clusters WHERE session_id = ? AND id = ?",
            (session_id, cluster_id),
        ).fetchone()
    details = _question_details(session_id)
    return _enrich_cluster(row_to_dict(row), details)


def _status_rank(status: str) -> int:
    return {"UNANSWERED": 0, "PARTIALLY_ANSWERED": 1, "ANSWERED": 2}.get(status, 3)


def _matching_row(cluster: dict[str, Any]) -> dict[str, Any]:
    contexts = cluster["retrieval_context"]
    chat_best = max((item["score"] for item in contexts if item["kind"] == "chat_reply"), default=0)
    transcript_best = max((item["score"] for item in contexts if item["kind"] == "transcript"), default=0)
    return {
        "question": cluster["representative_question"],
        "has_chat_answer": cluster["status"] == "ANSWERED" and chat_best >= transcript_best,
        "has_transcript_answer": cluster["status"] == "ANSWERED" and transcript_best >= chat_best,
        "chat_score": round(chat_best, 2),
        "transcript_score": round(transcript_best, 2),
        "status": cluster["status"],
    }


def _email_preview(final_list: list[dict[str, Any]]) -> str:
    lines = [
        "Tiêu đề: [AI Summary] Câu hỏi chưa được giải đáp - Lớp AI Fundamentals",
        "",
        "Dear Teacher,",
        "Dưới đây là danh sách các câu hỏi thật của học viên chưa được trả lời rõ ràng trong buổi học hôm nay:",
    ]
    for item in final_list:
        askers = ", ".join(item["askers"])
        lines.append(f"{item['rank']}. {item['question']} ({item['frequency']} lượt hỏi) - {askers}")
    lines.append("")
    lines.append("Hệ thống đã loại các câu hỏi có bằng chứng trả lời trong chat hoặc transcript.")
    return "\n".join(lines)


def dashboard(session_id: str) -> dict[str, Any]:
    with get_conn() as conn:
        session_row = conn.execute(
            "SELECT * FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        clusters = [
            row_to_dict(row)
            for row in conn.execute(
                """
                SELECT * FROM question_clusters
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchall()
        ]
        messages = [
            row_to_dict(row)
            for row in conn.execute(
                """
                SELECT id, session_id, user_id, display_name, role, content, is_question, created_at
                FROM messages
                WHERE session_id = ?
                ORDER BY rowid
                """,
                (session_id,),
            ).fetchall()
        ]
        chunks = [
            row_to_dict(row)
            for row in conn.execute(
                "SELECT id, source, chunk_index, text FROM transcript_chunks WHERE session_id = ? ORDER BY chunk_index",
                (session_id,),
            ).fetchall()
        ]
        vector_counts = row_to_dict(
            conn.execute(
                """
                SELECT
                  (SELECT COUNT(*) FROM messages WHERE session_id = ? AND embedding != '[]') AS message_embeddings,
                  (SELECT COUNT(*) FROM questions WHERE session_id = ? AND embedding != '[]') AS question_embeddings,
                  (SELECT COUNT(*) FROM question_clusters WHERE session_id = ? AND representative_embedding != '[]') AS cluster_embeddings,
                  (SELECT COUNT(*) FROM transcript_chunks WHERE session_id = ? AND embedding != '[]') AS transcript_embeddings
                """,
                (session_id, session_id, session_id, session_id),
            ).fetchone()
        )

    details = _question_details(session_id)
    enriched = [_enrich_cluster(cluster, details) for cluster in clusters]
    enriched.sort(key=lambda item: (_status_rank(item["status"]), -item["frequency"], item["confidence"]))
    for cluster in enriched:
        cluster.pop("representative_embedding", None)

    answered = [item for item in enriched if item["status"] == "ANSWERED"]
    unresolved = [item for item in enriched if item["status"] != "ANSWERED"]
    final_list = [
        {
            "rank": index,
            "question": cluster["representative_question"],
            "frequency": cluster["frequency"],
            "askers": cluster["askers"],
            "status": cluster["status"],
            "confidence": cluster["confidence"],
        }
        for index, cluster in enumerate(unresolved, start=1)
    ]
    chat_context = [
        {
            "question": cluster["representative_question"],
            "replies": [
                item
                for item in cluster["retrieval_context"]
                if item["kind"] == "chat_reply" and item["score"] >= 0.05
            ][:3],
        }
        for cluster in unresolved
    ]

    return {
        "session_id": session_id,
        "meeting": row_to_dict(session_row) if session_row else None,
        "summary": {
            "chat_messages": len(messages),
            "detected_questions": sum(cluster["frequency"] for cluster in enriched),
            "question_clusters": len(enriched),
            "answered": len(answered),
            "unresolved": len(unresolved),
            "transcript_chunks": len(chunks),
            "embeddings": vector_counts,
        },
        "messages": messages,
        "clusters": enriched,
        "answered_clusters": answered,
        "unresolved_ranking": unresolved,
        "chat_context": chat_context,
        "transcript_chunks": chunks,
        "matching_table": [_matching_row(cluster) for cluster in enriched],
        "final_send_list": final_list,
        "email_preview": _email_preview(final_list),
        "auto_send": {
            "channel": "email",
            "status": "ready" if final_list else "nothing_to_send",
            "requires_human_hitl": False,
        },
    }


def report(session_id: str) -> str:
    data = dashboard(session_id)
    lines = [
        "# VLearn Tutor CP3 Report",
        "",
        f"Session: {session_id}",
        f"Chat messages: {data['summary']['chat_messages']}",
        f"Detected questions: {data['summary']['detected_questions']}",
        f"Answered removed: {data['summary']['answered']}",
        f"Final unresolved questions: {data['summary']['unresolved']}",
        "",
        "## Final list to send",
    ]
    for item in data["final_send_list"]:
        askers = ", ".join(item["askers"])
        lines.append(f"{item['rank']}. {item['question']} ({item['frequency']} lượt hỏi) - {askers}")
    lines.append("")
    lines.append("## Removed as answered")
    for cluster in data["answered_clusters"]:
        lines.append(f"- {cluster['representative_question']} ({cluster['frequency']} lượt hỏi)")
    lines.append("")
    lines.append("## Email preview")
    lines.append(data["email_preview"])
    return "\n".join(lines)
