"""The mentor's arithmetic: how your week really went, where to raise the bar, and turning plans into blocks.

Progressive overload (the "surpass your limits" rule), per area over the last 14 days:
    completion ≥ 80%  → raise the bar  (longer / more blocks, a stretch goal)
    completion < 50%  → ease off       (smaller blocks) and find the blocker
    otherwise         → hold steady
Needs at least MIN_BLOCKS finished-or-skipped blocks in an area before judging it.
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import timetable
from app.core.timeutil import from_db, now_local
from app.db.models import Goal, Promise, Task, TaskStatus

MIN_BLOCKS = 4
RAISE_AT, EASE_AT = 0.8, 0.5


@dataclass
class AreaStats:
    area: str
    done: int
    skipped: int

    @property
    def total(self) -> int:
        return self.done + self.skipped

    @property
    def rate(self) -> float:
        return self.done / self.total if self.total else 0.0


def area_stats(db: Session, days: int, now: datetime | None = None) -> list[AreaStats]:
    now = now or datetime.now(timezone.utc)
    rows = db.scalars(
        select(Task).where(
            Task.planned_start >= now - timedelta(days=days), Task.planned_start < now,
            Task.status.in_([TaskStatus.DONE, TaskStatus.SKIPPED]),
        )
    ).all()
    by_area: dict[str, AreaStats] = {}
    for t in rows:
        s = by_area.setdefault(t.category, AreaStats(t.category, 0, 0))
        if t.status == TaskStatus.DONE:
            s.done += 1
        else:
            s.skipped += 1
    return sorted(by_area.values(), key=lambda s: -s.total)


def challenges(db: Session, now: datetime | None = None) -> list[dict]:
    """The progressive-overload verdict for every area with enough history."""
    out = []
    for s in area_stats(db, 14, now):
        if s.total < MIN_BLOCKS:
            continue
        verdict = "raise" if s.rate >= RAISE_AT else "ease" if s.rate < EASE_AT else "hold"
        out.append({"area": s.area, "rate": round(s.rate, 2), "done": s.done, "skipped": s.skipped,
                    "verdict": verdict})
    return out


def week_summary(db: Session, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    week = area_stats(db, 7, now)
    promises = db.scalars(
        select(Promise).where(Promise.due_at >= now - timedelta(days=7), Promise.due_at < now)
    ).all()
    goals = db.scalars(select(Goal).where(Goal.status == "active")).all()
    return {
        "areas": [{"area": s.area, "done": s.done, "skipped": s.skipped, "rate": round(s.rate, 2)} for s in week],
        "done": sum(s.done for s in week),
        "skipped": sum(s.skipped for s in week),
        "promises_kept": sum(p.status == "kept" for p in promises),
        "promises_broken": sum(p.status == "broken" for p in promises),
        "goals": [{"title": g.title, "why": g.why, "progress": round(g.progress, 2)} for g in goals],
    }


def refresh_goal_progress(db: Session, goal: Goal) -> float:
    """Milestones carry the weight; with none, completed linked blocks give a gentle signal."""
    if goal.milestones:
        goal.progress = sum(m.done_at is not None for m in goal.milestones) / len(goal.milestones)
    return goal.progress


def next_occurrence(days: set[int], start: time) -> date:
    """The first date on or after today (and still ahead if today) that falls on one of `days`."""
    now = now_local()
    for offset in range(8):
        d = now.date() + timedelta(days=offset)
        if d.weekday() in days and (offset > 0 or start > now.time()):
            return d
    return now.date() + timedelta(days=7)


def apply_plan(db: Session, goal_id: int | None, blocks: list[dict]) -> list[str]:
    """Turn an approved weekly plan into recurring timetable blocks linked to the goal."""
    added = []
    busy: dict[int, list[tuple[int, int]]] = {}  # weekday → [(start_min, end_min)] already planned
    for b in blocks:
        days = timetable.parse_recurrence(b.get("days"))
        try:
            h, m = map(int, str(b.get("start", "")).split(":")[:2])
            begin = (h % 24) * 60 + m
        except ValueError:
            continue
        if not days or not b.get("title"):
            continue
        minutes = max(15, min(int(b.get("duration_min") or 60), 240))
        # Guard: the model sometimes double-books. Push this block after any clash (+30 min breathing room).
        moved = True
        while moved:
            moved = False
            for d in days:
                for s0, e0 in busy.get(d, []):
                    if begin < e0 + 30 and s0 < begin + minutes + 30:
                        begin, moved = e0 + 30, True
        if begin + minutes > 23 * 60 + 59:
            continue  # no room left that day — better to drop it than plan past midnight
        for d in days:
            busy.setdefault(d, []).append((begin, begin + minutes))
        start = time(begin // 60, begin % 60)
        end = (datetime.combine(date.today(), start) + timedelta(minutes=minutes)).time()
        created = timetable.create_block(
            db, str(b["title"])[:200], next_occurrence(days, start), start, end,
            category=str(b.get("category") or "study")[:50], priority=4, recurrence=b.get("days"), goal_id=goal_id,
        )
        if created:
            added.append(f"{b['title']} ({b['days']} {start:%H:%M}, {minutes} min)")
    db.flush()
    return added


def due_promises(db: Session, now: datetime) -> list[Promise]:
    return db.scalars(
        select(Promise).where(Promise.status == "open", Promise.asked_at.is_(None), Promise.due_at <= now)
    ).all()


def overdue_hours(p: Promise, now: datetime) -> float:
    return (now - from_db(p.due_at)).total_seconds() / 3600
