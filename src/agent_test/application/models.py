"""Application DTOs; workflow state only, no business rules."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from agent_test.domains.drift.api import DriftRecord, VersionExecution
from agent_test.domains.execution.api import ExecutionBatch, ExecutionRequest
from agent_test.domains.review.api import FailureReview
from agent_test.domains.rules.api import RuleStatus

Identifier = Annotated[str, StringConstraints(strict=True, min_length=1, pattern=r"\S")]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class TestRun(Model):
    run_id: Identifier
    agent_version: Identifier
    snapshot_id: Identifier
    execution: ExecutionBatch
    result_statuses: list[RuleStatus] = Field(default_factory=list)
    drifts: list[DriftRecord] = Field(default_factory=list)
    reviews: list[FailureReview] = Field(default_factory=list)


class CompareRequest(Model):
    baseline: VersionExecution
    candidate: VersionExecution
