from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_test.domains.canonical.api import CanonicalSemanticModel
from agent_test.domains.rules.api import (
    CompatibilityContext, CompatibilityRule, RuleConfigError, RuleInputs,
    RuleSet, RuleStatus, TestRule as Rule, check_compatibility, check_rule, load_rules,
)
from agent_test.infrastructure.files.rule_config import YamlRuleConfigSource


ROOT = Path(__file__).resolve().parents[3]


def rule(assertion, **overrides):
    payload = dict(rule_id="fixture", description="Test fixture, not business approval",
                   approval="approved", approved_by="test-fixture-only", category="property",
                   preconditions={}, assertion=assertion)
    payload.update(overrides)
    return Rule.model_validate(payload)


def outcome(assertion, facts, **overrides):
    return check_rule(rule(assertion, **overrides), RuleInputs(facts=facts))


@pytest.fixture
def semantic():
    return dict(metric="metric-a", scope={"subject": "subject-a"}, grain="grain-a",
                dimensions=["dimension-a"], time={"operator": "time-a"}, filters=[],
                relations=[], set_operations=[], operation=None)


@pytest.mark.parametrize("value,status", [(0, "passed"), (100, "passed"),
                                          (50.2, "passed"), (-1, "failed"), (101, "failed")])
def test_configured_range(value, status):
    assertion = dict(kind="numeric_range", value="value", minimum=0, maximum=100,
                     include_minimum=True, include_maximum=True)
    assert outcome(assertion, {"value": value}).status == status


def test_config_changes_result_and_endpoint_policy():
    assertion = dict(kind="numeric_range", value="x", minimum=0, maximum=1,
                     include_minimum=True, include_maximum=True)
    assert outcome(assertion, {"x": 1}).status == "passed"
    assertion["include_maximum"] = False
    assert outcome(assertion, {"x": 1}).status == "failed"
    assertion["maximum"] = 2
    assert outcome(assertion, {"x": 1}).status == "passed"
    assertion["include_minimum"] = False
    assert outcome(assertion, {"x": 0}).status == "failed"


@pytest.mark.parametrize("value", [True, "0", None, [], {}])
def test_invalid_number_is_blocked(value, caplog):
    assertion = dict(kind="numeric_range", value="x", minimum=0, maximum=1,
                     include_minimum=True, include_maximum=True)
    result = outcome(assertion, {"x": value})
    assert result.status == "blocked" and result.reason == "invalid_input"
    assert "Invalid input for rule" in caplog.text


@pytest.mark.parametrize("items,limit,status", [([], 0, "passed"), ([1], 1, "passed"),
    ([1, 2], 1, "failed"), ([1], -1, "blocked"), ([1], True, "blocked"),
    ([1], 1.0, "blocked"), ("items", 1, "blocked")])
def test_count_limit(items, limit, status):
    assert outcome(dict(kind="count_limit", items="items", limit="limit"),
                   {"items": items, "limit": limit}).status == status


@pytest.mark.parametrize("kind,left,right,status", [
    ("subset", [1], [1, 2], "passed"), ("subset", [], [], "passed"),
    ("subset", [3], [1, 2], "failed"), ("subset", [False], [0], "failed"),
    ("subset", [{"id": "a"}], [{"id": "a"}], "passed"),
    ("disjoint", [1], [2], "passed"), ("disjoint", [1], [1], "failed"),
    ("disjoint", [], [], "passed"), ("disjoint", [None], [0], "passed"),
])
def test_set_assertions(kind, left, right, status):
    fields = {"subset": "left", "superset": "right"} if kind == "subset" else {
        "left": "left", "right": "right"}
    assert outcome(dict(kind=kind, **fields), {"left": left, "right": right}).status == status


@pytest.mark.parametrize("left,right,status", [(None, 0, "passed"), (0, 0, "failed"),
    ({"value": False}, {"value": 0}, "passed")])
