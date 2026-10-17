from collections.abc import Callable, Iterator
from typing import Protocol

from .models import DesignerRequest, ProposalBatch


class GenerationConfigError(Exception):
    pass


class CombinationDesignError(Exception):
    pass


class CandidateDesignError(Exception):
    pass


class GenerationBudgetExceeded(Exception):
    pass


class GenerationPolicySource(Protocol):
    def read(self) -> dict[str, object]:
        ...


class CombinationDesigner(Protocol):
    def rows(self, sizes: dict[str, int], strength: int,
             allow: Callable[[dict[str, int]], bool], max_interactions: int) -> Iterator[dict[str, int]]:
        ...


class CandidateDesigner(Protocol):
    def propose(self, request: DesignerRequest) -> ProposalBatch:
        """Return questions only; must never define expected semantic truth."""
        ...
