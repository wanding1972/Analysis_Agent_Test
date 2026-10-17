import json
from copy import deepcopy
from pathlib import Path

import pytest

from agent_test.domains.canonical.api import CanonicalTestCase, SemanticTime
from agent_test.domains.versioning.api import VersionNormalizationError
from agent_test.infrastructure.version_adapters.v4.task import V461PlanAdapter


FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "versioning" / "v461"


def task():
    return json.loads((FIXTURES / "repo4_query_task.json").read_text())


def normalize(mapping, bindings, steps):
    return V461PlanAdapter(mapping).normalize(case_id="fixture-case", question="测试用例",
        expected_behavior="ANSWER", steps=steps, bindings=bindings)


def test_real_querytask_example(mapping, bindings):
    result = normalize(mapping, bindings, [{"step_id": "s1", "task": task()}])
    assert result.metric == "sales_volume"
    assert result.scope.entity_ids == ["fixture-VW"]
    assert result.time.parameters["start"] == "2025-01"
    assert result.time.parameters["end"] == "2025-12"
    assert result.grain is None  # temporal grain is not subject grain
    assert CanonicalTestCase.model_validate_json(result.model_dump_json()) == result
    assert "security_context" not in result.model_dump_json()
    assert "question_ref" not in result.model_dump_json()


def test_real_package_smoke_querytask(mapping, bindings):
    raw = json.loads((FIXTURES / "smoke.query-task.json").read_text())
    result = normalize(mapping, bindings, [{"step_id": "s1", "task": raw}])
    assert result.relations[0].relation == "equippedWith"
    assert [item.field for item in result.filters] == ["powertrain", "segment"]
    assert result.operation.parameters["traversal"]["scope"] == "counted"
    assert result.operation.parameters["traversal"]["target_ids"] == ["fixture-screen"]


def plan():
    first = task()
    first.update(intent="rank", limit=3, emit_object_set="os_rank")
    second = task()
    second.update(task_id="second", subjects=[{"object_set_ref": "os_rank"}])
    return [{"step_id": "rank", "task": first, "emits": "os_rank", "final": False},
            {"step_id": "query", "task": second, "depends_on": ["rank"], "consumes": ["os_rank"]}]


def test_multistep_objectset_identity_and_order(mapping, bindings):
    result = normalize(mapping, bindings, plan())
    assert result.operation.operator == "sequence"
    assert [item.step_id for item in result.steps] == ["rank", "query"]
    assert result.steps[0].output_object_set_ids == ["os_rank"]
    assert result.steps[1].scope.object_set_id == "os_rank"
    assert result.steps[1].input_object_set_ids == ["os_rank"]
    assert result.steps[0].operation.parameters["result_included"] is False
    assert any(edge.object_set_id == "os_rank" and edge.depends_on == "rank" for edge in result.step_dependencies)


def test_competitor_basket_filter_binding_contract(mapping, bindings):
    # Export-shaped fixture based on actual recipes.py PlanStep construction;
    # not a trace claimed to have been executed by the supplied Agent.
    source = plan()
    source[0]["emits"] = "os_anchor"
    source[0]["task"]["emit_object_set"] = "os_anchor"
    source[1]["task"]["subjects"] = []
    source[1].update(consumes=["os_anchor"], filters_from_set="os_anchor",
                     filter_dims=[["segment", "级别"], ["powertrain", "动力类型"]])
    result = normalize(mapping, bindings, source)
    binding = result.steps[1].operation.parameters["filter_binding"]
    assert binding["source_object_set_id"] == "os_anchor"
    assert binding["fields"] == [{"attribute": "segment", "dimension": "segment"},
                                  {"attribute": "powertrain", "dimension": "powertrain"}]
    assert any(edge.object_set_id == "os_anchor" for edge in result.step_dependencies)


@pytest.mark.parametrize("operator,fields,expected,negated", [
    ("ne", {"value_text": "BEV"}, "BEV", True),
    ("not_in", {"values_text": ["BEV", "ICE"]}, ["BEV", "ICE"], True),
    ("between", {"range_low": "BEV", "range_high": "ICE"}, ["BEV", "ICE"], False),
])
def test_filter_mapping_is_configured(mapping, bindings, operator, fields, expected, negated):
    source = task()
    source["filters"] = [{"field_text": "动力类型", "op": operator, **fields}]
    result = normalize(mapping, bindings, [{"step_id": "s1", "task": source}])
    assert result.filters[0].value == expected
    assert result.filters[0].negated is negated