def test_distinct_preserves_unknown_and_types(left, right, status):
    assert outcome(dict(kind="distinct", left="a", right="b"),
                   {"a": left, "b": right}).status == status


@pytest.mark.parametrize("parts,total,tolerance,status", [
    ([0.1, 0.2], 0.3, 0, "passed"), ([1, 2], 4, 0, "failed"),
    ([1, 2], 3.01, 0.01, "passed"), ([1, 2], 3.01, 0.001, "failed"),
    ([], 0, 0, "passed"), ([True], 1, 0, "blocked"), (None, 0, 0, "blocked"),
])
def test_sum_relation(parts, total, tolerance, status):
    assertion = dict(kind="sum_equals", parts="parts", total="total", absolute_tolerance=tolerance)
    assert outcome(assertion, {"parts": parts, "total": total}).status == status


def test_semantic_equality_field_selection_and_validation(semantic):
    other = deepcopy(semantic)
    other["grain"] = "grain-b"
    assertion = dict(kind="semantic_equal", left="a", right="b", fields=["metric"])
    facts = {"a": semantic, "b": other}
    assert outcome(assertion, facts).status == "passed"
    assertion["fields"] = ["metric", "grain"]
    assert outcome(assertion, facts).status == "failed"
    other["route"] = "not-canonical"
    assert outcome(assertion, facts).reason == "invalid_input"


def test_semantic_equality_preserves_nested_types(semantic):
    semantic["operation"] = {"operator": "op", "parameters": {"p": False}}
    other = deepcopy(semantic)
    other["operation"]["parameters"]["p"] = 0
    assert outcome(dict(kind="semantic_equal", left="a", right="b", fields=["operation"]),
                   {"a": semantic, "b": other}).status == "failed"


def test_approval_preconditions_missing_input():
    assertion = dict(kind="distinct", left="a", right="b")
    facts = {"a": None, "b": 0, "complete": True}
    assert outcome(assertion, facts, approval="proposed", approved_by=None).reason == "not_approved"
    assert outcome(assertion, facts, approval="retired").reason == "not_approved"
    assert outcome(assertion, facts, preconditions={"complete": True}).status == "passed"
    assert outcome(assertion, facts, preconditions={"complete": False}).status == "skipped"
    assert outcome(assertion, facts, preconditions={"missing": True}).reason == "missing_input"
    assert outcome(assertion, {"a": None}).reason == "missing_input"
    assert outcome(assertion, facts, preconditions={"complete": 1}).status == "skipped"


@pytest.mark.parametrize("assertion", [
    {"kind": "eval", "expression": "True"},
    {"kind": "sum_equals", "parts": "a", "total": "b", "absolute_tolerance": -1},
    {"kind": "numeric_range", "value": "a", "minimum": 2, "maximum": 1,
     "include_minimum": True, "include_maximum": True},
    {"kind": "numeric_range", "value": "a", "minimum": False, "maximum": 1,
     "include_minimum": True, "include_maximum": True},
    {"kind": "semantic_equal", "left": "a", "right": "b", "fields": ["route"]},
    {"kind": "subset", "subset": "", "superset": "a"},
])
def test_invalid_assertion_schema(assertion):
    with pytest.raises(ValidationError):
        rule(assertion)


def test_approval_and_duplicate_id_schema():
    assertion = dict(kind="distinct", left="a", right="b")
    with pytest.raises(ValidationError):
        rule(assertion, approved_by=None)
    approved = rule(assertion)
    with pytest.raises(ValidationError):
        RuleSet(schema_version="1", compatibility_rules=[], test_rules=[approved, approved])


FAMILIES = [
    ("metric_scope_rules", "subject", "subject-a"),
    ("metric_grain_rules", "grain", "grain-a"),
    ("metric_dimension_rules", "dimensions", "dimension-a"),
    ("metric_time_rules", "time_op", "time-a"),
    ("join_cardinality_rules", "join_cardinality", "one-to-one"),
    ("aggregation_rules", "aggregation", "aggregate-a"),
    ("denominator_rules", "denominator_scope", "scope-a"),
    ("relation_rules", "relations", "relation-a"),
]


