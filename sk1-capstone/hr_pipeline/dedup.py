"""Multi-pass employee deduplication, ghost detection, and provenance."""

from __future__ import annotations

import pandas as pd
from rapidfuzz import fuzz

from config import CONFIG, logger
from export import export_ghost_employees, export_probable_matches

HRIS_SOURCES = ("globaltech_hris", "acquiredco_hris")
PERSON_FIELDS = [
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
]
PAYROLL_FIELDS = [
    "base_salary",
    "currency",
    "pay_frequency",
    "bonus_target_pct",
    "payroll_effective_date",
    "salary_usd_annual",
]
BENEFIT_FIELDS = [
    "benefits_enrolled",
    "benefit_plans",
    "benefit_plan_count",
    "benefit_coverage_level",
    "benefit_enrollment_date",
    "premium_employee",
    "premium_employer",
]


def _source_priority(source_system: object) -> int:
    """Return configured source priority; unknown sources sort last."""
    if pd.isna(source_system):
        return 99
    return int(CONFIG["source_priority"].get(str(source_system), 99))


def _prefer_non_dup_raw_id(series: pd.Series) -> pd.Series:
    """Rank canonical HRIS IDs ahead of synthetic ``ACQ_DUP_*`` collisions."""
    raw = series.astype("string")
    return raw.str.contains("DUP", case=False, na=False).astype(int)


def _first_non_null(series: pd.Series):
    """Return the first non-null value in a Series."""
    non_null = series.dropna()
    return non_null.iloc[0] if not non_null.empty else pd.NA


def _join_strings_by_date(values: pd.Series, dates: pd.Series) -> str:
    """Join values in enrollment-date order, replacing blanks/NA with ``N/A``."""
    if values.empty:
        return "N/A"

    ordered_index = dates.sort_values(ascending=True, na_position="last").index
    parts: list[str] = []
    for value in values.loc[ordered_index]:
        text = "" if pd.isna(value) else str(value).strip()
        parts.append(text if text else "N/A")
    return ",".join(parts)


def _full_name(frame: pd.DataFrame) -> pd.Series:
    """Build a comparable first+last name string."""
    first = frame["first_name"].astype("string").fillna("").str.strip()
    last = frame["last_name"].astype("string").fillna("").str.strip()
    return (first + " " + last).str.replace(r"\s+", " ", regex=True).str.strip()


def aggregate_benefits(benefits: pd.DataFrame) -> pd.DataFrame:
    """Collapse enrollment rows to one employee-level benefits profile.

    Plan names and coverage levels are joined in enrollment-date order.
    Blank or missing values become ``N/A``.

    Args:
        benefits: Cleaned benefits enrollments (plan grain).

    Returns:
        One row per ``employee_id`` with enrolled flag, plan list, and counts.
    """
    if benefits.empty:
        return pd.DataFrame(
            columns=["employee_id", "company_origin", "source_system", *BENEFIT_FIELDS]
        )

    frame = benefits.copy()
    frame["benefit_plans"] = frame["benefit_plans"].astype("string")

    def join_by_enrollment_date(values: pd.Series) -> str:
        return _join_strings_by_date(
            values,
            frame.loc[values.index, "benefit_enrollment_date"],
        )

    aggregated = (
        frame.groupby("employee_id", as_index=False)
        .agg(
            company_origin=("company_origin", _first_non_null),
            source_system=("source_system", _first_non_null),
            benefits_enrolled=("benefits_enrolled", "max"),
            benefit_plans=("benefit_plans", join_by_enrollment_date),
            benefit_plan_count=("benefit_plans", "count"),
            benefit_coverage_level=("benefit_coverage_level", join_by_enrollment_date),
            benefit_enrollment_date=("benefit_enrollment_date", "min"),
            premium_employee=("premium_employee", "sum"),
            premium_employer=("premium_employer", "sum"),
        )
    )
    aggregated["benefits_enrolled"] = aggregated["benefits_enrolled"].fillna(False).astype(bool)
    aggregated["source_system"] = "benefits"
    return aggregated


