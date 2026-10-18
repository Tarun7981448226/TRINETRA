"""Command council: the agents that hear you first and answer you."""
import re
from datetime import timedelta

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
    "planning": r"\b(plan|schedule|timetable|remind|tomorrow|tonight|reschedule|move|shift|postpone|push back|"
                r"cancel (my|the|tomorrow|today|tonight)|free up|clear my)\b",
}
# Signals that need care, not pressure. Overrides everything else.
QUIETER = re.compile(r"(?<!don't )(?<!dont )(?<!do not )\b(stop (nagging|pinging|bugging|spamming)( me)?|too many (notifications|reminders|nudges|messages)|"
                     r"(fewer|less) (notifications|reminders|nudges)|leave me alone(?! for| to| while| until)|you'?re (too )?(annoying|clingy)|"
                     r"back off(?!\s+(the|my|on|it|to|from|a|an)\b)|stop bothering me)\b", re.I)
FORGET_THAT = re.compile(r"(?<!don't )(?<!dont )(?<!do not )(?<!never )(?<!not )(?<!won't )\b(forget (that|this|what i (just )?said)(?! i\b| my\b| the\b| to\b)|don'?t (remember|save|keep) (that|this)|delete that( memory)?|"
                         r"that'?s private|erase that)\b", re.I)
LOUDER = re.compile(r"(?<!never )(?<!don't )(?<!dont )(?<!do not )(?<!stop )\b(nudge me again|you can (nag|nudge|ping) me again|(more|turn on) (nudges|reminders)|push me (more|harder))\b", re.I)
CRISIS_LINE = ("If any part of you is thinking about ending your life or hurting yourself, please call or text 988 "
               "(the Suicide & Crisis Lifeline in the US; in India, Tele-MANAS 14416; elsewhere, your local emergency "
               "number) right now, or reach someone you trust. You don't have to carry this alone.")

# Crisis language only (an ordinary "I want to give up on this bug" is low, not crisis — the emotion agents handle that).
DISTRESS = re.compile(
    r"\b(give up on life|no point (in )?(living|anything|going on|being here)|hurt(ing)? myself|end it all|"
    r"end (it|things|my life) (for good|forever)|end my life|kill(ing)? myself|suicid\w*|(i want|i wanna|i'?m going|i am going) to die|"
    r"want to be dead|not worth living|no reason (for me )?to (live|go on|be here)|(don'?t|do not) want to (be here|wake up|exist|live)|"
    r"(don'?t|do not|cant|can'?t) see (the|any) point (of|in) (anything|living|life|going on)|"
    r"want (it all|everything) to (stop|end)|disappear forever|self[- ]?harm\w*|better off without me|"
    r"i'?m done with life(?!\s+\w)|(i'?m|i am|i feel|feeling) (so |completely |totally )?(hopeless|worthless)(?!\s+at\b))\b",
    re.I)

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


# "show me your emotions" → the character acts them out while the reply names each one
ALL_EMOTIONS = ["happy", "excited", "proud", "caring", "shy", "surprised", "firm", "angry", "sad", "sleepy"]
EMOTION_WORDS = {"happy": "happy|happiness|joy(ful)?|glad|smil\\w*", "excited": "excited|excitement|exciting|hyped?|pumped",
                 "proud": "proud|pride", "caring": "caring|care|kind|kindness|soft|love|loving|gentle|warm",
                 "shy": "shy|shyness|blush\\w*|embarrass\\w*|cute", "surprised": "surprised?|shocked|amazed|scared|confused|curious",
                 "firm": "firm|serious|strict|stern", "angry": "angry|anger|mad|furious|annoyed|rage",
                 "sad": "sad|sadness|upset|down|crying|cry", "sleepy": "sleepy|tired|sleep|bored"}
EMOTION_LABEL = {"happy": "😊 Happy", "excited": "🤩 Excited", "proud": "😌 Proud", "caring": "🤗 Caring", "shy": "☺️ Shy",
                 "surprised": "😮 Surprised", "firm": "😐 Firm", "angry": "😠 Angry", "sad": "😢 Sad", "sleepy": "😴 Sleepy"}
PERFORM_ALL = re.compile(r"\b(show|act|perform|do|express|display)\b.{0,30}\b(emotions?|feelings?|faces?|expressions?|moods?)\b", re.I)
PERFORM_ONE = re.compile(r"\b(show me|act|play|give me|do)\b.{0,20}?\b(" + "|".join(EMOTION_WORDS.values()) + r")\b", re.I)


