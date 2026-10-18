"""Time & Planning + Reminders: building your timetable from plain words, and nudging you on time."""
import json
import logging
import re
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select

from app.core import courses, deliberation, llm, timetable
from app.core import mood as mood_modes
from app.core.orchestrator import AgentContext, AgentResult, IncomingEvent
from app.core.persona import humanize, system_prompt
from app.core.registry import agent
from app.core.timeutil import from_db, local, now_local, to_utc
from app.db.models import Message, Task, TaskStatus

log = logging.getLogger("trinetra.planning")

# Only spend an LLM call when the message smells like scheduling.
SCHEDULING_HINT = re.compile(
    r"\b(\d{1,2}(:\d{2})?\s*(am|pm)|\d{1,2}:\d{2}|at \d{1,2}|every\s+\w+|daily|weekdays?|weekends?|tomorrow|tonight|"
    r"today|morning|evening|afternoon|night|remind|schedule|timetable|plan|block|cancel|delete|remove|move|"
    r"reschedule|postpone|shift|monday|tuesday|wednesday|thursday|friday|saturday|sunday|mark .* (done|complete))\b",
    re.I,
)

BUILDER_PROMPT = """You manage a personal timetable. Convert the user's message into timetable operations.
Now: {now} ({weekday}). Timezone is the user's local time; use 24h HH:MM and YYYY-MM-DD.

Current blocks (next 7 days):
{blocks}

Operations (JSON only):
{{"ops": [
  {{"op": "create", "title": str, "date": "YYYY-MM-DD", "start": "HH:MM", "end": "HH:MM" or null,
    "duration_min": int or null, "recurrence": null | "daily" | "weekdays" | "weekends" | "mon,wed,fri",
    "until": "YYYY-MM-DD" or null (last day a routine runs, e.g. "until the exam on Nov 6"),
    "notify": "full" (study/work: reminder + check-in) | "remind" (reminder only) | "none" (meals, commute),
    "category": "study|work|health|fitness|personal|social|chores|rest|general", "priority": 1-5}},
  {{"op": "move", "id": int, "date": "YYYY-MM-DD", "start": "HH:MM", "end": "HH:MM" or null}},
  {{"op": "delete", "id": int, "whole_series": bool}},
  {{"op": "status", "id": int, "status": "done" | "skipped" | "started"}},
  {{"op": "set_sleep", "start": "HH:MM", "end": "HH:MM"}}
]}}
Rules:
- Only act on what the user clearly asked. Questions, feelings or chat → {{"ops": []}}.
- "every weekday at 6 gym" → one create with recurrence "weekdays", date = next occurrence (today if still ahead).
- A time without a date means the next time that clock time occurs (today if still ahead, else tomorrow).
- Default duration 60 minutes when no end/duration is given.
- Use ids from the list above for move/delete/status. Never invent ids.
- If they describe their whole week/routine ("here's my schedule…"), output one create per recurring activity
  (classes, work, gym, study, meals, commute…) with the right recurrence, plus set_sleep if they mention sleep.
  If it replaces an existing routine, delete that routine (whole_series: true).
- "I sleep at 12 and wake at 7" → set_sleep 00:00–07:00."""


