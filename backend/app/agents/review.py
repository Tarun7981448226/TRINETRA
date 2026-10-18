"""Plan review board: every timetable change is examined before it happens (event: plan.proposed).

Order (by priority): Sleep Guardian 70 → Completion Predictor 55 → Buffer Manager 45 → Deadline Tracker 40
→ Critic 20 (reasons over everyone's findings) → Arbiter 15 (decides: act / act on a safer version / ask).
"""
import json
import logging

from app.core import deliberation, llm
from app.core.orchestrator import AgentContext, IncomingEvent
from app.core.registry import agent
from app.core.timeutil import local, now_local

log = logging.getLogger("trinetra.review")

CRITIC_PROMPT = """You are TRINETRA's Critic. The user asked to change their timetable. Your job: think it through
like a sharp chief-of-staff before anything is changed.

Now: {now} ({weekday}). User's request: "{request}"
Proposed operations (JSON): {ops}
What the change does: {summary}
Problems the review agents found:
{findings}
Their schedule around those days:
{schedule}
Sleep window: {sleep}.

Decide:
- "ok": the concerns are minor — do it as asked.
- "adjust": a small change fixes the problems while keeping what they want (shift a time, shorten a block, add a
  break, pick a nearby free slot). Return the FULL corrected ops list in the same schema.
- "ask": it's a real trade-off only they can decide (e.g. they explicitly want to cut sleep, or there's no good slot).
Never invent block ids. Keep recurrence as given unless it is the problem.
Return JSON only: {{"verdict": "ok"|"adjust"|"ask", "reasoning": "1-2 short spoken sentences explaining your
thinking to them", "ops": [...] (only for adjust), "question": "one short question" (only for ask)}}"""


def _proposal(ctx: AgentContext) -> deliberation.Proposal | None:
    return ctx.notes.get("proposal") if ctx.event.type == "plan.proposed" else None


def _add(ctx: AgentContext, findings: list[deliberation.Finding]) -> None:
    ctx.notes.setdefault("findings", []).extend(findings)


@agent("sleep_guardian")
async def sleep_guardian(ctx: AgentContext) -> None:
    if p := _proposal(ctx):
        _add(ctx, deliberation.check_sleep(ctx.db, p))


@agent("buffer_manager")
async def buffer_manager(ctx: AgentContext) -> None:
    if p := _proposal(ctx):
        _add(ctx, deliberation.check_buffers(ctx.db, p))


@agent("deadline_tracker")
async def deadline_tracker(ctx: AgentContext) -> None:
    if p := _proposal(ctx):
        _add(ctx, deliberation.check_goals(p))


@agent("critic")
async def critic(ctx: AgentContext) -> None:
    p = _proposal(ctx)
    findings = [f for f in ctx.notes.get("findings", []) if f.severity in ("block", "warn")]
    if p is None or not findings or ctx.notes.get("no_critic") or not ctx.settings.llm_available:
        return
    s_start, s_end = deliberation.sleep_window(ctx.db)
    around = deliberation._existing(ctx.db, p)
    now = now_local()
    prompt = CRITIC_PROMPT.format(
        now=f"{now:%Y-%m-%d %H:%M}", weekday=f"{now:%A}", request=ctx.notes.get("request", ""),
        ops=json.dumps(p.ops), summary="; ".join(p.describe()),
        findings="\n".join(f"- [{f.severity}] {f.message}" for f in findings),
        schedule="\n".join(f"- #{t.id} {local(t.planned_start):%a %d %H:%M}–{local(t.planned_end):%H:%M} {t.title}"
                           for t in sorted(around, key=lambda t: t.planned_start)[:40]) or "(nothing else)",
        sleep=f"{s_start:%H:%M}–{s_end:%H:%M}",
    )
    try:
        raw = await llm.complete([{"role": "system", "content": prompt}, {"role": "user", "content": "Decide."}],
                                 tier="smart", temperature=0, max_tokens=2500, json_mode=True)
        verdict = json.loads(raw)
    except (llm.LLMUnavailable, json.JSONDecodeError, ValueError) as e:
        log.warning("critic unavailable: %s", e)
        return
    if verdict.get("verdict") in ("ok", "adjust", "ask"):
        ctx.notes["critic"] = verdict


@agent("arbiter")
async def arbiter(ctx: AgentContext) -> None:
    """Final call. Hard problems (sleep, clashes) are never applied silently."""
    p = _proposal(ctx)
    if p is None:
        return
    findings = ctx.notes.get("findings", [])
    blocks = [f for f in findings if f.severity == "block"]
    warns = [f for f in findings if f.severity == "warn"]
    verdict = ctx.notes.get("critic") or {}
    decision = {"ops": p.ops, "original_ops": p.ops, "reasoning": verdict.get("reasoning", ""),
                "question": verdict.get("question", ""), "findings": [f.message for f in blocks + warns],
                "summary": p.describe()}

    if ctx.notes.get("no_critic"):  # this is a re-check of the Critic's fix: just report
        decision["action"] = "ask" if blocks else "apply"
    elif p.is_big:
        decision["action"] = "ask"  # a whole new schedule: you see it before it goes live
        if verdict.get("verdict") == "adjust" and verdict.get("ops"):
            decision["ops"] = verdict["ops"]
    elif not blocks and not warns:
        decision["action"] = "apply"
    elif verdict.get("verdict") == "adjust" and verdict.get("ops") and ctx.core is not None:
        fixed = deliberation.build(ctx.db, verdict["ops"])
        recheck = await ctx.core.dispatch(
            IncomingEvent("plan.proposed", {"request": "critic re-check", "ops_count": len(fixed.ops)}, "critic"),
            ctx.db, notes={"proposal": fixed, "no_critic": True}, commit=False,
        )
        still = [f for f in recheck.notes.get("findings", []) if f.severity == "block"]
        decision["ops"] = fixed.ops
        decision["action"] = "apply_adjusted" if not still else "ask"
        if still:
            decision["findings"] += [f.message for f in still]
    elif verdict.get("verdict") == "ok" and not blocks:
        decision["action"] = "apply"
    else:
        decision["action"] = "ask"
    ctx.notes["decision"] = decision
