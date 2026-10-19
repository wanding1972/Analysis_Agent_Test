from agent_test.domains.drift.api import DriftPolicy, VersionExecution, compare
from agent_test.domains.execution.api import ExecutionObservation


def execution(version, status="answered", semantic=None):
    return VersionExecution(
        version_id=version,
        observation=ExecutionObservation(
            run_id="run-1", case_id="case-1", question="q", snapshot_id="snap-1", status=status,
        ),
        semantic=semantic,
    )


def test_drift_detects_status_and_semantic_changes():
    record = compare(
        execution("v1", semantic={"metric": "sales"}),
        execution("v2", status="clarify", semantic={"metric": "profit"}),
        DriftPolicy(schema_version="1"),
    )
    assert record.status == "regression"
    assert {item.kind for item in record.items} == {"capability", "semantic"}


def test_expected_change_is_explicit():
    record = compare(
        execution("v1", semantic={"metric": "sales"}),
        execution("v2", semantic={"metric": "profit"}),
        DriftPolicy(schema_version="1", expected_changes=["semantic"]),
    )
    assert record.status == "expected_change"


def test_context_mismatch_is_blocked():
    left = execution("v1"); right = execution("v2")
    right.observation.snapshot_id = "other"
    assert compare(left, right, DriftPolicy(schema_version="1")).status == "blocked"