@agent("timetable_builder")
async def timetable_builder(ctx: AgentContext) -> None:
    """Planner: drafts the change, then convenes the review board before touching anything."""
    text = str(ctx.event.payload.get("text", ""))
    if ctx.event.payload.get("button") or not SCHEDULING_HINT.search(text) or not ctx.settings.llm_available:
        return
    now = now_local()
    blocks = "\n".join(timetable.describe(t) for t in timetable.upcoming(ctx.db)) or "(empty)"
    s_start, s_end = deliberation.sleep_window(ctx.db)
    long_request = len(text) > 250  # a whole routine: use the stronger model and leave room for many ops
    try:
        raw = await llm.complete(
            [
                {"role": "system", "content": BUILDER_PROMPT.format(
                    now=f"{now:%Y-%m-%d %H:%M}", weekday=f"{now:%A}", blocks=blocks)
                    + f"\nTheir sleep window: {s_start:%H:%M}-{s_end:%H:%M}."},
                {"role": "user", "content": text + (f"\n(in plain words: {_plain(text)})" if _plain(text).lower() != text.lower() else "")},
            ],
            tier="smart" if long_request else "fast", temperature=0,
            max_tokens=4000 if long_request else 1200, json_mode=True,
        )
        ops = json.loads(raw).get("ops", [])
    except (llm.LLMUnavailable, json.JSONDecodeError, AttributeError) as e:
        log.warning("timetable builder skipped: %s", e)
        return
    ops = [o for o in (ops if isinstance(ops, list) else []) if isinstance(o, dict)]
    if not ops:
        return
    ops = _keep_his_time(text, ops)
    ops = _keep_his_day(ctx.db, text, ops)
    ops = _no_surprise_wipes(text, ops)
    ops = _whole_routine_moves(ctx.db, text, ops)

    # Marking something done/skipped needs no deliberation.
    quick = [o for o in ops if o.get("op") == "status"]
    ops = [o for o in ops if o.get("op") != "status"]
    changes = deliberation.apply(ctx.db, quick) if quick else []

    if ops:
        proposal = deliberation.build(ctx.db, ops)
        review = await ctx.core.dispatch(
            IncomingEvent("plan.proposed", {"request": text[:300], "ops_count": len(ops)}, "planner"),
            ctx.db, notes={"proposal": proposal, "request": text}, commit=False,
        )
        decision = review.notes.get("decision") or {"action": "apply", "ops": ops, "original_ops": ops}
        ctx.notes["deliberation"] = {k: decision.get(k) for k in ("action", "reasoning", "question", "findings")}
        if decision["action"] in ("apply", "apply_adjusted"):
            changes += deliberation.apply(ctx.db, decision["ops"])
        else:
            adjusted = decision["ops"] != decision["original_ops"]
            preview = deliberation.build(ctx.db, decision["ops"]).describe()
            ctx.notes["proposal"] = {
                "content": ("Here's what I'd do:\n" if adjusted else "Here's the change, waiting for your OK:\n")
                           + "\n".join(f"• {line}" for line in preview[:25]),
                "meta": {"kind": "schedule_proposal", "ops": decision["ops"], "original_ops": decision["original_ops"],
                         "buttons": ["accept", "original", "reject"] if adjusted else ["approve", "reject"]},
            }
    if changes:
        ctx.notes["timetable_changes"] = changes


# ---------- proactive messages (fired by the scheduler) ----------

CRITIQUE = {"lag", "why"}  # "you're behind" / "remember your why": the ones that can land badly
CRITIC_PROMPT = """You check a message an AI mentor is about to send, unprompted, to the person it mentors. Good: firm but
kind, about the action not the person, specific, short (1–3 sentences), no guilt-tripping, no sarcasm, no shaming, no
invented facts. Message:
\"\"\"{text}\"\"\"
Return JSON only: {{"ok": true}} if it's good, else {{"ok": false, "fixed": the same message rewritten to be good}}"""


async def _critique(text: str, kind: str) -> str:
    """Self-critique (LLM-as-judge): a different model reviews the tone; a bad line is replaced by its fixed version."""
    import json
    try:
        # the writer used the fast pool (Groq first); the judge comes from the smart pool (Gemini first): a different model,
        # so it doesn't just approve its own style (LLM-as-a-judge self-preference bias)
        raw = await llm.complete([{"role": "user", "content": CRITIC_PROMPT.format(text=text[:800])}], tier="smart",
                                 temperature=0, max_tokens=300, json_mode=True, reasoning="low")
        d = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
    except Exception:
        return text  # no verdict: the original stands
    fixed = d.get("fixed") if isinstance(d, dict) and d.get("ok") is False else None
    if isinstance(fixed, str) and 10 < len(fixed.strip()) < 600:
        log.info("critic rewrote a %s nudge", kind)
        return humanize(fixed.strip()) or text
    return text


CLOCK = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)|\b(\d{1,2}):(\d{2})\b", re.I)


def said_times(text: str, sure: bool = False) -> list[str]:
    """Exact clock times he typed, as HH:MM (24 h): "12:30 am" → "00:30", "7pm" → "19:00", "18:45" → "18:45".
    `sure`: only unambiguous ones — a bare "9:30" could be morning or night, so it's left out."""
    out = []
    for m in CLOCK.finditer(text):
        if m.group(3):
            h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3).lower()[0]
            if not (1 <= h <= 12) or mi > 59:
                continue
            h = (0 if h == 12 else h) + (12 if ap == "p" else 0)
        else:
            h, mi = int(m.group(4)), int(m.group(5))
            if h > 23 or mi > 59 or (sure and 1 <= h <= 12 and not m.group(4).startswith("0")):
                continue
        out.append(f"{h:02d}:{mi:02d}")
    return out


RANGE = re.compile(r"\b(from|to|till|until|til|between|and)\s+\d|\b(instead of|busy|after|before|except|not|wake)\b|"
                   r"\d\s*[-–]\s*\d", re.I)
END_WORDS = re.compile(r"\b(end(s|ing)?|done|finish(ed|es|ing)?|wrap(s|ping)? up|over|for \d+ (hours?|hrs?|min))\b", re.I)
SLEEP_WORDS = re.compile(r"\b(bed|sleep|lights out|bedtime)\b", re.I)


