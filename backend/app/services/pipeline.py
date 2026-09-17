from __future__ import annotations

import json
import re
import uuid
from typing import Any

from app.database import decode_vector, encode_vector, get_conn, row_to_dict
from app.services.ai import chunk_text, cosine_similarity, embedding, embedding_many, is_question, normalize_text, teacher_attention_status_many, tokenize


DEDUP_THRESHOLD = 0.62
SHORT_QUESTION_DEDUP_THRESHOLD = 0.82
SAME_TOPIC_DEDUP_THRESHOLD = 0.34
SAME_TOPIC_SHORT_QUESTION_THRESHOLD = 0.55

TOPIC_GROUPS = {
    "course_access": (
        "github",
        "git",
        "repo",
        "repository",
        "email",
        "liên kết",
        "tai khoản",
        "tài khoản",
        "notebook",
        "colab",
        "lab",
        "bài tập",
        "tệp",
        "file",
        "thư mục",
        "link",
        "không mở",
        "truy cập",
        "nguồn",
        "slide",
    ),
    "model_identity": ("what model", "model are you", "gpt", "claude", "gemini", "mô hình nào", "model gì"),
    "ai_ml": ("machine learning", "ai", "ml", "deep learning", "bốn làn sóng", "lan sóng", "supervised", "unsupervised", "học có giám sát", "không giám sát"),
    "llm": ("llm", "large language model", "ngôn ngữ lớn", "chatgpt", "generative ai", "gen ai", "generative model", "transformer", "sinh văn bản"),
    "rag": ("rag", "retrieval", "fine-tuning", "fine tune", "vector database", "embedding"),
    "prompt": ("prompt", "system prompt", "token", "context window", "temperature", "top-p"),
    "data_labeling": ("label", "nhãn", "ground truth", "lidar", "mask", "polygon", "gán nhãn", "yolo", "yolo11", "object detection", "xe tự lái", "bàn cờ", "othello"),
    "agent": ("agent", "agentic", "tool", "reasoning", "state", "memory"),
    "sqlite": ("sqlite", "postgres", "pgvector", "database", "cơ sở dữ liệu"),
    "frontend": ("frontend", "ui", "dashboard", "giao diện", "deploy"),
}


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
    turn_id: str | None = None,
    event_time: str | None = None,
    lecture_code: str | None = None,
    lecture_title: str | None = None,
    course_id: str | None = None,
    reply_ms: int | None = None,
    rating: str | None = None,
    move_used: str | None = None,
    source_type: str = "live_chat",
    event_time_sec: float | None = None,
) -> dict[str, Any]:
    clean_role = role if role in {"student", "teacher", "assistant"} else "student"
    question_flag = clean_role == "student" and is_question(content)
    message_vector = embedding(content)
    message_id = new_id("msg")
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO messages
            (id, session_id, user_id, display_name, role, content, embedding, is_question,
             turn_id, event_time, lecture_code, lecture_title, course_id, reply_ms, rating, move_used, source_type,
             event_time_sec)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                turn_id,
                event_time,
                lecture_code,
                lecture_title,
                course_id,
                reply_ms,
                rating,
                move_used,
                source_type,
                event_time_sec,
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
        "turn_id": turn_id,
        "event_time": event_time,
        "lecture_code": lecture_code,
        "lecture_title": lecture_title,
        "course_id": course_id,
        "reply_ms": reply_ms,
        "rating": rating,
        "move_used": move_used,
        "source_type": source_type,
        "event_time_sec": event_time_sec,
    }


