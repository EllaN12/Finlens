"""
test_data_quality.py — Data quality and schema validation tests.

Mirrors the dbt tests in the guide but runs in Python against
synthetic fixtures (and can be pointed at real BigQuery data).

Tests:
  1. Schema / column presence
  2. Approval/origination rate bounds [0, 1]
  3. No empty state-year combinations
  4. Macro controls not null
  5. Treatment flag consistency
  6. Loan amount positivity
  7. Funnel monotonicity (approved ≤ applications)
  8. Unit economics margin sign plausibility
  9. Investor loan share within realistic range
 10. Regulatory era labels exhaustive

Run: pytest tests/test_data_quality.py -v
"""
import pytest
import numpy as np
import pandas as pd


# ════════════════════════════════════════════════════════════════════
# 1. Schema — required columns present
# ════════════════════════════════════════════════════════════════════

class TestSchema:

    REGULATORY_REQUIRED = [
        "activity_year","state_code","regulatory_era",
        "is_california","is_post_ccpa","is_treated",
        "approval_rate","origination_rate","avg_ltv",
        "unemployment_rate","hpi","mortgage_rate_30yr",
        "income_tier","is_investor_loan",
    ]
    FUNNEL_REQUIRED = [
        "activity_year","state_code","loan_type_label","income_tier",
        "total_applications","total_approved","total_originated",
        "approval_rate","origination_rate","denial_rate",
        "avg_loan_amount","avg_interest_rate",
    ]
    UNIT_ECON_REQUIRED = [
        "activity_year","state_code","vintage_label",
        "loan_count","avg_loan_amount","avg_annual_interest_revenue",
        "est_contribution_margin","est_contribution_margin_pct",
        "avg_ltv",
    ]

    def test_regulatory_columns(self, regulatory_df):
        missing = [c for c in self.REGULATORY_REQUIRED
                   if c not in regulatory_df.columns]
        assert not missing, f"regulatory_df missing columns: {missing}"

    def test_funnel_columns(self, funnel_df):
        missing = [c for c in self.FUNNEL_REQUIRED
                   if c not in funnel_df.columns]
        assert not missing, f"funnel_df missing columns: {missing}"

    def test_unit_econ_columns(self, unit_econ_df):
        missing = [c for c in self.UNIT_ECON_REQUIRED
                   if c not in unit_econ_df.columns]
        assert not missing, f"unit_econ_df missing columns: {missing}"

    def test_no_entirely_empty_columns(self, regulatory_df):
        """No column should be 100% null."""
        for col in regulatory_df.columns:
            pct_null = regulatory_df[col].isna().mean()
            assert pct_null < 1.0, f"Column '{col}' is entirely null"

    def test_dtypes_numeric_rates(self, regulatory_df):
        for col in ["approval_rate","origination_rate","avg_ltv"]:
            assert pd.api.types.is_numeric_dtype(regulatory_df[col]), (
                f"Column '{col}' is not numeric"
            )


# ════════════════════════════════════════════════════════════════════
# 2. Rate bounds [0, 1]
# ════════════════════════════════════════════════════════════════════

class TestRateBounds:

    RATE_COLS = ["approval_rate", "origination_rate", "denial_rate"]

    def test_approval_rate_in_bounds_regulatory(self, regulatory_df):
        bad = regulatory_df[
            (regulatory_df["approval_rate"] < 0)
            | (regulatory_df["approval_rate"] > 1)
        ]
        assert len(bad) == 0, (
            f"{len(bad)} rows with approval_rate outside [0,1]:\n{bad[['state_code','activity_year','approval_rate']].head()}"
        )

    def test_origination_rate_in_bounds(self, regulatory_df):
        bad = regulatory_df[
            (regulatory_df["origination_rate"] < 0)
            | (regulatory_df["origination_rate"] > 1)
        ]
        assert len(bad) == 0, f"{len(bad)} rows with origination_rate outside [0,1]"

    def test_origination_leq_approval(self, regulatory_df):
        """Origination rate ≤ approval rate (you can't originate more than approved)."""
        bad = regulatory_df[
            regulatory_df["origination_rate"] > regulatory_df["approval_rate"] + 0.001
        ]
        pct_bad = len(bad) / len(regulatory_df)
        assert pct_bad < 0.01, (
            f"{pct_bad:.1%} of rows have origination_rate > approval_rate "
            f"(allowed: <1%)"
        )

    def test_funnel_rate_bounds(self, funnel_df):
        for col in self.RATE_COLS:
            if col not in funnel_df.columns:
                continue
            bad = funnel_df[(funnel_df[col] < 0) | (funnel_df[col] > 1)]
            assert len(bad) == 0, f"{len(bad)} rows with {col} outside [0,1]"

    def test_avg_ltv_reasonable(self, regulatory_df):
        """LTV should be between 0.3 and 1.0 for realistic mortgages."""
        valid = regulatory_df["avg_ltv"].dropna()
        assert (valid >= 0.30).all(), "LTV values below 0.30 detected"
        assert (valid <= 1.05).all(), "LTV values above 1.05 detected"


