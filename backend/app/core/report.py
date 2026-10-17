"""The Sunday-night report.

From 23:00 Sunday the heartbeat builds it step by step (each step fits in one serverless call):
    step 1: measure the week (metrics) and compare with every earlier week
    steps 2-7: write one ~5-minute spoken chapter per step
At 23:30 a push + the "TRINETRA Report" Shortcut play the six chapters back to back (~30 min).
"""
import json
from collections import defaultdict
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import llm
from app.core.persona import humanize, system_prompt
from app.core.timeutil import from_db, local, to_utc
from app.db.models import Goal, Promise, Task, TaskStatus, WakeSession, WeeklyReport

CHAPTERS = [
    ("The scorecard", "Open the report. Give the headline numbers of the week (completion rate, hours by area, "
                      "wake-ups) and an honest one-paragraph verdict. Then walk through each day of the week briefly."),
    ("What you did right", "Celebrate specifically: the blocks, days, habits and wake-ups that went well, with numbers. "
                           "Explain WHY they worked so he can repeat them."),
    ("What went wrong", "Be direct and honest about skipped/ignored blocks, slow wake-ups, broken promises. Find the "
                        "patterns (which days, which times, which subjects) and the likely real reasons. No insults."),
    ("Mornings and energy", "Analyse the wake-up data day by day (rings, minutes to wake, wrong answers), weekday vs "
                            "weekend, Monday vs others, and how mornings affected the rest of the day."),
    ("Goals and the roadmap", "Progress on each goal and milestone, the DSA roadmap topics done vs due, the CSCI exam "
                              "prep, the internship pipeline. What's on track, what's behind, by how much."),
    ("Compared with before, and next week", "Compare this week with previous weeks (the deltas and trend). Then lay "
                                            "out the plan for next week: three concrete fixes, one stretch challenge, "
                                            "and a closing mentor message to send him to sleep motivated."),
]
WORDS_PER_CHAPTER = 700  # ≈ 5 minutes spoken → six chapters ≈ 30 minutes


def week_bounds(any_day: date) -> tuple[date, datetime, datetime]:
    monday = any_day - timedelta(days=any_day.weekday())
    start = to_utc(datetime.combine(monday, time.min))
    return monday, start, start + timedelta(days=7)


def compute_metrics(db: Session, monday: date) -> dict:
    _, start, end = week_bounds(monday)
    tasks = db.scalars(select(Task).where(Task.planned_start >= start, Task.planned_start < end,
                                          Task.notify != "none", Task.category != "sleep")).all()
    by_cat: dict = defaultdict(lambda: {"planned": 0, "done": 0, "skipped": 0, "missed": 0, "hours_done": 0.0})
    by_day: dict = defaultdict(lambda: {"planned": 0, "done": 0})
    now = datetime.now(start.tzinfo)
    for t in tasks:
        c, d = by_cat[t.category], by_day[local(t.planned_start).strftime("%a")]
        c["planned"] += 1
        d["planned"] += 1
        hours = (from_db(t.planned_end) - from_db(t.planned_start)).total_seconds() / 3600
        if t.status == TaskStatus.DONE:
            c["done"] += 1
            d["done"] += 1
            c["hours_done"] = round(c["hours_done"] + hours, 2)
        elif t.status == TaskStatus.SKIPPED:
            c["skipped"] += 1
        elif from_db(t.planned_end) < now:
            c["missed"] += 1  # never answered — counted against you
    planned = sum(c["planned"] for c in by_cat.values())
    done = sum(c["done"] for c in by_cat.values())

    wakes = []
    for i in range(7):
        day = (monday + timedelta(days=i)).isoformat()
        s = db.scalar(select(WakeSession).where(WakeSession.day == day))
        wakes.append({
            "day": (monday + timedelta(days=i)).strftime("%a"),
            "rings": s.rings if s else 0, "wrong": s.wrong if s else 0, "solved": bool(s and s.solved_at),
            "solved_at": f"{local(s.solved_at):%H:%M}" if s and s.solved_at else None,
            "minutes_to_wake": (round((from_db(s.solved_at) - from_db(s.first_ring_at)).total_seconds() / 60, 1)
                                if s and s.solved_at and s.first_ring_at else None),
        })
    solved = [w for w in wakes if w["minutes_to_wake"] is not None]
    promises = db.scalars(select(Promise).where(Promise.due_at >= start, Promise.due_at < end)).all()
    goals = []
    for g in db.scalars(select(Goal).where(Goal.status != "dropped")):
        due_now = [m for m in g.milestones if m.due_date and from_db(m.due_date) < end]
        goals.append({"title": g.title, "progress": round(g.progress, 2),
                      "milestones_done": sum(m.done_at is not None for m in g.milestones),
                      "milestones_total": len(g.milestones),
                      "due_by_now": len(due_now), "done_of_due": sum(m.done_at is not None for m in due_now),
                      "done_this_week": [m.title for m in g.milestones
                                         if m.done_at and start <= from_db(m.done_at) < end]})
    metrics = {
        "week_start": monday.isoformat(),
        "blocks": {"planned": planned, "done": done, "rate": round(done / planned, 2) if planned else None},
        "hours_done": round(sum(c["hours_done"] for c in by_cat.values()), 1),
        "by_category": dict(by_cat), "by_day": dict(by_day),
        "wake": {"days": wakes, "solved_days": len(solved),
                 "avg_minutes_to_wake": round(sum(w["minutes_to_wake"] for w in solved) / len(solved), 1)
                 if solved else None,
                 "first_ring_days": sum(1 for w in wakes if w["solved"] and w["rings"] == 1)},
        "promises": {"kept": sum(p.status == "kept" for p in promises),
                     "broken": sum(p.status == "broken" for p in promises),
                     "list": [{"text": p.text, "status": p.status} for p in promises]},
        "goals": goals,
    }
    metrics["compare"] = compare(db, monday, metrics)
    return metrics