def upsert_question(session_id: str, message_id: str, text: str) -> dict[str, Any]:
    question_text = canonical_question_text(text)
    vector = embedding(question_text)
    cluster_id = None
    best_similarity = 0.0
    with get_conn() as conn:
        clusters = conn.execute(
            "SELECT * FROM question_clusters WHERE session_id = ?",
            (session_id,),
        ).fetchall()
        for cluster in clusters:
            similarity = cosine_similarity(vector, decode_vector(cluster["representative_embedding"]))
            threshold = _dedup_threshold(question_text, cluster["representative_question"])
            if (
                similarity >= threshold
                and similarity > best_similarity
                and _can_merge_questions(question_text, cluster["representative_question"])
            ):
                best_similarity = similarity
                cluster_id = cluster["id"]

        if cluster_id:
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
                (id, session_id, representative_question, representative_embedding, frequency, status)
                VALUES (?, ?, ?, ?, 1, 'NEEDS_TEACHER_REVIEW')
                """,
                (cluster_id, session_id, question_text, encode_vector(vector)),
            )

        question_id = new_id("question")
        conn.execute(
            """
            INSERT INTO questions (id, session_id, message_id, cluster_id, text, embedding, similarity, event_time_sec)
            VALUES (?, ?, ?, ?, ?, ?, ?, (SELECT event_time_sec FROM messages WHERE id = ?))
            """,
            (question_id, session_id, message_id, cluster_id, question_text, encode_vector(vector), best_similarity, message_id),
        )
    return {"id": question_id, "cluster_id": cluster_id, "similarity": best_similarity}


def canonical_question_text(text: str) -> str:
    clean = " ".join((text or "").split()).strip()
    clean = re.sub(r"^\(Đang học phần [“\"][^”\"]+[”\"] của buổi này\)\s*", "", clean, flags=re.I)
    clean = re.sub(r"^\(Currently on the part [“\"][^”\"]+[”\"] of this lesson\)\s*", "", clean, flags=re.I)
    clean = re.sub(r"^\(Trang\s+\d+,\s*đoạn được chọn:\s*[“\"].*?[”\"]\)\s*", "", clean, flags=re.I)
    clean = re.sub(r"^\([^)]{0,240}(đang học phần|currently on the part|đoạn được chọn|trang\s+\d+)[^)]*\)\s*", "", clean, flags=re.I)
    if len(clean) > 260 and "?" in clean:
        before_last_question_mark = clean.rsplit("?", 1)[0]
        tail_question = before_last_question_mark.split("?")[-1].strip(" .:;,-–—")
        if 3 <= len(tail_question.split()) <= 24:
            return f"{tail_question}?"
    return clean or text


def _topic_tags(text: str) -> set[str]:
    clean = canonical_question_text(text)
    raw = clean.lower()
    normalized = normalize_text(clean)
    tags = {
        topic
        for topic, keywords in TOPIC_GROUPS.items()
        if any(keyword in raw or keyword in normalized for keyword in keywords)
    }
    if "model" in normalized and "machine learning" not in normalized and "mô hình" not in normalized:
        tags.add("model_identity")
    return tags


def _dedup_threshold(left: str, right: str) -> float:
    left_topics = _topic_tags(left)
    right_topics = _topic_tags(right)
    shortest_len = min(len(tokenize(left)), len(tokenize(right)))
    if left_topics and right_topics and left_topics & right_topics:
        if shortest_len <= 4:
            return SAME_TOPIC_SHORT_QUESTION_THRESHOLD
        return SAME_TOPIC_DEDUP_THRESHOLD
    if shortest_len <= 4:
        return SHORT_QUESTION_DEDUP_THRESHOLD
    if set(tokenize(left)) & set(tokenize(right)):
        return 0.56
    return DEDUP_THRESHOLD


def _can_merge_questions(left: str, right: str) -> bool:
    left_clean = canonical_question_text(left)
    right_clean = canonical_question_text(right)
    left_norm = normalize_text(left_clean)
    right_norm = normalize_text(right_clean)
    left_topics = _topic_tags(left_clean)
    right_topics = _topic_tags(right_clean)
    if left_topics and right_topics and not (left_topics & right_topics):
        return False

    left_tokens = set(tokenize(left_clean))
    right_tokens = set(tokenize(right_clean))
    shared_tokens = left_tokens & right_tokens
    shortest_len = min(len(left_tokens), len(right_tokens))
    if shortest_len <= 4 and not shared_tokens and not (left_topics & right_topics):
        return False

    conflict_pairs = [
        ("fine-tuning", "vector database"),
        ("temperature", "chi phí"),
        ("hội thoại", "token"),
        ("github", "machine learning"),
        ("github", "llm"),
        ("github", "model"),
        ("email", "machine learning"),
        ("email", "llm"),
        ("ai", "github"),
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
                INSERT INTO transcript_chunks
                (id, session_id, source, chunk_index, text, embedding, transcript_order, source_type, start_sec, end_sec)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'lecture_transcript', ?, ?)
                """,
                (
                    new_id("chunk"),
                    session_id,
                    source,
                    index,
                    chunk,
                    encode_vector(embedding(chunk)),
                    index,
                    index * 8,
                    index * 8 + 8,
                ),
            )
    return {"session_id": session_id, "source": source, "chunks": len(chunks)}


