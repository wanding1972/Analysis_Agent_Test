"""Atomic, insert-only SQLite storage for complete asset sets."""

import logging
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

from pydantic import ValidationError

from agent_test.domains.assets.api import (
    AssetConflictError, AssetNotFoundError, AssetSetSummary, AssetStorageError,
    TestAssetSet, validate_asset_set,
)


logger = logging.getLogger(__name__)


class SQLiteAssetSetRepository:
    def __init__(self, path: Path):
        self.path = path
        with self._connection() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS asset_sets ("
                "asset_set_id TEXT PRIMARY KEY NOT NULL, payload TEXT NOT NULL)"
            )

    @contextmanager
    def _connection(self):
        try:
            with closing(sqlite3.connect(self.path)) as connection:
                with connection:
                    yield connection
        except (sqlite3.Error, OSError) as error:
            logger.error("Asset storage operation failed")
            raise AssetStorageError("Asset storage operation failed") from error

    def save(self, asset_set: TestAssetSet) -> None:
        validated = validate_asset_set(asset_set.model_dump(mode="json"))
        with self._connection() as connection:
            try:
                connection.execute(
                    "INSERT INTO asset_sets (asset_set_id, payload) VALUES (?, ?)",
                    (validated.asset_set_id, validated.model_dump_json()),
                )
            except sqlite3.IntegrityError as error:
                if error.sqlite_errorcode in (
                    sqlite3.SQLITE_CONSTRAINT_PRIMARYKEY, sqlite3.SQLITE_CONSTRAINT_UNIQUE,
                ):
                    logger.warning("Asset set already exists")
                    raise AssetConflictError("Asset set already exists") from error
                raise

    def get(self, asset_set_id: str) -> TestAssetSet:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT asset_set_id, payload FROM asset_sets WHERE asset_set_id = ?",
                (asset_set_id,),
            ).fetchone()
        if row is None:
            logger.warning("Asset set not found")
            raise AssetNotFoundError("Asset set not found")
        return self._decode(row)

    def list(self) -> list[AssetSetSummary]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT asset_set_id, payload FROM asset_sets ORDER BY asset_set_id"
            ).fetchall()
        result = []
        for row in rows:
            asset_set = self._decode(row)
            result.append(AssetSetSummary(
                asset_set_id=asset_set.asset_set_id,
                question_count=len(asset_set.questions), snapshot_count=len(asset_set.snapshots),
                canonical_case_count=len(asset_set.canonical_cases),
                golden_baseline_count=len(asset_set.golden_baselines),
            ))
        return result

    @staticmethod
    def _decode(row) -> TestAssetSet:
        try:
            asset_set = TestAssetSet.model_validate_json(row[1])
            if row[0] != asset_set.asset_set_id:
                raise ValueError("stored asset identity mismatch")
            return asset_set
        except (ValidationError, ValueError) as error:
            logger.error("Stored asset set is invalid")
            raise AssetStorageError("Stored asset set is invalid") from error
