"""
test_scenarios.py — Integration tests for the FinLens S1–S5 privacy-law
impact scenario runners and the unified runner dispatcher.

Scenarios under test:
  S1 — Standard 2×2 DiD (CCPA vs. TX/FL/OH baseline, HC3-robust OLS)
  S2 — Multi-state staggered DiD (CCPA / VCDPA / CPA cohorts)
  S3 — Event study (dynamic DiD, pre-trend F-test)
  S4 — Triple DiD (owner-occupied vs. investor within CA vs. control)
  S5 — Heterogeneous treatment effects (income tier stratification + CausalForest)

Test classes:
  1. TestScenarioSmoke          — every scenario runs without exception
  2. TestScenarioResultShape    — ScenarioResult fields present and typed correctly
  3. TestScenarioConsistency    — S1 and S3 recover same-sign estimates
  4. TestScenarioConfigurability — outcomes, control sets, year ranges
  5. TestScenarioFigures        — Plotly figures are valid and have data
  6. TestExecutiveSummary       — narrative mentions key terms + numeric values
  7. TestRunner                 — dispatcher routes to correct class

Run: pytest tests/test_scenarios.py -v
"""
import re
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import numpy as np
import pandas as pd
import plotly.graph_objects as go

try:
    from scenarios.scenario_s1_did       import ScenarioS1DiD
    from scenarios.scenario_s2_staggered import ScenarioS2Staggered
    from scenarios.scenario_s3_event     import ScenarioS3Event
    from scenarios.scenario_s4_triple    import ScenarioS4TripleDiD
    from scenarios.scenario_s5_hte       import ScenarioS5HTE
    from scenarios.runner                import run_scenario, run_scenario_by_number, SCENARIO_MAP
    from scenarios.base                  import ScenarioResult
    SCENARIOS_AVAILABLE = True
except ImportError as _e:
    SCENARIOS_AVAILABLE = False
    _IMPORT_ERR = str(_e)

pytestmark = pytest.mark.skipif(
    not SCENARIOS_AVAILABLE,
    reason=f"scenarios package not importable — ensure finlens root is in PYTHONPATH",
)

# ════════════════════════════════════════════════════════════════════
# Shared defaults
# ════════════════════════════════════════════════════════════════════

DEFAULT_KWARGS = dict(
    treatment_state = "CA",
    control_states  = ["TX", "FL", "OH"],
    pre_years       = (2018, 2019),
    post_years      = (2020, 2021),
    outcome         = "approval_rate",
)

if SCENARIOS_AVAILABLE:
    ALL_SCENARIO_CLASSES = [
        ScenarioS1DiD,
        ScenarioS2Staggered,
        ScenarioS3Event,
        ScenarioS4TripleDiD,
        ScenarioS5HTE,
    ]

    EXPECTED_NAMES = {
        ScenarioS1DiD:        "S1_2x2_DiD",
        ScenarioS2Staggered:  "S2_Staggered_DiD",
        ScenarioS3Event:      "S3_Event_Study",
        ScenarioS4TripleDiD:  "S4_Triple_DiD",
        ScenarioS5HTE:        "S5_HTE_Income_Tier",
    }
else:
    ALL_SCENARIO_CLASSES = []
    EXPECTED_NAMES = {}


# ════════════════════════════════════════════════════════════════════
# 1. Smoke tests — all scenarios complete without exception
# ════════════════════════════════════════════════════════════════════

class TestScenarioSmoke:

    @pytest.mark.parametrize("ScenCls", ALL_SCENARIO_CLASSES,
                             ids=[c.__name__ for c in ALL_SCENARIO_CLASSES])
    def test_scenario_runs(self, regulatory_df, ScenCls):
        runner = ScenCls(df=regulatory_df, **DEFAULT_KWARGS)
        result = runner.run()
        assert result is not None
        assert isinstance(result, ScenarioResult)

    def test_all_scenario_map_keys_run(self, regulatory_df):
        """Every key in SCENARIO_MAP must complete without error."""
        for key in SCENARIO_MAP:
            result = run_scenario(key, regulatory_df, **DEFAULT_KWARGS)
            assert result is not None, f"Scenario '{key}' returned None"

    def test_run_by_number_1_through_5(self, regulatory_df):
        for n in range(1, 6):
            result = run_scenario_by_number(n, regulatory_df, **DEFAULT_KWARGS)
            assert isinstance(result, ScenarioResult), (
                f"run_scenario_by_number({n}) returned {type(result)}"
            )


