"""Coaching: looking back at the week and ahead at the goals."""
import json
import re
from datetime import date, datetime, timezone

from sqlalchemy import select

from app.agents.planning import _speak_up
from app.core import courses, llm, report, roadmap, vision
from app.core.orchestrator import AgentContext, AgentResult
from app.core.registry import agent
from app.core.timeutil import from_db, local
from app.db.models import Course, Goal, KeyValue, Task


def analyse_week(db, monday: date) -> dict:
    """Where you're lagging: each course's week (TUF sprints, Coursera) and each goal's forecast vs its target."""
    _, start, end = report.week_bounds(monday)
    out = {"courses": [], "goals": []}
    courses.ensure(db)
    for c in db.scalars(select(Course).order_by(Course.id)).all():
        s = courses.summary(db, c, min(end, datetime.now(timezone.utc)))
        its = courses.items(db, c)
        this_week = [i for i in its if i.task_id and i.done_at and start <= from_db(i.done_at) < end]
        due_this_week = [i for i in its if i.planned_date and monday.isoformat() <= i.planned_date
                         < date.fromordinal(monday.toordinal() + 7).isoformat()]
        sprint = next((sp for sp in s["sprints"] if sp["done"] < sp["total"]), None)
        out["courses"].append({
            "course": c.title, "done": s["done"], "total": s["total"], "now_at": (s["now_at"] or {}).get("title"),
            "done_this_week": len(this_week), "planned_this_week": len(due_this_week),
            "planned_this_week_done": sum(1 for i in due_this_week if i.done_at),
            "overdue": s["behind"], "current_sprint": sprint,
            "need_per_block": s["need_per_block"], "per_block": s["per_block"], "on_pace": s["on_pace"],
        })
    for g in db.scalars(select(Goal).where(Goal.status == "active")).all():
        f = roadmap.forecast(db, g) or {}
        target = local(g.target_date).date().isoformat() if g.target_date else None
        finish = f.get("finish")
        out["goals"].append({"goal": g.title, "progress": round(g.progress, 2), "target": target,
                             "forecast_finish": finish,
                             "late_by_days": (date.fromisoformat(finish) - date.fromisoformat(target)).days
                             if finish and target else None})
    from collections import Counter

    from app.db.models import MoodEntry

    moods = db.scalars(select(MoodEntry).where(MoodEntry.at >= start, MoodEntry.at < end)).all()
    out["moods"] = {"logged": len(moods), "counts": dict(Counter(m.mood for m in moods).most_common(6)),
                    "low": sum(m.mood in ("sad", "low", "tired", "stressed", "anxious", "lonely", "overwhelmed", "hurt",
                                          "frustrated") for m in moods)}
    return out


@agent("weekly_analyst")
async def weekly_analyst(ctx: AgentContext) -> None:
    """Sunday night, before the report is written: the facts on where you're lagging go into it."""
    week = ctx.event.payload.get("week_of")
    if not week:
        return
    found = analyse_week(ctx.db, date.fromisoformat(week))
    key = f"week_analysis:{week}"
    row = ctx.db.get(KeyValue, key)
    if row is None:
        ctx.db.add(KeyValue(key=key, value=json.dumps(found)))
    else:
        row.value = json.dumps(found)
    ctx.db.flush()
    ctx.notes["week_analysis"] = found


# ---------- your why: the vision, and reminding you of it when you waver ----------

VISION_TALK = re.compile(r"\b(in|within|next|after)\s+(1|one|a|3|three|5|five)\s+years?\b|\bmy vision\b|\bmy dream\b", re.I)


@agent("vision_keeper")
async def vision_keeper(ctx: AgentContext) -> AgentResult | None:
    """You talk about where you want to be in 1 / 3 / 5 years → it's kept (and the 🎯 screen shows it)."""
    text = str(ctx.event.payload.get("text", ""))
    if ctx.event.payload.get("button") or not VISION_TALK.search(text):
        return None
    found = {}
    if ctx.settings.llm_available:
        try:
            raw = await llm.complete([
                {"role": "system", "content": "Extract the person's vision from their message. JSON only: "
                 '{"y1": string|null, "y3": string|null, "y5": string|null} — where they want to be in 1, 3 and 5 '
                 "years, in their own words, first person. null when they didn't say. No guessing."},
                {"role": "user", "content": text}], tier="fast", temperature=0, max_tokens=300, json_mode=True)
            found = {k: v for k, v in json.loads(raw).items() if k in vision.HORIZONS and v}
        except (llm.LLMUnavailable, ValueError, TypeError, AttributeError):
            found = {}
    if not found:
        m = re.search(r"\b(1|one|a|3|three|5|five)\s+years?\b", text, re.I)
        h = {"1": "y1", "one": "y1", "a": "y1", "3": "y3", "three": "y3", "5": "y5", "five": "y5"}.get(m.group(1).lower()) if m else None
        if h:
            found = {h: text.strip()}
    if not found:
        return None
    vision.put(ctx.db, **found)
    ctx.notes["vision_saved"] = found
    return None  # the chat reply carries on; the 🎯 screen shows what was kept


