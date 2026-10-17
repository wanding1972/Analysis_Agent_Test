"""Asset schemas and reference integrity, without execution or truth decisions."""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints, model_validator

from agent_test.domains.canonical.api import CanonicalTestCase, ExpectedBehavior
from agent_test.domains.rules.api import RuleSet


Identifier = Annotated[str, StringConstraints(strict=True, min_length=1, pattern=r"\S")]


class AssetModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class GoldenQuestion(AssetModel):
    question_id: Identifier
    category: Identifier
    question: Identifier
    expected_behavior: ExpectedBehavior
    expected_metric: Identifier | None
    expected_scope: Identifier | None
    expected_grain: Identifier | None
    expected_time: Identifier | None
    note: Identifier | None


def _unique(values: list[str], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"duplicate {label}")


class QuestionSet(AssetModel):
    questions: list[GoldenQuestion]

    @model_validator(mode="after")
    def validate_ids(self) -> Self:
        _unique([item.question_id for item in self.questions], "question_id")
        return self


class SnapshotRef(AssetModel):
    snapshot_id: Identifier
    kind: Literal["snapshot", "database", "fixture"]
    reference: Identifier
    description: Identifier | None = None
    content_sha256: Annotated[str, StringConstraints(pattern=r"^[a-fA-F0-9]{64}$")] | None = None


class ReferenceSQL(AssetModel):
    kind: Literal["reference_sql"]
    sql: Identifier
    parameters: dict[Identifier, JsonValue]


class ReferenceResult(AssetModel):
    kind: Literal["reference_result"]
    result: JsonValue


class ConfirmedSemanticCase(AssetModel):
    kind: Literal["canonical_case"]
    case: CanonicalTestCase


class VerifiedVersionResult(AssetModel):
    kind: Literal["verified_version_result"]
    agent_version_ref: Identifier
    verification_reference: Identifier
    result: JsonValue


GoldenSource = Annotated[
    ReferenceSQL | ReferenceResult | ConfirmedSemanticCase | VerifiedVersionResult,
    Field(discriminator="kind"),
]


class GoldenBaseline(AssetModel):
    baseline_id: Identifier
    question_id: Identifier
    snapshot_id: Identifier
    confirmed_by: Identifier
    confirmation_reference: Identifier
    source: GoldenSource


class CanonicalCaseAsset(AssetModel):
    question_id: Identifier
    case: CanonicalTestCase


class TestAssetSet(AssetModel):
    schema_version: Literal["1"]
    asset_set_id: Identifier
    questions: list[GoldenQuestion]
    snapshots: list[SnapshotRef]
    canonical_cases: list[CanonicalCaseAsset]
    golden_baselines: list[GoldenBaseline]
    rules: RuleSet

    @model_validator(mode="after")
    def validate_references(self) -> Self:
        _unique([item.question_id for item in self.questions], "question_id")
        _unique([item.snapshot_id for item in self.snapshots], "snapshot_id")
        _unique([item.case.case_id for item in self.canonical_cases], "case_id")
        _unique([item.baseline_id for item in self.golden_baselines], "baseline_id")
        questions = {item.question_id for item in self.questions}
        snapshots = {item.snapshot_id for item in self.snapshots}
        for item in self.canonical_cases:
            if item.question_id not in questions:
                raise ValueError("Canonical case references an unknown question")
        for item in self.golden_baselines:
            if item.question_id not in questions:
                raise ValueError("Golden baseline references an unknown question")
            if item.snapshot_id not in snapshots:
                raise ValueError("Golden baseline references an unknown snapshot")
        return self


class AssetSetSummary(AssetModel):
    asset_set_id: Identifier
    question_count: Annotated[int, Field(strict=True, ge=0)]
    snapshot_count: Annotated[int, Field(strict=True, ge=0)]
    canonical_case_count: Annotated[int, Field(strict=True, ge=0)]
    golden_baseline_count: Annotated[int, Field(strict=True, ge=0)]