def aggregate_payroll(payroll: pd.DataFrame) -> pd.DataFrame:
    """Collapse duplicated payroll rows to one record per employee ID.

    When multiple payroll rows share an ID, the latest
    ``payroll_effective_date`` is preferred.

    Args:
        payroll: Cleaned payroll DataFrame.

    Returns:
        One payroll profile per ``employee_id``.
    """
    if payroll.empty:
        return pd.DataFrame(
            columns=["employee_id", "company_origin", "source_system", *PAYROLL_FIELDS]
        )

    frame = payroll.copy()
    # at this point, source_system should be "payroll" for all rows. This is just a backup.
    frame["_source_priority"] = frame["source_system"].map(_source_priority)
    frame = frame.sort_values(
        by=["employee_id", "payroll_effective_date", "_source_priority"],
        ascending=[True, False, True],
        na_position="last",
    )

    keep_columns = ["employee_id", "company_origin", "source_system", *PAYROLL_FIELDS]
    available = [column for column in keep_columns if column in frame.columns]
    aggregated = frame.groupby("employee_id", as_index=False).first()[available]
    aggregated["source_system"] = "payroll"
    return aggregated


def detect_ghost_employees(
    payroll: pd.DataFrame,
    hris_employee_ids: set[str],
) -> pd.DataFrame:
    """Identify payroll records with no matching HRIS employee ID.

    Args:
        payroll: Cleaned payroll DataFrame (pre-aggregation).
        hris_employee_ids: Canonical HRIS employee IDs after Pass 1 collapse.

    Returns:
        Ghost report with the Deliverable 6 required columns.
    """
    if payroll.empty:
        return pd.DataFrame(
            columns=[
                "payroll_employee_id",
                "name",
                "salary_usd_annual",
                "ghost_flag_reason",
                "ghost_employee",
                "company_origin",
                "source_system",
            ]
        )

    ghosts = payroll.loc[~payroll["employee_id"].isin(hris_employee_ids)].copy()
    if ghosts.empty:
        return pd.DataFrame(
            columns=[
                "payroll_employee_id",
                "name",
                "salary_usd_annual",
                "ghost_flag_reason",
                "ghost_employee",
                "company_origin",
                "source_system",
            ]
        )

    # One ghost row per payroll employee ID (latest effective date wins).
    ghosts = ghosts.sort_values(
        by=["employee_id", "payroll_effective_date"],
        ascending=[True, False],
        na_position="last",
    )
    ghosts = ghosts.groupby("employee_id", as_index=False).first()

    first = ghosts.get("first_name", pd.Series(pd.NA, index=ghosts.index)).astype("string")
    last = ghosts.get("last_name", pd.Series(pd.NA, index=ghosts.index)).astype("string")
    name = (first.fillna("").str.strip() + " " + last.fillna("").str.strip()).str.strip()
    name = name.replace("", pd.NA)

    return pd.DataFrame(
        {
            "payroll_employee_id": ghosts["employee_id"],
            "name": name,
            "salary_usd_annual": ghosts["salary_usd_annual"],
            "ghost_flag_reason": "Payroll employee_id has no matching HRIS record",
            "ghost_employee": True,
            "company_origin": ghosts["company_origin"],
            "source_system": "payroll",
        }
    )


