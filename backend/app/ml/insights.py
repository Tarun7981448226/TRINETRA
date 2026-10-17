"""What your own history says: how long things really take, when you're sharp, what you push off, what goes together.

Plain statistics on your blocks (no black box): every number here can be read back to the days it came from.
Kept in one KeyValue ("insights") that the planner, the profile, the weekly report and the 📊 screen read.
"""
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import streaks
from app.core.timeutil import from_db, local
from app.db.models import KeyValue, MoodEntry, Task, TaskStatus, WakeSession

KEY = "insights"
WINDOW = timedelta(days=28)
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
LOW = {"sad", "low", "tired", "stressed", "anxious", "lonely", "overwhelmed", "hurt", "frustrated"}


def load(db: Session) -> dict:
    row = db.get(KeyValue, KEY)
    return json.loads(row.value) if row and row.value else {}


def save(db: Session, **parts) -> dict:
    data = {**load(db), **parts, "updated": datetime.now(timezone.utc).isoformat()}
    row = db.get(KeyValue, KEY)
    if row is None:
        db.add(KeyValue(key=KEY, value=json.dumps(data)))
    else:
        row.value = json.dumps(data)
    db.flush()
    return data


def kind(task: Task) -> str:
    return streaks.kind_of(task) or task.category or "general"


def _finished(db: Session, now: datetime) -> list[Task]:
    return db.scalars(select(Task).where(Task.planned_start >= now - WINDOW, Task.planned_end < now,
                                         Task.notify != "none", Task.category != "sleep")).all()


def durations(db: Session, now: datetime) -> dict:
    """Per kind of block: actual minutes / planned minutes, from blocks you started and finished."""
    acc: dict = defaultdict(list)
    for t in db.scalars(select(Task).where(Task.actual_start.is_not(None), Task.actual_end.is_not(None),
                                           Task.planned_start >= now - timedelta(days=60))).all():
        planned = (from_db(t.planned_end) - from_db(t.planned_start)).total_seconds()
        actual = (from_db(t.actual_end) - from_db(t.actual_start)).total_seconds()
        if planned > 0 and 0.2 < actual / planned < 4:
            acc[kind(t)].append(actual / planned)
    return {k: {"n": len(v), "ratio": round(sum(v) / len(v), 2)} for k, v in acc.items()}


def energy(tasks: list[Task]) -> dict:
    """Done-rate by 2-hour band of the day (smoothed) → peak and slump."""
    bands: dict = defaultdict(lambda: [0, 0])
    for t in tasks:
        b = local(t.planned_start).hour // 2 * 2
        bands[b][0] += t.status == TaskStatus.DONE
        bands[b][1] += 1
    rated = {b: (d + 1) / (n + 2) for b, (d, n) in bands.items() if n >= 3}
    if len(rated) < 2:
        return {}
    peak, slump = max(rated, key=rated.get), min(rated, key=rated.get)
    return {"peak": f"{peak:02d}:00–{peak + 2:02d}:00", "peak_rate": round(rated[peak] * 100),
            "slump": f"{slump:02d}:00–{slump + 2:02d}:00", "slump_rate": round(rated[slump] * 100),
            "bands": {f"{b:02d}": round(r * 100) for b, r in sorted(rated.items())}}


def procrastination(tasks: list[Task]) -> list[dict]:
    """Blocks you skip (or never answer) most, and on which day."""
    by: dict = defaultdict(lambda: [0, 0])
    for t in tasks:
        missed = t.status == TaskStatus.SKIPPED or t.status == TaskStatus.PLANNED
        for key in ((t.title, None), (t.title, DAYS[local(t.planned_start).weekday()])):
            by[key][0] += missed
            by[key][1] += 1
    out = [{"block": title, "day": day, "missed": m, "of": n, "rate": round(100 * m / n)}
           for (title, day), (m, n) in by.items() if n >= 3 and m / n >= 0.5]
    return sorted(out, key=lambda x: (-x["rate"], -x["of"]))[:5]


def _rate(days: list[dict]) -> float | None:
    p = sum(d["planned"] for d in days)
    return round(100 * sum(d["done"] for d in days) / p) if p else None


def patterns(db: Session, tasks: list[Task]) -> list[dict]:
    """Day-level links: gym days, first-ring mornings, low-mood days → that day's done-rate."""
    days: dict = defaultdict(lambda: {"planned": 0, "done": 0, "gym": False, "low": False, "first_ring": None})
    for t in tasks:
        d = days[local(t.planned_start).date()]
        d["planned"] += 1
        d["done"] += t.status == TaskStatus.DONE
        if kind(t) == "gym" and t.status == TaskStatus.DONE:
            d["gym"] = True
    for m in db.scalars(select(MoodEntry).where(MoodEntry.at >= datetime.now(timezone.utc) - WINDOW)).all():
        if m.mood in LOW:
            days[local(m.at).date()]["low"] = True
    for w in db.scalars(select(WakeSession)).all():
        dd = datetime.fromisoformat(w.day).date()
        if dd in days and w.solved_at:
            days[dd]["first_ring"] = w.rings <= 1
    out = []
    for name, test, yes, no in (("gym", lambda d: d["gym"], "on gym days", "on days without the gym"),
                                ("wake", lambda d: d["first_ring"] is True, "after first-ring mornings", "after slow mornings"),
                                ("mood", lambda d: d["low"], "on low-mood days", "on other days")):
        a = [d for d in days.values() if test(d)]
        b = [d for d in days.values() if not test(d) and (name != "wake" or d["first_ring"] is False)]
        if len(a) >= 3 and len(b) >= 3:
            ra, rb = _rate(a), _rate(b)
            if ra is not None and rb is not None and abs(ra - rb) >= 10:
                out.append({"link": name, "text": f"You finish {ra}% of blocks {yes} vs {rb}% {no}.", "diff": ra - rb,
                            "days": len(a) + len(b)})
    return sorted(out, key=lambda x: -abs(x["diff"]))


def refresh(db: Session, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    tasks = _finished(db, now)
    return save(db, durations=durations(db, now), energy=energy(tasks), procrastination=procrastination(tasks),
                patterns=patterns(db, tasks), blocks=len(tasks))
