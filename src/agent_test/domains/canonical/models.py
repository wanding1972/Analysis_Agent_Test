"""Canonical schema only: no compatibility, evaluation, or version rules."""

from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints, model_validator


Identifier = Annotated[str, StringConstraints(strict=True, min_length=1, pattern=r"\S")]


class ContractModel(BaseModel):
    """Reject unknown input and implicit scalar coercion at the boundary."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True, allow_inf_nan=False)


class ExpectedBehavior(StrEnum):
    ANSWER = "ANSWER"
    CLARIFY = "CLARIFY"
    REJECT = "REJECT"


class SemanticScope(ContractModel):
    subject: Identifier
    entity_ids: list[Identifier] = Field(default_factory=list)
    object_set_id: Identifier | None = None


class SemanticTime(ContractModel):
    operator: Identifier
    parameters: dict[Identifier, JsonValue] = Field(default_factory=dict)


class SemanticFilter(ContractModel):
    field: Identifier
    operator: Identifier
    value: JsonValue
    negated: Annotated[bool, Field(strict=True)] = False


class SemanticRelation(ContractModel):
    relation: Identifier
    source: Identifier
    target: Identifier


class SetOperation(ContractModel):
    operator: Identifier
    operand_set_ids: list[Identifier] = Field(min_length=1)
    result_set_id: Identifier


class SemanticOperation(ContractModel):
    operator: Identifier
    parameters: dict[Identifier, JsonValue] = Field(default_factory=dict)


class CanonicalSemanticModel(ContractModel):
    # Required nullable fields distinguish explicit unknown from omitted input.
    metric: Identifier | None
    scope: SemanticScope | None
    grain: Identifier | None
    dimensions: list[Identifier]
    time: SemanticTime | None
    filters: list[SemanticFilter]
    relations: list[SemanticRelation]
    set_operations: list[SetOperation]
    operation: SemanticOperation | None


class CanonicalStep(CanonicalSemanticModel):
    step_id: Identifier
    input_object_set_ids: list[Identifier] = Field(default_factory=list)
    output_object_set_ids: list[Identifier] = Field(default_factory=list)


class StepDependency(ContractModel):
    step_id: Identifier
    depends_on: Identifier
    object_set_id: Identifier | None = None


def _require_unique(values: list[str], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"duplicate {label}")


class CanonicalTestCase(CanonicalSemanticModel):
    case_id: Identifier
    question: Identifier
    expected_behavior: ExpectedBehavior
    steps: list[CanonicalStep] = Field(default_factory=list)
    step_dependencies: list[StepDependency]

    @model_validator(mode="after")
    def validate_step_references(self) -> Self:
        """An ordered plan must reference earlier steps and matching set IDs."""
        _require_unique([step.step_id for step in self.steps], "step_id")
        positions = {step.step_id: index for index, step in enumerate(self.steps)}
        steps = {step.step_id: step for step in self.steps}
        edges: set[tuple[str, str, str | None]] = set()
        for edge in self.step_dependencies:
            key = (edge.step_id, edge.depends_on, edge.object_set_id)
            if key in edges:
                raise ValueError("duplicate step dependency")
            edges.add(key)
            if edge.step_id not in steps or edge.depends_on not in steps:
                raise ValueError("step dependency references an unknown step")
            if positions[edge.depends_on] >= positions[edge.step_id]:
                raise ValueError("dependency must precede dependent step")
            if edge.object_set_id is not None:
                producer = steps[edge.depends_on]
                consumer = steps[edge.step_id]
                if edge.object_set_id not in producer.output_object_set_ids:
                    raise ValueError("dependency set is not a producer output")
                if edge.object_set_id not in consumer.input_object_set_ids:
                    raise ValueError("dependency set is not a consumer input")
        return self


class CanonicalCapability(ContractModel):
    capability_id: Identifier
    metrics: list[Identifier]
    subjects: list[Identifier]
    dimensions: list[Identifier]
    time_ops: list[Identifier]
    filters: list[Identifier]
    relations: list[Identifier]
    set_ops: list[Identifier]
    operations: list[Identifier]
    multi_step: Annotated[bool, Field(strict=True)]


class CanonicalCapabilitySet(ContractModel):
    capabilities: list[CanonicalCapability]

    @model_validator(mode="after")
    def validate_ids(self) -> Self:
        _require_unique([item.capability_id for item in self.capabilities], "capability_id")
        return self