def collapse_hris_by_employee_id(hris: pd.DataFrame) -> pd.DataFrame:
    """Collapse HRIS rows that share a namespaced employee ID.

    Synthetic ``ACQ_DUP_*`` collisions lose to the canonical AcquiredCo row.
    """
    if hris.empty:
        return hris.copy()

    frame = hris.copy()
    frame["_source_priority"] = frame["source_system"].map(_source_priority)
    frame["_dup_rank"] = (
        _prefer_non_dup_raw_id(frame["employee_id_raw"])
        if "employee_id_raw" in frame.columns
        else 0
    )
    frame["_row_count"] = frame.groupby("employee_id")["employee_id"].transform("size")
    frame = frame.sort_values(
        by=["employee_id", "_source_priority", "_dup_rank"],
        ascending=[True, True, True],
    )

    collapsed = frame.groupby("employee_id", as_index=False, sort=False).first()
    collapsed["source_systems"] = collapsed["source_system"].astype("string")
    collapsed["dedup_method"] = collapsed["_row_count"].gt(1).map(
        {True: "exact_id", False: "single_source"}
    )
    collapsed = collapsed.drop(
        columns=[column for column in collapsed.columns if column.startswith("_")],
        errors="ignore",
    )

    logger.info(
        "Collapsed HRIS %s rows -> %s unique employee IDs",
        f"{len(hris):,}",
        f"{len(collapsed):,}",
    )
    return collapsed


def _assign_enrichment_columns(
    base: pd.DataFrame,
    enrichment: pd.DataFrame,
    columns: list[str],
) -> pd.DataFrame:
    """Left-join enrichment fields onto the employee spine."""
    if enrichment.empty:
        return base

    keep_columns = ["employee_id", *[column for column in columns if column in enrichment.columns]]
    if len(keep_columns) == 1:
        return base

    # Avoid combine_first warnings by dropping empty placeholder columns first.
    cleaned_base = base.drop(
        columns=[
            column
            for column in columns
            if column in base.columns and base[column].isna().all()
        ],
        errors="ignore",
    )
    return cleaned_base.merge(enrichment[keep_columns], on="employee_id", how="left")


