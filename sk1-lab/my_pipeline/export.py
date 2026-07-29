"""
Pipeline output writing: golden datasets, quality report, and EDA chart.
"""

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from config import CONFIG, logger


def generate_eda_report(df: pd.DataFrame, output_dir: Path):
    """Generate a professional 6-chart EDA and quality visualization."""
    logger.info("STEP 5: Generating EDA visualization...")

    fig, axes = plt.subplots(2, 3, figsize=(18, 10))
    fig.suptitle("ShopStream Customer Data Quality Report", fontsize=16, fontweight="bold")
    colors = ["#2196F3", "#4CAF50", "#FF9800", "#F44336", "#9C27B0", "#00BCD4"]

    # 1. Customer Count by Region
    region_counts = df["region"].value_counts()
    axes[0, 0].bar(region_counts.index, region_counts.values, color=colors[:len(region_counts)])
    axes[0, 0].set_title("Customers by Region")
    axes[0, 0].set_ylabel("Count")
    for i, (r, c) in enumerate(region_counts.items()):
        axes[0, 0].text(i, c + 50, f"{c:,}", ha="center", fontweight="bold", fontsize=9)

    # 2. Registration Trend
    dated = df.dropna(subset=["registration_date"]).set_index("registration_date")
    try:
        monthly = dated.resample("ME").size()
    except ValueError:
        monthly = dated.resample("M").size()
    axes[0, 1].plot(monthly.index, monthly.values, color=colors[0], linewidth=2)
    axes[0, 1].fill_between(monthly.index, monthly.values, alpha=0.2, color=colors[0])
    axes[0, 1].set_title("Monthly Registration Trend")
    axes[0, 1].set_ylabel("New Customers")
    axes[0, 1].tick_params(axis="x", rotation=45)

    # 3. Source Contribution
    if "sources" in df.columns:
        source_counts = df["sources"].str.split(",").explode().value_counts()
    else:
        source_counts = df["source"].value_counts()
    axes[0, 2].pie(
        source_counts.values,
        labels=source_counts.index,
        autopct="%1.1f%%",
        colors=colors[:len(source_counts)],
        startangle=90,
    )
    axes[0, 2].set_title("Records by Source System")

    # 4. Field Completeness
    fields = ["email", "first_name", "last_name", "phone", "region"]
    completeness = df[fields].notna().mean().sort_values()
    bar_colors = ["#F44336" if v < 0.9 else "#4CAF50" for v in completeness.values]
    axes[1, 0].barh(completeness.index, completeness.values, color=bar_colors)
    axes[1, 0].set_xlim(0, 1.1)
    axes[1, 0].axvline(
        x=CONFIG["quality_threshold"],
        color="red",
        linestyle="--",
        label=f"{CONFIG['quality_threshold']:.0%} threshold",
    )
    axes[1, 0].set_title("Field Completeness Rate")
    axes[1, 0].legend(fontsize=8)
    for i, v in enumerate(completeness.values):
        axes[1, 0].text(v + 0.01, i, f"{v:.1%}", va="center", fontsize=9)

    # 5. Email Validity Breakdown
    if "email_valid" in df.columns:
        valid_counts = df["email_valid"].value_counts()
        labels = ["Valid", "Invalid"]
        values = [valid_counts.get(True, 0), valid_counts.get(False, 0)]
        wedge_colors = [colors[1], colors[3]]
        axes[1, 1].pie(values, labels=labels, autopct="%1.1f%%", colors=wedge_colors, startangle=90)
        axes[1, 1].set_title("Email Validity")

    # 6. Opt-Out Rate by Region
    if "opt_out" in df.columns:
        opt_out_rate = df.groupby("region")["opt_out"].mean().sort_values()
        axes[1, 2].bar(
            opt_out_rate.index,
            opt_out_rate.values,
            color=[colors[3] if v > 0.2 else colors[1] for v in opt_out_rate.values],
        )
        axes[1, 2].set_title("Opt-Out Rate by Region")
        axes[1, 2].set_ylabel("Opt-Out Rate")
        axes[1, 2].axhline(y=0.2, color="red", linestyle="--", label="20% threshold")
        for i, (region, rate) in enumerate(opt_out_rate.items()):
            axes[1, 2].text(i, rate + 0.005, f"{rate:.1%}", ha="center", fontsize=9)

    plt.tight_layout()
    output_path = output_dir / "customer_quality_report.png"
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    logger.info(f"  EDA report saved: {output_path}")


def export_results(df: pd.DataFrame, quality_report: pd.DataFrame, output_dir: Path = None):
    """Write golden customer files, quality report CSV, and EDA PNG."""
    output_dir = output_dir or CONFIG["output_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)

    generate_eda_report(df, output_dir)

    logger.info("STEP 6: Exporting Results")

    parquet_path = output_dir / "golden_customers.parquet"
    df.to_parquet(parquet_path, index=False, engine="pyarrow", compression="gzip")
    logger.info(f"  Parquet export: {parquet_path} ({parquet_path.stat().st_size / 1024:.1f} KB)")

    csv_path = output_dir / "golden_customers.csv"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    logger.info(f"  CSV export: {csv_path}")

    report_path = output_dir / "quality_report.csv"
    quality_report.to_csv(report_path, index=False)
    logger.info(f"  Quality report: {report_path}")

    return {
        "parquet": parquet_path,
        "csv": csv_path,
        "quality_report": report_path,
        "eda": output_dir / "customer_quality_report.png",
    }
