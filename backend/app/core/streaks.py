"""Streaks: days in a row you did the thing (wake-up, TUF/DSA, gym, ML)."""
import re
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.timeutil import local, now_local, to_utc
from app.db.models import StudyItem, Task, TaskStatus, WakeSession

KINDS = {
    "wake": "Wake-up",
    "dsa": "TUF / DSA",
    "gym": "Gym",
    "ml": "ML course",
}
MILESTONES = (3, 5, 7, 10, 14, 21, 30, 45, 60, 75, 100, 150, 200, 365)
MATCH = {"dsa": re.compile(r"\bTUF\b|\bDSA\b", re.I), "gym": re.compile(r"\bgym\b|workout", re.I),
         "ml": re.compile(r"\bML Specialization\b|\bCoursera\b", re.I)}


def kind_of(task: Task) -> str | None:
    if task.category == "fitness" or MATCH["gym"].search(task.title):
        return "gym"
    for k in ("dsa", "ml"):
        if MATCH[k].search(task.title):
            return k
    return None


def _days_done(db: Session, kind: str, start: date, end: date) -> set[date]:
    """Local dates in [start, end] when it was done."""
    lo, hi = to_utc(datetime.combine(start, time.min)), to_utc(datetime.combine(end + timedelta(days=1), time.min))
    if kind == "wake":
        rows = db.scalars(select(WakeSession).where(WakeSession.day >= start.isoformat(), WakeSession.day <= end.isoformat(),
                                                    WakeSession.solved_at.is_not(None))).all()
        return {date.fromisoformat(r.day) for r in rows}
    days = set()
    for t in db.scalars(select(Task).where(Task.planned_start >= lo, Task.planned_start < hi,
                                           Task.status == TaskStatus.DONE)).all():
        if kind_of(t) == kind:
            days.add(local(t.planned_start).date())
    if kind in ("dsa", "ml"):  # ticking course items counts too
        from app.db.models import Course
        key = "tuf" if kind == "dsa" else "ml"
        course = db.scalar(select(Course).where(Course.key == key))
        if course:
            for i in db.scalars(select(StudyItem).where(StudyItem.course_id == course.id, StudyItem.task_id.is_not(None),
                                                        StudyItem.done_at >= lo, StudyItem.done_at < hi)).all():
                days.add(local(i.done_at).date())
    return days


def streak(db: Session, kind: str, today: date | None = None, lookback: int = 200) -> dict:
    today = today or now_local().date()
    done = _days_done(db, kind, today - timedelta(days=lookback), today)
    d, current = today if today in done else today - timedelta(days=1), 0
    while d in done:
        current += 1
        d -= timedelta(days=1)
    best = run = 0
    for i in range(lookback, -1, -1):
        run = run + 1 if (today - timedelta(days=i)) in done else 0
        best = max(best, run)
    return {"kind": kind, "label": KINDS[kind], "current": current, "best": best, "today": today in done,
            "at_risk": current > 0 and today not in done}


def all_streaks(db: Session, today: date | None = None) -> list[dict]:
    return [streak(db, k, today) for k in KINDS]
