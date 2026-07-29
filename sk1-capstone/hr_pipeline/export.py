"""Pipeline output writing for review reports and quality artifacts."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from html import escape
from pathlib import Path

import pandas as pd

from config import CONFIG, logger
from visualize import generate_eda_report

GHOST_EMPLOYEE_COLUMNS = [
    "payroll_employee_id",
    "name",
    "salary_usd_annual",
    "ghost_flag_reason",
    "ghost_employee",
    "company_origin",
    "source_system",
]

PROBABLE_MATCH_REQUIRED_COLUMNS = [
    "record_1_id",
    "record_2_id",
    "similarity_score",
    "hire_date_diff_days",
    "recommended_action",
]

PROBABLE_MATCH_EXPORT_COLUMNS = [
    "record_1_id",
    "record_2_id",
    "similarity_score",
    "hire_date_diff_days",
    "recommended_action",
    "record_1_name",
    "record_2_name",
    "record_1_company",
    "record_2_company",
    "dedup_method",
]

UNMAPPED_DEPARTMENT_COLUMNS = [
    "source_system",
    "company_origin",
    "department_original",
    "record_count",
]

GOLDEN_COLUMN_DESCRIPTIONS: dict[str, str] = {
    "employee_id": "Canonical namespaced employee ID (GT-###### or AC-######)",
    "first_name": "Standardized given name (Unicode NFKC, title case)",
    "last_name": "Standardized family name (Unicode NFKC, title case)",
    "email": "Work email address used for identity matching",
    "department": "Mapped standard department name",
    "job_title": "Job title as provided by the source HRIS",
    "hire_date": "Parsed hire date (datetime64[ns])",
    "country": "Work location country",
    "employment_type": "Standard employment type: Full-Time, Part-Time, or Contractor",
    "employment_status": "Employment status when provided by the source",
    "manager_id": "Namespaced manager employee ID, when present",
    "company_origin": "Partition key: GlobalTech or AcquiredCo",
    "source_system": "Primary contributing source system for the surviving row",
    "employee_id_raw": "Original employee ID before namespacing",
    "manager_id_raw": "Original manager ID before namespacing",
    "department_original": "Department value before taxonomy mapping",
    "department_unmapped": "True when the original department was not in the taxonomy map",
    "hire_date_invalid": "True when hire_date could not be parsed cleanly",
    "payroll_effective_date_invalid": "True when payroll_effective_date was invalid",
    "benefit_enrollment_date_invalid": "True when benefit_enrollment_date was invalid",
    "source_systems": "Comma-separated provenance of all contributing sources",
    "dedup_method": "How the row was resolved: exact_id, email_match, fuzzy_name, or single_source",
    "base_salary": "Original salary amount before FX / frequency conversion",
    "currency": "ISO currency code for base_salary (USD, EUR, GBP)",
    "pay_frequency": "Payroll frequency: Annual, Monthly, or Bi-Weekly",
    "bonus_target_pct": "Target bonus percentage from payroll, when present",
    "payroll_effective_date": "Effective date of the retained payroll record",
    "salary_usd_annual": "Annualized salary converted to USD using configured FX rates",
    "benefits_enrolled": "True when the employee has at least one benefits enrollment",
    "benefit_plans": "Aggregated benefit plan names for the employee",
    "benefit_plan_count": "Number of distinct benefit plans enrolled",
    "benefit_coverage_level": "Coverage level from the latest enrollment",
    "benefit_enrollment_date": "Most recent benefit enrollment date",
    "premium_employee": "Employee premium amount from benefits",
    "premium_employer": "Employer premium amount from benefits",
}


def write_csv(
    frame: pd.DataFrame,
    path: Path,
    *,
    empty_columns: list[str] | None = None,
    log: bool = True,
) -> Path:
    """Write a CSV report, including headers when the frame is empty."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    export = frame.copy()
    if export.empty and empty_columns is not None:
        export = pd.DataFrame(columns=empty_columns)
    export.to_csv(path, index=False, encoding="utf-8")
    if log:
        logger.info("Wrote %s (%s row(s))", path, f"{len(frame):,}")
    return path


