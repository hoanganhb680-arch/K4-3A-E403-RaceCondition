from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
from pathlib import Path
from typing import Any

import httpx

from app.database import encode_vector, get_conn, row_to_dict
from app.services.ai import embedding
from app.services.pipeline import add_message, create_session, new_id, process_session


VIDEO_DIR = Path(__file__).resolve().parents[2] / "data" / "videos"
GEMINI_GENERATE_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_VIDEO_MODEL = "gemini-3.8-flash"
MAX_INLINE_VIDEO_BYTES = int(os.getenv("REALTIME_MAX_INLINE_VIDEO_MB", "20")) * 1024 * 1024


def save_realtime_video(
    session_id: str,
    file_name: str,
    content: bytes,
    mime_type: str | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^a-zA-Z0-9_.-]+", "_", file_name).strip("._") or "lecture.mp4"
    video_id = new_id("video")
    path = VIDEO_DIR / f"{video_id}_{safe_name}"
    path.write_bytes(content)
    mime = mime_type or mimetypes.guess_type(safe_name)[0] or "video/mp4"

    create_session(
        title or f"Realtime video - {safe_name}",
        session_id=session_id,
        course_title="Realtime Demo",
        platform="Video Realtime",
        status="running",
    )

    with get_conn() as conn:
        conn.execute(
            "DELETE FROM videos WHERE session_id = ?",
            (session_id,),
        )
        conn.execute(
            "DELETE FROM transcript_chunks WHERE session_id = ?",
            (session_id,),
        )
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
        conn.execute(
            "DELETE FROM messages WHERE session_id = ? AND source_type IN ('generated_video_question', 'manual_live_question')",
            (session_id,),
        )
        conn.execute(
            """
            INSERT INTO videos (id, session_id, file_path, file_name, mime_type, stt_status)
            VALUES (?, ?, ?, ?, ?, 'uploaded')
            """,
            (video_id, session_id, str(path), safe_name, mime),
        )

    return {
        "video_id": video_id,
        "session_id": session_id,
        "file_path": str(path),
        "file_name": safe_name,
        "mime_type": mime,
        "size_bytes": len(content),
    }


def analyze_video_with_gemini(session_id: str, video_id: str) -> dict[str, Any]:
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("Missing GEMINI_API_KEY")

    with get_conn() as conn:
        video = conn.execute(
            "SELECT * FROM videos WHERE id = ? AND session_id = ?",
            (video_id, session_id),
        ).fetchone()
    if not video:
        raise ValueError("Video not found")

    path = Path(video["file_path"])
    content = path.read_bytes()
    if len(content) > MAX_INLINE_VIDEO_BYTES:
        raise RuntimeError(
            f"Video is {len(content)} bytes, larger than inline limit {MAX_INLINE_VIDEO_BYTES}. "
            "Use a shorter demo clip for this realtime prototype."
        )

    prompt = """
Bạn là công cụ tạo dữ liệu realtime cho dashboard giảng viên.
Hãy đọc video bài giảng và trả duy nhất JSON hợp lệ, không markdown.
Schema:
{
  "duration_sec": number,
  "transcript_chunks": [
    {"start_sec": number, "end_sec": number, "speaker": "teacher", "text": "đoạn giảng ngắn"}
  ],
  "student_questions": [
    {"time_sec": number, "student": "S001", "question": "câu hỏi học viên có thể hỏi tại thời điểm này"}
  ]
}
Yêu cầu:
- transcript_chunks phải theo thứ tự thời gian, mỗi đoạn 8-20 giây.
- student_questions gồm 8-20 câu, bám nội dung video, có câu hỏi lặp ý tự nhiên.
- time_sec của câu hỏi phải nằm trong timeline video.
- Không bịa nội dung ngoài video.
"""
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "inline_data": {
                            "mime_type": video["mime_type"],
                            "data": base64.b64encode(content).decode("ascii"),
                        }
                    },
                    {"text": prompt},
                ],
            }
        ],
        "generationConfig": {
            "response_mime_type": "application/json",
            "temperature": 0.25,
        },
    }
    model = os.getenv("GEMINI_VIDEO_MODEL", DEFAULT_VIDEO_MODEL)
    response = httpx.post(
        GEMINI_GENERATE_URL.format(model=model),
        params={"key": api_key},
        json=payload,
        timeout=float(os.getenv("AI_TIMEOUT_SECONDS", "120")),
    )
    response.raise_for_status()
    result_text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
    result = _parse_json(result_text)
    return store_realtime_video_analysis(session_id, video_id, result)


def store_realtime_video_analysis(session_id: str, video_id: str, result: dict[str, Any]) -> dict[str, Any]:
    chunks = result.get("transcript_chunks", [])
    questions = result.get("student_questions", [])
    duration_sec = float(result.get("duration_sec") or 0)

    with get_conn() as conn:
        conn.execute(
            "DELETE FROM transcript_chunks WHERE session_id = ? AND video_id = ?",
            (session_id, video_id),
        )
        for index, chunk in enumerate(chunks):
            text = str(chunk.get("text", "")).strip()
            if not text:
                continue
            start_sec = _float_value(chunk.get("start_sec"), index * 12)
            end_sec = _float_value(chunk.get("end_sec"), start_sec + 12)
            conn.execute(
                """
                INSERT INTO transcript_chunks
                (id, session_id, source, chunk_index, text, embedding, segment_id,
                 transcript_order, source_type, video_id, start_sec, end_sec, speaker)
                VALUES (?, ?, 'video_upload', ?, ?, ?, ?, ?, 'video_transcript', ?, ?, ?, ?)
                """,
                (
                    new_id("chunk"),
                    session_id,
                    index,
                    text,
                    encode_vector(embedding(text)),
                    f"V{index + 1:03d}",
                    index,
                    video_id,
                    start_sec,
                    end_sec,
                    str(chunk.get("speaker") or "teacher"),
                ),
            )
        conn.execute(
            "UPDATE videos SET duration_sec = ?, stt_status = 'completed' WHERE id = ?",
            (duration_sec, video_id),
        )

    added_questions = 0
    for index, item in enumerate(questions):
        text = str(item.get("question", "")).strip()
        if not text:
            continue
        add_live_question(
            session_id=session_id,
            question=text,
            time_sec=_float_value(item.get("time_sec"), index * 24 + 10),
            student=str(item.get("student") or f"S{index + 1:03d}"),
            source_type="generated_video_question",
            process_after_add=False,
        )
        added_questions += 1

    process_session(session_id, top_k=5)
    return {
        "ok": True,
        "session_id": session_id,
        "video_id": video_id,
        "transcript_chunks": len(chunks),
        "generated_questions": added_questions,
        "duration_sec": duration_sec,
    }


def add_live_question(
    session_id: str,
    question: str,
    time_sec: float,
    student: str = "Live Student",
    source_type: str = "manual_live_question",
    process_after_add: bool = True,
) -> dict[str, Any]:
    create_session(
        "Realtime video",
        session_id=session_id,
        course_title="Realtime Demo",
        platform="Video Realtime",
        status="running",
    )
    result = add_message(
        session_id=session_id,
        user_id=student,
        content=question,
        display_name=student,
        role="student",
        source_type=source_type,
        event_time_sec=float(time_sec),
    )
    if process_after_add:
        process_session(session_id, top_k=5)
    return result


def _parse_json(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            raise
        return json.loads(match.group(0))


def _float_value(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)
