"""Which memories matter right now.

Retrieval as in Generative Agents (Park et al., 2023): every memory gets
    score = recency + importance + relevance,
each min-max scaled to [0, 1] over the candidates, and the top k go into the prompt. Here:
  • relevance  = cosine similarity of the memory to the conversation (core/embed.py — computed locally, private);
  • importance = the 1–5 the memory agent gave it;
  • recency    = 0.998 ^ (hours since it was last used / strength). 0.998/h is a ~14-day half-life for a real person
                 (the paper's 0.995 was per game-hour). strength = 1 + times recalled — MemoryBank's Ebbinghaus idea:
                 what keeps coming up is forgotten more slowly.
A few core profile facts are always included (who he is shouldn't depend on today's topic). Recalling a memory
"touches" it (last_used, uses), so the ranking learns what actually matters to him.
"""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core import embed
from app.core.timeutil import from_db
from app.db.models import Memory

DECAY = 0.998
K = 12
CORE = 5  # always-present profile facts (importance ≥ 4)


def _scaled(x: np.ndarray) -> np.ndarray:
    lo, hi = float(x.min()), float(x.max())
    return (x - lo) / (hi - lo) if hi > lo else np.zeros_like(x)


def live(db: Session) -> list[Memory]:
    return list(db.scalars(select(Memory).where(or_(Memory.archived.is_(None), Memory.archived.is_(False)))
                           .order_by(Memory.id)).all())


def scores(mems: list[Memory], query: str, now: datetime | None = None) -> np.ndarray:
    if not mems:
        return np.zeros(0)
    now = now or datetime.now(timezone.utc)
    hours = np.array([max(0.0, (now - from_db(m.last_used or m.created_at)).total_seconds() / 3600) for m in mems])
    strength = np.array([1 + (m.uses or 0) for m in mems], dtype=float)
    recency = DECAY ** (hours / strength)
    importance = np.array([(min(max(m.importance or 3, 1), 5) - 1) / 4 for m in mems])
    relevance = embed.similarity(query, [m.content for m in mems]) if query.strip() else np.zeros(len(mems))
    return _scaled(recency) + _scaled(importance) + _scaled(relevance) * 1.5  # what he's talking about weighs a bit more


def recall(db: Session, query: str, k: int = K, touch: bool = True) -> list[Memory]:
    """The memories to bring into this conversation, most useful first."""
    mems = live(db)
    if len(mems) <= k:
        chosen = sorted(mems, key=lambda m: -(m.importance or 3))
    else:
        s = scores(mems, query)
        core = sorted((m for m in mems if m.kind == "profile" and (m.importance or 3) >= 4),
                      key=lambda m: -(m.importance or 3))[:CORE]
        ranked = [mems[i] for i in np.argsort(-s)]
        chosen = core + [m for m in ranked if m not in core][: max(0, k - len(core))]
    if touch:
        now = datetime.now(timezone.utc)
        for m in chosen:
            m.last_used, m.uses = now, (m.uses or 0) + 1
    return chosen


def similar(db: Session, text: str, k: int = 12) -> list[Memory]:
    """Existing memories closest in meaning to `text` (for de-duplicating / updating facts — Mem0's idea)."""
    mems = live(db)
    if len(mems) <= k:
        return mems
    sim = embed.similarity(text, [m.content for m in mems])
    return [mems[i] for i in np.argsort(-sim)[:k]]
