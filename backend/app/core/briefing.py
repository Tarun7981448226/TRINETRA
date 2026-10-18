"""The managers' reports: what each team concluded this turn, in one line each, for TRINETRA to decide with.

The org chart is real at run time: every agent's findings (the notes it adds to the blackboard) are credited to its
team, and the team's ★ manager condenses them into one line. TRINETRA (the core orchestrator) then reads ~10 short
reports instead of dozens of raw notes — the tree from "How it works" (n−1 links instead of n(n−1)/2), and Anthropic's
orchestrator–workers pattern: workers report summaries, the lead decides.
"""
from __future__ import annotations

from typing import Any

SKIP = {"timings_ms", "expression", "proactive", "brain", "proposal", "_by_council", "briefing", "trace"}


def _say(key: str, v: Any) -> str | None:
    """One finding in plain words. None = not worth TRINETRA's attention."""
    if v in (None, False, [], {}, ""):
        return None
    if key == "felt":  # the trained reader misses idioms ("I want to give up" → joy): only its low reading is worth passing up
        return f"own reader hears {', '.join(v['emotions']) or v['group']} (he's low)" if v.get("low") else None
    if key == "user_mood":
        return f"he sounds {v}"
    if key == "user_mood_intensity":
        return None
    if key == "expression_label":
        return f"tone to take: {v}"
    if key == "distress":
        return "DISTRESS — drop all pressure"
    if key == "intent":
        return f"he wants: {v}"
    if key == "remembered":
        return f"saved {len(v)} new fact(s)"
    if key == "insights":
        return f"new insight: {v[0]}"
    if key == "timetable_changes":
        return f"changed the timetable ({len(v)} change(s))"
    if key == "deliberation":
        return f"plan review: {v.get('action')}" + (f", concerns: {'; '.join(v.get('findings') or [])}" if v.get("findings") else "")
    if key == "p_complete":
        return f"predicts {round(float(v) * 100)}% chance he finishes the next block" if isinstance(v, (int, float)) else None
    if key == "held_back":
        return f"held back a {v.get('kind')} nudge ({v.get('reason', '')[:80]})"
    if key in ("show", "perform"):
        return f"acting out {v}"
    if key == "mode_changed":
        return f"switched to {v} mode"
    if key == "focus_pick":
        return f"best thing to do now: {v}"
    if key == "goal_created":
        return f"saved goal '{v.get('title')}'"
    if key == "promises_saved":
        return f"noted promise(s): {v}"
    if key in ("stress", "streak", "lag", "habitual_skip", "patterns", "time_estimate", "silent", "focus_guard", "coach",
               "vision_saved", "critic", "decision", "week_analysis", "day_review", "challenges", "pushed_to", "archived_memories", "demo"):
        text = str(v)
        return f"{key.replace('_', ' ')}: {text[:90]}"
    return None


def reports(ctx) -> list[dict]:
    """[{team, manager, line}] for the teams that found something this turn, in org-chart order."""
    by = ctx.notes.get("_by_council") or {}
    reg = ctx.core.registry if ctx.core else None
    out = []
    for council, keys in by.items():
        bits = [b for k in keys if k not in SKIP and (b := _say(k, ctx.notes.get(k)))]
        if not bits:
            continue
        info = (reg.info.get(council) if reg else None) or {}
        mgr = reg.specs.get(info.get("manager")) if reg and info.get("manager") else None
        out.append({"team": council, "manager": mgr.name if mgr else council, "line": "; ".join(dict.fromkeys(bits))})
    return out


def as_text(rows: list[dict]) -> str:
    if not rows:
        return ""
    return ("Your teams' reports this turn (their managers' summaries — weigh them, then decide):\n"
            + "\n".join(f"- {r['manager']} ({r['team'].replace('_', ' ')}): {r['line']}" for r in rows))
