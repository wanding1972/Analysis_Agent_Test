from agent_test.application.api import export_report, report
from agent_test.application.models import TestRun as RunState
from agent_test.domains.execution.api import ExecutionBatch


def test_application_report_orchestration():
    run = RunState(
        run_id="r", agent_version="v", snapshot_id="s",
        execution=ExecutionBatch(status="ready", observations=[], errors=[], truncated=False),
        result_statuses=["passed"],
    )
    assert report(run).summary.passed == 1
    assert export_report(run, "json").format == "json"
