from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_test.domains.evaluation.api import (
    EvaluationConfigError, EvaluationPolicy, EvaluationRequest, ReferenceEvidenceError,
    TestResult as EvaluationResult, evaluate, load_policy,
)
from agent_test.domains.rules.api import RuleInputs, TestRule as Rule, check_rule
from agent_test.infrastructure.files.evaluation_config import YamlEvaluationPolicySource


def run(payload, reader=None):
    return evaluate(EvaluationRequest.model_validate(payload), reader)


def layer(result, name):
    return next(item for item in result.layers if item.layer == name)


def test_all_four_layers_and_round_trip(evaluation_request):
    result = evaluate(evaluation_request)
    assert result.status == "passed"
    assert len(result.layers) == 4
    assert all(item.status == "passed" and item.failure_code is None for item in result.layers)
    assert EvaluationResult.model_validate_json(result.model_dump_json()) == result


@pytest.mark.parametrize("field,value", [
    ("metric", "other_metric"), ("scope", {"subject": "other_subject"}),
    ("grain", "other_grain"), ("dimensions", ["extra"]),
    ("time", {"operator": "window", "parameters": {"start": "2025-01"}}),
    ("filters", [{"field": "f", "operator": "eq", "value": 0, "negated": True}]),
    ("relations", [{"relation": "r", "source": "a", "target": "b"}]),
    ("set_operations", [{"operator": "difference", "operand_set_ids": ["a", "b"], "result_set_id": "c"}]),
    ("operation", {"operator": "query", "parameters": {"metrics": ["another", "metric"]}}),
])
def test_semantic_field_failures(request_data, field, value):
    request_data["observation"]["semantic"][field] = value
    result = run(request_data)
    assert layer(result, "semantic").failure_code == "SEMANTIC_ERROR"
    assert result.status == "failed"


@pytest.mark.parametrize("failure", ["dependency", "lost_step", "scope", "empty"])
def test_plan_failures_and_empty_is_blocked(request_data, failure):
    actual = request_data["observation"]
    if failure == "dependency":
        actual["step_dependencies"] = [{"step_id": "s1", "depends_on": "missing"}]
    elif failure == "lost_step":
        actual["steps"] = None
    elif failure == "empty":
        actual["steps"] = []
    else:
        actual["steps"][0]["scope"]["object_set_id"] = "escaped"
    result = layer(run(request_data), "plan")
    assert result.status == ("blocked" if failure in {"lost_step", "empty"} else "failed")
    if failure == "dependency":
        assert any(check.reason == "invalid_plan_structure" for check in result.checks)


def test_golden_result_failure_is_evidence_only(request_data):
    request_data["golden_baseline"]["source"]["result"]["value"] = 99
    result = run(request_data)
    assert layer(result, "evidence").failure_code == "EVIDENCE_ERROR"
    assert layer(result, "answer").status == "passed"


@pytest.mark.parametrize("failure", ["behavior", "claim_value", "claim_source", "condition_loss", "unknown_zero"])
def test_answer_failures(request_data, failure):
    answer = request_data["observation"]["answer"]
    if failure == "behavior":
        answer["behavior"] = "REJECT"
    elif failure == "claim_value":
        answer["claims"][0]["value"] = 999
    elif failure == "claim_source":
        answer["claims"][0]["evidence_id"] = None
    elif failure == "condition_loss":
        answer["conditions"]["scope"] = None
    else:
        request_data["observation"]["evidence"]["result"]["value"] = None
        request_data["golden_baseline"]["source"]["result"]["value"] = None
        answer["claims"][0]["value"] = 0
    result = layer(run(request_data), "answer")
    assert result.failure_code == "ANSWER_ERROR"


@pytest.mark.parametrize("field", ["semantic", "steps", "evidence", "answer"])
def test_missing_layer_input(request_data, field):
    request_data["observation"][field] = None
    names = {"semantic": "semantic", "steps": "plan", "evidence": "evidence", "answer": "answer"}
    assert layer(run(request_data), names[field]).status == "blocked"


