from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import mood as mood_modes
from app.core import push, timetable, voice
from app.core.orchestrator import IncomingEvent, Orchestrator
from app.core.timeutil import day_bounds_utc, from_db, local, now_local, to_utc, user_tz
from app.db.models import Goal, Memory, Message, PushSubscription, Task, TaskStatus
from app.db.session import get_db

router = APIRouter()


def get_orchestrator(request: Request) -> Orchestrator:
    return request.app.state.orchestrator


# ---------- talking to TRINETRA ----------

class ChatIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    channel: str = "api"


class DispatchOut(BaseModel):
    reply: str | None
    mood: str | None
    spoke: str | None
    ran: list[str]
    actions: list[dict[str, Any]]
    notes: dict[str, Any]


@router.post("/chat", response_model=DispatchOut)
async def chat(body: ChatIn, db: Session = Depends(get_db), core: Orchestrator = Depends(get_orchestrator)):
    result = await core.dispatch(
        IncomingEvent(type="user.message", payload={"text": body.text}, source=body.channel), db
    )
    return DispatchOut(**result.__dict__)


class EventIn(BaseModel):
    type: str = Field(pattern=r"^[a-z_]+(\.[a-z_]+)+$")  # e.g. shortcut.app_opened
    payload: dict[str, Any] = {}
    source: str = "api"


@router.post("/events", response_model=DispatchOut)
async def ingest_event(body: EventIn, db: Session = Depends(get_db), core: Orchestrator = Depends(get_orchestrator)):
    """Single entry point for n8n, iOS Shortcuts, the WhatsApp bridge and the PWA."""
    result = await core.dispatch(IncomingEvent(type=body.type, payload=body.payload, source=body.source), db)
    return DispatchOut(**result.__dict__)


# ---------- agents ----------

@router.get("/agents")
def list_agents(core: Orchestrator = Depends(get_orchestrator)):
    councils = core.registry.councils()
    specs = list(core.registry.specs.values())
    return {
        "total": len(specs),
        "active": sum(s.status == "active" for s in specs),
        "councils": {
            name: [
                {"id": s.id, "name": s.name, "role": s.role, "kind": s.kind, "status": s.status, "phase": s.phase}
                for s in members
            ]
            for name, members in councils.items()
        },
    }


# ---------- timetable ----------

