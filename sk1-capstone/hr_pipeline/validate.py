"""Data quality validation checks, reporting, and pipeline gate."""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from config import CONFIG, logger
from export import export_quality_report


class QualityGateError(RuntimeError):
    """Raised when too many quality checks fail the pipeline gate."""


class DataQualityValidator:
    """Runs configurable quality checks and produces a pass/fail report.

    Reusable across projects — swap the checks in ``run_quality_checks``.
    A check PASSes when its pass rate meets ``threshold`` (default 95%).
    """

    def __init__(self, df: pd.DataFrame, threshold: float = 0.95):
        self.df = df
        self.threshold = threshold
        self.results: list[dict] = []
        self.n = len(df)

    def _record(self, check: str, description: str, failed: int, total: int) -> dict:
        pass_rate = 1 - (failed / total) if total > 0 else 1.0
        result = {
            "check": check,
            "description": description,
            "total": total,
            "passed": total - failed,
            "failed": failed,
            "pass_rate": round(pass_rate, 4),
            "status": "PASS" if pass_rate >= self.threshold else "FAIL",
        }
        self.results.append(result)
        return result

    def check_not_null(self, column: str, description: str) -> dict:
        failed = int(self.df[column].isna().sum())
        return self._record(f"NOT NULL: {column}", description, failed, self.n)

    def check_unique(self, column: str, description: str) -> dict:
        non_null = self.df[column].dropna()
        if column == "email":
            keys = non_null.astype("string").str.strip().str.lower()
        else:
            keys = non_null
        failed = int(keys.duplicated().sum())
        return self._record(f"UNIQUE: {column}", description, failed, len(non_null))

    def check_regex(self, column: str, pattern: str, description: str) -> dict:
        non_null = self.df[column].dropna().astype("string")
        failed = int((~non_null.str.match(pattern, na=False)).sum())
        return self._record(f"REGEX: {column}", description, failed, len(non_null))

    def check_values_in_set(
        self,
        column: str,
        valid_values: list,
        description: str,
    ) -> dict:
        non_null = self.df[column].dropna()
        failed = int((~non_null.isin(valid_values)).sum())
        return self._record(
            f"VALUES IN SET: {column}",
            description,
            failed,
            len(non_null),
        )

    def check_numeric_range(
        self,
        column: str,
        min_value: float,
        max_value: float,
        description: str,
    ) -> dict:
        non_null = pd.to_numeric(self.df[column], errors="coerce").dropna()
        failed = int((~non_null.between(min_value, max_value)).sum())
        return self._record(
            f"NUMERIC RANGE: {column}",
            description,
            failed,
            len(non_null),
        )

    def check_date_range(
        self,
        column: str,
        min_date: str,
        max_date: str,
        description: str,
    ) -> dict:
        non_null = self.df[column].dropna()
        in_range = non_null.between(pd.Timestamp(min_date), pd.Timestamp(max_date))
        failed = int((~in_range).sum())
        return self._record(f"DATE RANGE: {column}", description, failed, len(non_null))

    def check_referential_integrity(
        self,
        foreign_key: str,
        primary_key: str,
        description: str,
    ) -> dict:
        """Require every non-null foreign key to exist in the primary-key column."""
        foreign_values = self.df[foreign_key].dropna().astype(str)
        primary_values = set(self.df[primary_key].dropna().astype(str))
        failed = int((~foreign_values.isin(primary_values)).sum())
        return self._record(
            f"REFERENTIAL INTEGRITY: {foreign_key} -> {primary_key}",
            description,
            failed,
            len(foreign_values),
        )

    def generate_report(self) -> pd.DataFrame:
        report = pd.DataFrame(self.results)
        logger.info("=" * 60)
        logger.info("DATA QUALITY REPORT")
        logger.info("=" * 60)
        for result in self.results:
            icon = "PASS" if result["status"] == "PASS" else "FAIL"
            logger.info(
                "  [%s] %s: %.1f%% (%s failed of %s)",
                icon,
                result["check"],
                result["pass_rate"] * 100,
                f"{result['failed']:,}",
                f"{result['total']:,}",
            )
        failed_checks = int((report["status"] == "FAIL").sum()) if not report.empty else 0
        logger.info("=" * 60)
        logger.info(
            "  SUMMARY: %s/%s checks passed (%s failed)",
            len(report) - failed_checks,
            len(report),
            failed_checks,
        )
        logger.info("=" * 60)
        return report


