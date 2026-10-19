"""Human-owned QA review contracts."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from agent_test.domains.drift.api import DriftRecord

Identifier = Annotated[str, StringConstraints(strict=True, min_length=1, pattern=r"\S")]
Classification = Literal[
    "BUG", "EXPECTED_CHANGE", "DATA_ISSUE", "BASELINE_ERROR", "TEST_RULE_ERROR", "BLOCKED",
]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ReviewDecision(Model):
    classification: Classification
    reviewer: Identifier
    comment: Identifier


class FailureReview(Model):
    review_id: Identifier
    case_id: Identifier
    drift_id: Identifier | None
    status: Literal["pending", "decided"]
    classification: Classification | None
    reviewer: Identifier | None
    comment: str | None
    suggested_cause: str | None


def review_from_drift(drift: DriftRecord, decision: ReviewDecision | None = None) -> FailureReview:
    if decision is None:
        return FailureReview(
            review_id=f"review:{drift.drift_id}", case_id=drift.case_id, drift_id=drift.drift_id,
            status="pending", classification=None, reviewer=None, comment=None,
            suggested_cause=drift.summary,
        )
    return FailureReview(
        review_id=f"review:{drift.drift_id}", case_id=drift.case_id, drift_id=drift.drift_id,
        status="decided", classification=decision.classification, reviewer=decision.reviewer,
        comment=decision.comment, suggested_cause=drift.summary,
    )
