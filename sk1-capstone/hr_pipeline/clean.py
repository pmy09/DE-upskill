"""Clean and standardize ingested GlobalTech employee data."""

from __future__ import annotations

import re
import unicodedata

import pandas as pd

from config import CONFIG, logger
from export import export_unmapped_departments


SUPPORTED_DATE_FORMATS = (
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%d-%b-%Y",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%d %H:%M:%S",
)

DATE_COLUMNS = (
    "hire_date",
    "payroll_effective_date",
    "benefit_enrollment_date",
)


def _normalize_text(value: object) -> object:
    """Normalize Unicode and whitespace while preserving missing values."""
    if pd.isna(value):
        return pd.NA

    normalized = unicodedata.normalize("NFKC", str(value))
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized if normalized else pd.NA


def standardize_name_series(series: pd.Series) -> pd.Series:
    """Normalize and title-case personal names.

    Unicode NFKC normalization keeps accented characters in a consistent
    representation. Python's Unicode-aware ``str.title`` also title-cases each
    component separated by spaces, hyphens, or apostrophes:
    ``van der berg`` -> ``Van Der Berg`` and ``o'brien`` -> ``O'Brien``.

    Args:
        series: A Series containing first names or last names.

    Returns:
        A nullable string Series containing standardized names.
    """
    return series.map(_normalize_text).astype("string").str.title()


def standardize_names(df: pd.DataFrame) -> pd.DataFrame:
    """Standardize the ``first_name`` and ``last_name`` columns."""
    cleaned = df.copy()
    for column in ("first_name", "last_name"):
        if column in cleaned.columns:
            cleaned[column] = standardize_name_series(cleaned[column])
    return cleaned


def _format_namespaced_ids(
    identifiers: pd.Series,
    company_origins: pd.Series,
) -> tuple[pd.Series, pd.Series]:
    """Return namespaced IDs and a mask identifying unformattable values."""
    raw_ids = identifiers.astype("string").str.strip()
    origins = company_origins.astype("string").str.strip().str.casefold()
    prefixes = origins.map({"globaltech": "GT", "acquiredco": "AC"})

    numeric_parts = raw_ids.str.extract(r"(\d+)", expand=False)
    numeric_ids = pd.to_numeric(numeric_parts, errors="coerce").astype("Int64")
    valid_number = numeric_ids.between(0, 999_999).fillna(False)
    valid = raw_ids.notna() & prefixes.notna() & valid_number

    formatted = pd.Series(pd.NA, index=identifiers.index, dtype="string")
    formatted.loc[valid] = (
        prefixes.loc[valid]
        + "-"
        + numeric_ids.loc[valid].astype("string").str.zfill(6)
    )
    invalid = raw_ids.notna() & ~valid
    return formatted, invalid


def standardize_employee_ids(df: pd.DataFrame) -> pd.DataFrame:
    """Apply company namespaces to employee and manager IDs.

    GlobalTech identifiers become ``GT-######`` and AcquiredCo identifiers
    become ``AC-######``. The original values are retained in
    ``employee_id_raw`` and ``manager_id_raw`` for traceability.

    Args:
        df: An ingested DataFrame containing ``employee_id`` and
            ``company_origin``.

    Returns:
        A copy with namespaced employee and manager identifiers.
    """
    cleaned = df.copy()
    if "employee_id" not in cleaned or "company_origin" not in cleaned:
        logger.warning("Skipping ID standardization: required columns are absent")
        return cleaned

    if "employee_id_raw" not in cleaned:
        cleaned["employee_id_raw"] = cleaned["employee_id"]

    cleaned["employee_id"], invalid_employee_ids = _format_namespaced_ids(
        cleaned["employee_id"],
        cleaned["company_origin"],
    )

    if "manager_id" in cleaned:
        if "manager_id_raw" not in cleaned:
            cleaned["manager_id_raw"] = cleaned["manager_id"]
        cleaned["manager_id"], invalid_manager_ids = _format_namespaced_ids(
            cleaned["manager_id"],
            cleaned["company_origin"],
        )
    else:
        invalid_manager_ids = pd.Series(False, index=cleaned.index)

    if invalid_employee_ids.any():
        logger.warning(
            "Could not namespace %s employee ID(s)",
            f"{int(invalid_employee_ids.sum()):,}",
        )
    if invalid_manager_ids.any():
        logger.warning(
            "Could not namespace %s manager ID(s)",
            f"{int(invalid_manager_ids.sum()):,}",
        )

    return cleaned


