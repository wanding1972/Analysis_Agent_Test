"""Version-neutral evaluation input, policy and result contracts."""

from typing import Annotated, Literal, Self, get_args

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints, model_validator

from agent_test.domains.assets.api import GoldenBaseline
from agent_test.domains.canonical.api import (
    CanonicalSemanticModel, CanonicalStep, CanonicalTestCase, ExpectedBehavior, StepDependency,
)
from agent_test.domains.rules.api import ApprovalStatus, RuleSet, RuleStatus


Identifier = Annotated[str, StringConstraints(strict=True, min_length=1, pattern=r"\S")]
Layer = Literal["semantic", "plan", "evidence", "answer"]
FailureCode = Literal["SEMANTIC_ERROR", "PLAN_ERROR", "EVIDENCE_ERROR", "ANSWER_ERROR"]
ComparisonKind = Literal["json_equal", "unordered_equal"]
SemanticField = Literal["metric", "scope", "grain", "dimensions", "time", "filters", "relations", "set_operations", "operation"]
PathItem = Annotated[int, Field(strict=True, ge=0)] | Annotated[str, Field(strict=True)]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class EvidenceReference(Model):
    evidence_id: Identifier
    path: list[PathItem]
    conditions: CanonicalSemanticModel | None
    step_id: Identifier | None = None


class EvidenceBundle(Model):
    result: JsonValue
    references: list[EvidenceReference]

    @model_validator(mode="after")
    def unique_ids(self) -> Self:
        ids = [item.evidence_id for item in self.references]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate evidence_id")
        return self


class AnswerClaim(Model):
    claim_id: Identifier
    evidence_id: Identifier | None
    value: JsonValue
    conditions: CanonicalSemanticModel | None


class AnswerObservation(Model):
    behavior: ExpectedBehavior
    claims: list[AnswerClaim]
    claims_complete: Annotated[bool, Field(strict=True)] | None
    conditions: CanonicalSemanticModel | None

    @model_validator(mode="after")
    def unique_claims(self) -> Self:
        ids = [item.claim_id for item in self.claims]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate claim_id")
        return self


class Observation(Model):
    case_id: Identifier
    snapshot_id: Identifier
    semantic: CanonicalSemanticModel | None
    steps: list[CanonicalStep] | None
    step_dependencies: list[StepDependency] | None
    evidence: EvidenceBundle | None
    answer: AnswerObservation | None


class RelatedEvidence(Model):
    snapshot_id: Identifier
    bundle: EvidenceBundle


class ResultFact(Model):
    source: Literal["result", "semantic"]
    path: list[PathItem]


class RelatedFact(Model):
    source: Literal["related"]
    reference: Identifier
    path: list[PathItem]


class LiteralFact(Model):
    source: Literal["literal"]
    value: JsonValue


FactBinding = Annotated[ResultFact | RelatedFact | LiteralFact, Field(discriminator="source")]


class LayerPolicy(Model):
    behaviors: list[ExpectedBehavior]
    failure_code: FailureCode


class SemanticPolicy(LayerPolicy):
    fields: dict[SemanticField, ComparisonKind] = Field(min_length=1)


class PlanPolicy(LayerPolicy):
    fields: dict[Literal["steps", "step_dependencies"], ComparisonKind] = Field(min_length=1)
    validate_structure: Annotated[bool, Field(strict=True)]


class EvidencePolicy(LayerPolicy):
    require_golden: Annotated[bool, Field(strict=True)]
    golden_comparison: ComparisonKind
    rule_bindings: dict[Identifier, dict[Identifier, FactBinding]]
    check_reference_conditions: Annotated[bool, Field(strict=True)]
    reference_condition_comparison: ComparisonKind
    condition_fields: list[SemanticField] = Field(min_length=1)


class AnswerCheck(Model):
    kind: Literal["behavior", "claims_complete", "claim_values", "claim_conditions", "answer_conditions"]
    behaviors: list[ExpectedBehavior]
    comparison: ComparisonKind


class AnswerPolicy(LayerPolicy):
    checks: list[AnswerCheck] = Field(min_length=1)
    condition_fields: list[SemanticField] = Field(min_length=1)
    required_claims_complete: Annotated[bool, Field(strict=True)]

    @model_validator(mode="after")
    def unique_checks(self) -> Self:
        ids = [item.kind for item in self.checks]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate answer check")
        return self


class EvaluationPolicy(Model):
    schema_version: Literal["1"]
    approval: ApprovalStatus
    approved_by: Identifier | None
    precedence: list[RuleStatus]
    semantic: SemanticPolicy
    plan: PlanPolicy
    evidence: EvidencePolicy
    answer: AnswerPolicy

    @model_validator(mode="after")
    def complete_policy(self) -> Self:
        if len(self.precedence) != len(RuleStatus) or set(self.precedence) != set(RuleStatus):
            raise ValueError("precedence must include each status exactly once")
        if self.approval == ApprovalStatus.APPROVED and self.approved_by is None:
            raise ValueError("approved policies require human approval reference")
        return self


class EvaluationRequest(Model):
    test_case: CanonicalTestCase
    question_id: Identifier
    snapshot_id: Identifier
    observation: Observation
    approved_rules: RuleSet
    golden_baseline: GoldenBaseline | None
    policy: EvaluationPolicy
    related_evidence: dict[Identifier, RelatedEvidence] = Field(default_factory=dict)


class CheckResult(Model):
    check_id: Identifier
    status: RuleStatus
    reason: Identifier
    expected: JsonValue = None
    actual: JsonValue = None


class LayerResult(Model):
    layer: Layer
    status: RuleStatus
    failure_code: FailureCode | None
    checks: list[CheckResult]


class TestResult(Model):
    case_id: Identifier
    snapshot_id: Identifier
    status: RuleStatus
    layers: list[LayerResult]

    @model_validator(mode="after")
    def all_layers(self) -> Self:
        if len(self.layers) != len(get_args(Layer)) or {item.layer for item in self.layers} != set(get_args(Layer)):
            raise ValueError("result must contain each evaluation layer exactly once")
        return self