def compatibility_rule(family="metric_scope_rules", axis="subject", allowed="subject-a", **overrides):
    payload = dict(rule_id="compat", description="Fixture", approval="approved",
                   approved_by="test-fixture-only", family=family,
                   when=[{"axis": "metric", "allowed": ["metric-a"]}],
                   require=[{"axis": axis, "allowed": [allowed]}])
    payload.update(overrides)
    return CompatibilityRule.model_validate(payload)


@pytest.mark.parametrize("family,axis,allowed", FAMILIES)
def test_compatibility_families(semantic, family, axis, allowed):
    semantic["relations"] = [{"relation": "relation-a", "source": "a", "target": "b"}]
    context = CompatibilityContext(join_cardinality="one-to-one", aggregation="aggregate-a",
                                   denominator_scope="scope-a")
    model = CanonicalSemanticModel.model_validate(semantic)
    rules = [compatibility_rule(family, axis, allowed)]
    assert check_compatibility(model, rules, context)[0].status == "passed"
    rules = [compatibility_rule(family, axis, "other")]
    assert check_compatibility(model, rules, context)[0].status == "failed"


def test_compatibility_missing_skipped_unapproved_empty(semantic):
    model = CanonicalSemanticModel.model_validate(semantic)
    context = CompatibilityContext()
    assert check_compatibility(model, [], context) == []
    proposed = compatibility_rule(approval="proposed", approved_by=None)
    assert check_compatibility(model, [proposed], context)[0].reason == "not_approved"
    other = compatibility_rule(when=[{"axis": "metric", "allowed": ["other"]}])
    assert check_compatibility(model, [other], context)[0].status == "skipped"
    missing = compatibility_rule(axis="aggregation", allowed="anything")
    assert check_compatibility(model, [missing], context)[0].reason == "missing_input"
    semantic["metric"] = None
    model = CanonicalSemanticModel.model_validate(semantic)
    assert check_compatibility(model, [compatibility_rule()], context)[0].reason == "missing_input"


def test_all_config_files_validate_and_remain_unapproved():
    counts = {}
    for name in ("semantic_rules", "properties", "metamorphic"):
        rules = load_rules(YamlRuleConfigSource(ROOT / "config" / f"{name}.yml"))
        assert RuleSet.model_validate_json(rules.model_dump_json()) == rules
        counts[name] = len(rules.test_rules)
        for item in rules.test_rules:
            assert check_rule(item, RuleInputs(facts={})).reason == "not_approved"
    assert counts == {"semantic_rules": 0, "properties": 7, "metamorphic": 5}


@pytest.mark.parametrize("text", [
    "[", "[]", "", "schema_version: '1'\nschema_version: '2'",
    "!!python/object/apply:os.system ['echo unsafe']", "a: 1\n---\nb: 2", "1: value",
])
def test_invalid_yaml_has_stable_error(tmp_path, text, caplog):
    path = tmp_path / "rules.yml"
    path.write_text(text)
    with pytest.raises(RuleConfigError, match="Unable to read") as caught:
        load_rules(YamlRuleConfigSource(path))
    assert caught.value.__cause__ is not None
    assert "Unable to read rule configuration" in caplog.text
    assert "echo unsafe" not in caplog.text


def test_missing_file_and_invalid_encoding(tmp_path):
    path = tmp_path / "rules.yml"
    with pytest.raises(RuleConfigError):
        load_rules(YamlRuleConfigSource(path))
    path.write_bytes(b"\xff")
    with pytest.raises(RuleConfigError):
        load_rules(YamlRuleConfigSource(path))