def _hm_add(hm: str, minutes: int) -> str:
    h, m = divmod((int(hm[:2]) * 60 + int(hm[3:5]) + minutes) % 1440, 60)
    return f"{h:02d}:{m:02d}"


def _mins(hm: str) -> int:
    return int(hm[:2]) * 60 + int(hm[3:5])


def _keep_his_time(text: str, ops: list[dict]) -> list[dict]:
    """The model once read "12:30 am" as 23:30. Only when there's no doubt — he typed exactly one time, unambiguously,
    with no range or "from / to / busy at" around it, the single timed change uses neither that time as start nor end,
    and (for sleep) he talked about bed or sleep — the start becomes his time and the end moves with it (same length)."""
    said, sure = said_times(text), said_times(text, sure=True)
    timed = [o for o in ops if o.get("op") in ("create", "move", "set_sleep") and o.get("start")]
    if len(set(said)) != 1 or len(set(sure)) != 1 or len(timed) != 1 or RANGE.search(text):
        return ops
    (want,) = set(sure)
    o = timed[0]
    if o["op"] != "set_sleep" and re.search(r"\bby\s+\d", text, re.I):  # "finish it by 7pm" names the END
        return ops
    start, end = str(o["start"])[:5], (str(o.get("end"))[:5] if o.get("end") else None)
    if not re.fullmatch(r"\d{2}:\d{2}", start) or want == start:
        return ops
    if want == end and (END_WORDS.search(text) or not re.search(r"\bat\s+\d", text, re.I)):
        return ops  # "ending at 9pm" / "done at 11pm": his time is the end, and the model has it right
    if o["op"] == "set_sleep" and not SLEEP_WORDS.search(text):
        return ops
    log.warning("builder said %s for %r; he said %s — keeping his", start, text[:80], want)
    if end and re.fullmatch(r"\d{2}:\d{2}", end) and o["op"] != "set_sleep":
        o["end"] = _hm_add(end, _mins(want) - _mins(start))  # same length
    o["start"] = want
    return ops


def _plain(text: str) -> str:
    """Texting style → plain words for the planner ("cn u push my dsa to 10pm tmrw" → "... tomorrow")."""
    from app.core import show
    return " ".join(show.normalise(text)) or text


def said_day(text: str):
    """today / tonight / tomorrow, if he named one (and only one)."""
    from datetime import timedelta
    words = set(_plain(text).lower().split())
    sure = said_times(text, sure=True)
    small_hours = bool(sure) and all(t < "05:00" for t in sure) and now_local().hour >= 5  # "reading at 2am tonight"
    tonight = now_local().date() + timedelta(days=1 if small_hours else 0)  # "12:30 am tonight" is after midnight
    days = ({now_local().date()} if "today" in words else set()) | ({tonight} if "tonight" in words else set()) | \
           ({now_local().date() + timedelta(days=1)} if "tomorrow" in words else set())
    return next(iter(days)) if len(days) == 1 else None


# "the whole routine" has to be said about the routine, not in passing ("I'm always tired", "exams every day")
WHOLE = re.compile(r"\b(from now on|for good|permanently|every (single )?(day|week|time|session)|all (of )?my (\w+ ){0,2}"
                   r"(sessions|blocks|classes|workouts|runs|lessons|practices|routines?)|the whole (routine|series)|"
                   r"stop doing \w+ (altogether|completely)|no more \w+ (at all|ever))\b", re.I)
FOR_GOOD = re.compile(r"\b(from now on|for good|permanently|altogether|no more \w+ (at all|ever))\b", re.I)
WEEKDAY_OR_DATE = re.compile(r"\b(mon|tue|wed|thu|fri|sat|sun)[a-z]*\b|\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}(st|nd|rd|th)\b", re.I)


def _no_surprise_wipes(text: str, ops: list[dict]) -> list[dict]:
    """Seen live: "free up my evening tomorrow" deleted his whole Gym and DSA routines. A delete only takes the whole
    routine when he says so ("every", "all", "from now on", "quit"…); naming one day means that day's block."""
    plain = _plain(text)
    named_day = said_day(text) is not None
    if len(text) > 250 or (WHOLE.search(plain) and (not named_day or FOR_GOOD.search(plain))):
        return ops  # he said so (and not just "… tomorrow"), or a whole new schedule replacing the old one
    for o in ops:
        if o.get("op") == "delete" and o.get("whole_series"):
            log.warning("builder wanted to wipe a whole routine for %r — only this one", text[:80])
            o["whole_series"] = False
    return ops


