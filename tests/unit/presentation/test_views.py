from agent_test.domains.reporting.api import ReportInput, build
from agent_test.presentation.api import report_html, report_json


def test_presentation_is_a_view_only():
    view = build(ReportInput(run_id="r", agent_version="v", snapshot_id="s", result_statuses=[]))
    assert report_json(view)["run_id"] == "r"
    assert "Test Run r" in report_html(view)
