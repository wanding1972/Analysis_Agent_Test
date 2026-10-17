import json

import pytest
import yaml
from openpyxl import Workbook

from agent_test.domains.assets.api import AssetReadError, AssetValidationError, load_asset_set, load_questions
from agent_test.infrastructure.files.asset_files import (
    ExcelQuestionSource, JsonAssetSetSource, YamlAssetSetSource,
)


@pytest.mark.parametrize("source_type", [JsonAssetSetSource, YamlAssetSetSource])
def test_document_load(tmp_path, asset_payload, source_type):
    path = tmp_path / "assets"
    text = json.dumps(asset_payload) if source_type is JsonAssetSetSource else yaml.safe_dump(asset_payload)
    path.write_text(text, encoding="utf-8")
    assert load_asset_set(source_type(path)).asset_set_id == "assets-fixture"


@pytest.mark.parametrize("source_type,text", [
    (JsonAssetSetSource, "{"), (JsonAssetSetSource, "[]"),
    (JsonAssetSetSource, '{"a": 1, "a": 2}'), (JsonAssetSetSource, '{"a": NaN}'),
    (YamlAssetSetSource, "["), (YamlAssetSetSource, "[]"),
    (YamlAssetSetSource, "a: 1\na: 2"), (YamlAssetSetSource, "a: 1\n---\na: 2"),
    (YamlAssetSetSource, "!!python/object/apply:os.system ['do-not-execute']"),
])
def test_invalid_documents(tmp_path, source_type, text, caplog):
    path = tmp_path / "assets"
    path.write_text(text)
    with pytest.raises(AssetReadError) as caught:
        load_asset_set(source_type(path))
    assert caught.value.__cause__ is not None
    assert "Unable to read" in caplog.text
    assert "do-not-execute" not in caplog.text


@pytest.mark.parametrize("source_type", [JsonAssetSetSource, YamlAssetSetSource, ExcelQuestionSource])
def test_missing_file(tmp_path, source_type):
    with pytest.raises(AssetReadError):
        source_type(tmp_path / "missing.xlsx").read()


@pytest.mark.parametrize("source_type", [JsonAssetSetSource, YamlAssetSetSource])
def test_invalid_encoding_and_schema(tmp_path, source_type):
    path = tmp_path / "assets"
    path.write_bytes(b"\xff")
    with pytest.raises(AssetReadError):
        source_type(path).read()
    path.write_text("{}")
    with pytest.raises(AssetValidationError):
        load_asset_set(source_type(path))


def write_workbook(path, headers, values, extra_sheet=False):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Questions"
    sheet.append(headers)
    sheet.append(values)
    sheet.append([None] * len(headers))
    if extra_sheet:
        workbook.create_sheet("Other")
    workbook.save(path)
    workbook.close()


def test_excel_headers_reordered_and_null_preserved(tmp_path, question):
    path = tmp_path / "golden_questions.xlsx"
    headers = list(reversed(question))
    write_workbook(path, headers, [question[key] for key in headers])
    questions = load_questions(ExcelQuestionSource(path))
    assert len(questions) == 1
    assert questions[0].model_dump(mode="json") == question
    assert questions[0].expected_scope is None


@pytest.mark.parametrize("failure", ["missing_header", "duplicate_header", "extra_header",
                                       "formula", "error", "invalid_behavior", "numeric_time"])
def test_excel_invalid_rows_and_headers(tmp_path, question, failure):
    path = tmp_path / "questions.xlsx"
    headers = list(question)
    if failure == "missing_header":
        headers.remove("note")
    elif failure == "duplicate_header":
        headers[-1] = headers[0]
    elif failure == "extra_header":
        headers.append("route")
        question["route"] = "legacy"
    elif failure == "formula":
        question["question"] = "=SUM(1,2)"
    elif failure == "error":
        question["question"] = "#VALUE!"
    elif failure == "invalid_behavior":
        question["expected_behavior"] = "GUESS"
    else:
        question["expected_time"] = 2026
    write_workbook(path, headers, [question[key] for key in headers])
    with pytest.raises((AssetReadError, AssetValidationError)):
        load_questions(ExcelQuestionSource(path))


def test_excel_explicit_sheet_selection(tmp_path, question):
    path = tmp_path / "questions.xlsx"
    write_workbook(path, list(question), list(question.values()), extra_sheet=True)
    with pytest.raises(AssetReadError):
        load_questions(ExcelQuestionSource(path))
    assert len(load_questions(ExcelQuestionSource(path, "Questions"))) == 1
    with pytest.raises(AssetReadError):
        ExcelQuestionSource(path, "Missing").read()


def test_corrupt_excel_and_header_only(tmp_path, question):
    path = tmp_path / "questions.xlsx"
    path.write_text("not a zip file")
    with pytest.raises(AssetReadError):
        ExcelQuestionSource(path).read()
    write_workbook(path, list(question), [None] * len(question))
    assert load_questions(ExcelQuestionSource(path)) == []
