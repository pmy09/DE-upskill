"""
Cleaning, standardization, deduplication, and optional AI enrichment.
"""

import json
import re

import numpy as np
import pandas as pd

from config import CONFIG, logger

REGION_MAP = {
    "us": "US", "usa": "US", "united states": "US", "north america": "US",
    "na": "US", "amer": "US", "america": "US",
    "eu": "EU", "europe": "EU", "emea": "EU", "eur": "EU", "european union": "EU",
    "apac": "APAC", "asia": "APAC", "asia pacific": "APAC",
    "ap": "APAC", "asia-pacific": "APAC",
}


def standardize_emails(series: pd.Series) -> pd.Series:
    return (
        series
        .astype(str)
        .str.strip()
        .str.lower()
        .str.replace(r"\s+", "", regex=True)
        .replace({"nan": np.nan, "none": np.nan, "": np.nan})
    )


def validate_emails(series: pd.Series) -> pd.Series:
    """Returns a boolean Series: True = valid email format."""
    return series.str.match(CONFIG["email_regex"], na=False)


def standardize_phone_numbers(series: pd.Series) -> pd.Series:
    """
    Normalize phone numbers: remove formatting, preserve + prefix.

    Examples:
        +1 (555) 123-4567  →  +15551234567
        555.123.4567       →  5551234567
        invalid-phone      →  NaN
    """
    def clean_phone(phone):
        if pd.isna(phone) or str(phone).strip() in ("", "nan", "None"):
            return np.nan
        phone = str(phone).strip()
        has_plus = phone.startswith("+")
        digits = re.sub(r"[^\d]", "", phone)
        if len(digits) < 7:
            return np.nan
        return f"+{digits}" if has_plus else digits

    return series.apply(clean_phone)


def standardize_names(series: pd.Series) -> pd.Series:
    return (
        series
        .astype(str)
        .str.strip()
        .str.replace(r"\s+", " ", regex=True)
        .str.title()
        .replace({"Nan": np.nan, "None": np.nan, "": np.nan})
    )


def standardize_regions(series: pd.Series) -> pd.Series:
    return (
        series
        .astype(str)
        .str.strip()
        .str.lower()
        .map(REGION_MAP)
    )