def _whole_routine_moves(db, text: str, ops: list[dict]) -> list[dict]:
    """"Move all my gym sessions to 7am from now on": the model sometimes moves only the blocks it was shown. When he
    clearly asked for the whole routine (and named it), and two or more of its blocks at the same old time go to the same
    new time, the later blocks at that old time follow — with the same new length."""
    plain = _plain(text)
    if not WHOLE.search(plain) or said_day(text) is not None:
        return ops
    from collections import defaultdict
    groups = defaultdict(list)
    for o in ops:
        if o.get("op") != "move" or not o.get("start"):
            continue
        try:
            t = db.get(Task, int(o["id"]))
        except (TypeError, ValueError):
            continue
        if t is not None and t.series_id and re.search(rf"\b{re.escape(t.title.split()[-1])}", plain, re.I):
            groups[(t.series_id, str(o["start"])[:5], local(t.planned_start).time(), o.get("end"))].append(t)
    for (series, start, old_time, end), tasks in groups.items():
        if len(tasks) < 2:
            continue
        have = {t.id for t in tasks}
        last = max(t.planned_start for t in tasks)
        for t in db.scalars(select(Task).where(Task.series_id == series, Task.planned_start > last,
                                                Task.status == TaskStatus.PLANNED)):
            if t.id not in have and local(t.planned_start).time() == old_time:
                extra = {"op": "move", "id": t.id, "date": local(t.planned_start).date().isoformat(), "start": start}
                if end:
                    extra["end"] = end
                ops.append(extra)
    return ops


def _keep_his_day(db, text: str, ops: list[dict]) -> list[dict]:
    """He said "tomorrow" but the model picked another day's copy of the routine (seen live: Tuesday's DSA moved for
    "tmrw" on a Sunday). Point a single move at the block on the day he named, and a single create at that day."""
    day = said_day(text)
    if day is None:
        return ops
    for o in [o for o in ops if o.get("op") == "delete"]:  # "cancel gym tomorrow": tomorrow's block, whichever id it named
        _retarget(db, o, day, text)
    dated = [o for o in ops if o.get("op") in ("move", "create")]
    if len(dated) != 1:
        return ops
    o = dated[0]
    if o["op"] == "create":
        if not WEEKDAY_OR_DATE.search(text):  # "put gym on friday" — the model's date stands
            o["date"] = day.isoformat()
        return ops
    if str(o.get("date") or "") == day.isoformat():  # the named day is where it's going ("do it tomorrow instead")
        return ops
    _retarget(db, o, day, text)
    return ops


def _retarget(db, o: dict, day, text: str) -> None:
    """Point an op at the copy of the same routine on `day` (if the model picked another day's copy)."""
    try:
        task = db.get(Task, int(o.get("id")))
    except (TypeError, ValueError):
        return
    if task is None or local(task.planned_start).date() == day:
        return
    same = select(Task).where(Task.series_id == task.series_id) if task.series_id else select(Task).where(Task.title == task.title)
    twin = next((t for t in db.scalars(same) if local(t.planned_start).date() == day), None)
    if twin is not None:
        log.warning("builder picked %s for %r; he meant %s", local(task.planned_start).date(), text[:80], day)
        o["id"] = twin.id
        if o.get("op") == "move":
            o["date"] = day.isoformat()


async def _speak_up(ctx: AgentContext, instruction: str, fallback: str, mood: str, meta: dict,
                    keep_mood: bool = False, channel: str = "reminder") -> AgentResult:
    """Compose a short proactive line in TRINETRA's voice; fall back to a template if the LLM is down.
    Optional nudges the scheduler raises are TRINETRA's own decision (core/autonomy.py): it may hold back."""
    from app.core import autonomy
    kind = (meta or {}).get("kind")
    verdict = None
    if kind in autonomy.OPTIONAL and (ctx.event.source == "scheduler" or autonomy.quiet_until(ctx.db)):
        verdict = autonomy.decide(ctx.db, kind, ctx.notes.get("expression_label"))
        if not verdict.send:
            autonomy.record(ctx.db, kind, verdict)
            ctx.notes["held_back"] = {"kind": kind, "reason": verdict.reason}
            return AgentResult()
    if not keep_mood and ctx.notes.get("expression_label") not in (None, "calm"):
        mood = ctx.notes["expression"]  # after a string of skips, reminders get an edge
    mood = mood_modes.apply(ctx.db, mood, ctx.notes.get("expression_label"))  # a mode you asked for wins (unless he's low)
    text = fallback
    if ctx.settings.llm_available:
        try:
            text = await llm.complete(
                [{"role": "system", "content": system_prompt(mood)}, {"role": "user", "content": instruction}],
                tier="fast", temperature=0.8, max_tokens=300,
                sensitive=kind in ("journal_ack", "wellbeing") or ctx.notes.get("expression_label") in ("comforting", "gentle"),
            )
            text = humanize(text) or fallback
            if kind in CRITIQUE:  # a judgmental nudge gets a second opinion before it reaches his phone
                text = await _critique(text, kind)
        except llm.LLMUnavailable:
            pass
    msg = Message(role="trinetra", content=text, channel=channel, mood=mood, meta=meta)
    ctx.db.add(msg)
    if verdict is not None:
        ctx.db.flush()
        autonomy.record(ctx.db, kind, verdict, msg.id)
    ctx.notes["proactive"] = {"text": text, "mood": mood, "meta": meta}  # the Push Agent delivers it
    return AgentResult(reply=text, mood=mood)


