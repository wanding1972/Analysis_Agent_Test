"""Projection of actual V4.6.1 declarations, not a runtime availability verdict."""

import logging
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints, ValidationError

from agent_test.domains.canonical.api import CanonicalCapability, CanonicalCapabilitySet
from agent_test.domains.versioning.api import (
    CapabilityDeclaration, CapabilityNormalization, VersionNormalizationError, VersionPackage,
)

from .package import V461Mapping, V461Status


logger = logging.getLogger(__name__)
Text = Annotated[str, StringConstraints(strict=True, min_length=1, pattern=r"\S")]


class _Record(BaseModel):
    model_config = ConfigDict(extra="allow", allow_inf_nan=False)
    __pydantic_extra__: dict[str, JsonValue] = Field(init=False)
    id: Text
    measured_at: Text | None = None
    base_metric: Text | None = None
    supported_dimensions: list[Text] = Field(default_factory=list)
    time_op: Text | None = None


class _Capability(BaseModel):
    model_config = ConfigDict(extra="allow", allow_inf_nan=False)
    __pydantic_extra__: dict[str, JsonValue] = Field(init=False)
    capability_id: Text | None = None
    question_ref: Annotated[int, Field(strict=True, ge=1)] | None = None
    text: Text
    declared_status: V461Status
    metric_refs: list[Text] = Field(default_factory=list)
    link_refs: list[Text] = Field(default_factory=list)
    recipe_ref: Text | None = None
    fanout: Text
    metric_mode: Text
    intent: Text | None = None
    task_intent: Text | None = None
    analysis: Text | None = None


def _index(document: object, key: str) -> dict[str, dict]:
    if not isinstance(document, dict) or set(document) != {key} or not isinstance(document[key], list):
        raise ValueError("invalid catalog document")
    records = [_Record.model_validate(item).model_dump(exclude_none=True) for item in document[key]]
    result = {item["id"]: item for item in records}
    if len(result) != len(records):
        raise ValueError("duplicate catalog ID")
    return result


def _unique(items):
    return list(dict.fromkeys(items))


class V461CapabilityAdapter:
    def __init__(self, mapping: V461Mapping):
        self.mapping = mapping

    def normalize(self, version_package: VersionPackage) -> CanonicalCapabilitySet:
        return self.inspect(version_package).capabilities

    def inspect(self, version_package: VersionPackage) -> CapabilityNormalization:
        try:
            mapping = V461Mapping.model_validate(self.mapping.model_dump())
            package = VersionPackage.model_validate(version_package.model_dump())
            if (package.version.version_id != mapping.version_id
                    or package.version.requirement_aliases != mapping.requirement_aliases):
                raise ValueError("wrong version adapter")
            docs = package.documents
            if docs["package"]["semantic_version"] != package.version.semantic_version:
                raise ValueError("ontology version does not match registration")
            catalogs = {key: _index(docs[key], key) for key in
                        ("metrics", "object_types", "dimensions", "links", "recipes")}
            raw = docs["capabilities"]
            if not isinstance(raw, dict) or set(raw) != {"capabilities"} or not isinstance(raw["capabilities"], list):
                raise ValueError("invalid capability document")
            capabilities, declarations = [], []
            for item in raw["capabilities"]:
                source = _Capability.model_validate({**mapping.capability_defaults, **item})
                if source.capability_id is None and source.question_ref is None:
                    raise ValueError("capability has no identity")
                identity = source.capability_id or mapping.capability_id_template.format(question_ref=source.question_ref)
                metrics = [catalogs["metrics"][ref] for ref in source.metric_refs]
                links = [catalogs["links"][ref] for ref in source.link_refs]
                recipe = catalogs["recipes"][source.recipe_ref] if source.recipe_ref else None
                dimensions = _unique(dim for metric in metrics for dim in metric["supported_dimensions"])
                if any(dim not in catalogs["dimensions"] and dim not in mapping.additional_dimension_ids for dim in dimensions):
                    raise ValueError("unknown dimension reference")
                subjects = _unique(self._subject(metric, catalogs["metrics"], set()) for metric in metrics)
                subjects = [value for value in subjects if value is not None]
                subjects = _unique([*subjects, *(link["from"] for link in links)])
                if any(value not in catalogs["object_types"] for value in subjects):
                    raise ValueError("unknown subject reference")
                operations = _unique(mapping.capability_operators[value] for value in
                                     (source.intent, source.task_intent, source.analysis) if value is not None)
                # No shape/recipe expression is evaluated or turned into guessed steps.
                multi_step = mapping.fanout_modes[source.fanout] or bool(recipe and len(recipe["steps"]) > 1)
                projected = CanonicalCapability(
                    capability_id=identity, metrics=source.metric_refs, subjects=subjects,
                    dimensions=dimensions, time_ops=_unique(m["time_op"] for m in metrics if "time_op" in m),
                    filters=[], relations=source.link_refs, set_ops=[], operations=operations, multi_step=multi_step,
                )
                included = source.declared_status in mapping.exposed_statuses
                if included:
                    capabilities.append(projected)
                declarations.append(CapabilityDeclaration(
                    capability_id=identity, declared_status=source.declared_status,
                    status_basis="source_declaration", included_in_canonical=included,
                    limitations=mapping.capability_limitations,
                    source_metadata=source.model_dump(mode="json"),
                ))
            return CapabilityNormalization(
                capabilities=CanonicalCapabilitySet(capabilities=capabilities), declarations=declarations,
            )
        except (ValidationError, ValueError, KeyError, TypeError, RecursionError) as error:
            logger.error("V4 capability normalization failed")
            raise VersionNormalizationError("V4 capability normalization failed") from error

    @staticmethod
    def _subject(metric, metrics, seen):
        if metric["id"] in seen:
            raise ValueError("cyclic metric reference")
        if "measured_at" in metric:
            return metric["measured_at"]
        if "base_metric" not in metric:
            return None
        return V461CapabilityAdapter._subject(metrics[metric["base_metric"]], metrics, seen | {metric["id"]})
