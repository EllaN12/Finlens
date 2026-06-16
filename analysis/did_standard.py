#%%

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
import numpy as np
import statsmodels.formula.api as smf
import matplotlib.pyplot as plt
from data_loader import load_regulatory_cohort

def run_standard_did(outcome="approval_rate"):
    df = load_regulatory_cohort()
    df_did = df[
        df["state_code"].isin(["CA","TX","FL","OH"])
        & df["activity_year"].between(2018, 2021)
    ].copy()

    model = smf.ols(
        f"{outcome} ~ is_california + is_post_ccpa + is_treated"
        " + unemployment_rate + hpi + mortgage_rate_30yr",
        data=df_did
    ).fit(cov_type="HC3")

    est  = model.params["is_treated"]
    pval = model.pvalues["is_treated"]
    ci   = model.conf_int().loc["is_treated"]

    print(f"\nStandard DiD — {outcome}")
    print(f"  ATT:    {est:+.4f} ({est*100:+.2f} pp)")
    print(f"  95% CI: [{ci[0]:.4f}, {ci[1]:.4f}]")
    print(f"  p-val:  {pval:.4f}")

    return model, df_did

if __name__ == "__main__":
    run_standard_did()
    

# %%
