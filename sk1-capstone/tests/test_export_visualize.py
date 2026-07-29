"""Tests for output files, Parquet partitions, and EDA rendering."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from export import (
    GHOST_EMPLOYEE_COLUMNS,
    PROBABLE_MATCH_REQUIRED_COLUMNS,
    build_schema_frame,
    export_ghost_employees,
    export_golden_dataset,
    export_probable_matches,
    write_schema_documentation,
)
from visualize import _short_check_label, generate_eda_report


def test_empty_review_csvs_keep_required_headers(tmp_path):
    ghost_path = export_ghost_employees(pd.DataFrame(), tmp_path / "ghosts.csv")
    match_path = export_probable_matches(pd.DataFrame(), tmp_path / "matches.csv")

    assert pd.read_csv(ghost_path).columns.tolist() == GHOST_EMPLOYEE_COLUMNS
    assert pd.read_csv(match_path).columns.tolist() == PROBABLE_MATCH_REQUIRED_COLUMNS


def test_schema_frame_and_markdown_document_all_columns(valid_employees, tmp_path):
    schema = build_schema_frame(valid_employees)
    output = write_schema_documentation(valid_employees, tmp_path / "schema.md")

    assert schema["column_name"].tolist() == valid_employees.columns.tolist()
    assert {"column_name", "data_type", "description", "example_value"} == set(
        schema.columns
    )
    text = output.read_text(encoding="utf-8")
    assert "# Golden Employee Dataset Schema" in text
    assert "`employee_id`" in text


def test_golden_dataset_is_partitioned_by_company_origin(valid_employees, tmp_path):
    pytest.importorskip("pyarrow")
    output = export_golden_dataset(valid_employees, tmp_path / "golden")

    partitions = {path.name for path in output.glob("company_origin=*")}
    reloaded = pd.read_parquet(output)

    assert partitions == {
        "company_origin=GlobalTech",
        "company_origin=AcquiredCo",
    }
    assert len(reloaded) == len(valid_employees)
    assert set(reloaded["company_origin"]) == {"GlobalTech", "AcquiredCo"}


def test_golden_export_requires_partition_column(tmp_path):
    with pytest.raises(KeyError, match="company_origin"):
        export_golden_dataset(pd.DataFrame({"employee_id": ["GT-000001"]}), tmp_path / "x")


def test_quality_labels_are_shortened():
    label = _short_check_label(
        "REFERENTIAL INTEGRITY: manager_id -> employee_id", max_len=20
    )

    assert len(label) <= 20
    assert label.startswith("REF:")


def test_eda_report_writes_png(valid_employees, tmp_path, monkeypatch):
    import visualize

    quality_report = pd.DataFrame(
        {
            "check": ["NOT NULL: employee_id", "UNIQUE: email"],
            "passed": [2, 2],
            "failed": [0, 0],
        }
    )
    output = tmp_path / "eda.png"
    monkeypatch.setitem(visualize.CONFIG, "eda_dpi", 72)

    result = generate_eda_report(valid_employees, quality_report, output)

    assert result == output
    assert output.exists()
    assert output.stat().st_size > 0
