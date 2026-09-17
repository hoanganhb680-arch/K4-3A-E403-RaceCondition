"use client";

import {
  AlertCircle,
  Archive,
  Bot,
  CalendarDays,
  ChevronDown,
  CheckCircle2,
  Clock3,
  Crown,
  History,
  Layers,
  MessageSquare,
  Pause,
  Play,
  Radio,
  RefreshCw,
  Search,
  Send,
  Sparkles,
  Video,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const DEFAULT_SESSION_ID = "vlearn-pack";

type Meeting = {
  id: string;
  title: string;
  course_title: string;
  meeting_date: string;
  start_time: string;
  end_time: string;
  platform: string;
  status: string;
  chat_messages?: number;
  question_clusters?: number;
  saved_summaries?: number;
};

type ScheduleDay = {
  date: string;
  meetings: Meeting[];
};

type Message = {
  id: string;
  display_name: string;
  role: "student" | "teacher" | "assistant";
  content: string;
  is_question: number;
  event_time?: string | null;
  lecture_code?: string | null;
  lecture_title?: string | null;
  source_type?: string | null;
};

type Cluster = {
  id: string;
  representative_question: string;
  frequency: number;
  status: "NEEDS_TEACHER_REVIEW" | "MONITOR" | "AI_TUTOR_HANDLED";
  confidence: number;
  priority_score?: number;
  attention_reason?: string;
  askers: string[];
  sample_questions: string[];
};

type WorkspaceData = {
  session_id: string;
  meeting: Meeting | null;
  summary: {
    chat_messages: number;
    detected_questions: number;
    question_clusters: number;
    answered: number;
    unresolved: number;
    ai_tutor_handled?: number;
    needs_teacher_attention?: number;
    transcript_chunks: number;
  };
  messages: Message[];
  clusters: Cluster[];
};

type SavedSummaryListItem = {
  id: string;
  session_id: string;
  title: string;
  top_k: number;
  total_clusters: number;
  item_count: number;
  created_at: string;
  meeting_title?: string;
  course_title?: string;
  meeting_date?: string;
  start_time?: string;
  end_time?: string;
  platform?: string;
};

type StudentQuestion = {
  text: string;
  display_name: string;
  user_id: string;
  created_at: string;
  event_time?: string | null;
  lecture_code?: string | null;
  lecture_title?: string | null;
};

type SummaryItem = {
  id: string;
  rank: number;
  cluster_id: string;
  question: string;
  frequency: number;
  askers: string[];
  sample_questions: string[];
  student_questions?: StudentQuestion[];
  status: Cluster["status"];
  confidence: number;
  priority_score?: number;
  attention_reason?: string;
};

type SavedSummary = SavedSummaryListItem & {
  teacher_id: string;
  items: SummaryItem[];
  meeting: Meeting | null;
  saved_to: {
    database: string;
    tables: string[];
  };
};

type RealtimeQuestion = StudentQuestion & {
  question_id: string;
  cluster_id: string;
  time_sec: number;
};

type RealtimeTranscriptChunk = {
  id: string;
  source: string;
  chunk_index: number;
  text: string;
  start_sec: number;
  end_sec: number;
};

type RealtimeData = {
  session_id: string;
  meeting: Meeting | null;
  elapsed_sec: number;
  total_duration_sec: number;
  progress: number;
  summary: {
    visible_questions: number;
    visible_clusters: number;
    visible_transcript_chunks: number;
    total_questions: number;
    total_clusters: number;
    total_transcript_chunks: number;
  };
  live_questions: RealtimeQuestion[];
  live_clusters: (Cluster & { student_questions?: RealtimeQuestion[] })[];
  live_transcript: RealtimeTranscriptChunk[];
};

type View = "schedule" | "chat" | "realtime" | "summary" | "history";

function shortText(text: string, limit = 240) {
  return text.length > limit ? `${text.slice(0, limit).trim()}...` : text;
}

function formatTime(value?: string) {
  return value ? value.replace("T", " ").slice(0, 16) : "";
}

function formatDate(value?: string) {
  if (!value) return "";
  const date = new Date(`${value}T00:00:00`);
  return date.toLocaleDateString("vi-VN", {
    weekday: "long",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

function formatDuration(value: number | null) {
  if (value === null) return "0.0s";
  return `${(value / 1000).toFixed(1)}s`;
}

function formatSeconds(value: number) {
  const minutes = Math.floor(value / 60);
  const seconds = Math.max(0, Math.floor(value % 60));
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

function cleanQuestionText(text: string) {
  return text
    .replace(/^\(Đang học phần [“"][^”"]+[”"] của buổi này\)\s*/u, "")
    .replace(/\s+/g, " ")
    .trim();
}

function statusLabel(status: Cluster["status"]) {
  if (status === "NEEDS_TEACHER_REVIEW") return "Cần giảng viên xem";
  if (status === "MONITOR") return "Theo dõi";
  return "AI tutor đã trả lời";
}

export default function Dashboard() {
  const [view, setView] = useState<View>("schedule");
  const [schedule, setSchedule] = useState<ScheduleDay[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState(DEFAULT_SESSION_ID);
  const [workspace, setWorkspace] = useState<WorkspaceData | null>(null);
  const [summaries, setSummaries] = useState<SavedSummaryListItem[]>([]);
  const [currentSummary, setCurrentSummary] = useState<SavedSummary | null>(null);
  const [busy, setBusy] = useState(false);
  const [summarizing, setSummarizing] = useState(false);
  const [summaryElapsedMs, setSummaryElapsedMs] = useState(0);
  const [lastSummaryDurationMs, setLastSummaryDurationMs] = useState<number | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [showDetectedQuestions, setShowDetectedQuestions] = useState(false);
  const [expandedSummaryItemId, setExpandedSummaryItemId] = useState<string | null>(null);
  const [topK, setTopK] = useState(10);
  const [message, setMessage] = useState("Em muốn hỏi lại phần này có giống câu hỏi nào trước đó không?");
  const [realtime, setRealtime] = useState<RealtimeData | null>(null);
  const [realtimeElapsedSec, setRealtimeElapsedSec] = useState(0);
  const [realtimeRunning, setRealtimeRunning] = useState(false);
  const [realtimeSessionId, setRealtimeSessionId] = useState("realtime-video");
  const [videoFile, setVideoFile] = useState<File | null>(null);
  const [videoBusy, setVideoBusy] = useState(false);
  const [videoError, setVideoError] = useState<string | null>(null);
  const [liveQuestion, setLiveQuestion] = useState("Em chưa hiểu phần này, giảng viên giải thích lại được không?");

  const meetings = useMemo(() => schedule.flatMap((day) => day.meetings), [schedule]);
  const selectedMeeting = workspace?.meeting ?? meetings.find((item) => item.id === selectedSessionId) ?? null;
  const messages = workspace?.messages ?? [];
  const questions = useMemo(() => messages.filter((item) => item.is_question), [messages]);

  async function refreshSchedule() {
    const response = await fetch(`${API_URL}/teacher/schedule`);
    if (response.ok) {
      const data = await response.json();
      setSchedule(data.days ?? []);
    }
  }

  async function refreshWorkspace(sessionId = selectedSessionId) {
    const response = await fetch(`${API_URL}/teacher/workspace?session_id=${sessionId}`);
    if (response.ok) {
      setWorkspace(await response.json());
    }
  }

  async function refreshSummaries() {
    const response = await fetch(`${API_URL}/teacher/summaries`);
    if (response.ok) {
      setSummaries(await response.json());
    }
  }

  async function refreshRealtime(sessionId = realtimeSessionId, elapsedSec = realtimeElapsedSec) {
    const response = await fetch(`${API_URL}/teacher/realtime?session_id=${sessionId}&elapsed_sec=${elapsedSec}&top_k=${topK}`);
    if (response.ok) {
      setRealtime(await response.json());
    }
  }

  async function uploadRealtimeVideo() {
    if (!videoFile) return;
    setVideoBusy(true);
    setVideoError(null);
    const form = new FormData();
    form.append("file", videoFile);
    form.append("session_id", realtimeSessionId);
    form.append("title", videoFile.name);
    form.append("analyze", "true");
    try {
      const response = await fetch(`${API_URL}/teacher/realtime/video`, {
        method: "POST",
        body: form,
      });
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        setVideoError(error.detail ?? "Không xử lý được video.");
      } else {
        setRealtimeElapsedSec(0);
        setRealtimeRunning(false);
        await refreshRealtime(realtimeSessionId, 0);
        await refreshSchedule();
      }
    } catch {
      setVideoError("Không kết nối được backend khi upload video.");
    } finally {
      setVideoBusy(false);
    }
  }

  async function sendLiveQuestion() {
    if (!liveQuestion.trim()) return;
    setBusy(true);
    await fetch(`${API_URL}/teacher/realtime/questions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: realtimeSessionId,
        question: liveQuestion,
        time_sec: realtimeElapsedSec,
        student: "Manual Student",
      }),
    });
    setLiveQuestion("");
    await refreshRealtime(realtimeSessionId, realtimeElapsedSec);
    setBusy(false);
  }

  async function loadEverything() {
    setBusy(true);
    await refreshSchedule();
    await refreshWorkspace(selectedSessionId);
    await refreshSummaries();
    setBusy(false);
  }

  async function selectMeeting(sessionId: string) {
    setBusy(true);
    setSelectedSessionId(sessionId);
    setCurrentSummary(null);
    setShowDetectedQuestions(false);
    setExpandedSummaryItemId(null);
    setLastSummaryDurationMs(null);
    setSummaryError(null);
    await refreshWorkspace(sessionId);
    await refreshRealtime(sessionId, 0);
    setView("chat");
    setBusy(false);
  }

  async function summarizeQuestions() {
    setBusy(true);
    setSummarizing(true);
    setLastSummaryDurationMs(null);
    setSummaryError(null);
    setSummaryElapsedMs(0);
    const startedAt = performance.now();
    try {
      const response = await fetch(`${API_URL}/teacher/summarize`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: selectedSessionId,
          teacher_id: "teacher",
          top_k: topK,
        }),
      });
      if (response.ok) {
        const summary = await response.json();
        setCurrentSummary(summary);
        setShowDetectedQuestions(false);
        setExpandedSummaryItemId(null);
        setView("summary");
        await refreshWorkspace(selectedSessionId);
        await refreshSchedule();
        await refreshSummaries();
      } else {
        setSummaryError("Tổng hợp chưa thành công. Kiểm tra Gemini API key hoặc thử lại sau.");
      }
    } catch {
      setSummaryError("Không kết nối được backend khi tổng hợp.");
    } finally {
      const duration = performance.now() - startedAt;
      setSummaryElapsedMs(duration);
      setLastSummaryDurationMs(duration);
      setSummarizing(false);
      setBusy(false);
    }
  }

  async function openSummary(summaryId: string) {
    setBusy(true);
    const response = await fetch(`${API_URL}/teacher/summaries/${summaryId}`);
    if (response.ok) {
      const summary = await response.json();
      setCurrentSummary(summary);
      setShowDetectedQuestions(false);
      setExpandedSummaryItemId(null);
      setSelectedSessionId(summary.session_id);
      await refreshWorkspace(summary.session_id);
      setView("summary");
    }
    setBusy(false);
  }

  async function sendMessage() {
    if (!message.trim()) return;
    setBusy(true);
    await fetch(`${API_URL}/sessions/${selectedSessionId}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        user_id: "live_student",
        display_name: "Live Student",
        role: "student",
        content: message,
      }),
    });
    setMessage("");
    await refreshWorkspace(selectedSessionId);
    await refreshSchedule();
    setBusy(false);
  }

  useEffect(() => {
    loadEverything();
  }, []);

  useEffect(() => {
    if (view !== "realtime") return;
    refreshRealtime(realtimeSessionId, realtimeElapsedSec);
  }, [view, realtimeSessionId]);

  useEffect(() => {
    if (!realtimeRunning) return;
    const timer = window.setInterval(() => {
      setRealtimeElapsedSec((value) => {
        const next = value + 5;
        refreshRealtime(realtimeSessionId, next);
        return next;
      });
    }, 1000);
    return () => window.clearInterval(timer);
  }, [realtimeRunning, realtimeSessionId, topK]);

  useEffect(() => {
    if (!summarizing) return;
    const startedAt = performance.now() - summaryElapsedMs;
    const timer = window.setInterval(() => {
      setSummaryElapsedMs(performance.now() - startedAt);
    }, 250);
    return () => window.clearInterval(timer);
  }, [summarizing]);

  return (
    <main className="teacherApp">
      <aside className="sidebar">
        <div className="brandBlock">
          <span><Bot size={22} /></span>
          <div>
            <strong>VLearn Tutor</strong>
            <small>Tài khoản: Giảng viên</small>
          </div>
        </div>

        <nav>
          <button className={view === "schedule" ? "active" : ""} onClick={() => setView("schedule")}>
            <CalendarDays size={16} /> Thời khóa biểu
          </button>
          <button className={view === "chat" ? "active" : ""} onClick={() => setView("chat")}>
            <MessageSquare size={16} /> Chat lớp học
          </button>
          <button className={view === "realtime" ? "active" : ""} onClick={() => setView("realtime")}>
            <Radio size={16} /> Realtime demo
          </button>
          <button className={view === "summary" ? "active" : ""} onClick={() => setView("summary")}>
            <Crown size={16} /> Tổng hợp mới nhất
          </button>
          <button className={view === "history" ? "active" : ""} onClick={() => setView("history")}>
            <History size={16} /> Xem lại đã lưu
          </button>
        </nav>

        <div className="storageCard">
          <Archive size={17} />
          <div>
            <strong>Lưu trong SQLite</strong>
            <span>Mỗi bản tổng hợp gắn với `session_id`, ngày học, lượt hỏi và AI tutor reply.</span>
          </div>
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <p className="eyebrow">Teacher Flow</p>
            {selectedMeeting && (
              <div className="meetingContext">
                <Video size={15} />
                <span>{selectedMeeting.title}</span>
                <span>{formatDate(selectedMeeting.meeting_date)}</span>
                <span>{selectedMeeting.start_time} - {selectedMeeting.end_time}</span>
              </div>
            )}
          </div>
          <div className="topbarActions">
            <button className="ghostButton" onClick={loadEverything} disabled={busy}>
              <RefreshCw size={15} /> Làm mới
            </button>
            <label>
              Top K
              <input type="number" min={3} max={30} value={topK} onChange={(event) => setTopK(Number(event.target.value))} />
            </label>
            <button className="primaryButton" onClick={summarizeQuestions} disabled={busy || !selectedMeeting}>
              {summarizing ? <RefreshCw className="spinIcon" size={16} /> : <Sparkles size={16} />}
              {summarizing ? `Đang tổng hợp... ${formatDuration(summaryElapsedMs)}` : "Tổng hợp nhóm cần chú ý"}
            </button>
          </div>
        </header>

        {(summarizing || lastSummaryDurationMs !== null || summaryError) && (
          <section className={`processingNotice ${summaryError ? "error" : summarizing ? "running" : "done"}`}>
            {summaryError ? <AlertCircle size={18} /> : summarizing ? <RefreshCw className="spinIcon" size={18} /> : <CheckCircle2 size={18} />}
            <div>
              <strong>{summaryError ? "Tổng hợp bị lỗi" : summarizing ? "Đang tổng hợp câu hỏi" : "Tổng hợp hoàn tất"}</strong>
              <span>
                {summaryError
                  ? summaryError
                  : summarizing
                  ? `Đã chạy ${formatDuration(summaryElapsedMs)}`
                  : `Hoàn tất trong ${formatDuration(lastSummaryDurationMs)}`}
              </span>
            </div>
          </section>
        )}

        {view !== "schedule" && (
          <section className="metricGrid">
            <div><MessageSquare size={18} /><strong>{view === "realtime" ? realtime?.summary.visible_questions ?? 0 : workspace?.summary.chat_messages ?? 0}</strong><span>{view === "realtime" ? "câu hỏi đã xuất hiện" : "tin nhắn trong meeting"}</span></div>
            <div><Search size={18} /><strong>{view === "realtime" ? realtime?.summary.total_questions ?? 0 : workspace?.summary.detected_questions ?? 0}</strong><span>{view === "realtime" ? "tổng câu hỏi demo" : "câu hỏi phát hiện"}</span></div>
            <div><Layers size={18} /><strong>{view === "realtime" ? realtime?.summary.visible_clusters ?? 0 : workspace?.summary.question_clusters ?? 0}</strong><span>nhóm câu hỏi</span></div>
            <div><Archive size={18} /><strong>{view === "realtime" ? formatSeconds(realtimeElapsedSec) : workspace?.summary.needs_teacher_attention ?? 0}</strong><span>{view === "realtime" ? "thời gian demo" : "nhóm cần giảng viên chú ý"}</span></div>
          </section>
        )}

        {view === "schedule" && (
          <section className="scheduleLayout">
            {schedule.map((day) => (
              <article className="panel dayPanel" key={day.date}>
                <div className="panelHeader">
                  <div>
                    <h2>{formatDate(day.date)}</h2>
                    <p>{day.meetings.length} cuộc họp trong ngày</p>
                  </div>
                </div>
                <div className="meetingList">
                  {day.meetings.map((meeting) => (
                    <button
                      className={`meetingButton ${meeting.id === selectedSessionId ? "active" : ""}`}
                      key={meeting.id}
                      onClick={() => selectMeeting(meeting.id)}
                    >
                      <div>
                        <strong>{meeting.title}</strong>
                        <span>{meeting.start_time} - {meeting.end_time} · {meeting.platform}</span>
                        <em>{meeting.chat_messages ?? 0} tin chat · {meeting.question_clusters ?? 0} cụm · {meeting.saved_summaries ?? 0} bản lưu</em>
                      </div>
                      <Video size={18} />
                    </button>
                  ))}
                </div>
              </article>
            ))}
          </section>
        )}

        {view === "chat" && (
          <section className="chatLayout singleColumn">
            <article className="panel chatPanel">
              <div className="panelHeader">
                <div>
                  <h2>Chat lớp học</h2>
                  <p>{selectedMeeting ? `${formatDate(selectedMeeting.meeting_date)} · ${selectedMeeting.start_time} - ${selectedMeeting.end_time}` : "Chọn cuộc họp từ thời khóa biểu."}</p>
                </div>
                <span className="liveBadge">{selectedMeeting?.status === "completed" ? "ĐÃ DIỄN RA" : "MEETING"}</span>
              </div>
              <div className="messageList">
                {messages.slice(-30).map((item) => (
                  <div className={`messageItem ${item.role}`} key={item.id}>
                    <span>{item.display_name.slice(0, 1).toUpperCase()}</span>
                    <div>
                      <strong>{item.display_name}</strong>
                      <p>{shortText(item.content, 360)}</p>
                    </div>
                  </div>
                ))}
                {messages.length === 0 && (
                  <div className="emptyState small">
                    <MessageSquare size={32} />
                    <strong>Cuộc họp này chưa có chat</strong>
                    <span>Chọn meeting có dữ liệu hoặc thêm một câu hỏi thử.</span>
                  </div>
                )}
              </div>
              <div className="composer">
                <input value={message} onChange={(event) => setMessage(event.target.value)} placeholder="Thêm câu hỏi học viên..." />
                <button onClick={sendMessage} disabled={busy || !message.trim()}><Send size={16} /></button>
              </div>
            </article>

          </section>
        )}

        {view === "realtime" && (
          <section className="summaryLayout">
            <article className="panel tierPanel">
              <div className="panelHeader">
                <div>
                  <h2>Realtime teacher dashboard</h2>
                  <p>Upload video, Gemini tạo transcript/câu hỏi theo timestamp, rồi dashboard cập nhật theo timeline.</p>
                </div>
                <div className="topbarActions compact">
                  <button
                    className="ghostButton"
                    onClick={() => {
                      setRealtimeElapsedSec(0);
                      setRealtimeRunning(false);
                      refreshRealtime(realtimeSessionId, 0);
                    }}
                  >
                    <RefreshCw size={15} /> Reset
                  </button>
                  <button className="primaryButton" onClick={() => setRealtimeRunning((value) => !value)}>
                    {realtimeRunning ? <Pause size={16} /> : <Play size={16} />}
                    {realtimeRunning ? "Tạm dừng" : "Chạy demo"}
                  </button>
                </div>
              </div>

              <div className="realtimeSetup">
                <label>
                  Session
                  <input value={realtimeSessionId} onChange={(event) => setRealtimeSessionId(event.target.value)} />
                </label>
                <label>
                  Video
                  <input type="file" accept="video/*,audio/*" onChange={(event) => setVideoFile(event.target.files?.[0] ?? null)} />
                </label>
                <button className="ghostButton" disabled={!videoFile || videoBusy} onClick={uploadRealtimeVideo}>
                  {videoBusy ? <RefreshCw className="spinIcon" size={15} /> : <Video size={15} />}
                  {videoBusy ? "Đang phân tích..." : "Upload & phân tích"}
                </button>
              </div>
              {videoError && (
                <section className="processingNotice error">
                  <AlertCircle size={18} />
                  <div>
                    <strong>Video chưa xử lý được</strong>
                    <span>{videoError}</span>
                  </div>
                </section>
              )}

              <div className="realtimeProgress">
                <span>{formatSeconds(realtimeElapsedSec)}</span>
                <div>
                  <i style={{ width: `${Math.min((realtime?.progress ?? 0) * 100, 100)}%` }} />
                </div>
                <span>{formatSeconds(realtime?.total_duration_sec ?? 0)}</span>
              </div>

              <div className="tierList">
                {(realtime?.live_clusters ?? []).map((cluster, index) => (
                  <div className="tierItem" key={cluster.id}>
                    <div className="tierItemMain static">
                      <span className="rank">#{index + 1}</span>
                      <div>
                        <strong>{cleanQuestionText(cluster.representative_question) || cluster.representative_question}</strong>
                        <p>{cluster.frequency} lượt hỏi đã xuất hiện · {cluster.askers?.slice(0, 5).join(", ")}</p>
                        <small>{statusLabel(cluster.status)}{cluster.attention_reason ? ` · ${cluster.attention_reason}` : ""}</small>
                        {cluster.sample_questions?.length > 0 && (
                          <em>Một vài câu hỏi: {cluster.sample_questions.map(cleanQuestionText).slice(0, 2).join(" · ")}</em>
                        )}
                      </div>
                      <span className="tierAction">
                        <span className={`status ${cluster.status}`}>{cluster.frequency}</span>
                      </span>
                    </div>
                  </div>
                ))}
                {(realtime?.live_clusters ?? []).length === 0 && (
                  <div className="emptyState">
                    <Radio size={38} />
                    <strong>Chưa có câu hỏi trong timeline</strong>
                    <span>Bấm “Chạy demo” để câu hỏi và cụm ưu tiên xuất hiện theo thời gian.</span>
                  </div>
                )}
              </div>
            </article>

            <article className="panel savedInfoPanel">
              <div className="panelHeader">
                <div>
                  <h2>Live stream</h2>
                  <p>Câu hỏi và transcript đang mở khóa theo thời gian demo.</p>
                </div>
              </div>
              <div className="liveFeed">
                <strong>Nhập câu hỏi live</strong>
                <div className="liveQuestionComposer">
                  <input value={liveQuestion} onChange={(event) => setLiveQuestion(event.target.value)} placeholder="Nhập câu hỏi học viên tại thời điểm hiện tại..." />
                  <button onClick={sendLiveQuestion} disabled={busy || !liveQuestion.trim()}><Send size={15} /></button>
                </div>
                <strong>Câu hỏi mới nhất</strong>
                {(realtime?.live_questions ?? []).slice(-6).reverse().map((question) => (
                  <div key={question.question_id}>
                    <span>{formatSeconds(question.time_sec)} · {question.display_name}</span>
                    <p>{cleanQuestionText(question.text) || question.text}</p>
                  </div>
                ))}
                <strong>Transcript gần nhất</strong>
                {(realtime?.live_transcript ?? []).slice(-4).reverse().map((chunk) => (
                  <div key={chunk.id}>
                    <span>{formatSeconds(chunk.start_sec)} - {formatSeconds(chunk.end_sec)}</span>
                    <p>{shortText(chunk.text, 180)}</p>
                  </div>
                ))}
              </div>
            </article>
          </section>
        )}

        {view === "summary" && (
          <section className="summaryLayout">
            <article className="panel tierPanel">
              <div className="panelHeader">
                <div>
                  <h2>Top {currentSummary?.top_k ?? topK} nhóm câu hỏi cần chú ý</h2>
                  <p>{currentSummary?.meeting ? `${formatDate(currentSummary.meeting.meeting_date)} · ${currentSummary.meeting.title}` : "Mỗi dòng là một nhóm câu hỏi có cùng ý và đã đối chiếu với AI tutor reply."}</p>
                </div>
                {currentSummary && <span className="savedBadge">Đã lưu SQLite</span>}
              </div>

              {!currentSummary ? (
                <div className="emptyState">
                  <Sparkles size={38} />
                  <strong>Chưa có bản tổng hợp trong cuộc họp này</strong>
                  <span>Bấm “Tổng hợp nhóm cần chú ý” trong meeting để tạo tier list.</span>
                </div>
              ) : (
                <div className="tierList">
                  {currentSummary.items.map((item) => {
                    const isExpanded = expandedSummaryItemId === item.id;
                    const studentQuestions = item.student_questions ?? [];
                    const questionRows: StudentQuestion[] = studentQuestions.length
                      ? studentQuestions
                      : item.sample_questions.map((text) => ({
                          text,
                          display_name: "Học viên",
                          user_id: "",
                          created_at: "",
                        }));
                    const displayQuestion = cleanQuestionText(item.question) || item.question;
                    const previewQuestions = item.sample_questions
                      .map(cleanQuestionText)
                      .filter((text) => text && text !== displayQuestion)
                      .slice(0, 2);

                    return (
                      <div className={`tierItem ${isExpanded ? "expanded" : ""}`} key={item.id}>
                        <button
                          className="tierItemMain"
                          type="button"
                          aria-expanded={isExpanded}
                          onClick={() => setExpandedSummaryItemId(isExpanded ? null : item.id)}
                        >
                          <span className="rank">#{item.rank}</span>
                          <div>
                            <strong>{displayQuestion}</strong>
                            <p>
                              {item.frequency} lượt hỏi cùng ý
                              {item.askers.length > 0 ? ` · ${item.askers.slice(0, 6).join(", ")}` : ""}
                            </p>
                            <small>{statusLabel(item.status)}{item.attention_reason ? ` · ${item.attention_reason}` : ""}</small>
                            {previewQuestions.length > 0 && (
                              <em>Một vài cách học viên đã hỏi: {previewQuestions.join(" · ")}</em>
                            )}
                          </div>
                          <span className="tierAction">
                            <span className={`status ${item.status}`}>{item.frequency}</span>
                            <ChevronDown className={isExpanded ? "open" : ""} size={17} />
                          </span>
                        </button>

                        {isExpanded && (
                          <div className="studentQuestionList">
                            <div className="studentQuestionHeader">
                              <strong>{questionRows.length || item.frequency} câu hỏi học viên đã gửi</strong>
                              <span>{item.askers.length} người hỏi</span>
                            </div>
                            {questionRows.map((question, index) => (
                              <div className="studentQuestionRow" key={`${item.id}-${index}-${question.text}`}>
                                <span>{index + 1}</span>
                                <div>
                                  <strong>{question.display_name || question.user_id || "Học viên"}</strong>
                                  {(question.event_time || question.lecture_title) && (
                                    <em>{[question.event_time, question.lecture_title].filter(Boolean).join(" · ")}</em>
                                  )}
                                  <p>{cleanQuestionText(question.text) || question.text}</p>
                                </div>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </article>

            <article className="panel savedInfoPanel">
              <div className="panelHeader">
                <div>
                  <h2>Thông tin bản lưu</h2>
                  <p>Mở tab “Xem lại đã lưu” để truy vấn theo ngày và cuộc họp.</p>
                </div>
              </div>
              <div className="storageDetail">
                <Archive size={24} />
                <strong>SQLite</strong>
                <span>`messages` giữ `turn_id`, `asked_at_vn`, lecture và AI tutor reply.</span>
                <span>`summary_items`: từng nhóm câu hỏi cần giảng viên xem lại trong top-K.</span>
              </div>
              {currentSummary && (
                <div className="summaryMeta">
                  <div><Clock3 size={15} /> Tạo lúc {formatTime(currentSummary.created_at)}</div>
                  <div><CalendarDays size={15} /> {formatDate(currentSummary.meeting?.meeting_date)}</div>
                  <div><Video size={15} /> {currentSummary.meeting?.start_time} - {currentSummary.meeting?.end_time}</div>
                  <div><Layers size={15} /> {currentSummary.items.length} nhóm top / {currentSummary.total_clusters} nhóm đã gom</div>
                  <div><CheckCircle2 size={15} /> ID: {currentSummary.id}</div>
                </div>
              )}
            </article>

            {currentSummary && (
              <article className="panel detectedTogglePanel">
                <div className="panelHeader">
                  <div>
                    <h2>Câu hỏi đã detect</h2>
                    <p>Giảng viên có thể mở danh sách này nếu muốn kiểm tra dữ liệu đầu vào.</p>
                  </div>
                  <button className="ghostButton" onClick={() => setShowDetectedQuestions((value) => !value)}>
                    {showDetectedQuestions ? "Ẩn đi" : "Xem danh sách"}
                  </button>
                </div>
                {showDetectedQuestions && (
                  <div className="questionList">
                    {questions.map((item) => (
                      <div key={item.id}>
                        <strong>{item.display_name}</strong>
                        <p>{shortText(item.content, 220)}</p>
                      </div>
                    ))}
                    {questions.length === 0 && (
                      <div className="emptyState small">
                        <Search size={32} />
                        <strong>Chưa có câu hỏi detect</strong>
                        <span>Cuộc họp này chưa có câu hỏi học viên.</span>
                      </div>
                    )}
                  </div>
                )}
              </article>
            )}
          </section>
        )}

        {view === "history" && (
          <section className="historyLayout">
            <article className="panel">
              <div className="panelHeader">
                <div>
                  <h2>Lịch sử tổng hợp đã lưu</h2>
                  <p>Danh sách này truy vấn được bản lưu thuộc cuộc họp nào và ngày nào.</p>
                </div>
              </div>
              <div className="historyList">
                {summaries.map((summary) => (
                  <button key={summary.id} onClick={() => openSummary(summary.id)}>
                    <div>
                      <strong>{summary.meeting_title ?? summary.title}</strong>
                      <span>{formatDate(summary.meeting_date)} · {summary.start_time} - {summary.end_time} · {summary.item_count} nhóm</span>
                      <em>{summary.title} · {summary.total_clusters} nhóm đã gom</em>
                    </div>
                    <Crown size={18} />
                  </button>
                ))}
                {summaries.length === 0 && (
                  <div className="emptyState small">
                    <History size={32} />
                    <strong>Chưa có lịch sử</strong>
                    <span>Bấm tổng hợp câu hỏi trong một cuộc họp để tạo bản lưu đầu tiên.</span>
                  </div>
                )}
              </div>
            </article>
          </section>
        )}
      </section>
    </main>
  );
}
