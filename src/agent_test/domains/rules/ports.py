"""Boundary for rule configuration input; no file dependency in the domain."""

from typing import Protocol


class RuleConfigError(Exception):
    """Stable configuration IO/parse/schema failure; carries no raw input."""


class RuleConfigSource(Protocol):
    def read(self) -> dict[str, object]:
        """Return a decoded configuration or raise RuleConfigError."""
        ...