@pytest.mark.parametrize("complete", [None, False])
def test_unverified_claim_coverage_blocks(request_data, complete):
    request_data["observation"]["answer"]["claims_complete"] = complete
    assert layer(run(request_data), "answer").status == "blocked"


@pytest.mark.parametrize("failure", ["snapshot", "case", "golden_snapshot", "golden_question", "approval"])
def test_context_gate_before_io(request_data, failure):
    class NoIO:
        def read(self, baseline):
            raise AssertionError("must not perform IO for invalid context")

    request_data["golden_baseline"]["source"] = {"kind": "reference_sql", "sql": "SELECT 10", "parameters": {}}
    if failure == "snapshot":
        request_data["observation"]["snapshot_id"] = "other"
    elif failure == "case":
        request_data["observation"]["case_id"] = "other"
    elif failure == "golden_snapshot":
        request_data["golden_baseline"]["snapshot_id"] = "other"
    elif failure == "golden_question":
        request_data["golden_baseline"]["question_id"] = "other"
    else:
        request_data["policy"]["approval"] = "proposed"
        request_data["policy"]["approved_by"] = None
    result = run(request_data, NoIO())
    assert result.status == "blocked"
    assert all(item.status == "blocked" for item in result.layers)


def test_reference_sql_port_success_failure_and_missing(request_data, caplog):
    request_data["golden_baseline"]["source"] = {"kind": "reference_sql", "sql": "SELECT :value", "parameters": {"value": 10}}

    class Reference:
        def read(self, baseline):
            assert baseline.snapshot_id == "snapshot-fixture"
            return {"value": baseline.source.parameters["value"]}

    class Unavailable:
        def read(self, baseline):
            raise ReferenceEvidenceError("private diagnostic not for log")

    assert run(request_data, Reference()).status == "passed"
    assert layer(run(request_data), "evidence").status == "blocked"
    assert layer(run(request_data, Unavailable()), "evidence").status == "blocked"
    assert "Reference evidence unavailable" in caplog.text
    assert "private diagnostic" not in caplog.text


@pytest.mark.parametrize("invalid", [float("nan"), object()])
def test_invalid_reference_sdk_values_block(request_data, invalid):
    request_data["golden_baseline"]["source"] = {"kind": "reference_sql", "sql": "SELECT 10", "parameters": {}}

    class InvalidReference:
        def read(self, baseline):
            return invalid

    assert layer(run(request_data, InvalidReference()), "evidence").status == "blocked"


def test_verified_version_baseline(request_data):
    request_data["golden_baseline"]["source"] = {
        "kind": "verified_version_result", "agent_version_ref": "opaque-version",
        "verification_reference": "test-fixture-only", "result": {"value": 10}}
    assert layer(run(request_data), "evidence").status == "passed"


def test_required_golden_and_missing_claim_conditions(request_data):
    request_data["golden_baseline"] = None
    request_data["policy"]["evidence"]["require_golden"] = True
    request_data["observation"]["answer"]["claims"][0]["conditions"] = None
    result = run(request_data)
    assert layer(result, "evidence").checks[0].reason == "missing_golden"
    assert layer(result, "answer").status == "blocked"


def test_claim_path_must_exist(request_data):
    request_data["observation"]["evidence"]["references"][0]["path"] = ["missing"]
    result = layer(run(request_data), "answer")
    assert result.status == "blocked"
    assert any(item.reason == "invalid_evidence_path" for item in result.checks)


def test_plan_compares_operation_order(request_data):
    first = deepcopy(request_data["test_case"]["steps"][0])
    second = deepcopy(first)
    second["step_id"] = "s2"
    request_data["test_case"]["steps"] = [first, second]
    request_data["observation"]["steps"] = [second, first]
    assert layer(run(request_data), "plan").failure_code == "PLAN_ERROR"


def test_unordered_dependency_order_is_configurable(request_data):
    root = deepcopy(request_data["test_case"]["steps"][0])
    steps = [dict(root, step_id=name) for name in ("s1", "s2", "s3")]
    dependencies = [{"step_id": "s3", "depends_on": name} for name in ("s1", "s2")]
    request_data["test_case"].update(steps=deepcopy(steps), step_dependencies=dependencies)
    request_data["observation"].update(steps=steps, step_dependencies=list(reversed(dependencies)))
    assert layer(run(request_data), "plan").status == "passed"


