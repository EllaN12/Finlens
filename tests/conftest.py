"""
conftest.py — Shared pytest fixtures for FinLens test suite.

Generates  realistic synthetic that mirrors the BigQuery mart  schemas
so all tests run locally without any GCP credentials.

Run: pytest tests/ -v
"""
import pytest
import numpy as np
import pandas as pd

# ── Reproducibility ──────────────────────────────────────────────────
RNG = np.random.default_rng(seed=42)

STATES        = ["CA", "TX", "FL", "OH", "NY", "IL"]
YEARS         = list(range(2018, 2024))
LOAN_TYPES    = ["conventional", "fha", "va", "usda"]
INCOME_TIERS  = ["low_income", "moderate_income", "middle_income", "high_income"]
LOAN_SIZES    = ["small", "conforming", "jumbo"]
REG_ERAS      = {2018: "pre_ccpa", 2019: "pre_ccpa",
                 2020: "ccpa_transition",
                 2021: "post_ccpa", 2022: "post_ccpa", 2023: "post_ccpa"}

# True DGP parameters — used to verify estimator recovery in tests
TRUE_CCPA_EFFECT = -0.025      # -2.5pp approval rate impact on CA post-2020
TRUE_CONFOUNDERS = {           # macro → outcome coefficients
    "unemployment_rate": -0.008,
    "hpi":               0.0003,
    "mortgage_rate_30yr": -0.015,
}


# ────────────────────────────────────────────────────────────────────
# Helper: macro controls (deterministic by state/year)
# ────────────────────────────────────────────────────────────────────
def _macro_values(state: str, year: int) -> dict:
    """Realistic but synthetic macro controls, vary by state + year."""
    base_ur  = {"CA":4.5,"TX":4.0,"FL":3.8,"OH":4.2,"NY":4.7,"IL":4.3}
    base_hpi = {"CA":310,"TX":220,"FL":250,"OH":180,"NY":290,"IL":210}
    trend_ur = (year - 2018) * 0.1 + (0.5 if year >= 2020 else 0)  # slight rise 2020
    trend_hpi = (year - 2018) * 12

    ur  = base_ur.get(state, 4.0) + trend_ur + RNG.normal(0, 0.15)
    hpi = base_hpi.get(state, 220) + trend_hpi + RNG.normal(0, 5)
    mr  = 3.5 + max(0, (year - 2021) * 0.8) + RNG.normal(0, 0.1)  # rises 2022+
    return {"unemployment_rate": round(ur, 2),
            "hpi":               round(hpi, 1),
            "mortgage_rate_30yr": round(mr, 3)}


# ────────────────────────────────────────────────────────────────────
# Fixture: mart_regulatory_cohort
# ────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="session")
def regulatory_df() -> pd.DataFrame:
    """
    Synthetic mart_regulatory_cohort with a known CCPA treatment effect
    of TRUE_CCPA_EFFECT = -0.025 on approval_rate for California post-2020.
    Estimators should recover a value close to this.
    """
    rows = []
    n_per_cell = 30   # observations per state-year-tier cell

    for state in STATES:
        for year in YEARS:
            macro = _macro_values(state, year)
            is_ca   = 1 if state == "CA" else 0
            is_post = 1 if year >= 2020 else 0
            is_treat = is_ca * is_post

            for income_tier in INCOME_TIERS:
                for loan_type in LOAN_TYPES:

                    # Base approval rate from DGP
                    base_rate = (
                        0.72
                        + (0.03 if income_tier == "high_income" else
                           0.01 if income_tier == "middle_income" else
                          -0.02 if income_tier == "low_income" else 0)
                        + TRUE_CCPA_EFFECT * is_treat
                        + TRUE_CONFOUNDERS["unemployment_rate"] * macro["unemployment_rate"]
                        + TRUE_CONFOUNDERS["hpi"] * (macro["hpi"] / 100)
                        + TRUE_CONFOUNDERS["mortgage_rate_30yr"] * macro["mortgage_rate_30yr"]
                        + RNG.normal(0, 0.015)
                    )
                    approval_rate = float(np.clip(base_rate, 0.30, 0.98))

                    # Origination rate ~ approval rate * 0.85
                    orig_rate = float(np.clip(approval_rate * 0.85
                                              + RNG.normal(0, 0.01), 0.20, 0.95))

                    # Average loan amount
                    base_loan = (
                        350_000 if state in ("CA","NY") else 280_000
                    ) * (1 + (year-2018)*0.04) * (1 + RNG.normal(0, 0.05))

                    rows.append({
                        "activity_year":          year,
                        "state_code":             state,
                        "regulatory_era":         REG_ERAS[year],
                        "is_california":          is_ca,
                        "is_post_ccpa":           is_post,
                        "is_treated":             is_treat,
                        "is_treated_staggered":   is_treat,
                        "treatment_year":         2020 if state == "CA" else None,
                        "loan_type_label":        loan_type,
                        "loan_purpose_label":     "purchase",
                        "income_tier":            income_tier,
                        "is_investor_loan":       int(RNG.random() < 0.18),
                        "n_applications":         n_per_cell,
                        "n_approved":             int(approval_rate * n_per_cell),
                        "n_originated":           int(orig_rate * n_per_cell),
                        "approval_rate":          round(approval_rate, 4),
                        "origination_rate":       round(orig_rate, 4),
                        "avg_approved_loan_amount": round(base_loan, 0),
                        "avg_approved_income":    round(80_000 + RNG.normal(0, 15_000), 0),
                        "pct_missing_income":     round(abs(RNG.normal(0.05, 0.02)), 4),
                        "avg_interest_rate":      round(macro["mortgage_rate_30yr"]
                                                        + RNG.normal(0.3, 0.1), 3),
                        "avg_ltv":                round(np.clip(0.78 + RNG.normal(0, 0.04),
                                                                0.50, 0.97), 3),
                        **macro,
                    })

    df = pd.DataFrame(rows)
    return df


