"""TRINETRA's heartbeat: every TICK_SECONDS it looks at the clock and turns time into events.

  block starting soon      → task.due      (Reminder Dispatcher)
  block just ended         → task.ending   (Check-in Agent)
  once an hour             → routines topped up to the horizon
  free gap between blocks  → free.checkin  (Free-Time Watcher, every 30 min)
  portfolio visitors       → forgotten when idle; 21:30 digest of what they left
"""
import asyncio
import json
import logging
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core import guest, mentor, timetable
from app.core.orchestrator import IncomingEvent, Orchestrator
from app.core.timeutil import from_db, now_local
from app.db.models import KeyValue, Message, Task, TaskStatus

log = logging.getLogger("trinetra.scheduler")

TICK_SECONDS = 30
STALE_REMINDER = timedelta(minutes=30)  # don't remind about blocks that started long ago (e.g. server was off)
STALE_CHECKIN = timedelta(hours=6)
NAG_EVERY, NAG_MAX = timedelta(minutes=5), 3  # Tarun chose: every 5 minutes, up to 3 times
# Ignored all of those on an important block (priority 4–5)? Red alerts: 5 min after the last follow-up, then 15 min later.
RED_PRIORITY, RED_AFTER = 4, [timedelta(minutes=5), timedelta(minutes=20)]


async def tick(db: Session, core: Orchestrator, now: datetime | None = None) -> list[str]:
    """One heartbeat. Returns the events fired (handy for tests)."""
    now = now or datetime.now(timezone.utc)
    lead = timedelta(minutes=core.settings.trinetra_reminder_lead_min)
    fired: list[str] = []

    due = db.scalars(
        select(Task).where(
            Task.status == TaskStatus.PLANNED,
            Task.reminded_at.is_(None),
            Task.notify != "none",  # meals, commutes: no pings
            Task.planned_start <= now + lead,
            Task.planned_start > now - STALE_REMINDER,
        )
    ).all()
    for task in due:
        task.reminded_at = now
        await core.dispatch(IncomingEvent("task.due", {"task_id": task.id, "title": task.title}, "scheduler"), db)
        fired.append(f"task.due:{task.id}")

    # Follow-ups: a block you haven't started gets up to NAG_MAX more pings, NAG_EVERY apart.
    nag = db.scalars(
        select(Task).where(
            Task.status == TaskStatus.PLANNED,
            Task.reminded_at.is_not(None),
            Task.notify == "full",
            Task.nag_count < NAG_MAX,
            Task.planned_end > now,
        )
    ).all()
    for task in nag:
        if now < from_db(task.reminded_at) + NAG_EVERY * (task.nag_count + 1):
            continue
        task.nag_count += 1
        await core.dispatch(IncomingEvent("task.nag", {"task_id": task.id, "title": task.title,
                                                       "count": task.nag_count}, "scheduler"), db)
        fired.append(f"task.nag:{task.id}:{task.nag_count}")

    red = db.scalars(
        select(Task).where(
            Task.status == TaskStatus.PLANNED,
            Task.reminded_at.is_not(None),
            Task.notify == "full",
            Task.priority >= RED_PRIORITY,
            Task.nag_count >= NAG_MAX,
            Task.nag_count < NAG_MAX + len(RED_AFTER),
            Task.planned_end > now,
        )
    ).all()
    for task in red:
        k = task.nag_count - NAG_MAX  # red alerts already sent
        if now < from_db(task.reminded_at) + NAG_EVERY * NAG_MAX + RED_AFTER[k]:
            continue
        task.nag_count += 1
        await core.dispatch(IncomingEvent("task.escalate", {"task_id": task.id, "title": task.title,
                                                            "count": k + 1}, "scheduler"), db)
        fired.append(f"task.escalate:{task.id}:{k + 1}")

    ended = db.scalars(
        select(Task).where(
            Task.status.in_([TaskStatus.PLANNED, TaskStatus.STARTED]),
            Task.checkin_at.is_(None),
            Task.notify == "full",  # only real work gets a "how did it go?"
            Task.planned_end <= now,
            Task.planned_end > now - STALE_CHECKIN,
        )
    ).all()
    for task in ended:
        task.checkin_at = now
        await core.dispatch(IncomingEvent("task.ending", {"task_id": task.id, "title": task.title}, "scheduler"), db)
        fired.append(f"task.ending:{task.id}")

    for promise in mentor.due_promises(db, now):
        promise.asked_at = now
        if mentor.overdue_hours(promise, now) > 24:  # server was off for a day: don't nag about stale ones
            continue
        await core.dispatch(IncomingEvent("promise.due", {"promise_id": promise.id}, "scheduler"), db)
        fired.append(f"promise.due:{promise.id}")

    db.commit()
    return fired


