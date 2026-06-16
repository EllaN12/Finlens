import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd, numpy as np, warnings
import statsmodels.formula.api as smf
from data_loader import load_regulatory_cohort

TREATMENT_YEARS = {"CA": 2020, "VA": 2023, "CO": 2023}
NEVER_TREATED   = ["TX", "FL", "OH", "NY", "IL"]

def att_gt(df, outcome, covariates):
    """Simplified Callaway-Sant'Anna ATT(g,t) via 2x2 DiD blocks."""
    never = df[df["state_code"].isin(NEVER_TREATED)].copy()
    results = []
    for state, g in TREATMENT_YEARS.items():
        treated = df[df["state_code"] == state].copy()
        for t in df["activity_year"].unique():
            if t <= g - 1:   # skip reference period (g-1) and earlier
                continue
            block = pd.concat([
                treated[treated["activity_year"].isin([g-1, t])],
                never[never["activity_year"].isin([g-1, t])]
            ])
            block["_treat"] = (block["state_code"] == state).astype(int)
            block["_post"]  = (block["activity_year"] == t).astype(int)
            block["_did"]   = block["_treat"] * block["_post"]
            covs = " + ".join(covariates) if covariates else "1"
            try:
                mod = smf.ols(f"{outcome} ~ _treat+_post+_did+{covs}", data=block).fit(cov_type="HC3")
                results.append({
                    "cohort_state": state, "cohort_g": g, "calendar_year": t,
                    "event_time": t - g,
                    "att": mod.params["_did"], "se": mod.bse["_did"],
                    "pval": mod.pvalues["_did"], "n": len(block),
                })
            except Exception as e:
                warnings.warn(f"{state} t={t}: {e}")
    return pd.DataFrame(results)

def run_staggered_did():
    df  = load_regulatory_cohort()
    df2 = df[df["state_code"].isin(list(TREATMENT_YEARS)+NEVER_TREATED)].copy()
    results = att_gt(df2, "approval_rate",
                     ["unemployment_rate","hpi","mortgage_rate_30yr"])
    print(results[["cohort_state","event_time","att","se","pval"]].to_string())
    print(f"\nAvg ATT: {results['att'].mean():+.4f}")
    return results

if __name__ == "__main__":
    run_staggered_did()