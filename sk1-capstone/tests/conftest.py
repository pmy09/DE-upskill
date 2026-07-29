"""Shared pytest configuration and compact employee fixtures."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_DIR = PROJECT_ROOT / "hr_pipeline"
if str(PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_DIR))


@pytest.fixture
def valid_employees() -> pd.DataFrame:
    """Return two valid, referentially consistent golden employee rows."""
    return pd.DataFrame(
        {
            "employee_id": pd.Series(["GT-000001", "AC-000001"], dtype="string"),
            "first_name": pd.Series(["Ann", "Bob"], dtype="string"),
            "last_name": pd.Series(["Lee", "Ng"], dtype="string"),
            "email": ["ann@example.com", "bob@example.com"],
            "department": pd.Series(["Engineering", "Sales"], dtype="string"),
            "job_title": ["Engineer", "Sales Analyst"],
            "hire_date": pd.to_datetime(["2020-01-15", "2021-06-01"]),
            "country": ["United States", "Ghana"],
            "employment_type": pd.Series(["Full-Time", "Contractor"], dtype="string"),
            "employment_status": ["Active", "Active"],
            "manager_id": pd.Series([pd.NA, "GT-000001"], dtype="string"),
            "company_origin": ["GlobalTech", "AcquiredCo"],
            "source_system": ["globaltech_hris", "acquiredco_hris"],
            "source_systems": pd.Series(
                ["globaltech_hris,payroll", "acquiredco_hris"], dtype="string"
            ),
            "dedup_method": pd.Series(["exact_id", "single_source"], dtype="string"),
            "base_salary": ["80000", "70000"],
            "currency": pd.Series(["USD", "EUR"], dtype="string"),
            "pay_frequency": pd.Series(["Annual", "Annual"], dtype="string"),
            "salary_usd_annual": pd.Series([80_000.0, 76_300.0], dtype="Float64"),
            "benefits_enrolled": [True, False],
            "benefit_plan_count": [1, 0],
        }
    )
