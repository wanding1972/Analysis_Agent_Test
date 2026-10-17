"""Read V4.6.1 ontology input as data; never import or execute supplied source."""

import logging
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from agent_test.domains.versioning.api import AgentVersion, VersionPackage, VersionPackageError


logger = logging.getLogger(__name__)
V461Status = Literal["AVAILABLE", "CALIBRATION_PENDING", "DATA_UNAVAILABLE", "OUT_OF_SCOPE", "PARTIAL"]


class _Loader(yaml.SafeLoader):
    pass


def _mapping(loader, node):
    result = {}
    for key, value in loader.construct_pairs(node, deep=True):
        if not isinstance(key, str) or key in result:
            raise ValueError("mapping keys must be unique strings")
        result[key] = value
    return result


_Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def read_yaml(path: Path) -> dict:
    try:
        with path.open(encoding="utf-8") as stream:
            result = yaml.load(stream, Loader=_Loader)
        if not isinstance(result, dict):
            raise ValueError("expected document object")
        return result
    except (OSError, UnicodeError, yaml.YAMLError, ValueError, RecursionError) as error:
        logger.error("Unable to read version package document")
        raise VersionPackageError("Unable to read version package document") from error


class MappingModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class FilterMapping(MappingModel):
    operator: str = Field(min_length=1)
    negated: Annotated[bool, Field(strict=True)]
    fields: list[Literal["value_text", "values_text", "range_low", "range_high"]] = Field(min_length=1)


class V461Mapping(MappingModel):
    schema_version: Literal["1"]
    version_id: str = Field(min_length=1)
    requirement_aliases: list[str]
    documents: dict[str, str]
    capability_id_template: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_-]*\{question_ref\}$")
    fanout_modes: dict[str, Annotated[bool, Field(strict=True)]]
    capability_defaults: dict[str, str]
    exposed_statuses: list[V461Status]
    additional_dimension_ids: list[str]
    capability_limitations: list[str]
    sequence_operator: str = Field(min_length=1)
    plan_step_defaults: dict[str, JsonValue]
    filter_operators: dict[str, FilterMapping]
    task_defaults: dict[str, JsonValue]
    relation_defaults: dict[str, JsonValue]
    time_defaults: dict[str, JsonValue]
    order_defaults: dict[str, JsonValue]
    capability_operators: dict[str, str]
    task_operators: dict[str, str]
    output_kinds: dict[str, str]
    traversal_directions: dict[str, str]
    relation_scopes: dict[str, str]
    argument_names: dict[str, str]

    @classmethod
    def load(cls, path: Path):
        try:
            return cls.model_validate(read_yaml(path))
        except ValidationError as error:
            logger.error("Invalid version mapping configuration")
            raise VersionPackageError("Invalid version mapping configuration") from error


class V461DirectorySource:
    def __init__(self, ontology_root: Path, version: AgentVersion, mapping: V461Mapping):
        self.root = ontology_root
        self.version = version
        self.mapping = mapping

    def read(self) -> VersionPackage:
        try:
            version = AgentVersion.model_validate(self.version.model_dump())
            mapping = V461Mapping.model_validate(self.mapping.model_dump())
            if version.version_id != mapping.version_id or version.requirement_aliases != mapping.requirement_aliases:
                raise ValueError("version registration does not match mapping")
            documents = {}
            root = self.root.resolve()
            for name, relative in mapping.documents.items():
                path = (root / relative).resolve()
                if not path.is_relative_to(root):
                    raise ValueError("document escapes package root")
                documents[name] = read_yaml(path)
            if version.semantic_version != documents["package"]["semantic_version"]:
                raise ValueError("ontology semantic version does not match registration")
            return VersionPackage(version=version, documents=documents)
        except (ValidationError, ValueError, KeyError, TypeError, OSError, RecursionError) as error:
            logger.error("Invalid version package")
            raise VersionPackageError("Invalid version package") from error
