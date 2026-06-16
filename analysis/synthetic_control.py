import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd, numpy as np
import matplotlib.pyplot as plt
from pysyncon import Dataprep, Synth
from data_loader import load_regulatory_cohort

def run_synthetic_control(outcome="approval_rate"):
    df = load_regulatory_cohort()
    panel = df.groupby(["state_code","activity_year"]).agg(
        approval_rate    =("approval_rate","mean"),
        origination_rate =("origination_rate","mean"),
        avg_ltv          =("avg_ltv","mean"),
        unemployment_rate=("unemployment_rate","mean"),
        hpi              =("hpi","mean"),
        mortgage_rate_30yr=("mortgage_rate_30yr","mean"),
        pct_missing_income=("pct_missing_income","mean"),
    ).reset_index()

    donor_states = ["TX","FL","OH","NY","IL","WA"]
    panel_sc = panel[panel["state_code"].isin(["CA"]+donor_states)].copy()

    dataprep = Dataprep(
        foo=panel_sc,
        predictors=["unemployment_rate","hpi","mortgage_rate_30yr"],
        predictors_op="mean",
        time_predictors_prior=list(range(2018,2020)),
        special_predictors=[(outcome,[2018],"mean"),(outcome,[2019],"mean")],
        dependent=outcome,
        unit_variable="state_code",
        time_variable="activity_year",
        treatment_identifier="CA",
        controls_identifier=donor_states,
        time_optimize_ssr=list(range(2018, 2020)),
    )
    synth = Synth()
    synth.fit(dataprep)

    panel_wide = panel_sc.pivot(index="activity_year",columns="state_code",values=outcome)
    # Align W_weights to the column order of panel_wide to avoid silent misalignment
    weights = synth.weights()
    w = weights.reindex(donor_states).values
    synthetic_ca = panel_wide[donor_states].values @ w
    actual_ca    = panel_wide["CA"].values
    gap          = actual_ca - synthetic_ca
    years        = panel_wide.index.tolist()

    fig, axes = plt.subplots(2,1,figsize=(12,8))
    axes[0].plot(years, actual_ca,    "b-o", label="Actual CA")
    axes[0].plot(years, synthetic_ca, "r--s", label="Synthetic CA")
    axes[0].axvline(x=2019.5, color="gray", ls="--", label="CCPA")
    axes[0].set_title(f"Synthetic Control: {outcome}"); axes[0].legend()

    colors = ["crimson" if g < 0 else "steelblue" for g in gap]
    axes[1].bar(years, gap, color=colors, alpha=0.75)
    axes[1].axhline(0, color="black", lw=0.8)
    axes[1].axvline(x=2019.5, color="gray", ls="--")
    axes[1].set_title("Treatment Effect Gap (Actual – Synthetic CA)")
    plt.tight_layout()
    plt.savefig("outputs/synthetic_control.png", dpi=150)
    print("Saved outputs/synthetic_control.png")

    print("\nSynthetic CA donor weights:")
    for s, weight in weights.items():
        if weight > 0.01:
            print(f"  {s}: {weight:.4f}")

    return gap

if __name__ == "__main__":
    run_synthetic_control()
    