# ════════════════════════════════════════════════════════════════════
# 3. Coverage — no empty state-year combinations
# ════════════════════════════════════════════════════════════════════

class TestCoverage:

    EXPECTED_STATES = ["CA","TX","FL","OH","NY","IL"]
    EXPECTED_YEARS  = list(range(2018, 2024))

    def test_all_states_present(self, regulatory_df):
        present = set(regulatory_df["state_code"].unique())
        missing = set(self.EXPECTED_STATES) - present
        assert not missing, f"Missing states: {missing}"

    def test_all_years_present(self, regulatory_df):
        present = set(regulatory_df["activity_year"].unique())
        missing = set(self.EXPECTED_YEARS) - present
        assert not missing, f"Missing years: {missing}"

    def test_all_state_year_combinations(self, regulatory_df):
        """Every expected (state, year) pair must have ≥ 1 row."""
        for state in self.EXPECTED_STATES:
            for year in self.EXPECTED_YEARS:
                n = len(regulatory_df[
                    (regulatory_df["state_code"] == state)
                    & (regulatory_df["activity_year"] == year)
                ])
                assert n > 0, f"No data for state={state}, year={year}"

    def test_california_in_treatment(self, regulatory_df):
        """California must have is_california == 1 for all rows."""
        ca_rows = regulatory_df[regulatory_df["state_code"] == "CA"]
        assert (ca_rows["is_california"] == 1).all(), (
            "Some CA rows have is_california != 1"
        )

    def test_non_california_not_in_treatment(self, regulatory_df):
        """Non-CA states must have is_california == 0."""
        non_ca = regulatory_df[regulatory_df["state_code"] != "CA"]
        assert (non_ca["is_california"] == 0).all(), (
            "Non-CA rows have is_california != 0"
        )

    def test_income_tiers_all_present(self, regulatory_df):
        expected = {"low_income","moderate_income","middle_income","high_income"}
        present  = set(regulatory_df["income_tier"].unique())
        missing  = expected - present
        assert not missing, f"Missing income tiers: {missing}"

    def test_years_in_funnel(self, funnel_df):
        present = set(funnel_df["activity_year"].unique())
        missing = set(self.EXPECTED_YEARS) - present
        assert not missing, f"funnel_df missing years: {missing}"


# ════════════════════════════════════════════════════════════════════
# 4. Macro controls
# ════════════════════════════════════════════════════════════════════