class TaskBase(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    planned_start: datetime
    planned_end: datetime
    category: str = "general"
    priority: int = Field(3, ge=1, le=5)
    recurrence: str | None = None
    goal_id: int | None = None


class TaskIn(TaskBase):
    @field_validator("planned_start", "planned_end")
    @classmethod
    def utc(cls, v: datetime) -> datetime:
        return to_utc(v)

    @model_validator(mode="after")
    def end_after_start(self):
        if self.planned_end <= self.planned_start:
            raise ValueError("planned_end must be after planned_start")
        return self


class TaskOut(TaskBase):
    id: int
    status: str
    rating: int | None
    actual_start: datetime | None
    actual_end: datetime | None

    model_config = {"from_attributes": True}

    @field_validator("planned_start", "planned_end", "actual_start", "actual_end")
    @classmethod
    def aware(cls, v: datetime | None) -> datetime | None:
        return from_db(v) if v else v


class TaskUpdate(BaseModel):
    status: TaskStatus | None = None
    rating: int | None = Field(None, ge=1, le=5)
    planned_start: datetime | None = None
    planned_end: datetime | None = None

    @field_validator("planned_start", "planned_end")
    @classmethod
    def utc(cls, v: datetime | None) -> datetime | None:
        return to_utc(v) if v else v


@router.post("/tasks", response_model=TaskOut, status_code=201)
async def create_task(body: TaskIn, db: Session = Depends(get_db), core: Orchestrator = Depends(get_orchestrator)):
    if body.goal_id is not None and db.get(Goal, body.goal_id) is None:
        raise HTTPException(404, "goal not found")
    task = Task(**body.model_dump())
    db.add(task)
    db.flush()
    await core.dispatch(IncomingEvent(type="task.created", payload={"task_id": task.id, "title": task.title}), db)
    return task


@router.get("/tasks", response_model=list[TaskOut])
def list_tasks(start: datetime | None = None, end: datetime | None = None, db: Session = Depends(get_db)):
    q = select(Task).order_by(Task.planned_start)
    if start:
        q = q.where(Task.planned_start >= start)
    if end:
        q = q.where(Task.planned_start < end)
    return db.scalars(q).all()


@router.patch("/tasks/{task_id}", response_model=TaskOut)
async def update_task(
    task_id: int, body: TaskUpdate, db: Session = Depends(get_db), core: Orchestrator = Depends(get_orchestrator)
):
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(404, "task not found")
    changes = body.model_dump(exclude_unset=True)
    now = datetime.now(timezone.utc)
    if changes.get("status") == TaskStatus.STARTED and task.actual_start is None:
        task.actual_start = now
    if changes.get("status") == TaskStatus.DONE:
        task.actual_end = now
    for key, value in changes.items():
        setattr(task, key, value)
    if from_db(task.planned_end) <= from_db(task.planned_start):
        raise HTTPException(422, "planned_end must be after planned_start")
    db.flush()
    if "status" in changes:
        await core.dispatch(
            IncomingEvent(type=f"task.{task.status}", payload={"task_id": task.id, "title": task.title}), db
        )
    else:
        db.commit()
    return task


@router.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: int, whole_routine: bool = False, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(404, "task not found")
    from app.core import deliberation
    deliberation.apply(db, [{"op": "delete", "id": task_id, "whole_series": whole_routine}])
    db.commit()


# ---------- goals ----------

class GoalIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    why: str = ""
    horizon: str = "3m"
    area: str = "general"
    target_date: datetime | None = None


class MilestoneOut(BaseModel):
    id: int
    title: str
    due_date: datetime | None
    done: bool
    depends_on: list[int] = []
    effort_hours: float | None = None


class GoalOut(GoalIn):
    id: int
    progress: float
    status: str
    milestones: list[MilestoneOut] = []
    forecast: dict | None = None  # roadmap goals: projected finish per milestone + weekly sprints


def _goal_out(g: Goal, db: Session | None = None) -> GoalOut:
    from app.core import roadmap

    return GoalOut(
        id=g.id, title=g.title, why=g.why, horizon=g.horizon, area=g.area,
        target_date=from_db(g.target_date) if g.target_date else None, progress=round(g.progress, 2),
        status=g.status,
        milestones=[MilestoneOut(id=m.id, title=m.title, due_date=from_db(m.due_date) if m.due_date else None,
                                 done=m.done_at is not None, depends_on=m.depends_on or [],
                                 effort_hours=m.effort_hours) for m in g.milestones],
        forecast=roadmap.forecast(db, g) if db is not None else None,
    )


@router.post("/goals", response_model=GoalOut, status_code=201)
async def create_goal(body: GoalIn, db: Session = Depends(get_db), core: Orchestrator = Depends(get_orchestrator)):
    goal = Goal(**body.model_dump())
    db.add(goal)
    db.flush()
    await core.dispatch(IncomingEvent(type="goal.created", payload={"goal_id": goal.id, "title": goal.title}), db)
    return _goal_out(goal)


@router.get("/goals", response_model=list[GoalOut])
def list_goals(db: Session = Depends(get_db)):
    return [_goal_out(g, db) for g in db.scalars(select(Goal).where(Goal.status != "dropped").order_by(Goal.id))]


class MilestoneUpdate(BaseModel):
    done: bool


@router.patch("/milestones/{milestone_id}", response_model=GoalOut)
async def update_milestone(milestone_id: int, body: MilestoneUpdate, db: Session = Depends(get_db),
                           core: Orchestrator = Depends(get_orchestrator)):
    from app.core import mentor
    from app.db.models import Milestone

    m = db.get(Milestone, milestone_id)
    if m is None:
        raise HTTPException(404, "milestone not found")
    was_done = m.done_at is not None
    m.done_at = datetime.now(timezone.utc) if body.done else None
    goal = m.goal
    mentor.refresh_goal_progress(db, goal)
    if goal.milestones and all(x.done_at for x in goal.milestones):
        goal.status = "achieved"
    elif goal.status == "achieved":
        goal.status = "active"
    db.flush()
    if body.done and not was_done:
        await core.dispatch(IncomingEvent("milestone.done", {"milestone_id": m.id, "title": m.title,
                                                             "goal": goal.title}), db)
    db.commit()
    return _goal_out(goal, db)


# ---------- answering TRINETRA's proposals and promise check-ins ----------

def _mark_answered(db: Session, message: Message, action: str) -> None:
    message.meta = {**(message.meta or {}), "answered": action}  # reassign so the JSON change is saved


class ProposalAnswer(BaseModel):
    action: str = Field(pattern="^(approve|accept|original|reject)$")


@router.post("/proposals/{message_id}/respond", response_model=DispatchOut)
async def answer_proposal(message_id: int, body: ProposalAnswer, db: Session = Depends(get_db),
                          core: Orchestrator = Depends(get_orchestrator)):
    from app.core import mentor

    from app.core import deliberation

    msg = db.get(Message, message_id)
    kind = (msg.meta or {}).get("kind") if msg else None
    if kind not in ("plan_proposal", "schedule_proposal", "initiative"):
        raise HTTPException(404, "proposal not found")
    if (msg.meta or {}).get("answered"):
        raise HTTPException(409, "already answered")
    _mark_answered(db, msg, body.action)
    if kind == "initiative":  # its own idea: a yes goes through the normal pipeline (the timetable builder acts on it)
        text = f"✅ Yes, do it: {msg.meta.get('idea')}" if body.action in ("approve", "accept") else "✋ Not now."
        result = await core.dispatch(IncomingEvent("user.message", {"text": text, **({} if body.action in ("approve", "accept") else {"button": True})}, "web"), db)
        return DispatchOut(**result.__dict__)
    if kind == "schedule_proposal":
        if body.action == "reject":
            text = "✋ Leave my timetable as it is."
        else:
            ops = msg.meta["original_ops"] if body.action == "original" else msg.meta["ops"]
            changes = deliberation.apply(db, ops)
            if msg.meta.get("why") and changes:  # a proposal TRINETRA made itself: say what changed and why
                await core.dispatch(IncomingEvent("plan.applied", {"changes": changes, "why": msg.meta["why"]}, "web"), db)
            label = "⚡ Do exactly what I asked." if body.action == "original" else "✅ Go with your version."
            text = f"{label} (done: {'; '.join(changes[:6]) or 'nothing to change'})"
        result = await core.dispatch(IncomingEvent("user.message", {"text": text, "button": True}, "web"), db)
        return DispatchOut(**result.__dict__)
    if body.action in ("approve", "accept"):
        added = mentor.apply_plan(db, msg.meta.get("goal_id"), msg.meta.get("blocks", []))
        text = "✅ Approved the plan."
        notes_text = f"(added to timetable: {'; '.join(added)})" if added else ""
    else:
        text, notes_text = "✋ Not that plan.", ""
    result = await core.dispatch(IncomingEvent("user.message", {"text": f"{text} {notes_text}".strip(),
                                                                "button": True}, "web"), db)
    return DispatchOut(**result.__dict__)


class PromiseAnswer(BaseModel):
    action: str = Field(pattern="^(kept|broken)$")


@router.post("/promises/{promise_id}/respond", response_model=DispatchOut)
async def answer_promise(promise_id: int, body: PromiseAnswer, db: Session = Depends(get_db),
                         core: Orchestrator = Depends(get_orchestrator)):
    from app.db.models import Promise

    promise = db.get(Promise, promise_id)
    if promise is None:
        raise HTTPException(404, "promise not found")
    if promise.status != "open":  # a double tap must not count twice (pride / frustration, training data)
        raise HTTPException(409, "already answered")
    promise.status = body.action
    for m in db.scalars(select(Message).where(Message.meta.is_not(None)).order_by(Message.id.desc()).limit(30)):
        if (m.meta or {}).get("promise_id") == promise.id and not m.meta.get("answered"):
            _mark_answered(db, m, body.action)
    db.flush()
    await core.dispatch(IncomingEvent(f"promise.{body.action}", {"promise_id": promise.id}), db)
    phrase = "✅ I kept my word: " if body.action == "kept" else "❌ I broke my promise: "
    result = await core.dispatch(IncomingEvent("user.message", {"text": phrase + promise.text, "button": True},
                                               "web"), db)
    return DispatchOut(**result.__dict__)


@router.get("/promises")
def list_promises(db: Session = Depends(get_db)):
    from app.db.models import Promise

    rows = db.scalars(select(Promise).order_by(Promise.due_at.desc()).limit(50)).all()
    return [{"id": p.id, "text": p.text, "due": f"{local(p.due_at):%a %d %b %H:%M}", "status": p.status}
            for p in rows]


# ---------- voice ----------

class SpeakIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    mood: str | None = None


@router.post("/speak", response_class=Response)
async def speak(body: SpeakIn):
    try:
        audio = await voice.speak(body.text, body.mood)
    except Exception as e:  # edge-tts needs internet; don't crash the chat over it
        raise HTTPException(503, f"voice unavailable: {e}") from e
    effect = voice.effect_for(body.mood)
    return Response(audio, media_type="audio/mpeg", headers={"X-Trinetra-Effect": effect or "none",
                                                            "Access-Control-Expose-Headers": "X-Trinetra-Effect"})


@router.post("/listen")
async def listen(audio: UploadFile):
    data = await audio.read()
    if not data:
        raise HTTPException(400, "empty recording")
    try:
        text = await voice.transcribe(data, audio.filename or "voice.webm", audio.content_type or "audio/webm")
    except voice.STTUnavailable as e:
        raise HTTPException(503, str(e)) from e
    return {"text": text}


# ---------- memory ----------

class MemoryOut(BaseModel):
    id: int
    kind: str
    content: str
    importance: int
    created_at: datetime

    model_config = {"from_attributes": True}


class MemoryIn(BaseModel):
    content: str = Field(min_length=1, max_length=500)
    kind: str = "profile"
    importance: int = Field(3, ge=1, le=5)


@router.get("/memories", response_model=list[MemoryOut])
def list_memories(db: Session = Depends(get_db)):
    return db.scalars(select(Memory).order_by(Memory.importance.desc(), Memory.id.desc())).all()


@router.post("/memories", response_model=MemoryOut, status_code=201)
def add_memory(body: MemoryIn, db: Session = Depends(get_db)):
    memory = Memory(**body.model_dump())
    db.add(memory)
    db.commit()
    return memory


@router.delete("/memories/{memory_id}", status_code=204)
def forget(memory_id: int, db: Session = Depends(get_db)):
    memory = db.get(Memory, memory_id)
    if memory is None:
        raise HTTPException(404, "memory not found")
    db.delete(memory)
    db.commit()


# ---------- conversation history ----------

def _utc_iso(t):
    if t is None:
        return None
    return (t if t.tzinfo else t.replace(tzinfo=timezone.utc)).isoformat()


@router.get("/messages")
def recent_messages(limit: int = 50, after_id: int | None = None, db: Session = Depends(get_db)):
    """Recent conversation; with after_id, only what's new (the page polls this for reminders)."""
    q = select(Message)
    if after_id is not None:
        rows = db.scalars(q.where(Message.id > after_id).order_by(Message.id).limit(50)).all()
    else:
        rows = list(reversed(db.scalars(q.order_by(Message.id.desc()).limit(min(limit, 200))).all()))
    return [
        {"id": m.id, "role": m.role, "content": m.content, "mood": m.mood, "channel": m.channel, "meta": m.meta,
         "at": _utc_iso(m.created_at)}
        for m in rows
    ]


# ---------- today + quick answers to reminders/check-ins ----------

@router.get("/today")
def today(days: int = 1, start_day: str | None = None, db: Session = Depends(get_db)):
    """Blocks from `start_day` (YYYY-MM-DD, your local date; default today) for `days` days."""
    when = None
    if start_day:
        try:
            when = datetime.combine(datetime.fromisoformat(start_day).date(), datetime.min.time(), user_tz())
        except ValueError:
            raise HTTPException(422, "start_day must be YYYY-MM-DD")
    start, _ = day_bounds_utc(when)
    end = start + timedelta(days=max(1, min(days, 14)))
    tasks = db.scalars(
        select(Task).where(Task.planned_start >= start, Task.planned_start < end).order_by(Task.planned_start)
    ).all()
    return [
        {
            "id": t.id, "title": t.title, "category": t.category, "status": t.status,
            "day": f"{local(t.planned_start):%a %d %b}", "start": f"{local(t.planned_start):%H:%M}",
            "end": f"{local(t.planned_end):%H:%M}", "recurrence": t.recurrence,
            "date": f"{local(t.planned_start):%Y-%m-%d}", "priority": t.priority, "routine": bool(t.series_id),
            "notify": t.notify,
            "goal_id": t.goal_id,
        }
        for t in tasks
    ]


QUICK_ACTIONS = {
    "start": (TaskStatus.STARTED, "▶️ Starting {title} now."),
    "done": (TaskStatus.DONE, "✅ Done: {title}"),
    "partly": (TaskStatus.DONE, "◐ Partly done: {title}"),
    "skip": (TaskStatus.SKIPPED, "⏭ Skipped: {title}"),
    "skipped": (TaskStatus.SKIPPED, "⏭ Skipped: {title}"),
    "snooze": (None, "⏰ Snooze {title} for 10 minutes."),
    "onit": (TaskStatus.STARTED, "👍 Still on {title}."),
}


class RespondIn(BaseModel):
    action: str = Field(pattern="^(start|done|partly|skip|skipped|snooze|onit)$")


@router.post("/tasks/{task_id}/respond", response_model=DispatchOut)
async def respond(
    task_id: int, body: RespondIn, db: Session = Depends(get_db), core: Orchestrator = Depends(get_orchestrator)
):
    """One-tap answers from reminder/check-in buttons. Spoken back to TRINETRA as a message, so it reacts."""
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(404, "task not found")
    status, phrase = QUICK_ACTIONS[body.action]
    same = task.status == status and ((body.action == "partly") == (task.rating == 2))  # "partly" after "done" corrects it
    if status is not None and same and body.action != "onit":  # double tap
        raise HTTPException(409, "already answered")
    if status is None:  # snooze: push the block 10 minutes later, keep its length
        start = max(local(task.planned_start), now_local()) + timedelta(minutes=10)
        timetable.move(task, start, start + (from_db(task.planned_end) - from_db(task.planned_start)))
    else:
        timetable.set_status(task, status)
        if body.action == "partly":
            task.rating = 2

    for m in db.scalars(select(Message).where(Message.meta.is_not(None)).order_by(Message.id.desc()).limit(30)):
        if m.meta.get("task_id") == task.id and not m.meta.get("answered"):
            m.meta = {**m.meta, "answered": body.action}  # reassign so the JSON change is saved
    db.commit()  # the answer is saved before TRINETRA reacts, so a second tap a moment later sees it

    if status is not None:  # feelings update first, so the reply already carries them
        await core.dispatch(IncomingEvent(f"task.{status}", {"task_id": task.id, "title": task.title}), db)
    result = await core.dispatch(
        IncomingEvent("user.message", {"text": phrase.format(title=task.title), "button": True}, "web"), db
    )
    return DispatchOut(**result.__dict__)


# ---------- courses + proof of work (TUF DSA, the ML Specialization) ----------

def _course(db: Session, course_id: int) -> "Course":
    from app.core import courses
    from app.db.models import Course

    courses.ensure(db)
    c = db.get(Course, course_id)
    if c is None:
        raise HTTPException(404, "no such course")
    return c


class VisionIn(BaseModel):
    y1: str | None = Field(None, max_length=600)
    y3: str | None = Field(None, max_length=600)
    y5: str | None = Field(None, max_length=600)


class JournalIn(BaseModel):
    text: str = Field(min_length=1, max_length=5000)


@router.get("/journal")
def journal_list(limit: int = 30, db: Session = Depends(get_db)):
    from app.db.models import JournalEntry

    rows = db.scalars(select(JournalEntry).order_by(JournalEntry.id.desc()).limit(min(limit, 200))).all()
    return [{"id": e.id, "at": e.at, "text": e.text} for e in rows]


@router.post("/journal", status_code=201)
async def journal_write(body: JournalIn, db: Session = Depends(get_db), core: Orchestrator = Depends(get_orchestrator)):
    from app.db.models import JournalEntry

    e = JournalEntry(text=body.text.strip())
    db.add(e)
    db.flush()
    result = await core.dispatch(IncomingEvent("journal.entry", {"entry_id": e.id}, "web"), db)
    return {"id": e.id, "reply": result.reply}


@router.get("/export")
def export_all(db: Session = Depends(get_db)):
    """Everything TRINETRA knows, as JSON — for the nightly iCloud backup (deploy/backup.sh). Passcode-protected."""
    from app.db.models import Base

    skip = {"push_subscriptions"}  # device keys: useless in a backup, and better not copied around
    out = {"exported_at": datetime.now(timezone.utc).isoformat(), "tables": {}}
    for table in Base.metadata.sorted_tables:
        if table.name in skip:
            continue
        rows = db.execute(table.select()).mappings().all()
        out["tables"][table.name] = [{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in r.items()} for r in rows]
    return out


@router.get("/insights")
def get_insights(db: Session = Depends(get_db)):
    """What your history says: real durations, peak/slump hours, what you push off, day-level links."""
    from app.ml import insights

    return insights.load(db)


@router.get("/vision")
def get_vision(db: Session = Depends(get_db)):
    from app.core import vision

    return vision.get(db)


@router.put("/vision")
def put_vision(body: VisionIn, db: Session = Depends(get_db)):
    from app.core import vision

    out = vision.put(db, **body.model_dump())
    db.commit()
    return out


@router.get("/moods")
def get_moods(days: int = 14, db: Session = Depends(get_db)):
    """Your mood per day (what TRINETRA read from your messages)."""
    from collections import Counter, defaultdict

    from app.db.models import MoodEntry

    since = datetime.now(timezone.utc) - timedelta(days=min(days, 90))
    by_day: dict = defaultdict(list)
    for m in db.scalars(select(MoodEntry).where(MoodEntry.at >= since).order_by(MoodEntry.at)).all():
        by_day[local(m.at).date().isoformat()].append(m.mood)
    return [{"date": d, "main": Counter(ms).most_common(1)[0][0], "count": len(ms),
             "low": sum(x in ("sad", "low", "tired", "stressed", "anxious", "lonely", "overwhelmed", "hurt", "frustrated")
                        for x in ms)} for d, ms in sorted(by_day.items())]


@router.get("/streaks")
def get_streaks(db: Session = Depends(get_db)):
    from app.core import streaks

    return streaks.all_streaks(db)


@router.get("/courses")
def list_courses(db: Session = Depends(get_db)):
    from app.core import courses
    from app.db.models import Course

    courses.ensure(db)
    out = [courses.summary(db, c) for c in db.scalars(select(Course).order_by(Course.id)).all()]
    db.commit()
    return out


class OutlineIn(BaseModel):
    text: str = Field(min_length=1, max_length=40000)


@router.put("/courses/{course_id}/outline")
def course_outline(course_id: int, body: OutlineIn, db: Session = Depends(get_db)):
    from app.core import courses

    c = _course(db, course_id)
    n = courses.set_outline(db, c, body.text)
    if n == 0:
        raise HTTPException(422, "no items found: one item per line, '# Section' for headers")
    db.commit()
    return courses.summary(db, c)


class PositionIn(BaseModel):
    item_id: int


@router.post("/courses/{course_id}/position")
def course_position(course_id: int, body: PositionIn, db: Session = Depends(get_db)):
    from app.core import courses
    from app.db.models import StudyItem

    c = _course(db, course_id)
    item = db.get(StudyItem, body.item_id)
    if item is None or item.course_id != c.id:
        raise HTTPException(404, "no such item in this course")
    courses.set_position(db, c, item.id)
    db.commit()
    return courses.summary(db, c)


class ImportItem(BaseModel):
    section: str = Field("", max_length=200)
    title: str = Field(min_length=1, max_length=300)
    kind: str | None = Field(None, max_length=60)
    est_min: int | None = Field(None, ge=0, le=1000)
    planned_date: date | None = None
    done: bool = False
    optional: bool = False


class ImportIn(BaseModel):
    items: list[ImportItem] = Field(min_length=1, max_length=3000)
    title: str | None = Field(None, max_length=200)
    active_from: date | None = None
    roadmap_title: str | None = Field(None, max_length=200)  # set → the linked goal's milestones become the sprints


@router.post("/courses/{course_id}/import")
def course_import(course_id: int, body: ImportIn, db: Session = Depends(get_db)):
    """Load a course exactly as TUF Planly / Coursera has it (synced from Tarun's own logged-in browser)."""
    from app.core import courses

    c = _course(db, course_id)
    courses.import_items(db, c, [{**i.model_dump(), "planned_date": i.planned_date.isoformat() if i.planned_date else None}
                                 for i in body.items])
    if body.title:
        c.title = body.title
    if body.active_from:
        c.active_from = datetime.combine(body.active_from, datetime.min.time(), user_tz()).astimezone(timezone.utc)
    milestones = courses.rebuild_roadmap(db, c, body.roadmap_title) if body.roadmap_title else 0
    db.commit()
    return {**courses.summary(db, c), "milestones": milestones}


class CourseSettingsIn(BaseModel):
    per_block: int | None = Field(None, ge=1, le=20)
    target_date: date | None = None


@router.patch("/courses/{course_id}")
def course_settings(course_id: int, body: CourseSettingsIn, db: Session = Depends(get_db)):
    from app.core import courses

    c = _course(db, course_id)
    if body.per_block is not None:
        c.per_block = body.per_block
    if body.target_date is not None:
        c.target_date = datetime.combine(body.target_date, datetime.min.time(), user_tz()).astimezone(timezone.utc)
    db.commit()
    return courses.summary(db, c)


@router.get("/proof/{task_id}")
def proof_form(task_id: int, db: Session = Depends(get_db)):
    from app.core import courses

    task = db.get(Task, task_id)
    tg = courses.target(db, task) if task else None
    if tg is None:
        raise HTTPException(404, "not a course block")
    c, aimed = tg
    rest = [i for i in courses.items(db, c) if not i.done_at and i not in aimed][:6]
    row = lambda i: {"id": i.id, "section": i.section, "title": i.title, "done": i.task_id == task.id}  # noqa: E731
    db.commit()
    return {"task": {"id": task.id, "title": task.title, "status": task.status}, "course": c.title,
            "aimed": [row(i) for i in aimed], "more": [row(i) for i in rest],
            "logged": task.status in (TaskStatus.DONE, TaskStatus.SKIPPED)}


class ProofIn(BaseModel):
    done_ids: list[int] = Field(default_factory=list, max_length=100)
    note: str = Field(default="", max_length=300)


@router.post("/proof/{task_id}", response_model=DispatchOut)
async def proof_log(task_id: int, body: ProofIn, db: Session = Depends(get_db), core: Orchestrator = Depends(get_orchestrator)):
    from app.core import courses

    task = db.get(Task, task_id)
    if task is None or courses.target(db, task) is None:
        raise HTTPException(404, "not a course block")
    res = courses.record(db, task, body.done_ids, body.note)
    status = {"all": TaskStatus.DONE, "some": TaskStatus.DONE, "none": TaskStatus.SKIPPED}[res["outcome"]]
    timetable.set_status(task, status)
    if res["outcome"] == "some":
        task.rating = 2
    for m in db.scalars(select(Message).where(Message.meta.is_not(None)).order_by(Message.id.desc()).limit(30)):
        if m.meta.get("task_id") == task.id and not m.meta.get("answered"):
            m.meta = {**m.meta, "answered": res["outcome"]}
    said = "✅ " + "; ".join(res["finished"]) if res["finished"] else "Nothing from the target."
    db.add(Message(role="user", channel="web", content=f"📋 {task.title}: {said}" + (f" — stopped at: {res['note']}" if res["note"] else "")))
    db.flush()
    await core.dispatch(IncomingEvent(f"task.{status}", {"task_id": task.id, "title": task.title}), db)
    result = await core.dispatch(IncomingEvent("proof.logged", {"task_id": task.id, **res}, "web"), db)
    return DispatchOut(**result.__dict__)


# ---------- mood mode ----------

class ModeIn(BaseModel):
    mode: str | None = Field(None, pattern="^(angry|strict|gentle|hype)$")


@router.get("/autonomy")
def autonomy_policy(db: Session = Depends(get_db)):
    """What TRINETRA has learned about when to speak up on its own, and its recent decisions with their reasons."""
    from app.core import autonomy
    return autonomy.policy(db)


@router.get("/mode")
def get_mode(db: Session = Depends(get_db)):
    mode = mood_modes.get_mode(db)
    return {"mode": mode, "label": mood_modes.LABELS.get(mode)}


@router.post("/mode")
def set_mode(body: ModeIn, db: Session = Depends(get_db)):
    mood_modes.set_mode(db, body.mode)
    db.commit()
    return {"mode": body.mode, "label": mood_modes.LABELS.get(body.mode)}


@router.get("/emotion")
def get_emotion(db: Session = Depends(get_db)):
    from dataclasses import asdict

    from app.core import emotion

    state = emotion.decay(emotion.load(db))
    mood, label = emotion.expression(state)
    return {"label": label, "mood": mood, **{k: round(v, 2) if isinstance(v, float) else v
                                               for k, v in asdict(state).items()}}


# ---------- the brain ----------

BRAIN_LAYERS = [
    ("Perception", "Router, Empathy Detector, Whisper ears — what you say and how you feel"),
    ("Emotion", "Emotion Engine — frustration, pride, concern, warmth, fading over time"),
    ("Memory", "Long-term Memory + conversation history — who you are, what you promised"),
    ("Reasoning", "Gemini / Groq language models — thinking and talking"),
    ("Neural Core", "Your own neural network — learns when and why you follow through"),
    ("Action", "Timetable Builder, Reminders, Check-ins — doing things in the world"),
]


@router.get("/brain")
def brain(db: Session = Depends(get_db), core: Orchestrator = Depends(get_orchestrator)):
    from app.ml import neural_core

    r = neural_core.report(db)
    specs = list(core.registry.specs.values())
    return {
        "layers": [{"name": n, "what": w} for n, w in BRAIN_LAYERS],
        "agents": {"total": len(specs), "active": sum(s.status == "active" for s in specs)},
        "neural_core": {
            "mode": r.mode, "samples": r.samples, "hidden_layers": r.layers, "neurons": r.neurons,
            "accuracy": round(r.accuracy, 2) if r.accuracy is not None else None, "trained_at": r.trained_at,
            "next_growth": next(
                ({"at_samples": t, "layers": l} for t, l in reversed(neural_core.GROWTH) if r.samples < t), None
            ),
        },
    }


@router.post("/brain/train")
def train_brain(db: Session = Depends(get_db)):
    from app.ml import neural_core

    report = neural_core.train(db)
    db.commit()
    return report.__dict__


# ---------- push notifications ----------

class PushKeys(BaseModel):
    p256dh: str
    auth: str


class SubscriptionIn(BaseModel):
    endpoint: str = Field(pattern=r"^https://")
    keys: PushKeys
    device: str = ""


@router.get("/push/key")
def push_key():
    return {"public_key": push.vapid_keys()["public_key"]}


@router.post("/push/subscribe", status_code=201)
def push_subscribe(body: SubscriptionIn, db: Session = Depends(get_db)):
    sub = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == body.endpoint))
    if sub is None:
        sub = PushSubscription(endpoint=body.endpoint)
        db.add(sub)
    sub.p256dh, sub.auth, sub.device = body.keys.p256dh, body.keys.auth, body.device[:200]
    db.commit()
    return {"subscribed": True}


