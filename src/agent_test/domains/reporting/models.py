"""Stable report view and artifact contracts."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from agent_test.domains.drift.api import DriftRecord
from agent_test.domains.review.api import FailureReview
from agent_test.domains.rules.api import RuleStatus

Identifier = Annotated[str, StringConstraints(strict=True, min_length=1, pattern=r"\S")]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ReportInput(Model):
    run_id: Identifier
    agent_version: Identifier
    snapshot_id: Identifier
    result_statuses: list[RuleStatus]
    drifts: list[DriftRecord] = Field(default_factory=list)
    reviews: list[FailureReview] = Field(default_factory=list)


class ReportSummary(Model):
    total: int = Field(ge=0)
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    blocked: int = Field(ge=0)
    skipped: int = Field(ge=0)
    regression_count: int = Field(ge=0)
    pending_review_count: int = Field(ge=0)


class ReportView(Model):
    run_id: Identifier
    agent_version: Identifier
    snapshot_id: Identifier
    summary: ReportSummary
    drifts: list[DriftRecord]
    reviews: list[FailureReview]


class ReportArtifact(Model):
    format: Literal["json", "csv", "html", "xlsx"]
    filename: Identifier
    content: bytes