def pass1_exact_id_match(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Merge records that share a namespaced employee ID.

    HRIS rows are the employee spine. Payroll and benefits enrich matching IDs.
    Multiple rows for the same ID are collapsed with source priority
    HRIS > Payroll > Benefits.
    """
    hris = collapse_hris_by_employee_id(
        pd.concat(
            [frames["globaltech_hris"], frames["acquiredco_hris"]],
            ignore_index=True,
        )
    )
    payroll = aggregate_payroll(frames["payroll"])
    benefits = aggregate_benefits(frames["benefits"])

    merged = hris.copy()
    if "source_systems" not in merged.columns:
        merged["source_systems"] = merged["source_system"].astype("string")
    if "dedup_method" not in merged.columns:
        merged["dedup_method"] = "single_source"

    matched_payroll = set(payroll["employee_id"]) if not payroll.empty else set()
    matched_benefits = set(benefits["employee_id"]) if not benefits.empty else set()

    merged = _assign_enrichment_columns(merged, payroll, PAYROLL_FIELDS)
    if matched_payroll:
        has_payroll = merged["employee_id"].isin(matched_payroll)
        merged.loc[has_payroll, "source_systems"] = (
            merged.loc[has_payroll, "source_systems"].astype("string") + ",payroll"
        )
        merged.loc[has_payroll, "dedup_method"] = "exact_id"

    merged = _assign_enrichment_columns(merged, benefits, BENEFIT_FIELDS)
    if matched_benefits:
        has_benefits = merged["employee_id"].isin(matched_benefits)
        merged.loc[has_benefits, "source_systems"] = (
            merged.loc[has_benefits, "source_systems"].astype("string") + ",benefits"
        )
        merged.loc[has_benefits, "dedup_method"] = "exact_id"

    if "benefits_enrolled" in merged.columns:
        enrolled = merged["benefits_enrolled"]
        merged["benefits_enrolled"] = enrolled.where(enrolled.notna(), False).astype(bool)
    else:
        merged["benefits_enrolled"] = False

    if "benefit_plan_count" in merged.columns:
        merged["benefit_plan_count"] = (
            pd.to_numeric(merged["benefit_plan_count"], errors="coerce").fillna(0).astype(int)
        )
    else:
        merged["benefit_plan_count"] = 0

    merged["source_systems"] = merged["source_systems"].map(
        lambda value: ",".join(
            sorted(
                {
                    part.strip()
                    for part in str(value).split(",")
                    if part and part.strip() not in {"nan", "<NA>"}
                },
                key=_source_priority,
            )
        )
    )

    logger.info(
        "Pass 1 exact ID match: %s HRIS employees enriched with payroll/benefits",
        f"{len(merged):,}",
    )
    return merged.reset_index(drop=True)


def pass2_email_match(employees: pd.DataFrame) -> pd.DataFrame:
    """Merge cross-company employees that share the same email address.

    Same email across GlobalTech and AcquiredCo is treated as one person
    (for example a contractor present in both HRIS systems).
    """
    frame = employees.copy()
    frame["email_key"] = (
        frame["email"].astype("string").str.strip().str.lower().replace({"": pd.NA})
    )

    email_groups = (
        frame.dropna(subset=["email_key"])
        .groupby("email_key")
        .agg(
            company_count=("company_origin", "nunique"),
            record_count=("employee_id", "count"),
        )
    )
    cross_company_emails = set(
        email_groups.loc[
            (email_groups["company_count"] > 1) & (email_groups["record_count"] > 1)
        ].index
    )

    if not cross_company_emails:
        frame = frame.drop(columns=["email_key"])
        logger.info("Pass 2 email match: 0 cross-company email collisions")
        return frame

    keep_rows = []
    consumed = set()

    for email in cross_company_emails:
        group = frame.loc[frame["email_key"] == email].copy()
        group["_source_priority"] = group["source_system"].map(_source_priority)
        group = group.sort_values(by=["_source_priority", "company_origin"])
        merged = group.iloc[0].copy()
        for column in group.columns:
            if column.startswith("_") or column == "email_key":
                continue
            if pd.isna(merged.get(column)):
                merged[column] = _first_non_null(group[column])

        source_parts = []
        for value in group["source_systems"].fillna(group["source_system"]):
            source_parts.extend(str(value).split(","))
        merged["source_systems"] = ",".join(
            sorted(set(part for part in source_parts if part), key=_source_priority)
        )
        merged["dedup_method"] = "email_match"
        keep_rows.append(merged.drop(labels=["email_key", "_source_priority"], errors="ignore"))
        consumed.update(group.index.tolist())

    remaining = frame.loc[~frame.index.isin(consumed)].drop(columns=["email_key"])
    matched = pd.DataFrame(keep_rows)
    result = pd.concat([remaining, matched], ignore_index=True)

    logger.info(
        "Pass 2 email match: merged %s cross-company email group(s); %s employees remain",
        f"{len(cross_company_emails):,}",
        f"{len(result):,}",
    )
    return result


def pass3_fuzzy_name_match(employees: pd.DataFrame) -> pd.DataFrame:
    """Find probable same-person matches without auto-merging.

    Candidates are blocked by hire-date proximity (± configured days) and then
    scored with ``rapidfuzz`` on the full name. Matches at or above the
    configured threshold are written to the HR review file only.
    """
    frame = employees.copy()
    frame = frame.dropna(subset=["hire_date"]).copy()
    frame["full_name"] = _full_name(frame)
    frame = frame.loc[frame["full_name"].str.len() > 0].copy()
    frame = frame.sort_values("hire_date").reset_index(drop=True)

    threshold = CONFIG["fuzzy_match_threshold"]
    window_days = CONFIG["fuzzy_hire_date_window_days"]
    matches: list[dict] = []

    hire_dates = frame["hire_date"]
    names = frame["full_name"].tolist()
    employee_ids = frame["employee_id"].astype(str).tolist()
    origins = frame["company_origin"].astype("string").tolist()

    right = 0
    n_rows = len(frame)
    for left in range(n_rows):
        left_date = hire_dates.iloc[left]
        while right < n_rows and (hire_dates.iloc[right] - left_date).days <= window_days:
            right += 1

        for candidate in range(left + 1, right):
            # Prefer cross-company comparisons for acquisition reconciliation.
            if origins[left] == origins[candidate] and pd.notna(origins[left]):
                continue
            if employee_ids[left] == employee_ids[candidate]:
                continue

            day_diff = abs((hire_dates.iloc[candidate] - left_date).days)
            if day_diff > window_days:
                continue

            score = fuzz.token_sort_ratio(names[left], names[candidate])
            if score < threshold:
                continue

            matches.append(
                {
                    "record_1_id": employee_ids[left],
                    "record_2_id": employee_ids[candidate],
                    "record_1_name": names[left],
                    "record_2_name": names[candidate],
                    "record_1_company": origins[left],
                    "record_2_company": origins[candidate],
                    "similarity_score": round(float(score), 2),
                    "hire_date_diff_days": int(day_diff),
                    "recommended_action": "review",
                    "dedup_method": "fuzzy_name",
                }
            )

    review = pd.DataFrame(matches)
    if not review.empty:
        review = (
            review.sort_values(
                by=["similarity_score", "hire_date_diff_days"],
                ascending=[False, True],
            )
            .drop_duplicates(subset=["record_1_id", "record_2_id"])
            .reset_index(drop=True)
        )

    logger.info(
        "Pass 3 fuzzy name match: %s probable pair(s) for HR review "
        "(threshold=%s%%, window=%s days)",
        f"{len(review):,}",
        threshold,
        window_days,
    )
    return review


def _ensure_provenance(employees: pd.DataFrame) -> pd.DataFrame:
    """Guarantee ``source_systems`` and ``dedup_method`` on every output row."""
    frame = employees.copy()
    if "source_systems" not in frame.columns:
        frame["source_systems"] = frame.get("source_system", pd.Series(pd.NA, index=frame.index))
    frame["source_systems"] = frame["source_systems"].fillna(frame.get("source_system")).astype("string")

    if "dedup_method" not in frame.columns:
        frame["dedup_method"] = "single_source"
    frame["dedup_method"] = frame["dedup_method"].fillna("single_source").astype("string")

    multi_source = frame["source_systems"].astype("string").str.contains(",", na=False)
    exact_needed = multi_source & frame["dedup_method"].eq("single_source")
    frame.loc[exact_needed, "dedup_method"] = "exact_id"
    return frame


def deduplicate_employees(
    frames: dict[str, pd.DataFrame],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Run the full multi-pass deduplication workflow.

    Args:
        frames: Cleaned source DataFrames from ``clean.clean_all_sources``.

    Returns:
        A tuple of ``(employees, ghost_employees, probable_matches)``.
    """
    logger.info("=" * 60)
    logger.info("STEP 3: Deduplication")

    required = {"globaltech_hris", "acquiredco_hris", "payroll", "benefits"}
    missing = required - set(frames)
    if missing:
        raise KeyError(f"Missing cleaned source frame(s): {sorted(missing)}")

    hris = pd.concat(
        [frames["globaltech_hris"], frames["acquiredco_hris"]],
        ignore_index=True,
    )
    employees = pass1_exact_id_match(frames)
    ghosts = detect_ghost_employees(
        frames["payroll"],
        set(employees["employee_id"].dropna().astype(str)),
    )
    employees = pass2_email_match(employees)
    probable_matches = pass3_fuzzy_name_match(employees)
    employees = _ensure_provenance(employees)

    export_ghost_employees(ghosts)
    export_probable_matches(probable_matches)

    method_counts = employees["dedup_method"].value_counts(dropna=False).to_dict()
    logger.info("Deduplication summary")
    logger.info("  Input HRIS rows:        %s", f"{len(hris):,}")
    logger.info("  Output employees:       %s", f"{len(employees):,}")
    logger.info("  Ghost employees:        %s", f"{len(ghosts):,}")
    logger.info("  Probable match pairs:   %s", f"{len(probable_matches):,}")
    logger.info("  Dedup methods:          %s", method_counts)

    return employees.reset_index(drop=True), ghosts, probable_matches
