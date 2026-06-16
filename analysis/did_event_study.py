import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd, numpy as np
import statsmodels.formula.api as smf
import matplotlib.pyplot as plt
from data_loader import load_regulatory_cohort

def run_event_study(outcome="approval_rate"):
    df = load_regulatory_cohort()
    df_es = df[df["state_code"].isin(["CA","TX","FL","OH"])].copy()
    df_es["event_time"] = df_es["activity_year"].astype(int) - 2020

    for t in df_es["event_time"].unique():
        if t == -1:
            continue
        t = int(t)
        col = f"ca_t{'p' if t >= 0 else 'm'}{abs(t)}"
        df_es[col] = ((df_es["is_california"] == 1) & (df_es["event_time"] == t)).astype(int)

    dummies  = [c for c in df_es.columns if c.startswith("ca_t")]
    formula  = f"{outcome} ~ is_california + {' + '.join(dummies)} + unemployment_rate + hpi + mortgage_rate_30yr + C(activity_year)"
    model    = smf.ols(formula, data=df_es).fit(cov_type="HC3")

    event_times = sorted(df_es["event_time"].unique())
    coefs = []
    for t in event_times:
        if t == -1:
            coefs.append({"t": t, "coef": 0.0, "lo": 0.0, "hi": 0.0})
        else:
            col = f"ca_t{'p' if t >= 0 else 'm'}{abs(int(t))}"
            if col in model.params:
                coefs.append({"t": t, "coef": model.params[col],
                              "lo": model.conf_int().loc[col,0],
                              "hi": model.conf_int().loc[col,1]})

    coef_df = pd.DataFrame(coefs)

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.errorbar(coef_df["t"], coef_df["coef"],
                yerr=[coef_df["coef"]-coef_df["lo"], coef_df["hi"]-coef_df["coef"]],
                fmt="o-", capsize=5, color="steelblue")
    ax.axhline(0, color="black", lw=0.8)
    ax.axvline(-0.5, color="red", ls="--", alpha=0.6, label="CCPA")
    ax.set_title(f"Event Study: CCPA Effect on {outcome}")
    ax.set_xlabel("Event Time"); ax.set_ylabel("DiD Coefficient")
    ax.legend(); plt.tight_layout()
    plt.savefig("outputs/event_study.png", dpi=150)
    print("Saved outputs/event_study.png")
    return model, coef_df

if __name__ == "__main__":
    run_event_study()
