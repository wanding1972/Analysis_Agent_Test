"""Reference IO is provided externally, never implemented inside Evaluation."""

from typing import Protocol

from pydantic import JsonValue

from agent_test.domains.assets.api import GoldenBaseline


class EvaluationConfigError(Exception):
    """Stable policy read or schema error."""


class ReferenceEvidenceError(Exception):
    """Reference query/result could not be obtained by the IO adapter."""


class EvaluationPolicySource(Protocol):
    def read(self) -> dict[str, object]:
        ...


class ReferenceEvidenceReader(Protocol):
    def read(self, baseline: GoldenBaseline) -> JsonValue:
        """Resolve Reference SQL against its fixed snapshot or raise ReferenceEvidenceError."""
        ...