@router.post("/push/test")
async def push_test(db: Session = Depends(get_db)):
    import asyncio

    sent = await asyncio.to_thread(push.send, db, "TRINETRA", "I'm on your lock screen now. I've got your back.")
    db.commit()
    return {"delivered": sent}


# ---------- login ----------

@router.get("/login", include_in_schema=False)
def login_page():
    from fastapi.responses import FileResponse

    from app.main import STATIC

    return FileResponse(STATIC / "login.html")


class LoginIn(BaseModel):
    passcode: str


LOGIN_MAX_FAILS = 8
LOGIN_WINDOW = timedelta(minutes=15)


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    """Passcode → year-long session cookie. Failures are counted in the DB (works across serverless
    instances): after 8 wrong tries in 15 minutes, logins pause for 15 minutes."""
    import hmac as _hmac
    import json as _json

    from app.config import get_settings
    from app.core.auth import COOKIE, session_token
    from app.db.models import KeyValue

    s = get_settings()
    now = datetime.now(timezone.utc)
    row = db.get(KeyValue, "login_failures")
    fails = _json.loads(row.value) if row and row.value else {"count": 0, "since": now.isoformat()}
    if datetime.fromisoformat(fails["since"]) < now - LOGIN_WINDOW:
        fails = {"count": 0, "since": now.isoformat()}
    if fails["count"] >= LOGIN_MAX_FAILS:
        raise HTTPException(429, "too many wrong tries — wait 15 minutes")

    if not s.trinetra_passcode or not _hmac.compare_digest(body.passcode.strip(), s.trinetra_passcode):
        fails["count"] += 1
        if row is None:
            db.add(KeyValue(key="login_failures", value=_json.dumps(fails)))
        else:
            row.value = _json.dumps(fails)
        db.commit()
        raise HTTPException(401, "wrong passcode")

    if row is not None:
        db.delete(row)
        db.commit()
    https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(
        COOKIE, session_token(s.trinetra_passcode, s.trinetra_secret),
        max_age=60 * 60 * 24 * 365, httponly=True, samesite="lax", secure=https,
    )
    return {"ok": True}


