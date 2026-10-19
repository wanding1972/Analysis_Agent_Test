from agent_test.domains.drift.api import DriftPolicy, VersionExecution, compare
from agent_test.domains.execution.api import ExecutionObservation
from agent_test.domains.review.api import ReviewDecision, review_from_drift


def drift():
    base = VersionExecution(version_id="v1", observation=ExecutionObservation(
        run_id="r", case_id="c", question="q", snapshot_id="s", status="answered"))
    candidate = VersionExecution(version_id="v2", observation=ExecutionObservation(
        run_id="r", case_id="c", question="q", snapshot_id="s", status="clarify"))
    return compare(base, candidate, DriftPolicy(schema_version="1"))


def test_review_starts_pending_and_accepts_human_decision():
    pending = review_from_drift(drift())
    assert pending.status == "pending"
    decided = review_from_drift(drift(), ReviewDecision(
        classification="BUG", reviewer="qa", comment="reproduce in next run"))
    assert decided.status == "decided"
    assert decided.classification == "BUG"