REPORT_DAY, REPORT_BUILD_HOUR, REPORT_PLAY = 6, 23, time(23, 30)  # Sunday: write from 23:00, play 23:30


async def weekly(db: Session, core: Orchestrator) -> str | None:
    """Sunday night: build the weekly report one step per beat, then announce it at 23:30."""
    from app.core import push, report

    now = now_local()
    if now.weekday() != REPORT_DAY or now.hour < REPORT_BUILD_HOUR:
        return None
    monday, *_ = report.week_bounds(now.date())
    done_key = f"weekly_cron:{monday.isoformat()}"
    if db.get(KeyValue, done_key) is None:  # once a week: overload verdicts + goal progress
        db.add(KeyValue(key=done_key, value="1"))
        await core.dispatch(IncomingEvent("cron.weekly", {"week_of": monday.isoformat()}, "scheduler"), db)
    step = await report.advance(db, core.settings, monday)
    announced = f"report_announced:{monday.isoformat()}"
    if step == "ready" and now.time() >= REPORT_PLAY and db.get(KeyValue, announced) is None:
        db.add(KeyValue(key=announced, value="1"))
        text = "Your weekly report is ready. 30 minutes, six chapters. Let's go through your week."
        db.add(Message(role="trinetra", content=text, channel="reminder", mood="calm and caring",
                       meta={"kind": "weekly_report", "week": monday.isoformat()}))
        push.send(db, "TRINETRA — weekly report", text, url="/#report")
        return "announced"
    return step


WAKE_PUSHES = [
    "Tarun. It's {t}. Get up — tap here and answer my three questions.",
    "Still in bed? It's {t}. Your day already started. Up. Now.",
    "TARUN! {t}! Every minute in bed is a minute your goals wait. GET UP!",
    "I'm not stopping. It's {t}. Feet on the floor. Answer the questions.",
    "{t}. This is going in your weekly report. Get up and prove me wrong.",
    "Last call, {t}. You promised yourself more than this. Up!",
]


async def wake_watch(db: Session, now: datetime) -> bool:
    """After wake-up time, if the questions aren't solved, nag the lock screen every 5 minutes."""
    from app.core import push, wake

    if db.get(KeyValue, "wake_enabled") is None:  # only once the Shortcut is set up
        return False
    local_now = now_local()
    h, m = map(int, wake.wake_time(db).split(":"))
    wake_at = local_now.replace(hour=h, minute=m, second=0, microsecond=0)
    if not (wake_at + timedelta(minutes=5) <= local_now <= wake_at + timedelta(minutes=45)):
        return False
    s = wake.today_session(db)
    if s.last == "done" or s.pushes >= len(WAKE_PUSHES):
        return False
    if s.last_push_at and now - from_db(s.last_push_at) < timedelta(minutes=5):
        return False
    s.pushes += 1
    s.last_push_at = now
    push.send(db, "TRINETRA ⏰", WAKE_PUSHES[s.pushes - 1].format(t=f"{local_now:%H:%M}"), url="/#wake", tag="wake")
    return True


