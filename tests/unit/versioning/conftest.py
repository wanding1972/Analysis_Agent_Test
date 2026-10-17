import json
from pathlib import Path

import pytest

from agent_test.domains.versioning.api import AgentVersion
from agent_test.infrastructure.version_adapters.v4.package import V461DirectorySource, V461Mapping
from agent_test.infrastructure.version_adapters.v4.task import V461SemanticBindings


ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "tests" / "fixtures" / "versioning" / "v461"


@pytest.fixture
def mapping():
    return V461Mapping.load(ROOT / "config" / "versioning" / "v461.yml")


@pytest.fixture
def package(mapping):
    provenance = json.loads((FIXTURES / "provenance.json").read_text())
    version = AgentVersion(version_id="V4.6.1", requirement_aliases=["V4.1"],
                           source_reference=provenance["archive_name"],
                           source_sha256=provenance["archive_sha256"], semantic_version="4.0.0")
    return V461DirectorySource(FIXTURES, version, mapping).read()


@pytest.fixture
def bindings():
    # Explicit test bindings, not approved QA truth or evidence of Agent resolution.
    return V461SemanticBindings(
        metrics={"销量": "sales_volume", "车型数": "model_count"},
        subjects={"大众": {"subject": "ModelVersion", "entity_ids": ["fixture-VW"]},
                  "ModelVersion": {"subject": "ModelVersion"}},
        subject_type_hints={"车型": "ModelVersion"},
        dimensions={"级别": "segment", "动力类型": "powertrain"},
        attributes={"级别": "segment", "动力类型": "powertrain", "segment": "segment", "powertrain": "powertrain"},
        values={"级别": {"A": "A", "B": "B"}, "动力类型": {"BEV": "BEV", "ICE": "ICE"}},
        relations={"搭载": {"relation": "equippedWith", "source": "ModelVersion", "target": "Feature"}},
        entities={"副驾屏": "fixture-screen", "导航": "fixture-nav"},
        times={"2025年": {"operator": "total", "parameters": {"start": "2025-01", "end": "2025-12", "grain": "year"}}},
        object_set_subjects={"os_anchor": "ModelVersion", "os_rank": "ModelVersion"},
        default_scope={"subject": "ModelVersion"}, external_object_set_ids=[],
        relation_operand_set_ids={"副驾屏": "fixture-screen-set", "导航": "fixture-nav-set"},
    )
