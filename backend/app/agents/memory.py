"""Memory council: what TRINETRA keeps about you, permanently."""
import json
import logging

from sqlalchemy import select

from app.core import llm
from app.core.orchestrator import AgentContext, AgentResult
from app.core.registry import agent
from app.db.models import Memory

log = logging.getLogger("trinetra.memory")

KINDS = {"profile", "goal", "habit", "promise", "preference", "person", "health", "event"}

EXTRACT_PROMPT = """You maintain the long-term memory of a personal AI mentor.
Read the user's latest message and pull out facts worth remembering for weeks or months:
who they are, goals, habits, promises they made, preferences, important people, health, key life events.
Ignore small talk, questions, and passing moods (moods are tracked elsewhere).
Do NOT repeat anything already in memory. If a fact updates an existing one, set "replaces" to that id.

Already in memory:
{existing}

Return JSON only: {{"facts": [{{"kind": one of {kinds}, "content": short third-person fact, \
"importance": 1-5, "replaces": id or null}}]}}
Return {{"facts": []}} if nothing is worth remembering."""


@agent("long_term_memory")
async def long_term_memory(ctx: AgentContext) -> None:
    text = str(ctx.event.payload.get("text", "")).strip()
    if len(text) < 8 or not ctx.settings.llm_available:
        return
    existing = ctx.db.scalars(select(Memory).order_by(Memory.id)).all()
    listing = "\n".join(f"{m.id}: ({m.kind}) {m.content}" for m in existing) or "(empty)"
    try:
        raw = await llm.complete(
            [
                {"role": "system", "content": EXTRACT_PROMPT.format(existing=listing, kinds=sorted(KINDS))},
                {"role": "user", "content": text},
            ],
            tier="fast",
            temperature=0,
            max_tokens=600,
            json_mode=True,
        )
        facts = json.loads(raw).get("facts", [])
    except (llm.LLMUnavailable, json.JSONDecodeError, AttributeError) as e:
        log.warning("memory extraction skipped: %s", e)
        return

    by_id = {m.id: m for m in existing}
    saved = []
    for f in facts:
        content = str(f.get("content", "")).strip()
        if not content:
            continue
        kind = f.get("kind") if f.get("kind") in KINDS else "profile"
        importance = min(max(int(f.get("importance") or 3), 1), 5)
        old = by_id.get(f.get("replaces"))
        if old is not None:
            old.content, old.kind, old.importance = content, kind, importance
        else:
            ctx.db.add(Memory(kind=kind, content=content, importance=importance))
        saved.append(content)
    if saved:
        ctx.notes["remembered"] = saved


@agent("journal_agent")
async def journal_agent(ctx: AgentContext) -> AgentResult | None:
    """You wrote in your journal: one warm line back, and the mood goes in the log. The entry itself stays private."""
    from app.agents.emotion import FALLBACK
    from app.agents.planning import _speak_up
    from app.db.models import JournalEntry, MoodEntry

    entry = ctx.db.get(JournalEntry, ctx.event.payload.get("entry_id"))
    if entry is None:
        return None
    mood = next((name for name, pattern in FALLBACK if pattern.search(entry.text)), None)
    if mood:
        ctx.db.add(MoodEntry(mood=mood, intensity=0.6, source="journal"))
    return await _speak_up(
        ctx, instruction=(f"I just wrote this in my private journal: “{entry.text[:1200]}”. Reply with ONE warm, human "
                          "sentence — notice something real in it. Don't summarise it, don't give advice unless I asked."),
        fallback="Thanks for writing that down. It's kept just for you.", mood="warm and caring", keep_mood=True,
        channel="web", meta={"kind": "journal_ack"})
