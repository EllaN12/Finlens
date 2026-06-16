"""
scenarios/base.py — Abstract base class and shared dataclass for FinLens scenarios.

Every concrete scenario must:
  1. Inherit from ScenarioRunner
  2. Implement the abstract property: name
  3. Implement the abstract method: run() → ScenarioResult

ScenarioResult is the single shared output contract consumed by
the Streamlit UI and the pytest integration tests.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Optional, List, Tuple

import numpy  as np
import pandas as pd

try:
    from config import cfg as _cfg
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from config import cfg as _cfg

try:
    import plotly.graph_objects as go
    _PLOTLY = True
except ImportError:
    _PLOTLY = False


# ════════════════════════════════════════════════════════════════════
# Output contract
# ════════════════════════════════════════════════════════════════════

@dataclass
class ScenarioResult:
    """
    Standardised output returned by every ScenarioRunner.run() call.

    Primary statistics
    ------------------
    scenario_name     : short machine-readable key  ("S1_2x2_DiD", etc.)
    effect_label      : what the primary_estimate measures ("CCPA ΔApproval Rate")
    primary_estimate  : point estimate (e.g. DiD ATT in percentage points)
    primary_se        : heteroskedasticity-robust standard error
    primary_pval      : two-tailed p-value
    primary_ci        : (lower, upper) 95 % confidence interval tuple

    Narrative fields
    ----------------
    executive_summary : 2-3 sentence plain-English conclusion
    methodology_note  : brief description of the estimator pipeline

    Visual outputs
    --------------
    fig_primary       : primary Plotly Figure (DiD/event study/synthetic control)
    fig_secondary     : secondary Plotly Figure (heterogeneity / estimates table)
    fig_tertiary      : optional third figure (CausalForest violin, Bayesian posterior)

    Tabular output
    --------------
    results_df        : tidy DataFrame of all coefficient/statistic rows
    """
    # ── Identifiers ────────────────────────────────────────────────
    scenario_name  : str = ""
    effect_label   : str = ""

    # ── Primary statistics ─────────────────────────────────────────
    primary_estimate: float = float("nan")
    primary_se      : float = float("nan")
    primary_pval    : float = float("nan")
    primary_ci      : Tuple[float, float] = (float("nan"), float("nan"))

    # ── Narrative ──────────────────────────────────────────────────
    executive_summary : str = ""
    methodology_note  : str = ""
    # ── Figures ────────────────────────────────────────────────────
    fig_primary   : Optional[object] = None   # go.Figure or None
    fig_secondary : Optional[object] = None
    fig_tertiary  : Optional[object] = None

    # ── Tabular ────────────────────────────────────────────────────
    results_df: pd.DataFrame = field(default_factory=pd.DataFrame)


# ════════════════════════════════════════════════════════════════════
# Abstract base runner
# ════════════════════════════════════════════════════════════════════

class ScenarioRunner(abc.ABC):
    """
    Abstract base for FinLens scenario runners.

    Parameters
    ----------
    df              : mart_regulatory_cohort DataFrame (real or synthetic)
    treatment_state : state code for the treated unit      (default "CA")
    control_states  : list of donor/control state codes
    pre_years       : (first_pre_year, last_pre_year) inclusive
    post_years      : (first_post_year, last_post_year) inclusive
    outcome         : column name of the outcome variable
    """

    def __init__(
        self,
        df              : pd.DataFrame,
        treatment_state : str             = "CA",
        control_states  : List[str]       = None,
        pre_years       : Tuple[int, int] = (2018, 2019),
        post_years      : Tuple[int, int] = (2020, 2021),
        outcome         : str             = "approval_rate",
    ):
        self.df              = df.copy()
        self.treatment_state = treatment_state
        self.control_states  = control_states or list(_cfg.default_control_states)
        self.pre_years       = pre_years
        self.post_years      = post_years
        self.outcome         = outcome

        # Validate that the outcome column exists
        if outcome not in self.df.columns:
            raise ValueError(
                f"Outcome column '{outcome}' not found in DataFrame. "
                f"Available columns: {list(self.df.columns)}"
            )

    # ── Abstract interface ─────────────────────────────────────────

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Short machine-readable scenario name, e.g. 'S1_2x2_DiD'."""

    @abc.abstractmethod
    def run(self) -> ScenarioResult:
        """Execute all estimation steps and return a ScenarioResult."""

    # ── Shared helpers ─────────────────────────────────────────────

    def _filter(self) -> pd.DataFrame:
        """
        Return rows for treatment + control states, aggregated to
        state × year (mean of numeric columns within each cell).
        """
        keep_states = [self.treatment_state] + self.control_states
        sub = self.df[self.df["state_code"].isin(keep_states)].copy()

        # Build treatment indicators from the filtered subset
        sub["is_treated_unit"] = (sub["state_code"] == self.treatment_state).astype(int)
        sub["is_post"]         = sub["activity_year"].between(
            self.post_years[0], self.post_years[1]
        ).astype(int)
        sub["did_interaction"]  = sub["is_treated_unit"] * sub["is_post"]

        return sub

    def _panel(self) -> pd.DataFrame:
        """
        Collapse filtered data to a balanced state × year panel
        by taking the (weighted) mean of the outcome and covariates.
        """
        sub = self._filter()
        all_years = list(range(self.pre_years[0], self.post_years[1] + 1))
        sub = sub[sub["activity_year"].isin(all_years)]

        groupby_keys = ["state_code", "activity_year"]
        numeric_cols = [
            c for c in sub.select_dtypes(include=[np.number]).columns.tolist()
            if c not in groupby_keys
        ]
        panel = (
            sub.groupby(groupby_keys)[numeric_cols]
            .mean()
            .reset_index()
        )

        # Re-derive binary flags on the collapsed panel
        panel["is_treated_unit"] = (panel["state_code"] == self.treatment_state).astype(int)
        panel["is_post"]         = panel["activity_year"].between(
            self.post_years[0], self.post_years[1]
        ).astype(int)
        panel["did_interaction"] = panel["is_treated_unit"] * panel["is_post"]

        return panel

    @staticmethod
    def _blank_figure(title: str = "") -> "go.Figure":
        """Return an empty Plotly figure with a centred annotation."""
        if not _PLOTLY:
            raise ImportError("plotly is required for figure generation")
        fig = go.Figure()
        fig.update_layout(
            title_text=title,
            annotations=[dict(
                text="No data available",
                xref="paper", yref="paper",
                x=0.5, y=0.5, showarrow=False,
                font=dict(size=14),
            )],
        )
        return fig