def perform_request(text: str) -> list[str] | None:
    """'show me angery then hapy' → ['angry', 'happy'] (typos, slang and casual phrasing understood by core/show.py)."""
    from app.core.show import emotions
    return emotions(text)


@agent("router")
async def router(ctx: AgentContext) -> None:
    """Cheap, instant intent tagging — no LLM call needed."""
    text = str(ctx.event.payload.get("text", ""))
    ctx.notes["distress"] = bool(DISTRESS.search(text))
    from app.core import show as _show
    plain = " ".join(_show.normalise(text))  # "cn u mve my gym tmrw" → "can you move my gym tomorrow"
    ctx.notes["intent"] = next(
        (name for name, pat in INTENT_PATTERNS.items() if re.search(pat, plain, re.I)), "chat"
    )
    from app.core import show
    # a mood mode ("be angry with me", "hype mode") or a one-off demo ("scold Rahul") wins over a face or a show
    mode_talk = mood_modes.detect_demo(text) or mood_modes.detect_request(text)[0]
    if not mode_talk and (wanted := show.request(text)):  # "dance", "play the guitar", "jump", "stop"
        ctx.notes["show"] = wanted
        return
    if not mode_talk and (perform := perform_request(text)):
        ctx.notes["perform"] = perform
        return
    if demo := mood_modes.detect_demo(text):
        ctx.notes["demo"] = {"mode": demo[0], "target": demo[1]}
        return  # a one-off show — the lasting mode stays as it is
    if FORGET_THAT.search(text):  # "forget that": what it just learned is put away (archived, never recalled)
        from datetime import datetime, timedelta, timezone
        from app.db.models import Memory
        since = datetime.now(timezone.utc) - timedelta(minutes=15)
        fresh = [m for m in ctx.db.scalars(select(Memory).where(Memory.created_at >= since)) if not m.archived]
        for m in fresh:
            m.archived = True
        ctx.notes["forgot"] = [m.content for m in fresh] or ["(nothing new to forget)"]
    if text.startswith(("✅", "✋", "⚡")):  # a button answer re-sent as a message isn't a request about nudges
        pass
    elif QUIETER.search(text):  # "stop nagging me": his call — optional nudges go quiet for a few days
        from app.core import autonomy
        ctx.notes["quieter_until"] = autonomy.quieter(ctx.db)
    elif LOUDER.search(text):
        from app.core import autonomy
        autonomy.louder(ctx.db)
        ctx.notes["nudges_back"] = True
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
    t_start, t_end = day_bounds_utc(now_local() + timedelta(days=1))
    tomorrow = ctx.db.scalars(select(Task).where(Task.planned_start >= t_start, Task.planned_start < t_end)
                              .order_by(Task.planned_start)).all()
    lines.append("Tomorrow's timetable:" if tomorrow else "Tomorrow's timetable: empty")
    lines += [f"- {local(t.planned_start):%H:%M}–{local(t.planned_end):%H:%M} {t.title} [{t.status}]" for t in tomorrow]
    from app.core import recall  # the memories that matter for what he just said (not just the 40 "most important")
    text = str(ctx.event.payload.get("text", ""))
    recent = " ".join(m.content for m in ctx.db.scalars(select(Message).where(Message.role == "user")
                                                         .order_by(Message.id.desc()).limit(3)).all())
    memories = recall.recall(ctx.db, f"{text} {recent}".strip(), touch=not ctx.event.payload.get("button"))  # a tap isn't a use
    if memories:
        lines.append("What you know about them:")
        lines += [f"- ({m.kind}) {m.content}" for m in memories]
    else:
        lines.append("What you know about them: nothing saved yet. If he asks what you know, say honestly that you're "
                     "still getting to know him — don't describe his personality or habits.")
    return "\n".join(lines)


# Emotional support in stages (Hill's Helping Skills; the ESConv study of real supporters): explore → comfort → act.
# Jumping to advice on the first sad message feels dismissive; never moving on to a small step feels stuck.
SUPPORT_STEPS = [
    "Support stage 1, explore: don't advise yet. Reflect the feeling you hear in your own words, then ask ONE gentle, "
    "open question about what's going on.",
    "Support stage 2, comfort: affirm him — it makes sense to feel this way, and name something real he's done well or "
    "is carrying. Reassure without brushing it off. Still no to-do list.",
    "Support stage 3, act: now offer ONE small, concrete next step (tiny and doable tonight), or ask if he wants one. "
    "Keep the warmth.",
]


