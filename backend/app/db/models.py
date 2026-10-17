"""TRINETRA's memory: what you plan, what you actually do, and what it learns about you."""
from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class TaskStatus(StrEnum):
    PLANNED = "planned"
    STARTED = "started"
    DONE = "done"
    SKIPPED = "skipped"
    RESCHEDULED = "rescheduled"


class Goal(Base):
    """A long-term aim (e.g. 'Crack DSA interviews'), broken into tasks."""

    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    why: Mapped[str] = mapped_column(Text, default="")  # the reason — used by the mentor
    horizon: Mapped[str] = mapped_column(String(20), default="3m")  # 1w / 3m / 1y / 5y
    area: Mapped[str] = mapped_column(String(50), default="general")  # study, health, career...
    target_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    progress: Mapped[float] = mapped_column(Float, default=0.0)  # 0..1
    status: Mapped[str] = mapped_column(String(20), default="active")  # active / achieved / dropped
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    tasks: Mapped[list["Task"]] = relationship(back_populates="goal")
    milestones: Mapped[list["Milestone"]] = relationship(
        back_populates="goal", order_by="Milestone.position", cascade="all, delete-orphan"
    )


class Milestone(Base):
    """A checkpoint on the way to a goal (e.g. 'Finish 150 LeetCode problems')."""

    __tablename__ = "milestones"

    id: Mapped[int] = mapped_column(primary_key=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("goals.id"))
    title: Mapped[str] = mapped_column(String(200))
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    position: Mapped[int] = mapped_column(Integer, default=0)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    depends_on: Mapped[list | None] = mapped_column(JSON(none_as_null=True))  # milestone ids that come first (roadmaps)
    effort_hours: Mapped[float | None] = mapped_column(Float)  # study hours it needs (drives the roadmap forecast)

    goal: Mapped[Goal] = relationship(back_populates="milestones")


