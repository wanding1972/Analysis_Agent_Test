"""Execution ports; concrete Agent protocol code stays in infrastructure."""

from typing import Protocol

from .models import AgentReply


class ExecutionError(Exception):
    """Stable boundary error; response bodies and credentials are not included."""


class AgentExecutor(Protocol):
    def ask(self, question: str, *, timeout_seconds: int) -> AgentReply:
        ...
