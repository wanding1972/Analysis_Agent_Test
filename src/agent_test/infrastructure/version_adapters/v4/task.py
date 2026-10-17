"""Text QueryTask / PlanStep normalization with explicit, caller-supplied bindings.

This adapter does not perform entity resolution, execute recipes, or call the Agent.
Unrepresentable inputs fail closed instead of losing fields.
"""

import logging
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints, ValidationError, model_validator

from agent_test.domains.canonical.api import (
    CanonicalSemanticModel, CanonicalStep, CanonicalTestCase, ExpectedBehavior, SemanticFilter, SemanticOperation,
    SemanticRelation, SemanticScope, SemanticTime, SetOperation, StepDependency,
)
from agent_test.domains.versioning.api import VersionNormalizationError

from .package import V461Mapping


logger = logging.getLogger(__name__)
Text = Annotated[str, StringConstraints(strict=True, min_length=1, pattern=r"\S")]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class RelationBinding(_Strict):
    relation: Text
    source: Text
    target: Text


class V461SemanticBindings(_Strict):
    """Explicit resolved IDs and values; no alias guessing inside the adapter."""

    metrics: dict[Text, Text]
    subjects: dict[Text, SemanticScope]
    subject_type_hints: dict[Text, Text] = Field(default_factory=dict)
    dimensions: dict[Text, Text]
    attributes: dict[Text, Text]
    values: dict[Text, dict[Text, JsonValue]]
    argument_values: dict[Text, dict[Text, JsonValue]] = Field(default_factory=dict)
    relations: dict[Text, RelationBinding]
    entities: dict[Text, Text]
    times: dict[Text, SemanticTime]
    object_set_subjects: dict[Text, Text]
    relation_operand_set_ids: dict[Text, Text] = Field(default_factory=dict)
    relation_result_set_ids: dict[Text, Text] = Field(default_factory=dict)
    default_scope: SemanticScope | None
    external_object_set_ids: list[Text]


class _Subject(_Strict):
    text: Text | None = None
    object_set_ref: Text | None = None
    kind_hint: Text | None = None

    @model_validator(mode="after")
    def exclusive(self):
        if (self.text is None) == (self.object_set_ref is None):
            raise ValueError("subject must specify exactly one reference")
        return self


class _Filter(_Strict):
    field_text: Text
    op: Text = "eq"
    value_text: Text | None = None
    values_text: list[Text] | None = None
    range_low: Text | None = None
    range_high: Text | None = None


