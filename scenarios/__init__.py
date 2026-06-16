"""
scenarios/__init__.py — FinLens Causal Inference Scenario Framework

Five privacy-law impact scenarios:

    ScenarioS1DiD        Standard 2x2 DiD  — CCPA vs. TX/FL/OH (HC3-robust OLS)
    ScenarioS2Staggered  Staggered DiD     — CCPA / VCDPA / CPA cohort ATTs
    ScenarioS3Event      Event Study       — dynamic coefficients + pre-trend F-test
    ScenarioS4TripleDiD  Triple DiD        — investor vs. owner-occ x CA vs. control
    ScenarioS5HTE        HTE / CausalForest — income tier CATE (+ optional EconML)

Quick start:
    from scenarios.runner import run_scenario
    result = run_scenario("S1 — Standard 2x2 DiD (CCPA vs. Control)", df)
"""

from .base                  import ScenarioResult, ScenarioRunner       # noqa: F401
from .scenario_s1_did       import ScenarioS1DiD                        # noqa: F401
from .scenario_s2_staggered import ScenarioS2Staggered                  # noqa: F401
from .scenario_s3_event     import ScenarioS3Event                      # noqa: F401
from .scenario_s4_triple    import ScenarioS4TripleDiD                  # noqa: F401
from .scenario_s5_hte       import ScenarioS5HTE                        # noqa: F401
from .runner                import run_scenario, run_scenario_by_number, SCENARIO_MAP  # noqa: F401

__all__ = [
    "ScenarioResult",
    "ScenarioRunner",
    "ScenarioS1DiD",
    "ScenarioS2Staggered",
    "ScenarioS3Event",
    "ScenarioS4TripleDiD",
    "ScenarioS5HTE",
    "run_scenario",
    "run_scenario_by_number",
    "SCENARIO_MAP",
]
