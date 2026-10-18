"""Mentor council: your vision, the plan to get there, the promises you make, and the weekly reckoning."""
import json
import logging
import re
from datetime import date, datetime, time

from sqlalchemy import select

from app.core import llm, mentor
from app.core import mood as mood_modes
from app.core.orchestrator import AgentContext, AgentResult
from app.core.persona import humanize, system_prompt
from app.core.registry import agent
from app.core.timeutil import now_local, to_utc
from app.db.models import Goal, Message, Milestone, Promise

log = logging.getLogger("trinetra.mentor")

GOAL_HINT = re.compile(
    r"\b(goal|dream|vision|ambition|aim|aspire|want to (be|become|get|land|crack|build|learn|master|lose|run)|"
    r"my target|achieve|by (january|february|march|april|may|june|july|august|september|october|november|"
    r"december|summer|winter|spring|fall|end of|next year|20\d\d))\b",
    re.I,
)
PROMISE_HINT = re.compile(
    r"\b(i'?ll|i will|i promise|i'?m going to|i am going to|i swear|i commit)\b.*\b(by|before|until|tonight|"
    r"tomorrow|today|this week|monday|tuesday|wednesday|thursday|friday|saturday|sunday|\d{1,2}(:\d{2})?\s*(am|pm))\b",
    re.I,
)

GOAL_PROMPT = """You are TRINETRA's goal architect. The user just said something about what they want to achieve.
Today is {today} ({weekday}). Their existing goals: {goals}. Their current weekly routine: {routine}.

If the message states a real goal or ambition (not just a passing wish or a question), return JSON:
{{"is_goal": true,
  "goal": {{"title": short goal, "why": their reason if given else "", "horizon": "1m"|"3m"|"6m"|"1y"|"3y"|"5y",
            "area": "study|career|fitness|health|finance|skills|personal|relationships", "target_date": "YYYY-MM-DD" or null}},
  "milestones": [{{"title": concrete checkpoint, "due_date": "YYYY-MM-DD"}}],   // 3-6, evenly spaced, measurable
  "weekly_blocks": [{{"title": what to do, "days": "mon,wed,fri" | "weekdays" | "daily" | "sat,sun",
                     "start": "HH:MM", "duration_min": int, "category": "study|work|fitness|health|personal"}}]  // 1-3 realistic blocks
}}
Weekly blocks must NEVER overlap each other on any shared day, nor their existing routine. Check every pair: a block
that starts at 19:00 for 90 min occupies 19:00-20:30. Leave at least 30 min between blocks on the same day.
Otherwise return {{"is_goal": false}}."""

PROMISE_PROMPT = """Extract commitments the user makes in this message — things THEY say they will do by a time.
Now: {now} ({weekday}), user's local time. Return JSON only:
{{"promises": [{{"text": "what they'll do, short, in second person e.g. 'finish 50 LeetCode problems'",
                "due": "YYYY-MM-DD HH:MM" (local; 'tonight' = 23:00, 'tomorrow' = tomorrow 21:00, a weekday = that day 21:00)}}]}}
Return {{"promises": []}} if there's no real commitment with a deadline."""


def _date(value) -> date | None:
    try:
        return date.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


async def _json_call(system: str, text: str, tier: str = "fast") -> dict | None:
    try:
        raw = await llm.complete([{"role": "system", "content": system}, {"role": "user", "content": text}],
                                 tier=tier, temperature=0, max_tokens=1500, json_mode=True)
        return json.loads(raw)
    except (llm.LLMUnavailable, json.JSONDecodeError, ValueError) as e:
        log.warning("mentor extraction skipped: %s", e)
        return None


@agent("goal_decomposer")
async def goal_decomposer(ctx: AgentContext) -> None:
    text = str(ctx.event.payload.get("text", ""))
    if ctx.event.payload.get("button") or not GOAL_HINT.search(text) or not ctx.settings.llm_available:
        return
    now = now_local()
    goals = [g.title for g in ctx.db.scalars(select(Goal).where(Goal.status == "active"))]
    from app.core import timetable
    routine = sorted({f"{t.title} ({t.recurrence})" for t in timetable.upcoming(ctx.db) if t.recurrence})
    data = await _json_call(
        GOAL_PROMPT.format(today=now.date(), weekday=f"{now:%A}", goals=goals or "none", routine=routine or "none"),
        text, tier="smart",
    )
    if not data or not data.get("is_goal") or not isinstance(data.get("goal"), dict):
        return
    g = data["goal"]
    target = _date(g.get("target_date"))
    goal = Goal(
        title=str(g.get("title") or text)[:200], why=str(g.get("why") or "")[:1000],
        horizon=str(g.get("horizon") or "3m")[:20], area=str(g.get("area") or "general")[:50],
        target_date=to_utc(datetime.combine(target, time(21))) if target else None,
    )
    for i, m in enumerate((data.get("milestones") or [])[:8]):
        due = _date(m.get("due_date"))
        goal.milestones.append(Milestone(
            title=str(m.get("title", ""))[:200], position=i,
            due_date=to_utc(datetime.combine(due, time(21))) if due else None,
        ))
    ctx.db.add(goal)
    ctx.db.flush()
    blocks = [b for b in (data.get("weekly_blocks") or [])[:3] if isinstance(b, dict)]
    ctx.notes["goal_created"] = {"id": goal.id, "title": goal.title, "milestones": [m.title for m in goal.milestones]}
    if blocks:
        lines = "\n".join(f"• {b.get('title')} — {b.get('days')} at {b.get('start')} ({b.get('duration_min')} min)"
                          for b in blocks)
        ctx.notes["proposal"] = {
            "content": f"Here's the weekly plan I'd add for “{goal.title}”:\n{lines}\nWant me to put it on your timetable?",
            "meta": {"kind": "plan_proposal", "goal_id": goal.id, "blocks": blocks,
                     "buttons": ["approve", "reject"]},
        }