@agent("reminder_dispatcher")
async def reminder_dispatcher(ctx: AgentContext) -> AgentResult | None:
    task = ctx.db.get(Task, ctx.event.payload.get("task_id"))
    if task is None or task.status != TaskStatus.PLANNED:
        return None
    if ctx.event.type == "task.nag":
        return await _nag(ctx, task, int(ctx.event.payload.get("count") or 1))
    s, e = local(task.planned_start), local(task.planned_end)
    minutes = max(0, round((s - now_local()).total_seconds() / 60))
    when = "now" if minutes <= 1 else f"in {minutes} minutes"
    if task.category == "sleep":
        return await _speak_up(
            ctx,
            instruction=("It's bedtime. Start with 'Time to sleep'. Tell me, like a caring mentor, to "
                         "put the phone down and get some rest. Keep it simple: do NOT mention the time, gym, classes, "
                         "study or tomorrow's plan. One or two short spoken sentences."),
            fallback="Time to sleep. Put the phone down and get some rest.",
            mood="warm and caring, but firm about bedtime",
            meta={"kind": "reminder", "task_id": task.id, "buttons": ["start", "snooze"],
                  "respond": f"/tasks/{task.id}/respond"},
            keep_mood=True,  # bedtime is always caring, whatever the day's emotions were
        )
    aim = ""
    if tg := courses.target(ctx.db, task):
        aim = " Today's target: " + "; ".join(i.title for i in tg[1]) + ". Name it."
    risk = ""
    if (p := ctx.notes.get("p_complete")) is not None and p < 0.5:
        risk = (f" My neural core says there's only a {round(p * 100)}% chance I'll actually do it — "
                "I tend to skip this kind of block. Be extra persuasive and make starting feel easy.")
    return await _speak_up(
        ctx,
        instruction=(
            f"Remind me that '{task.title}' starts {when} ({s:%H:%M}–{e:%H:%M}). "
            "One or two short spoken sentences. Energise me to start on time." + aim + risk
        ),
        fallback=f"{task.title} starts {when}, {s:%H:%M} to {e:%H:%M}. Let's go.",
        mood="focused and sharp",
        meta={"kind": "reminder", "task_id": task.id, "buttons": ["start", "snooze", "skip"],
              "respond": f"/tasks/{task.id}/respond"},
    )


async def _nag(ctx: AgentContext, task: Task, count: int) -> AgentResult:
    """A follow-up when a reminder was ignored — firmer each time."""
    late = max(0, round((now_local() - local(task.planned_start)).total_seconds() / 60))
    tone = ["firm — a clear nudge", "firm and angry — raised voice", "ANGRY — last warning before it counts as skipped"]
    return await _speak_up(
        ctx,
        instruction=(f"Follow-up #{count} of 3: '{task.title}' started {late} minutes ago and I still haven't tapped "
                     "Start. One or two short sentences. Make me start right now."
                     + (" Tell me this is the last ping and ignoring it counts as a skip." if count >= 3 else "")),
        fallback=f"{task.title} started {late} minutes ago. Start now.",
        mood=tone[min(count, 3) - 1],
        meta={"kind": "reminder", "task_id": task.id, "buttons": ["start", "snooze", "skip"],
              "respond": f"/tasks/{task.id}/respond", "nag": count},
    )


