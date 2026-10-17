"""Monitoring: knows whether you're actually doing the work.

Focus Guard — an iPhone automation ("when Instagram, YouTube, … is opened → run Trinetra Focus Guard") reports
each open. In a focus block TRINETRA calls it out loud, firmer each time; in class it only sends a silent
notification; late at night it tells you to sleep; in free time it just keeps count.
"""
import asyncio
import re
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import func, select

from app.agents.planning import _speak_up
from app.core import emotion, push
from app.core.orchestrator import AgentContext, AgentResult
from app.core.registry import agent
from app.core.timeutil import from_db, local
from app.db.models import AppOpen, Task, TaskStatus

COOLDOWN = timedelta(minutes=3)        # bouncing in and out of an app = one call-out, not five
NIGHT_FROM, NIGHT_UNTIL = time(23, 30), time(5, 0)
RELAXED = {"health", "fitness", "rest", "social", "chores", "sleep"}
CLASS = re.compile(r"\b(class|seminar|exam|meeting)\b", re.I)  # in a real room: never talk out loud


def clock() -> datetime:  # tests move it
    return datetime.now(timezone.utc)


def current_block(db, now: datetime) -> Task | None:
    return db.scalars(select(Task).where(
        Task.planned_start <= now, Task.planned_end > now, Task.notify != "none",
        Task.status.in_([TaskStatus.PLANNED, TaskStatus.STARTED])).order_by(Task.priority.desc())).first()


def situation(db, now: datetime) -> tuple[str, Task | None]:
    block, t = current_block(db, now), local(now).time()
    if (block and block.category == "sleep") or t >= NIGHT_FROM or t < NIGHT_UNTIL:
        return "sleep", block
    if block is None or block.category in RELAXED:
        return "free", block
    if CLASS.search(block.title):
        return "class", block
    return "focus", block


@agent("distraction_watcher")
async def distraction_watcher(ctx: AgentContext) -> AgentResult | None:
    db, now = ctx.db, clock()
    app = (ctx.event.payload.get("app") or "").strip()[:60]
    kind, block = situation(db, now)
    last = db.scalar(select(func.max(AppOpen.at)).where(AppOpen.spoke.is_(True)))
    cooling = last is not None and now - from_db(last) < COOLDOWN
    row = AppOpen(app=app, kind=kind, task_id=block.id if block else None, spoke=False, at=now)
    db.add(row)
    ctx.notes["focus_guard"] = kind
    if kind == "free" or cooling:
        db.flush()
        return None
    row.spoke = True
    what = app or "that app"
    if kind == "sleep":
        return await _speak_up(
            ctx, instruction=(f"It's late and I just opened {what} instead of sleeping. In one or two short, warm "
                              "sentences, tell me to put the phone down and sleep. No lecture."),
            fallback="It's late. Put the phone down and get some sleep.",
            mood="warm and caring, but firm about bedtime", keep_mood=True, channel="shortcut",
            meta={"kind": "focus_guard", "situation": kind, "app": app})

    db.flush()
    count = db.scalar(select(func.count()).select_from(AppOpen).where(  # includes this one
        AppOpen.task_id == block.id, AppOpen.spoke.is_(True), AppOpen.kind.in_(["focus", "class"])))
    state = emotion.decay(emotion.load(db))
    if count >= 2:
        state.nudge("frustration", 0.12 * (count - 1) * (0.6 + ctx.settings.trinetra_strictness * 0.2))
    emotion.save(db, state)
    felt, label = emotion.expression(state)
    mood = ("firm but calm — a quick call-out, no lecture" if count == 1 else
            felt if label in ("angry", "firm") else "firm and annoyed — this is the second time this block")
    left = max(1, round((from_db(block.planned_end) - now).total_seconds() / 60))
    meta = {"kind": "focus_guard", "situation": kind, "app": app, "task_id": block.id, "count": count}
    instruction = (f"I'm supposed to be in '{block.title}' ({left} minutes left) and I just opened {what}"
                   f"{'' if count == 1 else f' — that is time number {count} this block'}. Call it out in one or "
                   "two short spoken sentences and send me back to the work. "
                   + ("Keep it light the first time." if count == 1 else "Be firmer; I keep doing it."))
    fallback = (f"{what.capitalize() if app else 'Hey'}? You're in {block.title}. Close it and get back to work."
                if count == 1 else f"That's {count} times this block. Close it. {block.title}, now.")
    out = await _speak_up(ctx, instruction=instruction, fallback=fallback, mood=mood, keep_mood=True,
                          channel="shortcut", meta=meta)
    if kind == "class":  # silent on the lock screen instead of a voice in the room
        await asyncio.to_thread(push.send, db, "TRINETRA", out.reply, "/", f"focus-{block.id}")
        ctx.notes["silent"] = True
    return out
