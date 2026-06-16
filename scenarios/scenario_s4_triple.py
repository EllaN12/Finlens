"""
scenarios/scenario_s4_triple.py
FinLens — Scenario 4: Triple Difference-in-Differences (DiDiD)
===============================================================
Business question:
    Did CCPA specifically harm owner-occupied applicants — who are CCPA-covered
    natural persons — more than investor borrowers who are typically LLCs or
    entities outside the law's personal-data scope?

Method:
    DiDiD = (CA − Control) × (Owner-Occ − Investor) × (Post − Pre)
    Investor loans within CA act as a within-treated-state placebo.
    A significant DiDiD coefficient isolates CCPA's data-restriction mechanism.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import statsmodels.formula.api as smf

from .base import ScenarioResult, ScenarioRunner


class ScenarioS4TripleDiD(ScenarioRunner):
    """Triple DiD — investor vs. owner-occupied, CA vs. control."""

    @property
    def name(self) -> str:
        return "S4_Triple_DiD"

    def run(self) -> ScenarioResult:
        d = self.df[
            self.df["state_code"].isin([self.treatment_state] + self.control_states)
            & self.df["activity_year"].between(self.pre_years[0], self.post_years[1])
        ].copy()

        # Derive occupancy flag
        if "occupancy_type" in d.columns:
            d["is_owner_occ"] = (d["occupancy_type"] == 1).astype(int)
        elif "is_investor_loan" in d.columns:
            d["is_owner_occ"] = (1 - d["is_investor_loan"]).astype(int)
        else:
            d["is_owner_occ"] = 1   # fallback — all treated as owner-occ

        d["treat"]  = (d["state_code"] == self.treatment_state).astype(int)
        d["post"]   = (d["activity_year"] > self.pre_years[1]).astype(int)
        d["owner"]  = d["is_owner_occ"]
        d["didid"]  = d["treat"] * d["post"] * d["owner"]
        d["did_t"]  = d["treat"] * d["post"]
        d["did_o"]  = d["treat"] * d["owner"]
        d["post_o"] = d["post"]   * d["owner"]

        covs = [c for c in ["unemployment_rate", "hpi", "mortgage_rate_30yr"]
                if c in d.columns]
        d = d.dropna(subset=[self.outcome] + covs)

        if len(d) < 15:
            return ScenarioResult(
                scenario_name     = self.name,
                executive_summary = "Insufficient data for Triple DiD. Check occupancy_type column.",
            )

        cov_str = " + ".join(covs)
        formula  = (f"{self.outcome} ~ treat + post + owner + "
                    f"did_t + did_o + post_o + didid"
                    + (f" + {cov_str}" if cov_str else "")
                    + " + C(state_code)")
        mod = smf.ols(formula, data=d).fit(cov_type="HC3")

        est  = float(mod.params.get("didid", np.nan))
        se   = float(mod.bse.get("didid",  np.nan))
        pval = float(mod.pvalues.get("didid", 1.0))
        ci   = tuple(mod.conf_int().loc["didid"]) if "didid" in mod.conf_int().index else (np.nan, np.nan)

        # ── Group means for bar chart ─────────────────────────────────────────
        d["state_group"] = d["state_code"].apply(
            lambda s: f"{self.treatment_state} (treated)" if s == self.treatment_state else "Control")
        d["period_label"] = d["activity_year"].apply(
            lambda y: "Pre" if y <= self.pre_years[1] else "Post")
        d["occ_label"] = d["owner"].map({1: "Owner-Occupied", 0: "Investor"})

        agg = (d.groupby(["state_group", "occ_label", "period_label"])[self.outcome]
                 .mean().reset_index())

        fig_primary = go.Figure()
        bar_colours = {"Pre": "#7f7f7f", "Post": "#1f77b4"}
        for period, grp in agg.groupby("period_label"):
            fig_primary.add_trace(go.Bar(
                x=[f"{row['state_group']} | {row['occ_label']}"
                   for _, row in grp.iterrows()],
                y=grp[self.outcome] * 100,
                name=period,
                marker_color=bar_colours[period],
                text=[f"{v * 100:.1f}%" for v in grp[self.outcome]],
                textposition="outside",
            ))
        fig_primary.update_layout(
            barmode="group",
            title=f"Triple DiD — {self.outcome.replace('_', ' ').title()} by Group",
            xaxis_title="State × Occupancy Type",
            yaxis_title=f"{self.outcome.replace('_', ' ').title()} (%)",
            height=400, legend_title="Period",
        )

        # ── Decomposition table ───────────────────────────────────────────────
        def _mean(sg, ol, pl):
            row = agg[(agg.state_group == sg) & (agg.occ_label == ol) & (agg.period_label == pl)]
            return float(row[self.outcome].values[0]) if not row.empty else np.nan

        sg_t = f"{self.treatment_state} (treated)"
        decomp = pd.DataFrame({
            "Comparison": [
                "CA Owner-Occ (Post − Pre)",
                "CA Investor (Post − Pre)",
                "Control Owner-Occ (Post − Pre)",
                "Control Investor (Post − Pre)",
                "DiD (Owner-Occ): CA vs. Control",
                "DiD (Investor): CA vs. Control",
                "DiDiD (mechanism estimate)",
            ],
            "Value (pp)": [
                (_mean(sg_t, "Owner-Occupied", "Post") - _mean(sg_t, "Owner-Occupied", "Pre")) * 100,
                (_mean(sg_t, "Investor", "Post")        - _mean(sg_t, "Investor", "Pre")) * 100,
                (_mean("Control", "Owner-Occupied", "Post") - _mean("Control", "Owner-Occupied", "Pre")) * 100,
                (_mean("Control", "Investor", "Post")       - _mean("Control", "Investor", "Pre")) * 100,
                np.nan,  # filled below
                np.nan,
                est * 100,
            ],
        })
        oo_ca_ctrl  = decomp.iloc[0]["Value (pp)"] - decomp.iloc[2]["Value (pp)"]
        inv_ca_ctrl = decomp.iloc[1]["Value (pp)"] - decomp.iloc[3]["Value (pp)"]
        decomp.at[4, "Value (pp)"] = oo_ca_ctrl
        decomp.at[5, "Value (pp)"] = inv_ca_ctrl

        fig_secondary = go.Figure(go.Table(
            header=dict(values=["Comparison", "Value (pp)"],
                        fill_color="#1f3c6b", font_color="white", align="left"),
            cells=dict(
                values=[decomp["Comparison"].tolist(),
                        [f"{v:+.3f}" if not np.isnan(v) else "—"
                         for v in decomp["Value (pp)"].tolist()]],
                fill_color="lavender", align="left",
            ),
        ))
        fig_secondary.update_layout(title="DiDiD Decomposition", height=280)

        direction = "reduced" if est < 0 else "increased"
        owner_gap = abs(oo_ca_ctrl - inv_ca_ctrl)
        summary = (
            f"The Triple DiD coefficient (DiDiD = {est * 100:+.2f} pp, SE={se * 100:.2f}, "
            f"p={pval:.4f}) shows that CCPA {direction} {self.outcome.replace('_', ' ')} "
            f"for owner-occupied borrowers by {abs(est) * 100:.2f} pp more than for investor "
            f"borrowers in {self.treatment_state} relative to controls. "
            f"The {owner_gap:.2f} pp gap between owner-occ and investor reactions is "
            f"consistent with CCPA's data-restriction mechanism targeting natural persons "
            f"rather than LLC/entity borrowers."
        )

        return ScenarioResult(
            scenario_name     = self.name,

            effect_label      = f"DiDiD — Owner-Occ vs. Investor in {self.treatment_state} vs. Control",
            primary_estimate  = est,
            primary_se        = se,
            primary_pval      = pval,
            primary_ci        = ci,
            executive_summary = summary,
            methodology_note  = (
                "Triple DiD (DiDiD) regression with treat × post × owner-occ interaction. "
                "Investor loans within CA serve as within-treated-state placebo. "
                "HC3-robust SEs. Occupancy derived from occupancy_type (1=owner, 2=investor)."
            ),
            fig_primary       = fig_primary,
            fig_secondary     = fig_secondary,
            results_df        = decomp,
        )