CHANGE = re.compile(r"(?:moved to|added) #\d+ \w{3} \d{1,2} \w{3} (\d{2}:\d{2})–(\d{2}:\d{2}) (.+?) \[")


def _true_to_changes(reply: str, changes: list[str]) -> str:
    """Seen live: after swapping gym and DSA, the reply gave each the other's time. Only an EXPLICIT time (with am/pm or a
    colon) right after a changed block's name is checked — not one after "from" (that's the old time); if it's none of
    that block's new starts or ends, a short exact line is added and the reply itself is kept."""
    def forms(t: str) -> set[str]:
        h, m = int(t[:2]), t[3:]
        twelve = f"{(h % 12) or 12}"
        out = {t, f"{h}:{m}", f"{twelve}:{m}", f"{twelve}:{m}{'pm' if h >= 12 else 'am'}"}
        if m == "00":
            out |= {f"{twelve}{'pm' if h >= 12 else 'am'}"}
        return out
    facts = [(m.group(3).strip(), m.group(1), m.group(2)) for c in changes if (m := CHANGE.search(c))]
    allowed: dict[str, set[str]] = {}
    for title, start, end in facts:  # the same block name at several times (Mon 7am, Tue 8am): any of them is right
        allowed.setdefault(title.split()[-1].lower(), set()).update(forms(start) | forms(end))
    wrong = False
    for name, ok in allowed.items():
        pattern = rf"\b{re.escape(name)}\b[^.!?\n]{{0,15}}?(?<!from )(?<!from)\b(\d{{1,2}}:\d{{2}}\s*(?:am|pm)?|\d{{1,2}}\s*(?:am|pm))\b(?!\s*(?:h|hr|hour|min))"
        for m in re.finditer(pattern, reply, re.I):
            said = re.sub(r"\s+", "", m.group(1).lower())  # models write "7\u202fpm" (narrow no-break space)
            if said not in ok and said.lstrip("0") not in ok:
                wrong = True
    if not wrong:
        return reply
    return reply.rstrip() + " (Exact: " + "; ".join(f"{t} {a}–{b}" for t, a, b in facts) + ".)"