# ────────────────────────────────────────────────────────────────────
# Fixture: mart_lending_funnel
# ────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="session")
def funnel_df() -> pd.DataFrame:
    rows = []
    for state in STATES:
        for year in YEARS:
            macro = _macro_values(state, year)
            for income_tier in INCOME_TIERS:
                for loan_type in LOAN_TYPES:
                    n_apps  = int(RNG.integers(800, 5000))
                    apr     = float(np.clip(0.72 + RNG.normal(0, 0.04), 0.4, 0.95))
                    orig_r  = float(np.clip(apr * 0.85 + RNG.normal(0, 0.01), 0.3, 0.93))
                    denial  = float(np.clip(1 - apr - 0.05, 0.02, 0.5))
                    rows.append({
                        "activity_year":     year,
                        "state_code":        state,
                        "regulatory_era":    REG_ERAS[year],
                        "loan_type_label":   loan_type,
                        "loan_purpose_label":"purchase",
                        "loan_size_tier":    RNG.choice(LOAN_SIZES),
                        "income_tier":       income_tier,
                        "total_applications":n_apps,
                        "total_approved":    int(apr * n_apps),
                        "total_originated":  int(orig_r * n_apps),
                        "total_denied":      int(denial * n_apps),
                        "total_withdrawn":   int(0.05 * n_apps),
                        "approval_rate":     round(apr, 4),
                        "origination_rate":  round(orig_r, 4),
                        "denial_rate":       round(denial, 4),
                        "close_rate":        round(orig_r / max(apr, 0.01), 4),
                        "avg_loan_amount":   round(300_000 + RNG.normal(0, 50_000), 0),
                        "total_loan_volume": round(n_apps * orig_r * 300_000, 0),
                        "avg_interest_rate": round(macro["mortgage_rate_30yr"]
                                                   + RNG.normal(0.3, 0.1), 3),
                    })
    return pd.DataFrame(rows)


# ────────────────────────────────────────────────────────────────────
# Fixture: mart_unit_economics
# ────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="session")
def unit_econ_df() -> pd.DataFrame:
    rows = []
    for state in STATES:
        for year in YEARS:
            for income_tier in INCOME_TIERS:
                for loan_type in LOAN_TYPES:
                    loan_amt = round(300_000 * (1 + (year-2018)*0.04)
                                     + RNG.normal(0, 30_000), 0)
                    rate     = round(3.5 + max(0,(year-2021)*0.8)
                                     + RNG.normal(0.3, 0.1), 3)
                    ann_rev  = round(loan_amt * rate / 100, 0)
                    orig_cost= round(loan_amt * 0.015, 0)
                    svc_cost = round(loan_amt * 0.003, 0)
                    margin   = round(ann_rev - orig_cost - svc_cost, 0)
                    rows.append({
                        "activity_year":             year,
                        "vintage_label":             f"VTG-{year}",
                        "regulatory_era":            REG_ERAS[year],
                        "rate_era":                  ("rising_rate_era"
                                                      if year >= 2022
                                                      else "low_rate_era"),
                        "state_code":                state,
                        "loan_type_label":           loan_type,
                        "loan_size_tier":            RNG.choice(LOAN_SIZES),
                        "income_tier":               income_tier,
                        "is_investor_loan":          int(RNG.random() < 0.18),
                        "loan_count":                int(RNG.integers(50, 500)),
                        "avg_loan_amount":           loan_amt,
                        "total_loan_volume":         loan_amt * 200,
                        "avg_annual_interest_revenue": ann_rev,
                        "total_interest_revenue_proxy": ann_rev * 200,
                        "est_origination_cost_per_loan": orig_cost,
                        "est_annual_servicing_cost":  svc_cost,
                        "est_contribution_margin":    margin,
                        "est_contribution_margin_pct": round(margin/max(loan_amt,1), 4),
                        "avg_ltv":                   round(np.clip(0.78+RNG.normal(0,0.04),
                                                                   0.5, 0.97), 3),
                        "avg_lti":                   round(3.5 + RNG.normal(0, 0.5), 2),
                        "avg_cltv":                  round(np.clip(0.80+RNG.normal(0,0.04),
                                                                   0.5, 0.98), 3),
                    })
    return pd.DataFrame(rows)


# ────────────────────────────────────────────────────────────────────
# Fixture: small_regulatory_df (faster for unit tests)
# ────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="session")
def small_regulatory_df(regulatory_df) -> pd.DataFrame:
    """Subset: CA + TX only, 2018–2021, conventional loans only."""
    return regulatory_df[
        regulatory_df["state_code"].isin(["CA","TX"])
        & regulatory_df["activity_year"].between(2018, 2021)
        & regulatory_df["loan_type_label"].eq("conventional")
    ].copy()