# ---------- cloud heartbeat ----------

@router.post("/cron/tick")
async def cron_tick(request: Request, db: Session = Depends(get_db), core: Orchestrator = Depends(get_orchestrator)):
    """Called every minute by the Cloudflare Worker cron — the serverless replacement for the in-process heartbeat."""
    import hmac as _hmac

    from app.config import get_settings
    from app.core import scheduler

    secret = get_settings().trinetra_cron_secret
    given = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not secret or not _hmac.compare_digest(given, secret):
        raise HTTPException(401, "bad cron secret")
    return await scheduler.heartbeat(db, core)


# ---------- iOS Shortcuts: wake-up alarm, "what's now", weekly report audio ----------
# Shortcuts can't keep a login cookie, so they pass ?key=TRINETRA_SHORTCUT_KEY. That key opens ONLY /sc/*.

def require_shortcut_key(key: str = "") -> None:
    import hmac as _hmac

    from app.config import get_settings

    expected = get_settings().trinetra_shortcut_key
    if not expected or not _hmac.compare_digest(key, expected):
        raise HTTPException(401, "bad shortcut key")


def _audio(data: bytes) -> Response:
    return Response(data, media_type="audio/mpeg", headers={"Cache-Control": "no-store"})


def _silence() -> Response:
    return _audio(voice.SILENT_MP3)