def compare(db: Session, monday: date, metrics: dict) -> dict:
    """Deltas against last week and the average of all earlier weeks."""
    earlier = db.scalars(select(WeeklyReport).where(WeeklyReport.week_start < monday.isoformat())
                         .order_by(WeeklyReport.week_start.desc())).all()
    if not earlier:
        return {"weeks_before": 0}

    def pick(m):
        return {"rate": (m.get("blocks") or {}).get("rate"), "hours_done": m.get("hours_done"),
                "avg_minutes_to_wake": (m.get("wake") or {}).get("avg_minutes_to_wake")}

    now, last = pick(metrics), pick(earlier[0].metrics)
    hist = [pick(r.metrics) for r in earlier]
    avg = {k: (round(sum(h[k] for h in hist if h[k] is not None) / n, 2) if (n := sum(h[k] is not None for h in hist))
               else None) for k in now}
    delta = {k: (round(now[k] - last[k], 2) if now[k] is not None and last[k] is not None else None) for k in now}
    return {"weeks_before": len(earlier), "last_week": last, "average_before": avg, "change_vs_last_week": delta}


async def write_chapter(db: Session, report: WeeklyReport, n: int, settings) -> str:
    title, brief = CHAPTERS[n]
    fallback = f"{title}. This week you completed {report.metrics['blocks']['done']} of " \
               f"{report.metrics['blocks']['planned']} blocks."
    if not settings.llm_available:
        return fallback
    try:
        text = await llm.complete([
            {"role": "system", "content": system_prompt("honest, warm, deeply invested mentor — proud where earned, "
                                                        "firm where needed")},
            {"role": "user", "content": (
                f"This is chapter {n + 1} of 6 of my spoken weekly report: '{title}'. {brief}\n"
                f"Write about {WORDS_PER_CHAPTER} words, to be read aloud. Plain spoken text, no lists or headings. "
                f"Use only these facts (JSON):\n{json.dumps(report.metrics)}"
                + ("\nStart with a one-line welcome to the weekly report." if n == 0 else "")
            )},
        ], tier="smart", temperature=0.7, max_tokens=1800)
        return humanize(text) or fallback
    except llm.LLMUnavailable:
        return fallback


async def advance(db: Session, settings, monday: date) -> str:
    """Do the next step of building this week's report. Returns what happened."""
    report = db.scalar(select(WeeklyReport).where(WeeklyReport.week_start == monday.isoformat()))
    if report is None:
        report = WeeklyReport(week_start=monday.isoformat(), metrics=compute_metrics(db, monday), sections=[])
        db.add(report)
        db.flush()
        return "measured"
    if report.status == "ready":
        return "ready"
    n = len(report.sections)
    text = await write_chapter(db, report, n, settings)
    report.sections = [*report.sections, {"title": CHAPTERS[n][0], "text": text}]
    if len(report.sections) == len(CHAPTERS):
        report.status = "ready"
    return f"chapter {n + 1}"
