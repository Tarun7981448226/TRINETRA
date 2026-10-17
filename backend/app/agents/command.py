"""Command council: the agents that hear you first and answer you."""
import re

from sqlalchemy import select

from app.core import llm
from app.core import mood as mood_modes
from app.core.orchestrator import AgentContext, AgentResult
from app.core.persona import humanize, system_prompt
from app.core.registry import agent
from app.core.timeutil import day_bounds_utc, local, now_local
from app.db.models import Event, Memory, Message, Task

INTENT_PATTERNS: dict[str, str] = {
    "feeling_low": r"\b(tired|sad|low|stressed|anxious|exhausted|depressed|lonely|overwhelmed|can'?t do)\b",
    "slacking": r"\b(skip(ped)?|lazy|procrastinat\w*|bunk(ed)?|wasted (my )?time|didn'?t (study|work|do it|go))\b",
    "progress": r"\b(done|finished|completed|nailed|achieved)\b",
    "planning": r"\b(plan|schedule|timetable|remind|tomorrow|reschedule|move)\b",
}
# Signals that need care, not pressure. Overrides everything else.
DISTRESS = re.compile(r"\b(hopeless|worthless|give up on life|no point|hurt myself|end it)\b", re.I)

# Placeholder until the Emotion Engine (phase 3b) takes over mood selection.
MOOD_FOR_INTENT = {
    "feeling_low": "gentle and comforting",
    "slacking": "firm and disappointed — push them, kindly but without excuses",
    "progress": "proud and energised",
    "planning": "focused and sharp",
    "chat": "calm and caring",
}


@agent("data_collector")
async def data_collector(ctx: AgentContext) -> None:
    """Every event becomes training data for the ML brain."""
    ctx.db.add(Event(type=ctx.event.type, source=ctx.event.source, payload=ctx.event.payload))


@agent("router")
async def router(ctx: AgentContext) -> None:
    """Cheap, instant intent tagging — no LLM call needed."""
    text = str(ctx.event.payload.get("text", ""))
    ctx.notes["distress"] = bool(DISTRESS.search(text))
    ctx.notes["intent"] = next(
        (name for name, pat in INTENT_PATTERNS.items() if re.search(pat, text, re.I)), "chat"
    )
    if demo := mood_modes.detect_demo(text):
        ctx.notes["demo"] = {"mode": demo[0], "target": demo[1]}
        return  # a one-off show — the lasting mode stays as it is
    asked, mode = mood_modes.detect_request(text)
    if asked:
        mood_modes.set_mode(ctx.db, mode)
        ctx.notes["mode_changed"] = mode or "normal"


def _today_context(ctx: AgentContext) -> str:
    start, end = day_bounds_utc()
    tasks = ctx.db.scalars(
        select(Task).where(Task.planned_start >= start, Task.planned_start < end).order_by(Task.planned_start)
    ).all()
    lines = [f"Now: {now_local():%A %d %b %Y, %H:%M}"]
    if tasks:
        lines.append("Today's timetable:")
        for t in tasks:
            lines.append(f"- {local(t.planned_start):%H:%M}–{local(t.planned_end):%H:%M} {t.title} [{t.status}]")
    else:
        lines.append("Today's timetable: empty")
    memories = ctx.db.scalars(select(Memory).order_by(Memory.importance.desc(), Memory.id.desc()).limit(40)).all()
    if memories:
        lines.append("What you know about them:")
        lines += [f"- ({m.kind}) {m.content}" for m in memories]
    return "\n".join(lines)


