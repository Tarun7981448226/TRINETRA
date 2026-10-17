"""The 6am wake-up protocol.

An iOS Shortcut (run by a time-of-day automation at 06:00, re-run at 06:10 and 06:20) drives it:
    /wake/start  → registers a ring
    /wake/speech → TRINETRA's voice: motivation + the current question (or today's briefing once done)
    /wake/question → the question as text (for the typing prompt)
    /wake/answer?a=51 → checks it; three correct answers = you're awake
Each morning is stored (rings, minutes to wake, wrong answers) so TRINETRA learns how you wake up.
"""
import random
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import llm
from app.core.persona import humanize, system_prompt
from app.core.timeutil import day_bounds_utc, from_db, local, now_local
from app.db.models import KeyValue, Task, TaskStatus, WakeSession

QUESTIONS_NEEDED = 3


def medium_question(rng: random.Random) -> dict:
    kind = rng.choice(["mul", "sub", "add"])
    if kind == "mul":
        a, b = rng.randint(12, 19), rng.randint(3, 9)
        return {"q": f"{a} times {b}", "text": f"{a} × {b}", "a": a * b}
    if kind == "sub":
        a, b = rng.randint(52, 99), rng.randint(13, 49)
        return {"q": f"{a} minus {b}", "text": f"{a} − {b}", "a": a - b}
    a, b = rng.randint(38, 89), rng.randint(27, 79)
    return {"q": f"{a} plus {b}", "text": f"{a} + {b}", "a": a + b}


def today_session(db: Session, create: bool = True) -> WakeSession | None:
    day = now_local().date().isoformat()
    s = db.scalar(select(WakeSession).where(WakeSession.day == day))
    if s is None and create:
        rng = random.Random()
        s = WakeSession(day=day, questions=[medium_question(rng) for _ in range(QUESTIONS_NEEDED)])
        db.add(s)
        db.flush()
    return s


def wake_time(db: Session) -> str:
    row = db.get(KeyValue, "sleep_window")
    return row.value.split("-")[1] if row and row.value and "-" in row.value else "06:00"


def ring(db: Session) -> WakeSession:
    s = today_session(db)
    if s.last != "done":
        s.rings += 1
        s.first_ring_at = s.first_ring_at or datetime.now(timezone.utc)
        s.last = "start" if s.index == 0 and s.wrong == 0 else s.last
    return s


def answer(db: Session, value: str) -> str:
    s = today_session(db)
    if s.last == "done":
        return "done"
    try:
        given = int(str(value).strip().replace(",", "").split(".")[0])
    except ValueError:
        given = None
    s.attempts += 1
    if given == s.questions[s.index]["a"]:
        s.index += 1
        if s.index >= len(s.questions):
            s.last = "done"
            s.solved_at = datetime.now(timezone.utc)
            return "done"
        s.last = "correct"
        return "correct"
    s.wrong += 1
    s.last = "wrong"
    return "wrong"


def minutes_to_wake(s: WakeSession) -> float | None:
    if not (s.solved_at and s.first_ring_at):
        return None
    return round((from_db(s.solved_at) - from_db(s.first_ring_at)).total_seconds() / 60, 1)


def mood_for(s: WakeSession) -> str:
    if s.last == "done":
        return "proud and energised"
    if s.rings >= 3 or s.wrong >= 3:
        return "ANGRY — fired up, it's past wake-up time and he's still in bed"
    if s.rings == 2 or s.last == "wrong":
        return "firm and angry — raised voice, get him out of bed"
    return "warm but energetic — a mentor waking his student up with purpose"


def _today_first_blocks(db: Session) -> list[str]:
    start, end = day_bounds_utc()
    rows = db.scalars(select(Task).where(Task.planned_start >= start, Task.planned_start < end,
                                         Task.notify != "none", Task.status == TaskStatus.PLANNED)
                      .order_by(Task.planned_start).limit(4)).all()
    return [f"{local(t.planned_start):%H:%M} {t.title}" for t in rows]


async def speech_text(db: Session, settings) -> tuple[str, str]:
    """What TRINETRA says right now, and the mood to say it in."""
    s = today_session(db)
    mood = mood_for(s)
    q = s.questions[min(s.index, len(s.questions) - 1)]["q"] if s.questions else ""
    if s.last == "done":
        mins = minutes_to_wake(s)
        instruction = (f"I just proved I'm awake ({mins} minutes after you started, {s.rings} ring(s), {s.wrong} "
                       f"wrong answers). Give me a 3-4 sentence morning briefing: today's first blocks "
                       f"{_today_first_blocks(db)}, one line of motivation tied to my goals. Spoken, energetic.")
        fallback = "You're up. Good. Breakfast, then TUF at 8:30. Let's make today count."
    elif s.last == "wrong":
        return (f"Wrong. Wake up properly, Tarun. Try again: what is {q}?", mood)
    elif s.last == "correct":
        return (f"Correct. Next one: what is {q}?", mood)
    else:
        instruction = (f"It's {now_local():%H:%M}. Wake me up — this is ring number {s.rings}. In 2-3 punchy spoken "
                       "sentences: tell me to get up, remind me what's at stake (my AI/ML internship and DSA goals, "
                       f"today's plan: {_today_first_blocks(db)}). "
                       + ("I've ignored you already — be angry." if s.rings >= 2 else "Be motivating.")
                       + " Do NOT ask the math question; I'll add it.")
        fallback = "Tarun, wake up. It's time for your day. We have a lot to get done."
    text = fallback
    if settings.llm_available:
        try:
            text = humanize(strip_name=False, text=await llm.complete(
                [{"role": "system", "content": system_prompt(mood)}, {"role": "user", "content": instruction}],
                tier="fast", max_tokens=400)) or fallback
        except llm.LLMUnavailable:
            pass
    if s.last != "done":
        text += " Prove you're awake: open TRINETRA and answer my questions. Now."
    return text, mood
