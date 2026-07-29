"""Unit tests for source alignment and cleaning transformations."""

from __future__ import annotations

import pandas as pd
import pytest

from clean import (
    normalize_currency_and_salary,
    standardize_dates,
    standardize_departments,
    standardize_employee_ids,
    standardize_employment_types,
    standardize_name_series,
)
from config import CONFIG
from ingest import align_schema


def test_align_schema_adds_standard_columns_and_source_tags():
    native = pd.DataFrame(
        {
            "employee_id": ["42"],
            "first_name": ["Ada"],
            "last_name": ["Lovelace"],
        }
    )

    aligned = align_schema(native, "globaltech_hris")

    assert aligned.columns.tolist() == CONFIG["standard_schema"]
    assert aligned.loc[0, "source_system"] == "globaltech_hris"
    assert aligned.loc[0, "company_origin"] == "GlobalTech"
    assert pd.isna(aligned.loc[0, "currency"])


def test_align_schema_rejects_unknown_source():
    with pytest.raises(ValueError, match="Unsupported source"):
        align_schema(pd.DataFrame(), "unknown")


def test_benefits_alignment_sets_enrollment_defaults():
    native = pd.DataFrame({"employee_id": ["1"], "plan_type": ["Dental"]})

    aligned = align_schema(native, "benefits")

    assert bool(aligned.loc[0, "benefits_enrolled"]) is True
    assert aligned.loc[0, "benefit_plan_count"] == 1


def test_name_standardization_preserves_accents_hyphens_and_apostrophes():
    names = pd.Series(["  josé  ", "anne-mARIE", "o'BRIEN", None])

    result = standardize_name_series(names)

    assert result.iloc[:3].tolist() == ["José", "Anne-Marie", "O'Brien"]
    assert pd.isna(result.iloc[3])


def test_employee_and_manager_ids_are_namespaced():
    frame = pd.DataFrame(
        {
            "employee_id": ["42", "ACQ_00007"],
            "manager_id": ["9", "ACQ_00002"],
            "company_origin": ["GlobalTech", "AcquiredCo"],
        }
    )

    result = standardize_employee_ids(frame)

    assert result["employee_id"].tolist() == ["GT-000042", "AC-000007"]
    assert result["manager_id"].tolist() == ["GT-000009", "AC-000002"]
    assert result["employee_id_raw"].tolist() == ["42", "ACQ_00007"]


def test_employment_types_map_to_standard_taxonomy():
    frame = pd.DataFrame(
        {"employment_type": ["FT", "pt", "CONTRACTOR", "temporary"]}
    )

    result = standardize_employment_types(frame)

    assert result["employment_type"].iloc[:3].tolist() == [
        "Full-Time",
        "Part-Time",
        "Contractor",
    ]
    assert pd.isna(result["employment_type"].iloc[3])


def test_salary_normalization_handles_symbols_fx_and_frequency():
    frame = pd.DataFrame(
        {
            "base_salary": ["$10,000", "€1,000", "£2,000"],
            "currency": ["usd", "EUR", "gbp"],
            "pay_frequency": ["Monthly", "Annual", "Bi-Weekly"],
        }
    )

    result = normalize_currency_and_salary(frame)

    assert result["salary_usd_annual"].tolist() == [
        120_000.0,
        1_090.0,
        66_040.0,
    ]


def test_departments_map_codes_and_flag_unknown_values():
    frame = pd.DataFrame({"department": ["ENG-01", "Sales", "Mystery Team"]})

    result = standardize_departments(frame)

    assert result["department"].iloc[:2].tolist() == ["Engineering", "Sales"]
    assert pd.isna(result["department"].iloc[2])
    assert result["department_unmapped"].tolist() == [False, False, True]


def test_dates_parse_supported_formats_and_flag_invalid_values():
    frame = pd.DataFrame(
        {
            "hire_date": [
                "2020-01-02",
                "03/04/2021",
                "05-May-2022",
                "not-a-date",
                "1960-01-01",
            ]
        }
    )

    result = standardize_dates(frame, date_columns=("hire_date",))

    assert result["hire_date"].notna().sum() == 4
    assert result["hire_date_invalid"].tolist() == [False, False, False, True, True]
