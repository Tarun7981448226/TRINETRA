"""TRINETRA Core: every event flows through here to the agents that care about it.

Agents run in priority order and share a blackboard (`ctx.notes`), so later agents
build on earlier ones (Router tags intent → Core replies with that in mind).
The Arbiter rule is simple: the highest-priority agent that produced a reply speaks.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings
from app.core.registry import AgentSpec, Registry

log = logging.getLogger("trinetra.core")


@dataclass
class IncomingEvent:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    source: str = "api"


@dataclass
class AgentResult:
    reply: str | None = None
    mood: str | None = None
    actions: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class AgentContext:
    event: IncomingEvent
    db: Session
    settings: Settings
    spec: AgentSpec | None = None
    notes: dict[str, Any] = field(default_factory=dict)  # shared blackboard between agents
    core: "Orchestrator | None" = None  # lets an agent convene other agents (e.g. a plan review)


@dataclass
class DispatchResult:
    reply: str | None
    mood: str | None
    spoke: str | None  # which agent's reply won
    ran: list[str]
    actions: list[dict[str, Any]]
    notes: dict[str, Any]


class Orchestrator:
    def __init__(self, registry: Registry, settings: Settings):
        self.registry = registry
        self.settings = settings

    async def dispatch(self, event: IncomingEvent, db: Session, notes: dict[str, Any] | None = None,
                       commit: bool = True) -> DispatchResult:
        """Run every agent listening to `event`. `notes` pre-loads the blackboard (in-memory objects that
        shouldn't go into the event log, e.g. a draft plan under review). A nested review (`commit=False`) leaves
        committing to the request that convened it, so a half-finished outer request is never committed early."""
        from app.core import llm
        if commit:
            llm.load_bench(db)
        ctx = AgentContext(event=event, db=db, settings=self.settings, notes=dict(notes or {}), core=self)
        ran: list[str] = []
        actions: list[dict[str, Any]] = []
        winner: tuple[AgentSpec, AgentResult] | None = None

        for spec in self.registry.for_event(event.type):
            if spec.handler is None:
                continue  # planned agent, not built yet
            ctx.spec = spec
            t0 = time.perf_counter()
            before = {k: id(v) for k, v in ctx.notes.items()}
            if spec.id == "core_orchestrator":  # TRINETRA decides with its managers' reports in hand
                from app.core import briefing
                try:
                    ctx.notes["briefing"] = briefing.reports(ctx)
                except Exception:
                    log.exception("briefing failed")  # never worth losing the reply over
            try:
                result = await spec.handler(ctx)
            except Exception:
                # One broken agent must never take TRINETRA down.
                log.exception("Agent %s failed on %s", spec.id, event.type)
                if not db.is_active:  # a failed flush poisons the session: roll back so the rest (and the commit) still work
                    db.rollback()
                continue
            finally:
                ctx.notes.setdefault("timings_ms", {})[spec.id] = round((time.perf_counter() - t0) * 1000)
                found = [k for k, v in ctx.notes.items() if before.get(k) != id(v) and k not in ("timings_ms", "briefing")]
                if found:  # credit the findings to the agent's team (its manager reports them up)
                    team = ctx.notes.setdefault("_by_council", {}).setdefault(spec.council, [])
                    team += [k for k in found if k not in team]
            ran.append(spec.id)
            if result is None:
                continue
            actions.extend(result.actions)
            if result.reply and winner is None:
                winner = (spec, result)

        if commit:
            llm.save_bench(db)
            db.commit()
        return DispatchResult(
            reply=winner[1].reply if winner else None,
            mood=winner[1].mood if winner else None,
            spoke=winner[0].id if winner else None,
            ran=ran,
            actions=actions,
            notes=ctx.notes,
        )
