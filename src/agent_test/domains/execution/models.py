"""Version-neutral execution contracts."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints

from agent_test.domains.canonical.api import CanonicalTestCase


Identifier = Annotated[str, StringConstraints(strict=True, min_length=1, pattern=r"\S")]
PositiveInt = Annotated[int, Field(strict=True, gt=0)]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class AgentReply(Model):
    status: Literal["answered", "clarify", "blocked", "error"]
    answer: JsonValue = None
    detail: str | None = None


class ExecutionRequest(Model):
    run_id: Identifier
    cases: list[CanonicalTestCase] = Field(min_length=1)
    max_cases: PositiveInt
    timeout_seconds: PositiveInt


class ExecutionObservation(Model):
    run_id: Identifier
    case_id: Identifier
    question: Identifier
    snapshot_id: Identifier
    status: Literal["answered", "clarify", "blocked", "error"]
    answer: JsonValue = None
    detail: str | None = None


class ExecutionBatch(Model):
    status: Literal["ready", "partial", "blocked"]
    observations: list[ExecutionObservation]
    errors: list[Identifier]
    truncated: bool
