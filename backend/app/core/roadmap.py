"""Roadmap forecast: when will each milestone really be finished, given the blocks on the timetable?

A goal's milestones carry `effort_hours`; the goal's linked timetable blocks (e.g. every "TUF DSA" block
for the DSA goal) are the hours available. Walking the pending milestones in roadmap order through those
hours gives a projected start and finish for each, grouped into weekly sprints (Mon–Sun, Sprint 1 = the
week the goal was created). Routines are extended on paper past the 14 days that exist as real rows.
Hours from completed blocks since the last finished milestone count towards the current one.
"""
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.timetable import parse_recurrence
from app.core.timeutil import from_db, local, user_tz
from app.db.models import Goal, Task, TaskStatus

LOOKAHEAD_DAYS = 400


def _hours(a: datetime, b: datetime) -> float:
    return max(0.0, (b - a).total_seconds() / 3600)


def capacity(db: Session, goal: Goal, now: datetime) -> list[tuple[date, float]]:
    """(day, hours) of every future study block for this goal, in time order."""
    tasks = db.scalars(select(Task).where(Task.goal_id == goal.id).order_by(Task.planned_start)).all()
    slots: list[tuple[datetime, float]] = []
    last_by_series: dict[str, Task] = {}
    for t in tasks:
        s, e = from_db(t.planned_start), from_db(t.planned_end)
        if t.series_id:
            last_by_series[t.series_id] = t
        if t.status in (TaskStatus.PLANNED, TaskStatus.STARTED) and e > now:
            slots.append((s, _hours(max(s, now), e)))
    stop_at = local(now).date() + timedelta(days=LOOKAHEAD_DAYS)
    for t in last_by_series.values():  # routines continue beyond the rows that exist yet
        days = parse_recurrence(t.recurrence)
        if not days:
            continue
        s_l, e_l = local(t.planned_start), local(t.planned_end)
        length = e_l - s_l
        stop = min(stop_at, local(t.repeat_until).date()) if t.repeat_until else stop_at
        d = s_l.date() + timedelta(days=1)
        while d <= stop:
            if d.weekday() in days:
                start = datetime.combine(d, s_l.time(), user_tz())
                slots.append((start.astimezone(timezone.utc), length.total_seconds() / 3600))
            d += timedelta(days=1)
    slots.sort()
    return [(local(s).date(), h) for s, h in slots if h > 0]


def _sprint(goal: Goal, d: date) -> int:
    first = local(goal.created_at).date() if goal.created_at else d
    return (d - (first - timedelta(days=first.weekday()))).days // 7 + 1


def forecast(db: Session, goal: Goal, now: datetime | None = None) -> dict | None:
    ms = sorted(goal.milestones, key=lambda m: m.position)
    if not any(m.effort_hours for m in ms):
        return None
    now = now or datetime.now(timezone.utc)
    slots = capacity(db, goal, now)

    finished = [from_db(m.done_at) for m in ms if m.done_at]
    since = max(finished) if finished else None
    done_q = select(Task).where(Task.goal_id == goal.id, Task.status == TaskStatus.DONE)
    credit = sum(_hours(from_db(t.planned_start), from_db(t.planned_end)) for t in db.scalars(done_q)
                 if since is None or from_db(t.planned_end) > since)

    items: dict[int, dict] = {}
    sprints: dict[int, dict] = defaultdict(lambda: {"hours": 0.0, "topics": []})
    i, left_in_slot = 0, slots[0][1] if slots else 0.0
    for m in ms:
        if m.done_at:
            items[m.id] = {"status": "done", "done_on": local(m.done_at).date().isoformat()}
            continue
        need = max(0.0, (m.effort_hours or 0) - credit)
        credit = max(0.0, credit - (m.effort_hours or 0))
        start = finish = None
        while need > 1e-9 and i < len(slots):
            day = slots[i][0]
            use = min(need, left_in_slot)
            start = start or day
            sp = sprints[_sprint(goal, day)]
            sp["hours"] += use
            if m.title not in sp["topics"]:
                sp["topics"].append(m.title)
            need -= use
            left_in_slot -= use
            finish = day
            if left_in_slot <= 1e-9:
                i += 1
                left_in_slot = slots[i][1] if i < len(slots) else 0.0
        if need > 1e-9:
            finish = None  # not enough timetable hours to ever finish it
        elif finish is None:  # nothing left to do (credited) — finishes today
            start = finish = local(now).date()
        due = local(m.due_date).date() if m.due_date else None
        items[m.id] = {
            "status": "pending", "effort_hours": m.effort_hours,
            "start": start.isoformat() if start else None, "finish": finish.isoformat() if finish else None,
            "sprint": _sprint(goal, finish) if finish else None,
            "slip_days": (finish - due).days if finish and due else None,
        }

    week = [h for d, h in slots if d < local(now).date() + timedelta(days=7)]
    finishes = [date.fromisoformat(v["finish"]) for v in items.values() if v.get("finish")]
    pending = [v for v in items.values() if v["status"] == "pending"]
    end = None if any(v["finish"] is None for v in pending) else (max(finishes) if finishes else None)
    target = local(goal.target_date).date() if goal.target_date else None
    return {
        "milestones": items,
        "finish": end.isoformat() if end else None,
        "target": target.isoformat() if target else None,
        "buffer_days": (target - end).days if target and end else None,
        "hours_per_week": round(sum(week), 1),
        "hours_left": round(sum(m.effort_hours or 0 for m in ms if not m.done_at), 1),
        "sprints": [
            {"n": n, "start": (s := _week_start(goal, n)).isoformat(), "end": (s + timedelta(days=6)).isoformat(),
             "hours": round(v["hours"], 1), "topics": v["topics"]}
            for n, v in sorted(sprints.items())
        ],
    }


def _week_start(goal: Goal, n: int) -> date:
    first = local(goal.created_at).date() if goal.created_at else date.today()
    return first - timedelta(days=first.weekday()) + timedelta(weeks=n - 1)


def rebaseline(db: Session, goal: Goal) -> int:
    """Set each pending milestone's due date to its forecast finish (evening of that day). Returns how many."""
    f = forecast(db, goal)
    if not f:
        return 0
    changed = 0
    for m in goal.milestones:
        v = f["milestones"].get(m.id, {})
        if v.get("finish"):
            m.due_date = datetime.combine(date.fromisoformat(v["finish"]), time(21), user_tz()).astimezone(timezone.utc)
            changed += 1
    return changed