class TestMacroControls:

    MACRO_COLS = ["unemployment_rate","hpi","mortgage_rate_30yr"]

    def test_no_null_macro_controls(self, regulatory_df):
        for col in self.MACRO_COLS:
            null_pct = regulatory_df[col].isna().mean()
            assert null_pct == 0, (
                f"Column '{col}' has {null_pct:.1%} null values — "
                "macro controls must be fully populated"
            )

    def test_unemployment_rate_range(self, regulatory_df):
        ur = regulatory_df["unemployment_rate"]
        assert (ur >= 1.0).all(), f"Unemployment rate < 1%: min={ur.min():.2f}"
        assert (ur <= 20.0).all(), f"Unemployment rate > 20%: max={ur.max():.2f}"

    def test_hpi_positive(self, regulatory_df):
        assert (regulatory_df["hpi"] > 0).all(), "HPI must be positive"

    def test_mortgage_rate_range(self, regulatory_df):
        mr = regulatory_df["mortgage_rate_30yr"]
        assert (mr >= 2.0).all(), f"Mortgage rate < 2%: min={mr.min():.2f}"
        assert (mr <= 12.0).all(), f"Mortgage rate > 12%: max={mr.max():.2f}"

    def test_macro_varies_by_year(self, regulatory_df):
        """Macro controls must vary across years (not constant)."""
        for col in self.MACRO_COLS:
            yearly_means = regulatory_df.groupby("activity_year")[col].mean()
            assert yearly_means.std() > 0, (
                f"Macro control '{col}' does not vary across years — "
                "may indicate a data loading error"
            )

    def test_mortgage_rate_rises_post_2021(self, regulatory_df):
        """Rising rate environment post-2021 is a key narrative."""
        pre_rate  = regulatory_df[regulatory_df["activity_year"] <= 2021]["mortgage_rate_30yr"].mean()
        post_rate = regulatory_df[regulatory_df["activity_year"] >= 2022]["mortgage_rate_30yr"].mean()
        assert post_rate > pre_rate, (
            f"Expected mortgage rate to rise post-2021 "
            f"(pre={pre_rate:.2f}, post={post_rate:.2f})"
        )


# ════════════════════════════════════════════════════════════════════
# 5. Treatment flag consistency
# ════════════════════════════════════════════════════════════════════

class TestTreatmentFlags:

    def test_is_treated_is_product(self, regulatory_df):
        """is_treated must equal is_california × is_post_ccpa."""
        expected = regulatory_df["is_california"] * regulatory_df["is_post_ccpa"]
        mismatch = (regulatory_df["is_treated"] != expected).sum()
        assert mismatch == 0, (
            f"{mismatch} rows where is_treated ≠ is_california × is_post_ccpa"
        )

    def test_is_post_ccpa_threshold(self, regulatory_df):
        """is_post_ccpa must be 1 iff activity_year >= 2020."""
        should_be_post = regulatory_df[regulatory_df["activity_year"] >= 2020]
        should_be_pre  = regulatory_df[regulatory_df["activity_year"] < 2020]
        assert (should_be_post["is_post_ccpa"] == 1).all(), \
            "Rows with year >= 2020 have is_post_ccpa != 1"
        assert (should_be_pre["is_post_ccpa"] == 0).all(), \
            "Rows with year < 2020 have is_post_ccpa != 0"

    def test_treatment_years_coverage(self, regulatory_df):
        """CA post-2020 rows must exist and be flagged as treated."""
        treated_rows = regulatory_df[
            (regulatory_df["state_code"] == "CA")
            & (regulatory_df["activity_year"] >= 2020)
        ]
        assert len(treated_rows) > 0, "No treated (CA post-2020) rows found"
        assert (treated_rows["is_treated"] == 1).all(), \
            "CA post-2020 rows not flagged as treated"

    def test_binary_flags(self, regulatory_df):
        """All binary flags must contain only 0 and 1."""
        for col in ["is_california","is_post_ccpa","is_treated","is_investor_loan"]:
            unique_vals = set(regulatory_df[col].unique())
            assert unique_vals <= {0, 1}, (
                f"Column '{col}' contains values other than 0/1: {unique_vals}"
            )


# ════════════════════════════════════════════════════════════════════
# 6. Funnel monotonicity
# ════════════════════════════════════════════════════════════════════

class TestFunnelMonotonicity:

    def test_approved_leq_applications(self, funnel_df):
        """You cannot approve more than you receive."""
        bad = funnel_df[funnel_df["total_approved"] > funnel_df["total_applications"]]
        assert len(bad) == 0, (
            f"{len(bad)} rows where total_approved > total_applications"
        )

    def test_originated_leq_approved(self, funnel_df):
        """You cannot originate more than you approve."""
        bad = funnel_df[funnel_df["total_originated"] > funnel_df["total_approved"] + 1]
        assert len(bad) == 0, (
            f"{len(bad)} rows where total_originated > total_approved"
        )

    def test_all_counts_positive(self, funnel_df):
        for col in ["total_applications","total_approved","total_originated"]:
            assert (funnel_df[col] >= 0).all(), f"Negative values in {col}"

    def test_total_applications_nonzero(self, funnel_df):
        zero_apps = funnel_df[funnel_df["total_applications"] == 0]
        assert len(zero_apps) == 0, (
            f"{len(zero_apps)} rows with zero total_applications"
        )


