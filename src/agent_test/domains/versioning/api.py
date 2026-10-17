"""Public version contracts; concrete adapters are statically wired by callers."""

from .models import AgentVersion, CapabilityDeclaration, CapabilityNormalization, VersionPackage
from .ports import (
    CapabilityAdapter, VersioningError, VersionNormalizationError, VersionPackageError,
    VersionPackageSource,
)

__all__ = [
    "AgentVersion", "CapabilityDeclaration", "CapabilityNormalization", "VersionPackage",
    "CapabilityAdapter", "VersioningError", "VersionNormalizationError", "VersionPackageError",
    "VersionPackageSource",
]
