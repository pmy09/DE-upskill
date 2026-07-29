"""GlobalTech HR data integration pipeline.

Run the implemented pipeline stages from this directory:

    python3 pipeline.py
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from clean import clean_all_sources
from config import logger
from dedup import deduplicate_employees
from export import export_eda_report, export_final_artifacts
from ingest import ingest_all_sources
from validate import QualityGateError, run_quality_checks


SourceFrames = dict[str, pd.DataFrame]
PipelineResult = dict[str, Any]


def run_ingestion() -> SourceFrames:
    """Run Deliverable 1 and return standardized source DataFrames."""
    return ingest_all_sources()


def run_cleaning(frames: SourceFrames | None = None) -> SourceFrames:
    """Run Deliverable 2 on ingested source DataFrames.

    Args:
        frames: DataFrames returned by ``run_ingestion``. When omitted,
            ingestion runs first so this stage can also be called directly.

    Returns:
        Cleaned DataFrames keyed by source system.
    """
    source_frames = frames if frames is not None else run_ingestion()
    return clean_all_sources(source_frames)


def run_deduplication(frames: SourceFrames | None = None) -> PipelineResult:
    """Run Deliverable 3 multi-pass deduplication.

    Args:
        frames: Cleaned DataFrames from ``run_cleaning``. When omitted,
            ingestion and cleaning run first.

    Returns:
        Dictionary with ``employees``, ``ghost_employees``, and
        ``probable_matches`` DataFrames.
    """
    cleaned_frames = frames if frames is not None else run_cleaning()
    employees, ghosts, probable_matches = deduplicate_employees(cleaned_frames)
    return {
        "employees": employees,
        "ghost_employees": ghosts,
        "probable_matches": probable_matches,
    }


def run_validation(
    employees: pd.DataFrame | None = None,
    *,
    enforce_gate: bool = True,
) -> pd.DataFrame:
    """Run Deliverable 4 data quality validation.

    Args:
        employees: Deduplicated employees from ``run_deduplication``.
            When omitted, ingestion through deduplication run first.
        enforce_gate: When True, halt if more than two checks FAIL.

    Returns:
        Quality report DataFrame.
    """
    if employees is None:
        employees = run_deduplication()["employees"]
    return run_quality_checks(employees, enforce_gate=enforce_gate)


def run_eda(
    employees: pd.DataFrame | None = None,
    quality_report: pd.DataFrame | None = None,
) -> Path:
    """Run Deliverable 5 EDA visualization report.

    Args:
        employees: Deduplicated employees. When omitted, prior stages run first.
        quality_report: Validation report used by the quality dashboard chart.

    Returns:
        Path to the written PNG report.
    """
    if employees is None or quality_report is None:
        if employees is None:
            employees = run_deduplication()["employees"]
        if quality_report is None:
            quality_report = run_validation(employees, enforce_gate=False)
    return export_eda_report(employees, quality_report)


def run_export(
    employees: pd.DataFrame | None = None,
    ghosts: pd.DataFrame | None = None,
    probable_matches: pd.DataFrame | None = None,
) -> dict[str, Path]:
    """Run Deliverable 6 golden dataset and documentation export.

    Args:
        employees: Deduplicated employees.
        ghosts: Ghost-employee report frame.
        probable_matches: Fuzzy-match review frame.

    Returns:
        Paths for golden Parquet, schema doc, ghost CSV, and probable-match CSV.
    """
    if employees is None or ghosts is None or probable_matches is None:
        dedup_result = run_deduplication()
        employees = employees if employees is not None else dedup_result["employees"]
        ghosts = ghosts if ghosts is not None else dedup_result["ghost_employees"]
        probable_matches = (
            probable_matches
            if probable_matches is not None
            else dedup_result["probable_matches"]
        )
    return export_final_artifacts(employees, ghosts, probable_matches)


def run_pipeline() -> PipelineResult:
    """Run every pipeline stage in dependency order."""
    started_at = datetime.now()
    logger.info("=" * 60)
    logger.info("GLOBALTECH HR DATA INTEGRATION PIPELINE")
    logger.info("Pipeline started: %s", started_at.isoformat(timespec="seconds"))
    logger.info("=" * 60)

    ingested_frames = run_ingestion()
    cleaned_frames = run_cleaning(ingested_frames)
    dedup_result = run_deduplication(cleaned_frames)

    employees = dedup_result["employees"]
    ghosts = dedup_result["ghost_employees"]
    probable_matches = dedup_result["probable_matches"]

    try:
        quality_report = run_validation(employees, enforce_gate=True)
    except QualityGateError:
        logger.critical(
            "Pipeline halted by quality gate before golden export / EDA stages"
        )
        raise

    eda_path = run_eda(employees, quality_report)
    export_paths = run_export(employees, ghosts, probable_matches)

    empty_sources = [
        source_name
        for source_name, frame in cleaned_frames.items()
        if frame.empty
    ]
    if empty_sources:
        logger.warning(
            "Pipeline completed with empty source(s): %s",
            ", ".join(empty_sources),
        )

    completed_at = datetime.now()
    duration_seconds = (completed_at - started_at).total_seconds()
    failed_checks = int((quality_report["status"] == "FAIL").sum())

    logger.info("=" * 60)
    logger.info("PIPELINE COMPLETE")
    for source_name, frame in cleaned_frames.items():
        logger.info("  %-24s %s cleaned record(s)", source_name, f"{len(frame):,}")
    logger.info("  %-24s %s employee record(s)", "deduplicated", f"{len(employees):,}")
    logger.info("  %-24s %s ghost record(s)", "ghost_employees", f"{len(ghosts):,}")
    logger.info(
        "  %-24s %s probable pair(s)",
        "probable_matches",
        f"{len(probable_matches):,}",
    )
    logger.info(
        "  %-24s %s/%s checks passed",
        "quality",
        f"{len(quality_report) - failed_checks}",
        f"{len(quality_report)}",
    )
    logger.info("  %-24s %s", "eda_report", eda_path)
    logger.info("  %-24s %s", "golden_dataset", export_paths["golden_dataset"])
    logger.info("  %-24s %s", "schema_doc", export_paths["schema_doc"])
    if "dedup_method" in employees.columns:
        for method, count in employees["dedup_method"].value_counts().items():
            logger.info("  %-24s %s", f"method:{method}", f"{count:,}")
    logger.info("  %-24s %.2f seconds", "duration", duration_seconds)
    logger.info("=" * 60)

    return {
        **dedup_result,
        "quality_report": quality_report,
        "eda_report": eda_path,
        "golden_dataset": export_paths["golden_dataset"],
        "schema_doc": export_paths["schema_doc"],
        "export_paths": export_paths,
    }


if __name__ == "__main__":
    run_pipeline()