def standardize_employment_types(df: pd.DataFrame) -> pd.DataFrame:
    """Map source employment codes to the standard three-value taxonomy."""
    cleaned = df.copy()
    if "employment_type" not in cleaned:
        return cleaned

    original = cleaned["employment_type"]
    normalized = (
        original.map(_normalize_text)
        .astype("string")
        .str.upper()
    )
    mapped = normalized.map(CONFIG["employment_type_map"]).astype("string")
    unknown = original.notna() & mapped.isna()

    cleaned["employment_type"] = mapped
    if unknown.any():
        logger.warning(
            "Unmapped employment types (%s record(s)): %s",
            f"{int(unknown.sum()):,}",
            sorted(original.loc[unknown].astype(str).unique().tolist()),
        )
    return cleaned


def _parse_salary_values(series: pd.Series) -> pd.Series:
    """Parse numeric salary values while ignoring currency symbols/commas."""
    values = series.astype("string").str.strip()
    negative_parentheses = values.str.match(r"^\(.*\)$", na=False)
    numeric_text = values.str.replace(r"[^\d.\-]", "", regex=True)
    numeric = pd.to_numeric(numeric_text, errors="coerce")
    numeric.loc[negative_parentheses & numeric.notna()] *= -1
    return numeric


def normalize_currency_and_salary(df: pd.DataFrame) -> pd.DataFrame:
    """Convert source salaries to annual USD while retaining original fields.

    The configured rates express one unit of each source currency in USD.
    Salary strings such as ``$85,000`` are parsed to ``85000.0`` before the
    pay-frequency and exchange-rate multipliers are applied.

    Args:
        df: A standardized source DataFrame.

    Returns:
        A copy with ``salary_usd_annual`` populated where salary, currency, and
        pay frequency are all valid. ``base_salary``, ``currency``, and
        ``pay_frequency`` remain present.
    """
    cleaned = df.copy()
    required = {"base_salary", "currency", "pay_frequency"}
    if not required.issubset(cleaned.columns):
        logger.warning("Skipping salary normalization: required columns are absent")
        return cleaned

    salary_values = _parse_salary_values(cleaned["base_salary"])
    currencies = cleaned["currency"].astype("string").str.strip().str.upper()

    frequency_lookup = {
        frequency.casefold(): frequency
        for frequency in CONFIG["pay_frequency_multipliers"]
    }
    frequencies = (
        cleaned["pay_frequency"]
        .map(_normalize_text)
        .astype("string")
        .str.casefold()
        .map(frequency_lookup)
        .astype("string")
    )

    exchange_rates = currencies.map(CONFIG["exchange_rates_to_usd"])
    frequency_multipliers = frequencies.map(CONFIG["pay_frequency_multipliers"])
    cleaned["salary_usd_annual"] = (
        salary_values * exchange_rates * frequency_multipliers
    ).round(2)

    # Currency and frequency are taxonomy fields, so normalize their casing
    # while retaining all three original source columns.
    cleaned["currency"] = currencies
    cleaned["pay_frequency"] = frequencies

    has_salary = cleaned["base_salary"].notna()
    invalid_salary = has_salary & salary_values.isna()
    unknown_currency = has_salary & exchange_rates.isna()
    unknown_frequency = has_salary & frequency_multipliers.isna()

    if invalid_salary.any():
        logger.warning("Could not parse %s salary value(s)", int(invalid_salary.sum()))
    if unknown_currency.any():
        logger.warning(
            "Unknown currencies (%s record(s)): %s",
            int(unknown_currency.sum()),
            sorted(currencies.loc[unknown_currency].dropna().unique().tolist()),
        )
    if unknown_frequency.any():
        logger.warning(
            "Unknown pay frequencies (%s record(s)): %s",
            int(unknown_frequency.sum()),
            sorted(
                cleaned.loc[unknown_frequency, "pay_frequency"]
                .dropna()
                .unique()
                .tolist()
            ),
        )

    return cleaned