# ════════════════════════════════════════════════════════════════════
# 2. ScenarioResult shape — required fields, types, ranges
# ════════════════════════════════════════════════════════════════════

class TestScenarioResultShape:

    @pytest.fixture(scope="class",
                    params=ALL_SCENARIO_CLASSES,
                    ids=[c.__name__ for c in ALL_SCENARIO_CLASSES])
    def result(self, request, regulatory_df):
        return request.param(df=regulatory_df, **DEFAULT_KWARGS).run()

    def test_scenario_name_nonempty(self, result):
        assert isinstance(result.scenario_name, str) and len(result.scenario_name) > 0

    def test_effect_label_nonempty(self, result):
        assert isinstance(result.effect_label, str) and len(result.effect_label) > 0

    def test_executive_summary_nonempty(self, result):
        assert isinstance(result.executive_summary, str) and len(result.executive_summary) > 10

    def test_methodology_note_nonempty(self, result):
        assert isinstance(result.methodology_note, str) and len(result.methodology_note) > 10

    def test_primary_estimate_is_finite(self, result):
        assert isinstance(result.primary_estimate, (int, float, np.floating))
        assert np.isfinite(result.primary_estimate), (
            f"primary_estimate is non-finite: {result.primary_estimate}"
        )

    def test_primary_se_positive(self, result):
        assert result.primary_se > 0, f"primary_se must be > 0, got {result.primary_se}"

    def test_pval_in_range(self, result):
        assert 0.0 <= result.primary_pval <= 1.0, (
            f"primary_pval {result.primary_pval} outside [0, 1]"
        )

    def test_ci_is_ordered_tuple(self, result):
        ci = result.primary_ci
        assert isinstance(ci, tuple) and len(ci) == 2
        lo, hi = ci
        assert lo <= hi, f"CI lower {lo} > upper {hi}"

    def test_results_df_is_dataframe(self, result):
        assert isinstance(result.results_df, pd.DataFrame)

    def test_no_position_fields(self, result):
        """Removed fields must not appear on the result object."""
        for banned in ("position_title", "jd_alignment", "jd_keywords"):
            assert not hasattr(result, banned), (
                f"ScenarioResult still has banned field '{banned}'"
            )


# ════════════════════════════════════════════════════════════════════
# 3. Directional consistency — S1 (OLS DiD) vs S3 (event study peak)
# ════════════════════════════════════════════════════════════════════

class TestScenarioConsistency:

    def test_s1_s3_same_sign(self, regulatory_df):
        """
        S1 OLS DiD and S3 event-study peak coefficient measure the same
        underlying effect. With a linear DGP they should share the same sign.
        """
        r1 = ScenarioS1DiD(df=regulatory_df, **DEFAULT_KWARGS).run()
        r3 = ScenarioS3Event(df=regulatory_df, **DEFAULT_KWARGS).run()
        assert np.sign(r1.primary_estimate) == np.sign(r3.primary_estimate), (
            f"S1 ({r1.primary_estimate:.4f}) and S3 ({r3.primary_estimate:.4f}) "
            "have opposite signs — indicates a methodological inconsistency"
        )

    def test_scenario_names_all_distinct(self, regulatory_df):
        names = [
            ScenCls(df=regulatory_df, **DEFAULT_KWARGS).run().scenario_name
            for ScenCls in ALL_SCENARIO_CLASSES
        ]
        assert len(names) == len(set(names)), f"Duplicate scenario_names: {names}"

    def test_expected_scenario_names(self, regulatory_df):
        for ScenCls, expected in EXPECTED_NAMES.items():
            result = ScenCls(df=regulatory_df, **DEFAULT_KWARGS).run()
            assert result.scenario_name == expected, (
                f"{ScenCls.__name__} returned scenario_name='{result.scenario_name}', "
                f"expected '{expected}'"
            )