def enforce_quality_gate(
    report: pd.DataFrame,
    max_failed: int | None = None,
) -> None:
    """Halt the pipeline when failed checks exceed the configured allowance."""
    limit = (
        CONFIG["max_failed_quality_checks"] if max_failed is None else max_failed
    )
    failed_checks = int((report["status"] == "FAIL").sum()) if not report.empty else 0
    failed_names = (
        report.loc[report["status"] == "FAIL", "check"].tolist() if not report.empty else []
    )

    if failed_checks > limit:
        logger.critical(
            "Quality gate FAILED: %s checks failed (limit=%s). Failed checks: %s",
            failed_checks,
            limit,
            ", ".join(failed_names) if failed_names else "(none)",
        )
        raise QualityGateError(
            f"Quality gate failed: {failed_checks} checks failed "
            f"(limit {limit}). See {CONFIG['output_files']['quality_report_csv']}"
        )

    logger.info(
        "Quality gate passed: %s failed check(s) within limit of %s",
        failed_checks,
        limit,
    )


def run_quality_checks(
    df: pd.DataFrame,
    *,
    enforce_gate: bool = True,
) -> pd.DataFrame:
    """Run the GlobalTech HR quality suite (≥12 checks) and export reports.

    Args:
        df: Deduplicated employee DataFrame.
        enforce_gate: When True, raise ``QualityGateError`` if more than
            ``CONFIG['max_failed_quality_checks']`` checks FAIL.

    Returns:
        Quality report DataFrame with columns check, description, total,
        passed, failed, pass_rate, status.
    """
    logger.info("=" * 60)
    logger.info("STEP 4: Data quality validation")

    v = DataQualityValidator(df, threshold=CONFIG["quality_threshold"])

    # NOT NULL (6)
    v.check_not_null("employee_id", "Every employee must have a canonical employee ID")
    v.check_not_null("first_name", "Every employee must have a first name")
    v.check_not_null("last_name", "Every employee must have a last name")
    v.check_not_null("email", "Every employee must have an email address")
    v.check_not_null("department", "Every employee must be assigned to a department")
    v.check_not_null("country", "Every employee must have a country")

    # UNIQUE (2)
    v.check_unique("email", "Emails must be unique after deduplication")
    v.check_unique("employee_id", "Employee IDs must be unique after deduplication")

    # VALUES IN SET (2)
    v.check_values_in_set(
        "employment_type",
        CONFIG["valid_employment_types"],
        "Employment type must be Full-Time, Part-Time, or Contractor",
    )
    v.check_values_in_set(
        "currency",
        CONFIG["valid_currencies"],
        "Currency must be USD, EUR, or GBP when present",
    )

    # REGEX (2)
    v.check_regex(
        "email",
        CONFIG["email_regex"],
        "Emails must match a standard email format",
    )
    v.check_regex(
        "employee_id",
        CONFIG["employee_id_regex"],
        "Employee IDs must match GT-###### or AC-######",
    )

    # NUMERIC RANGE (1)
    v.check_numeric_range(
        "salary_usd_annual",
        CONFIG["minimum_annual_salary_usd"],
        CONFIG["maximum_annual_salary_usd"],
        "Annual USD salary must be between $15,000 and $2,000,000 when present",
    )

    # DATE RANGE (1)
    v.check_date_range(
        "hire_date",
        CONFIG["minimum_hire_date"],
        datetime.now().strftime("%Y-%m-%d"),
        "Hire dates must be between 1970-01-01 and today",
    )

    # REFERENTIAL INTEGRITY (1) — total 15 checks
    v.check_referential_integrity(
        "manager_id",
        "employee_id",
        "Every non-null manager_id must exist as an employee_id in the dataset",
    )

    report = v.generate_report()
    export_quality_report(report)

    if enforce_gate:
        enforce_quality_gate(report)

    return report
