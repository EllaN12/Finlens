import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd, numpy as np
import statsmodels.formula.api as smf
import matplotlib.pyplot as plt
from data_loader import load_regulatory_cohort

def run_hte_by_income_tier():
    df = load_regulatory_cohort()
    df_hte = df[df["state_code"].isin(["CA","TX","FL","OH"])
                & df["activity_year"].between(2018,2021)].copy()

    results = {}
    for tier in df_hte["income_tier"].dropna().unique():
        sub = df_hte[df_hte["income_tier"]==tier].copy()
        if len(sub) < 30: continue
        mod = smf.ols(
            "approval_rate ~ is_california+is_post_ccpa+is_treated"
            "+unemployment_rate+hpi+mortgage_rate_30yr",
            data=sub
        ).fit(cov_type="HC3")
        results[tier] = {"att": mod.params.get("is_treated",np.nan),
                         "se":  mod.bse.get("is_treated",np.nan),
                         "pval":mod.pvalues.get("is_treated",np.nan)}

    res_df = pd.DataFrame(results).T.sort_values("att")
    print("HTE by Income Tier:\n", res_df.round(4))

    fig, ax = plt.subplots(figsize=(8,4))
    ax.barh(res_df.index, res_df["att"], xerr=1.96*res_df["se"],
            capsize=4, color="steelblue", alpha=0.75)
    ax.axvline(0, color="black", lw=0.8)
    ax.set_title("Heterogeneous CCPA Effect by Income Tier")
    ax.set_xlabel("DiD ATT")
    plt.tight_layout()
    plt.savefig("outputs/hte_income.png", dpi=150)
    return res_df

def run_causal_forest():
    from econml.dml import CausalForestDML
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import make_pipeline

    df = load_regulatory_cohort()
    macro_cols = ["unemployment_rate", "hpi", "mortgage_rate_30yr"]
    df_cf = df[df["state_code"].isin(["CA","TX","FL","OH"])
               & df["activity_year"].between(2018,2021)].dropna(
               subset=["approval_rate","income_tier"] + macro_cols).copy()

    # ── Correct DML design ────────────────────────────────────────────────────
    # X  = income_tier (ordinal 0–3) — the moderator; CATE varies over this.
    # W  = is_post_ccpa + macro covariates — confounders DML partials out.
    # T  = is_california — binary state assignment.
    # Using macro features as X causes propensity blowup: T is a state-level
    # dummy perfectly collinear with state-level macro vars → residuals ≈ 0.
    _TIER_ORD = {"low_income": 0, "moderate_income": 1,
                 "middle_income": 2, "high_income": 3}
    df_cf["_tier_code"] = df_cf["income_tier"].map(_TIER_ORD)
    df_cf = df_cf.dropna(subset=["_tier_code"])

    X = df_cf[["_tier_code"]].values.astype(float)
    W = np.column_stack([
        df_cf["is_post_ccpa"].values,
        df_cf[macro_cols].fillna(df_cf[macro_cols].median()).values,
    ]).astype(float)
    T = df_cf["is_california"].values.astype(float)
    Y = df_cf["approval_rate"].values.astype(float)

    if len(df_cf) < 100:
        raise ValueError(f"Too few observations ({len(df_cf)}) for stable CATE estimation.")

    est = CausalForestDML(
        model_y=make_pipeline(StandardScaler(), Ridge(alpha=1.0)),
        model_t=make_pipeline(StandardScaler(), Ridge(alpha=1.0)),
        n_estimators=200, random_state=42, inference=True,
    )
    est.fit(Y, T, X=X, W=W)
    te, lb, ub = est.effect_interval(X, alpha=0.05)
    outcome_range = float(Y.max() - Y.min()) or 1.0
    if np.abs(te).max() > outcome_range * 2:
        raise ValueError(
            f"CATE estimates are numerically unstable (max |CATE| = {np.abs(te).max():.2f}, "
            f"outcome range = {outcome_range:.2f}). Propensity residuals are near zero — "
            "increase N or check feature collinearity."
        )
    df_cf["cate"] = te
    print("CATE by income tier:\n",
          df_cf.groupby("income_tier")["cate"].agg(["mean","std","count"]).round(4))
    return df_cf

if __name__ == "__main__":
    run_hte_by_income_tier()
    run_causal_forest()
    
    