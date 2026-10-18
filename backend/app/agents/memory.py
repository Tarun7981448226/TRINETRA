"""Memory council: what TRINETRA keeps about you, permanently."""
import json
import logging

from sqlalchemy import select

from app.core import llm
from app.core.orchestrator import AgentContext, AgentResult
from app.core.registry import agent
from app.db.models import Memory

log = logging.getLogger("trinetra.memory")

KINDS = {"profile", "goal", "habit", "promise", "preference", "person", "health", "event", "insight"}

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
    from app.core import recall
    existing = recall.similar(ctx.db, text, k=15)  # only the closest facts — the whole table would blow the token budget
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


REFLECT_PROMPT = """You are the reflective mind of TRINETRA, a personal AI mentor for {name}. Below are things you have learned
about him (with ids) and what he said in the last two days. Like a thoughtful mentor at the end of the day, find at most
3 deeper insights — patterns, causes, what reliably helps him and what hurts him — that should change how you mentor him.
Each must be supported by at least two of the facts or messages (cite the memory ids). Don't restate a single fact; don't
repeat an existing insight unless you'd sharpen it (then give its id in "replaces"). No diagnosis, no judgement.

Facts:
{facts}

Recent messages from him:
{messages}

Return JSON only: {{"insights": [{{"content": one sentence, "evidence": [ids], "replaces": id or null}}]}}"""


@agent("reflector")
async def reflector(ctx: AgentContext) -> None:
    """Generative Agents' reflection: many small memories → a few insights that guide decisions (importance 4)."""
    from datetime import datetime, timedelta, timezone
    from app.core import recall
    from app.db.models import Message
    if not ctx.settings.llm_available:
        return
    mems = recall.live(ctx.db)
    if len(mems) < 4:
        return
    facts = sorted(mems, key=lambda m: (-(m.importance or 3), -m.id))[:80]
    since = datetime.now(timezone.utc) - timedelta(days=2)
    said = ctx.db.scalars(select(Message).where(Message.role == "user", Message.created_at >= since)
                          .order_by(Message.id.desc()).limit(40)).all()
    try:
        raw = await llm.complete([{"role": "user", "content": REFLECT_PROMPT.format(
            name=ctx.settings.trinetra_user_name,
            facts="\n".join(f"{m.id}: ({m.kind}) {m.content}" for m in facts),
            messages="\n".join(f"- {m.content[:200]}" for m in reversed(said)) or "(none)")}],
            tier="smart", temperature=0.3, max_tokens=700, json_mode=True, sensitive=True)  # his whole memory
        insights = json.loads(raw).get("insights", [])
    except (llm.LLMUnavailable, json.JSONDecodeError, AttributeError) as e:
        log.warning("reflection skipped: %s", e)
        return
    by_id = {m.id: m for m in mems}
    known = {m.id for m in mems}
    written = []
    for i in insights[:3]:
        content = str(i.get("content", "")).strip()
        evidence = [e for e in (i.get("evidence") or []) if e in known]
        if not content or len(evidence) < 2:  # an insight needs support, not a hunch
            continue
        old = by_id.get(i.get("replaces"))
        if old is not None and old.kind == "insight":
            old.content = content
        else:
            twin = recall.similar(ctx.db, content, k=1)
            from app.core import embed
            if twin and twin[0].kind == "insight" and float(embed.similarity(content, [twin[0].content])[0]) > 0.9:
                twin[0].content = content
            else:
                ctx.db.add(Memory(kind="insight", content=content, importance=4))
        written.append(content)
    if written:
        ctx.notes["insights"] = written


def _twins(a: str, b: str, cosine: float) -> bool:
    """Only true duplicates merge. Static embeddings rate "gym at 6pm" vs "gym at 7am" 0.82 and "likes" vs "hates" 0.80,
    so meaning alone is not enough: same words (ignoring spaces / punctuation), or near-identical AND the same numbers."""
    import re
    flat = lambda t: re.sub(r"[^a-z0-9]", "", t.lower())
    nums = lambda t: re.findall(r"\d+", t)
    return flat(a) == flat(b) or (cosine > 0.97 and nums(a) == nums(b))


@agent("forgetter")
async def forgetter(ctx: AgentContext) -> None:
    """Keeps memory clean: near-duplicates merge into the more important one; faded trivia is archived (never deleted).
    Retention R = e^(-days / strength) (MemoryBank); archive when R < 0.1 and importance ≤ 2."""
    import math
    from datetime import datetime, timezone
    from app.core import embed, recall
    from app.core.timeutil import from_db
    mems = recall.live(ctx.db)
    if len(mems) < 2:
        return
    vecs = embed.embed([m.content for m in mems])
    gone: set[int] = set()
    for i, a in enumerate(mems):
        if a.id in gone:
            continue
        for j in range(i + 1, len(mems)):
            b = mems[j]
            if b.id in gone or a.kind != b.kind:
                continue
            if _twins(a.content, b.content, float(vecs[i] @ vecs[j])):  # the same fact twice
                keep, drop = (a, b) if (a.importance or 3) >= (b.importance or 3) else (b, a)
                keep.uses = (keep.uses or 0) + (drop.uses or 0)
                drop.archived = True
                gone.add(drop.id)
    now = datetime.now(timezone.utc)
    for m in mems:
        if m.id in gone or (m.importance or 3) > 2 or m.kind in ("profile", "insight"):
            continue
        days = (now - from_db(m.last_used or m.created_at)).total_seconds() / 86400
        if math.exp(-days / (7 * (1 + (m.uses or 0)))) < 0.1:  # strength in weeks: unused trivia fades in ~16 days
            m.archived = True
            gone.add(m.id)
    if gone:
        ctx.notes["archived_memories"] = len(gone)