# ════════════════════════════════════════════════════════════════════
# 7. Unit economics plausibility
# ════════════════════════════════════════════════════════════════════

class TestUnitEconomics:

    def test_avg_loan_amount_positive(self, unit_econ_df):
        assert (unit_econ_df["avg_loan_amount"] > 0).all(), \
            "Negative or zero average loan amounts"

    def test_interest_revenue_positive(self, unit_econ_df):
        assert (unit_econ_df["avg_annual_interest_revenue"] > 0).all(), \
            "Non-positive interest revenue"

    def test_contribution_margin_reasonable(self, unit_econ_df):
        """Margin as % of loan should be between -5% and 15%."""
        pct = unit_econ_df["est_contribution_margin_pct"]
        assert (pct >= -0.05).all(), f"Margin pct too low: {pct.min():.4f}"
        assert (pct <= 0.15).all(), f"Margin pct too high: {pct.max():.4f}"

    def test_vintage_label_format(self, unit_econ_df):
        """Vintage labels must follow 'VTG-YYYY' format."""
        bad = unit_econ_df[
            ~unit_econ_df["vintage_label"].str.match(r"^VTG-\d{4}$", na=False)
        ]
        assert len(bad) == 0, (
            f"{len(bad)} rows with invalid vintage_label format"
        )

    def test_rate_era_labels(self, unit_econ_df):
        """rate_era must be one of two expected values."""
        valid = {"low_rate_era","rising_rate_era"}
        actual = set(unit_econ_df["rate_era"].unique())
        invalid = actual - valid
        assert not invalid, f"Unexpected rate_era values: {invalid}"


# ════════════════════════════════════════════════════════════════════
# 8. Investor loan share
# ════════════════════════════════════════════════════════════════════

class TestInvestorLoans:

    def test_investor_share_realistic(self, regulatory_df):
        """Investor loan share should be between 5% and 35% nationally."""
        investor_share = regulatory_df["is_investor_loan"].mean()
        assert 0.05 <= investor_share <= 0.35, (
            f"Investor loan share {investor_share:.2%} outside [5%, 35%]"
        )

    def test_investor_flag_binary(self, regulatory_df):
        unique = set(regulatory_df["is_investor_loan"].unique())
        assert unique <= {0, 1}, f"is_investor_loan not binary: {unique}"


# ════════════════════════════════════════════════════════════════════
# 9. Regulatory era labels
# ════════════════════════════════════════════════════════════════════

class TestRegulatoryEra:

    VALID_ERAS = {"pre_ccpa","ccpa_transition","post_ccpa"}

    def test_era_labels_exhaustive(self, regulatory_df):
        actual  = set(regulatory_df["regulatory_era"].unique())
        invalid = actual - self.VALID_ERAS
        assert not invalid, f"Unexpected regulatory_era values: {invalid}"

    def test_era_year_mapping(self, regulatory_df):
        """Verify year → era mapping is correct."""
        mappings = {
            2018: "pre_ccpa", 2019: "pre_ccpa",
            2020: "ccpa_transition",
            2021: "post_ccpa", 2022: "post_ccpa", 2023: "post_ccpa",
        }
        for year, expected_era in mappings.items():
            rows = regulatory_df[regulatory_df["activity_year"] == year]
            if len(rows) == 0:
                continue
            actual_eras = rows["regulatory_era"].unique()
            assert len(actual_eras) == 1, (
                f"Year {year} has multiple eras: {actual_eras}"
            )
            assert actual_eras[0] == expected_era, (
                f"Year {year}: expected era '{expected_era}', "
                f"got '{actual_eras[0]}'"
            )

    def test_no_null_era(self, regulatory_df):
        null_count = regulatory_df["regulatory_era"].isna().sum()
        assert null_count == 0, f"{null_count} rows with null regulatory_era"
