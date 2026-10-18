"""The Communications team's WhatsApp agents. The bridge (bridge/ on Render) sends events; these decide.

whatsapp.received {message_id}:  Listener (route) → Contact Profiler → Replier (draft in his style) → Confidence Judge
whatsapp.activity:               Presence Watcher (he's on WhatsApp → the session pauses)
user.message:                    Presence Watcher ("I'm busy for 2 hours", "I'm back")
cron.nightly:                    Reply Style Learner (rebuilds how he writes)
"""
import re
from datetime import datetime, timedelta

from app.core import whatsapp
from app.core.orchestrator import AgentContext, AgentResult
from app.core.registry import agent
from app.core.timeutil import local, now_local, to_utc
from app.db.models import WaContact, WaMessage

BUSY = re.compile(
    r"\b(?:i'?m|i am|im|i'?ll be|i will be|gonna be|going to be)\s+(?:busy|in (?:a |my )?(?:meeting|class|lecture|exam|interview)|"
    r"(?:in |doing )?deep (?:work|research|focus)|researching|studying|heads?[- ]down|driving|offline)\b", re.I)
HANDLE = re.compile(r"\b(?:handle|take care of|look after|manage|answer|reply to)\s+(?:my\s+)?(?:whatsapp|wa|messages|chats|texts)\b", re.I)
FOR = re.compile(r"\bfor\s+(?:the next\s+)?(half an hour|an?|one|two|three|\d+(?:\.\d+)?)\s*(h|hrs?|hours?|m|mins?|minutes?)\b", re.I)
TILL = re.compile(r"\b(?:till|until|untill|til|upto|up to)\s+(tonight|(\d{1,2})(?::(\d{2}))?\s*(am|pm)?)\b", re.I)
BACK = re.compile(r"^\s*(?:i'?m|im|i am)\s+(?:back|free|done|online)(?:\s+now)?\b|\bstop (?:handling|replying to|answering) (?:my )?(?:whatsapp|messages)\b", re.I)
WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3}


def busy_until(text: str, now: datetime | None = None) -> datetime | None:
    """ "I'm in deep research for 2 hours" / "handle my WhatsApp till 5pm" → when it ends (UTC). None if it isn't that."""
    asked = HANDLE.search(text)
    busy = BUSY.search(text)
    f, t = FOR.search(text), TILL.search(text)
    if not (asked or (busy and (f or t))):  # "I'm busy with DSA" alone is just chat, not a WhatsApp request
        return None
    now = now or now_local()
    if f:
        n = 0.5 if f.group(1).lower() == "half an hour" else WORDS.get(f.group(1).lower()) or float(f.group(1))
        unit = f.group(2).lower()
        return to_utc(now + (timedelta(hours=n) if unit.startswith("h") or f.group(1).lower() == "half an hour" else timedelta(minutes=n)))
    if t:
        if t.group(1).lower() == "tonight":
            return whatsapp.until_for("busy_tonight")
        h, mi, ap = int(t.group(2)), int(t.group(3) or 0), (t.group(4) or "").lower()
        h = h % 12 + 12 if ap == "pm" else h % 12 if ap == "am" else (h + 12 if h < 8 else h)  # "till 5" = 17:00
        end = now.replace(hour=h % 24, minute=mi, second=0, microsecond=0)
        if end <= now:
            end += timedelta(days=1)
        return to_utc(end)
    return to_utc(now + timedelta(hours=1))  # "handle my WhatsApp": an hour unless he says


@agent("presence_watcher")
async def presence_watcher(ctx: AgentContext) -> AgentResult | None:
    if ctx.event.type == "whatsapp.activity":
        when = ctx.event.payload.get("at")
        s = whatsapp.mark_active(ctx.db, datetime.fromisoformat(when) if when else None)
        if s is not None:
            ctx.notes["wa_paused"] = True
        return None
    text = (ctx.event.payload.get("text") or "").strip()
    if not text or not whatsapp.configured() or ctx.event.payload.get("button"):
        return None
    if BACK.search(text) and (s := whatsapp.current(ctx.db)):
        ctx.notes["wa_session_ended"] = whatsapp.end(ctx.db, s, "you're back") or "nothing happened on WhatsApp"
        return None
    if (until := busy_until(text)) is not None:
        whatsapp.start(ctx.db, until)
        ctx.notes["wa_session_until"] = f"{local(until):%-I:%M %p}"
        await whatsapp.catch_up(ctx.db)
    return None


@agent("whatsapp_listener")
async def whatsapp_listener(ctx: AgentContext) -> AgentResult | None:
    m = ctx.db.get(WaMessage, ctx.event.payload.get("message_id"))
    if m is None or m.from_me:
        return None
    ctx.notes["wa_route"] = whatsapp.route(ctx.db, m)
    return None


@agent("contact_profiler")
async def contact_profiler(ctx: AgentContext) -> AgentResult | None:
    m = ctx.db.get(WaMessage, ctx.event.payload.get("message_id"))
    c = m and ctx.db.get(WaContact, m.jid)
    if c is not None:
        from datetime import timezone
        c.updated_at = datetime.now(timezone.utc)  # who he talks to most recently comes first in the app
        ctx.notes["wa_contact"] = {"name": whatsapp.who(c), "known": c.known, "auto_ok": c.auto_ok}
    return None


@agent("whatsapp_replier")
async def whatsapp_replier(ctx: AgentContext) -> AgentResult | None:
    if ctx.notes.get("wa_route") != "session":
        return None
    m = ctx.db.get(WaMessage, ctx.event.payload.get("message_id"))
    ctx.notes["wa_draft"] = await whatsapp.triage(ctx.db, m)
    return None


@agent("confidence_judge")
async def confidence_judge(ctx: AgentContext) -> AgentResult | None:
    if (t := ctx.notes.get("wa_draft")) is None:
        return None
    m = ctx.db.get(WaMessage, ctx.event.payload.get("message_id"))
    s = whatsapp.current(ctx.db)
    if s is None:  # the session ended a moment ago
        m.handled = "pending"
        return None
    ctx.notes["wa_did"] = whatsapp.act(ctx.db, m, s, t)
    return None


@agent("reply_style_learner")
async def reply_style_learner(ctx: AgentContext) -> AgentResult | None:
    from app.core import style
    learned = style.learn(ctx.db)
    ctx.notes["style_learned"] = (learned.get("overall") or {}).get("n", 0)
    return None
