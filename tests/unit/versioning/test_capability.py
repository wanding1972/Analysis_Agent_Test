import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from agent_test.domains.canonical.api import CanonicalCapabilitySet
from agent_test.domains.versioning.api import VersionNormalizationError, VersionPackageError
from agent_test.infrastructure.version_adapters.v4.capability import V461CapabilityAdapter
from agent_test.infrastructure.version_adapters.v4.package import V461DirectorySource, V461Mapping


FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "versioning" / "v461"


def test_actual_source_fixtures_match_recorded_checksums():
    provenance = json.loads((FIXTURES / "provenance.json").read_text())
    for name, record in provenance["files"].items():
        assert hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest() == record["sha256"]


def test_actual_40_declarations_and_version_alias(package, mapping):
    assert package.version.version_id == "V4.6.1"
    assert package.version.requirement_aliases == ["V4.1"]
    assert package.version.semantic_version == "4.0.0"
    adapter = V461CapabilityAdapter(mapping)
    report = adapter.inspect(package)
    assert len(report.capabilities.capabilities) == 26
    assert len(report.declarations) == 40
    assert adapter.normalize(package) == report.capabilities
    assert CanonicalCapabilitySet.model_validate_json(report.capabilities.model_dump_json()) == report.capabilities
    index = {item.capability_id: item for item in report.capabilities.capabilities}
    assert index["question_1"].metrics == ["sales_volume", "sales_volume_cumulative"]
    assert index["question_1"].subjects == ["ModelVersion"]
    assert "cumulative" in index["question_1"].time_ops
    assert "equippedWith" in index["question_10"].relations
    assert index["question_2"].multi_step is True
    assert "question_32" not in index
    assert "question_40" not in index
    statuses = {item.capability_id: item.declared_status for item in report.declarations}
    assert statuses["question_40"] == "OUT_OF_SCOPE"
    assert statuses["question_33"] == "CALIBRATION_PENDING"
    assert all(item.status_basis == "source_declaration" and item.limitations for item in report.declarations)
    assert "route_any" not in report.capabilities.model_dump_json()
    assert "fanout" not in report.capabilities.model_dump_json()
    assert report.declarations[1].source_metadata["fanout"] == "per_scope"


def test_selection_and_recipe_mapping_are_configured(package, mapping):
    mapping.exposed_statuses.append("PARTIAL")
    report = V461CapabilityAdapter(mapping).inspect(package)
    index = {item.capability_id: item for item in report.capabilities.capabilities}
    assert len(index) == 30
    assert index["question_32"].multi_step is True
    assert next(item for item in report.declarations if item.capability_id == "question_32").declared_status == "PARTIAL"


@pytest.mark.parametrize("failure", ["missing_doc", "wrong_version", "missing_metric", "duplicate_metric",
                                       "unknown_link", "unknown_recipe", "unknown_dimension", "unknown_fanout",
                                       "cycle", "duplicate_capability", "invalid_field", "invalid_status"])
def test_package_normalization_errors(package, mapping, failure, caplog):
    package = deepcopy(package)
    docs = package.documents
    cap = docs["capabilities"]["capabilities"][0]
    if failure == "missing_doc":
        del docs["metrics"]
    elif failure == "wrong_version":
        package.version.version_id = "not-supported"
    elif failure == "missing_metric":
        cap["metric_refs"] = ["not-existing"]
    elif failure == "duplicate_metric":
        docs["metrics"]["metrics"].append(deepcopy(docs["metrics"]["metrics"][0]))
    elif failure == "unknown_link":
        cap["link_refs"] = ["not-existing"]
    elif failure == "unknown_recipe":
        cap["recipe_ref"] = "not-existing"
    elif failure == "unknown_dimension":
        docs["metrics"]["metrics"][0]["supported_dimensions"] = ["not-existing"]
    elif failure == "unknown_fanout":
        cap["fanout"] = "not-existing"
    elif failure == "cycle":
        docs["metrics"]["metrics"][0].pop("measured_at")
        docs["metrics"]["metrics"][0]["base_metric"] = "sales_volume"
    elif failure == "duplicate_capability":
        docs["capabilities"]["capabilities"].append(deepcopy(cap))
    elif failure == "invalid_status":
        cap["declared_status"] = "TYPO"
    else:
        cap["metric_refs"] = "wrong-type"
    with pytest.raises(VersionNormalizationError):
        V461CapabilityAdapter(mapping).normalize(package)
    assert "normalization failed" in caplog.text
    assert "not-existing" not in caplog.text


def test_source_identity_version_and_directory_checks(package, mapping, tmp_path):
    with pytest.raises(VersionPackageError):
        V461DirectorySource(tmp_path, package.version, mapping).read()
    mapping.documents["capabilities"] = "../outside.yml"
    with pytest.raises(VersionPackageError):
        V461DirectorySource(FIXTURES, package.version, mapping).read()


def test_wrong_semantic_version(package, mapping):
    package.version.semantic_version = "wrong"
    with pytest.raises(VersionPackageError):
        V461DirectorySource(FIXTURES, package.version, mapping).read()


@pytest.mark.parametrize("text", ["[", "a: 1\na: 2", "!!python/object/apply:os.system ['unsafe']", "{}"])
def test_mapping_parse_and_schema_errors(tmp_path, text):
    path = tmp_path / "mapping.yml"
    path.write_text(text)
    with pytest.raises(VersionPackageError):
        V461Mapping.load(path)