@agent("escalation_agent")
async def escalation_agent(ctx: AgentContext) -> AgentResult | None:
    """Red alert: an important block, a reminder and three follow-ups, all ignored."""
    task = ctx.db.get(Task, ctx.event.payload.get("task_id"))
    if task is None or task.status != TaskStatus.PLANNED:
        return None
    count = int(ctx.event.payload.get("count") or 1)
    late = max(0, round((now_local() - local(task.planned_start)).total_seconds() / 60))
    left = max(0, round((local(task.planned_end) - now_local()).total_seconds() / 60))
    return await _speak_up(
        ctx,
        instruction=(f"RED ALERT #{count}: '{task.title}' is important and started {late} minutes ago. I've ignored the "
                     f"reminder and all three follow-ups. {left} minutes of it are left. Two or three short, loud "
                     "sentences: you're done being polite. Tell me to tap Start right now, or own it and tap Skip."
                     + (" This is the last alert for this block." if count >= 2 else "")),
        fallback=f"Red alert. {task.title} started {late} minutes ago and you've ignored me four times. "
                 "Tap Start now, or own it and skip it.",
        mood="ANGRY — red alert, every reminder ignored",
        meta={"kind": "red_alert", "task_id": task.id, "buttons": ["start", "skip"],
              "respond": f"/tasks/{task.id}/respond", "alert": count},
        keep_mood=True,
    )


@agent("silence_detector")
async def silence_detector(ctx: AgentContext) -> AgentResult | None:
    """Started a block, then an hour of silence. Not a scolding: a light "still on it?"."""
    task = ctx.db.get(Task, ctx.event.payload.get("task_id"))
    if task is None or task.status != TaskStatus.STARTED:
        return None
    quiet = int(ctx.event.payload.get("quiet_min") or 60)
    left = max(0, round((local(task.planned_end) - now_local()).total_seconds() / 60))
    return await _speak_up(
        ctx,
        instruction=(f"I started '{task.title}' and I've been silent for about {quiet} minutes; {left} minutes of the "
                     "block are left. In one short spoken sentence, check I'm still on it. Light, not a scolding: "
                     "silence might just mean I'm deep in the work."),
        fallback=f"Quiet for an hour. Still on {task.title}?",
        mood="calm and attentive",
        meta={"kind": "silence", "task_id": task.id, "buttons": ["onit", "done", "skipped"],
              "respond": f"/tasks/{task.id}/respond"},
    )


@agent("checkin_agent")
async def checkin_agent(ctx: AgentContext) -> AgentResult | None:
    task = ctx.db.get(Task, ctx.event.payload.get("task_id"))
    if task is None or task.status in (TaskStatus.DONE, TaskStatus.SKIPPED):
        return None
    started = task.status == TaskStatus.STARTED
    if tg := courses.target(ctx.db, task):  # a course block: proof, not just "how did it go?"
        aimed = "; ".join(i.title for i in tg[1]) or "the next part"
        return await _speak_up(
            ctx,
            instruction=(f"The block '{task.title}' just ended. The target was: {aimed}. In one or two short sentences "
                         "ask me what I actually got through and where I stopped — I'll tick it off in the app."),
            fallback=f"Time's up on {task.title}. The target was {aimed}. What did you get through?",
            mood="calm and caring",
            meta={"kind": "proof", "task_id": task.id, "proof": f"/proof/{task.id}"},
        )
    return await _speak_up(
        ctx,
        instruction=(
            f"The block '{task.title}' just ended. "
            + ("I told you I started it. " if started else "I never confirmed starting it. ")
            + "Ask me in one or two short sentences how it went. Don't lecture yet."
        ),
        fallback=f"Time's up on {task.title}. How did it go?",
        mood="calm and caring",
        meta={"kind": "checkin", "task_id": task.id, "buttons": ["done", "partly", "skipped"],
              "respond": f"/tasks/{task.id}/respond"},
    )


@agent("proof_of_work_verifier")
async def proof_of_work_verifier(ctx: AgentContext) -> AgentResult | None:
    """You logged what a course block really produced. React like a mentor who checks the work."""
    p = ctx.event.payload
    task = ctx.db.get(Task, p.get("task_id"))
    if task is None:
        return None
    done, aimed, note, nxt = p.get("finished") or [], p.get("aimed") or [], p.get("note") or "", p.get("next")
    outcome = p.get("outcome")
    facts = (f"Block '{task.title}'. Target: {'; '.join(aimed) or 'none set'}. Finished: {'; '.join(done) or 'nothing'}."
             + (f" Where I stopped: {note}." if note else "") + (f" Next up: {nxt}." if nxt else ""))
    how = {"all": ("proud", "I hit the whole target. Be proud of me in one or two sentences, and name what's next."),
           "some": ("firm but encouraging", "I got part of it done. Acknowledge what I did, then be clear the rest "
                    "carries over and has to be cleared next block. Two sentences."),
           "none": ("firm and disappointed", "I got nothing on the target done. Two short sentences: honest, firm, "
                    "no insults; ask what got in the way.")}[outcome]
    return await _speak_up(
        ctx, instruction=f"{facts} {how[1]}",
        fallback={"all": f"Target cleared. Next up: {nxt}." if nxt else "Target cleared. Good work.",
                  "some": "Some of it's done. The rest carries over to the next block.",
                  "none": "Nothing on the target got done. What got in the way?"}[outcome],
        mood=how[0], keep_mood=outcome == "all", channel="web",
        meta={"kind": "proof_result", "task_id": task.id, "outcome": outcome})


