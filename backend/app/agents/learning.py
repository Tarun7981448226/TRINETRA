"""Learning council: the neural core predicts, the trainer keeps it learning, and your history gets read."""
from datetime import datetime, timezone

from app.core.orchestrator import AgentContext
from app.core.registry import agent
from app.core.timeutil import from_db, local
from app.db.models import Task
from app.ml import insights, neural_core


@agent("completion_predictor")
async def completion_predictor(ctx: AgentContext) -> None:
    """Before a reminder goes out (or a plan is accepted): how likely are you to actually do this?"""
    if ctx.event.type == "plan.proposed" and (p := ctx.notes.get("proposal")):
        from app.core import deliberation
        ctx.notes.setdefault("findings", []).extend(deliberation.check_odds(ctx.db, p))
        return
    task = ctx.db.get(Task, ctx.event.payload.get("task_id"))
    if task is not None:
        ctx.notes["p_complete"] = round(neural_core.predict(ctx.db, task), 2)


@agent("model_trainer")
async def model_trainer(ctx: AgentContext) -> None:
    report = neural_core.train(ctx.db)
    ctx.notes["brain"] = report.__dict__


# ---------- what your history says (app/ml/insights.py) ----------


@agent("duration_model")
async def duration_model(ctx: AgentContext) -> None:
    """A block you started and finished: how long it really took vs planned, per kind of block."""
    insights.save(ctx.db, durations=insights.durations(ctx.db, datetime.now(timezone.utc)))


@agent("time_estimator")
async def time_estimator(ctx: AgentContext) -> None:
    """A new one-off block planned shorter (or longer) than you really need → offer the realistic length."""
    from app.core import planner

    task = ctx.db.get(Task, ctx.event.payload.get("task_id"))
    if task is None or task.recurrence or from_db(task.planned_start) < datetime.now(timezone.utc):
        return
    d = (insights.load(ctx.db).get("durations") or {}).get(insights.kind(task))
    if not d or d["n"] < 5 or abs(d["ratio"] - 1) < 0.25:
        return
    planned = (from_db(task.planned_end) - from_db(task.planned_start)).total_seconds() / 60
    better = max(15, round(planned * d["ratio"] / 5) * 5)
    s = local(task.planned_start)
    op = {"op": "move", "id": task.id, "date": s.date().isoformat(), "start": s.strftime("%H:%M"), "duration_min": better}
    ctx.notes["time_estimate"] = {"planned": round(planned), "suggested": better, "ratio": d["ratio"]}
    planner.propose(ctx.db, [op], f"Your {insights.kind(task)} blocks usually take {d['ratio']}× what's planned "
                                  f"(last {d['n']}). '{task.title}' is {round(planned)} min — make it {better}?")


@agent("energy_curve_model")
async def energy_curve_model(ctx: AgentContext) -> None:
    """Nightly: done-rate by time of day → your peak and slump hours."""
    now = datetime.now(timezone.utc)
    insights.save(ctx.db, energy=insights.energy(insights._finished(ctx.db, now)))


@agent("procrastination_detector")
async def procrastination_detector(ctx: AgentContext) -> None:
    """Nightly: which blocks you skip most, and on which day. A skip that fits the pattern is flagged."""
    now = datetime.now(timezone.utc)
    if ctx.event.type == "cron.nightly":
        insights.save(ctx.db, procrastination=insights.procrastination(insights._finished(ctx.db, now)))
        return
    task = ctx.db.get(Task, ctx.event.payload.get("task_id"))
    if task is None:
        return
    day = insights.DAYS[local(task.planned_start).weekday()]
    for p in insights.load(ctx.db).get("procrastination") or []:
        if p["block"] == task.title and p["day"] in (None, day):
            ctx.notes["habitual_skip"] = p
            return


@agent("pattern_miner")
async def pattern_miner(ctx: AgentContext) -> None:
    """Weekly: day-level links (gym days, first-ring mornings, low moods) vs how much gets done."""
    now = datetime.now(timezone.utc)
    found = insights.patterns(ctx.db, insights._finished(ctx.db, now))
    insights.save(ctx.db, patterns=found)
    ctx.notes["patterns"] = found