# The Shortcuts contain NO "If" or loops (iOS drops their settings in generated shortcuts). They only fetch audio
# and play it; when there's nothing to say the server sends a moment of silence instead of an error.

def _block_starting_now(db: Session) -> Task | None:
    now = datetime.now(timezone.utc)
    return db.scalars(select(Task).where(
        Task.planned_start >= now - timedelta(minutes=10), Task.planned_start <= now + timedelta(minutes=10),
        Task.status == TaskStatus.PLANNED, Task.notify != "none").order_by(Task.planned_start)).first()


@router.get("/sc/wake/start", dependencies=[Depends(require_shortcut_key)], response_class=Response)
def sc_wake_start(db: Session = Depends(get_db)):
    from app.core import wake
    from app.db.models import KeyValue

    if db.get(KeyValue, "wake_enabled") is None:
        db.add(KeyValue(key="wake_enabled", value="1"))
    s = wake.ring(db)
    db.commit()
    return Response("done" if s.last == "done" else "", media_type="text/plain")  # empty = keep going (Shortcuts "has any value")


@router.get("/sc/wake/status", dependencies=[Depends(require_shortcut_key)], response_class=Response)
def sc_wake_status(db: Session = Depends(get_db)):
    from app.core import wake

    s = wake.today_session(db)
    db.commit()
    return Response("done" if s.last == "done" else "", media_type="text/plain")  # empty = keep going (Shortcuts "has any value")


