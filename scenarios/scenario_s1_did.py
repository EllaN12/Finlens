"""
scenarios/scenario_s1_did.py
FinLens — Scenario 1: Standard 2×2 Difference-in-Differences
=============================================================
Business question:
    Did the California Consumer Privacy Act measurably change mortgage lending
    outcomes in California relative to comparable non-adopting states (TX/FL/OH),
    and if so, by how much?

Method: HC3-robust OLS DiD with state + macro controls.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import statsmodels.formula.api as smf

from .base import ScenarioResult, ScenarioRunner


class ScenarioS1DiD(ScenarioRunner):
    """Standard 2×2 DiD — CCPA vs. control states."""

    @property
    def name(self) -> str:
        return "S1_2x2_DiD"

    def run(self) -> ScenarioResult:
        panel = self._panel()

        # ── OLS DiD with HC3 SEs ──────────────────────────────────────────────
        d = panel.copy()
        d["treat"] = d["is_treated_unit"]
        d["post"]  = d["is_post"]
        d["did"]   = d["treat"] * d["post"]

        covs = [c for c in ["unemployment_rate", "hpi", "mortgage_rate_30yr"]
                if c in d.columns]
        cov_str = " + ".join(covs)
        formula = (f"{self.outcome} ~ treat + post + did"
                   + (f" + {cov_str}" if cov_str else "")
                   + " + C(state_code)")

        mod = smf.ols(formula, data=d.dropna(subset=[self.outcome] + covs)).fit(cov_type="HC3")
        est  = float(mod.params.get("did", np.nan))
        se   = float(mod.bse.get("did", np.nan))
        pval = float(mod.pvalues.get("did", 1.0))
        ci   = tuple(mod.conf_int().loc["did"]) if "did" in mod.conf_int().index else (np.nan, np.nan)

        # ── Time-series chart ─────────────────────────────────────────────────
        ts = d.groupby(["activity_year", "is_treated_unit"])[self.outcome].mean().reset_index()
        ts["group"] = ts["is_treated_unit"].map(
            {1: f"{self.treatment_state} (treated)", 0: "Control avg"})

        fig_primary = go.Figure()
        colour_map = {f"{self.treatment_state} (treated)": "#1f77b4", "Control avg": "#7f7f7f"}
        for grp, sub in ts.groupby("group"):
            fig_primary.add_trace(go.Scatter(
                x=sub["activity_year"], y=sub[self.outcome] * 100,
                mode="lines+markers", name=grp,
                line=dict(color=colour_map.get(grp, "#333"), width=2),
            ))
        law_yr = self.post_years[0]
        fig_primary.add_vrect(
            x0=law_yr - 0.5, x1=self.post_years[1] + 0.5,
            fillcolor="rgba(255,200,60,0.12)", opacity=1, line_width=0,
            annotation_text="Post-law", annotation_position="top left",
        )
        fig_primary.update_layout(
            title=f"DiD Time Series — {self.outcome}",
            xaxis_title="Year", yaxis_title=f"{self.outcome} (%)",
            height=380,
        )

        # ── 2×2 means table ───────────────────────────────────────────────────
        means = d.groupby(["is_treated_unit", "is_post"])[self.outcome].mean().unstack()
        means.index = [f"{self.treatment_state} (treated)" if i == 1 else "Control"
                       for i in means.index]
        means.columns = ["Pre", "Post"]
        means["Δ"] = means["Post"] - means["Pre"]
        means_long = means.reset_index().melt(id_vars="index", var_name="Period", value_name=self.outcome)

        fig_secondary = go.Figure(go.Table(
            header=dict(values=["Group", "Pre", "Post", "Δ (Post−Pre)"],
                        fill_color="#1f3c6b", font_color="white", align="left"),
            cells=dict(
                values=[means.index.tolist(),
                        [f"{v:.4f}" for v in means["Pre"]],
                        [f"{v:.4f}" for v in means["Post"]],
                        [f"{v:+.4f}" for v in means["Δ"]]],
                fill_color="lavender", align="left",
            ),
        ))
        fig_secondary.update_layout(title="2×2 Means Table", height=200)

        # ── Executive summary ─────────────────────────────────────────────────
        direction = "reduced" if est < 0 else "increased"
        sig_txt   = "statistically significant at 5%" if pval < 0.05 else "not statistically significant"
        summary = (
            f"CCPA {direction} the {self.outcome.replace('_',' ')} in {self.treatment_state} "
            f"by {abs(est * 100):.2f} percentage points relative to control states "
            f"(ATT = {est:+.4f}, SE = {se:.4f}, p = {pval:.4f}). "
            f"The effect is {sig_txt}. "
            f"HC3-robust standard errors account for heteroskedasticity in loan-level panel data."
        )

        return ScenarioResult(
            scenario_name     = self.name,

            effect_label      = f"CCPA ATT — {self.outcome}",
            primary_estimate  = est,
            primary_se        = se,
            primary_pval      = pval,
            primary_ci        = ci,
            executive_summary = summary,
            methodology_note  = (
                "Standard 2×2 DiD with state and macro controls (unemployment rate, HPI, "
                "30yr mortgage rate). HC3-robust standard errors. Treatment: California "
                f"post-{self.post_years[0]}. Control: {', '.join(self.control_states)}."
            ),
            fig_primary       = fig_primary,
            fig_secondary     = fig_secondary,
            results_df        = means.reset_index(),
        )