def _question_details(session_id: str) -> dict[str, list[dict[str, Any]]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT q.cluster_id, q.text, m.display_name, m.user_id, m.created_at,
                   m.turn_id, m.event_time, m.lecture_code, m.lecture_title, m.course_id,
                   m.reply_ms, m.rating, m.move_used, m.source_type
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
            "turn_id": row["turn_id"],
            "event_time": row["event_time"],
            "lecture_code": row["lecture_code"],
            "lecture_title": row["lecture_title"],
            "course_id": row["course_id"],
            "reply_ms": row["reply_ms"],
            "rating": row["rating"],
            "move_used": row["move_used"],
            "source_type": row["source_type"],
        }
        for row in question_rows
    ]
    return cluster


def retrieve_context(
    session_id: str,
    cluster_id: str,
    question_vector: list[float],
    top_k: int,
    question_turn_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    contexts: list[dict[str, Any]] = []
    with get_conn() as conn:
        transcript_rows = conn.execute(
            """
            SELECT id, source, chunk_index, text, embedding, segment_id, transcript_order, source_type
            FROM transcript_chunks
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchall()
        chat_rows = conn.execute(
            """
            SELECT m.id, m.display_name, m.role, m.content, m.embedding,
                   m.turn_id, m.event_time, m.lecture_code, m.lecture_title, m.course_id,
                   m.reply_ms, m.rating, m.move_used, m.source_type
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
                "segment_id": row["segment_id"],
                "transcript_order": row["transcript_order"],
                "source_type": row["source_type"],
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
                "turn_id": row["turn_id"],
                "event_time": row["event_time"],
                "lecture_code": row["lecture_code"],
                "lecture_title": row["lecture_title"],
                "course_id": row["course_id"],
                "reply_ms": row["reply_ms"],
                "rating": row["rating"],
                "move_used": row["move_used"],
                "source_type": row["source_type"],
                "same_turn_reply": bool(row["turn_id"] and row["turn_id"] in (question_turn_ids or set())),
                "text": row["content"],
                "score": round(score, 4),
            }
        )

    ranked = sorted(contexts, key=lambda item: item["score"], reverse=True)
    same_turn_replies = [item for item in ranked if item.get("same_turn_reply")]
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in same_turn_replies + ranked:
        item_id = str(item["id"])
        if item_id in seen:
            continue
        seen.add(item_id)
        result.append(item)
        if len(result) >= top_k + len(same_turn_replies):
            break
    return result


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