# ════════════════════════════════════════════════════════════════════
# 4. Configurability
# ════════════════════════════════════════════════════════════════════

class TestScenarioConfigurability:

    @pytest.mark.parametrize("outcome", [
        "approval_rate", "origination_rate", "avg_ltv", "pct_missing_income"
    ])
    def test_s1_different_outcomes(self, regulatory_df, outcome):
        kwargs = {**DEFAULT_KWARGS, "outcome": outcome}
        result = ScenarioS1DiD(df=regulatory_df, **kwargs).run()
        assert np.isfinite(result.primary_estimate), (
            f"S1 non-finite estimate for outcome '{outcome}'"
        )

    @pytest.mark.parametrize("outcome", ["approval_rate", "origination_rate"])
    def test_s5_different_outcomes(self, regulatory_df, outcome):
        kwargs = {**DEFAULT_KWARGS, "outcome": outcome}
        result = ScenarioS5HTE(df=regulatory_df, **kwargs).run()
        assert np.isfinite(result.primary_estimate), (
            f"S5 non-finite estimate for outcome '{outcome}'"
        )

    def test_single_control_state(self, regulatory_df):
        kwargs = {**DEFAULT_KWARGS, "control_states": ["TX"]}
        result = ScenarioS1DiD(df=regulatory_df, **kwargs).run()
        assert np.isfinite(result.primary_estimate)

    def test_extended_post_period(self, regulatory_df):
        kwargs = {**DEFAULT_KWARGS, "post_years": (2020, 2022)}
        result = ScenarioS1DiD(df=regulatory_df, **kwargs).run()
        assert np.isfinite(result.primary_estimate)

    def test_shorter_pre_period(self, regulatory_df):
        kwargs = {**DEFAULT_KWARGS, "pre_years": (2019, 2019)}
        result = ScenarioS1DiD(df=regulatory_df, **kwargs).run()
        assert result is not None

    def test_s4_investor_flag_fallback(self, regulatory_df):
        """S4 should still run when occupancy_type is absent (uses is_investor_loan)."""
        df2 = regulatory_df.drop(columns=["is_investor_loan"], errors="ignore")
        result = ScenarioS4TripleDiD(df=df2, **DEFAULT_KWARGS).run()
        assert result is not None

    def test_s5_missing_income_tier_fallback(self, regulatory_df):
        """S5 should not crash when income_tier column is absent."""
        df2 = regulatory_df.drop(columns=["income_tier"], errors="ignore")
        result = ScenarioS5HTE(df=df2, **DEFAULT_KWARGS).run()
        assert result is not None


# ════════════════════════════════════════════════════════════════════
# 5. Plotly figure validation
# ════════════════════════════════════════════════════════════════════

class TestScenarioFigures:

    @pytest.fixture(scope="class",
                    params=ALL_SCENARIO_CLASSES,
                    ids=[c.__name__ for c in ALL_SCENARIO_CLASSES])
    def result(self, request, regulatory_df):
        return request.param(df=regulatory_df, **DEFAULT_KWARGS).run()

    def test_primary_figure_is_plotly(self, result):
        assert isinstance(result.fig_primary, go.Figure), (
            f"fig_primary is {type(result.fig_primary)}, expected go.Figure"
        )

    def test_primary_figure_has_traces(self, result):
        assert len(result.fig_primary.data) > 0, "fig_primary has no traces"

    def test_primary_figure_has_title(self, result):
        title = result.fig_primary.layout.title.text
        assert title and len(title) > 0, "fig_primary has no layout title"

    def test_secondary_figure_is_plotly(self, result):
        assert isinstance(result.fig_secondary, go.Figure), (
            f"fig_secondary is {type(result.fig_secondary)}, expected go.Figure"
        )

    def test_s5_tertiary_figure_when_econml(self, regulatory_df):
        """If econml is installed, S5 may provide a 3rd figure; if set it must be valid."""
        try:
            import econml  # noqa: F401
        except ImportError:
            pytest.skip("econml not installed")
        result = ScenarioS5HTE(df=regulatory_df, **DEFAULT_KWARGS).run()
        if result.fig_tertiary is not None:
            assert isinstance(result.fig_tertiary, go.Figure)


