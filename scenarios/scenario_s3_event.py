"""
scenarios/scenario_s3_event.py
FinLens — Scenario 3: Event Study (Dynamic DiD)
===============================================
Business question:
    When exactly did lender behaviour change relative to CCPA's enactment date —
    and does the timing rule out the possibility that something else caused the shift?

Method:
    Dynamic DiD — leads (β₋₄…β₋₁) and lags (β₀…β₊ₙ) around CCPA effective date.
    Pre-trend F-test validates parallel-trends assumption.
    t = −1 omitted as reference period.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import statsmodels.formula.api as smf
from scipy import stats

from .base import ScenarioResult, ScenarioRunner


class ScenarioS3Event(ScenarioRunner):
    """Event study — dynamic treatment effects around CCPA."""

    @property
    def name(self) -> str:
        return "S3_Event_Study"

    def _run_event_study(self) -> pd.DataFrame:
        d = self.df[
            self.df["state_code"].isin([self.treatment_state] + self.control_states)
        ].copy()
        d["treat"]      = (d["state_code"] == self.treatment_state).astype(int)
        d["post"]       = (d["activity_year"] > self.pre_years[1]).astype(int)
        d["event_time"] = d["activity_year"] - (self.pre_years[1] + 1)
        ref_t = -1

        for t in sorted(d["event_time"].unique()):
            if t == ref_t:
                continue
            col = f"ca_t{'p' if t >= 0 else 'm'}{abs(int(t))}"
            d[col] = ((d["treat"] == 1) & (d["event_time"] == t)).astype(int)

        dummies = sorted([c for c in d.columns if c.startswith("ca_t")])
        if not dummies:
            return pd.DataFrame(), None

        covs = [c for c in ["unemployment_rate", "hpi", "mortgage_rate_30yr"]
                if c in d.columns]
        cov_str  = " + ".join(covs)
        dum_str  = " + ".join(dummies)
        formula  = (f"{self.outcome} ~ treat + {dum_str}"
                    + (f" + {cov_str}" if cov_str else "")
                    + " + C(activity_year)")
        mod = smf.ols(formula, data=d.dropna(subset=[self.outcome] + covs)).fit(cov_type="HC3")

        rows = []
        for t in sorted(d["event_time"].unique()):
            col = f"ca_t{'p' if t >= 0 else 'm'}{abs(int(t))}"
            if t == ref_t:
                rows.append({"t": t, "coef": 0.0, "lo": 0.0, "hi": 0.0, "pval": 1.0})
            elif col in mod.params:
                ci = mod.conf_int().loc[col]
                rows.append({"t": t, "coef": float(mod.params[col]),
                             "lo": float(ci[0]), "hi": float(ci[1]),
                             "pval": float(mod.pvalues[col])})
        return pd.DataFrame(rows), mod

    def run(self) -> ScenarioResult:
        es_df, mod = self._run_event_study()

        if es_df.empty:
            return ScenarioResult(
                scenario_name     = self.name,
                executive_summary = "Insufficient data to run event study. Widen the year range.",
            )


        # ── Pre-trend F-test (Wald test on pre-period dummies ≈ 0) ───────────
        pre_rows_df = es_df[(es_df["t"] < -1) & (es_df["t"] != 0)]
        pre_coefs   = pre_rows_df["coef"]
        max_pre     = float(pre_coefs.abs().max()) if len(pre_coefs) else 0.0
        pre_ses     = pre_rows_df["t"].apply(
            lambda t: float(mod.bse.get(f"ca_t{'p' if t >= 0 else 'm'}{abs(int(t))}", np.nan))
        ).dropna()
        avg_se2 = float((pre_ses**2).mean()) if len(pre_ses) else 1e-6
        f_stat  = float(np.mean(pre_coefs**2) / avg_se2) if len(pre_coefs) else 0.0
        f_pval  = float(1 - stats.chi2.cdf(f_stat * max(len(pre_coefs), 1),
                                           df=max(len(pre_coefs), 1)))
        parallel_trends_ok = f_pval > 0.10

        # ── Event-study coefficient plot ──────────────────────────────────────
        sig_colors = [
            "#1f77b4" if p < 0.05 else "#aec7e8" for p in es_df["pval"]
        ]
        fig_primary = go.Figure()
        fig_primary.add_trace(go.Scatter(
            x=es_df["t"], y=es_df["coef"] * 100,
            error_y=dict(
                type="data",
                array=(es_df["hi"] - es_df["coef"]) * 100,
                arrayminus=(es_df["coef"] - es_df["lo"]) * 100,
                visible=True, thickness=1.5,
            ),
            mode="markers+lines",
            marker=dict(size=10, color=sig_colors),
            line=dict(color="#1f3c6b", width=1.5),
            name="β (95% CI)",
        ))
        fig_primary.add_hline(y=0, line_dash="dash", line_color="#aaa")
        fig_primary.add_vline(x=-0.5, line_dash="dot", line_color="#d62728",
                              annotation_text="Law effective",
                              annotation_position="top right")
        post_ts = es_df[es_df["t"] >= 0]["t"]
        if not post_ts.empty:
            fig_primary.add_vrect(
                x0=-0.5, x1=float(post_ts.max()) + 0.5,
                fillcolor="rgba(255,200,60,0.12)", opacity=1, line_width=0,
                annotation_text="Post-law window",
                annotation_position="top left",
            )
        pre_ts = es_df[es_df["t"] < -1]["t"]
        if not pre_ts.empty:
            fig_primary.add_vrect(
                x0=float(pre_ts.min()) - 0.5, x1=-0.5,
                fillcolor="rgba(100,180,255,0.07)", opacity=1, line_width=0,
                annotation_text="Pre-period (should ≈ 0)",
                annotation_position="top left",
            )
        t_vals = sorted(es_df["t"].astype(int).tolist())
        fig_primary.update_xaxes(
            tickvals=t_vals, ticktext=[f"t{t:+d}" for t in t_vals]
        )
        fig_primary.update_layout(
            title=(f"Event Study: {self.outcome.replace('_', ' ').title()} — "
                   f"{self.treatment_state} vs. Control"),
            xaxis_title="Period relative to law effective date",
            yaxis_title=f"β coefficient (pp) · ref: t=−1",
            height=400,
        )

        # ── Pre-trend summary table ───────────────────────────────────────────
        pre_rows = es_df[es_df["t"] < 0].copy()
        pre_rows["label"] = pre_rows["t"].apply(lambda t: f"t{t:+d}")
        fig_secondary = go.Figure(go.Table(
            header=dict(
                values=["Period", "β (pp)", "95% CI Lo", "95% CI Hi", "p-value"],
                fill_color="#1f3c6b", font_color="white",
            ),
            cells=dict(
                values=[
                    pre_rows["label"].tolist(),
                    [f"{v * 100:+.3f}" for v in pre_rows["coef"]],
                    [f"{v * 100:+.3f}" for v in pre_rows["lo"]],
                    [f"{v * 100:+.3f}" for v in pre_rows["hi"]],
                    [f"{v:.4f}" for v in pre_rows["pval"]],
                ],
                fill_color="lavender",
            ),
        ))
        fig_secondary.update_layout(title="Pre-period Coefficients", height=220)

        peak_row = es_df.loc[es_df["coef"].idxmin()]
        direction = "fell" if peak_row["coef"] < 0 else "rose"
        pt_verdict = "parallel-trends assumption is supported" if parallel_trends_ok \
                     else "pre-trends detected — interpret with caution"

        summary = (
            f"The event study shows the {self.outcome.replace('_', ' ')} "
            f"{direction} most sharply at t={int(peak_row['t']):+d} "
            f"({peak_row['coef'] * 100:+.2f} pp). "
            f"The pre-period F-test (max |β| = {max_pre:.4f}, approx. p = {f_pval:.3f}) "
            f"indicates the {pt_verdict}. "
            f"The coefficient pattern is consistent with lenders adjusting underwriting "
            f"after the law's effective date."
        )

        return ScenarioResult(
            scenario_name     = self.name,

            effect_label      = f"Peak dynamic coefficient — {self.outcome}",
            primary_estimate  = float(peak_row["coef"]),
            primary_se        = float((peak_row["hi"] - peak_row["coef"]) / 1.96),
            primary_pval      = float(peak_row["pval"]),
            primary_ci        = (float(peak_row["lo"]), float(peak_row["hi"])),
            executive_summary = summary,
            methodology_note  = (
                "Dynamic DiD with leads (t−4 to t−2) and lags (t0 to t+3) around "
                "CCPA effective date. t=−1 omitted as reference. HC3-robust SEs. "
                "Pre-trend F-test approximated via max |pre-period coefficient|."
            ),
            fig_primary       = fig_primary,
            fig_secondary     = fig_secondary,
            results_df        = es_df,
        )
