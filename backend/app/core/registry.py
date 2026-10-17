"""Agent registry.

Agents are *declared* in YAML (agents/<council>.yaml) and *implemented* in Python
(app/agents/*.py via the @agent decorator). A declared agent without an implementation
is "planned": visible in /agents, skipped at dispatch, built in its phase.
"""
from __future__ import annotations

import fnmatch
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import yaml

if TYPE_CHECKING:
    from app.core.orchestrator import AgentContext, AgentResult

Handler = Callable[["AgentContext"], Awaitable["AgentResult | None"]]

_HANDLERS: dict[str, Handler] = {}


def agent(agent_id: str) -> Callable[[Handler], Handler]:
    """Attach a Python implementation to a YAML-declared agent."""

    def register(fn: Handler) -> Handler:
        _HANDLERS[agent_id] = fn
        return fn

    return register


@dataclass
class AgentSpec:
    id: str
    name: str
    council: str
    role: str
    kind: Literal["rule", "ml", "llm"] = "rule"
    tier: Literal["smart", "fast", "none"] = "none"
    triggers: list[str] = field(default_factory=list)
    priority: int = 5  # higher runs first, and wins reply arbitration
    phase: str = "1"
    enabled: bool = True
    builtin: str | None = None  # works inside a core pipeline (e.g. the voice), not through dispatch: where it lives

    @property
    def handler(self) -> Handler | None:
        return _HANDLERS.get(self.id)

    @property
    def status(self) -> str:
        if not self.enabled:
            return "disabled"
        return "active" if self.handler or self.builtin else "planned"

    def listens_to(self, event_type: str) -> bool:
        return any(fnmatch.fnmatchcase(event_type, t) for t in self.triggers)


class Registry:
    def __init__(self, specs: list[AgentSpec], info: dict[str, dict] | None = None):
        self.info = info or {}  # council → {"description", "manager"}
        ids = [s.id for s in specs]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"Duplicate agent ids: {sorted(dupes)}")
        self.specs = {s.id: s for s in specs}

    @classmethod
    def load(cls, agents_dir: Path) -> Registry:
        import app.agents  # noqa: F401  — registers @agent handlers

        specs: list[AgentSpec] = []
        info: dict[str, dict] = {}
        for path in sorted(agents_dir.glob("*.yaml")):
            doc = yaml.safe_load(path.read_text()) or {}
            council = doc.get("council", path.stem)
            info[council] = {"description": doc.get("description", ""), "manager": doc.get("manager")}
            for raw in doc.get("agents", []):
                specs.append(AgentSpec(council=council, **raw))
        return cls(specs, info)

    def for_event(self, event_type: str) -> list[AgentSpec]:
        matched = [s for s in self.specs.values() if s.enabled and s.listens_to(event_type)]
        return sorted(matched, key=lambda s: -s.priority)

    def councils(self) -> dict[str, list[AgentSpec]]:
        out: dict[str, list[AgentSpec]] = {}
        for s in self.specs.values():
            out.setdefault(s.council, []).append(s)
        return out
