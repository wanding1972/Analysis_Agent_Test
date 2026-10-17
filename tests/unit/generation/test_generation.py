from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_test.domains.generation.api import (
    CandidateDesignError, CombinationDesignError, GenerationBatch, GenerationConfigError,
    GenerationRequest, ProposalBatch, generate, load_policy,
)
from agent_test.infrastructure.files.generation_config import YamlGenerationPolicySource
from agent_test.infrastructure.generation.allpairs import AllPairsDesigner


def run(payload, designer=None, combinations=None):
    return generate(GenerationRequest.model_validate(payload), combinations or AllPairsDesigner(), designer)


def test_pairwise_candidates_preserve_semantic_plan_and_inputs(request_data):
    original = deepcopy(request_data)
    batch = run(request_data)
    assert batch.status == "ready" and len(batch.candidates) == 4
    assert batch.sampling[0].backend_exhausted is True
    assert batch.constrained_coverage_verified is False
    assert request_data == original
    assert GenerationBatch.model_validate_json(batch.model_dump_json()) == batch
    assert {item.case.metric for item in batch.candidates} == {"m1", "m2"}
    for item in batch.candidates:
        assert item.status == "candidate" and item.source == "deterministic"
        assert item.case.metric == item.case.steps[0].metric
        assert item.case.scope == item.case.steps[0].scope
        assert all(outcome.status == "passed" for outcome in item.compatibility)
    assert [item.case.case_id for item in batch.candidates] == [item.case.case_id for item in run(request_data).candidates]


def third_axis(request_data):
    template = request_data["policy"]["templates"][0]
    template["question_template"] += " {dimension}"
    template["axes"].append({"name": "dimension", "targets": [{"step_id": None}, {"step_id": "step"}],
                            "options": [{"label": value, "patch": {"dimensions": [value]}} for value in ("d1", "d2")]})


def test_configured_high_risk_strength(request_data):
    third_axis(request_data)
    pairs = run(request_data)
    request_data["policy"]["high_risk_capability_ids"] = ["cap"]
    triples = run(request_data)
    assert len(pairs.candidates) == 4
    assert len(triples.candidates) == 8
    assert triples.sampling[0].requested_strength == 3


def constrain_diagonal(request_data):
    base = request_data["rules"]["compatibility_rules"][0]
    other = deepcopy(base)
    base.update(when=[{"axis": "metric", "allowed": ["m1"]}], require=[{"axis": "subject", "allowed": ["s1"]}])
    other.update(rule_id="compat-other", when=[{"axis": "metric", "allowed": ["m2"]}],
                 require=[{"axis": "subject", "allowed": ["s2"]}])
    request_data["rules"]["compatibility_rules"].append(other)


def test_incompatible_rows_excluded_before_export(request_data):
    constrain_diagonal(request_data)
    batch = run(request_data)
    assert batch.status == "ready"
    assert {(item.case.metric, item.case.scope.subject) for item in batch.candidates} == {("m1", "s1"), ("m2", "s2")}
    assert batch.rejected_counts["compatibility_disallowed"] > 0


def test_negative_behavior_from_config_not_ai(request_data):
    constrain_diagonal(request_data)
    request_data["policy"]["invalid_combination_strategy"] = "negative"
    request_data["policy"]["invalid_combination_behavior"] = "CLARIFY"
    batch = run(request_data)
    negatives = [item for item in batch.candidates if item.case_type == "negative"]
    assert len(negatives) == 2 and len(batch.candidates) == 4
    assert all(item.case.expected_behavior == "CLARIFY" for item in negatives)
    assert request_data["seed_cases"][0]["expected_behavior"] == "ANSWER"


@pytest.mark.parametrize("mode", ["missing_rules", "unapproved_rules", "skipped_family", "unknown_capability"])
def test_incomplete_knowledge_cannot_generate_valid_or_negative_cases(request_data, mode):
    request_data["policy"]["invalid_combination_strategy"] = "negative"
    if mode == "missing_rules":
        request_data["rules"]["compatibility_rules"] = []
    elif mode == "unapproved_rules":
        request_data["rules"]["compatibility_rules"][0].update(approval="proposed", approved_by=None)
    elif mode == "skipped_family":
        request_data["rules"]["compatibility_rules"][0]["when"] = [{"axis": "metric", "allowed": ["other"]}]
    else:
        request_data["capability"]["metrics"] = []
    result = run(request_data)
    assert result.status == "blocked" and result.candidates == []