@agent("accountability_agent")
async def accountability_agent(ctx: AgentContext) -> AgentResult | None:
    if ctx.event.type == "promise.due":
        return await _promise_checkin(ctx)
    text = str(ctx.event.payload.get("text", ""))
    if ctx.event.payload.get("button") or not PROMISE_HINT.search(text) or not ctx.settings.llm_available:
        return None
    now = now_local()
    data = await _json_call(PROMISE_PROMPT.format(now=f"{now:%Y-%m-%d %H:%M}", weekday=f"{now:%A}"), text)
    saved = []
    for p in (data or {}).get("promises", [])[:3]:
        try:
            due = datetime.strptime(str(p.get("due")), "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        if due <= now.replace(tzinfo=None):
            continue
        ctx.db.add(Promise(text=str(p.get("text", ""))[:300], due_at=to_utc(due)))
        saved.append(f"{p.get('text')} (by {due:%a %d %b %H:%M})")
    if saved:
        ctx.notes["promises_saved"] = saved
    return None


async def _promise_checkin(ctx: AgentContext) -> AgentResult | None:
    promise = ctx.db.get(Promise, ctx.event.payload.get("promise_id"))
    if promise is None or promise.status != "open":
        return None
    mood = mood_modes.apply(ctx.db, "calm and caring")
    fallback = f"Deadline's here. You promised to {promise.text}. Did you do it?"
    text = fallback
    if ctx.settings.llm_available:
        try:
            text = humanize(await llm.complete([
                {"role": "system", "content": system_prompt(mood)},
                {"role": "user", "content": f"My deadline just hit. I promised: '{promise.text}'. "
                                            "Ask me straight, in one or two short sentences, whether I kept it."},
            ], tier="fast", max_tokens=200)) or fallback
        except llm.LLMUnavailable:
            pass
    meta = {"kind": "promise_check", "promise_id": promise.id, "buttons": ["kept", "broken"],
            "respond": f"/promises/{promise.id}/respond"}
    ctx.db.add(Message(role="trinetra", content=text, channel="reminder", mood=mood, meta=meta))
    ctx.notes["proactive"] = {"text": text, "mood": mood, "meta": meta}
    return AgentResult(reply=text, mood=mood)


@agent("challenge_designer")
async def challenge_designer(ctx: AgentContext) -> None:
    ctx.notes["challenges"] = mentor.challenges(ctx.db)


@agent("progress_scorer")
async def progress_scorer(ctx: AgentContext) -> None:
    for goal in ctx.db.scalars(select(Goal).where(Goal.status == "active")):
        mentor.refresh_goal_progress(ctx.db, goal)


@agent("mentor_voice")
async def mentor_voice(ctx: AgentContext) -> AgentResult:
    """The Sunday-evening session: what you won, where you lagged and why, and one challenge."""
    summary = mentor.week_summary(ctx.db)
    challenges = ctx.notes.get("challenges", [])
    mood = mood_modes.apply(ctx.db, ctx.notes.get("expression") or "calm, proud where earned, honest where not",
                           ctx.notes.get("expression_label"))
    fallback = (f"Weekly check-in: you finished {summary['done']} blocks and skipped {summary['skipped']}. "
                "Let's make next week sharper.")
    text = fallback
    if ctx.settings.llm_available:
        try:
            text = humanize(await llm.complete([
                {"role": "system", "content": system_prompt(mood)},
                {"role": "user", "content": (
                    "Give me my weekly mentor session, spoken, max 7 sentences. Structure: one real win; where I "
                    "lagged and the honest likely reason; how my goals are tracking; then ONE specific challenge for "
                    "next week that pushes me past my comfort zone (use the raise/ease verdicts: raise = harder, "
                    "ease = smaller steps and ask what's blocking me). Use only these facts:\n"
                    f"{json.dumps({'week': summary, 'overload': challenges})}"
                )},
            ], tier="smart", max_tokens=700)) or fallback
        except llm.LLMUnavailable:
            pass
    meta = {"kind": "weekly_session"}
    ctx.db.add(Message(role="trinetra", content=text, channel="reminder", mood=mood, meta=meta))
    ctx.notes["proactive"] = {"text": text, "mood": mood, "meta": meta}
    return AgentResult(reply=text, mood=mood)
