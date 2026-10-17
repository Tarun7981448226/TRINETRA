"""Learning council: the neural core predicts, the trainer keeps it learning."""
from app.core.orchestrator import AgentContext
from app.core.registry import agent
from app.db.models import Task
from app.ml import neural_core


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
