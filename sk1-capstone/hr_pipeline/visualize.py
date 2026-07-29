"""EDA visualization report for the GlobalTech HR pipeline."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

from config import CONFIG, logger

# Okabe–Ito colorblind-safe palette
PALETTE = {
    "blue": "#0072B2",
    "orange": "#E69F00",
    "green": "#009E73",
    "sky": "#56B4E9",
    "vermillion": "#D55E00",
    "purple": "#CC79A7",
    "yellow": "#F0E442",
    "gray": "#666666",
}

SOURCE_NOTE = "Source: GlobalTech + AcquiredCo HRIS / Payroll / Benefits (post-dedup)"
QUALITY_SOURCE_NOTE = "Source: pipeline quality_report.csv"


def _set_chart_title(
    ax: plt.Axes,
    title: str,
    source: str = SOURCE_NOTE,
) -> None:
    """Set the chart title with the data-source note directly underneath."""
    ax.set_title(title, fontsize=11, pad=16)
    ax.text(
        0.5,
        1.01,
        source,
        transform=ax.transAxes,
        fontsize=7,
        color=PALETTE["gray"],
        ha="center",
        va="bottom",
        clip_on=False,
    )


def _short_check_label(check: str, max_len: int = 28) -> str:
    """Shorten quality-check names for the dashboard axis."""
    label = str(check).replace("REFERENTIAL INTEGRITY: ", "REF: ")
    label = label.replace("NUMERIC RANGE: ", "RANGE: ")
    label = label.replace("VALUES IN SET: ", "SET: ")
    label = label.replace("NOT NULL: ", "NULL: ")
    label = label.replace("UNIQUE: ", "UNIQ: ")
    label = label.replace("DATE RANGE: ", "DATE: ")
    label = label.replace("REGEX: ", "REGEX: ")
    if len(label) > max_len:
        return label[: max_len - 1] + "…"
    return label


def _plot_headcount_by_department(ax: plt.Axes, employees: pd.DataFrame) -> None:
    counts = (
        employees["department"]
        .fillna("(Unknown)")
        .astype("string")
        .value_counts()
        .sort_values(ascending=True)
    )
    ax.barh(counts.index, counts.values, color=PALETTE["blue"])
    _set_chart_title(ax, "1. Headcount by Department")
    ax.set_xlabel("Employees")
    ax.set_ylabel("Department")
    ax.tick_params(axis="y", labelsize=7)


def _plot_headcount_by_country(ax: plt.Axes, employees: pd.DataFrame) -> None:
    counts = (
        employees["country"]
        .fillna("(Unknown)")
        .astype("string")
        .value_counts()
        .sort_values(ascending=False)
        .head(15)
    )
    ax.bar(range(len(counts)), counts.values, color=PALETTE["sky"])
    ax.set_xticks(range(len(counts)))
    ax.set_xticklabels(counts.index, rotation=45, ha="right", fontsize=7)
    _set_chart_title(ax, "2. Headcount by Country (Top 15)")
    ax.set_xlabel("Country")
    ax.set_ylabel("Employees")


def _plot_salary_by_employment_type(ax: plt.Axes, employees: pd.DataFrame) -> None:
    salary = employees.loc[
        employees["salary_usd_annual"].notna(),
        ["employment_type", "salary_usd_annual"],
    ].copy()
    salary["employment_type"] = salary["employment_type"].fillna("(Unknown)")
    order = [
        value
        for value in CONFIG["valid_employment_types"]
        if value in set(salary["employment_type"])
    ]
    extras = sorted(set(salary["employment_type"]) - set(order))
    order = order + extras

    if salary.empty:
        ax.text(0.5, 0.5, "No salary data", ha="center", va="center")
        ax.set_axis_off()
        return

    # Cap extreme annualized outliers for readable compensation comparison.
    plot_frame = salary.copy()
    plot_frame["salary_plot"] = plot_frame["salary_usd_annual"].clip(
        upper=CONFIG["maximum_annual_salary_usd"]
    )

    sns.boxplot(
        data=plot_frame,
        x="employment_type",
        y="salary_plot",
        order=order,
        ax=ax,
        color=PALETTE["green"],
        showfliers=False,
    )
    _set_chart_title(ax, "3. Salary Distribution by Employment Type")
    ax.set_xlabel("Employment Type")
    ax.set_ylabel("Annual Salary (USD, clipped at $2M)")
    ax.tick_params(axis="x", labelsize=8)
    ax.yaxis.set_major_formatter(lambda value, _: f"${value/1000:,.0f}k")


def _plot_tenure_distribution(ax: plt.Axes, employees: pd.DataFrame) -> None:
    hire_dates = pd.to_datetime(employees["hire_date"], errors="coerce").dropna()
    today = pd.Timestamp(datetime.now().date())
    tenure_years = ((today - hire_dates).dt.days / 365.25).clip(lower=0)

    ax.hist(
        tenure_years,
        bins=20,
        color=PALETTE["orange"],
        edgecolor="white",
        linewidth=0.5,
    )
    _set_chart_title(ax, "4. Tenure Distribution")
    ax.set_xlabel("Years of Tenure")
    ax.set_ylabel("Employees")
    median = float(tenure_years.median()) if not tenure_years.empty else 0.0
    ax.axvline(median, color=PALETTE["vermillion"], linestyle="--", linewidth=1.5)
    ax.text(
        0.98,
        0.95,
        f"Median: {median:.1f} yrs",
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=8,
        color=PALETTE["vermillion"],
    )


def _plot_benefits_enrollment_by_department(
    ax: plt.Axes,
    employees: pd.DataFrame,
) -> None:
    frame = employees.copy()
    frame["department"] = frame["department"].fillna("(Unknown)").astype("string")
    enrolled = frame["benefits_enrolled"].fillna(False).astype(bool)
    rates = (
        frame.assign(benefits_enrolled=enrolled)
        .groupby("department", dropna=False)["benefits_enrolled"]
        .mean()
        .mul(100)
        .sort_values(ascending=False)
    )

    ax.bar(range(len(rates)), rates.values, color=PALETTE["purple"])
    ax.set_xticks(range(len(rates)))
    ax.set_xticklabels(rates.index, rotation=45, ha="right", fontsize=7)
    _set_chart_title(ax, "5. Benefits Enrollment Rate by Department")
    ax.set_xlabel("Department")
    ax.set_ylabel("Enrollment Rate (%)")
    ax.set_ylim(0, 100)


def _plot_quality_summary(ax: plt.Axes, quality_report: pd.DataFrame) -> None:
    if quality_report is None or quality_report.empty:
        ax.text(0.5, 0.5, "No quality report", ha="center", va="center")
        ax.set_axis_off()
        return

    report = quality_report.copy()
    labels = [_short_check_label(check) for check in report["check"]]
    x = np.arange(len(report))
    width = 0.38

    ax.bar(
        x - width / 2,
        report["passed"],
        width=width,
        label="Passed",
        color=PALETTE["green"],
    )
    ax.bar(
        x + width / 2,
        report["failed"],
        width=width,
        label="Failed",
        color=PALETTE["vermillion"],
    )
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=55, ha="right", fontsize=6)
    _set_chart_title(ax, "6. Data Quality Summary", source=QUALITY_SOURCE_NOTE)
    ax.set_xlabel("Check")
    ax.set_ylabel("Records")
    ax.legend(fontsize=8, loc="upper right")


def generate_eda_report(
    employees: pd.DataFrame,
    quality_report: pd.DataFrame,
    output_path: Path | None = None,
) -> Path:
    """Build the six-chart EDA PNG and write it at the configured DPI.

    Args:
        employees: Deduplicated employee DataFrame.
        quality_report: Validation report from ``run_quality_checks``.
        output_path: Optional override for the PNG path.

    Returns:
        Path to the written PNG file.
    """
    logger.info("=" * 60)
    logger.info("STEP 5: EDA & visualization report")

    output_path = Path(output_path or CONFIG["output_files"]["eda_report"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    dpi = int(CONFIG["eda_dpi"])
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    sns.set_theme(style="whitegrid", context="notebook")
    fig, axes = plt.subplots(2, 3, figsize=(20, 11))
    fig.suptitle(
        "GlobalTech HR Data Integration — EDA Report",
        fontsize=16,
        fontweight="bold",
        y=0.98,
    )
    fig.text(
        0.5,
        0.955,
        f"Generated: {generated_at}  |  Employees: {len(employees):,}",
        ha="center",
        va="top",
        fontsize=10,
        color=PALETTE["gray"],
    )

    _plot_headcount_by_department(axes[0, 0], employees)
    _plot_headcount_by_country(axes[0, 1], employees)
    _plot_salary_by_employment_type(axes[0, 2], employees)
    _plot_tenure_distribution(axes[1, 0], employees)
    _plot_benefits_enrollment_by_department(axes[1, 1], employees)
    _plot_quality_summary(axes[1, 2], quality_report)

    fig.tight_layout(rect=(0, 0.02, 1, 0.93), h_pad=2.5)
    fig.savefig(output_path, dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    logger.info("Wrote EDA report: %s (%s DPI)", output_path, dpi)
    return output_path
