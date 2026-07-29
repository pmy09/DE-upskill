"""Unit tests for quality checks and the pipeline gate."""

from __future__ import annotations

import pandas as pd
import pytest

import validate
from validate import DataQualityValidator, QualityGateError, enforce_quality_gate


def test_unique_email_is_case_and_whitespace_insensitive():
    frame = pd.DataFrame({"email": [" Ann@Example.com ", "ann@example.com"]})
    validator = DataQualityValidator(frame, threshold=0.95)

    result = validator.check_unique("email", "unique email")

    assert result["failed"] == 1
    assert result["status"] == "FAIL"


def test_numeric_and_date_ranges_count_outliers():
    frame = pd.DataFrame(
        {
            "salary": [14_000, 50_000, 2_100_000, None],
            "hire_date": pd.to_datetime(["1969-01-01", "2020-01-01", None, None]),
        }
    )
    validator = DataQualityValidator(frame, threshold=0.5)

    salary = validator.check_numeric_range("salary", 15_000, 2_000_000, "range")
    dates = validator.check_date_range(
        "hire_date", "1970-01-01", "2026-12-31", "date range"
    )

    assert salary["failed"] == 2
    assert salary["total"] == 3
    assert dates["failed"] == 1
    assert dates["total"] == 2


def test_referential_integrity_detects_missing_manager():
    frame = pd.DataFrame(
        {
            "employee_id": ["GT-000001", "GT-000002"],
            "manager_id": [pd.NA, "GT-999999"],
        }
    )
    validator = DataQualityValidator(frame)

    result = validator.check_referential_integrity(
        "manager_id", "employee_id", "manager exists"
    )

    assert result["total"] == 1
    assert result["failed"] == 1


def test_gate_allows_two_failed_checks():
    report = pd.DataFrame({"status": ["FAIL", "FAIL", "PASS"], "check": ["a", "b", "c"]})

    enforce_quality_gate(report, max_failed=2)


def test_gate_raises_when_more_than_two_checks_fail():
    report = pd.DataFrame(
        {"status": ["FAIL", "FAIL", "FAIL"], "check": ["a", "b", "c"]}
    )

    with pytest.raises(QualityGateError, match="3 checks failed"):
        enforce_quality_gate(report, max_failed=2)


def test_full_suite_returns_15_rows_without_writing_real_outputs(
    valid_employees, monkeypatch
):
    exported = {}
    monkeypatch.setattr(
        validate,
        "export_quality_report",
        lambda report: exported.setdefault("report", report.copy()),
    )

    report = validate.run_quality_checks(valid_employees, enforce_gate=False)

    assert len(report) == 15
    assert report["status"].eq("PASS").all()
    assert len(exported["report"]) == 15
    assert report.columns.tolist() == [
        "check",
        "description",
        "total",
        "passed",
        "failed",
        "pass_rate",
        "status",
    ]