@agent("core_orchestrator")
async def core(ctx: AgentContext) -> AgentResult:
    text = str(ctx.event.payload.get("text", "")).strip()
    channel = ctx.event.source
    intent = ctx.notes.get("intent", "chat")
    demo = ctx.notes.get("demo")
    if ctx.notes.get("distress"):
        mood = "deeply caring — no pressure at all"  # overrides any mode, including angry
    elif demo:
        mood = mood_modes.MODES[demo["mode"]]
    else:
        # The Emotion Engine's graded feeling; on a calm day, the intent flavours the tone instead.
        felt = ctx.notes.get("expression")
        if not felt or (ctx.notes.get("expression_label") == "calm" and intent in ("planning", "chat")):
            felt = MOOD_FOR_INTENT[intent]
        mood = mood_modes.apply(ctx.db, felt)

    history = ctx.db.scalars(select(Message).order_by(Message.id.desc()).limit(12)).all()
    context = _today_context(ctx)
    if changes := ctx.notes.get("timetable_changes"):
        context += "\nYou JUST made these timetable changes for them in response to this message. Confirm in a few natural words, like a friend would, e.g. Done, gym's on for 6 every weekday.:\n"
        context += "\n".join(f"- {c}" for c in changes)
    if d := ctx.notes.get("deliberation"):
        concerns = "; ".join(d.get("findings") or []) or "none"
        if d.get("action") in ("apply", "apply_adjusted"):
            context += ("\nBefore changing anything you reviewed it with your agents. Concerns found: "
                        f"{concerns}. Your reasoning: {d.get('reasoning') or 'clean change, no clashes, sleep protected'}."
                        + (" You applied an ADJUSTED, safer version — say what you changed and why, briefly."
                           if d.get("action") == "apply_adjusted" else ""))
        else:
            context += ("\nYou reviewed the requested change and did NOT apply it yet. Concerns: "
                        f"{concerns}. Your thinking: {d.get('reasoning') or ''} "
                        f"Ask them: {d.get('question') or 'should I go ahead?'} The options are buttons below "
                        "your message. Be brief and human, like a chief-of-staff flagging a trade-off.")
    if goal := ctx.notes.get("goal_created"):
        context += (f"\nYou JUST saved their goal '{goal['title']}' with milestones {goal['milestones']}. "
                    "Acknowledge it like a mentor who believes in them (1-2 sentences)"
                    + (", and say you've drafted a weekly plan they can approve below." if ctx.notes.get("proposal") else "."))
    if promises := ctx.notes.get("promises_saved"):
        context += (f"\nYou noted their promise(s): {promises}. Tell them briefly you'll check in at the deadline "
                    "and hold them to it. You did NOT add anything to their timetable — don't say you did.")
    if pick := ctx.notes.get("focus_pick"):
        context += (f"\nThey're asking what to do now. The highest-impact thing that fits: {pick}. Recommend it "
                    "concretely (name it), in a sentence or two.")
    if saved := ctx.notes.get("vision_saved"):
        context += f"\nYou just saved their vision ({saved}). Acknowledge it briefly; it's on the 🎯 screen."
    if demo:
        who = demo["target"] or "the person they describe (or them, if nobody is named)"
        context += (
            f"\nThey asked for a ONE-TIME demonstration of your {demo['mode']} side, aimed at {who}. "
            "Perform it fully in character, right now, speaking directly to that person — make it feel real "
            "and intense like a coach, but no slurs, threats, or humiliation. Don't explain or add disclaimers; "
            "just perform it. After this you return to your usual mode."
        )
    if changed := ctx.notes.get("mode_changed"):
        context += (
            f"\nThey just asked you to switch to {changed} mode. Switch instantly and show it in this very reply."
            if changed != "normal" else "\nThey asked you to go back to your normal self. Do it, warmly."
        )
    messages = [{"role": "system", "content": system_prompt(mood, context)}]
    messages += [
        {
            "role": "user" if m.role == "user" else "assistant",
            # Timestamps stop the model confusing 'earlier today' with 'yesterday'.
            "content": f"[{local(m.created_at):%a %d %b %H:%M}] {m.content}" if m.role == "user" else m.content,
        }
        for m in reversed(history)
    ]
    messages.append({"role": "user", "content": text})

    try:
        reply = humanize(await llm.complete(messages, tier="smart", reasoning="low"))  # conversation: fast > deep
    except llm.LLMUnavailable as e:
        reply = str(e) if not ctx.settings.llm_available else (
            "I'm having trouble thinking right now — my model providers are busy. Try me again in a minute."
        )

    ctx.db.add(Message(role="user", content=text, channel=channel))
    ctx.db.add(Message(role="trinetra", content=reply, channel=channel, mood=mood))
    if proposal := ctx.notes.get("proposal"):
        ctx.db.add(Message(role="trinetra", content=proposal["content"], channel=channel, mood=mood,
                           meta=proposal["meta"]))
    return AgentResult(reply=reply, mood=mood)
