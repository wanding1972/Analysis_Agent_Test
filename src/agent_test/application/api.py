"""Public application orchestration API."""

from agent_test.domains.drift.api import DriftPolicy, DriftRecord, VersionExecution, compare
from agent_test.domains.execution.api import AgentExecutor, ExecutionBatch, ExecutionRequest
from agent_test.domains.reporting.api import ReportArtifact, ReportInput, ReportView, build, export
from agent_test.domains.review.api import FailureReview, ReviewDecision, review_from_drift

from .models import TestRun


def run_test_suite(executor: AgentExecutor, request: ExecutionRequest, agent_version: str, snapshot_id: str) -> TestRun:
    batch = executor.execute(request)
    return TestRun(run_id=request.run_id, agent_version=agent_version, snapshot_id=snapshot_id, execution=batch)


def compare_versions(baseline: VersionExecution, candidate: VersionExecution, policy: DriftPolicy) -> DriftRecord:
    return compare(baseline, candidate, policy)


def review_failure(drift: DriftRecord, decision: ReviewDecision | None = None) -> FailureReview:
    return review_from_drift(drift, decision)


def report(test_run: TestRun) -> ReportView:
    return build(ReportInput(
        run_id=test_run.run_id, agent_version=test_run.agent_version, snapshot_id=test_run.snapshot_id,
        result_statuses=test_run.result_statuses, drifts=test_run.drifts, reviews=test_run.reviews,
    ))


def export_report(test_run: TestRun, format: str) -> ReportArtifact:
    return export(report(test_run), format)


__all__ = [
    "TestRun", "run_test_suite", "compare_versions", "review_failure", "report", "export_report",
]
