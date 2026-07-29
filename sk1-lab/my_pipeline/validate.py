"""
Data quality validation checks and pass/fail reporting.
"""

from datetime import datetime

import pandas as pd

from config import CONFIG, logger


class DataQualityValidator:
    """
    Runs configurable quality checks and produces a pass/fail report.
    Designed to be reusable across projects — just swap the checks.
    """

    def __init__(self, df: pd.DataFrame, threshold: float = 0.95):
        self.df = df
        self.threshold = threshold
        self.results = []
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
        failed = int(non_null.duplicated().sum())
        return self._record(f"UNIQUE: {column}", description, failed, len(non_null))

    def check_regex(self, column: str, pattern: str, description: str) -> dict:
        non_null = self.df[column].dropna()
        failed = int((~non_null.str.match(pattern, na=False)).sum())
        return self._record(f"REGEX: {column}", description, failed, len(non_null))

    def check_values_in_set(self, column: str, valid_values: list, description: str) -> dict:
        non_null = self.df[column].dropna()
        failed = int((~non_null.isin(valid_values)).sum())
        return self._record(f"VALUES IN SET: {column}", description, failed, len(non_null))

    def check_date_range(self, column: str, min_date: str, max_date: str, description: str) -> dict:
        non_null = self.df[column].dropna()
        in_range = non_null.between(pd.Timestamp(min_date), pd.Timestamp(max_date))
        failed = int((~in_range).sum())
        return self._record(f"DATE RANGE: {column}", description, failed, len(non_null))

    def generate_report(self) -> pd.DataFrame:
        report = pd.DataFrame(self.results)
        logger.info("=" * 60)
        logger.info("DATA QUALITY REPORT")
        logger.info("=" * 60)
        for r in self.results:
            icon = "✓" if r["status"] == "PASS" else "✗"
            logger.info(
                f"  [{icon}] {r['check']}: {r['pass_rate']:.1%} "
                f"({r['failed']} failed of {r['total']})"
            )
        overall = (report["status"] == "PASS").all()
        logger.info("=" * 60)
        logger.info(f"  OVERALL: {'ALL CHECKS PASSED ✓' if overall else 'SOME CHECKS FAILED ✗'}")
        logger.info("=" * 60)
        return report


def run_quality_checks(df: pd.DataFrame) -> pd.DataFrame:
    """Run the standard ShopStream quality suite (7 checks)."""
    logger.info("STEP 4: Quality Validation")
    v = DataQualityValidator(df, threshold=CONFIG["quality_threshold"])
    v.check_not_null("email", "Every customer must have an email address")
    v.check_not_null("first_name", "Every customer must have a first name")
    v.check_not_null("region", "Every customer must be assigned to a region for campaign segmentation")
    v.check_unique("email", "Emails must be unique after deduplication")
    v.check_regex("email", CONFIG["email_regex"], "Emails must be in valid format")
    v.check_values_in_set("region", CONFIG["valid_regions"], "Region must be US, EU, or APAC")
    v.check_date_range(
        "registration_date",
        "2010-01-01",
        datetime.now().strftime("%Y-%m-%d"),
        "Registration dates must be between 2010 and today",
    )
    return v.generate_report()
