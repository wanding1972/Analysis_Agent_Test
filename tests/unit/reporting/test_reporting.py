from agent_test.domains.reporting.api import ReportInput, build, export


def test_report_summary_and_exports():
    view = build(ReportInput(
        run_id="r", agent_version="v", snapshot_id="s", result_statuses=["passed", "failed", "blocked"]
    ))
    assert view.summary.total == 3
    assert view.summary.failed == 1
    for format in ("json", "csv", "html", "xlsx"):
        artifact = export(view, format)
        assert artifact.format == format
        assert artifact.content