def test_multi_metric_and_multi_subject_are_preserved(mapping, bindings):
    source = task()
    source["metrics"].append("车型数")
    source["subjects"].append({"text": "ModelVersion"})
    result = normalize(mapping, bindings, [{"step_id": "s1", "task": source}])
    assert result.metric is None and result.scope is None
    assert result.operation.parameters["metrics"] == ["sales_volume", "model_count"]
    assert len(result.operation.parameters["scopes"]) == 2


def test_comparison_operands_pairs_and_negation(mapping, bindings):
    source = task()
    source.update(intent="compare", comparison={
        "operands": [
            {"ref": "a", "subjects": [{"text": "大众"}]},
            {"ref": "b", "filters": [{"field_text": "动力类型", "op": "ne", "value_text": "BEV"}]},
        ], "pairs": [["a", "b"]], "mode": "delta",
    })
    result = normalize(mapping, bindings, [{"step_id": "s1", "task": source}])
    comparison = result.operation.parameters["comparison"]
    assert comparison["pairs"] == [["a", "b"]] and comparison["mode"] == "delta"
    assert comparison["operands"][1]["semantic"]["filters"][0]["negated"] is True


def test_set_algebra_preserves_operand_order(mapping, bindings):
    source = task()
    source.update(intent="set_algebra", emit_object_set="result-set", relation={
        "link_text": "搭载", "target_texts": ["副驾屏", "导航"], "set_op": "difference"})
    result = normalize(mapping, bindings, [{"step_id": "s1", "task": source}])
    assert result.set_operations[0].operand_set_ids == ["fixture-screen-set", "fixture-nav-set"]
    assert result.set_operations[0].result_set_id == "result-set"
    assert result.set_operations[0].operator == "difference"


def test_explicit_time_interval_and_order(mapping, bindings):
    source = task()
    source.update(time={"start": "2025-01", "end": "2025-12", "op": "by_month"},
                  order={"by": "metric", "key": "销量", "direction": "asc"})
    result = normalize(mapping, bindings, [{"step_id": "s1", "task": source}])
    assert result.time.operator == "by_month"
    assert result.time.parameters == {"start": "2025-01", "end": "2025-12", "grain": "month"}
    assert result.operation.parameters["order"] == {"by": "metric", "key": "sales_volume", "direction": "asc"}


@pytest.mark.parametrize("time", [
    {"text": "2025年", "grain": "year", "op": "since_launch"},
    {"text": "2025年", "grain": "year", "op": "total", "since_launch_months": 3},
    {"text": "2025年", "grain": "year", "op": "total", "start": "2024-01", "end": "2024-12"},
    {"text": "2025年", "op": "total"},  # month default disagrees with explicit year binding
    {"start": "2025-01", "end": "2024-12"},
    {"start": "2025-01", "end": "2025-12", "op": "invented"},
])
def test_time_binding_and_source_schema_errors(mapping, bindings, time):
    source = task()
    source["time"] = time
    with pytest.raises(VersionNormalizationError):
        normalize(mapping, bindings, [{"step_id": "s1", "task": source}])


def test_explicit_external_set_reference(mapping, bindings):
    source = task()
    source["subjects"] = [{"object_set_ref": "os_rank"}]
    bindings.external_object_set_ids = ["os_rank"]
    result = normalize(mapping, bindings, [{"step_id": "s1", "task": source, "consumes": ["os_rank"]}])
    assert result.steps[0].input_object_set_ids == ["os_rank"]
    assert result.step_dependencies == []


def test_subject_hint_is_not_silently_dropped(mapping, bindings):
    bindings.subject_type_hints["车型"] = "wrong-type"
    with pytest.raises(VersionNormalizationError):
        normalize(mapping, bindings, [{"step_id": "s1", "task": task()}])


@pytest.mark.parametrize("failure", ["unknown_operand", "duplicate_operand", "multiple_metrics"])
def test_comparison_schema_errors(mapping, bindings, failure):
    source = task()
    source.update(intent="compare", comparison={"operands": [{"ref": "a"}, {"ref": "b"}], "pairs": [["a", "b"]]})
    if failure == "unknown_operand":
        source["comparison"]["pairs"] = [["a", "missing"]]
    elif failure == "duplicate_operand":
        source["comparison"]["operands"][1]["ref"] = "a"
    else:
        source["metrics"].append("车型数")
    with pytest.raises(VersionNormalizationError):
        normalize(mapping, bindings, [{"step_id": "s1", "task": source}])