@agent("free_time_watcher")
async def free_time_watcher(ctx: AgentContext) -> AgentResult:
    left = int(ctx.event.payload.get("minutes_left") or 0)
    nxt = ctx.event.payload.get("next_title")
    then = f"'{nxt}' starts in {left} minutes" if nxt else f"about {left} minutes left before winding down for bed"
    return await _speak_up(
        ctx,
        instruction=(f"I'm in free time — no block right now; {then}. Ask me, in one or two short spoken sentences, "
                     "what I'm doing right now. Free time is fine for rest, food or a walk, but if I'm scrolling "
                     "or wasting it, I should tell you honestly. Don't lecture yet."
                     + (f" If I'm free, suggest this (it fits): {ctx.notes['focus_pick']}." if ctx.notes.get("focus_pick") else "")),
        fallback="Free time. What are you doing right now? "
                 + (f"{nxt} starts in {left} minutes." if nxt else f"You have {left} minutes before bed."),
        mood="calm and attentive",
        meta={"kind": "free_checkin", "minutes_left": left, "next": nxt},
    )


# ---------- planning ahead: tomorrow (9 pm), the rest of today (a block ended short), next week (Sunday) ----------

def _wake(db):
    from app.core import wake

    h, m = map(int, wake.wake_time(db).split(":"))
    return time(h, m)


def _course_loads(db, day: date) -> list[dict]:
    from app.core import courses, planner
    from app.db.models import Course

    courses.ensure(db)
    out = []
    for c in db.scalars(select(Course).order_by(Course.id)).all():
        if c.active_from and from_db(c.active_from) > to_utc(datetime.combine(day, time(23, 59))):
            continue
        ld = planner.load(db, c, day)
        if ld["due"] or ld["overdue"]:
            out.append({**ld, "course_obj": c})
    return out


@agent("daily_planner")
async def daily_planner(ctx: AgentContext) -> AgentResult | None:
    """9 pm: tomorrow at a glance, and a catch-up proposal when the courses need more time than the plan has."""
    from app.core import planner

    day = date.fromisoformat(ctx.event.payload.get("date") or (now_local().date() + timedelta(days=1)).isoformat())
    blocks = [t for t in planner.blocks_on(ctx.db, day) if t.notify != "none" and t.category != "sleep"]
    if not blocks:
        return None
    loads = _course_loads(ctx.db, day)
    from app.core import streaks

    plan = "; ".join(f"{local(t.planned_start):%H:%M} {t.title}" for t in blocks[:10])
    chains = [s for s in streaks.all_streaks(ctx.db) if s["current"] >= 2]
    from app.core import vision

    dream = vision.line(ctx.db) if day.weekday() == 0 else ""  # Mondays: what the week is for
    keep = (f" It's a new week: tie it to my vision in a few words ({dream})." if dream else "")
    if chains:
        keep += " Streaks to keep alive tomorrow: " + ", ".join(f"{s['label']} {s['current']} days" for s in chains) + "."
    work = " ".join(f"{ld['course']}: {ld['due']} topics due ({ld['section'] or 'catch-up'}), {ld['overdue']} overdue, "
                    f"~{round(ld['need_min'] / 60, 1)}h needed vs {round(ld['capacity_min'] / 60, 1)}h of blocks."
                    for ld in loads)
    out = await _speak_up(
        ctx, instruction=(f"Brief me on tomorrow ({day:%A}) in two or three short spoken sentences, like a mentor at "
                          f"9 pm: the shape of the day, the one thing that matters most, and to sleep on time. Plan: {plan}. "
                          f"{work}{keep}"),
        fallback=f"Tomorrow starts with {blocks[0].title} at {local(blocks[0].planned_start):%-I:%M}. " + (
            f"{loads[0]['due']} TUF topics are due." if loads else "Sleep on time."),
        mood="calm and caring", meta={"kind": "daily_plan", "date": day.isoformat()})
    for ld in loads:
        if ld["short_min"] > planner.SLACK:
            ops = planner.catch_up_ops(ctx.db, ld["course_obj"], day, ld["short_min"], _wake(ctx.db))
            planner.propose(ctx.db, ops, f"Tomorrow {ld['course']} needs about {round(ld['need_min'] / 60, 1)}h "
                                         f"({ld['due']} due + {ld['overdue']} overdue) but its blocks give "
                                         f"{round(ld['capacity_min'] / 60, 1)}h.")
    return out


