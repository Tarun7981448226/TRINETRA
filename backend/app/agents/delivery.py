"""Reminders council — delivery: getting TRINETRA's words onto your lock screen."""
import asyncio

from app.core import push
from app.core.orchestrator import AgentContext
from app.core.registry import agent


@agent("push_agent")
async def push_agent(ctx: AgentContext) -> None:
    out = ctx.notes.get("proactive")
    if not out:
        return
    meta = out.get("meta") or {}
    # webpush is blocking network I/O — keep it off the event loop.
    red = meta.get("kind") == "red_alert"  # its own notification, never folded into the earlier reminder
    sent = await asyncio.to_thread(
        push.send, ctx.db, "🚨 TRINETRA" if red else "TRINETRA", out["text"], "/",
        f"{'red' if red else 'task'}-{meta.get('task_id', '')}"
    )
    ctx.notes["pushed_to"] = sent