def support_step(ctx: AgentContext) -> str | None:
    """Where we are in a low moment: count my caring replies in the last 2 hours."""
    if ctx.notes.get("distress") or ctx.notes.get("expression_label") not in ("comforting", "gentle"):
        return None
    from datetime import datetime, timedelta, timezone
    since = datetime.now(timezone.utc) - timedelta(hours=2)
    recent = ctx.db.scalars(select(Message).where(Message.role == "trinetra", Message.created_at >= since)
                            .order_by(Message.id.desc()).limit(6)).all()
    caring = 0
    for m in recent:  # consecutive caring replies, newest first
        if m.mood and ("comfort" in m.mood or "gentle" in m.mood or "no pressure" in m.mood):
            caring += 1
        else:
            break
    ctx.notes["support_stage"] = min(caring, 2) + 1
    text = str(ctx.event.payload.get("text", ""))
    if "?" in text or re.search(r"\b(should i|what do i|what should i)\b", text, re.I):  # "gym or sleep?" — a direct ask
        return ("He asked you something directly while he's low: answer it first, clearly (if he asks you to choose, "
                "choose for him and say why in a few words), kindly — then one gentle line about how he's doing.")
    step = SUPPORT_STEPS[min(caring, 2)]
    if now_local().hour < 5 or now_local().hour >= 23:  # the middle of the night: short, calming, protect his sleep
        step += (" It's the middle of the night: keep it short and include one tiny calming step (a slow breath out, or "
                 "writing the worry down for the morning), and nudge him gently towards sleep.")
    return step


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
        mood = mood_modes.apply(ctx.db, felt, ctx.notes.get("expression_label"))

    history = ctx.db.scalars(select(Message).order_by(Message.id.desc()).limit(12)).all()
    context = _today_context(ctx)
    if (step := support_step(ctx)) is not None:
        context += "\n" + step
    from app.core import briefing
    if reports := briefing.as_text(ctx.notes.get("briefing") or []):
        context += "\n" + reports
    if intent == "planning" and not ctx.notes.get("timetable_changes") and not ctx.notes.get("deliberation"):
        context += ("\nNothing in the timetable changed for this message. You CAN edit his timetable, so never say you "
                    "can't. If he asked for a change you didn't make, say what's missing (e.g. there's no gym block "
                    "tomorrow) and offer to add or move it.")
    if until := ctx.notes.get("quieter_until"):
        context += (f"\nHe asked you to back off, so you just turned your OPTIONAL nudges (check-in extras, streak cheers, "
                    f"behind-schedule talks, your own ideas) off until {until}. Reminders he set himself and his wake-up "
                    "still come. Tell him that in a sentence, without arguing, and that he can say 'nudge me again' anytime.")
    if forgot := ctx.notes.get("forgot"):
        if FORGET_THAT.search(text):
            context += (f"\nHe asked you to forget what he just told you. You put these away for good (they won't come up "
                        f"again): {forgot}. Confirm in one short, warm sentence; don't repeat what it was.")
    if ctx.notes.get("nudges_back"):
        context += "\nYou just turned your optional nudges back on because he asked. Say so in a few words."
    if changes := ctx.notes.get("timetable_changes"):
        context += "\nYou JUST made these timetable changes for them in response to this message. Confirm in a few natural words, like a friend would, e.g. Done, gym's on for 6 every weekday. Use the times EXACTLY as listed here (read each line; don't swap them), and say you did it — never that it was already that way:\n"
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
    if coach := ctx.notes.get("coach"):
        mode = coach["mode"]
        if mode == "quiz":
            context += (f"\nThey asked for a quiz. Ask EXACTLY this question about '{coach['topic']}', nothing else "
                        f"(one short lead-in at most): {coach['question']}")
        elif mode == "graded":
            verdict = "gave up" if coach["gave_up"] else ("got it right" if coach["correct"] else "got it wrong")
            context += (f"\nThat message was their answer to your quiz question on '{coach['topic']}' ({coach['question']}). "
                        f"They {verdict}. Feedback to give: {coach.get('feedback') or 'the key points: ' + '; '.join(coach['key_points'])}. "
                        f"Tell them in two or three sentences; mention you'll ask about it again on {coach['next']}.")
        elif mode == "explain":
            context += (f"\nTeach them '{coach['topic']}' like a great tutor, spoken: the intuition first, one tiny "
                        "example, then the time/space complexity if it applies. Under 150 words, no code blocks.")
        elif mode == "nothing_yet":
            context += "\nThey asked for a quiz, but nothing they've studied is due for review yet (topics come up a day after they tick them). Say so and suggest one to study."
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
    if wanted := ctx.notes.get("show"):  # a dance, a tune, a little move: just its name, the character does the rest
        from app.core import show
        reply = show.label(wanted)
        ctx.db.add(Message(role="user", content=text, channel=channel))
        ctx.db.add(Message(role="trinetra", content=reply, channel=channel, mood=mood, meta={"kind": "show", "show": wanted}))
        return AgentResult(reply=reply, mood=mood)
    if perform := ctx.notes.get("perform"):  # "show me your emotions": just the names, while the face acts them out
        reply = " · ".join(EMOTION_LABEL[e] for e in perform)
        ctx.db.add(Message(role="user", content=text, channel=channel))
        ctx.db.add(Message(role="trinetra", content=reply, channel=channel, mood=mood, meta={"kind": "perform", "perform": perform}))
        return AgentResult(reply=reply, mood=mood)
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
        sensitive = bool(ctx.notes.get("distress")) or ctx.notes.get("expression_label") in ("comforting", "gentle") \
            or bool((ctx.notes.get("felt") or {}).get("low"))  # his feelings stay with providers that don't train on them
        reply = humanize(await llm.complete(messages, tier="smart", reasoning="low", sensitive=sensitive))  # conversation: fast > deep
    except llm.LLMUnavailable as e:
        reply = str(e) if not ctx.settings.llm_available else (
            "I'm having trouble thinking right now — my model providers are busy. Try me again in a minute."
        )
        if ctx.notes.get("distress"):  # never "try again later" to someone in crisis
            reply = "I'm here, and I'm not going anywhere. What you're feeling matters."
    if changes := ctx.notes.get("timetable_changes"):
        reply = _true_to_changes(reply, changes)
    if ctx.notes.get("distress") and "988" not in reply:  # a real way to get help, every time — not left to the model
        reply += "\n\n" + CRISIS_LINE

    ctx.db.add(Message(role="user", content=text, channel=channel))
    ctx.db.add(Message(role="trinetra", content=reply, channel=channel, mood=mood))
    if proposal := ctx.notes.get("proposal"):
        ctx.db.add(Message(role="trinetra", content=proposal["content"], channel=channel, mood=mood,
                           meta=proposal["meta"]))
    return AgentResult(reply=reply, mood=mood)