FREE_EVERY = timedelta(minutes=30)  # Tarun chose: in free time, "what are you doing?" every 30 minutes
FREE_MIN_GAP = timedelta(minutes=30)  # only gaps at least this long count as free time
FREE_SETTLE = timedelta(minutes=10)  # leave room for the block's "how did it go?" before asking
FREE_QUIET_FROM = time(23, 30)  # winding down for bed: no check-ins


async def free_watch(db: Session, core: Orchestrator, now: datetime) -> bool:
    """In a free gap between blocks, ask what he's doing — every FREE_EVERY, never while asleep."""
    from app.core import wake
    from app.core.timeutil import user_tz

    local_now = now.astimezone(user_tz())
    h, m = map(int, wake.wake_time(db).split(":"))
    if local_now.time() < time(h, m) or local_now.time() >= FREE_QUIET_FROM:
        return False
    active = (TaskStatus.PLANNED, TaskStatus.STARTED)
    if db.scalar(select(Task.id).where(Task.status.in_(active), Task.planned_start <= now,
                                       Task.planned_end > now).limit(1)) is not None:
        return False  # a block is on: the reminders handle it
    day_start = local_now.replace(hour=h, minute=m, second=0, microsecond=0).astimezone(timezone.utc)
    prev_end = db.scalar(select(func.max(Task.planned_end)).where(
        Task.status != TaskStatus.SKIPPED, Task.planned_end <= now, Task.planned_end > day_start))
    free_since = max(from_db(prev_end), day_start) if prev_end else day_start
    nxt = db.scalars(select(Task).where(Task.status.in_(active), Task.planned_start > now)
                     .order_by(Task.planned_start).limit(1)).first()
    quiet = datetime.combine(local_now.date(), FREE_QUIET_FROM, user_tz())
    free_until = min(from_db(nxt.planned_start), quiet) if nxt else quiet
    if free_until - free_since < FREE_MIN_GAP or now - free_since < FREE_SETTLE or free_until - now < FREE_SETTLE:
        return False
    from app.agents.monitoring import focus_on

    if focus_on(db, now):  # Focus mode is on: he's working on something, leave him be
        return False
    row = db.get(KeyValue, "free_checkin_last")
    if row and now - datetime.fromisoformat(row.value) < FREE_EVERY:
        return False
    if row is None:
        db.add(KeyValue(key="free_checkin_last", value=now.isoformat()))
    else:
        row.value = now.isoformat()
    left = round((free_until - now).total_seconds() / 60)
    next_title = nxt.title if nxt and free_until == from_db(nxt.planned_start) else None
    await core.dispatch(IncomingEvent("free.checkin", {"minutes_left": left, "next_title": next_title}, "scheduler"),
                        db)
    return True


SILENCE_AFTER = timedelta(minutes=60)  # in a block you started, an hour with no word from you…
SILENCE_TAIL = timedelta(minutes=15)   # …unless it's about to end anyway (the "how did it go?" comes then)
SILENCE_MAX = 2                        # at most twice per block


async def silence_watch(db: Session, core: Orchestrator, now: datetime) -> bool:
    """You started a block and then went quiet for an hour: a light "still on it?"."""
    task = db.scalars(select(Task).where(
        Task.status == TaskStatus.STARTED, Task.notify == "full", Task.category != "sleep",
        Task.planned_start <= now, Task.planned_end > now + SILENCE_TAIL).order_by(Task.planned_start)).first()
    if task is None:
        return False
    key = f"silence:{task.id}"
    row = db.get(KeyValue, key)
    seen = json.loads(row.value) if row and row.value else {"n": 0, "at": None}
    if seen["n"] >= SILENCE_MAX:
        return False
    last_word = db.scalar(select(func.max(Message.created_at)).where(Message.role == "user"))
    phone = db.get(KeyValue, "last_signal")  # Focus mode / places from the iPhone count as signs of life
    if phone and phone.value:
        last_word = max(filter(None, [from_db(last_word) if last_word else None, datetime.fromisoformat(phone.value)]))
    signs = [from_db(t) for t in (task.actual_start, last_word) if t] + \
            ([datetime.fromisoformat(seen["at"])] if seen["at"] else []) + [from_db(task.planned_start)]
    quiet = now - max(signs)
    if quiet < SILENCE_AFTER:
        return False
    seen = {"n": seen["n"] + 1, "at": now.isoformat()}
    if row is None:
        db.add(KeyValue(key=key, value=json.dumps(seen)))
    else:
        row.value = json.dumps(seen)
    await core.dispatch(IncomingEvent("silence.check", {"task_id": task.id, "title": task.title,
                                                        "quiet_min": round(quiet.total_seconds() / 60)}, "scheduler"), db)
    return True


