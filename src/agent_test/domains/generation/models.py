from string import Formatter
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints, model_validator

from agent_test.domains.canonical.api import CanonicalCapability, CanonicalTestCase, ExpectedBehavior
from agent_test.domains.rules.api import (
    ApprovalStatus, CompatibilityContext, CompatibilityFamily, RuleOutcome, RuleSet, SemanticAxis,
)


Identifier = Annotated[str, StringConstraints(strict=True, min_length=1, pattern=r"\S")]
PositiveInt = Annotated[int, Field(strict=True, gt=0)]
Count = Annotated[int, Field(strict=True, ge=0)]
SemanticField = Literal["metric", "scope", "grain", "dimensions", "time", "filters", "relations", "set_operations", "operation"]
CaseType = Literal["combination", "property", "metamorphic", "negative", "paraphrase", "seed"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class AxisOption(Model):
    label: Identifier
    patch: dict[SemanticField, JsonValue] = Field(min_length=1)


class AxisTarget(Model):
    step_id: Identifier | None  # null explicitly targets root semantics


class GenerationAxis(Model):
    name: Identifier
    targets: list[AxisTarget] = Field(min_length=1)
    options: list[AxisOption] = Field(min_length=1)


class GenerationTemplate(Model):
    template_id: Identifier
    seed_case_id: Identifier
    case_type: Literal["combination", "property", "metamorphic", "seed"]
    question_template: Identifier
    axes: list[GenerationAxis]
    rule_ids: list[Identifier]
    related_seed_case_ids: list[Identifier]

    @model_validator(mode="after")
    def validate_template(self) -> Self:
        if len(self.rule_ids) != len(set(self.rule_ids)) or len(self.related_seed_case_ids) != len(set(self.related_seed_case_ids)):
            raise ValueError("duplicate rule or related-seed reference")
        names = [axis.name for axis in self.axes]
        if len(names) != len(set(names)) or "question" in names or any(not name.isidentifier() for name in names):
            raise ValueError("axes need unique identifier names; question is reserved")
        used = set()
        for _, field, spec, conversion in Formatter().parse(self.question_template):
            if field is not None:
                if field not in {*names, "question"} or spec or conversion:
                    raise ValueError("only plain declared placeholders are allowed")
                used.add(field)
        if not set(names) <= used:
            raise ValueError("every axis must be represented in the question")
        targets = set()
        for axis in self.axes:
            labels = [option.label for option in axis.options]
            if len(labels) != len(set(labels)):
                raise ValueError("axis option labels must be unique")
            local = [(target.step_id, field) for target in axis.targets
                     for field in {key for option in axis.options for key in option.patch}]
            if len(local) != len(set(local)) or targets.intersection(local):
                raise ValueError("axes must not overwrite the same semantic slot")
            targets.update(local)
        if self.case_type in {"property", "metamorphic"} and not self.rule_ids:
            raise ValueError("rule-derived templates require rule references")
        if self.case_type == "metamorphic" and not self.related_seed_case_ids:
            raise ValueError("metamorphic templates require related seed references")
        return self


class GenerationFilters(Model):
    required_families: list[CompatibilityFamily]
    allow_capability_only: Annotated[bool, Field(strict=True)]
    capability_axes: dict[SemanticAxis, Literal[
        "metrics", "subjects", "dimensions", "time_ops", "filters", "relations", "set_ops", "operations",
    ]]
    closed_world_axes: list[SemanticAxis]
    structural_operations: list[Identifier]


class GenerationPolicy(Model):
    schema_version: Literal["1"]
    approval: ApprovalStatus
    approved_by: Identifier | None
    pairwise_strength: Annotated[int, Field(strict=True, ge=2, le=3)]
    high_risk_strength: Annotated[int, Field(strict=True, ge=2, le=3)]
    high_risk_capability_ids: list[Identifier]
    max_generated_cases: PositiveInt
    max_candidate_checks: PositiveInt
    max_interaction_checks: PositiveInt
    paraphrase_count: Count
    max_ai_candidates: Count
    ai_enabled: Annotated[bool, Field(strict=True)]
    designer_prompt: Identifier
    allowed_case_types: list[CaseType]
    invalid_combination_strategy: Literal["exclude", "negative"]
    invalid_combination_behavior: ExpectedBehavior
    generation_filters: GenerationFilters
    templates: list[GenerationTemplate]

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        if self.ai_enabled and self.paraphrase_count > 0 and self.max_ai_candidates == 0:
            raise ValueError("enabled AI requires a nonzero proposal budget")
        if self.approval == ApprovalStatus.APPROVED and self.approved_by is None:
            raise ValueError("approved policies require human approval reference")
        ids = [item.template_id for item in self.templates]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate template ID")
        return self


class GenerationRequest(Model):
    capability: CanonicalCapability
    seed_cases: list[CanonicalTestCase] = Field(min_length=1)
    rules: RuleSet
    context: CompatibilityContext
    policy: GenerationPolicy

    @model_validator(mode="after")
    def validate_refs(self) -> Self:
        seeds = {item.case_id for item in self.seed_cases}
        if len(seeds) != len(self.seed_cases):
            raise ValueError("duplicate seed ID")
        for template in self.policy.templates:
            if template.seed_case_id not in seeds or not set(template.related_seed_case_ids) <= seeds:
                raise ValueError("template references unknown seeds")
            seed = next(item for item in self.seed_cases if item.case_id == template.seed_case_id)
            steps = {item.step_id for item in seed.steps}
            if any(target.step_id is not None and target.step_id not in steps
                   for axis in template.axes for target in axis.targets):
                raise ValueError("axis target references unknown step")
        return self


class DesignerRequest(Model):
    seeds: list[CanonicalTestCase]
    paraphrase_count: Count
    max_candidates: Count
    prompt: Identifier


class QuestionProposal(Model):
    seed_case_id: Identifier
    question: Identifier


class ProposalBatch(Model):
    proposals: list[QuestionProposal]


class GeneratedTestCase(Model):
    case: CanonicalTestCase
    seed_case_id: Identifier
    capability_id: Identifier
    case_type: CaseType
    source: Literal["deterministic", "ai"]
    status: Literal["candidate"] = "candidate"
    review_required: Annotated[bool, Field(strict=True)]
    compatibility: list[RuleOutcome]
    rule_ids: list[Identifier]
    related_seed_case_ids: list[Identifier]

    @model_validator(mode="after")
    def validate_ai_provenance(self) -> Self:
        if self.source == "ai" and (not self.review_required or self.case_type != "paraphrase"):
            raise ValueError("AI question candidates require review and paraphrase provenance")
        return self


class SamplingRecord(Model):
    template_id: Identifier
    requested_strength: Literal[2, 3]
    effective_strength: Count
    backend_exhausted: Annotated[bool, Field(strict=True)]
    emitted_rows: Count


class GenerationBatch(Model):
    status: Literal["ready", "partial", "blocked"]
    candidates: list[GeneratedTestCase]
    rejected_counts: dict[Identifier, Count]
    diagnostics: list[Identifier]
    truncated: Annotated[bool, Field(strict=True)]
    sampling: list[SamplingRecord]
    # Backend exhaustion alone does not prove constrained t-wise completeness.
    constrained_coverage_verified: Literal[False] = False