def test_schema_failure_and_domain_port_without_files(caplog):
    class MemorySource:
        def read(self):
            return {"schema_version": "1", "compatibility_rules": [], "test_rules": []}

    assert load_rules(MemorySource()).test_rules == []

    class InvalidSource:
        def read(self):
            return {"secret-like-input": "do-not-log-this"}

    with pytest.raises(RuleConfigError, match="schema"):
        load_rules(InvalidSource())
    assert "schema validation failed" in caplog.text
    assert "do-not-log-this" not in caplog.text


def test_rule_outcome_json_contract():
    result = outcome(dict(kind="distinct", left="a", right="b"), {"a": None, "b": 0})
    assert result.status is RuleStatus.PASSED
    assert type(result).model_validate_json(result.model_dump_json()) == result


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_facts_rejected(value):
    with pytest.raises(ValidationError):
        RuleInputs(facts={"value": value})


def test_mutated_rule_is_revalidated():
    model = rule(dict(kind="sum_equals", parts="p", total="t", absolute_tolerance=0))
    model.assertion.absolute_tolerance = -1
    with pytest.raises(ValidationError):
        check_rule(model, RuleInputs(facts={"p": [], "t": 0}))


@pytest.mark.parametrize("rule_id,facts", [
    ("installation_rate_range", {"metric": "installation_rate", "unit": "percent",
                                  "installation_rate": 50}),
    ("top_n_max_count", {"top_n": ["a"], "requested_n": 1}),
    ("top_n_subset", {"top_n": ["a"], "source_set": ["a", "b"]}),
    ("unknown_not_zero", {"unknown_value": None, "zero_value": 0}),
    ("object_set_containment", {"queried_objects": ["a"], "source_objects": ["a"]}),
    ("intersection_subset", {"intersection": ["a"], "set_a": ["a", "b"]}),
    ("difference_disjoint", {"difference": ["a"], "set_b": ["b"]}),
    ("annual_equals_month_sum", {"months_complete": True, "monthly_values": [1, 2],
                                 "annual_value": 3}),
    ("group_sum_equals_total", {"groups_complete": True, "group_values": [1, 2],
                               "total_value": 3}),
    ("top10_subset_top20", {"same_ordering": True, "same_source": True,
                            "top10": ["a"], "top20": ["a", "b"]}),
    ("filtered_subset_original", {"same_source": True, "filtered_set": ["a"],
                                  "original_set": ["a", "b"]}),
])
def test_saved_candidate_bindings_with_test_only_approval(rule_id, facts):
    # Production files remain proposed. Approval here belongs only to a test fixture.
    rules = [item for name in ("properties", "metamorphic")
             for item in load_rules(YamlRuleConfigSource(ROOT / "config" / f"{name}.yml")).test_rules]
    candidate = next(item for item in rules if item.rule_id == rule_id)
    fixture = candidate.model_dump()
    fixture.update(approval="approved", approved_by="test-fixture-only")
    approved = Rule.model_validate(fixture)
    assert check_rule(approved, RuleInputs(facts=facts)).status == "passed"
    assert check_rule(approved, RuleInputs(facts={})).status == "blocked"


def test_saved_semantic_candidate_with_test_only_approval(semantic):
    candidate = load_rules(YamlRuleConfigSource(ROOT / "config" / "metamorphic.yml")).test_rules[-1]
    fixture = candidate.model_dump()
    fixture.update(approval="approved", approved_by="test-fixture-only")
    approved = Rule.model_validate(fixture)
    facts = {"baseline_semantic": semantic, "paraphrase_semantic": deepcopy(semantic)}
    assert check_rule(approved, RuleInputs(facts=facts)).status == "passed"
    facts["paraphrase_semantic"]["filters"] = [
        {"field": "f", "operator": "op", "value": 0, "negated": True}
    ]
    assert check_rule(approved, RuleInputs(facts=facts)).status == "failed"


@pytest.mark.parametrize("axis", ["version", "route", "shape"])
def test_version_specific_axes_rejected(axis):
    with pytest.raises(ValidationError):
        compatibility_rule(axis=axis)