@pytest.mark.parametrize("budget", ["cases", "candidates", "interactions"])
def test_resource_limits_are_reported(request_data, budget):
    if budget == "cases":
        request_data["policy"]["max_generated_cases"] = 1
    elif budget == "candidates":
        request_data["policy"]["max_candidate_checks"] = 1
    else:
        third_axis(request_data)
        request_data["policy"].update(high_risk_capability_ids=["cap"], max_interaction_checks=1)
    batch = run(request_data)
    assert batch.truncated and batch.status in {"blocked", "partial"}
    assert len(batch.candidates) <= request_data["policy"]["max_generated_cases"]
    assert not batch.sampling[0].backend_exhausted


def test_policy_approval_gate_does_not_call_ports(request_data):
    class NoCalls:
        def rows(self, *args):
            raise AssertionError("must not call")

    request_data["policy"].update(approval="proposed", approved_by=None)
    batch = run(request_data, combinations=NoCalls())
    assert batch.status == "blocked" and batch.diagnostics == ["policy_not_approved"]


def test_duplicate_templates_deduplicate_candidates(request_data):
    other = deepcopy(request_data["policy"]["templates"][0])
    other["template_id"] = "other"
    request_data["policy"]["templates"].append(other)
    batch = run(request_data)
    assert len(batch.candidates) == 4
    assert batch.rejected_counts["duplicate_candidate"] == 4


def test_empty_axes_explicit_seed_template(request_data):
    template = request_data["policy"]["templates"][0]
    template.update(axes=[], case_type="seed", question_template="{question}")
    assert len(run(request_data).candidates) == 1


def test_single_axis(request_data):
    template = request_data["policy"]["templates"][0]
    template.update(axes=template["axes"][:1], question_template="{metric}")
    assert len(run(request_data).candidates) == 2


@pytest.mark.parametrize("kind", ["property", "metamorphic"])
def test_rule_derived_templates_keep_rule_and_related_refs(request_data, kind):
    template = request_data["policy"]["templates"][0]
    template.update(case_type=kind, rule_ids=["property-fixture"], related_seed_case_ids=["seed"] if kind == "metamorphic" else [])
    request_data["rules"]["test_rules"] = [{
        "rule_id": "property-fixture", "description": "Fixture only", "approval": "approved", "approved_by": "test-fixture-only",
        "category": kind, "preconditions": {}, "assertion": {"kind": "distinct", "left": "a", "right": "b"},
    }]
    result = run(request_data)
    assert len(result.candidates) == 4
    assert all(item.rule_ids == ["property-fixture"] for item in result.candidates)
    request_data["rules"]["test_rules"][0].update(approval="proposed", approved_by=None)
    assert run(request_data).status == "blocked"


class FixtureDesigner:
    def __init__(self, proposals):
        self.proposals = proposals
        self.calls = 0

    def propose(self, request):
        self.calls += 1
        return ProposalBatch.model_validate({"proposals": self.proposals})


def test_ai_questions_cannot_replace_expected_semantics(request_data):
    request_data["policy"].update(ai_enabled=True, paraphrase_count=1)
    designer = FixtureDesigner([{"seed_case_id": "seed", "question": "AI candidate question"}])
    result = run(request_data, designer)
    assert designer.calls == 1
    ai = [item for item in result.candidates if item.source == "ai"]
    assert len(ai) == 1 and ai[0].review_required and ai[0].status == "candidate"
    assert ai[0].case.metric == "m1" and ai[0].case.expected_behavior == "ANSWER"


@pytest.mark.parametrize("proposals", [[], [{"seed_case_id": "other", "question": "q"}],
    [{"seed_case_id": "seed", "question": "q1"}, {"seed_case_id": "seed", "question": "q2"}]])
