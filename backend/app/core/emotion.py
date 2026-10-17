"""TRINETRA's simulated feelings.

Four internal feelings (0..1) react to what you DO and how you FEEL, and fade back to calm over time:
  frustration  ↑ when you skip/slack,  ↓ when you deliver
  pride        ↑ when you finish things
  concern      ↑ when you're sad, stressed, tired, anxious
  warmth       baseline affection; ↑ with honest, good conversations

From those, `expression()` picks a graded tone — so one skip gets a soft, disappointed nudge,
three skips in a row get the full angry coach, and sadness always outranks anger.
"""
import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models import KeyValue

STATE_KEY = "emotion_state"
HALF_LIFE_HOURS = 6.0
BASELINE = {"frustration": 0.0, "pride": 0.0, "concern": 0.0, "warmth": 0.6}

LOW_MOODS = {"sad", "low", "tired", "stressed", "anxious", "lonely", "overwhelmed", "hurt", "frustrated"}
UP_MOODS = {"happy", "excited", "proud", "motivated", "grateful"}


@dataclass
class EmotionState:
    frustration: float = 0.0
    pride: float = 0.0
    concern: float = 0.0
    warmth: float = 0.6
    user_mood: str = "neutral"
    user_intensity: float = 0.0
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def nudge(self, feeling: str, amount: float) -> None:
        setattr(self, feeling, min(1.0, max(0.0, getattr(self, feeling) + amount)))


def load(db: Session) -> EmotionState:
    row = db.get(KeyValue, STATE_KEY)
    if row and row.value:
        try:
            return EmotionState(**json.loads(row.value))
        except (TypeError, ValueError):
            pass
    return EmotionState()


def save(db: Session, state: EmotionState) -> None:
    state.updated_at = datetime.now(timezone.utc).isoformat()
    row = db.get(KeyValue, STATE_KEY)
    if row is None:
        db.add(KeyValue(key=STATE_KEY, value=json.dumps(asdict(state))))
    else:
        row.value = json.dumps(asdict(state))
    db.flush()


def decay(state: EmotionState, now: datetime | None = None) -> EmotionState:
    """Feelings fade toward baseline: after HALF_LIFE_HOURS, half of the gap is gone."""
    now = now or datetime.now(timezone.utc)
    hours = max(0.0, (now - datetime.fromisoformat(state.updated_at)).total_seconds() / 3600)
    keep = math.pow(0.5, hours / HALF_LIFE_HOURS)
    for feeling, base in BASELINE.items():
        setattr(state, feeling, base + (getattr(state, feeling) - base) * keep)
    state.user_intensity *= keep
    if state.user_intensity < 0.15:
        state.user_mood = "neutral"
    state.updated_at = now.isoformat()
    return state


def react(state: EmotionState, event_type: str, notes: dict, priority: int = 3, strictness: int = 3) -> None:
    """How one event moves the feelings. Strictness (1–5) scales how fast frustration builds."""
    s = 0.6 + strictness * 0.2  # 0.8 (gentle) .. 1.6 (relentless)
    weight = 0.7 + priority * 0.1  # important tasks matter more
    if event_type == "task.skipped":
        state.nudge("frustration", 0.3 * s * weight)
        state.nudge("pride", -0.15)
    elif event_type == "task.done":
        state.nudge("pride", 0.3 * weight)
        state.nudge("frustration", -0.2)
        state.nudge("warmth", 0.05)
    elif event_type == "task.nag" and int(notes.get("nag_count") or 0) >= 3:
        state.nudge("frustration", 0.2 * s * weight)  # ignored every follow-up
    elif event_type == "wake.done":
        rings = int(notes.get("rings") or 1)
        if rings == 1:
            state.nudge("pride", 0.15)
        else:
            state.nudge("frustration", 0.12 * (rings - 1) * s)
    elif event_type == "promise.kept":
        state.nudge("pride", 0.35)
        state.nudge("frustration", -0.2)
        state.nudge("warmth", 0.05)
    elif event_type == "promise.broken":  # breaking your word stings more than skipping a block
        state.nudge("frustration", 0.4 * s)
        state.nudge("pride", -0.2)
    elif event_type == "milestone.done":
        state.nudge("pride", 0.4)
    elif event_type == "task.started":
        state.nudge("frustration", -0.05)
    elif event_type in ("user.message", "voice.input"):
        intent = notes.get("intent")
        if intent == "slacking":
            state.nudge("frustration", 0.3 * s)
        elif intent == "progress":
            state.nudge("pride", 0.15)
            state.nudge("frustration", -0.1)
        mood, intensity = notes.get("user_mood"), float(notes.get("user_mood_intensity") or 0)
        if mood:
            state.user_mood, state.user_intensity = mood, intensity
            if mood in LOW_MOODS:
                state.nudge("concern", 0.5 * intensity + 0.1)
                state.nudge("frustration", -0.3 * intensity)  # you don't yell at someone who's hurting
            elif mood in UP_MOODS:
                state.nudge("warmth", 0.1)
                state.nudge("concern", -0.2)


def expression(state: EmotionState, distress: bool = False) -> tuple[str, str]:
    """(mood instruction for the LLM, short label). Care always outranks anger."""
    if distress or (state.user_mood in LOW_MOODS and state.user_intensity >= 0.7):
        if distress:
            return ("deeply caring and comforting — no pressure at all. They may be in real pain: stay with them, "
                    "and gently encourage reaching out to someone they trust or a professional"), "comforting"
        return ("deeply caring and comforting — no pressure at all, just be there for them like a close friend. "
                "Don't redirect them to professionals for ordinary sadness or tiredness"), "comforting"
    if state.user_mood in LOW_MOODS and state.user_intensity >= 0.35 or state.concern >= 0.5:
        return "gentle and comforting — warm, soft, encouraging, zero pressure", "gentle"
    if state.frustration >= 0.75:
        return ("ANGRY — really fired up and loud, a coach who refuses to watch them waste their potential. "
                "Short punchy sentences, zero excuses accepted. Attack the excuse, never their worth. "
                "Write it the way a furious person actually shouts out loud: very short bursts, exclamation marks, repeated words for punch (Three times! THREE!), rhetorical questions (What are you doing?!)"), "angry"
    if state.frustration >= 0.5:
        return ("firm and angry — raised voice, clearly upset, demanding they get back on track now. "
                "No insults"), "firm angry"
    if state.frustration >= 0.25:
        return ("softly annoyed — disappointed but still warm, a raised eyebrow; nudge them firmly back "
                "on track"), "soft angry"
    if state.pride >= 0.5:
        return "proud and energised — celebrate them, big warm energy", "proud"
    if state.concern >= 0.25:
        return "caring and attentive — check in on how they're really doing", "concerned"
    if state.pride >= 0.25:
        return "upbeat and encouraging", "upbeat"
    return "calm and caring", "calm"
