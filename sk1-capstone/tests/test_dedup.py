"""Unit tests for employee aggregation and multi-pass matching."""

from __future__ import annotations

import pandas as pd

from dedup import (
    aggregate_benefits,
    aggregate_payroll,
    collapse_hris_by_employee_id,
    detect_ghost_employees,
    pass2_email_match,
    pass3_fuzzy_name_match,
)


def test_aggregate_payroll_keeps_latest_effective_record():
    payroll = pd.DataFrame(
        {
            "employee_id": ["GT-000001", "GT-000001"],
            "company_origin": ["GlobalTech", "GlobalTech"],
            "source_system": ["payroll", "payroll"],
            "payroll_effective_date": pd.to_datetime(["2023-01-01", "2024-01-01"]),
            "salary_usd_annual": [60_000.0, 75_000.0],
        }
    )

    result = aggregate_payroll(payroll)

    assert len(result) == 1
    assert result.loc[0, "salary_usd_annual"] == 75_000.0


def test_aggregate_benefits_combines_employee_plans():
    benefits = pd.DataFrame(
        {
            "employee_id": ["GT-000001", "GT-000001"],
            "company_origin": ["GlobalTech", "GlobalTech"],
            "source_system": ["benefits", "benefits"],
            "benefits_enrolled": [True, True],
            "benefit_plans": pd.Series(["Dental", "Vision"], dtype="string"),
            "benefit_coverage_level": ["Individual", "Family"],
            "benefit_enrollment_date": pd.to_datetime(["2024-01-01", "2024-02-01"]),
            "premium_employee": [10.0, 20.0],
            "premium_employer": [50.0, 60.0],
        }
    )

    result = aggregate_benefits(benefits)

    assert len(result) == 1
    assert result.loc[0, "benefit_plans"] == "Dental,Vision"
    assert result.loc[0, "benefit_plan_count"] == 2
    assert result.loc[0, "premium_employee"] == 30.0


def test_collapse_hris_prefers_canonical_acquiredco_row():
    hris = pd.DataFrame(
        {
            "employee_id": ["AC-000001", "AC-000001"],
            "employee_id_raw": ["ACQ_DUP_00001", "ACQ_00001"],
            "first_name": ["Duplicate", "Canonical"],
            "source_system": ["acquiredco_hris", "acquiredco_hris"],
        }
    )

    result = collapse_hris_by_employee_id(hris)

    assert len(result) == 1
    assert result.loc[0, "first_name"] == "Canonical"
    assert result.loc[0, "dedup_method"] == "exact_id"


def test_detect_ghosts_returns_latest_unmatched_payroll_row():
    payroll = pd.DataFrame(
        {
            "employee_id": ["GT-000001", "GT-999999", "GT-999999"],
            "first_name": ["Known", "Ghost", "Ghost"],
            "last_name": ["Person", "Employee", "Employee"],
            "salary_usd_annual": [50_000.0, 60_000.0, 70_000.0],
            "payroll_effective_date": pd.to_datetime(
                ["2024-01-01", "2023-01-01", "2024-01-01"]
            ),
            "company_origin": ["GlobalTech"] * 3,
        }
    )

    result = detect_ghost_employees(payroll, {"GT-000001"})

    assert len(result) == 1
    assert result.loc[0, "payroll_employee_id"] == "GT-999999"
    assert result.loc[0, "salary_usd_annual"] == 70_000.0
    assert bool(result.loc[0, "ghost_employee"]) is True


def test_pass2_merges_only_cross_company_email_collision():
    employees = pd.DataFrame(
        {
            "employee_id": ["GT-000001", "AC-000001", "GT-000002"],
            "first_name": ["Sam", pd.NA, "Other"],
            "last_name": ["Lee", "Lee", "Person"],
            "email": [" SAM@EXAMPLE.COM ", "sam@example.com", "other@example.com"],
            "company_origin": ["GlobalTech", "AcquiredCo", "GlobalTech"],
            "source_system": [
                "globaltech_hris",
                "acquiredco_hris",
                "globaltech_hris",
            ],
            "source_systems": [
                "globaltech_hris,payroll",
                "acquiredco_hris",
                "globaltech_hris",
            ],
            "dedup_method": ["exact_id", "single_source", "single_source"],
        }
    )

    result = pass2_email_match(employees)

    assert len(result) == 2
    merged = result.loc[result["dedup_method"] == "email_match"].iloc[0]
    assert merged["first_name"] == "Sam"
    assert "globaltech_hris" in merged["source_systems"]
    assert "acquiredco_hris" in merged["source_systems"]


def test_pass3_reports_cross_company_name_match_without_merging():
    employees = pd.DataFrame(
        {
            "employee_id": ["GT-000001", "AC-000001", "GT-000002"],
            "first_name": ["John", "John", "Unrelated"],
            "last_name": ["Smith", "Smith", "Person"],
            "hire_date": pd.to_datetime(["2020-01-01", "2020-01-10", "2020-01-05"]),
            "company_origin": ["GlobalTech", "AcquiredCo", "GlobalTech"],
        }
    )

    result = pass3_fuzzy_name_match(employees)

    assert len(result) == 1
    assert set(result.loc[0, ["record_1_id", "record_2_id"]]) == {
        "GT-000001",
        "AC-000001",
    }
    assert result.loc[0, "recommended_action"] == "review"
