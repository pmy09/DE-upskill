"""Unit tests for cleaning helpers."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Allow imports from my_pipeline/ when running pytest from repo root or this dir
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clean import (  # noqa: E402
    standardize_emails,
    validate_emails,
    standardize_phone_numbers,
    standardize_names,
    standardize_regions,
    clean_dataframe,
    deduplicate_customers,
)


class TestEmailCleaning:
    def test_standardize_emails_lower_and_strip(self):
        s = pd.Series(["  Alice@Example.COM ", "bob@test.com"])
        result = standardize_emails(s)
        assert result.tolist() == ["alice@example.com", "bob@test.com"]

    def test_validate_emails(self):
        s = pd.Series(["ok@gmail.com", "not-an-email", "missing@", np.nan])
        result = validate_emails(standardize_emails(s))
        assert result.tolist() == [True, False, False, False]


class TestPhoneCleaning:
    def test_international_plus_preserved(self):
        s = pd.Series(["+1 (555) 123-4567"])
        assert standardize_phone_numbers(s).iloc[0] == "+15551234567"

    def test_invalid_phone_becomes_nan(self):
        s = pd.Series(["invalid-phone", "123"])
        result = standardize_phone_numbers(s)
        assert pd.isna(result.iloc[0])
        assert pd.isna(result.iloc[1])


class TestNameAndRegion:
    def test_standardize_names_title_case(self):
        s = pd.Series(["  mary   JANE ", "josé"])
        result = standardize_names(s)
        assert result.iloc[0] == "Mary Jane"
        assert result.iloc[1] == "José"

    def test_region_mapping(self):
        s = pd.Series(["usa", "EMEA", "Asia Pacific", "N/A", None])
        result = standardize_regions(s)
        assert result.tolist()[0:3] == ["US", "EU", "APAC"]
        assert pd.isna(result.iloc[3])
        assert pd.isna(result.iloc[4])


class TestCleanAndDedupe:
    def _sample_frame(self):
        return pd.DataFrame({
            "email": ["A@X.com", "a@x.com", "bad"],
            "first_name": ["Ann", "Anne", "Bob"],
            "last_name": ["Lee", "Lee", "X"],
            "phone": ["555.123.4567", None, None],
            "region": ["usa", None, "EU"],
            "registration_date": ["2021-01-01", "2020-01-01", "2019-06-01"],
            "opt_out": [0, 1, 0],
            "source": ["website", "crm", "erp"],
        })

    def test_clean_dataframe_adds_email_valid(self):
        cleaned = clean_dataframe(self._sample_frame())
        assert "email_valid" in cleaned.columns
        assert cleaned["email"].iloc[0] == "a@x.com"
        assert cleaned["region"].iloc[0] == "US"

    def test_dedupe_prefers_crm_and_merges_opt_out(self):
        cleaned = clean_dataframe(self._sample_frame())
        deduped = deduplicate_customers(cleaned)
        # Two valid emails collapse to one (a@x.com); invalid "bad" remains
        valid = deduped[deduped["email_valid"] == True]  # noqa: E712
        assert len(valid) == 1
        row = valid.iloc[0]
        assert row["source"] == "crm"  # higher priority kept as base
        assert row["opt_out"] is True or row["opt_out"] == True  # GDPR any-source
        assert row["phone"] == "5551234567"  # filled from website
