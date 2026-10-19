"""JSON and HTML view models; no business decisions live here."""

import html
import json

from agent_test.domains.reporting.api import ReportView


def report_json(view: ReportView) -> dict:
    return view.model_dump(mode="json")


def report_html(view: ReportView) -> str:
    summary = json.dumps(view.summary.model_dump(mode="json"), ensure_ascii=False)
    rows = "".join(
        f"<tr><td>{html.escape(item.case_id)}</td><td>{html.escape(item.status)}</td>"
        f"<td>{html.escape(item.summary)}</td></tr>" for item in view.drifts
    )
    return (
        f"<main><h1>Test Run {html.escape(view.run_id)}</h1>"
        f"<pre>{html.escape(summary)}</pre>"
        f"<table><thead><tr><th>Case</th><th>Status</th><th>Summary</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></main>"
    )
