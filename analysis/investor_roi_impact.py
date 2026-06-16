import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd, numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
from data_loader import load_regulatory_cohort

BASE = {
    "property_value":       500_000,
    "ltv":                  0.75,
    "loan_term_yrs":        30,
    "hold_period_yrs":      5,
    "gross_rent_multiplier": 18,
    "vacancy_rate":         0.05,
    "operating_expense_ratio": 0.40,
    "annual_appreciation":  0.04,
    "flip_hold_months":     6,
    "flip_renovation_pct":  0.10,
    "flip_selling_costs":   0.06,
}

def rental_roi(params, interest_rate, approval_delta=0.0):
    pv, ltv   = params["property_value"], params["ltv"]
    loan      = pv * ltv
    equity    = pv - loan
    r_mo      = interest_rate / 12
    n         = params["loan_term_yrs"] * 12
    pmt       = loan * (r_mo*(1+r_mo)**n) / ((1+r_mo)**n - 1)
    gross_rent= pv / params["gross_rent_multiplier"]
    noi       = gross_rent * (1-params["vacancy_rate"]) * (1-params["operating_expense_ratio"])
    net_cf    = noi - pmt*12
    adj_apprec= params["annual_appreciation"] + approval_delta * (-0.30)
    term_val  = pv * (1+adj_apprec)**params["hold_period_yrs"]
    bal       = loan * ((1+r_mo)**n - (1+r_mo)**(params["hold_period_yrs"]*12)) / ((1+r_mo)**n - 1)
    terminal_equity = term_val - bal - term_val*0.06
    total_return    = net_cf*params["hold_period_yrs"] + (terminal_equity - equity)
    ann_roi         = total_return / (equity * params["hold_period_yrs"])
    return {"annualized_roi": ann_roi, "net_cash_flow_pa": net_cf,
            "cap_rate": noi/pv, "dscr": noi/(pmt*12),
            "adjusted_appreciation": adj_apprec, "equity": equity}

def flip_roi(params, interest_rate, approval_delta=0.0):
    pv         = params["property_value"]
    loan       = pv * params["ltv"]
    equity     = pv - loan
    hold_mo    = params["flip_hold_months"]
    reno       = pv * params["flip_renovation_pct"]
    carry      = loan * (interest_rate/12) * hold_mo
    total_in   = equity + reno + carry
    adj_apprec = params["annual_appreciation"] + approval_delta*(-0.30)
    arv        = pv * (1 + adj_apprec*(hold_mo/12)) + reno*1.20
    net_proc   = arv - loan - arv*params["flip_selling_costs"]
    profit     = net_proc - total_in
    roi_hold   = profit / total_in
    ann_roi    = (1+roi_hold)**(12/hold_mo) - 1
    return {"annualized_roi": ann_roi, "roi_hold_period": roi_hold,
            "arv": arv, "gross_profit": profit, "total_cost": total_in}

def run_scenario_analysis():
    df      = load_regulatory_cohort()
    pre_rate  = df[df["state_code"].eq("CA") & df["activity_year"].isin([2018,2019])]["avg_interest_rate"].mean()
    post_rate = df[df["state_code"].eq("CA") & df["activity_year"].isin([2020,2021])]["avg_interest_rate"].mean()
    did_est   = -0.018   # replace with actual DiD output

    scenarios = {
        "Baseline\n(Pre-CCPA)":     {"rate": pre_rate/100,        "delta": 0.0},
        "Post-CCPA\n(Observed)":    {"rate": post_rate/100,        "delta": did_est},
        "Stress\n(2× Effect)":      {"rate": (post_rate+0.5)/100,  "delta": did_est*2},
    }

    print(f"CA Avg Rate Pre:  {pre_rate:.3f}% | Post: {post_rate:.3f}%")
    print(f"DiD Estimate:     {did_est:+.4f} ({did_est*100:+.2f} pp)\n")

    rental_res = {n: rental_roi(BASE, s["rate"], s["delta"]) for n, s in scenarios.items()}
    flip_res   = {n: flip_roi(BASE,   s["rate"], s["delta"]) for n, s in scenarios.items()}

    print("=" * 65)
    print("RENTAL INVESTOR ROI")
    print("=" * 65)
    for metric in ["annualized_roi","net_cash_flow_pa","cap_rate","dscr","adjusted_appreciation"]:
        row = f"{metric:<32}"
        for n in scenarios:
            v = rental_res[n][metric]
            fmt = f"{v:.1%}" if metric in ["annualized_roi","cap_rate","adjusted_appreciation"] else f"${v:,.0f}" if "cash" in metric else f"{v:.2f}"
            row += f"  {fmt:>18}"
        print(row)

    fig, axes = plt.subplots(1,2,figsize=(13,5))
    names   = [n.replace("\n"," ") for n in scenarios]
    colors  = ["#2196F3","#FF9800","#F44336"]
    r_rois  = [rental_res[n]["annualized_roi"]*100 for n in scenarios]
    fl_rois = [flip_res[n]["annualized_roi"]*100   for n in scenarios]

    for ax, rois, title in zip(axes, [r_rois, fl_rois],
                                ["Buy-and-Hold Annualized ROI","Fix-and-Flip Annualized ROI"]):
        bars = ax.bar(names, rois, color=colors, alpha=0.85, edgecolor="white", width=0.5)
        ax.yaxis.set_major_formatter(mtick.PercentFormatter())
        ax.set_title(f"{title}\n(CA, $500K Property, 75% LTV)")
        ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)
        for bar, roi in zip(bars, rois):
            ax.text(bar.get_x()+bar.get_width()/2, bar.get_height()+0.2,
                    f"{roi:.1f}%", ha="center", va="bottom", fontweight="bold")
        ax.tick_params(axis="x", rotation=10)

    plt.tight_layout()
    plt.savefig("outputs/investor_roi.png", dpi=150)
    print("Saved outputs/investor_roi.png")
    return rental_res, flip_res

if __name__ == "__main__":
    run_scenario_analysis()
    