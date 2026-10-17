"""Time & Planning + Reminders: building your timetable from plain words, and nudging you on time."""
import json
import logging
import re
from datetime import date, datetime, time, timedelta

from app.core import deliberation, llm, timetable
from app.core import mood as mood_modes
from app.core.orchestrator import AgentContext, AgentResult, IncomingEvent
from app.core.persona import humanize, system_prompt
from app.core.registry import agent
from app.core.timeutil import local, now_local
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
                {"role": "user", "content": text},
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

    # Marking something done/skipped needs no deliberation.
    quick = [o for o in ops if o.get("op") == "status"]
    ops = [o for o in ops if o.get("op") != "status"]
    changes = deliberation.apply(ctx.db, quick) if quick else []

    if ops:
        proposal = deliberation.build(ctx.db, ops)
        review = await ctx.core.dispatch(
            IncomingEvent("plan.proposed", {"request": text[:300], "ops_count": len(ops)}, "planner"),
            ctx.db, notes={"proposal": proposal, "request": text},
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

async def _speak_up(ctx: AgentContext, instruction: str, fallback: str, mood: str, meta: dict,
                    keep_mood: bool = False, channel: str = "reminder") -> AgentResult:
    """Compose a short proactive line in TRINETRA's voice; fall back to a template if the LLM is down."""
    if not keep_mood and ctx.notes.get("expression_label") not in (None, "calm"):
        mood = ctx.notes["expression"]  # after a string of skips, reminders get an edge
    mood = mood_modes.apply(ctx.db, mood)  # a mode you asked for wins
    text = fallback
    if ctx.settings.llm_available:
        try:
            text = await llm.complete(
                [{"role": "system", "content": system_prompt(mood)}, {"role": "user", "content": instruction}],
                tier="fast", temperature=0.8, max_tokens=300,
            )
            text = humanize(text) or fallback
        except llm.LLMUnavailable:
            pass
    ctx.db.add(Message(role="trinetra", content=text, channel=channel, mood=mood, meta=meta))
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
    risk = ""
    if (p := ctx.notes.get("p_complete")) is not None and p < 0.5:
        risk = (f" My neural core says there's only a {round(p * 100)}% chance I'll actually do it — "
                "I tend to skip this kind of block. Be extra persuasive and make starting feel easy.")
    return await _speak_up(
        ctx,
        instruction=(
            f"Remind me that '{task.title}' starts {when} ({s:%H:%M}–{e:%H:%M}). "
            "One or two short spoken sentences. Energise me to start on time." + risk
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


@agent("checkin_agent")
async def checkin_agent(ctx: AgentContext) -> AgentResult | None:
    task = ctx.db.get(Task, ctx.event.payload.get("task_id"))
    if task is None or task.status in (TaskStatus.DONE, TaskStatus.SKIPPED):
        return None
    started = task.status == TaskStatus.STARTED
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


@agent("free_time_watcher")
async def free_time_watcher(ctx: AgentContext) -> AgentResult:
    left = int(ctx.event.payload.get("minutes_left") or 0)
    nxt = ctx.event.payload.get("next_title")
    then = f"'{nxt}' starts in {left} minutes" if nxt else f"about {left} minutes left before winding down for bed"
    return await _speak_up(
        ctx,
        instruction=(f"I'm in free time — no block right now; {then}. Ask me, in one or two short spoken sentences, "
                     "what I'm doing right now. Free time is fine for rest, food or a walk, but if I'm scrolling "
                     "or wasting it, I should tell you honestly. Don't lecture yet."),
        fallback="Free time. What are you doing right now? "
                 + (f"{nxt} starts in {left} minutes." if nxt else f"You have {left} minutes before bed."),
        mood="calm and attentive",
        meta={"kind": "free_checkin", "minutes_left": left, "next": nxt},
    )