@router.get("/sc/wake/question", dependencies=[Depends(require_shortcut_key)], response_class=Response)
def sc_wake_question(db: Session = Depends(get_db)):
    from app.core import wake

    s = wake.today_session(db)
    db.commit()
    if s.last == "done":
        return Response("You're awake ✅", media_type="text/plain")
    q = s.questions[s.index]
    return Response(f"Question {s.index + 1} of {len(s.questions)}: what is {q['text']}?", media_type="text/plain")


async def _wake_speech(db: Session) -> Response:
    """What TRINETRA says right now: wake-up shouting, or (once) the morning briefing, then silence."""
    from app.config import get_settings
    from app.core import wake
    from app.db.models import KeyValue

    s = wake.today_session(db)
    if s.last == "done":
        key = f"wake_briefed:{s.day}"
        if db.get(KeyValue, key) is not None:
            db.commit()
            return _silence()  # you're up and briefed: the 06:10 / 06:20 re-rings stay quiet
        db.add(KeyValue(key=key, value="1"))
    text, mood = await wake.speech_text(db, get_settings())
    db.add(Message(role="trinetra", content=text, channel="wake", mood=mood, meta={"kind": "wake"}))
    db.commit()
    audio = await voice.speak(text, mood)
    return Response(audio, media_type="audio/mpeg",
                    headers={"Cache-Control": "no-store", "X-Trinetra-Effect": voice.effect_for(mood) or ""})


