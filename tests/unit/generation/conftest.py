from copy import deepcopy
from pathlib import Path

import pytest

from agent_test.domains.canonical.api import CanonicalTestCase
from agent_test.domains.generation.api import load_policy
from agent_test.infrastructure.files.generation_config import YamlGenerationPolicySource


@pytest.fixture
def request_data():
    policy = load_policy(YamlGenerationPolicySource(
        Path(__file__).resolve().parents[3] / "config" / "generation.yml")).model_dump(mode="json")
    policy.update(approval="approved", approved_by="test-fixture-only")
    policy["generation_filters"]["required_families"] = ["metric_scope_rules"]
    semantic = dict(metric="m1", scope={"subject": "s1"}, grain=None, dimensions=[], time=None,
                    filters=[], relations=[], set_operations=[], operation={"operator": "query", "parameters": {}})
    seed = CanonicalTestCase.model_validate(dict(
        **deepcopy(semantic), case_id="seed", question="Fixture question", expected_behavior="ANSWER",
        steps=[dict(**deepcopy(semantic), step_id="step")], step_dependencies=[],
    )).model_dump(mode="json")
    targets = [{"step_id": None}, {"step_id": "step"}]
    policy["templates"] = [{"template_id": "grid", "seed_case_id": "seed", "case_type": "combination",
        "question_template": "{metric} {scope}", "rule_ids": [], "related_seed_case_ids": [], "axes": [
            {"name": "metric", "targets": deepcopy(targets), "options": [
                {"label": "Metric one", "patch": {"metric": "m1"}},
                {"label": "Metric two", "patch": {"metric": "m2"}}]},
            {"name": "scope", "targets": deepcopy(targets), "options": [
                {"label": "Subject one", "patch": {"scope": {"subject": "s1"}}},
                {"label": "Subject two", "patch": {"scope": {"subject": "s2"}}}]},
        ]}]
    return dict(capability={"capability_id": "cap", "metrics": ["m1", "m2"], "subjects": ["s1", "s2"],
        "dimensions": ["d1", "d2"], "time_ops": [], "filters": [], "relations": [], "set_ops": [],
        "operations": ["query"], "multi_step": False}, seed_cases=[seed], context={}, policy=policy,
        rules={"schema_version": "1", "test_rules": [], "compatibility_rules": [{
            "rule_id": "compat", "description": "Fixture only", "approval": "approved", "approved_by": "test-fixture-only",
            "family": "metric_scope_rules", "when": [{"axis": "metric", "allowed": ["m1", "m2"]}],
            "require": [{"axis": "subject", "allowed": ["s1", "s2"]}],
        }]})
