"""Importing this package registers every implemented agent with the registry."""
from app.agents import (  # noqa: F401
    coaching, command, delivery, emotion, learning, memory, mentor, monitoring, planning, review, wellbeing,
)