@agent("replanner")
async def replanner(ctx: AgentContext) -> None:
    """A course block ended with work left (or was skipped): offer the rest of today's free time for it."""
    from app.core import courses, planner
    from app.db.models import KeyValue

    task = ctx.db.get(Task, ctx.event.payload.get("task_id"))
    if task is None or (ctx.event.type == "proof.logged" and ctx.event.payload.get("outcome") == "all"):
        return
    c = courses.course_for(ctx.db, task)
    now = datetime.now(timezone.utc)
    if c is None or local(now).time() >= time(21, 0):  # late: the 9 pm planner handles tomorrow
        return
    key = f"replan:{c.key}:{local(now).date().isoformat()}"
    if ctx.db.get(KeyValue, key) is not None:  # one offer a day, not after every block
        return
    ld = planner.load(ctx.db, c, local(now).date())
    remaining = sum((from_db(t.planned_end) - max(now, from_db(t.planned_start))).total_seconds() / 60
                    for t in planner.blocks_on(ctx.db, local(now).date())
                    if t.id != task.id and from_db(t.planned_end) > now and re.search(c.block_match, t.title, re.I)
                    and t.status in (TaskStatus.PLANNED, TaskStatus.STARTED))
    short = round(ld["need_min"] - remaining)
    if short <= planner.SLACK:
        return
    ops = planner.catch_up_ops(ctx.db, c, local(now).date(), short, _wake(ctx.db), after=now + timedelta(minutes=15),
                               max_blocks=1)
    if planner.propose(ctx.db, ops, f"{task.title} left work behind: {c.title} is {round(short / 60, 1)}h short today."):
        ctx.db.add(KeyValue(key=key, value="1"))


@agent("weekly_planner")
async def weekly_planner(ctx: AgentContext) -> AgentResult | None:
    """Sunday: next week's course load vs the hours on the timetable; weekend blocks if it doesn't fit."""
    from app.core import courses, planner
    from app.db.models import Course

    week = ctx.event.payload.get("week_of")
    if not week:
        return None
    nxt = date.fromisoformat(week) + timedelta(days=7)
    days = [nxt + timedelta(days=i) for i in range(7)]
    courses.ensure(ctx.db)
    out = None
    for c in db_courses(ctx.db):
        its = [i for i in courses.items(ctx.db, c) if not i.done_at and not i.optional and i.planned_date]
        if not its:
            continue
        need = sum(i.est_min or 10 for i in its if i.planned_date <= days[-1].isoformat())
        cap = sum(planner.load(ctx.db, c, d)["capacity_min"] for d in days)
        short = round(need - cap)
        sections = sorted({m.group(1) for i in its if days[0].isoformat() <= i.planned_date <= days[-1].isoformat()
                           and (m := re.match(r"(Sprint \d+)", i.section or ""))})  # "Sprint" with no number is skipped
        if short > 60:
            ops = []
            for d in [x for x in days if x.weekday() >= 5]:  # Saturday, Sunday
                ops += planner.catch_up_ops(ctx.db, c, d, short - sum(o["duration_min"] for o in ops), _wake(ctx.db))
            planner.propose(ctx.db, ops, f"Next week {c.title} ({', '.join(sections) or 'catch-up'}) needs "
                                         f"~{round(need / 60)}h, the timetable gives {round(cap / 60)}h.")
        out = await _speak_up(
            ctx, instruction=(f"In two short spoken sentences, set up next week for {c.title}: "
                              f"{', '.join(sections) or 'catch-up'}, about {round(need / 60)} hours of work against "
                              f"{round(cap / 60)} hours of blocks" + (", so I've proposed weekend blocks." if short > 60 else ".")),
            fallback=f"Next week: {', '.join(sections) or c.title}, about {round(need / 60)} hours against {round(cap / 60)} on the timetable.",
            mood="focused and sharp", meta={"kind": "weekly_plan", "week": nxt.isoformat()})
    return out


def db_courses(db):
    from app.db.models import Course

    return db.scalars(select(Course).order_by(Course.id)).all()


@agent("explainer")
async def explainer(ctx: AgentContext) -> AgentResult | None:
    """After you approve a change I proposed: what changed and why, in a sentence."""
    changes, why = ctx.event.payload.get("changes") or [], ctx.event.payload.get("why") or ""
    if not changes:
        return None
    return await _speak_up(
        ctx, instruction=f"I approved your change. Done: {'; '.join(changes)}. Why: {why}. One short spoken sentence saying what changed and why.",
        fallback=f"Done: {'; '.join(changes)}.", mood="calm and caring", channel="web", meta={"kind": "explained"})