@router.get("/sc/wake/speech", dependencies=[Depends(require_shortcut_key)], response_class=Response)
async def sc_wake_speech(db: Session = Depends(get_db)):
    return await _wake_speech(db)


# ---------- the wake-up screen in the app (the notifications at 6am open it) ----------

def _wake_state(s) -> dict:
    done = s.last == "done"
    q = None if done else s.questions[s.index]["text"]
    return {"done": done, "question": q, "number": s.index + 1, "total": len(s.questions), "wrong": s.wrong,
            "rings": s.rings, "last": s.last}


@router.get("/wake/state")
def wake_state(db: Session = Depends(get_db)):
    from app.core import wake

    s = wake.today_session(db)
    if s.first_ring_at is None:  # opened the app before the alarm: that still counts as the first ring
        wake.ring(db)
    db.commit()
    return _wake_state(s)


class WakeAnswerIn(BaseModel):
    a: str = Field(max_length=20)


@router.post("/wake/answer")
async def wake_answer(body: WakeAnswerIn, db: Session = Depends(get_db),
                      core: Orchestrator = Depends(get_orchestrator)):
    from app.core import wake

    result = await _answer_wake(db, core, body.a)
    return {"result": result, **_wake_state(wake.today_session(db))}


@router.get("/wake/speech", response_class=Response)
async def wake_speech(db: Session = Depends(get_db)):
    return await _wake_speech(db)


@router.get("/sc/wake/answer", dependencies=[Depends(require_shortcut_key)], response_class=Response)
async def sc_wake_answer(a: str = "", db: Session = Depends(get_db), core: Orchestrator = Depends(get_orchestrator)):
    return Response(await _answer_wake(db, core, a), media_type="text/plain")


async def _answer_wake(db: Session, core: Orchestrator, a: str) -> str:
    from app.core import wake

    result = wake.answer(db, a)
    if result == "done":
        s = wake.today_session(db)
        db.flush()
        await core.dispatch(IncomingEvent("wake.done", {
            "rings": s.rings, "minutes_to_wake": wake.minutes_to_wake(s), "wrong": s.wrong,
            "weekday": now_local().strftime("%a")}, "app"), db)
    db.commit()
    return result


