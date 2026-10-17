"""Planning ahead: does the time on the timetable cover what the courses need?

The TUF plan says what's due each day (with minutes); the timetable says how much TUF time there is. When the
work doesn't fit, TRINETRA proposes catch-up blocks in real free gaps — you approve or reject, nothing is added
on its own. Used by the Daily Planner (9 pm), the Replanner (a block ended short) and the Weekly Planner (Sunday).
"""
import re
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import courses
from app.core.timeutil import from_db, local, to_utc
from app.db.models import Course, Message, Task, TaskStatus

DAY_END = time(23, 0)      # catch-up blocks end by 23:00 (sleep comes first)
MIN_GAP = 45               # minutes: shorter gaps aren't worth a block
MAX_BLOCK = 120            # one catch-up block at most 2 h
SLACK = 15                 # minutes of shortfall we let slide


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    return to_utc(datetime.combine(day, time.min)), to_utc(datetime.combine(day + timedelta(days=1), time.min))


def blocks_on(db: Session, day: date) -> list[Task]:
    s, e = _day_bounds(day)
    return db.scalars(select(Task).where(Task.planned_start < e, Task.planned_end > s, Task.status != TaskStatus.SKIPPED)
                      .order_by(Task.planned_start)).all()


def free_gaps(db: Session, day: date, wake: time, after: datetime | None = None) -> list[tuple[datetime, datetime]]:
    """Gaps of MIN_GAP+ minutes between wake-up and DAY_END that no block covers (5 min of air on each side)."""
    start = to_utc(datetime.combine(day, wake))
    if after:
        start = max(start, after)
    stop = to_utc(datetime.combine(day, DAY_END))
    gaps, cur = [], start
    for t in blocks_on(db, day):
        s, e = from_db(t.planned_start), from_db(t.planned_end)
        if s - timedelta(minutes=5) > cur:
            gaps.append((cur, s - timedelta(minutes=5)))
        cur = max(cur, e + timedelta(minutes=5))
    if stop > cur:
        gaps.append((cur, stop))
    return [(a, b) for a, b in gaps if (b - a).total_seconds() / 60 >= MIN_GAP]


def load(db: Session, c: Course, day: date) -> dict:
    """For one day: minutes the course wants (due that day + overdue from before) vs minutes of its blocks."""
    iso = day.isoformat()
    open_items = [i for i in courses.items(db, c) if not i.done_at and not i.optional]
    due = [i for i in open_items if i.planned_date == iso]
    overdue = [i for i in open_items if i.planned_date and i.planned_date < iso]
    capacity = sum((from_db(t.planned_end) - from_db(t.planned_start)).total_seconds() / 60
                   for t in blocks_on(db, day) if re.search(c.block_match, t.title, re.I)
                   and t.status in (TaskStatus.PLANNED, TaskStatus.STARTED))
    need = sum(i.est_min or 10 for i in due + overdue)
    return {"course": c.title, "key": c.key, "due": len(due), "overdue": len(overdue), "need_min": round(need),
            "capacity_min": round(capacity), "short_min": max(0, round(need - capacity)),
            "section": due[0].section if due else None}


def catch_up_ops(db: Session, c: Course, day: date, short_min: int, wake: time, after: datetime | None = None,
                 max_blocks: int = 2) -> list[dict]:
    """Create-ops for catch-up blocks that fit real free gaps on that day."""
    ops, left = [], short_min
    for a, b in free_gaps(db, day, wake, after):
        if left <= SLACK or len(ops) >= max_blocks:
            break
        minutes = min(MAX_BLOCK, left, round((b - a).total_seconds() / 60))
        if minutes < MIN_GAP:
            continue
        s = local(a)
        s = (s + timedelta(minutes=(-s.minute) % 15)).replace(second=0, microsecond=0)  # start on a quarter hour
        if s + timedelta(minutes=minutes) > local(b):
            minutes = round((local(b) - s).total_seconds() / 60)
            if minutes < MIN_GAP:
                continue
        label = "TUF DSA" if c.key == "tuf" else "ML Specialization"
        ops.append({"op": "create", "title": f"{label} — catch-up", "date": day.isoformat(), "start": s.strftime("%H:%M"),
                    "duration_min": minutes, "category": "study", "priority": 4, "goal_id": c.goal_id})
        left -= minutes
    return ops


def propose(db: Session, ops: list[dict], why: str, mood: str = "focused and sharp") -> Message | None:
    """A schedule proposal message with Approve / Reject (nothing changes until you approve)."""
    if not ops:
        return None
    def line(o: dict) -> str:
        if o.get("op") == "delete":
            t = db.get(Task, o["id"])
            return f"• Drop {t.title} ({local(t.planned_start):%a %H:%M})" if t else "• Drop a block"
        return f"• {o['title']}: {date.fromisoformat(o['date']):%a %d %b} {o['start']}, {o['duration_min']} min"

    lines = [line(o) for o in ops]
    msg = Message(role="trinetra", channel="reminder", mood=mood,
                  content=f"{why}\n" + ("Here's what I'd change:\n" if any(o.get("op") == "delete" for o in ops)
                                         else "Here's what I'd add:\n") + "\n".join(lines),
                  meta={"kind": "schedule_proposal", "ops": ops, "original_ops": ops, "buttons": ["approve", "reject"],
                        "why": why})
    db.add(msg)
    db.flush()
    msg.meta = {**msg.meta, "respond": f"/proposals/{msg.id}/respond"}
    db.flush()
    return msg