def test_evidence_scope_cannot_be_hidden_by_matching_claim(request_data):
    request_data["observation"]["evidence"]["references"][0]["conditions"]["scope"] = None
    request_data["observation"]["answer"]["claims"][0]["conditions"]["scope"] = None
    assert layer(run(request_data), "evidence").failure_code == "EVIDENCE_ERROR"


@pytest.mark.parametrize("step_id", ["s1", "unknown"])
def test_evidence_step_context(request_data, step_id):
    request_data["observation"]["evidence"]["references"][0]["step_id"] = step_id
    assert layer(run(request_data), "evidence").status == ("passed" if step_id == "s1" else "blocked")


def test_skipped_properties_do_not_supply_an_oracle(request_data):
    add_range_rule(request_data)
    request_data["approved_rules"]["test_rules"][0]["preconditions"] = {"v": 999}
    assert layer(run(request_data), "evidence").status == "blocked"


def test_multiple_failures_preserved_and_failure_precedes_blocked(request_data):
    request_data["observation"]["semantic"]["metric"] = "changed"
    request_data["observation"]["steps"][0]["metric"] = "changed"
    request_data["observation"]["evidence"] = None
    request_data["observation"]["answer"]["behavior"] = "REJECT"
    result = run(request_data)
    assert result.status == "failed"
    assert {item.failure_code for item in result.layers if item.failure_code} == {
        "SEMANTIC_ERROR", "PLAN_ERROR", "ANSWER_ERROR"}


def add_range_rule(payload, approval="approved"):
    payload["golden_baseline"] = None
    payload["approved_rules"]["test_rules"] = [{
        "rule_id": "range", "description": "Fixture only", "approval": approval,
        "approved_by": "test-fixture-only" if approval == "approved" else None,
        "category": "property", "preconditions": {},
        "assertion": {"kind": "numeric_range", "value": "v", "minimum": 0, "maximum": 20,
                      "include_minimum": True, "include_maximum": True},
    }]
    payload["policy"]["evidence"]["rule_bindings"] = {"range": {"v": {"source": "result", "path": ["value"]}}}


@pytest.mark.parametrize("mode,expected", [("pass", "passed"), ("fail", "failed"),
    ("unapproved", "blocked"), ("missing_rule", "blocked"), ("missing_fact", "blocked")])
def test_property_rules_bind_to_observed_evidence(request_data, mode, expected):
    add_range_rule(request_data, "proposed" if mode == "unapproved" else "approved")
    if mode == "fail":
        request_data["approved_rules"]["test_rules"][0]["assertion"]["maximum"] = 5
    elif mode == "missing_rule":
        request_data["approved_rules"]["test_rules"] = []
    elif mode == "missing_fact":
        request_data["policy"]["evidence"]["rule_bindings"]["range"]["v"]["path"] = ["missing"]
    assert layer(run(request_data), "evidence").status == expected


def test_empty_oracles_are_not_passed(request_data):
    request_data["golden_baseline"] = None
    result = layer(run(request_data), "evidence")
    assert result.status == "blocked" and result.checks[0].reason == "no_applicable_oracle"


def test_confirmed_semantic_golden_takes_precedence(request_data):
    golden = deepcopy(request_data["test_case"])
    request_data["golden_baseline"]["source"] = {"kind": "canonical_case", "case": golden}
    request_data["test_case"]["metric"] = "untrusted_candidate_change"
    result = run(request_data)
    assert layer(result, "semantic").status == "passed"
    assert layer(result, "evidence").status == "blocked"  # semantic truth is not numeric truth