@router.get("/sc/now", dependencies=[Depends(require_shortcut_key)], response_class=Response)
async def sc_now(db: Session = Depends(get_db)):
    """Speaks the block that's starting about now (for time-of-day automations). Empty if nothing is due."""
    from app.config import get_settings
    from app.core import emotion, llm
    from app.core import mood as mood_modes
    from app.core.persona import humanize, system_prompt

    task = _block_starting_now(db)
    if task is None:
        return _silence()
    s, e = local(task.planned_start), local(task.planned_end)
    felt, _ = emotion.expression(emotion.decay(emotion.load(db)))
    mood = mood_modes.apply(db, felt)
    text = f"Tarun, it's {s:%-I:%M}. Time for {task.title}, until {e:%-I:%M}. Let's go."
    ask = (f"Speak to me out loud: it's {s:%H:%M}, time for '{task.title}' until {e:%H:%M}. "
           "Start with 'Tarun, it's time'. Two short sentences.")
    if task.category == "sleep":  # bedtime: always caring, never hyped
        mood = mood_modes.apply(db, "warm and caring, but firm about bedtime")
        text = "Tarun, it's time to sleep. Put the phone down and get some rest."
        ask = ("Speak to me out loud: it's bedtime. Start with 'Tarun, it's time to sleep'. Tell me to put the "
               "phone down and get some rest. Keep it simple: no time, gym, classes or plans. Two short sentences.")
    if get_settings().llm_available:
        try:
            text = humanize(strip_name=False, text=await llm.complete([
                {"role": "system", "content": system_prompt(mood)},
                {"role": "user", "content": ask}],
                tier="fast", max_tokens=200)) or text
        except llm.LLMUnavailable:
            pass
    return _audio(await voice.speak(text, mood))


@router.get("/sc/opened", dependencies=[Depends(require_shortcut_key)], response_class=Response)
async def sc_opened(app: str = "", db: Session = Depends(get_db), core: Orchestrator = Depends(get_orchestrator)):
    """Focus Guard: a distracting app was just opened. TRINETRA's voice when it should speak, else silence."""
    result = await core.dispatch(IncomingEvent(type="shortcut.app_opened", payload={"app": app}, source="shortcut"), db)
    db.commit()
    if result.spoke != "distraction_watcher" or result.notes.get("silent") or not result.reply:
        return _silence()
    return _audio(await voice.speak(result.reply, result.mood))


@router.get("/sc/focus", dependencies=[Depends(require_shortcut_key)], response_class=Response)
async def sc_focus(state: str = "on", db: Session = Depends(get_db), core: Orchestrator = Depends(get_orchestrator)):
    """iPhone Focus mode turned on / off (two automations, one per state)."""
    await core.dispatch(IncomingEvent(type="shortcut.focus", payload={"state": state[:8]}, source="shortcut"), db)
    db.commit()
    return Response("ok", media_type="text/plain")


@router.get("/sc/place", dependencies=[Depends(require_shortcut_key)], response_class=Response)
async def sc_place(name: str, event: str = "arrive", db: Session = Depends(get_db),
                   core: Orchestrator = Depends(get_orchestrator)):
    """Arrived at / left USC, the gym or home (location automations)."""
    await core.dispatch(IncomingEvent(type="shortcut.location", payload={"place": name[:20], "event": event[:10]},
                                      source="shortcut"), db)
    db.commit()
    return Response("ok", media_type="text/plain")


@router.get("/sc/report/audio", dependencies=[Depends(require_shortcut_key)], response_class=Response)
async def sc_report_audio(part: int = 1, db: Session = Depends(get_db)):
    """Chapter `part` (1-6) of the latest ready weekly report, as audio."""
    from app.db.models import WeeklyReport

    r = db.scalars(select(WeeklyReport).where(WeeklyReport.status == "ready")
                   .order_by(WeeklyReport.week_start.desc())).first()
    if r is None or not 1 <= part <= len(r.sections):
        return _silence()
    chapter = r.sections[part - 1]
    intro = f"Chapter {part} of {len(r.sections)}: {chapter['title']}. "
    return _audio(await voice.speak(intro + chapter["text"], "calm and caring"))


# ---------- reports + wake history in the app ----------

@router.get("/reports")
def list_reports(db: Session = Depends(get_db)):
    from app.db.models import WeeklyReport

    rows = db.scalars(select(WeeklyReport).order_by(WeeklyReport.week_start.desc()).limit(52)).all()
    return [{"week_start": r.week_start, "status": r.status, "metrics": r.metrics, "sections": r.sections}
            for r in rows]


@router.post("/reports/build")
async def build_report(week_of: str | None = None, db: Session = Depends(get_db)):
    """Build (or finish) a week's report now — normally the Sunday-night heartbeat does this."""
    from app.config import get_settings
    from app.core import report

    day = datetime.fromisoformat(week_of).date() if week_of else now_local().date()
    monday, *_ = report.week_bounds(day)
    steps = []
    for _ in range(len(report.CHAPTERS) + 1):
        step = await report.advance(db, get_settings(), monday)
        db.commit()
        steps.append(step)
        if step == "ready":
            break
    return {"week_start": monday.isoformat(), "steps": steps}


@router.get("/wake/history")
def wake_history(db: Session = Depends(get_db)):
    from app.core import wake
    from app.db.models import WakeSession

    rows = db.scalars(select(WakeSession).order_by(WakeSession.day.desc()).limit(60)).all()
    return [{"day": s.day, "rings": s.rings, "wrong": s.wrong, "solved": s.last == "done",
             "solved_at": f"{local(s.solved_at):%H:%M}" if s.solved_at else None,
             "minutes_to_wake": wake.minutes_to_wake(s)} for s in rows]
