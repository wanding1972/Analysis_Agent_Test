import pytest


@pytest.fixture
def question():
    return dict(question_id="q-fixture", category="fixture", question="测试问题",
                expected_behavior="ANSWER", expected_metric="metric-fixture", expected_scope=None,
                expected_grain=None, expected_time=None, note="Test data only")


@pytest.fixture
def canonical_case():
    return dict(case_id="case-fixture", question="测试问题", expected_behavior="ANSWER",
                metric="metric-fixture", scope=None, grain=None, dimensions=[], time=None,
                filters=[], relations=[], set_operations=[], operation=None, step_dependencies=[])


@pytest.fixture
def asset_payload(question, canonical_case):
    return dict(
        schema_version="1", asset_set_id="assets-fixture", questions=[question],
        snapshots=[dict(snapshot_id="snapshot-fixture", kind="fixture", reference="fixtures/data.json")],
        canonical_cases=[dict(question_id=question["question_id"], case=canonical_case)],
        golden_baselines=[dict(
            baseline_id="golden-fixture", question_id=question["question_id"],
            snapshot_id="snapshot-fixture", confirmed_by="test-fixture-only",
            confirmation_reference="test-fixture-only", source={"kind": "reference_result", "result": None},
        )],
        rules=dict(schema_version="1", compatibility_rules=[], test_rules=[]),
    )
