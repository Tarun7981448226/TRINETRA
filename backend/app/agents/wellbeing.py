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