def write_dead_letters(
    source_name: str,
    records: list[dict],
    reason: str,
) -> Path | None:
    """Append rejected records to a source-specific dead-letter CSV."""
    if not records:
        return None

    dead_letters = pd.DataFrame(
        {
            "rejected_at_utc": datetime.now(timezone.utc).isoformat(),
            "source_system": source_name,
            "reason": reason,
            "raw_record": [
                json.dumps(record, ensure_ascii=False, default=str)
                for record in records
            ],
        }
    )
    output_path = Path(CONFIG["dead_letter_dir"]) / f"{source_name}_dead_letters.csv"
    write_header = not output_path.exists()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    dead_letters.to_csv(
        output_path,
        mode="a",
        header=write_header,
        index=False,
        encoding="utf-8",
    )
    logger.warning(
        "Dead-lettered %s %s record(s): %s",
        len(records),
        source_name,
        reason,
    )
    return output_path


def export_unmapped_departments(
    frames: dict[str, pd.DataFrame],
    output_path: Path | None = None,
) -> pd.DataFrame:
    """Aggregate and write unique unmapped departments for manual review."""
    output_path = Path(output_path or CONFIG["output_files"]["unmapped_departments"])
    review_frames = []

    for frame in frames.values():
        if "department_unmapped" not in frame:
            continue
        unmapped = frame.loc[
            frame["department_unmapped"],
            ["source_system", "company_origin", "department_original"],
        ]
        if not unmapped.empty:
            review_frames.append(unmapped)

    if review_frames:
        review = (
            pd.concat(review_frames, ignore_index=True)
            .groupby(
                ["source_system", "company_origin", "department_original"],
                dropna=False,
            )
            .size()
            .rename("record_count")
            .reset_index()
            .sort_values(
                ["source_system", "department_original"],
                ignore_index=True,
            )
        )
    else:
        review = pd.DataFrame(columns=UNMAPPED_DEPARTMENT_COLUMNS)

    write_csv(
        review,
        output_path,
        empty_columns=UNMAPPED_DEPARTMENT_COLUMNS,
        log=False,
    )
    logger.info(
        "Unmapped department review: %s value(s) written to %s",
        len(review),
        output_path,
    )
    return review


def export_ghost_employees(
    ghosts: pd.DataFrame,
    output_path: Path | None = None,
) -> Path:
    """Write the ghost-employee review CSV."""
    output_path = Path(output_path or CONFIG["output_files"]["ghost_employees"])
    return write_csv(ghosts, output_path, empty_columns=GHOST_EMPLOYEE_COLUMNS)


def export_probable_matches(
    probable_matches: pd.DataFrame,
    output_path: Path | None = None,
) -> Path:
    """Write the fuzzy-match HR review CSV."""
    output_path = Path(output_path or CONFIG["output_files"]["probable_matches"])
    if probable_matches.empty:
        review_export = probable_matches
    else:
        keep = [
            column
            for column in PROBABLE_MATCH_EXPORT_COLUMNS
            if column in probable_matches.columns
        ]
        review_export = probable_matches[keep]
    return write_csv(
        review_export,
        output_path,
        empty_columns=PROBABLE_MATCH_REQUIRED_COLUMNS,
    )


