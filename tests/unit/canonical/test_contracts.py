from copy import deepcopy

import pytest
from pydantic import ValidationError

from agent_test.domains.canonical.api import (
    CanonicalCapability, CanonicalCapabilitySet, CanonicalSemanticModel,
    CanonicalTestCase,
)


@pytest.fixture
def case():
    return {
        "case_id": "case-1", "question": "测试问题", "expected_behavior": "ANSWER",
        "metric": "sample_metric", "scope": {"subject": "sample_subject"},
        "grain": None, "dimensions": [], "time": None, "filters": [],
        "relations": [], "set_operations": [], "operation": None,
        "step_dependencies": [],
    }


@pytest.fixture
def capability():
    return {
        "capability_id": "cap-1", "metrics": ["sample_metric"],
        "subjects": ["sample_subject"], "dimensions": [], "time_ops": [],
        "filters": [], "relations": [], "set_ops": [], "operations": [],
        "multi_step": False,
    }


@pytest.mark.parametrize("behavior", ["ANSWER", "CLARIFY", "REJECT"])
def test_case_round_trip(case, behavior):
    case["expected_behavior"] = behavior
    model = CanonicalTestCase.model_validate(case)
    assert CanonicalTestCase.model_validate_json(model.model_dump_json()) == model
    assert model.model_dump()["scope"]["subject"] == "sample_subject"


def test_explicit_unknown_and_zero_are_preserved(case):
    case["metric"] = None
    case["filters"] = [
        {"field": "field", "operator": "op", "value": None, "negated": True},
        {"field": "field", "operator": "op", "value": 0},
    ]
    model = CanonicalTestCase.model_validate(case)
    assert model.filters[0].value is None
    assert model.filters[0].negated is True
    assert model.filters[1].value == 0


@pytest.mark.parametrize("field,value", [
    ("case_id", " "), ("question", 1), ("expected_behavior", "MAYBE"),
    ("dimensions", "dimension"), ("scope", {"subject": ""}),
    ("filters", [{"field": "f", "operator": "o", "value": 0, "negated": "false"}]),
    ("route", "legacy"), ("metric", 42),
])
def test_invalid_case(case, field, value):
    case[field] = value
    with pytest.raises(ValidationError):
        CanonicalTestCase.model_validate(case)


@pytest.mark.parametrize("field", ["metric", "time", "step_dependencies", "case_id"])
def test_required_fields(case, field):
    del case[field]
    with pytest.raises(ValidationError):
        CanonicalTestCase.model_validate(case)


def make_plan(case):
    semantic = {key: case[key] for key in CanonicalSemanticModel.model_fields}
    case["steps"] = [
        dict(deepcopy(semantic), step_id="first", output_object_set_ids=["objects"]),
        dict(deepcopy(semantic), step_id="second", input_object_set_ids=["objects"]),
    ]
    case["steps"][1]["scope"]["object_set_id"] = "objects"
    case["step_dependencies"] = [
        {"step_id": "second", "depends_on": "first", "object_set_id": "objects"}
    ]
    return case


def test_multistep_contract(case):
    model = CanonicalTestCase.model_validate(make_plan(case))
    assert [step.step_id for step in model.steps] == ["first", "second"]
    assert model.steps[1].scope.object_set_id == "objects"
    assert CanonicalTestCase.model_validate_json(model.model_dump_json()) == model


@pytest.mark.parametrize("failure", ["unknown", "self", "cycle", "duplicate_id",
                                         "producer", "consumer", "duplicate_edge"])
def test_broken_plan_references(case, failure):
    case = make_plan(case)
    edge = case["step_dependencies"][0]
    if failure == "unknown":
        edge["depends_on"] = "missing"
    elif failure == "self":
        edge["depends_on"] = "second"
    elif failure == "cycle":
        case["step_dependencies"].append({"step_id": "first", "depends_on": "second"})
    elif failure == "duplicate_id":
        case["steps"][1]["step_id"] = "first"
    elif failure == "producer":
        case["steps"][0]["output_object_set_ids"] = []
    elif failure == "consumer":
        case["steps"][1]["input_object_set_ids"] = []
    else:
        case["step_dependencies"].append(deepcopy(edge))
    with pytest.raises(ValidationError):
        CanonicalTestCase.model_validate(case)


def test_capability_set_round_trip(capability):
    model = CanonicalCapabilitySet.model_validate({"capabilities": [capability]})
    assert CanonicalCapabilitySet.model_validate_json(model.model_dump_json()) == model


@pytest.mark.parametrize("field,value", [("multi_step", "false"), ("metrics", [1]),
                                          ("capability_id", ""), ("version", "V5")])
def test_invalid_capability(capability, field, value):
    capability[field] = value
    with pytest.raises(ValidationError):
        CanonicalCapability.model_validate(capability)


def test_duplicate_capability_id(capability):
    with pytest.raises(ValidationError):
        CanonicalCapabilitySet.model_validate({"capabilities": [capability, capability]})


def test_schemas_and_independent_defaults(case):
    assert "capability_id" in CanonicalCapability.model_json_schema()["required"]
    assert "step_dependencies" in CanonicalTestCase.model_json_schema()["required"]
    first = CanonicalTestCase.model_validate(case)
    second = CanonicalTestCase.model_validate(case)
    first.scope.entity_ids.append("entity")
    assert second.scope.entity_ids == []


def test_rich_semantics_round_trip(case):
    case.update(
        time={"operator": "window", "parameters": {"start": "2026-01"}},
        relations=[{"relation": "linked", "source": "a", "target": "b"}],
        set_operations=[{"operator": "combine", "operand_set_ids": ["a", "b"],
                         "result_set_id": "c"}],
        operation={"operator": "ordered", "parameters": {"count": 7}},
    )
    model = CanonicalTestCase.model_validate(case)
    assert model.model_dump(mode="json")["set_operations"] == case["set_operations"]
    assert CanonicalTestCase.model_validate_json(model.model_dump_json()) == model