def standardize_departments(df: pd.DataFrame) -> pd.DataFrame:
    """Map department names/codes and flag values requiring manual review.

    The source value is retained in ``department_original``. Unknown non-null
    values become null in the standard ``department`` column and are marked by
    ``department_unmapped``.
    """
    cleaned = df.copy()
    if "department" not in cleaned:
        return cleaned

    if "department_original" not in cleaned:
        cleaned["department_original"] = cleaned["department"]

    normalized = (
        cleaned["department_original"]
        .map(_normalize_text)
        .astype("string")
        .str.upper()
    )
    mapped = normalized.map(CONFIG["department_map"]).astype("string")
    cleaned["department_unmapped"] = (
        cleaned["department_original"].notna() & mapped.isna()
    )
    cleaned["department"] = mapped

    unmapped_count = int(cleaned["department_unmapped"].sum())
    if unmapped_count:
        logger.warning(
            "Found %s record(s) with unmapped departments",
            f"{unmapped_count:,}",
        )
    return cleaned


def _parse_mixed_dates(series: pd.Series) -> pd.Series:
    """Parse all project date formats into timezone-naive timestamps."""
    values = series.map(_normalize_text).astype("string")
    result = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns, UTC]")

    for date_format in SUPPORTED_DATE_FORMATS:
        remaining = result.isna() & values.notna()
        if not remaining.any():
            break
        parsed = pd.to_datetime(
            values.where(remaining),
            format=date_format,
            errors="coerce",
            utc=True,
        )
        result = result.fillna(parsed)

    # The fallback handles valid ISO-8601 variants not explicitly listed.
    remaining = result.isna() & values.notna()
    if remaining.any():
        fallback = pd.to_datetime(
            values.where(remaining),
            errors="coerce",
            utc=True,
        )
        result = result.fillna(fallback)

    return result.dt.tz_convert(None)


def standardize_dates(
    df: pd.DataFrame,
    date_columns: tuple[str, ...] = DATE_COLUMNS,
) -> pd.DataFrame:
    """Parse project date fields and flag malformed/out-of-range values.

    A date is invalid when a non-null source value cannot be parsed or when the
    parsed date is before the configured minimum (1970-01-01) or after today.
    Parsed values are retained even when outside the plausible range so that
    reviewers can inspect the original issue.

    Args:
        df: A standardized source DataFrame.
        date_columns: Date columns to parse when present.

    Returns:
        A copy whose date fields use ``datetime64[ns]`` and which contains an
        accompanying ``<column>_invalid`` boolean flag for every parsed field.
    """
    cleaned = df.copy()
    minimum = pd.Timestamp(CONFIG["minimum_hire_date"])
    maximum = pd.Timestamp.today().normalize()

    for column in date_columns:
        if column not in cleaned:
            continue

        original = cleaned[column].copy()
        parsed = _parse_mixed_dates(original)
        unparseable = original.notna() & parsed.isna()
        outside_range = parsed.notna() & (
            (parsed < minimum) | (parsed > maximum)
        )

        cleaned[column] = parsed
        cleaned[f"{column}_invalid"] = unparseable | outside_range

        invalid_count = int(cleaned[f"{column}_invalid"].sum())
        if invalid_count:
            logger.warning(
                "%s contains %s malformed/out-of-range date(s)",
                column,
                f"{invalid_count:,}",
            )

    return cleaned


def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Apply every Deliverable 2 transformation to one source DataFrame."""
    cleaned = standardize_names(df)
    cleaned = standardize_employee_ids(cleaned)
    cleaned = standardize_employment_types(cleaned)
    cleaned = normalize_currency_and_salary(cleaned)
    cleaned = standardize_departments(cleaned)
    cleaned = standardize_dates(cleaned)
    return cleaned


def clean_all_sources(
    frames: dict[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    """Clean every ingested source and export department mapping exceptions.

    Args:
        frames: Standardized source DataFrames returned by
            ``ingest.ingest_all_sources``.

    Returns:
        A new dictionary with the same source keys and cleaned DataFrames.
    """
    logger.info("=" * 60)
    logger.info("STEP 2: Data cleaning and transformation")

    cleaned_frames: dict[str, pd.DataFrame] = {}
    for source_name, frame in frames.items():
        cleaned = clean_dataframe(frame)
        cleaned_frames[source_name] = cleaned
        logger.info("Cleaned %s %s record(s)", source_name, f"{len(cleaned):,}")

    export_unmapped_departments(cleaned_frames)

    payroll = cleaned_frames.get("payroll")
    if payroll is not None:
        converted = int(payroll["salary_usd_annual"].notna().sum())
        logger.info("Annualized %s payroll salary record(s)", f"{converted:,}")

    return cleaned_frames
