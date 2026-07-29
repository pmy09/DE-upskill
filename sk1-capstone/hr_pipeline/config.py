"""Global configuration and logging for the GlobalTech HR pipeline."""

from __future__ import annotations

import logging
from pathlib import Path


# config.py lives in <project_root>/hr_pipeline/.
PIPELINE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PIPELINE_DIR.parent

RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DATA_DIR = PROJECT_ROOT / "data" / "processed"
DEAD_LETTER_DIR = PROCESSED_DATA_DIR / "dead_letter"
LOG_DIR = PROJECT_ROOT / "logs"

INPUT_FILES = {
    "globaltech_hris": RAW_DATA_DIR / "globaltech_hris.csv",
    "acquiredco_hris": RAW_DATA_DIR / "acquiredco_api.json",
    "payroll": RAW_DATA_DIR / "payroll_data.xlsx",
    "benefits": RAW_DATA_DIR / "benefits_enrollment.xml",
}

OUTPUT_FILES = {
    "golden_dataset": PROCESSED_DATA_DIR / "golden_employees",
    "ghost_employees": PROCESSED_DATA_DIR / "ghost_employees.csv",
    "probable_matches": PROCESSED_DATA_DIR / "probable_matches.csv",
    "quality_report_csv": PROCESSED_DATA_DIR / "quality_report.csv",
    "quality_report_html": PROCESSED_DATA_DIR / "quality_report.html",
    "eda_report": PROCESSED_DATA_DIR / "hr_eda_report.png",
    "unmapped_departments": PROCESSED_DATA_DIR / "unmapped_departments.csv",
    "schema_doc": PROJECT_ROOT / "docs" / "schema.md",
}

STANDARD_EMPLOYEE_SCHEMA = [
    "employee_id",
    "first_name",
    "last_name",
    "email",
    "department",
    "job_title",
    "hire_date",
    "country",
    "employment_type",
    "employment_status",
    "manager_id",
    "company_origin",
    "source_system",
    "base_salary",
    "currency",
    "pay_frequency",
    "bonus_target_pct",
    "payroll_effective_date",
    "salary_usd_annual",
    "benefits_enrolled",
    "benefit_plans",
    "benefit_plan_count",
    "benefit_coverage_level",
    "benefit_enrollment_date",
    "premium_employee",
    "premium_employer",
]

# Fixed project rates: one unit of source currency expressed in USD.
EXCHANGE_RATES_TO_USD = {
    "USD": 1.00,
    "EUR": 1.09,
    "GBP": 1.27,
}

PAY_FREQUENCY_MULTIPLIERS = {
    "Annual": 1,
    "Monthly": 12,
    "Bi-Weekly": 26,
}

EMPLOYMENT_TYPE_MAP = {
    "FT": "Full-Time",
    "FULL-TIME": "Full-Time",
    "FULL TIME": "Full-Time",
    "PT": "Part-Time",
    "PART-TIME": "Part-Time",
    "PART TIME": "Part-Time",
    "CONTRACTOR": "Contractor",
}

STANDARD_DEPARTMENTS = [
    "Business Development",
    "Communications",
    "Customer Success",
    "Data Science",
    "DevOps",
    "Engineering",
    "Finance",
    "Human Resources",
    "Information Technology",
    "Legal",
    "Manufacturing",
    "Marketing",
    "Operations",
    "Product",
    "Quality Assurance",
    "Sales",
    "Strategy",
    "Supply Chain",
]

# The provided data uses department names. Code aliases preserve the mapping
# behavior required by the brief if coded values appear in future extracts.
DEPARTMENT_MAP = {
    **{department.upper(): department for department in STANDARD_DEPARTMENTS},
    "ENG-01": "Engineering",
    "MKT-03": "Marketing",
}

SOURCE_PRIORITY = {
    "globaltech_hris": 1,
    "acquiredco_hris": 1,
    "payroll": 2,
    "benefits": 3,
}

CONFIG = {
    "pipeline_dir": PIPELINE_DIR,
    "project_root": PROJECT_ROOT,
    "input_dir": RAW_DATA_DIR,
    "output_dir": PROCESSED_DATA_DIR,
    "dead_letter_dir": DEAD_LETTER_DIR,
    "log_dir": LOG_DIR,
    "input_files": INPUT_FILES,
    "output_files": OUTPUT_FILES,
    "standard_schema": STANDARD_EMPLOYEE_SCHEMA,
    "exchange_rates_to_usd": EXCHANGE_RATES_TO_USD,
    "pay_frequency_multipliers": PAY_FREQUENCY_MULTIPLIERS,
    "employment_type_map": EMPLOYMENT_TYPE_MAP,
    "standard_departments": STANDARD_DEPARTMENTS,
    "department_map": DEPARTMENT_MAP,
    "source_priority": SOURCE_PRIORITY,
    "acquiredco_page_size": 100,
    "fuzzy_match_threshold": 88,
    "fuzzy_hire_date_window_days": 30,
    "quality_threshold": 0.95,
    "max_failed_quality_checks": 2,
    "email_regex": r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$",
    "employee_id_regex": r"^(GT|AC)-\d{6}$",
    "valid_employment_types": ["Full-Time", "Part-Time", "Contractor"],
    "valid_currencies": list(EXCHANGE_RATES_TO_USD),
    "minimum_hire_date": "1970-01-01",
    "minimum_annual_salary_usd": 15000,
    "maximum_annual_salary_usd": 2000000,
    "eda_dpi": 300,
}


for directory in (PROCESSED_DATA_DIR, DEAD_LETTER_DIR, LOG_DIR):
    directory.mkdir(parents=True, exist_ok=True)

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_LOG_FILE = LOG_DIR / "pipeline.log"

logger = logging.getLogger("globaltech_hr_pipeline")
logger.setLevel(logging.INFO)
logger.propagate = False

if not logger.handlers:
    formatter = logging.Formatter(_LOG_FORMAT)

    file_handler = logging.FileHandler(_LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
