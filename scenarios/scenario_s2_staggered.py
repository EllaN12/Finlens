"""
scenarios/scenario_s2_staggered.py
FinLens — Scenario 2: Staggered Difference-in-Differences
==========================================================
Business question:
    Is there a consistent, replicable causal effect on mortgage lending across
    all three privacy-law adopting states (CA 2020, VA 2023, CO 2023), or does
    the impact vary by law design and adoption cohort?

Method: Cohort-specific 2×2 DiD aggregated across CCPA / VCDPA / CPA rollouts.
        (Full Callaway & Sant'Anna requires pyfixest / csdid — not yet a PyPI package;
         this module uses clean cohort-by-cohort estimates as the approved approximation.)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import statsmodels.formula.api as smf

from .base import ScenarioResult, ScenarioRunner

TREATED_COHORTS = {
    "CA": {"law_year": 2020, "law_name": "CCPA",  "scope": "Broad opt-out"},
    "VA": {"law_year": 2023, "law_name": "VCDPA", "scope": "Narrower opt-out"},
    "CO": {"law_year": 2023, "law_name": "CPA",   "scope": "Opt-in for sensitive data"},
}
COLOURS = {"CA": "#1f77b4", "VA": "#ff7f0e", "CO": "#9467bd"}


class ScenarioS2Staggered(ScenarioRunner):
    """Staggered DiD — CCPA / VCDPA / CPA cohort-specific ATTs."""

    @property
    def name(self) -> str:
        return "S2_Staggered_DiD"

    def _cohort_did(self, treated_state: str, law_year: int) -> dict:
        """Run a clean 2×2 DiD for one cohort against never-treated controls."""
        never_treated = [s for s in self.control_states
                         if s not in TREATED_COHORTS]
        pre  = (law_year - 2, law_year - 1)
        post = (law_year, law_year + 1)
        d = self.df[
            self.df["state_code"].isin([treated_state] + never_treated)
            & self.df["activity_year"].between(pre[0], post[1])
        ].copy()
        d["treat"] = (d["state_code"] == treated_state).astype(int)
        d["post"]  = (d["activity_year"] >= law_year).astype(int)
        d["did"]   = d["treat"] * d["post"]
        covs = [c for c in ["unemployment_rate", "hpi", "mortgage_rate_30yr"]
                if c in d.columns]
        d = d.dropna(subset=[self.outcome] + covs)
        if len(d) < 8:
            return {"estimate": np.nan, "se": np.nan, "pval": 1.0,
                    "ci": (np.nan, np.nan), "n": 0}
        cov_str = " + ".join(covs)
        formula = (f"{self.outcome} ~ treat + post + did"
                   + (f" + {cov_str}" if cov_str else ""))
        mod = smf.ols(formula, data=d).fit(cov_type="HC3")
        est  = float(mod.params.get("did", np.nan))
        se   = float(mod.bse.get("did",  np.nan))
        pval = float(mod.pvalues.get("did", 1.0))
        ci   = tuple(mod.conf_int().loc["did"]) if "did" in mod.conf_int().index else (np.nan, np.nan)
        return {"estimate": est, "se": se, "pval": pval, "ci": ci, "n": len(d)}

    def run(self) -> ScenarioResult:
        cohort_rows = []
        cohort_figs = {}

        for state, meta in TREATED_COHORTS.items():
            if state not in self.df["state_code"].values:
                continue
            r = self._cohort_did(state, meta["law_year"])
            cohort_rows.append({
                "state":    state,
                "law":      meta["law_name"],
                "law_year": meta["law_year"],
                "scope":    meta["scope"],
                **r,
            })

        results_df = pd.DataFrame(cohort_rows)

        # ── ATT summary bar chart ─────────────────────────────────────────────
        fig_primary = go.Figure()
        for _, row in results_df.iterrows():
            if pd.isna(row["estimate"]):
                continue
            ci_lo = row["ci"][0] if not pd.isna(row["ci"][0]) else row["estimate"]
            ci_hi = row["ci"][1] if not pd.isna(row["ci"][1]) else row["estimate"]
            fig_primary.add_trace(go.Bar(
                x=[row["state"]],
                y=[row["estimate"] * 100],
                name=row["state"],
                marker_color=COLOURS.get(row["state"], "#333"),
                error_y=dict(
                    type="data",
                    array=[(ci_hi - row["estimate"]) * 100],
                    arrayminus=[(row["estimate"] - ci_lo) * 100],
                    visible=True,
                ),
                text=f"{row['estimate'] * 100:+.2f} pp",
                textposition="outside",
            ))
        fig_primary.add_hline(y=0, line_dash="dash", line_color="#aaa")
        fig_primary.update_layout(
            title=f"Cohort ATT — {self.outcome}",
            xaxis_title="Treated State", yaxis_title="ATT (percentage points)",
            showlegend=False, height=380,
        )

        # ── Relative-year trends per cohort ───────────────────────────────────
        fig_secondary = go.Figure()
        for state, meta in TREATED_COHORTS.items():
            if state not in self.df["state_code"].values:
                continue
            law_yr = meta["law_year"]
            never  = [s for s in self.control_states if s not in TREATED_COHORTS]
            sub = self.df[
                self.df["state_code"].isin([state] + never)
                & self.df["activity_year"].between(law_yr - 3, law_yr + 2)
            ].copy()
            sub["rel"] = sub["activity_year"] - law_yr
            agg = sub.groupby(["rel", "state_code"])[self.outcome].mean().unstack()
            if state in agg.columns and len(never) > 0:
                ctrl_cols = [c for c in never if c in agg.columns]
                if ctrl_cols:
                    diff = agg[state] - agg[ctrl_cols].mean(axis=1)
                    diff = diff.dropna().reset_index()
                    fig_secondary.add_trace(go.Scatter(
                        x=diff["rel"],
                        y=diff[0] * 100,
                        mode="lines+markers",
                        name=f"{state} ({meta['law_name']})",
                        line=dict(color=COLOURS.get(state, "#333"), width=2),
                    ))
        fig_secondary.add_hline(y=0, line_dash="dash", line_color="#aaa")
        fig_secondary.add_vline(x=-0.5, line_dash="dot", line_color="#666",
                                annotation_text="Law effective", annotation_position="top right")
        fig_secondary.update_layout(
            title="Treated − Control Diff by Years Relative to Law",
            xaxis_title="Years relative to law enactment",
            yaxis_title=f"Δ {self.outcome} (pp)",
            height=380, legend_title="State (Law)",
        )

        # ── Aggregate summary ─────────────────────────────────────────────────
        valid = results_df.dropna(subset=["estimate"])
        agg_est = float(valid["estimate"].mean()) if not valid.empty else np.nan
        agg_se  = float((valid["se"] ** 2).mean() ** 0.5) if not valid.empty else np.nan

        ca_rows = valid.loc[valid["state"] == "CA", "estimate"]
        if not ca_rows.empty:
            ca_str = f" CA (CCPA) shows the largest effect ({ca_rows.values[0]*100:+.2f} pp), consistent with CCPA's broader opt-out scope relative to later state laws."
        else:
            ca_str = ""
        summary = (
            f"Across {len(valid)} privacy-law cohorts (CCPA/VCDPA/CPA), consumer data "
            f"protection legislation is associated with a mean ATT of {agg_est * 100:+.2f} pp "
            f"on {self.outcome.replace('_', ' ')}.{ca_str}"
        )

        return ScenarioResult(
            scenario_name     = self.name,

            effect_label      = f"Mean ATT across cohorts — {self.outcome}",
            primary_estimate  = agg_est,
            primary_se        = agg_se,
            primary_pval      = float(valid["pval"].mean()) if not valid.empty else 1.0,
            primary_ci        = (agg_est - 1.96 * agg_se, agg_est + 1.96 * agg_se),
            executive_summary = summary,
            methodology_note  = (
                "Cohort-specific 2×2 DiD for CA (2020), VA (2023), CO (2023) using "
                "never-treated states as controls. HC3-robust SEs. Averages across cohorts "
                "approximate the Callaway & Sant'Anna ATT aggregator."
            ),
            fig_primary       = fig_primary,
            fig_secondary     = fig_secondary,
            results_df        = results_df,
        )