def test_set_operation_requires_explicit_operand_identity(mapping, bindings):
    source = task()
    source.update(intent="set_algebra", emit_object_set="result-set", relation={
        "link_text": "搭载", "target_texts": ["副驾屏", "导航"], "set_op": "intersect"})
    bindings.relation_operand_set_ids = {}
    with pytest.raises(VersionNormalizationError):
        normalize(mapping, bindings, [{"step_id": "s1", "task": source}])


def test_subject_names_from_set_are_preserved_as_binding(mapping, bindings):
    source = plan()
    source[1]["task"]["subjects"] = []
    source[1]["subjects_from_set"] = "os_rank"
    result = normalize(mapping, bindings, source)
    assert result.steps[1].operation.parameters["subject_binding"] == {"source_object_set_id": "os_rank"}
    assert result.steps[1].input_object_set_ids == ["os_rank"]


def test_since_launch_month_count_is_preserved(mapping, bindings):
    source = task()
    source["time"] = {"text": "上市前三月", "op": "since_launch", "since_launch_months": 3}
    bindings.times["上市前三月"] = SemanticTime(operator="since_launch", parameters={
        "start": "2025-01", "end": "2025-03", "grain": "month", "since_launch_months": 3})
    result = normalize(mapping, bindings, [{"step_id": "s1", "task": source}])
    assert result.time.parameters["since_launch_months"] == 3


def test_duplicate_task_ids_rejected(mapping, bindings):
    source = plan()
    source[1]["task"]["task_id"] = source[0]["task"]["task_id"]
    with pytest.raises(VersionNormalizationError):
        normalize(mapping, bindings, source)


def test_unknown_arguments_are_not_passed_to_canonical(mapping, bindings):
    source = task()
    source["params"] = {"source_parameter": "raw-value"}
    with pytest.raises(VersionNormalizationError):
        normalize(mapping, bindings, [{"step_id": "s1", "task": source}])
    mapping.argument_names["source_parameter"] = "canonical_parameter"
    bindings.argument_values["source_parameter"] = {"raw-value": 0}
    result = normalize(mapping, bindings, [{"step_id": "s1", "task": source}])
    assert result.operation.parameters["arguments"] == {"canonical_parameter": 0}


def test_output_and_direction_vocabulary_is_normalized(mapping, bindings):
    source = json.loads((FIXTURES / "smoke.query-task.json").read_text())
    source["relation"]["direction"] = "REVERSE"
    source["output_kind"] = "group_rows"
    result = normalize(mapping, bindings, [{"step_id": "s1", "task": source}])
    assert result.operation.parameters["output"] == "table"
    assert result.operation.parameters["traversal"]["direction"] == "reverse"


@pytest.mark.parametrize("failure", ["forward", "cycle", "missing_consumes", "missing_producer",
    "missing_dependency", "mismatched_emits", "duplicate_output", "duplicate_step", "missing_binding",
    "unknown_field", "invalid_filter", "invalid_time", "wrong_time_operator", "missing_rank_limit"])
def test_major_plan_errors(mapping, bindings, failure, caplog):
    source = deepcopy(plan())
    if failure in {"forward", "cycle"}:
        source[0]["depends_on"] = ["query"]
    elif failure == "missing_consumes":
        source[1]["consumes"] = []
    elif failure == "missing_producer":
        source[0]["emits"] = None
        source[0]["task"].pop("emit_object_set")
    elif failure == "missing_dependency":
        source[1]["depends_on"] = []
    elif failure == "mismatched_emits":
        source[0]["emits"] = "other"
    elif failure == "duplicate_output":
        source[1]["emits"] = "os_rank"
    elif failure == "duplicate_step":
        source[1]["step_id"] = "rank"
    elif failure == "missing_binding":
        bindings.metrics = {}
    elif failure == "unknown_field":
        source[0]["task"]["SQL"] = "never-execute"
    elif failure == "invalid_filter":
        source[0]["task"]["filters"] = [{"field_text": "级别", "op": "in", "value_text": "A"}]
    elif failure == "invalid_time":
        source[0]["task"]["time"] = {"start": "2025-13", "end": "2025-14"}
    elif failure == "wrong_time_operator":
        bindings.times["2025年"].operator = "yoy"
    else:
        source[0]["task"].pop("limit")
    with pytest.raises(VersionNormalizationError):
        normalize(mapping, bindings, source)
    assert "normalization failed" in caplog.text
    assert "never-execute" not in caplog.text