# ════════════════════════════════════════════════════════════════════
# 6. Executive summary content
# ════════════════════════════════════════════════════════════════════

class TestExecutiveSummary:

    def test_s1_summary_mentions_ccpa(self, regulatory_df):
        result = ScenarioS1DiD(df=regulatory_df, **DEFAULT_KWARGS).run()
        assert "CCPA" in result.executive_summary, (
            "S1 summary should mention CCPA"
        )

    def test_s3_summary_mentions_timing(self, regulatory_df):
        result = ScenarioS3Event(df=regulatory_df, **DEFAULT_KWARGS).run()
        assert any(kw in result.executive_summary.lower()
                   for kw in ["event", "trend", "period", "coefficient", "t+"]), (
            "S3 summary should reference event-study timing"
        )

    def test_s5_summary_mentions_income_tiers(self, regulatory_df):
        result = ScenarioS5HTE(df=regulatory_df, **DEFAULT_KWARGS).run()
        assert any(kw in result.executive_summary.lower()
                   for kw in ["income", "tier", "low", "high", "borrower"]), (
            "S5 summary should mention income tier heterogeneity"
        )

    @pytest.mark.parametrize("ScenCls", ALL_SCENARIO_CLASSES,
                             ids=[c.__name__ for c in ALL_SCENARIO_CLASSES])
    def test_summary_contains_numeric_value(self, regulatory_df, ScenCls):
        result = ScenCls(df=regulatory_df, **DEFAULT_KWARGS).run()
        assert re.search(r"\d+\.\d+", result.executive_summary), (
            f"{ScenCls.__name__} summary has no numeric value: "
            f"'{result.executive_summary[:120]}'"
        )

    @pytest.mark.parametrize("ScenCls", ALL_SCENARIO_CLASSES,
                             ids=[c.__name__ for c in ALL_SCENARIO_CLASSES])
    def test_no_job_or_position_language(self, regulatory_df, ScenCls):
        """Summaries must not contain position, job-title, or JD language."""
        result = ScenCls(df=regulatory_df, **DEFAULT_KWARGS).run()
        banned_terms = [
            "BizOps", "APaS", "GCS", "position title", "job description",
            "jd_alignment", "jd_keywords", "position_title",
        ]
        for term in banned_terms:
            assert term not in result.executive_summary, (
                f"{ScenCls.__name__} summary contains banned term '{term}'"
            )
            assert term not in result.methodology_note, (
                f"{ScenCls.__name__} methodology_note contains banned term '{term}'"
            )


# ════════════════════════════════════════════════════════════════════
# 7. Runner dispatch
# ════════════════════════════════════════════════════════════════════

class TestRunner:

    def test_scenario_map_has_five_entries(self):
        assert len(SCENARIO_MAP) == 5, (
            f"Expected 5 scenarios in SCENARIO_MAP, got {len(SCENARIO_MAP)}"
        )

    def test_invalid_key_raises(self, regulatory_df):
        with pytest.raises(KeyError):
            run_scenario("NonExistentScenario", regulatory_df, **DEFAULT_KWARGS)

    def test_invalid_number_raises(self, regulatory_df):
        with pytest.raises((KeyError, IndexError, ValueError)):
            run_scenario_by_number(99, regulatory_df, **DEFAULT_KWARGS)

    def test_runner_returns_scenario_result(self, regulatory_df):
        for key in SCENARIO_MAP:
            result = run_scenario(key, regulatory_df, **DEFAULT_KWARGS)
            assert isinstance(result, ScenarioResult), (
                f"run_scenario('{key}') returned {type(result)}, expected ScenarioResult"
            )
