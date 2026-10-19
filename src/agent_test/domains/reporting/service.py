"""Deterministic report building and serialization."""

import csv
import io
import json
import zipfile

from .models import ReportArtifact, ReportInput, ReportSummary, ReportView


def build(test_run: ReportInput) -> ReportView:
    statuses = list(test_run.result_statuses)
    counts = {name: statuses.count(name) for name in ("passed", "failed", "blocked", "skipped")}
    return ReportView(
        run_id=test_run.run_id, agent_version=test_run.agent_version, snapshot_id=test_run.snapshot_id,
        summary=ReportSummary(
            total=len(statuses), passed=counts["passed"], failed=counts["failed"],
            blocked=counts["blocked"], skipped=counts["skipped"],
            regression_count=sum(item.status == "regression" for item in test_run.drifts),
            pending_review_count=sum(item.status == "pending" for item in test_run.reviews),
        ), drifts=test_run.drifts, reviews=test_run.reviews,
    )


def export(view: ReportView, format: str) -> ReportArtifact:
    if format == "json":
        content = json.dumps(view.model_dump(mode="json"), ensure_ascii=False, indent=2).encode("utf-8")
        suffix = "json"
    elif format == "csv":
        stream = io.StringIO(); writer = csv.writer(stream)
        writer.writerow(["case_id", "drift_status", "summary"])
        writer.writerows([[item.case_id, item.status, item.summary] for item in view.drifts])
        content = stream.getvalue().encode("utf-8"); suffix = "csv"
    elif format == "html":
        summary = view.summary.model_dump(mode="json")
        rows = "".join(f"<tr><td>{item.case_id}</td><td>{item.status}</td><td>{item.summary}</td></tr>" for item in view.drifts)
        content = (f"<html><body><h1>Test Run {view.run_id}</h1><pre>{json.dumps(summary, ensure_ascii=False)}</pre>"
                   f"<table><tr><th>Case</th><th>Status</th><th>Summary</th></tr>{rows}</table></body></html>").encode("utf-8")
        suffix = "html"
    elif format == "xlsx":
        content = _xlsx(view); suffix = "xlsx"
    else:
        raise ValueError("unsupported_report_format")
    return ReportArtifact(format=format, filename=f"{view.run_id}.{suffix}", content=content)


def _xlsx(view: ReportView) -> bytes:
    """Create a minimal OOXML workbook without coupling the domain to a library."""
    summary_rows = [(key, value) for key, value in view.summary.model_dump(mode="json").items()]
    drift_rows = [(item.case_id, item.status, item.summary) for item in view.drifts]
    sheets = {
        "xl/worksheets/sheet1.xml": _sheet(summary_rows),
        "xl/worksheets/sheet2.xml": _sheet([("case_id", "status", "summary"), *drift_rows]),
    }
    workbook = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                '<sheets><sheet name="Summary" sheetId="1" r:id="rId1"/>'
                '<sheet name="Drift" sheetId="2" r:id="rId2"/></sheets></workbook>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/></Relationships>')
    content_types = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                     '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                     '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                     '<Default Extension="xml" ContentType="application/xml"/>'
                     '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                     '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                     '<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
    root_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                 '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_rels)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", rels)
        for name, data in sheets.items(): archive.writestr(name, data)
    return stream.getvalue()


def _sheet(rows):
    import xml.sax.saxutils as saxutils
    body = []
    for index, row in enumerate(rows, 1):
        cells = []
        for column, value in enumerate(row, 1):
            ref = f"{chr(64 + column)}{index}"
            text = saxutils.escape(str(value))
            cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{text}</t></is></c>')
        body.append(f'<row r="{index}">{"".join(cells)}</row>')
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
            + "".join(body) + '</sheetData></worksheet>')
