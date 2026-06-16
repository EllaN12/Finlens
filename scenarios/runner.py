"""
scenarios/runner.py — Unified scenario dispatcher for FinLens.

Five privacy-law impact scenarios:

    Scenario 1  S1_2x2_DiD          Standard 2×2 DiD (CCPA vs. TX/FL/OH, HC3-robust OLS)
    Scenario 2  S2_Staggered_DiD    Staggered DiD (CA/VA/CO cohort ATTs)
    Scenario 3  S3_Event_Study      Event study (dynamic β + pre-trend F-test)
    Scenario 4  S4_Triple_DiD       Triple DiD (owner-occ vs. investor × CA vs. control)
    Scenario 5  S5_HTE_CausalForest Heterogeneous treatment effects by income tier

Usage
-----
    from scenarios.runner import run_scenario, SCENARIO_MAP

    result = run_scenario(
        "S1 — Standard 2×2 DiD (CCPA vs. Control)",
        df,
        treatment_state="CA",
        control_states=["TX","FL","OH"],
        pre_years=(2018, 2019),
        post_years=(2020, 2021),
        outcome="approval_rate",
    )

SCENARIO_MAP keys match the Streamlit radio labels in app/finlens_app.py.
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

import pandas as pd

from .base                  import ScenarioResult
from .scenario_s1_did       import ScenarioS1DiD
from .scenario_s2_staggered import ScenarioS2Staggered
from .scenario_s3_event     import ScenarioS3Event
from .scenario_s4_triple    import ScenarioS4TripleDiD
from .scenario_s5_hte       import ScenarioS5HTE


# ── Registry: display label → runner class ───────────────────────────────────

SCENARIO_MAP: dict[str, type] = {
    "S1 — Standard 2×2 DiD (CCPA vs. Control)":        ScenarioS1DiD,
    "S2 — Multi-State Staggered DiD (CCPA/VCDPA/CPA)": ScenarioS2Staggered,
    "S3 — Event Study (Dynamic Coefficients)":          ScenarioS3Event,
    "S4 — Triple DiD (Investor vs. Owner-Occ)":         ScenarioS4TripleDiD,
    "S5 — Income Tier HTE (CausalForest)":              ScenarioS5HTE,
}

# Numeric key → label (matches Streamlit sidebar SCENARIO_LABELS dict)
SCENARIO_KEY_BY_NUMBER: dict[int, str] = {
    i + 1: k for i, k in enumerate(SCENARIO_MAP)
}


# ── Dispatch helper ───────────────────────────────────────────────────────────

def run_scenario(
    scenario_key    : str,
    df              : pd.DataFrame,
    treatment_state : str                  = "CA",
    control_states  : Optional[List[str]] = None,
    pre_years       : Tuple[int, int]      = (2018, 2019),
    post_years      : Tuple[int, int]      = (2020, 2021),
    outcome         : str                  = "approval_rate",
    **kwargs        : Any,
) -> ScenarioResult:
    """
    Instantiate the correct ScenarioRunner and call .run().

    Parameters
    ----------
    scenario_key    : one of the keys in SCENARIO_MAP
    df              : mart_regulatory_cohort DataFrame (real or synthetic)
    treatment_state : treated unit state code  (default "CA")
    control_states  : donor/control state codes (default TX, FL, OH, NY, IL)
    pre_years       : (first_pre_year, last_pre_year)   (default 2018-2019)
    post_years      : (first_post_year, last_post_year) (default 2020-2021)
    outcome         : outcome column name               (default "approval_rate")

    Returns
    -------
    ScenarioResult

    Raises
    ------
    KeyError  if scenario_key is not in SCENARIO_MAP
    """
    if scenario_key not in SCENARIO_MAP:
        raise KeyError(
            f"Unknown scenario key: '{scenario_key}'.\n"
            f"Valid keys: {list(SCENARIO_MAP.keys())}"
        )

    runner_cls = SCENARIO_MAP[scenario_key]
    runner = runner_cls(
        df              = df,
        treatment_state = treatment_state,
        control_states  = control_states or ["TX", "FL", "OH", "NY", "IL"],
        pre_years       = pre_years,
        post_years      = post_years,
        outcome         = outcome,
    )
    return runner.run()


def run_scenario_by_number(
    number: int,
    df: pd.DataFrame,
    **kwargs: Any,
) -> ScenarioResult:
    """Convenience wrapper — call by scenario number (1-5)."""
    if number not in SCENARIO_KEY_BY_NUMBER:
        raise KeyError(f"Scenario number must be 1-5, got {number}.")
    return run_scenario(SCENARIO_KEY_BY_NUMBER[number], df, **kwargs)
