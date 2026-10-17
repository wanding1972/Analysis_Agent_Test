from copy import deepcopy
from pathlib import Path

import pytest

from agent_test.domains.canonical.api import CanonicalTestCase
from agent_test.domains.evaluation.api import EvaluationRequest, load_policy
from agent_test.infrastructure.files.evaluation_config import YamlEvaluationPolicySource


@pytest.fixture
def request_data():
    policy = load_policy(YamlEvaluationPolicySource(
        Path(__file__).resolve().parents[3] / "config" / "evaluation.yml")).model_dump(mode="json")
    policy.update(approval="approved", approved_by="test-fixture-only")
    semantic = dict(metric="fixture_metric", scope={"subject": "fixture_subject", "entity_ids": ["a"]},
                    grain=None, dimensions=[], time=None, filters=[], relations=[], set_operations=[],
                    operation={"operator": "query", "parameters": {"metrics": ["fixture_metric"]}})
    case = CanonicalTestCase.model_validate(dict(
        **deepcopy(semantic), case_id="case-fixture", question="Fixture question",
        expected_behavior="ANSWER", step_dependencies=[],
        steps=[dict(**deepcopy(semantic), step_id="s1")],
    )).model_dump(mode="json")
    semantic = {key: value for key, value in case.items() if key in semantic}
    return dict(
        test_case=case, question_id="question-fixture", snapshot_id="snapshot-fixture", policy=policy,
        approved_rules={"schema_version": "1", "compatibility_rules": [], "test_rules": []},
        golden_baseline=dict(
            baseline_id="golden-fixture", question_id="question-fixture", snapshot_id="snapshot-fixture",
            confirmed_by="test-fixture-only", confirmation_reference="test-fixture-only",
            source={"kind": "reference_result", "result": {"value": 10}},
        ),
        observation=dict(
            case_id=case["case_id"], snapshot_id="snapshot-fixture", semantic=deepcopy(semantic),
            steps=deepcopy(case["steps"]), step_dependencies=[],
            evidence={"result": {"value": 10}, "references": [
                {"evidence_id": "e1", "path": ["value"], "conditions": deepcopy(semantic)}]},
            answer={"behavior": "ANSWER", "claims_complete": True, "conditions": deepcopy(semantic),
                    "claims": [{"claim_id": "claim1", "evidence_id": "e1", "value": 10,
                                "conditions": deepcopy(semantic)}]},
        ),
    )


@pytest.fixture
def evaluation_request(request_data):
    return EvaluationRequest.model_validate(request_data)
