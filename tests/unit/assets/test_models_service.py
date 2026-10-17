from copy import deepcopy

import pytest
from pydantic import ValidationError

from agent_test.domains.assets.api import (
    AssetValidationError, GoldenQuestion, TestAssetSet as AssetSet, load_asset_set,
    load_questions, save_asset_set, validate_asset_set,
)


def test_asset_round_trip_and_schema(asset_payload):
    model = validate_asset_set(asset_payload)
    assert AssetSet.model_validate_json(model.model_dump_json()) == model
    assert "golden_baselines" in AssetSet.model_json_schema()["required"]
    assert model.golden_baselines[0].source.result is None


@pytest.mark.parametrize("source", [
    {"kind": "reference_sql", "sql": "SELECT :value", "parameters": {"value": 0}},
    {"kind": "reference_result", "result": {"value": 0}},
    {"kind": "verified_version_result", "agent_version_ref": "opaque-version-reference",
     "verification_reference": "fixture-only", "result": [False, None, 0]},
])
def test_golden_source_variants(asset_payload, source):
    asset_payload["golden_baselines"][0]["source"] = source
    assert validate_asset_set(asset_payload).model_dump(mode="json")["golden_baselines"][0]["source"] == source


def test_confirmed_semantic_source(asset_payload, canonical_case):
    asset_payload["golden_baselines"][0]["source"] = {"kind": "canonical_case", "case": canonical_case}
    assert validate_asset_set(asset_payload).golden_baselines[0].source.case.case_id == "case-fixture"


@pytest.mark.parametrize("collection", ["questions", "snapshots", "canonical_cases", "golden_baselines"])
def test_duplicate_ids(asset_payload, collection):
    asset_payload[collection].append(deepcopy(asset_payload[collection][0]))
    with pytest.raises(AssetValidationError):
        validate_asset_set(asset_payload)


@pytest.mark.parametrize("collection,field", [
    ("canonical_cases", "question_id"), ("golden_baselines", "question_id"),
    ("golden_baselines", "snapshot_id"),
])
def test_dangling_references(asset_payload, collection, field):
    asset_payload[collection][0][field] = "missing"
    with pytest.raises(AssetValidationError):
        validate_asset_set(asset_payload)


@pytest.mark.parametrize("field,value", [
    ("question_id", " "), ("question", 1), ("expected_behavior", "GUESS"),
    ("expected_time", 2026), ("expected_metric", False), ("version", "V4"),
])
def test_invalid_question(question, field, value):
    question[field] = value
    with pytest.raises(ValidationError):
        GoldenQuestion.model_validate(question)


@pytest.mark.parametrize("field", ["confirmed_by", "confirmation_reference", "snapshot_id"])
def test_missing_confirmation_and_snapshot(asset_payload, field):
    del asset_payload["golden_baselines"][0][field]
    with pytest.raises(AssetValidationError):
        validate_asset_set(asset_payload)


@pytest.mark.parametrize("source", [
    {"kind": "reference_sql", "sql": "SELECT 1"},
    {"kind": "reference_result"},
    {"kind": "verified_version_result", "agent_version_ref": "ref", "result": 0},
    {"kind": "canonical_case", "case": {}}, {"kind": "ai_guess", "result": 1},
])
def test_invalid_golden_source(asset_payload, source):
    asset_payload["golden_baselines"][0]["source"] = source
    with pytest.raises(AssetValidationError):
        validate_asset_set(asset_payload)


def test_snapshot_hash_and_asset_set_version_fields(asset_payload):
    asset_payload["snapshots"][0]["content_sha256"] = "invalid"
    with pytest.raises(AssetValidationError):
        validate_asset_set(asset_payload)
    asset_payload["snapshots"][0]["content_sha256"] = "a" * 64
    assert validate_asset_set(asset_payload).snapshots[0].content_sha256 == "a" * 64
    asset_payload["agent_version"] = "not-part-of-cross-version-assets"
    with pytest.raises(AssetValidationError):
        validate_asset_set(asset_payload)


def test_empty_asset_set_is_not_proof_of_readiness(asset_payload):
    for key in ("questions", "snapshots", "canonical_cases", "golden_baselines"):
        asset_payload[key] = []
    assert validate_asset_set(asset_payload).questions == []


def test_ports_without_io(question, asset_payload):
    class Questions:
        def read(self):
            return [question]

    class Assets:
        def read(self):
            return asset_payload

    assert load_questions(Questions())[0].question_id == question["question_id"]
    assert load_asset_set(Assets()).asset_set_id == "assets-fixture"


def test_question_duplicate_and_schema_errors(question, caplog):
    class Duplicate:
        def read(self):
            return [question, question]

    class Invalid:
        def read(self):
            return [{"question": "sensitive-fixture-not-for-log"}]

    for source in (Duplicate(), Invalid()):
        with pytest.raises(AssetValidationError) as caught:
            load_questions(source)
        assert caught.value.__cause__ is not None
    assert "schema validation failed" in caplog.text
    assert "sensitive-fixture-not-for-log" not in caplog.text


def test_mutated_asset_rejected_before_save(asset_payload):
    class Repository:
        called = False

        def save(self, value):
            self.called = True

    model = validate_asset_set(asset_payload)
    model.golden_baselines[0].snapshot_id = "missing"
    repository = Repository()
    with pytest.raises(AssetValidationError):
        save_asset_set(model, repository)
    assert repository.called is False


def test_rules_approval_preserved(asset_payload):
    from pathlib import Path

    from agent_test.domains.rules.api import load_rules
    from agent_test.infrastructure.files.rule_config import YamlRuleConfigSource

    path = Path(__file__).resolve().parents[3] / "config" / "properties.yml"
    rules = load_rules(YamlRuleConfigSource(path))
    asset_payload["rules"] = rules.model_dump(mode="json")
    model = validate_asset_set(asset_payload)
    assert all(item.approval == "proposed" and item.approved_by is None for item in model.rules.test_rules)
