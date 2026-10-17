import json
import sqlite3

import pytest

from agent_test.domains.assets.api import (
    AssetConflictError, AssetNotFoundError, AssetStorageError, get_asset_set,
    list_asset_sets, save_asset_set, validate_asset_set,
)
from agent_test.infrastructure.files.asset_files import JsonAssetSetSource
from agent_test.infrastructure.storage.sqlite_assets import SQLiteAssetSetRepository


def test_persistent_round_trip_and_summary(tmp_path, asset_payload):
    path = tmp_path / "assets.sqlite"
    model = validate_asset_set(asset_payload)
    repository = SQLiteAssetSetRepository(path)
    assert list_asset_sets(repository) == []
    save_asset_set(model, repository)
    reopened = SQLiteAssetSetRepository(path)
    assert get_asset_set(model.asset_set_id, reopened) == model
    assert list_asset_sets(reopened)[0].model_dump() == dict(
        asset_set_id=model.asset_set_id, question_count=1, snapshot_count=1,
        canonical_case_count=1, golden_baseline_count=1,
    )


def test_conflict_preserves_original_and_allows_new_id(tmp_path, asset_payload):
    repository = SQLiteAssetSetRepository(tmp_path / "assets.sqlite")
    original = validate_asset_set(asset_payload)
    save_asset_set(original, repository)
    asset_payload["questions"][0]["note"] = "changed"
    with pytest.raises(AssetConflictError):
        save_asset_set(validate_asset_set(asset_payload), repository)
    assert get_asset_set(original.asset_set_id, repository) == original
    asset_payload["asset_set_id"] = "new-id"
    save_asset_set(validate_asset_set(asset_payload), repository)
    assert len(list_asset_sets(repository)) == 2


def test_not_found_and_parameterized_ids(tmp_path, asset_payload):
    repository = SQLiteAssetSetRepository(tmp_path / "assets.sqlite")
    with pytest.raises(AssetNotFoundError):
        get_asset_set("missing", repository)
    asset_payload["asset_set_id"] = "id'; DROP TABLE asset_sets; --"
    save_asset_set(validate_asset_set(asset_payload), repository)
    assert get_asset_set(asset_payload["asset_set_id"], repository).questions
    assert len(list_asset_sets(repository)) == 1


def test_storage_open_errors_and_missing_table(tmp_path, caplog):
    with pytest.raises(AssetStorageError):
        SQLiteAssetSetRepository(tmp_path / "missing" / "assets.sqlite")
    path = tmp_path / "assets.sqlite"
    repository = SQLiteAssetSetRepository(path)
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE asset_sets")
    with pytest.raises(AssetStorageError):
        repository.get("id")
    with pytest.raises(AssetStorageError):
        repository.list()
    assert "Asset storage operation failed" in caplog.text


@pytest.mark.parametrize("payload", ["not json", "{}", '{"secret": "do-not-log"}'])
def test_corrupt_stored_payload(tmp_path, payload, caplog):
    path = tmp_path / "assets.sqlite"
    repository = SQLiteAssetSetRepository(path)
    with sqlite3.connect(path) as connection:
        connection.execute("INSERT INTO asset_sets VALUES (?, ?)", ("id", payload))
    with pytest.raises(AssetStorageError):
        repository.get("id")
    with pytest.raises(AssetStorageError):
        repository.list()
    assert "do-not-log" not in caplog.text


def test_stored_id_mismatch(tmp_path, asset_payload):
    path = tmp_path / "assets.sqlite"
    repository = SQLiteAssetSetRepository(path)
    with sqlite3.connect(path) as connection:
        connection.execute("INSERT INTO asset_sets VALUES (?, ?)", ("different-id", json.dumps(asset_payload)))
    with pytest.raises(AssetStorageError):
        repository.get("different-id")


def test_failed_write_rolls_back_without_conflict_misclassification(tmp_path, asset_payload):
    path = tmp_path / "assets.sqlite"
    repository = SQLiteAssetSetRepository(path)
    model = validate_asset_set(asset_payload)
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TRIGGER fail_insert AFTER INSERT ON asset_sets "
                           "BEGIN SELECT RAISE(ABORT, 'fixture-only failure'); END")
    with pytest.raises(AssetStorageError) as caught:
        save_asset_set(model, repository)
    assert not isinstance(caught.value, AssetConflictError)
    assert repository.list() == []
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TRIGGER fail_insert")
    save_asset_set(model, repository)
    assert repository.get(model.asset_set_id) == model


def test_json_to_sqlite_workflow(tmp_path, asset_payload):
    from agent_test.domains.assets.api import load_asset_set

    path = tmp_path / "assets.json"
    path.write_text(json.dumps(asset_payload), encoding="utf-8")
    imported = load_asset_set(JsonAssetSetSource(path))
    repository = SQLiteAssetSetRepository(tmp_path / "assets.sqlite")
    save_asset_set(imported, repository)
    assert get_asset_set(imported.asset_set_id, repository).model_dump(mode="json") == asset_payload | {
        "snapshots": [dict(asset_payload["snapshots"][0], description=None, content_sha256=None)],
        "canonical_cases": [dict(asset_payload["canonical_cases"][0], case=imported.canonical_cases[0].case.model_dump(mode="json"))],
    }
