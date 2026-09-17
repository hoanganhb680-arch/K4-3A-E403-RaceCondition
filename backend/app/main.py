from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from app.database import init_db
from app.schemas import ImportVLearnRequest, MessageCreate, ProcessRequest, SessionCreate, SummarizeRequest, TranscriptCreate
from app.seed_demo import seed_demo
from app.services.ai import ai_runtime_status
from app.services.pipeline import add_message, add_transcript, create_session, dashboard, process_session, report
from app.services.teacher_flow import create_question_summary, ensure_default_workspace, get_question_summary, list_question_summaries, list_teacher_schedule
from app.services.vlearn_importer import import_vlearn_pack


app = FastAPI(title="VLearn Tutor CP3 API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict:
    return {"ok": True, "ai": ai_runtime_status()}


@app.post("/sessions")
def create_session_endpoint(payload: SessionCreate) -> dict:
    return create_session(
        payload.title,
        payload.id,
        payload.course_title,
        payload.meeting_date,
        payload.start_time,
        payload.end_time,
        payload.platform,
        payload.status,
    )


@app.post("/sessions/{session_id}/messages")
def add_message_endpoint(session_id: str, payload: MessageCreate) -> dict:
    create_session("Auto-created session", session_id)
    return add_message(session_id, payload.user_id, payload.content, payload.display_name, payload.role)


@app.post("/sessions/{session_id}/transcript")
def add_transcript_endpoint(session_id: str, payload: TranscriptCreate) -> dict:
    create_session("Auto-created session", session_id)
    return add_transcript(session_id, payload.source, payload.text)


@app.post("/sessions/{session_id}/process")
def process_endpoint(session_id: str, payload: ProcessRequest) -> dict:
    create_session("Auto-created session", session_id)
    return {"clusters": process_session(session_id, payload.top_k)}


@app.post("/demo/seed")
def seed_demo_endpoint() -> dict:
    seed_demo()
    return {"ok": True, "session_id": "ai-fundamentals"}


@app.post("/data/import-vlearn")
def import_vlearn_endpoint(payload: ImportVLearnRequest) -> dict:
    return import_vlearn_pack(
        pack_dir=payload.pack_dir,
        session_id=payload.session_id,
        max_turns=payload.max_turns,
        cohort_hint=payload.cohort_hint,
        include_presets=payload.include_presets,
        transcript_limit=payload.transcript_limit,
        process_after_import=payload.process_after_import,
    )


@app.get("/teacher/workspace")
def teacher_workspace_endpoint(session_id: str = "vlearn-pack") -> dict:
    return ensure_default_workspace(session_id=session_id)


@app.get("/teacher/schedule")
def teacher_schedule_endpoint() -> dict:
    return list_teacher_schedule()


@app.post("/teacher/summarize")
def teacher_summarize_endpoint(payload: SummarizeRequest) -> dict:
    return create_question_summary(payload.session_id, payload.teacher_id, payload.top_k)


@app.get("/teacher/summaries")
def teacher_summaries_endpoint(session_id: str | None = None) -> list[dict]:
    return list_question_summaries(session_id)


@app.get("/teacher/summaries/{summary_id}")
def teacher_summary_endpoint(summary_id: str) -> dict:
    try:
        return get_question_summary(summary_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Summary not found") from exc


@app.get("/sessions/{session_id}/dashboard")
def dashboard_endpoint(session_id: str) -> dict:
    try:
        return dashboard(session_id)
    except TypeError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc


@app.get("/sessions/{session_id}/report", response_class=PlainTextResponse)
def report_endpoint(session_id: str) -> str:
    return report(session_id)
