"""Mentor & Emotion council: reading your mood, and TRINETRA's own feelings."""
import json
import logging
import re

from app.core import emotion, llm
from app.core.orchestrator import AgentContext
from app.core.registry import agent
from app.db.models import Task

log = logging.getLogger("trinetra.emotion")

EMPATHY_PROMPT = """Read the emotional state of the person who wrote this message to their mentor.
Return JSON only: {"mood": one of ["neutral","happy","excited","proud","motivated","grateful","sad","low",
"tired","stressed","anxious","lonely","overwhelmed","hurt","frustrated","angry","bored"],
"intensity": 0.0-1.0, "distress": true only for hopelessness, self-harm, or crisis}"""

# Used when the LLM is unavailable.
FALLBACK = [
    ("sad", re.compile(r"\b(sad|low|down|crying|depressed|lonely|hurt|heartbroken)\b", re.I)),
    ("tired", re.compile(r"\b(tired|exhausted|sleepy|drained|burn(t|ed) out)\b", re.I)),
    ("stressed", re.compile(r"\b(stressed|anxious|overwhelmed|panic|pressure)\b", re.I)),
    ("happy", re.compile(r"\b(happy|great|awesome|excited|amazing|proud)\b", re.I)),
]


@agent("empathy_detector")
async def empathy_detector(ctx: AgentContext) -> None:
    text = str(ctx.event.payload.get("text", "")).strip()
    if len(text) < 3 or ctx.event.payload.get("button"):
        return
    mood, intensity, distress = "neutral", 0.0, False
    try:
        if not ctx.settings.llm_available:
            raise llm.LLMUnavailable("offline")
        raw = await llm.complete(
            [{"role": "system", "content": EMPATHY_PROMPT}, {"role": "user", "content": text}],
            tier="fast", temperature=0, max_tokens=200, json_mode=True,
        )
        data = json.loads(raw)
        mood = str(data.get("mood", "neutral")).lower()
        intensity = min(max(float(data.get("intensity") or 0), 0.0), 1.0)
        distress = bool(data.get("distress"))
    except (llm.LLMUnavailable, json.JSONDecodeError, ValueError, TypeError, AttributeError):
        for name, pattern in FALLBACK:
            if pattern.search(text):
                mood, intensity = name, 0.6
                break
    ctx.notes["user_mood"], ctx.notes["user_mood_intensity"] = mood, intensity
    if distress:
        ctx.notes["distress"] = True


@agent("emotion_engine")
async def emotion_engine(ctx: AgentContext) -> None:
    state = emotion.decay(emotion.load(ctx.db))
    priority = 3
    if task_id := ctx.event.payload.get("task_id"):
        if task := ctx.db.get(Task, task_id):
            priority = task.priority
    if not ctx.event.payload.get("button"):  # a button tap was already counted as its task.* event
        facts = {**ctx.notes, "nag_count": ctx.event.payload.get("count"), "rings": ctx.event.payload.get("rings")}
        emotion.react(state, ctx.event.type, facts, priority, ctx.settings.trinetra_strictness)
    emotion.save(ctx.db, state)
    mood, label = emotion.expression(state, bool(ctx.notes.get("distress")))
    ctx.notes["expression"], ctx.notes["expression_label"] = mood, label
