"""TRINETRA's own judgement: should it speak up right now, or hold back?

Reminders he set, wake-ups, alerts, plans and reports always go out. The *optional* nudges — a check-in in free time,
a water / break nudge, a streak cheer, a "you're behind" talk, a reminder of his why — are decisions, and they're made
the way a good mentor makes them: is it worth saying, will he take it well, and has he heard enough from me today?

    score = value(kind) × P(he engages | kind) − interruption cost

  • value: how much the nudge can help (wellbeing and lag matter more than a casual check-in).
  • P(engage): learned from him. Every sent nudge is settled 30 minutes later — engaged if he answered (a message or a
    tap), ignored if not — and P = (engaged + 1.5) / (sent + 2): a slightly optimistic Beta prior, so a new kind gets a
    fair try, and a kind he keeps ignoring fades out (bandit learning, as in the Proactive Agent work: proactive help is
    only good when the user accepts it).
  • cost: 0.12 for every optional nudge of another kind in the last 3 hours (don't pile up different nudges; each watcher
    already paces its own kind), and a daily budget of 10 (free-time check-ins alone can be 6 on an empty afternoon).
  • when he's low (the Emotion Engine says comforting / gentle), wellbeing nudges are always allowed.
  • exploration: after 5 holds in a row for a kind, one goes out anyway, so a habit he's changed can be noticed.
Held decisions are logged with their reason (GET /autonomy shows the policy), so the "why" is never hidden.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Decision, Message

VALUE = {"wellbeing": 0.8, "lag": 0.75, "why": 0.6, "streak": 0.5, "free_checkin": 0.45}
OPTIONAL = set(VALUE)
THRESHOLD = 0.15
DAILY_BUDGET = 10
COST_PER_RECENT = 0.12
SETTLE_AFTER = timedelta(minutes=30)
EXPLORE_AFTER = 5


@dataclass
class Verdict:
    send: bool
    score: float
    reason: str


def _now() -> datetime:
    return datetime.now(timezone.utc)


def engagement(db: Session, kind: str, days: int = 30) -> tuple[int, int]:
    """(engaged, settled) for this kind over the last `days`."""
    since = _now() - timedelta(days=days)
    rows = db.execute(select(Decision.outcome, func.count()).where(Decision.kind == kind, Decision.action == "sent",
                                                                   Decision.outcome.is_not(None), Decision.created_at >= since)
                      .group_by(Decision.outcome)).all()
    got = dict(rows)
    return got.get("engaged", 0), got.get("engaged", 0) + got.get("ignored", 0)


def p_engage(db: Session, kind: str) -> float:
    engaged, n = engagement(db, kind)
    return (engaged + 1.5) / (n + 2)


def decide(db: Session, kind: str, label: str | None = None) -> Verdict:
    now = _now()
    sent_since = lambda t, *where: db.scalar(select(func.count()).select_from(Decision).where(
        Decision.action == "sent", Decision.created_at >= t, *where)) or 0
    today = sent_since(now - timedelta(hours=24))
    # other kinds only: each watcher already paces its own kind (e.g. the 30-minute free-time check-in Tarun asked for)
    recent = sent_since(now - timedelta(hours=3), Decision.kind != kind)
    p = p_engage(db, kind)
    value = VALUE.get(kind, 0.5)
    score = value * p - COST_PER_RECENT * recent
    why = f"value {value:.2f} × P(engage) {p:.2f} − {recent} recent nudge(s) = {score:.2f}"
    if kind == "wellbeing" and label in ("comforting", "gentle"):
        return Verdict(True, max(score, THRESHOLD), "he's low — care always gets through · " + why)
    if today >= DAILY_BUDGET:
        return Verdict(False, score, f"daily budget used ({today}/{DAILY_BUDGET}) · " + why)
    if score >= THRESHOLD:
        return Verdict(True, score, why)
    last = db.scalars(select(Decision.action).where(Decision.kind == kind).order_by(Decision.id.desc())
                      .limit(EXPLORE_AFTER)).all()
    if len(last) == EXPLORE_AFTER and all(a == "held" for a in last):
        return Verdict(True, score, f"held {EXPLORE_AFTER} times in a row — trying once to see if he's changed · " + why)
    return Verdict(False, score, "not worth interrupting him · " + why)


def record(db: Session, kind: str, v: Verdict, message_id: int | None = None) -> Decision:
    d = Decision(kind=kind, action="sent" if v.send else "held", score=round(v.score, 3), reason=v.reason[:500],
                 message_id=message_id)
    db.add(d)
    db.flush()
    return d


def settle(db: Session, now: datetime | None = None) -> int:
    """Sent nudges older than 30 minutes: did he answer? Every one settled teaches the policy."""
    from app.core.timeutil import from_db
    now = now or _now()
    open_ = db.scalars(select(Decision).where(Decision.action == "sent", Decision.outcome.is_(None),
                                              Decision.created_at <= now - SETTLE_AFTER)).all()
    for d in open_:
        t0 = from_db(d.created_at)
        answered = db.scalar(select(func.count()).select_from(Message).where(
            Message.role == "user", Message.created_at > t0, Message.created_at <= t0 + SETTLE_AFTER)) or 0
        d.outcome = "engaged" if answered else "ignored"
    return len(open_)


def policy(db: Session) -> dict:
    """What it has learned, for the app (and for Tarun to check its judgement)."""
    kinds = []
    for k in sorted(VALUE, key=lambda k: -VALUE[k]):
        engaged, n = engagement(db, k)
        kinds.append({"kind": k, "value": VALUE[k], "p_engage": round(p_engage(db, k), 2), "engaged": engaged, "settled": n})
    recent = db.scalars(select(Decision).order_by(Decision.id.desc()).limit(15)).all()
    return {"threshold": THRESHOLD, "daily_budget": DAILY_BUDGET, "kinds": kinds,
            "recent": [{"kind": d.kind, "action": d.action, "outcome": d.outcome, "reason": d.reason,
                        "at": d.created_at.isoformat() if d.created_at else None} for d in recent]}