def _refresh_cluster_representatives(session_id: str) -> None:
    with get_conn() as conn:
        cluster_rows = conn.execute(
            "SELECT id FROM question_clusters WHERE session_id = ?",
            (session_id,),
        ).fetchall()
        for cluster_row in cluster_rows:
            question_rows = conn.execute(
                """
                SELECT text, embedding
                FROM questions
                WHERE session_id = ? AND cluster_id = ?
                """,
                (session_id, cluster_row["id"]),
            ).fetchall()
            if not question_rows:
                continue
            if len(question_rows) == 1:
                best_text = question_rows[0]["text"]
                best_embedding = question_rows[0]["embedding"]
            else:
                decoded = [
                    (row["text"], decode_vector(row["embedding"]))
                    for row in question_rows
                ]
                best_text, best_vector = max(
                    decoded,
                    key=lambda item: sum(cosine_similarity(item[1], other[1]) for other in decoded) / len(decoded),
                )
                best_embedding = encode_vector(best_vector)
            conn.execute(
                """
                UPDATE question_clusters
                SET representative_question = ?, representative_embedding = ?, frequency = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (best_text, best_embedding, len(question_rows), cluster_row["id"]),
            )


def rebuild_question_clusters(session_id: str, process_after_rebuild: bool = True) -> dict[str, Any]:
    with get_conn() as conn:
        message_rows = conn.execute(
            """
            SELECT id, content
            FROM messages
            WHERE session_id = ? AND role = 'student' AND is_question = 1
            ORDER BY rowid
            """,
            (session_id,),
        ).fetchall()
        conn.execute(
            "DELETE FROM question_summaries WHERE session_id = ?",
            (session_id,),
        )
        conn.execute(
            "DELETE FROM answer_results WHERE session_id = ?",
            (session_id,),
        )
        conn.execute(
            "DELETE FROM questions WHERE session_id = ?",
            (session_id,),
        )
        conn.execute(
            "DELETE FROM question_clusters WHERE session_id = ?",
            (session_id,),
        )

    for row in message_rows:
        upsert_question(session_id, row["id"], row["content"])

    _refresh_cluster_representatives(session_id)
    processed = process_session(session_id, top_k=5) if process_after_rebuild else []
    return {
        "ok": True,
        "session_id": session_id,
        "questions": len(message_rows),
        "clusters": len(processed) if process_after_rebuild else _cluster_count(session_id),
        "processed": process_after_rebuild,
    }


def _cluster_count(session_id: str) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS total FROM question_clusters WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    return int(row["total"]) if row else 0


def process_session(session_id: str, top_k: int = 5) -> list[dict[str, Any]]:
    _refresh_cluster_representatives(session_id)
    with get_conn() as conn:
        clusters = conn.execute(
            "SELECT * FROM question_clusters WHERE session_id = ?",
            (session_id,),
        ).fetchall()

    details = _question_details(session_id)
    work_items = []
    for cluster in clusters:
        question_vector = decode_vector(cluster["representative_embedding"])
        question_rows = details.get(cluster["id"], [])
        question_turn_ids = {
            row["turn_id"]
            for row in question_rows
            if row.get("turn_id")
        }
        contexts = retrieve_context(session_id, cluster["id"], question_vector, top_k, question_turn_ids)
        work_items.append(
            {
                "cluster_id": cluster["id"],
                "question": cluster["representative_question"],
                "frequency": cluster["frequency"],
                "student_questions": question_rows,
                "contexts": contexts,
            }
        )

    answers = teacher_attention_status_many(work_items)

    processed = []
    for item, answer in zip(work_items, answers):
        status, priority_score, evidence = answer
        result_id = new_id("answer")
        with get_conn() as conn:
            conn.execute(
                """
                UPDATE question_clusters
                SET status = ?, confidence = ?, priority_score = ?, attention_reason = ?,
                    retrieval_context = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    status,
                    priority_score,
                    priority_score,
                    evidence,
                    json.dumps(item["contexts"], ensure_ascii=False),
                    item["cluster_id"],
                ),
            )
            conn.execute(
                """
                INSERT INTO answer_results (id, session_id, cluster_id, status, confidence, evidence)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (result_id, session_id, item["cluster_id"], status, priority_score, evidence),
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
    return {"NEEDS_TEACHER_REVIEW": 0, "MONITOR": 1, "AI_TUTOR_HANDLED": 2}.get(status, 3)


def _matching_row(cluster: dict[str, Any]) -> dict[str, Any]:
    contexts = cluster["retrieval_context"]
    chat_best = max((item["score"] for item in contexts if item["kind"] == "chat_reply"), default=0)
    transcript_best = max((item["score"] for item in contexts if item["kind"] == "transcript"), default=0)
    return {
        "question": cluster["representative_question"],
        "has_ai_tutor_reply": any(
            item["kind"] == "chat_reply" and item.get("role") == "assistant"
            for item in contexts
        ),
        "has_same_turn_tutor_reply": any(item.get("same_turn_reply") for item in contexts),
        "has_transcript_context": transcript_best > 0,
        "chat_score": round(chat_best, 2),
        "transcript_score": round(transcript_best, 2),
        "status": cluster["status"],
    }


def _email_preview(final_list: list[dict[str, Any]]) -> str:
    lines = [
        "Tiêu đề: [AI Summary] Nhóm câu hỏi cần giảng viên chú ý - Lớp AI Fundamentals",
        "",
        "Dear Teacher,",
        "Dưới đây là các nhóm câu hỏi học viên hỏi nhiều hoặc có dấu hiệu cần giảng viên nhắc lại:",
    ]
    for item in final_list:
        askers = ", ".join(item["askers"])
        lines.append(f"{item['rank']}. {item['question']} ({item['frequency']} lượt hỏi) - {askers}")
    lines.append("")
    lines.append("Ghi chú: chatlog VLearn đã có AI tutor reply; danh sách này ưu tiên câu cần giảng viên xem lại, không phải câu thiếu AI reply.")
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
                SELECT id, session_id, user_id, display_name, role, content, is_question,
                       turn_id, event_time, lecture_code, lecture_title, course_id,
                       reply_ms, rating, move_used, source_type, created_at
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
                """
                SELECT id, source, chunk_index, text, segment_id, transcript_order, source_type
                FROM transcript_chunks
                WHERE session_id = ?
                ORDER BY source, chunk_index
                """,
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
    enriched.sort(key=lambda item: (_status_rank(item["status"]), -item["frequency"], -item["priority_score"]))
    for cluster in enriched:
        cluster.pop("representative_embedding", None)

    handled = [item for item in enriched if item["status"] == "AI_TUTOR_HANDLED"]
    needs_attention = [item for item in enriched if item["status"] != "AI_TUTOR_HANDLED"]
    final_list = [
        {
            "rank": index,
            "question": cluster["representative_question"],
            "frequency": cluster["frequency"],
            "askers": cluster["askers"],
            "status": cluster["status"],
            "confidence": cluster["confidence"],
        }
        for index, cluster in enumerate(needs_attention, start=1)
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
        for cluster in needs_attention
    ]

    return {
        "session_id": session_id,
        "meeting": row_to_dict(session_row) if session_row else None,
        "summary": {
            "chat_messages": len(messages),
            "detected_questions": sum(cluster["frequency"] for cluster in enriched),
            "question_clusters": len(enriched),
            "answered": len(handled),
            "unresolved": len(needs_attention),
            "ai_tutor_handled": len(handled),
            "needs_teacher_attention": len(needs_attention),
            "transcript_chunks": len(chunks),
            "embeddings": vector_counts,
        },
        "messages": messages,
        "clusters": enriched,
        "answered_clusters": handled,
        "unresolved_ranking": needs_attention,
        "ai_tutor_handled_clusters": handled,
        "needs_teacher_attention": needs_attention,
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
        f"AI tutor handled: {data['summary']['ai_tutor_handled']}",
        f"Needs teacher attention: {data['summary']['needs_teacher_attention']}",
        "",
        "## Priority list for teacher",
    ]
    for item in data["final_send_list"]:
        askers = ", ".join(item["askers"])
        lines.append(f"{item['rank']}. {item['question']} ({item['frequency']} lượt hỏi) - {askers}")
    lines.append("")
    lines.append("## Lower priority because AI tutor handled")
    for cluster in data["ai_tutor_handled_clusters"]:
        lines.append(f"- {cluster['representative_question']} ({cluster['frequency']} lượt hỏi)")
    lines.append("")
    lines.append("## Email preview")
    lines.append(data["email_preview"])
    return "\n".join(lines)