@pytest.mark.parametrize("behavior", ["CLARIFY", "REJECT"])
def test_configured_nonanswer_workflow(request_data, behavior):
    request_data["test_case"]["expected_behavior"] = behavior
    actual = request_data["observation"]
    actual.update(semantic=None, steps=None, step_dependencies=None, evidence=None)
    actual["answer"].update(behavior=behavior, claims=[], conditions=None)
    request_data["golden_baseline"] = None
    result = run(request_data)
    assert result.status == "passed"
    assert [item.status for item in result.layers[:3]] == ["skipped"] * 3


def test_metamorphic_related_snapshot_and_value(request_data):
    add_range_rule(request_data)
    rule = request_data["approved_rules"]["test_rules"][0]
    rule.update(category="metamorphic", assertion={"kind": "sum_equals", "parts": "parts", "total": "total", "absolute_tolerance": 0})
    request_data["observation"]["evidence"]["result"]["parts"] = [4, 6]
    request_data["policy"]["evidence"]["rule_bindings"] = {"range": {
        "parts": {"source": "result", "path": ["parts"]},
        "total": {"source": "related", "reference": "total", "path": []},
    }}
    request_data["related_evidence"] = {"total": {"snapshot_id": "snapshot-fixture", "bundle": {"result": 10, "references": []}}}
    assert layer(run(request_data), "evidence").status == "passed"
    request_data["related_evidence"]["total"]["snapshot_id"] = "other"
    assert layer(run(request_data), "evidence").status == "blocked"


def test_literal_and_semantic_facts_are_explicit_bindings(request_data):
    add_range_rule(request_data)
    request_data["approved_rules"]["test_rules"][0]["preconditions"] = {"metric": "fixture_metric", "enabled": True}
    facts = request_data["policy"]["evidence"]["rule_bindings"]["range"]
    facts.update(metric={"source": "semantic", "path": ["metric"]}, enabled={"source": "literal", "value": True})
    assert layer(run(request_data), "evidence").status == "passed"


def test_missing_policy_file(tmp_path):
    with pytest.raises(EvaluationConfigError):
        load_policy(YamlEvaluationPolicySource(tmp_path / "missing.yml"))


@pytest.mark.parametrize("kind,left,right,expected", [
    ("json_equal", None, 0, "failed"), ("json_equal", False, 0, "failed"),
    ("json_equal", {"x": 1}, {"x": 1}, "passed"),
    ("unordered_equal", [1, 2], [2, 1], "passed"),
    ("unordered_equal", [1, 1], [1], "failed"),
    ("unordered_equal", [False], [0], "failed"),
    ("unordered_equal", "x", [], "blocked"),
])
def test_new_rule_comparisons(kind, left, right, expected):
    rule = Rule(rule_id="fixture", description="Test only", approval="approved", approved_by="test-fixture-only",
                category="property", preconditions={}, assertion={"kind": kind, "left": "a", "right": "b"})
    assert check_rule(rule, RuleInputs(facts={"a": left, "b": right})).status == expected


def test_policy_loading_errors_and_default_proposed(tmp_path):
    source = Path(__file__).resolve().parents[3] / "config" / "evaluation.yml"
    assert load_policy(YamlEvaluationPolicySource(source)).approval == "proposed"
    for content in ("[", "{}", "a: 1\na: 2"):
        path = tmp_path / "evaluation.yml"
        path.write_text(content)
        with pytest.raises(EvaluationConfigError):
            load_policy(YamlEvaluationPolicySource(path))


@pytest.mark.parametrize("failure", ["precedence", "approval", "field", "extra", "duplicate_evidence", "duplicate_claim"])
def test_schema_errors(request_data, failure):
    if failure == "precedence":
        request_data["policy"]["precedence"] = ["passed"]
    elif failure == "approval":
        request_data["policy"]["approved_by"] = None
    elif failure == "field":
        request_data["policy"]["semantic"]["fields"] = {"route": "json_equal"}
    elif failure == "extra":
        request_data["observation"]["agent_version"] = "no-version-in-core"
    elif failure == "duplicate_evidence":
        request_data["observation"]["evidence"]["references"] *= 2
    else:
        request_data["observation"]["answer"]["claims"] *= 2
    with pytest.raises(ValidationError):
        EvaluationRequest.model_validate(request_data)