class _Time(_Strict):
    text: Text | None = None
    start: Annotated[str, StringConstraints(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")] | None = None
    end: Annotated[str, StringConstraints(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")] | None = None
    grain: Literal["month", "quarter", "year"]
    op: Literal["by_month", "by_quarter", "by_year", "total", "cumulative", "yoy", "mom", "moving_12", "since_launch"]
    since_launch_months: Annotated[int, Field(strict=True, gt=0, le=120)] | None = None

    @model_validator(mode="after")
    def interval(self):
        if (self.start is None) != (self.end is None):
            raise ValueError("time endpoints must be paired")
        if self.text is None and self.start is None:
            raise ValueError("missing time representation")
        if self.start is not None and self.start > self.end:
            raise ValueError("inverted time interval")
        return self


class _Relation(_Strict):
    link_text: Text
    direction: Literal["FORWARD", "REVERSE"]
    target_text: Text | None = None
    target_texts: list[Text] | None = None
    set_op: Literal["intersect", "union", "difference"] | None = None
    scope: Text
    fitment_scope: Text | None = None
    project_to_target: Annotated[bool, Field(strict=True)]


class _Order(_Strict):
    by: Literal["metric", "property", "group"]
    key: Text | None = None
    direction: Literal["asc", "desc"]


class _Security(_Strict):
    principal_id: Text
    tenant_id: Text | None = None
    roles: list[Text] = Field(default_factory=list)
    purpose: Text | None = None


class _Task(_Strict):
    task_id: Text
    intent: Literal["query", "rank", "enumerate", "traverse", "compare", "distribution", "set_algebra"]
    subjects: list[_Subject]
    metrics: list[Text]
    time: dict[str, JsonValue] | None = None
    filters: list[_Filter]
    group_by: list[Text]
    order: dict[str, JsonValue] | None = None
    limit: Annotated[int, Field(strict=True, gt=0, le=1_000_000)] | None = None
    relation: dict[str, JsonValue] | None = None
    comparison: dict[str, JsonValue] | None = None
    params: dict[Text, str]
    percentiles: list[Annotated[float, Field(strict=True, gt=0, lt=1)]]
    output_kind: Literal["scalar", "series", "group_rows", "object_list", "distribution"]
    emit_object_set: Text | None = None
    security_context: _Security
    ontology_version: Text | None = None
    snapshot_id: Text | None = None
    capability_ref: Text | None = None
    question_ref: Annotated[int, Field(strict=True, ge=1)] | None = None


class _PlanStep(_Strict):
    step_id: Text
    task: dict[str, JsonValue]
    depends_on: list[Text]
    consumes: list[Text]
    emits: Text | None
    purpose: str
    subjects_from_set: Text | None
    filters_from_set: Text | None
    filter_dims: list[tuple[Text, Text]]
    label: str
    final: Annotated[bool, Field(strict=True)]
    view: dict[str, JsonValue]


class _Operand(_Strict):
    ref: Text
    label: str | None = None
    subjects: list[_Subject] = Field(default_factory=list)
    filters: list[_Filter] = Field(default_factory=list)
    time: dict[str, JsonValue] | None = None
    relation: dict[str, JsonValue] | None = None


class _Comparison(_Strict):
    operands: list[_Operand] = Field(min_length=2)
    pairs: list[tuple[Text, Text]] = Field(min_length=1)
    mode: Literal["delta", "ratio", "delta_and_ratio"] = "delta_and_ratio"


class V461PlanAdapter:
    def __init__(self, mapping: V461Mapping):
        self.mapping = mapping

    def normalize(self, *, case_id: str, question: str, expected_behavior: ExpectedBehavior,
                  steps: list[dict], bindings: V461SemanticBindings) -> CanonicalTestCase:
        try:
            mapping = V461Mapping.model_validate(self.mapping.model_dump())
            bindings = V461SemanticBindings.model_validate(bindings.model_dump(mode="json"))
            source = [_PlanStep.model_validate({**mapping.plan_step_defaults, **step}) for step in steps]
            if not source or len({item.step_id for item in source}) != len(source):
                raise ValueError("plan must contain unique step IDs")
            normalized = [self._step(item, bindings, mapping) for item in source]
            if len({item.task["task_id"] for item in source}) != len(source):
                raise ValueError("duplicate task ID")
            dependencies = self._dependencies(source, normalized, bindings.external_object_set_ids)
            return CanonicalTestCase(
                **self._root(normalized, mapping), case_id=case_id, question=question,
                expected_behavior=expected_behavior, steps=normalized, step_dependencies=dependencies,
            )
        except (ValidationError, ValueError, KeyError, TypeError, RecursionError) as error:
            logger.error("V4 plan normalization failed")
            raise VersionNormalizationError("V4 plan normalization failed") from error

    def _step(self, item, bindings, mapping):
        task = _Task.model_validate({**mapping.task_defaults, **item.task})
        if task.emit_object_set is not None and item.emits is not None and task.emit_object_set != item.emits:
            raise ValueError("inconsistent emitted set identity")
        if task.emit_object_set is None and item.emits is not None:
            task.emit_object_set = item.emits
        semantic, references = self._task(task, bindings, mapping)
        injected = [value for value in (item.subjects_from_set, item.filters_from_set) if value]
        actual_inputs = list(dict.fromkeys([*references, *injected]))
        if len(item.consumes) != len(set(item.consumes)) or set(item.consumes) != set(actual_inputs):
            raise ValueError("consumes must match all task and injected set references")
        parameters = semantic["operation"].parameters
        parameters["result_included"] = item.final
        if item.subjects_from_set:
            parameters["subject_binding"] = {"source_object_set_id": item.subjects_from_set}
        if item.filters_from_set:
            if not item.filter_dims:
                raise ValueError("filter set binding requires explicit fields")
            parameters["filter_binding"] = {
                "source_object_set_id": item.filters_from_set,
                "fields": [{"attribute": bindings.attributes[attr], "dimension": bindings.dimensions[dim]}
                           for attr, dim in item.filter_dims],
            }
        elif item.filter_dims:
            raise ValueError("filter dimensions require a source set")
        return CanonicalStep(
            **semantic, step_id=item.step_id, input_object_set_ids=actual_inputs,
            output_object_set_ids=[task.emit_object_set] if task.emit_object_set else [],
        )

    @staticmethod
    def _dependencies(source, normalized, external):
        dependencies, producers, ancestors = [], {}, {}
        for item, step in zip(source, normalized, strict=True):
            if any(ref not in ancestors for ref in item.depends_on):
                raise ValueError("dependency must reference an earlier step")
            ancestors[item.step_id] = set(item.depends_on).union(
                *(ancestors[ref] for ref in item.depends_on)
            )
            dependencies.extend(StepDependency(step_id=item.step_id, depends_on=ref)
                                for ref in item.depends_on)
            for ref in step.input_object_set_ids:
                if ref in producers:
                    producer = producers[ref]
                    if producer not in ancestors[item.step_id]:
                        raise ValueError("set producer is outside declared dependency closure")
                    dependencies.append(StepDependency(
                        step_id=item.step_id, depends_on=producer, object_set_id=ref,
                    ))
                elif ref not in external:
                    raise ValueError("unproduced object set reference")
            for output in step.output_object_set_ids:
                if output in producers or output in external:
                    raise ValueError("duplicate object set producer")
                producers[output] = item.step_id
        return dependencies

    @staticmethod
    def _root(steps, mapping):
        if len(steps) == 1:
            return steps[0].model_dump(exclude={"step_id", "input_object_set_ids", "output_object_set_ids"})
        return dict(metric=None, scope=None, grain=None, dimensions=[], time=None,
                    filters=[], relations=[], set_operations=[],
                    operation=SemanticOperation(operator=mapping.sequence_operator,
                                                parameters={"step_ids": [item.step_id for item in steps]}))

    def _task(self, task: _Task, bindings: V461SemanticBindings, mapping: V461Mapping):
        scopes, references = self._scopes(task, bindings)
        metric_ids = [bindings.metrics[value] for value in task.metrics]
        arguments = {mapping.argument_names[key]: bindings.argument_values[key][value]
                     for key, value in task.params.items()}
        parameters = {"arguments": arguments, "output": mapping.output_kinds[task.output_kind],
                      "limit": task.limit, "percentiles": task.percentiles,
                      "metrics": metric_ids, "scopes": [item.model_dump(mode="json") for item in scopes]}
        if task.order is not None:
            parameters["order"] = self._order(task.order, bindings, mapping)
        relations, set_operations, traversal = self._relation(task, bindings, mapping)
        if traversal is not None:
            parameters["traversal"] = traversal
        if (task.intent == "compare") != (task.comparison is not None):
            raise ValueError("comparison payload must agree with task intent")
        if task.comparison is not None:
            parameters["comparison"], consumed = self._comparison(task, bindings, mapping)
            references.extend(consumed)
        if task.intent == "rank" and task.limit is None:
            raise ValueError("rank requires limit")
        if task.output_kind == "distribution" and not task.percentiles:
            raise ValueError("distribution requires percentiles")
        return dict(
            metric=metric_ids[0] if len(metric_ids) == 1 else None,
            scope=scopes[0] if len(scopes) == 1 else None, grain=None,
            dimensions=[bindings.dimensions[value] for value in task.group_by],
            time=self._time(task.time, bindings, mapping),
            filters=[self._filter(item, bindings, mapping) for item in task.filters],
            relations=relations, set_operations=set_operations,
            operation=SemanticOperation(operator=mapping.task_operators[task.intent], parameters=parameters),
        ), list(dict.fromkeys(references))

    @staticmethod
    def _scopes(task, bindings):
        scopes, references = [], []
        for subject in task.subjects:
            if subject.text is not None:
                scopes.append(bindings.subjects[subject.text])
            else:
                references.append(subject.object_set_ref)
                scopes.append(SemanticScope(subject=bindings.object_set_subjects[subject.object_set_ref],
                                            object_set_id=subject.object_set_ref))
            if subject.kind_hint is not None and bindings.subject_type_hints[subject.kind_hint] != scopes[-1].subject:
                raise ValueError("subject type hint disagrees with resolved scope")
        if not scopes and bindings.default_scope is not None:
            scopes = [bindings.default_scope]
        if len(references) > 1 or len({item.model_dump_json() for item in scopes}) != len(scopes):
            raise ValueError("duplicate or multiple object set subjects")
        return scopes, references

    @staticmethod
    def _order(raw, bindings, mapping):
        order = _Order.model_validate({**mapping.order_defaults, **raw})
        spaces = {"metric": bindings.metrics, "property": bindings.attributes, "group": bindings.dimensions}
        return {"by": order.by, "key": spaces[order.by][order.key] if order.key else None,
                "direction": order.direction}

    @staticmethod
    def _relation(task, bindings, mapping):
        if task.relation is None:
            if task.intent == "set_algebra":
                raise ValueError("set algebra requires a relation operator")
            return [], [], None
        if "scope" in task.relation and task.relation.get("fitment_scope") is not None:
            raise ValueError("ambiguous relation scope fields")
        relation = _Relation.model_validate({**mapping.relation_defaults, **task.relation})
        if relation.target_text is not None and relation.target_texts is not None:
            raise ValueError("ambiguous relation target")
        if relation.target_texts == []:
            raise ValueError("empty relation target list")
        targets = relation.target_texts if relation.target_texts is not None else (
            [relation.target_text] if relation.target_text is not None else []
        )
        traversal = {"direction": mapping.traversal_directions[relation.direction],
                     "scope": mapping.relation_scopes[relation.fitment_scope or relation.scope],
                     "target_ids": [bindings.entities[value] for value in targets],
                     "project_to_target": relation.project_to_target}
        operations = []
        if relation.set_op is not None:
            if not relation.target_texts:
                raise ValueError("set algebra requires target operands")
            operations.append(SetOperation(
                operator=relation.set_op,
                operand_set_ids=[bindings.relation_operand_set_ids[value] for value in targets],
                result_set_id=task.emit_object_set or bindings.relation_result_set_ids[task.task_id],
            ))
        if task.intent == "set_algebra" and not operations:
            raise ValueError("set algebra requires a relation operator")
        binding = bindings.relations[relation.link_text]
        return [SemanticRelation(**binding.model_dump())], operations, traversal

    def _comparison(self, task, bindings, mapping):
        if len(task.metrics) != 1:
            raise ValueError("source comparison contract requires one metric")
        comparison = _Comparison.model_validate(task.comparison)
        refs = {item.ref for item in comparison.operands}
        if len(refs) != len(comparison.operands) or any(
            a not in refs or b not in refs or a == b for a, b in comparison.pairs
        ):
            raise ValueError("invalid comparison operand references")
        operands, references = [], []
        for operand in comparison.operands:
            payload = {**mapping.task_defaults, "task_id": operand.ref,
                       "metrics": task.metrics, "security_context": task.security_context.model_dump(),
                       "subjects": [item.model_dump(exclude_none=True) for item in operand.subjects],
                       "filters": [item.model_dump(exclude_none=True) for item in operand.filters],
                       "time": operand.time, "relation": operand.relation}
            converted, consumed = self._task(_Task.model_validate(payload), bindings, mapping)
            references.extend(consumed)
            operands.append({"operand_id": operand.ref,
                             "semantic": CanonicalSemanticModel(**converted).model_dump(mode="json")})
        return {"operands": operands, "pairs": [list(pair) for pair in comparison.pairs],
                "mode": comparison.mode}, references

    @staticmethod
    def _time(payload, bindings, mapping):
        if payload is None:
            return None
        raw = _Time.model_validate({**mapping.time_defaults, **payload})
        if raw.op == "since_launch" and raw.since_launch_months is None:
            raise ValueError("since_launch requires an explicit month count")
        if raw.text is None:
            return SemanticTime(operator=raw.op, parameters=raw.model_dump(
                exclude={"text", "op"}, exclude_none=True))
        resolved = bindings.times[raw.text]
        if resolved.operator != raw.op:
            raise ValueError("resolved time operator does not match source")
        explicit = raw.model_dump(exclude={"text", "op"}, exclude_none=True)
        if any(resolved.parameters.get(key) != value for key, value in explicit.items()):
            raise ValueError("resolved time parameters do not match source")
        return resolved

    @staticmethod
    def _filter(source: _Filter, bindings: V461SemanticBindings, mapping: V461Mapping):
        rule = mapping.filter_operators[source.op]
        supplied = {key for key, value in source.model_dump().items()
                    if key not in {"field_text", "op"} and value is not None}
        if supplied != set(rule.fields):
            raise ValueError("filter value shape does not match operator")
        values = []
        for field in rule.fields:
            raw = getattr(source, field)
            if isinstance(raw, list):
                if not raw:
                    raise ValueError("empty filter value list")
                values.append([bindings.values[source.field_text][value] for value in raw])
            else:
                values.append(bindings.values[source.field_text][raw])
        return SemanticFilter(field=bindings.attributes[source.field_text], operator=rule.operator,
                              value=values[0] if len(values) == 1 else values, negated=rule.negated)
