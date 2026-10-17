"""Version-neutral package and normalization DTOs."""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints, model_validator

from agent_test.domains.canonical.api import CanonicalCapabilitySet


Identifier = Annotated[str, StringConstraints(strict=True, min_length=1, pattern=r"\S")]


class VersionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class AgentVersion(VersionModel):
    version_id: Identifier
    requirement_aliases: list[Identifier]
    source_reference: Identifier
    source_sha256: Annotated[str, StringConstraints(pattern=r"^[a-fA-F0-9]{64}$")]
    semantic_version: Identifier


class VersionPackage(VersionModel):
    version: AgentVersion
    documents: dict[Identifier, JsonValue]


class CapabilityDeclaration(VersionModel):
    capability_id: Identifier
    declared_status: Identifier
    status_basis: Literal["source_declaration"]
    included_in_canonical: Annotated[bool, Field(strict=True)]
    limitations: list[Identifier]
    # Namespaced source material belongs to Versioning, never Canonical.
    source_metadata: dict[Identifier, JsonValue]


class CapabilityNormalization(VersionModel):
    capabilities: CanonicalCapabilitySet
    declarations: list[CapabilityDeclaration]

    @model_validator(mode="after")
    def validate_ids(self) -> Self:
        ids = [item.capability_id for item in self.declarations]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate declaration ID")
        included = {item.capability_id for item in self.declarations if item.included_in_canonical}
        if included != {item.capability_id for item in self.capabilities.capabilities}:
            raise ValueError("declaration and Canonical IDs must agree")
        return self
