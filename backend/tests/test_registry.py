import pytest

from app.config import get_settings
from app.core.registry import AgentSpec, Registry


def test_all_councils_load():
    reg = Registry.load(get_settings().agents_dir)
    assert len(reg.specs) >= 64
    assert len(reg.councils()) == 10
    for spec in reg.specs.values():
        assert spec.triggers, f"{spec.id} listens to nothing"


def test_phase1_agents_are_active():
    reg = Registry.load(get_settings().agents_dir)
    for agent_id in ("data_collector", "router", "core_orchestrator"):
        assert reg.specs[agent_id].status == "active"


def test_wildcard_triggers_and_priority_order():
    reg = Registry(
        [
            AgentSpec(id="a", name="A", council="x", role="", triggers=["task.*"], priority=1),
            AgentSpec(id="b", name="B", council="x", role="", triggers=["*"], priority=9),
            AgentSpec(id="c", name="C", council="x", role="", triggers=["mail.received"]),
        ]
    )
    assert [s.id for s in reg.for_event("task.skipped")] == ["b", "a"]


def test_duplicate_ids_rejected():
    spec = AgentSpec(id="dup", name="D", council="x", role="", triggers=["*"])
    with pytest.raises(ValueError):
        Registry([spec, spec])
