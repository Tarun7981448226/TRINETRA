"""Timetable mechanics: creating blocks, repeating routines, moving and finishing things.

Routines ("gym at 6 every weekday") are stored as concrete Task rows linked by series_id,
materialised SERIES_HORIZON_DAYS ahead and topped up by the scheduler. Concrete rows keep
the ML brain simple: every planned block is one row with a plan and an outcome.
"""
import uuid
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.timeutil import from_db, local, now_local, to_utc, user_tz
from app.db.models import Task, TaskStatus

SERIES_HORIZON_DAYS = 14
NOTIFY_LEVELS = ("full", "remind", "none")
DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def parse_recurrence(rule: str | None) -> set[int] | None:
    """'daily' / 'weekdays' / 'weekends' / 'mon,wed,fri' → set of weekday numbers (Mon=0)."""
    if not rule:
        return None
    rule = rule.strip().lower()
    if rule in ("daily", "everyday", "every day"):
        return set(range(7))
    if rule == "weekdays":
        return set(range(5))
    if rule == "weekends":
        return {5, 6}
    days = {DAY_NAMES.index(d.strip()[:3]) for d in rule.split(",") if d.strip()[:3] in DAY_NAMES}
    return days or None


def _local_dt(d: date, t: time) -> datetime:
    return datetime.combine(d, t, user_tz())


def create_block(
    db: Session,
    title: str,
    day: date,
    start: time,
    end: time,
    category: str = "general",
    priority: int = 3,
    recurrence: str | None = None,
    goal_id: int | None = None,
    until: date | None = None,
    notify: str = "full",
) -> list[Task]:
    """Create a one-off block, or a routine (one row per occurrence up to the horizon, or `until`)."""
    days = parse_recurrence(recurrence)
    if days is None:
        recurrence = None
        until = None
    notify = notify if notify in NOTIFY_LEVELS else "full"
    series_id = str(uuid.uuid4()) if days else None
    last_day = day + timedelta(days=SERIES_HORIZON_DAYS - 1) if days else day
    if until is not None:
        last_day = min(last_day, until)
    repeat_until = to_utc(datetime.combine(until, time(23, 59))) if until else None
    created = []
    d = day
    while d <= last_day:
        if days is None or d.weekday() in days:
            s = _local_dt(d, start)
            e = _local_dt(d, end)
            if e <= s:  # crosses midnight, e.g. 23:00–01:00
                e += timedelta(days=1)
            task = Task(
                title=title, category=category, priority=priority, recurrence=recurrence,
                series_id=series_id, goal_id=goal_id, planned_start=to_utc(s), planned_end=to_utc(e),
                repeat_until=repeat_until, notify=notify,
            )
            db.add(task)
            created.append(task)
        d += timedelta(days=1)
    db.flush()
    return created


def extend_series(db: Session, horizon_days: int = SERIES_HORIZON_DAYS) -> int:
    """Keep every routine filled out to the horizon. Returns how many blocks were added."""
    horizon = now_local().date() + timedelta(days=horizon_days - 1)
    latest = db.execute(
        select(Task.series_id, func.max(Task.planned_start)).where(Task.series_id.is_not(None)).group_by(Task.series_id)
    ).all()
    added = 0
    for series_id, last_start in latest:
        template = db.scalars(
            select(Task).where(Task.series_id == series_id).order_by(Task.planned_start.desc()).limit(1)
        ).one()
        days = parse_recurrence(template.recurrence)
        if not days:
            continue
        # The routine's usual time, not the latest occurrence's: if that one block was moved (a one-off), copying it
        # would move every future block too. Most common start and length over the last 7 occurrences.
        from collections import Counter
        # upcoming occurrences only: a deliberate change to the routine moves all of them, a one-off moves one
        recent = db.scalars(select(Task).where(Task.series_id == series_id, Task.planned_start >= to_utc(now_local()))
                            .order_by(Task.planned_start.desc()).limit(14)).all() or [template]
        usual = Counter((local(t.planned_start).time(), local(t.planned_end) - local(t.planned_start)) for t in recent)
        (start_time, duration), _ = usual.most_common(1)[0]  # a tie goes to the most recent (Counter keeps order)
        start_l = local(template.planned_start).replace(hour=start_time.hour, minute=start_time.minute)
        d = local(last_start).date() + timedelta(days=1)
        stop = min(horizon, local(template.repeat_until).date()) if template.repeat_until else horizon
        while d <= stop:
            if d.weekday() in days:
                s = _local_dt(d, start_l.time())
                db.add(Task(
                    title=template.title, category=template.category, priority=template.priority,
                    recurrence=template.recurrence, series_id=series_id, goal_id=template.goal_id,
                    repeat_until=template.repeat_until, notify=template.notify,
                    planned_start=to_utc(s), planned_end=to_utc(s + duration),
                ))
                added += 1
            d += timedelta(days=1)
    db.flush()
    return added


def upcoming(db: Session, days: int = 7) -> list[Task]:
    start = to_utc(datetime.combine(now_local().date(), time.min))
    return db.scalars(
        select(Task)
        .where(Task.planned_start >= start, Task.planned_start < start + timedelta(days=days))
        .order_by(Task.planned_start)
    ).all()


def describe(task: Task) -> str:
    s, e = local(task.planned_start), local(task.planned_end)
    rep = f", repeats {task.recurrence}" if task.recurrence else ""
    return f"#{task.id} {s:%a %d %b %H:%M}–{e:%H:%M} {task.title} [{task.status}{rep}]"


def move(task: Task, start: datetime, end: datetime) -> None:
    task.planned_start, task.planned_end = to_utc(start), to_utc(end)
    task.reminded_at = task.checkin_at = None
    task.nag_count = 0
    task.status = TaskStatus.PLANNED


def set_status(task: Task, status: TaskStatus) -> None:
    now = datetime.now(timezone.utc)
    if status == TaskStatus.STARTED and task.actual_start is None:
        task.actual_start = now
    if status == TaskStatus.DONE:
        task.actual_start = task.actual_start or from_db(task.planned_start)
        task.actual_end = now
    task.status = status