class Promise(Base):
    """Something you said you'd do ("50 LeetCode problems by Sunday"). TRINETRA holds you to it."""

    __tablename__ = "promises"

    id: Mapped[int] = mapped_column(primary_key=True)
    text: Mapped[str] = mapped_column(String(300))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open / kept / broken
    asked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Task(Base):
    """One block on the timetable."""

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(50), default="general")
    priority: Mapped[int] = mapped_column(Integer, default=3)  # 1 (low) .. 5 (critical)
    planned_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    planned_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actual_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default=TaskStatus.PLANNED)
    rating: Mapped[int | None] = mapped_column(Integer)  # how it went, 1..5
    recurrence: Mapped[str | None] = mapped_column(String(100))  # e.g. "daily", "weekdays", "mon,wed,fri"
    series_id: Mapped[str | None] = mapped_column(String(36), index=True)  # links repeats of one routine
    repeat_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # routine stops after this day
    notify: Mapped[str] = mapped_column(String(10), default="full")  # full (remind + check in) / remind / none
    nag_count: Mapped[int] = mapped_column(Integer, default=0)  # follow-up pings sent after the reminder
    reminded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    checkin_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    goal_id: Mapped[int | None] = mapped_column(ForeignKey("goals.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    goal: Mapped[Goal | None] = relationship(back_populates="tasks")


class Event(Base):
    """Everything that happens — the raw data the ML brain learns from."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(80), index=True)  # e.g. task.skipped, checkin.mood
    source: Mapped[str] = mapped_column(String(50), default="api")  # pwa, telegram, shortcut, n8n...
    payload: Mapped[dict] = mapped_column(JSON(none_as_null=True), default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Memory(Base):
    """Facts TRINETRA learns about you (profile, habits, promises)."""

    __tablename__ = "memories"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(30))  # profile, habit, promise, preference
    content: Mapped[str] = mapped_column(Text)
    importance: Mapped[int] = mapped_column(Integer, default=3)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PushSubscription(Base):
    """A device that receives TRINETRA's notifications (e.g. your iPhone's home-screen app)."""

    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    p256dh: Mapped[str] = mapped_column(Text)
    auth: Mapped[str] = mapped_column(Text)
    device: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WakeSession(Base):
    """One morning: when TRINETRA started waking you, how many re-rings, and how you did on the questions."""

    __tablename__ = "wake_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[str] = mapped_column(String(10), unique=True)  # local YYYY-MM-DD
    rings: Mapped[int] = mapped_column(Integer, default=0)
    first_ring_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    solved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    questions: Mapped[list] = mapped_column(JSON, default=list)  # [{"q": "17 × 3", "a": 51}]
    index: Mapped[int] = mapped_column(Integer, default=0)  # current question
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    wrong: Mapped[int] = mapped_column(Integer, default=0)
    last: Mapped[str] = mapped_column(String(10), default="start")  # start / correct / wrong / done
    pushes: Mapped[int] = mapped_column(Integer, default=0)
    last_push_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WeeklyReport(Base):
    """The Sunday-night report: numbers + six spoken chapters. Kept forever, compared week to week."""

    __tablename__ = "weekly_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    week_start: Mapped[str] = mapped_column(String(10), unique=True)  # Monday, local YYYY-MM-DD
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    sections: Mapped[list] = mapped_column(JSON, default=list)  # [{"title": ..., "text": ...}]
    status: Mapped[str] = mapped_column(String(12), default="writing")  # writing / ready
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KeyValue(Base):
    """Small persistent settings TRINETRA keeps (e.g. the mood mode you asked for)."""

    __tablename__ = "kv"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text)


class Message(Base):
    """Conversation history between you and TRINETRA."""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    role: Mapped[str] = mapped_column(String(20))  # user / trinetra
    content: Mapped[str] = mapped_column(Text)
    channel: Mapped[str] = mapped_column(String(30), default="api")
    mood: Mapped[str | None] = mapped_column(Text)  # TRINETRA's emotional mode when it spoke
    meta: Mapped[dict | None] = mapped_column(JSON(none_as_null=True))  # e.g. {"kind": "checkin", "task_id": 4, "buttons": [...]}
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ---------- portfolio visitors (the Eye on tarundeepreddy.com) ----------

class GuestVisit(Base):
    """One visitor talking to TRINETRA on the portfolio. The conversation is wiped when they leave;
    the log (name, company, topics) stays for Tarun."""

    __tablename__ = "guest_visits"

    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    ip: Mapped[str | None] = mapped_column(String(64))
    name: Mapped[str | None] = mapped_column(String(80))
    company: Mapped[str | None] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(160))
    phone: Mapped[str | None] = mapped_column(String(40))
    role: Mapped[str | None] = mapped_column(String(40))  # recruiter / engineer / researcher / founder / manager / student / other
    topics: Mapped[list | None] = mapped_column(JSON(none_as_null=True))  # short labels of what they asked
    messages: Mapped[list | None] = mapped_column(JSON(none_as_null=True))  # live conversation; None once forgotten
    turns: Mapped[int] = mapped_column(Integer, default=0)
    last_said: Mapped[str | None] = mapped_column(Text)  # what TRINETRA just said (the only text /guest/speak voices)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GuestAsk(Base):
    """'What is Tarun doing right now?' — relayed to Tarun's phone, answered live (or timed out)."""

    __tablename__ = "guest_asks"

    id: Mapped[int] = mapped_column(primary_key=True)
    visit_id: Mapped[int] = mapped_column(ForeignKey("guest_visits.id"))
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="waiting")  # waiting / answered / timeout
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    digested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GuestNote(Base):
    """A message a visitor left for Tarun (with their email) — goes into the nightly digest."""

    __tablename__ = "guest_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    visit_id: Mapped[int] = mapped_column(ForeignKey("guest_visits.id"))
    name: Mapped[str | None] = mapped_column(String(80))
    email: Mapped[str] = mapped_column(String(160))  # "" when they left only a phone number
    phone: Mapped[str | None] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    digested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AppOpen(Base):
    """A distracting app opened on the iPhone (reported by the Focus Guard automation)."""

    __tablename__ = "app_opens"

    id: Mapped[int] = mapped_column(primary_key=True)
    app: Mapped[str] = mapped_column(String(60), default="")
    kind: Mapped[str] = mapped_column(String(20))  # focus / class / sleep / free
    task_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    spoke: Mapped[bool] = mapped_column(Boolean, default=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class GuestReply(Base):
    """Tarun's reply to a portfolio visitor, written in the app; shown in their chat while they're on the site."""

    __tablename__ = "guest_replies"

    id: Mapped[int] = mapped_column(primary_key=True)
    visit_id: Mapped[int] = mapped_column(ForeignKey("guest_visits.id"))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Course(Base):
    """Something you're working through in order (TUF DSA, the ML Specialization). Its blocks get daily targets."""

    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(40), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    block_match: Mapped[str] = mapped_column(String(200))  # regex on block titles: these blocks work on this course
    goal_id: Mapped[int | None] = mapped_column(ForeignKey("goals.id"), nullable=True)
    per_block: Mapped[int] = mapped_column(Integer, default=1)  # items to finish in one block
    target_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # targets + proof start here
    starter: Mapped[bool] = mapped_column(Boolean, default=True)  # still my starter outline, not your real syllabus


class StudyItem(Base):
    """One lecture / problem set / week of a course, in order."""

    __tablename__ = "study_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    section: Mapped[str] = mapped_column(String(200), default="")
    title: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str | None] = mapped_column(String(60), nullable=True)  # dsa / dbms / lecture / lab / quiz …
    est_min: Mapped[int | None] = mapped_column(Integer, nullable=True)  # how long it should take
    planned_date: Mapped[str | None] = mapped_column(String(10), nullable=True)  # YYYY-MM-DD in the course's own plan
    optional: Mapped[bool] = mapped_column(Boolean, default=False)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    task_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # the block it was done in


class MoodEntry(Base):
    """How you felt, read from what you wrote (or said) — the Mood Tracker's log."""

    __tablename__ = "mood_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    mood: Mapped[str] = mapped_column(String(30))
    intensity: Mapped[float] = mapped_column(Float, default=0.0)
    source: Mapped[str] = mapped_column(String(20), default="chat")


class JournalEntry(Base):
    """A private journal entry. Never added to memories or shown anywhere but the 📓 screen."""

    __tablename__ = "journal_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    text: Mapped[str] = mapped_column(Text)
