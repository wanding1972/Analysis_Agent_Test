"""Version-neutral drift contracts."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints

from agent_test.domains.execution.api import ExecutionObservation

Identifier = Annotated[str, StringConstraints(strict=True, min_length=1, pattern=r"\S")]
DriftKind = Literal["capability", "semantic", "plan", "evidence", "answer"]
DriftStatus = Literal["none", "regression", "expected_change", "blocked"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class DriftPolicy(Model):
    """Configuration only; expected changes are explicit and human-owned."""

    schema_version: Literal["1"]
    expected_changes: list[Identifier] = Field(default_factory=list)
    required_kinds: list[DriftKind] = Field(default_factory=lambda: [
        "capability", "semantic", "plan", "evidence", "answer",
    ])


class DriftItem(Model):
    kind: DriftKind
    path: Identifier
    baseline: JsonValue = None
    candidate: JsonValue = None
    reason: Identifier


class DriftRecord(Model):
    drift_id: Identifier
    case_id: Identifier
    snapshot_id: Identifier
    baseline_version: Identifier
    candidate_version: Identifier
    status: DriftStatus
    items: list[DriftItem]
    summary: Identifier


class VersionExecution(Model):
    version_id: Identifier
    observation: ExecutionObservation
    semantic: JsonValue = None
    plan: JsonValue = None
    evidence: JsonValue = None
    answer: JsonValue = None