PLAN_AT = time(21, 0)  # local: tomorrow's briefing (and any catch-up proposal)


async def plan_tomorrow(db: Session, core: Orchestrator) -> bool:
    """Once a day at PLAN_AT, the Daily Planner looks at tomorrow."""
    today = now_local()
    if today.time() < PLAN_AT:
        return False
    key = f"planned:{today.date().isoformat()}"
    if db.get(KeyValue, key) is not None:
        return False
    db.add(KeyValue(key=key, value="1"))
    await core.dispatch(IncomingEvent("plan.nightly", {"date": (today.date() + timedelta(days=1)).isoformat()},
                                      "scheduler"), db)
    return True


NIGHTLY_HOUR = 3  # local time: the brain retrains while you sleep


async def nightly(db: Session, core: Orchestrator) -> bool:
    """Once a day after NIGHTLY_HOUR local, fire cron.nightly (retraining, reflection)."""
    today = now_local()
    if today.hour < NIGHTLY_HOUR:
        return False
    row = db.get(KeyValue, "last_nightly")
    if row and row.value == today.date().isoformat():
        return False
    if row is None:
        db.add(KeyValue(key="last_nightly", value=today.date().isoformat()))
    else:
        row.value = today.date().isoformat()
    await core.dispatch(IncomingEvent("cron.nightly", {"date": today.date().isoformat()}, "scheduler"), db)
    return True


async def heartbeat(db: Session, core: Orchestrator, now: datetime | None = None) -> dict:
    """Everything one beat does. Called every 30s locally, or every minute by the Cloudflare cron in the cloud."""
    now = now or datetime.now(timezone.utc)
    extended = 0
    row = db.get(KeyValue, "last_extend")
    if row is None or datetime.fromisoformat(row.value) < now - timedelta(hours=1):
        extended = timetable.extend_series(db)
        if row is None:
            db.add(KeyValue(key="last_extend", value=now.isoformat()))
        else:
            row.value = now.isoformat()
        db.commit()
    fired = await tick(db, core, now)
    nightly_ran = await nightly(db, core)
    planned = await plan_tomorrow(db, core)
    weekly_ran = await weekly(db, core)
    woke = await wake_watch(db, now)
    free = await free_watch(db, core, now)
    silence = await silence_watch(db, core, now)
    forgotten = guest.sweep(db, now)
    digest = guest.digest(db, now)
    db.commit()
    return {"fired": fired, "routines_extended": extended, "nightly": nightly_ran, "planned_tomorrow": planned, "weekly": weekly_ran,
            "wake_nag": woke, "free_checkin": free, "silence_check": silence, "visitors_forgotten": forgotten, "visitor_digest": bool(digest)}


async def run_forever(session_factory: sessionmaker, core: Orchestrator) -> None:
    log.info("heartbeat started (every %ss)", TICK_SECONDS)
    while True:
        try:
            with session_factory() as db:
                await heartbeat(db, core)
        except Exception:
            log.exception("heartbeat tick failed")  # never let one bad tick stop the heart
        await asyncio.sleep(TICK_SECONDS)
