from __future__ import annotations

from pydantic import BaseModel, Field


class SessionCreate(BaseModel):
    id: str | None = None
    title: str = "AI Fundamentals"
    course_title: str = "AI Fundamentals"
    meeting_date: str = "2026-09-15"
    start_time: str = "09:00"
    end_time: str = "10:30"
    platform: str = "VLearn Live"
    status: str = "scheduled"


class MessageCreate(BaseModel):
    user_id: str = "student_demo"
    display_name: str | None = None
    role: str = "student"
    content: str = Field(min_length=1)


class TranscriptCreate(BaseModel):
    source: str = "live_transcript"
    text: str = Field(min_length=1)


class ProcessRequest(BaseModel):
    top_k: int = Field(default=5, ge=1, le=10)


class ImportVLearnRequest(BaseModel):
    pack_dir: str | None = None
    session_id: str = "vlearn-pack"
    max_turns: int = Field(default=240, ge=10, le=2000)
    cohort_hint: str = "K4"
    include_presets: bool = False
    transcript_limit: int = Field(default=3, ge=1, le=6)
    process_after_import: bool = True


class SummarizeRequest(BaseModel):
    session_id: str = "vlearn-pack"
    teacher_id: str = "teacher"
    top_k: int = Field(default=10, ge=3, le=30)


class ClusterOut(BaseModel):
    id: str
    representative_question: str
    frequency: int
    status: str
    confidence: float
    askers: list[str]
    retrieval_context: list[dict]