def export_quality_report(report: pd.DataFrame) -> dict[str, Path]:
    """Write the quality report as CSV and a styled HTML summary table."""
    csv_path = Path(CONFIG["output_files"]["quality_report_csv"])
    html_path = Path(CONFIG["output_files"]["quality_report_html"])
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    export = report.copy()
    export.to_csv(csv_path, index=False, encoding="utf-8")
    logger.info("Wrote quality report CSV: %s (%s row(s))", csv_path, f"{len(export):,}")

    header_cells = "".join(f"<th>{escape(str(column))}</th>" for column in export.columns)
    body_rows: list[str] = []
    for _, row in export.iterrows():
        css_class = "pass" if row.get("status") == "PASS" else "fail"
        cells = "".join(
            f"<td>{escape(str(row[column]))}</td>" for column in export.columns
        )
        body_rows.append(f'<tr class="{css_class}">{cells}</tr>')
    table_html = (
        '<table class="quality-report">'
        f"<thead><tr>{header_cells}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody>"
        "</table>"
    )

    generated_at = datetime.now().isoformat(timespec="seconds")
    html_document = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>GlobalTech HR Data Quality Report</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 2rem; color: #222; }}
    h1 {{ margin-bottom: 0.25rem; }}
    .meta {{ color: #555; margin-bottom: 1.5rem; }}
    table.quality-report {{ border-collapse: collapse; width: 100%; font-size: 0.95rem; }}
    table.quality-report th, table.quality-report td {{
      border: 1px solid #ccc; padding: 0.5rem 0.75rem; text-align: left;
    }}
    table.quality-report th {{ background: #f0f0f0; }}
    table.quality-report tr.pass td {{ background-color: #d4edda; }}
    table.quality-report tr.fail td {{ background-color: #f8d7da; }}
  </style>
</head>
<body>
  <h1>GlobalTech HR Data Quality Report</h1>
  <p class="meta">Generated: {generated_at}</p>
  {table_html}
</body>
</html>
"""
    html_path.write_text(html_document, encoding="utf-8")
    logger.info("Wrote quality report HTML: %s", html_path)
    return {"csv": csv_path, "html": html_path}


def export_eda_report(
    employees: pd.DataFrame,
    quality_report: pd.DataFrame,
    output_path: Path | None = None,
) -> Path:
    """Write the Deliverable 5 EDA visualization PNG."""
    return generate_eda_report(employees, quality_report, output_path=output_path)


def _example_value(series: pd.Series) -> str:
    """Format a single non-null example value for schema documentation."""
    non_null = series.dropna()
    if non_null.empty:
        return ""
    value = non_null.iloc[0]
    if pd.isna(value):
        return ""
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    text = str(value)
    if len(text) > 80:
        return text[:77] + "..."
    return text


def build_schema_frame(employees: pd.DataFrame) -> pd.DataFrame:
    """Build column / dtype / description / example documentation rows."""
    rows = []
    for column in employees.columns:
        rows.append(
            {
                "column_name": column,
                "data_type": str(employees[column].dtype),
                "description": GOLDEN_COLUMN_DESCRIPTIONS.get(
                    column,
                    "Derived or source field retained on the golden employee record",
                ),
                "example_value": _example_value(employees[column]),
            }
        )
    return pd.DataFrame(rows)


def write_schema_documentation(
    employees: pd.DataFrame,
    output_path: Path | None = None,
) -> Path:
    """Write markdown schema documentation for the golden employee dataset."""
    output_path = Path(output_path or CONFIG["output_files"]["schema_doc"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    schema = build_schema_frame(employees)

    lines = [
        "# Golden Employee Dataset Schema",
        "",
        "Unified, cleaned, and deduplicated employee records exported as Parquet "
        "partitioned by `company_origin`.",
        "",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        f"Record count: {len(employees):,}",
        "",
        "| column_name | data_type | description | example_value |",
        "|---|---|---|---|",
    ]
    for _, row in schema.iterrows():
        example = str(row["example_value"]).replace("|", "\\|")
        description = str(row["description"]).replace("|", "\\|")
        lines.append(
            f"| `{row['column_name']}` | `{row['data_type']}` | "
            f"{description} | {example} |"
        )
    lines.append("")
    output_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Wrote schema documentation: %s", output_path)
    return output_path


def _prepare_for_parquet(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize dtypes so mixed object columns serialize cleanly to Parquet."""
    export = frame.copy()
    for column in export.columns:
        if export[column].dtype == object:
            export[column] = (
                export[column]
                .map(lambda value: pd.NA if pd.isna(value) else str(value))
                .astype("string")
            )
    return export


def export_golden_dataset(
    employees: pd.DataFrame,
    output_path: Path | None = None,
) -> Path:
    """Write the golden employee Parquet dataset partitioned by company_origin."""
    output_path = Path(output_path or CONFIG["output_files"]["golden_dataset"])
    if "company_origin" not in employees.columns:
        raise KeyError("Golden export requires a company_origin column")

    if output_path.exists():
        if output_path.is_dir():
            shutil.rmtree(output_path)
        else:
            output_path.unlink()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    export = _prepare_for_parquet(employees)
    export["company_origin"] = export["company_origin"].astype("string").fillna("Unknown")

    export.to_parquet(
        output_path,
        engine="pyarrow",
        compression="snappy",
        index=False,
        partition_cols=["company_origin"],
    )

    partition_counts = export["company_origin"].value_counts(dropna=False).to_dict()
    logger.info(
        "Wrote golden dataset: %s (%s row(s); partitions=%s)",
        output_path,
        f"{len(export):,}",
        partition_counts,
    )
    return output_path


def export_final_artifacts(
    employees: pd.DataFrame,
    ghosts: pd.DataFrame,
    probable_matches: pd.DataFrame,
) -> dict[str, Path]:
    """Write Deliverable 6 golden outputs and refresh review CSVs."""
    logger.info("=" * 60)
    logger.info("STEP 6: Golden dataset & documentation export")

    ghost_path = export_ghost_employees(ghosts)
    probable_path = export_probable_matches(probable_matches)
    golden_path = export_golden_dataset(employees)
    schema_path = write_schema_documentation(employees)

    return {
        "golden_dataset": golden_path,
        "schema_doc": schema_path,
        "ghost_employees": ghost_path,
        "probable_matches": probable_path,
    }
