"""Version IO and normalization boundaries, without concrete Adapter imports."""

from typing import Protocol

from agent_test.domains.canonical.api import CanonicalCapabilitySet

from .models import CapabilityNormalization, VersionPackage


class VersioningError(Exception):
    """Stable error; raw package data is not part of the message."""


class VersionPackageError(VersioningError):
    """Package is unreadable, incomplete or invalid."""


class VersionNormalizationError(VersioningError):
    """Input cannot be normalized without guessing or losing semantics."""


class VersionPackageSource(Protocol):
    def read(self) -> VersionPackage:
        ...


class CapabilityAdapter(Protocol):
    def normalize(self, version_package: VersionPackage) -> CanonicalCapabilitySet:
        ...

    def inspect(self, version_package: VersionPackage) -> CapabilityNormalization:
        """Expose source status/limitations separately from Canonical semantics."""
        ...
