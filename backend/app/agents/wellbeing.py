"""Wellbeing + habits: streaks worth celebrating, and breaks during long stretches of work."""
from app.agents.planning import _speak_up
from app.core import streaks
from app.core.orchestrator import AgentContext, AgentResult
from app.core.registry import agent
from app.db.models import KeyValue, Task


@agent("routine_tracker")
async def routine_tracker(ctx: AgentContext) -> AgentResult | None:
    """A day added to a streak: celebrate the milestones (3, 7, 14, 30 … days in a row)."""
    if ctx.event.type == "wake.done":
        kind = "wake"
    else:
        task = ctx.db.get(Task, ctx.event.payload.get("task_id"))
        if task is None or (ctx.event.type == "proof.logged" and ctx.event.payload.get("outcome") == "none"):
            return None
        kind = streaks.kind_of(task)
    if kind is None:
        return None
    ctx.db.flush()
    s = streaks.streak(ctx.db, kind)
    ctx.notes["streak"] = s
    key = f"streak_cheer:{kind}:{s['current']}"
    if s["current"] not in streaks.MILESTONES or ctx.db.get(KeyValue, key) is not None:
        return None
    ctx.db.add(KeyValue(key=key, value="1"))
    record = " That's your best ever." if s["current"] >= s["best"] and s["current"] > 3 else ""
    return await _speak_up(
        ctx, instruction=(f"I just hit {s['current']} days in a row of {s['label']}.{record} One short, proud spoken "
                          "sentence; make me want to keep the chain going tomorrow."),
        fallback=f"🔥 {s['current']} days of {s['label']} in a row.{record} Keep the chain alive.",
        mood="proud", keep_mood=True, channel="web", meta={"kind": "streak", "streak": kind, "days": s["current"]})


@agent("health_hydration")
async def health_hydration(ctx: AgentContext) -> AgentResult | None:
    if ctx.event.payload.get("kind") != "hydrate":
        return None
    m = int(ctx.event.payload.get("minutes") or 90)
    return await _speak_up(
        ctx, instruction=(f"I've been working for {m} minutes without a break. One short, light sentence: drink water, "
                          "stand up, stretch for a minute, then back to it. No lecture."),
        fallback=f"{m} minutes in. Water, stand up, stretch for a minute.", mood="calm and caring", keep_mood=True,
        meta={"kind": "wellbeing", "nudge": "hydrate"})


@agent("meal_break_agent")
async def meal_break_agent(ctx: AgentContext) -> AgentResult | None:
    if ctx.event.payload.get("kind") != "break":
        return None
    m = int(ctx.event.payload.get("minutes") or 180)
    hours = round(m / 60, 1)
    return await _speak_up(
        ctx, instruction=(f"I've been working for {hours} hours straight. Two short, caring sentences: take ten real "
                          "minutes away from the screen (eat something if I haven't), and the work will be better for it."),
        fallback=f"{hours} hours straight. Take ten real minutes away from the screen.", mood="warm and caring",
        keep_mood=True, meta={"kind": "wellbeing", "nudge": "break"})


# ---------- mood over time, and overload ----------

LOW = {"sad", "low", "tired", "stressed", "anxious", "lonely", "overwhelmed", "hurt", "frustrated"}
STRESS = {"stressed", "anxious", "overwhelmed", "tired"}
HEAVY_DAY_MIN = 9 * 60  # more planned work than this in a day is a lot


@agent("mood_tracker")
async def mood_tracker(ctx: AgentContext) -> None:
    """Keep what the Empathy Detector read, so moods become a trend instead of a moment."""
    from app.db.models import MoodEntry

    mood, intensity = ctx.notes.get("user_mood"), float(ctx.notes.get("user_mood_intensity") or 0)
    if not mood or (mood == "neutral" and intensity < 0.3):
        return
    ctx.db.add(MoodEntry(mood=mood, intensity=round(intensity, 2),
                         source="voice" if ctx.event.type == "voice.input" else "chat"))
    ctx.db.flush()


def recent_stress(db, now, hours: int = 48) -> int:
    from datetime import timedelta

    from sqlalchemy import func, select

    from app.db.models import MoodEntry

    return db.scalar(select(func.count()).select_from(MoodEntry).where(
        MoodEntry.at >= now - timedelta(hours=hours), MoodEntry.mood.in_(STRESS), MoodEntry.intensity >= 0.4)) or 0


@agent("stress_monitor")
async def stress_monitor(ctx: AgentContext) -> None:
    """9 pm: a very full day tomorrow, or you've been stressed lately → offer to lighten it (you approve)."""
    from datetime import date, datetime, timezone

    from app.core import planner

    if ctx.event.type != "plan.nightly":
        return
    day = date.fromisoformat(ctx.event.payload["date"])
    work = [t for t in planner.blocks_on(ctx.db, day)
            if t.notify != "none" and t.category not in ("sleep", "health") and t.status == "planned"]
    minutes = sum((t.planned_end - t.planned_start).total_seconds() / 60 for t in work)
    stressed = recent_stress(ctx.db, datetime.now(timezone.utc))
    ctx.notes["stress"] = {"tomorrow_min": round(minutes), "stressed_48h": stressed}
    if minutes <= HEAVY_DAY_MIN and stressed < 3:
        return
    # the least important block that isn't a class or the gym: the one to let go
    from app.agents.monitoring import CLASSY
    flexible = [t for t in work if not CLASSY.search(t.title) and t.category != "fitness"]
    if not flexible:
        return
    drop = min(flexible, key=lambda t: (t.priority, -(t.planned_end - t.planned_start).total_seconds()))
    why = (f"Tomorrow has {round(minutes / 60, 1)} hours of work planned" if minutes > HEAVY_DAY_MIN else "Tomorrow is full")
    why += (f", and you've sounded stressed {stressed} times in two days" if stressed >= 3 else "") + \
           f". I'd let '{drop.title}' go tomorrow so the rest gets your best."
    planner.propose(ctx.db, [{"op": "delete", "id": drop.id}], why, mood="gentle and comforting — warm, soft, encouraging, zero pressure")
