"""Unit tests for data quality validation."""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from validate import DataQualityValidator, run_quality_checks  # noqa: E402
from config import CONFIG  # noqa: E402


class TestDataQualityValidator:
    def test_not_null_pass(self):
        df = pd.DataFrame({"email": ["a@b.com", "c@d.com"]})
        v = DataQualityValidator(df, threshold=0.95)
        result = v.check_not_null("email", "must have email")
        assert result["status"] == "PASS"
        assert result["failed"] == 0

    def test_not_null_fail_below_threshold(self):
        df = pd.DataFrame({"email": ["a@b.com", None, None, None]})
        v = DataQualityValidator(df, threshold=0.95)
        result = v.check_not_null("email", "must have email")
        assert result["status"] == "FAIL"
        assert result["failed"] == 3

    def test_unique_detects_duplicates(self):
        df = pd.DataFrame({"email": ["a@b.com", "a@b.com", "c@d.com"]})
        v = DataQualityValidator(df, threshold=0.95)
        result = v.check_unique("email", "unique emails")
        assert result["failed"] == 1

    def test_values_in_set(self):
        df = pd.DataFrame({"region": ["US", "EU", "APAC", "MARS"]})
        v = DataQualityValidator(df, threshold=0.5)
        result = v.check_values_in_set("region", CONFIG["valid_regions"], "regions")
        assert result["failed"] == 1
        assert result["status"] == "PASS"  # 75% >= 50%

    def test_run_quality_checks_returns_seven_rows(self):
        df = pd.DataFrame({
            "email": ["a@b.com", "c@d.com"],
            "first_name": ["Ann", "Bob"],
            "region": ["US", "EU"],
            "registration_date": pd.to_datetime(["2020-01-01", "2021-01-01"]),
        })
        report = run_quality_checks(df)
        assert len(report) == 7
        assert set(report["status"]) <= {"PASS", "FAIL"}
