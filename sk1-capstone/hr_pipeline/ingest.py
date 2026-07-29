"""Load and standardize the four GlobalTech HR source files."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd

from config import CONFIG, logger
from export import write_dead_letters


# These mappings document how each source field enters the common schema.
SOURCE_COLUMN_MAPPINGS: dict[str, dict[str, str]] = {
    "globaltech_hris": {
        "employee_id": "employee_id",
        "first_name": "first_name",
        "last_name": "last_name",
        "email": "email",
        "department": "department",
        "job_title": "job_title",
        "hire_date": "hire_date",
        "country": "country",
        "employment_type": "employment_type",
        "manager_id": "manager_id",
    },
    "acquiredco_hris": {
        "employee_identifier": "employee_id",
        "name_first": "first_name",
        "name_last": "last_name",
        "contact_email": "email",
        "assignment_department": "department",
        "assignment_role": "job_title",
        "assignment_hire_timestamp": "hire_date",
        "assignment_location": "country",
        "employment_type": "employment_type",
        "employment_status": "employment_status",
        "manager_employee_id": "manager_id",
    },
    "payroll": {
        "employee_id": "employee_id",
        "source": "company_origin",
        "base_salary": "base_salary",
        "currency": "currency",
        "pay_frequency": "pay_frequency",
        "bonus_target_pct": "bonus_target_pct",
        "effective_date": "payroll_effective_date",
    },
    "benefits": {
        "employee_id": "employee_id",
        "plan_type": "benefit_plans",
        "coverage_level": "benefit_coverage_level",
        "enrollment_date": "benefit_enrollment_date",
        "premium_employee": "premium_employee",
        "premium_employer": "premium_employer",
    },
}

SOURCE_COMPANY_ORIGIN = {
    "globaltech_hris": "GlobalTech",
    "acquiredco_hris": "AcquiredCo",
    "benefits": "GlobalTech",
}

SOURCE_REQUIRED_COLUMNS = {
    "globaltech_hris": set(SOURCE_COLUMN_MAPPINGS["globaltech_hris"]),
    "acquiredco_hris": {
        "employee_identifier",
        "name_first",
        "name_last",
        "contact_email",
    },
    "payroll": set(SOURCE_COLUMN_MAPPINGS["payroll"]),
    "benefits": set(SOURCE_COLUMN_MAPPINGS["benefits"]),
}


def _empty_standard_frame() -> pd.DataFrame:
    """Return an empty DataFrame with the configured standard schema."""
    return pd.DataFrame(columns=CONFIG["standard_schema"])


def _record_file_failure(source_name: str, filepath: Path, error: Exception) -> None:
    """Log a file-level ingestion failure without raising it."""
    reason = f"{type(error).__name__}: {error}"
    logger.error("Could not ingest %s from %s: %s", source_name, filepath, reason)
    write_dead_letters(
        source_name,
        [{"filepath": str(filepath)}],
        reason,
    )


def _check_required_columns(df: pd.DataFrame, source_name: str) -> bool:
    """Dead-letter a schema error and return False when columns are missing."""
    missing = SOURCE_REQUIRED_COLUMNS[source_name] - set(df.columns)
    if not missing:
        return True

    reason = f"Missing required columns: {sorted(missing)}"
    logger.error("%s schema validation failed: %s", source_name, reason)
    write_dead_letters(
        source_name,
        [{"available_columns": list(df.columns)}],
        reason,
    )
    return False


def _reject_missing_identity(
    df: pd.DataFrame,
    source_name: str,
    identity_column: str,
) -> pd.DataFrame:
    """Remove and dead-letter records that have no usable employee identity."""
    identity = df[identity_column]
    invalid_mask = identity.isna() | identity.astype(str).str.strip().eq("")
    if invalid_mask.any():
        write_dead_letters(
            source_name,
            df.loc[invalid_mask].to_dict(orient="records"),
            f"Missing required identity field: {identity_column}",
        )
    return df.loc[~invalid_mask].copy()


def align_schema(df: pd.DataFrame, source_name: str) -> pd.DataFrame:
    """Map one source DataFrame to the documented standard employee schema.

    Args:
        df: Source DataFrame using the native/normalized source column names.
        source_name: One of ``globaltech_hris``, ``acquiredco_hris``,
            ``payroll``, or ``benefits``.

    Returns:
        A new DataFrame containing every configured standard column. Fields
        unavailable in a source are filled with ``pd.NA``.

    Raises:
        ValueError: If ``source_name`` has no documented column mapping.
    """
    if source_name not in SOURCE_COLUMN_MAPPINGS:
        raise ValueError(f"Unsupported source for schema alignment: {source_name}")

    renamed = df.rename(columns=SOURCE_COLUMN_MAPPINGS[source_name])
    aligned = pd.DataFrame(index=renamed.index)

    for column in CONFIG["standard_schema"]:
        aligned[column] = renamed[column] if column in renamed.columns else pd.NA

    aligned["source_system"] = source_name

    if source_name in SOURCE_COMPANY_ORIGIN:
        aligned["company_origin"] = SOURCE_COMPANY_ORIGIN[source_name]
    elif source_name == "payroll":
        aligned["company_origin"] = (
            aligned["company_origin"]
            .astype("string")
            .str.strip()
            .replace({"<NA>": pd.NA})
        )

    if source_name == "benefits":
        aligned["benefits_enrolled"] = True
        aligned["benefit_plan_count"] = 1

    return aligned.reset_index(drop=True)


def ingest_globaltech_csv(filepath: Path) -> pd.DataFrame:
    """Load and standardize the GlobalTech Workday CSV export.

    Args:
        filepath: Path to the UTF-8 GlobalTech HRIS CSV file.

    Returns:
        A standard-schema DataFrame. Missing files, unreadable files, malformed
        CSV rows, and schema failures are logged/dead-lettered rather than
        raised.
    """
    source_name = "globaltech_hris"
    logger.info("Ingesting %s CSV: %s", source_name, filepath)
    malformed_rows: list[dict[str, Any]] = []

    def capture_bad_line(fields: list[str]) -> None:
        malformed_rows.append({"fields": fields})
        return None

    try:
        df = pd.read_csv(
            filepath,
            encoding="utf-8",
            engine="python",
            on_bad_lines=capture_bad_line,
            dtype={"employee_id": "string", "manager_id": "string"},
        )
    except (OSError, UnicodeError, pd.errors.ParserError) as error:
        _record_file_failure(source_name, filepath, error)
        return _empty_standard_frame()

    write_dead_letters(source_name, malformed_rows, "Malformed CSV row")
    if not _check_required_columns(df, source_name):
        return _empty_standard_frame()

    df = _reject_missing_identity(df, source_name, "employee_id")
    aligned = align_schema(df, source_name)
    logger.info("Ingested %s records from %s", f"{len(aligned):,}", source_name)
    return aligned


def ingest_acquiredco_json(
    filepath: Path,
    page_size: int = CONFIG["acquiredco_page_size"],
) -> pd.DataFrame:
    """Load the AcquiredCo JSON export using simulated API pagination.

    Args:
        filepath: Path to the nested BambooHR-style JSON export.
        page_size: Number of employee records to process per simulated page.
            Must be greater than zero.

    Returns:
        A flattened standard-schema DataFrame. Invalid records are sent to the
        dead-letter file and valid records continue through the pipeline.
    """
    source_name = "acquiredco_hris"
    logger.info(
        "Ingesting %s JSON with simulated page size %s: %s",
        source_name,
        page_size,
        filepath,
    )

    if page_size <= 0:
        error = ValueError("page_size must be greater than zero")
        _record_file_failure(source_name, filepath, error)
        return _empty_standard_frame()

    try:
        with filepath.open("r", encoding="utf-8") as file:
            payload = json.load(file)
        employees = payload["employees"]
        if not isinstance(employees, list):
            raise TypeError("'employees' must be a list")
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as error:
        _record_file_failure(source_name, filepath, error)
        return _empty_standard_frame()

    valid_records: list[dict[str, Any]] = []
    invalid_records: list[dict[str, Any]] = []

    for page_number, start in enumerate(range(0, len(employees), page_size), start=1):
        page = employees[start : start + page_size]
        for record in page:
            if not isinstance(record, dict) or not record.get("employee_identifier"):
                invalid_records.append(
                    record if isinstance(record, dict) else {"raw_value": record}
                )
                continue
            valid_records.append(record)
        logger.info(
            "Processed simulated page %s (%s record(s))",
            page_number,
            len(page),
        )

    write_dead_letters(
        source_name,
        invalid_records,
        "Malformed JSON employee or missing employee_identifier",
    )

    expected_count = payload.get("total_records")
    if expected_count is not None and expected_count != len(employees):
        logger.warning(
            "%s metadata count is %s but the file contains %s records",
            source_name,
            expected_count,
            len(employees),
        )

    if not valid_records:
        return _empty_standard_frame()

    df = pd.json_normalize(valid_records, sep="_")
    if not _check_required_columns(df, source_name):
        return _empty_standard_frame()

    aligned = align_schema(df, source_name)
    logger.info("Ingested %s records from %s", f"{len(aligned):,}", source_name)
    return aligned


def ingest_payroll_excel(filepath: Path) -> pd.DataFrame:
    """Load and standardize the combined ADP payroll Excel export.

    Args:
        filepath: Path to the ``.xlsx`` payroll workbook.

    Returns:
        A standard-schema DataFrame containing both company origins. Missing
        identities and malformed files are dead-lettered without stopping the
        pipeline.
    """
    source_name = "payroll"
    logger.info("Ingesting payroll Excel workbook: %s", filepath)

    try:
        df = pd.read_excel(
            filepath,
            dtype={"employee_id": "string", "source": "string"},
        )
    except (OSError, ImportError, ValueError) as error:
        _record_file_failure(source_name, filepath, error)
        return _empty_standard_frame()

    if not _check_required_columns(df, source_name):
        return _empty_standard_frame()

    df = _reject_missing_identity(df, source_name, "employee_id")
    invalid_origin = ~df["source"].isin(["GlobalTech", "AcquiredCo"])
    if invalid_origin.any():
        write_dead_letters(
            source_name,
            df.loc[invalid_origin].to_dict(orient="records"),
            "Unknown payroll company source",
        )
        df = df.loc[~invalid_origin].copy()

    aligned = align_schema(df, source_name)
    logger.info("Ingested %s records from %s", f"{len(aligned):,}", source_name)
    return aligned


def ingest_benefits_xml(filepath: Path) -> pd.DataFrame:
    """Load and standardize the MedShield benefits XML export.

    Args:
        filepath: Path to the XML file whose root contains ``enrollment``
            elements.

    Returns:
        One standard-schema row per valid enrollment. Records missing an
        employee ID or plan type are dead-lettered; malformed XML returns an
        empty standard DataFrame.
    """
    source_name = "benefits"
    logger.info("Ingesting benefits XML: %s", filepath)

    try:
        root = ET.parse(filepath).getroot()
    except (OSError, ET.ParseError) as error:
        _record_file_failure(source_name, filepath, error)
        return _empty_standard_frame()

    records: list[dict[str, Any]] = []
    invalid_records: list[dict[str, Any]] = []

    for enrollment in root.findall("enrollment"):
        record = {
            child.tag: child.text.strip() if child.text else None
            for child in enrollment
        }
        if not record.get("employee_id") or not record.get("plan_type"):
            invalid_records.append(record)
            continue
        records.append(record)

    write_dead_letters(
        source_name,
        invalid_records,
        "Malformed enrollment or missing employee_id/plan_type",
    )

    if not records:
        return _empty_standard_frame()

    df = pd.DataFrame(records)
    if not _check_required_columns(df, source_name):
        return _empty_standard_frame()

    aligned = align_schema(df, source_name)
    logger.info("Ingested %s records from %s", f"{len(aligned):,}", source_name)
    return aligned


def ingest_all_sources(
    input_files: dict[str, Path] | None = None,
) -> dict[str, pd.DataFrame]:
    """Run every source loader and return standardized DataFrames by source.

    Args:
        input_files: Optional source-name-to-path mapping. Defaults to the
            configured four production input files.

    Returns:
        A dictionary keyed by ``globaltech_hris``, ``acquiredco_hris``,
        ``payroll``, and ``benefits``. Keeping frames separate preserves their
        different grains for the cleaning and deduplication stages.
    """
    files = input_files or CONFIG["input_files"]
    loaders: dict[str, Callable[[Path], pd.DataFrame]] = {
        "globaltech_hris": ingest_globaltech_csv,
        "acquiredco_hris": ingest_acquiredco_json,
        "payroll": ingest_payroll_excel,
        "benefits": ingest_benefits_xml,
    }

    logger.info("=" * 60)
    logger.info("STEP 1: Multi-source ingestion")

    frames: dict[str, pd.DataFrame] = {}
    for source_name, loader in loaders.items():
        filepath = Path(files.get(source_name, CONFIG["input_files"][source_name]))
        frames[source_name] = loader(filepath)

    logger.info("Ingestion summary")
    for source_name, frame in frames.items():
        logger.info("  %-20s %s record(s)", source_name, f"{len(frame):,}")
    logger.info(
        "  %-20s %s record(s)",
        "total",
        f"{sum(len(frame) for frame in frames.values()):,}",
    )
    return frames


# if __name__ == "__main__":
#     ingest_all_sources()