def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Apply all cleaning transformations to the unified DataFrame."""
    logger.info("STEP 2: Cleaning & Standardization")
    df = df.copy()

    df["email_raw"] = df["email"].copy()
    df["email"] = standardize_emails(df["email"])
    df["email_valid"] = validate_emails(df["email"])

    df["first_name"] = standardize_names(df["first_name"])
    df["last_name"] = standardize_names(df["last_name"])
    df["phone"] = standardize_phone_numbers(df["phone"])
    df["region"] = standardize_regions(df["region"])
    df["registration_date"] = pd.to_datetime(df["registration_date"], errors="coerce")

    invalid_emails = (~df["email_valid"]).sum()
    null_regions = df["region"].isna().sum()
    logger.info(f"  Invalid emails: {invalid_emails}")
    logger.info(f"  Null regions after standardization: {null_regions}")
    logger.info(f"  Records after cleaning: {len(df)}")
    return df


def deduplicate_customers(df: pd.DataFrame) -> pd.DataFrame:
    """
    Deduplicate customer records across sources.

    Strategy:
        1. Sort by source priority (CRM is most trusted)
        2. Group by standardized email (primary key)
        3. Merge fields: first non-null from highest-priority source
        4. GDPR: if ANY source has opt_out=True, mark as opted out
    """
    logger.info("STEP 3: Deduplication")
    initial_count = len(df)

    df = df.copy()
    df["source_priority"] = df["source"].map(CONFIG["source_priority"]).fillna(99)
    df = df.sort_values("source_priority")

    def merge_group(group: pd.DataFrame) -> pd.Series:
        best = group.iloc[0].copy()

        if "email" not in best.index or pd.isna(best.get("email")):
            best["email"] = group.name

        for col in ["phone", "region", "first_name", "last_name", "registration_date"]:
            if col in group.columns and pd.isna(best.get(col)):
                non_null = group[col].dropna()
                if len(non_null) > 0:
                    best[col] = non_null.iloc[0]

        if "opt_out" in group.columns:
            best["opt_out"] = bool(
                pd.to_numeric(group["opt_out"], errors="coerce").fillna(0).astype(bool).any()
            )

        best["sources"] = ",".join(group["source"].unique())
        best["source_count"] = len(group["source"].unique())
        return best

    valid_mask = df["email_valid"] == True  # noqa: E712
    valid_df = df[valid_mask]
    invalid_df = df[~valid_mask].copy()

    try:
        deduped = (
            valid_df
            .groupby("email", sort=False)
            .apply(merge_group, include_groups=False)
            .reset_index(drop=True)
        )
    except TypeError:
        deduped = (
            valid_df
            .groupby("email", sort=False, group_keys=False)
            .apply(merge_group)
            .reset_index(drop=True)
        )

    result = pd.concat([deduped, invalid_df], ignore_index=True)

    if "opt_out" in result.columns:
        result["opt_out"] = (
            pd.to_numeric(result["opt_out"], errors="coerce").fillna(0).astype(bool)
        )

    removed = initial_count - len(result)
    logger.info(f"  Records before deduplication: {initial_count}")
    logger.info(f"  Duplicate records removed: {removed}")
    logger.info(f"  Records after deduplication: {len(result)}")
    return result


def infer_region_with_llm(df: pd.DataFrame) -> pd.DataFrame:
    """
    Use Claude to infer missing region values from available context.
    Only processes records with null region — never overwrites existing values.
    """
    try:
        import anthropic
    except ImportError:
        logger.warning("anthropic package not installed; skipping LLM region inference.")
        df = df.copy()
        df["region_inferred"] = False
        return df

    client = anthropic.Anthropic()
    null_region_mask = df["region"].isna()
    null_count = null_region_mask.sum()

    if null_count == 0:
        logger.info("No null regions to infer.")
        df = df.copy()
        df["region_inferred"] = False
        return df

    logger.info(f"Inferring region for {null_count} records using LLM...")
    df = df.copy()
    df["region_inferred"] = False

    null_records = df[null_region_mask].copy()
    batch_size = 10
    inferred_regions = {}

    for i in range(0, len(null_records), batch_size):
        batch = null_records.iloc[i:i + batch_size]
        records_text = "\n".join([
            f"  - Index {idx}: email={row.get('email', 'unknown')}, "
            f"name={row.get('first_name', '')} {row.get('last_name', '')}"
            for idx, row in batch.iterrows()
        ])

        prompt = f"""You are a data engineer. Based on the following customer records, 
infer the most likely geographic region for each. The only valid regions are:
- US (United States and Canada)
- EU (Europe, Middle East, Africa)  
- APAC (Asia Pacific, Australia, New Zealand)

Use email domains, name patterns, and any other available signals.
If you truly cannot infer, respond with UNKNOWN.

Records:
{records_text}

Respond ONLY in JSON format like:
{{"results": [{{"index": <index>, "region": "<US|EU|APAC|UNKNOWN>", "confidence": "<high|medium|low>", "reason": "<brief reason>"}}]}}"""

        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}],
            )
            result = json.loads(response.content[0].text)
            for item in result["results"]:
                idx = item["index"]
                region = item["region"]
                if region in CONFIG["valid_regions"]:
                    inferred_regions[idx] = region
                    logger.info(
                        f"  Inferred region for index {idx}: {region} "
                        f"(confidence: {item['confidence']}, reason: {item['reason']})"
                    )
        except Exception as e:
            logger.warning(f"  LLM inference failed for batch {i}-{i + batch_size}: {e}")

    for idx, region in inferred_regions.items():
        df.at[idx, "region"] = region
        df.at[idx, "region_inferred"] = True

    inferred_count = df["region_inferred"].sum()
    still_null = df["region"].isna().sum()
    logger.info(f"  Regions inferred by LLM: {inferred_count}")
    logger.info(f"  Regions still null (UNKNOWN or inference failed): {still_null}")
    return df
