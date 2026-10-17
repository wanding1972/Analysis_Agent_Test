"""Rules schemas; business selections and thresholds belong to configuration."""

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints, model_validator


Identifier = Annotated[str, StringConstraints(strict=True, min_length=1, pattern=r"\S")]
Number = Annotated[int, Field(strict=True)] | Annotated[
    float, Field(strict=True, allow_inf_nan=False)
]


class RuleModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ApprovalStatus(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    RETIRED = "retired"


class RuleStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


class RuleMetadata(RuleModel):
    rule_id: Identifier
    description: Identifier
    approval: ApprovalStatus
    approved_by: Identifier | None

    @model_validator(mode="after")
    def validate_approval(self) -> Self:
        if self.approval == ApprovalStatus.APPROVED and self.approved_by is None:
            raise ValueError("approved rules require a human approval reference")
        return self


SemanticAxis = Literal[
    "metric", "subject", "grain", "dimensions", "time_op", "filters",
    "relations", "set_ops", "operation", "join_cardinality", "aggregation",
    "denominator_scope",
]
CompatibilityFamily = Literal[
    "metric_scope_rules", "metric_grain_rules", "metric_dimension_rules",
    "metric_time_rules", "join_cardinality_rules", "aggregation_rules",
    "denominator_rules", "relation_rules",
]


class AxisConstraint(RuleModel):
    axis: SemanticAxis
    allowed: list[Identifier] = Field(min_length=1)


class CompatibilityRule(RuleMetadata):
    family: CompatibilityFamily
    when: list[AxisConstraint]
    require: list[AxisConstraint] = Field(min_length=1)


class RangeAssertion(RuleModel):
    kind: Literal["numeric_range"]
    value: Identifier
    minimum: Number
    maximum: Number
    include_minimum: Annotated[bool, Field(strict=True)]
    include_maximum: Annotated[bool, Field(strict=True)]

    @model_validator(mode="after")
    def validate_bounds(self) -> Self:
        if self.minimum > self.maximum:
            raise ValueError("minimum exceeds maximum")
        return self


class CountLimitAssertion(RuleModel):
    kind: Literal["count_limit"]
    items: Identifier
    limit: Identifier


class SubsetAssertion(RuleModel):
    kind: Literal["subset"]
    subset: Identifier
    superset: Identifier


class DisjointAssertion(RuleModel):
    kind: Literal["disjoint"]
    left: Identifier
    right: Identifier


class DistinctAssertion(RuleModel):
    kind: Literal["distinct"]
    left: Identifier
    right: Identifier


class SumAssertion(RuleModel):
    kind: Literal["sum_equals"]
    parts: Identifier
    total: Identifier
    absolute_tolerance: Annotated[Number, Field(ge=0)]


class SemanticEqualityAssertion(RuleModel):
    kind: Literal["semantic_equal"]
    left: Identifier
    right: Identifier
    fields: list[Literal[
        "metric", "scope", "grain", "dimensions", "time", "filters",
        "relations", "set_operations", "operation",
    ]] = Field(min_length=1)


class EqualityAssertion(RuleModel):
    kind: Literal["json_equal", "unordered_equal"]
    left: Identifier
    right: Identifier


Assertion = Annotated[
    RangeAssertion | CountLimitAssertion | SubsetAssertion | DisjointAssertion
    | DistinctAssertion | SumAssertion | SemanticEqualityAssertion | EqualityAssertion,
    Field(discriminator="kind"),
]


class TestRule(RuleMetadata):
    category: Literal["property", "metamorphic"]
    preconditions: dict[Identifier, JsonValue]
    assertion: Assertion


class RuleSet(RuleModel):
    schema_version: Literal["1"]
    compatibility_rules: list[CompatibilityRule]
    test_rules: list[TestRule]

    @model_validator(mode="after")
    def validate_rule_ids(self) -> Self:
        ids = [rule.rule_id for rule in [*self.compatibility_rules, *self.test_rules]]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate rule_id")
        return self


class RuleInputs(RuleModel):
    """Already normalized facts; no SDK, storage, or Agent trace entities."""

    facts: dict[Identifier, JsonValue]


class CompatibilityContext(RuleModel):
    """Additional canonical metadata unavailable in the P1 semantic schema."""

    join_cardinality: Identifier | None = None
    aggregation: Identifier | None = None
    denominator_scope: Identifier | None = None


class RuleOutcome(RuleModel):
    rule_id: Identifier
    status: RuleStatus
    reason: Literal[
        "satisfied", "violated", "not_applicable", "not_approved",
        "missing_input", "invalid_input",
    ]
