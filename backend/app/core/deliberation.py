"""Thinking before acting on your timetable.

A requested change (a list of ops from the Planner) is first turned into a Proposal: the concrete
time slots it would create over the next REVIEW_DAYS, and which existing blocks it would remove.
The review agents (Sleep Guardian, Buffer Manager, Deadline Tracker, Completion Predictor) each
inspect the Proposal and add Findings. The Critic weighs them; the Arbiter decides whether to act,
act on a safer version, or ask you first. Nothing touches the database until that decision.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import timetable
from app.core.timeutil import local, now_local, user_tz
from app.db.models import KeyValue, Task, TaskStatus

log = logging.getLogger("trinetra.deliberation")

REVIEW_DAYS = 7
DEFAULT_SLEEP = ("23:30", "06:00")  # until you tell TRINETRA your real sleep times
MAX_FOCUS_HOURS = 10
MAX_STRAIGHT_HOURS = 4
BIG_PLAN_SLOTS = 12  # a change this large is a new schedule: always show it before applying


# ---------- parsing the Planner's ops ----------

def parse_time(value) -> time | None:
    if not value:
        return None
    try:
        h, m = str(value).strip().split(":")[:2]
        return time(int(h) % 24, int(m))
    except ValueError:
        return None


def parse_date(value) -> date | None:
    try:
        return date.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def end_time(day: date, start: time, end: time | None, duration_min) -> time:
    if end:
        return end
    minutes = int(duration_min) if duration_min else 60
    return (datetime.combine(day, start) + timedelta(minutes=max(5, min(minutes, 12 * 60)))).time()


# ---------- the proposal ----------

@dataclass
class Slot:
    op: int  # index of the op that produces it
    title: str
    start: datetime  # local, tz-aware
    end: datetime
    category: str = "general"


@dataclass
class Finding:
    agent: str
    severity: str  # "block" (must not happen as-is), "warn" (think twice), "info"
    message: str


@dataclass
class Proposal:
    ops: list[dict]
    slots: list[Slot] = field(default_factory=list)
    removed: set[int] = field(default_factory=set)  # task ids that disappear (deleted, or moved away)
    removed_goal_titles: list[str] = field(default_factory=list)

    @property
    def is_big(self) -> bool:
        return len(self.slots) >= BIG_PLAN_SLOTS

    def describe(self) -> list[str]:
        lines = []
        for i, op in enumerate(self.ops):
            kind = op.get("op")
            if kind in ("create", "move"):
                first = next((s for s in self.slots if s.op == i), None)
                when = f"{first.start:%a %H:%M}–{first.end:%H:%M}" if first else "?"
                rep = f", repeats {op.get('recurrence')}" if op.get("recurrence") else ""
                rep += f" until {op.get('until')}" if op.get("until") and op.get("recurrence") else ""
                lines.append(f"{kind} '{op.get('title') or op.get('id')}' at {when}{rep}")
            elif kind == "delete":
                lines.append(f"delete block #{op.get('id')}" + (" (whole routine)" if op.get("whole_series") else ""))
            elif kind == "set_sleep":
                lines.append(f"sleep window {op.get('start')}–{op.get('end')}")
        return lines


def build(db: Session, ops: list[dict]) -> Proposal:
    """Expand ops into concrete slots over the review window (no database writes)."""
    p = Proposal(ops=ops)
    today = now_local().date()
    horizon = today + timedelta(days=REVIEW_DAYS)
    tz = user_tz()
    for i, op in enumerate(ops):
        kind = op.get("op")
        try:
            if kind == "create":
                start = parse_time(op.get("start"))
                if not start or not op.get("title"):
                    continue
                first = parse_date(op.get("date")) or today
                days = timetable.parse_recurrence(op.get("recurrence"))
                end = end_time(first, start, parse_time(op.get("end")), op.get("duration_min"))
                until = parse_date(op.get("until"))
                stop = min(horizon, until + timedelta(days=1)) if until else horizon
                d = first
                while d < stop and (days or d == first):
                    if days is None or d.weekday() in days:
                        s = datetime.combine(d, start, tz)
                        e = datetime.combine(d, end, tz)
                        p.slots.append(Slot(i, str(op["title"]), s, e if e > s else e + timedelta(days=1),
                                            str(op.get("category") or "general")))
                    if days is None:
                        break
                    d += timedelta(days=1)
            elif kind == "move":
                task = db.get(Task, int(op.get("id")))
                if task is None:
                    continue
                old = local(task.planned_start)
                day = parse_date(op.get("date")) or old.date()
                start = parse_time(op.get("start")) or old.time()
                minutes = (local(task.planned_end) - old).total_seconds() / 60
                end = end_time(day, start, parse_time(op.get("end")), minutes)
                s = datetime.combine(day, start, tz)
                e = datetime.combine(day, end, tz)
                p.slots.append(Slot(i, task.title, s, e if e > s else e + timedelta(days=1), task.category))
                p.removed.add(task.id)
            elif kind == "delete":
                task = db.get(Task, int(op.get("id")))
                if task is None:
                    continue
                gone = [task]
                if op.get("whole_series") and task.series_id:
                    gone = db.scalars(select(Task).where(Task.series_id == task.series_id,
                                                         Task.planned_start >= task.planned_start)).all()
                for t in gone:
                    p.removed.add(t.id)
                    if t.goal_id and t.title not in p.removed_goal_titles:
                        p.removed_goal_titles.append(t.title)
        except (TypeError, ValueError) as e:
            log.warning("unreadable op %s: %s", op, e)
    return p


# ---------- what the review agents check ----------

def sleep_window(db: Session) -> tuple[time, time]:
    row = db.get(KeyValue, "sleep_window")
    start, end = (row.value.split("-") if row and row.value else DEFAULT_SLEEP)
    return parse_time(start) or time(23, 30), parse_time(end) or time(6)


def set_sleep_window(db: Session, start: time, end: time) -> None:
    value = f"{start:%H:%M}-{end:%H:%M}"
    row = db.get(KeyValue, "sleep_window")
    if row is None:
        db.add(KeyValue(key="sleep_window", value=value))
    else:
        row.value = value


SLEEP_CATEGORY = "sleep"


def sync_sleep_blocks(db: Session) -> int:
    """Show the sleep window on the timetable as a daily 'Sleep' routine (with a bedtime reminder).
    Future sleep blocks are replaced, so changing the window moves them. Returns blocks created."""
    now = datetime.now(timezone.utc)
    for t in db.scalars(select(Task).where(Task.category == SLEEP_CATEGORY, Task.status == TaskStatus.PLANNED,
                                           Task.planned_start > now)):
        db.delete(t)
    db.flush()
    start, end = sleep_window(db)
    today = now_local().date()
    first = today if datetime.combine(today, start, user_tz()) > now_local() else today + timedelta(days=1)
    return len(timetable.create_block(db, "Sleep — rest up", first, start, end, category=SLEEP_CATEGORY,
                                      priority=5, recurrence="daily", notify="remind"))


def _overlaps(a0: datetime, a1: datetime, b0: datetime, b1: datetime) -> bool:
    return a0 < b1 and b0 < a1


def check_sleep(db: Session, p: Proposal) -> list[Finding]:
    s_start, s_end = sleep_window(db)
    out = []
    for slot in p.slots:
        d, tz = slot.start.date(), slot.start.tzinfo
        if s_start > s_end:  # bedtime before midnight (23:30–06:00): the night spans two dates
            nights = [(datetime.combine(d - timedelta(days=1), s_start, tz), datetime.combine(d, s_end, tz)),
                      (datetime.combine(d, s_start, tz), datetime.combine(d + timedelta(days=1), s_end, tz))]
        else:  # bedtime at/after midnight (00:00–06:00): the night sits inside one date
            nights = [(datetime.combine(d, s_start, tz), datetime.combine(d, s_end, tz)),
                      (datetime.combine(d + timedelta(days=1), s_start, tz),
                       datetime.combine(d + timedelta(days=1), s_end, tz))]
        if any(_overlaps(slot.start, slot.end, n0, n1) for n0, n1 in nights):
            out.append(Finding("sleep_guardian", "block",
                               f"'{slot.title}' {slot.start:%a %H:%M}–{slot.end:%H:%M} cuts into sleep "
                               f"({s_start:%H:%M}–{s_end:%H:%M})"))
            break  # one is enough to make the point
    return out


def _existing(db: Session, p: Proposal) -> list[Task]:
    if not p.slots:
        return []
    lo = min(s.start for s in p.slots) - timedelta(hours=12)
    hi = max(s.end for s in p.slots) + timedelta(hours=12)
    rows = db.scalars(select(Task).where(
        Task.planned_start < hi, Task.planned_end > lo,
        Task.status.in_([TaskStatus.PLANNED, TaskStatus.STARTED]),
    )).all()
    return [t for t in rows if t.id not in p.removed]


def check_buffers(db: Session, p: Proposal) -> list[Finding]:
    """Clashes with existing blocks or each other, marathons with no break, and overloaded days."""
    out: list[Finding] = []
    existing = [(local(t.planned_start), local(t.planned_end), t.title) for t in _existing(db, p)
                if t.category != SLEEP_CATEGORY]  # sleep is the Sleep Guardian's job
    seen = set()
    for i, slot in enumerate(p.slots):
        for s0, s1, title in existing:
            if _overlaps(slot.start, slot.end, s0, s1) and (slot.title, title) not in seen:
                seen.add((slot.title, title))
                out.append(Finding("buffer_manager", "block",
                                   f"'{slot.title}' {slot.start:%a %H:%M} clashes with '{title}' {s0:%H:%M}–{s1:%H:%M}"))
        for other in p.slots[i + 1:]:
            if other.op != slot.op and _overlaps(slot.start, slot.end, other.start, other.end):
                out.append(Finding("buffer_manager", "block",
                                   f"'{slot.title}' and '{other.title}' overlap on {slot.start:%a}"))
    # Load and breaks: only judged on days this change touches, and only where the NEW blocks are part of
    # the problem (your existing schedule isn't re-litigated on every edit).
    by_day: dict[date, list[tuple[datetime, datetime, bool]]] = {}
    for s0, s1, _ in existing:
        by_day.setdefault(s0.date(), []).append((s0, s1, False))
    for slot in p.slots:
        by_day.setdefault(slot.start.date(), []).append((slot.start, slot.end, True))
    flagged_load = flagged_break = False
    for d in sorted({s.start.date() for s in p.slots}):
        spans = sorted(by_day.get(d, []))
        # merge overlaps (lunch inside a class isn't extra hours), tracking how many blocks and if any is new
        runs: list[list] = []  # [start, end, n_blocks, has_new, gapless_run_start]
        merged: list[list] = []
        for s0, s1, new in spans:
            if merged and s0 < merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], s1)
                merged[-1][2] = merged[-1][2] or new
            else:
                merged.append([s0, s1, new])
        total = sum((e - s0).total_seconds() for s0, e, _ in merged) / 3600
        if total > MAX_FOCUS_HOURS and not flagged_load and any(n for *_, n in merged):
            flagged_load = True
            out.append(Finding("buffer_manager", "warn", f"{d:%a} would have {total:.0f}h of blocks — that's a lot"))
        for s0, s1, new in merged:  # chain blocks with < 15 min between them
            if runs and s0 - runs[-1][1] < timedelta(minutes=15):
                runs[-1][1] = max(runs[-1][1], s1)
                runs[-1][2] += 1
                runs[-1][3] = runs[-1][3] or new
            else:
                runs.append([s0, s1, 1, new])
        for r0, r1, n, has_new in runs:
            if n >= 2 and has_new and r1 - r0 > timedelta(hours=MAX_STRAIGHT_HOURS) and not flagged_break:
                flagged_break = True
                out.append(Finding("buffer_manager", "warn",
                                   f"{d:%a} becomes {(r1 - r0).total_seconds() / 3600:.0f}h back-to-back from "
                                   f"{r0:%H:%M} with no break"))
    past = [s for s in p.slots if s.end < now_local()]
    if past:
        out.append(Finding("buffer_manager", "warn", f"'{past[0].title}' at {past[0].start:%a %H:%M} is already in the past"))
    return out


def check_goals(p: Proposal) -> list[Finding]:
    if not p.removed_goal_titles:
        return []
    return [Finding("deadline_tracker", "warn",
                    f"removing goal work: {', '.join(p.removed_goal_titles[:3])} — that slows a goal down")]


def check_odds(db: Session, p: Proposal) -> list[Finding]:
    """Ask the neural core how likely you are to actually do each new block at its time."""
    from app.core.timeutil import to_utc
    from app.ml import neural_core

    out, judged = [], set()
    for slot in p.slots:
        if slot.op in judged:
            continue
        judged.add(slot.op)
        probe = Task(title=slot.title, category=slot.category, priority=3,
                     planned_start=to_utc(slot.start), planned_end=to_utc(slot.end))
        odds = neural_core.predict(db, probe)
        if odds < 0.35:
            out.append(Finding("completion_predictor", "warn",
                               f"you follow through on '{slot.title}' at {slot.start:%H:%M} only ~{round(odds * 100)}% "
                               "of the time — a different hour may work better"))
    return out


def apply(db: Session, ops: list[dict]) -> list[str]:
    """Carry out ops for real. Returns human-readable changes."""
    from app.core.timeutil import to_utc

    changes = []
    today = now_local().date()
    for op in ops:
        kind = op.get("op")
        try:
            if kind == "create":
                start = parse_time(op.get("start"))
                title = str(op.get("title", "")).strip()[:200]
                if not (start and title):
                    continue
                day = parse_date(op.get("date")) or today
                end = end_time(day, start, parse_time(op.get("end")), op.get("duration_min"))
                created = timetable.create_block(
                    db, title, day, start, end, category=str(op.get("category") or "general")[:50],
                    priority=min(max(int(op.get("priority") or 3), 1), 5), recurrence=op.get("recurrence"),
                    until=parse_date(op.get("until")), notify=str(op.get("notify") or "full"),
                    goal_id=op.get("goal_id") if isinstance(op.get("goal_id"), int) else None,
                )
                if created:
                    rep = f" ({len(created)} blocks scheduled)" if created[0].recurrence else ""
                    changes.append(f"added {timetable.describe(created[0])}{rep}")
            elif kind == "set_sleep":
                s, e = parse_time(op.get("start")), parse_time(op.get("end"))
                if s and e:
                    set_sleep_window(db, s, e)
                    sync_sleep_blocks(db)
                    changes.append(f"sleep window set to {s:%H:%M}–{e:%H:%M}")
            elif kind in ("move", "delete", "status"):
                task = db.get(Task, int(op.get("id")))
                if task is None:
                    continue
                if kind == "move":
                    old = local(task.planned_start)
                    day = parse_date(op.get("date")) or old.date()
                    start = parse_time(op.get("start")) or old.time()
                    minutes = float(op.get("duration_min") or (local(task.planned_end) - old).total_seconds() / 60)
                    end = end_time(day, start, parse_time(op.get("end")), minutes)
                    s, e = datetime.combine(day, start), datetime.combine(day, end)
                    timetable.move(task, s, e if e > s else e + timedelta(days=1))
                    changes.append(f"moved to {timetable.describe(task)}")
                elif kind == "delete":
                    if op.get("whole_series") and task.series_id:
                        future = db.scalars(select(Task).where(Task.series_id == task.series_id,
                                                               Task.planned_start >= task.planned_start)).all()
                        for t in future:
                            db.delete(t)
                        changes.append(f"removed routine '{task.title}' ({len(future)} blocks)")
                    else:
                        changes.append(f"removed {timetable.describe(task)}")
                        db.delete(task)
                else:
                    status = TaskStatus(op.get("status"))
                    timetable.set_status(task, status)
                    changes.append(f"marked {status}: {task.title}")
        except (TypeError, ValueError) as e:
            log.warning("bad op %s: %s", op, e)
    db.flush()
    return changes
