"""
ShopStream Customer Data Quality Pipeline
==========================================
Entry point: ingest -> clean -> dedupe -> validate -> export.

Run from this directory:
    python3 pipeline.py
"""

from datetime import datetime

from config import logger
from ingest import ensure_raw_data, ingest_all_sources
from clean import clean_dataframe, deduplicate_customers
# from clean import infer_region_with_llm  # optional — requires ANTHROPIC_API_KEY
from validate import run_quality_checks
from export import export_results


def run_pipeline():
    """
    Main pipeline entry point.
    Orchestrates: Ingest -> Clean -> Deduplicate -> Validate -> Visualize -> Export
    """
    start_time = datetime.now()
    logger.info("=" * 60)
    logger.info("SHOPSTREAM CUSTOMER DATA QUALITY PIPELINE")
    logger.info(f"Run started: {start_time.isoformat()}")
    logger.info("=" * 60)

    ensure_raw_data()

    combined = ingest_all_sources()
    input_count = len(combined)

    cleaned = clean_dataframe(combined)
    deduped = deduplicate_customers(cleaned)

    # Optional AI enrichment (uncomment if anthropic + API key are available):
    # deduped = infer_region_with_llm(deduped)

    quality_report = run_quality_checks(deduped)
    export_results(deduped, quality_report)

    duration = (datetime.now() - start_time).total_seconds()
    logger.info("=" * 60)
    logger.info("PIPELINE COMPLETE")
    logger.info(f"  Input records:          {input_count:,}")
    logger.info(f"  Output (golden) records:{len(deduped):,}")
    logger.info(f"  Duplicates removed:     {input_count - len(deduped):,}")
    logger.info(
        f"  Quality checks passed:  "
        f"{(quality_report['status'] == 'PASS').sum()}/{len(quality_report)}"
    )
    logger.info(f"  Duration:               {duration:.1f}s")
    logger.info("=" * 60)


if __name__ == "__main__":
    run_pipeline()
