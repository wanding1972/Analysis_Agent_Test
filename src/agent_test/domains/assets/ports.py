"""Asset IO contracts. Implementations own stable error translation and logging."""

from typing import Protocol

from .models import AssetSetSummary, TestAssetSet


class AssetError(Exception):
    """Base error for asset operations."""


class AssetReadError(AssetError):
    """Input could not be decoded or read."""


class AssetValidationError(AssetError):
    """Decoded input does not satisfy the asset schema."""


class AssetStorageError(AssetError):
    """Asset persistence failed."""


class AssetConflictError(AssetStorageError):
    """The asset set ID already exists; existing truth was not replaced."""


class AssetNotFoundError(AssetStorageError):
    """The requested asset set does not exist."""


class QuestionSource(Protocol):
    def read(self) -> list[dict[str, object]]:
        """Read question rows or raise AssetReadError."""
        ...


class AssetSetSource(Protocol):
    def read(self) -> dict[str, object]:
        """Read an asset set or raise AssetReadError."""
        ...


class AssetSetRepository(Protocol):
    def save(self, asset_set: TestAssetSet) -> None:
        """Insert one complete set atomically, never replace an existing ID."""
        ...

    def get(self, asset_set_id: str) -> TestAssetSet:
        """Read a complete set or raise AssetNotFoundError / AssetStorageError."""
        ...

    def list(self) -> list[AssetSetSummary]:
        """Read summaries in one batch or raise AssetStorageError."""
        ...