def test_ai_missing_and_invalid_quota_preserve_deterministic_cases(request_data, proposals):
    request_data["policy"].update(ai_enabled=True, paraphrase_count=1)
    batch = run(request_data, FixtureDesigner(proposals))
    assert batch.status == "partial"
    assert len([item for item in batch.candidates if item.source == "deterministic"]) == 4


def test_missing_or_failed_ai_port_is_explicit(request_data):
    request_data["policy"]["ai_enabled"] = True
    assert "candidate_designer_unavailable" in run(request_data).diagnostics

    class Failed:
        def propose(self, request):
            raise CandidateDesignError("private diagnostic")

    assert "candidate_designer_failed" in run(request_data, Failed()).diagnostics


def test_no_ai_call_when_case_cap_already_reached(request_data):
    request_data["policy"].update(ai_enabled=True, max_generated_cases=1)
    designer = FixtureDesigner([])
    assert run(request_data, designer).truncated
    assert designer.calls == 0


@pytest.mark.parametrize("row", [{"wrong": 0}, {"metric": -1, "scope": 0}, {"metric": [], "scope": 0}])
def test_invalid_combination_port_output(request_data, row):
    class Invalid:
        def rows(self, *args):
            yield row

    result = run(request_data, combinations=Invalid())
    assert result.status == "blocked" and "combination_designer_failed" in result.diagnostics


@pytest.mark.parametrize("failure", ["unknown_seed", "unknown_step", "bad_placeholder", "unused_axis",
    "duplicate_axis", "overlapping_axes", "unapproved", "bad_strength", "duplicate_template"])
def test_invalid_input_schema(request_data, failure):
    template = request_data["policy"]["templates"][0]
    if failure == "unknown_seed":
        template["seed_case_id"] = "unknown"
    elif failure == "unknown_step":
        template["axes"][0]["targets"] = [{"step_id": "unknown"}]
    elif failure == "bad_placeholder":
        template["question_template"] = "{metric.__class__} {scope}"
    elif failure == "unused_axis":
        template["question_template"] = "{metric}"
    elif failure == "duplicate_axis":
        template["axes"].append(deepcopy(template["axes"][0]))
    elif failure == "overlapping_axes":
        template["axes"][1]["options"][0]["patch"]["metric"] = "m1"
    elif failure == "unapproved":
        request_data["policy"]["approved_by"] = None
    elif failure == "bad_strength":
        request_data["policy"]["pairwise_strength"] = 1
    else:
        request_data["policy"]["templates"].append(deepcopy(template))
    with pytest.raises(ValidationError):
        GenerationRequest.model_validate(request_data)


def test_policy_source_safe_defaults_and_errors(tmp_path):
    path = Path(__file__).resolve().parents[3] / "config" / "generation.yml"
    policy = load_policy(YamlGenerationPolicySource(path))
    assert policy.approval == "proposed" and not policy.ai_enabled and policy.templates == []
    for text in ("[", "{}", "a: 1\na: 2", "!!python/object/apply:os.system ['unsafe']"):
        path = tmp_path / "generation.yml"
        path.write_text(text)
        with pytest.raises(GenerationConfigError):
            load_policy(YamlGenerationPolicySource(path))


def test_ai_schema_rejects_truth_and_approval_fields():
    with pytest.raises(ValidationError):
        ProposalBatch.model_validate({"proposals": [{"seed_case_id": "seed", "question": "q", "expected_behavior": "ANSWER"}]})


def test_multistep_objectset_and_dependencies_survive_generation(request_data):
    seed = request_data["seed_cases"][0]
    first = seed["steps"][0]
    first["output_object_set_ids"] = ["objects"]
    second = deepcopy(first)
    second.update(step_id="next", input_object_set_ids=["objects"], output_object_set_ids=[])
    second["scope"]["object_set_id"] = "objects"
    seed["steps"].append(second)
    seed["step_dependencies"] = [{"step_id": "next", "depends_on": "step", "object_set_id": "objects"}]
    request_data["capability"]["multi_step"] = True
    result = run(request_data)
    assert result.status == "ready"
    for candidate in result.candidates:
        assert candidate.case.steps[1].scope.object_set_id == "objects"
        assert candidate.case.step_dependencies[0].object_set_id == "objects"
        assert [step.step_id for step in candidate.case.steps] == ["step", "next"]