@agent("motivation_coach")
async def motivation_coach(ctx: AgentContext) -> AgentResult | None:
    """You skipped something that matters: the reason you're doing it, once a day — fuel, not guilt."""

    task = ctx.db.get(Task, ctx.event.payload.get("task_id"))
    if task is None or task.priority < 4:
        return None
    key = f"why_reminded:{local(datetime.now(timezone.utc)).date().isoformat()}"
    if ctx.db.get(KeyValue, key) is not None:
        return None
    goal = ctx.db.get(Goal, task.goal_id) if task.goal_id else None
    if goal is None and (c := courses.course_for(ctx.db, task)) and c.goal_id:
        goal = ctx.db.get(Goal, c.goal_id)
    why = (goal.why if goal and goal.why else "") or ""
    dream = vision.line(ctx.db)
    if not (why or dream or goal):
        return None
    ctx.db.add(KeyValue(key=key, value="1"))
    return await _speak_up(
        ctx, instruction=(f"I just skipped '{task.title}'. Remind me why it matters, in two short spoken sentences — "
                          f"fuel, not guilt. Goal: {goal.title if goal else 'none'}. My why: {why or 'not written'}. "
                          f"My vision: {dream or 'not written'}."),
        fallback=f"Remember why you're doing this: {why or (goal.title if goal else dream)}. One skip is fine; two is a pattern.",
        mood="warm and caring, but firm", keep_mood=True, channel="web", meta={"kind": "why"})


# ---------- what TRINETRA knows about you, kept current ----------

AUTO = "[auto-profile] "


@agent("profile_keeper")
async def profile_keeper(ctx: AgentContext) -> None:
    """Every night: your patterns from the data (best hours, what you skip, streaks, moods) → one profile memory."""
    from collections import Counter, defaultdict
    from datetime import timedelta

    from app.core import streaks
    from app.db.models import Memory, MoodEntry, TaskStatus

    now = datetime.now(timezone.utc)
    since = now - timedelta(days=28)
    tasks = ctx.db.scalars(select(Task).where(Task.planned_start >= since, Task.planned_end < now,
                                              Task.notify != "none", Task.category != "sleep")).all()
    if len(tasks) < 5:
        return
    by_hour, by_cat = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
    for t in tasks:
        ok = t.status == TaskStatus.DONE
        h = local(t.planned_start).hour
        band = "mornings" if h < 12 else "afternoons" if h < 17 else "evenings"
        by_hour[band][0] += ok
        by_hour[band][1] += 1
        by_cat[t.category][0] += ok
        by_cat[t.category][1] += 1
    rate = lambda p: round(100 * p[0] / p[1]) if p[1] else 0  # noqa: E731
    bands = sorted(by_hour.items(), key=lambda kv: -rate(kv[1]))
    weak = [c for c, p in by_cat.items() if p[1] >= 3 and rate(p) < 50]
    s = [x for x in streaks.all_streaks(ctx.db) if x["best"] >= 2]
    moods = Counter(m.mood for m in ctx.db.scalars(select(MoodEntry).where(MoodEntry.at >= since)).all())
    total = [sum(p[0] for p in by_cat.values()), sum(p[1] for p in by_cat.values())]
    parts = [f"Finishes {rate(total)}% of planned blocks"
             + (f": {rate(bands[0][1])}% in the {bands[0][0]} vs {rate(bands[-1][1])}% in the {bands[-1][0]}."
                if len(bands) > 1 else f", mostly in the {bands[0][0]}.")]
    if weak:
        parts.append("Often skips: " + ", ".join(weak) + ".")
    skipped = Counter(t.title for t in tasks if t.status == TaskStatus.SKIPPED).most_common(2)
    if skipped:
        parts.append("Most skipped: " + ", ".join(f"{n} ({c}×)" for n, c in skipped) + ".")
    if s:
        parts.append("Streaks: " + ", ".join(f"{x['label']} {x['current']} (best {x['best']})" for x in s) + ".")
    if moods:
        parts.append("Most common moods lately: " + ", ".join(m for m, _ in moods.most_common(3)) + ".")
    content = AUTO + " ".join(p for p in parts if p) + f" (last 28 days, updated {local(now):%d %b})"
    old = ctx.db.scalars(select(Memory).where(Memory.content.like(AUTO + "%"))).all()
    for m in old:
        ctx.db.delete(m)
    ctx.db.add(Memory(kind="habit", content=content[:1000], importance=4))
    ctx.db.flush()
