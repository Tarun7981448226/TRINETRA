"""Coaching: looking back at the week and ahead at the goals."""
import json
from datetime import date, datetime, timezone

from sqlalchemy import select

from app.core import courses, report, roadmap
from app.core.orchestrator import AgentContext
from app.core.registry import agent
from app.core.timeutil import from_db, local
from app.db.models import Course, Goal, KeyValue


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
