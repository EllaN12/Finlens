import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import statsmodels.formula.api as smf
from data_loader import load_regulatory_cohort

def run_triple_did():
    df = load_regulatory_cohort()
    df_did3 = df[
        df["state_code"].isin(["CA","TX","FL","OH"])
        & df["activity_year"].between(2018, 2021)
    ].copy()

    model = smf.ols(
        "approval_rate ~ is_california * is_post_ccpa * is_investor_loan"
        " + unemployment_rate + hpi + mortgage_rate_30yr + C(state_code)",
        data=df_did3
    ).fit(cov_type="HC3")

    key = "is_california:is_post_ccpa:is_investor_loan"
    if key in model.params:
        est, pval, ci = model.params[key], model.pvalues[key], model.conf_int().loc[key]
        print(f"Triple DiD (Investor × CA × Post-CCPA): {est:+.4f} (p={pval:.4f})")
        print(f"95% CI: [{ci[0]:.4f}, {ci[1]:.4f}]")
    return model

if __name__ == "__main__":
    run_triple_did()