def test_canonical_aliases_cannot_silently_disagree_after_axis_patch(request_data):
    seed = request_data["seed_cases"][0]
    seed["operation"]["parameters"] = {"metrics": ["m1"]}
    seed["steps"][0]["operation"]["parameters"] = {"metrics": ["m1"]}
    result = run(request_data)
    assert result.status == "partial"
    assert all(item.case.metric == "m1" for item in result.candidates)
    assert result.rejected_counts["invalid_canonical_parameters"] > 0


def test_nested_comparison_cannot_hide_unsupported_metrics(request_data):
    fields = ("metric", "scope", "grain", "dimensions", "time", "filters", "relations", "set_operations", "operation")
    seed = request_data["seed_cases"][0]
    semantic = {key: deepcopy(seed[key]) for key in fields}
    semantic["metric"] = "not-in-capability"
    inner = {key: deepcopy(seed[key]) for key in fields}
    inner["operation"]["parameters"] = {"comparison": {"operands": [{"semantic": semantic}]}}
    seed["operation"]["parameters"] = {"comparison": {"operands": [{"semantic": inner}]}}
    assert run(request_data).status == "blocked"


def test_malformed_axis_option_is_reported_not_ignored(request_data):
    request_data["policy"]["templates"][0]["axes"][1]["options"][0]["patch"]["scope"] = 123
    result = run(request_data)
    assert result.status == "partial"
    assert "invalid_candidate_schema" in result.diagnostics


def test_negative_type_must_be_explicitly_allowed(request_data):
    constrain_diagonal(request_data)
    request_data["policy"]["invalid_combination_strategy"] = "negative"
    request_data["policy"]["allowed_case_types"].remove("negative")
    assert all(item.case_type != "negative" for item in run(request_data).candidates)


def test_no_implicit_compatibility_when_families_empty(request_data):
    request_data["policy"]["generation_filters"]["required_families"] = []
    assert run(request_data).status == "blocked"
    request_data["policy"]["generation_filters"]["allow_capability_only"] = True
    assert run(request_data).status == "ready"


def test_320_synthetic_candidates_scale_check_is_not_business_acceptance(request_data):
    third_axis(request_data)
    request_data["policy"]["high_risk_capability_ids"] = ["cap"]
    original_seed = deepcopy(request_data["seed_cases"][0])
    original_template = deepcopy(request_data["policy"]["templates"][0])
    request_data["seed_cases"] = []
    request_data["policy"]["templates"] = []
    for index in range(40):
        seed = deepcopy(original_seed)
        seed.update(case_id=f"fixture-seed-{index}", question=f"Synthetic fixture {index}")
        template = deepcopy(original_template)
        template.update(template_id=f"fixture-template-{index}", seed_case_id=seed["case_id"],
                        question_template="{question}: {metric} {scope} {dimension}")
        request_data["seed_cases"].append(seed)
        request_data["policy"]["templates"].append(template)
    batch = run(request_data)
    assert batch.status == "ready" and len(batch.candidates) == 320
    assert len({item.case.case_id for item in batch.candidates}) == 320
    assert all(item.status == "candidate" for item in batch.candidates)


def test_duplicate_ai_paraphrases_report_unmet_unique_quota(request_data):
    request_data["policy"].update(ai_enabled=True, paraphrase_count=2)
    designer = FixtureDesigner([{"seed_case_id": "seed", "question": "duplicate"}] * 2)
    batch = run(request_data, designer)
    assert batch.status == "partial" and "ai_quota_not_met" in batch.diagnostics
    assert len([item for item in batch.candidates if item.source == "ai"]) == 1


def test_ai_review_cannot_be_removed_by_output_schema(request_data):
    from agent_test.domains.generation.api import GeneratedTestCase

    request_data["policy"].update(ai_enabled=True, paraphrase_count=1)
    batch = run(request_data, FixtureDesigner([{"seed_case_id": "seed", "question": "q"}]))
    candidate = next(item for item in batch.candidates if item.source == "ai").model_dump(mode="json")
    candidate["review_required"] = False
    with pytest.raises(ValidationError):
        GeneratedTestCase.model_validate(candidate)
