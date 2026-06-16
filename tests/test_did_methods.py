"""
test_did_methods.py — Unit tests for all DiD estimators and related methods.

Tests:
  1. Standard 2×2 DiD — known effect recovery
  2. Event Study — pre-trend coefficients ≈ 0
  3. DoubleML partialling-out estimator
  4. Power analysis monotonicity
  5. Triple DiD sign check
  6. Staggered DiD ATT(g,t) shape
  7. Synthetic control (panel shape checks, skips if pysyncon missing)

Run: pytest tests/test_did_methods.py -v
"""
import pytest
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from conftest import TRUE_CCPA_EFFECT


# ════════════════════════════════════════════════════════════════════
# Helpers (inline — no scenario module import required for unit tests)
# ════════════════════════════════════════════════════════════════════

COVARIATES = ["unemployment_rate", "hpi", "mortgage_rate_30yr"]

def _run_standard_did(df: pd.DataFrame, outcome: str = "approval_rate") -> dict:
    d = df.copy()
    d["treat"] = (d["state_code"] == "CA").astype(int)
    d["post"]  = (d["activity_year"] >= 2020).astype(int)
    d["did"]   = d["treat"] * d["post"]
    d = d.dropna(subset=[outcome] + COVARIATES)
    mod = smf.ols(
        f"{outcome} ~ treat + post + did + {'+'.join(COVARIATES)}",
        data=d,
    ).fit(cov_type="HC3")
    return {
        "estimate": mod.params.get("did", np.nan),
        "se":       mod.bse.get("did", np.nan),
        "pval":     mod.pvalues.get("did", np.nan),
        "ci":       tuple(mod.conf_int().loc["did"]) if "did" in mod.conf_int().index else (np.nan, np.nan),
        "model":    mod,
        "df":       d,
    }

def _run_event_study(df: pd.DataFrame, outcome: str = "approval_rate") -> pd.DataFrame:
    d = df.copy()
    d["treat"]      = (d["state_code"] == "CA").astype(int)
    d["post"]       = (d["activity_year"] >= 2020).astype(int)
    d["event_time"] = d["activity_year"] - 2020

    for t in d["event_time"].unique():
        if t == -1:
            continue
        col = f"ca_t{'p' if t >= 0 else 'm'}{abs(int(t))}"
        d[col] = ((d["treat"] == 1) & (d["event_time"] == t)).astype(int)

    dummies = [c for c in d.columns if c.startswith("ca_t")]
    if not dummies:
        return pd.DataFrame()

    formula = (
        f"{outcome} ~ treat + post + {'+'.join(dummies)}"
        f" + {'+'.join(COVARIATES)}"
    )
    mod = smf.ols(formula, data=d.dropna(subset=[outcome]+COVARIATES)).fit(cov_type="HC3")

    rows = []
    for t in sorted(d["event_time"].unique()):
        col = f"ca_t{'p' if t >= 0 else 'm'}{abs(int(t))}"
        if t == -1:
            rows.append({"t": t, "coef": 0.0, "lo": 0.0, "hi": 0.0, "pval": 1.0})
        elif col in mod.params:
            ci = mod.conf_int().loc[col]
            rows.append({"t": t,
                         "coef": mod.params[col],
                         "lo":   ci[0],
                         "hi":   ci[1],
                         "pval": mod.pvalues[col]})
    return pd.DataFrame(rows)

def _doubleml_estimate(df: pd.DataFrame, outcome: str = "approval_rate") -> dict:
    d = df.copy()
    d["treat"] = (d["state_code"] == "CA").astype(int)
    d["post"]  = (d["activity_year"] >= 2020).astype(int)
    d["did"]   = d["treat"] * d["post"]
    d = d.dropna(subset=[outcome] + COVARIATES)

    mod_y  = smf.ols(f"{outcome} ~ {'+'.join(COVARIATES)} + C(activity_year)", data=d).fit()
    d["y_resid"] = mod_y.resid
    mod_t  = smf.ols(f"did ~ {'+'.join(COVARIATES)} + C(activity_year)", data=d).fit()
    d["t_resid"] = mod_t.resid
    mod_dml = smf.ols("y_resid ~ t_resid", data=d).fit(cov_type="HC3")

    return {
        "estimate": mod_dml.params["t_resid"],
        "se":       mod_dml.bse["t_resid"],
        "pval":     mod_dml.pvalues["t_resid"],
        "ci":       tuple(mod_dml.conf_int().loc["t_resid"]),
    }

def _power_analysis(sigma: float, mde: float) -> pd.DataFrame:
    from scipy import stats
    alpha = 0.05
    rows  = []
    for power in [0.70, 0.80, 0.85, 0.90, 0.95]:
        z_a = stats.norm.ppf(1 - alpha/2)
        z_b = stats.norm.ppf(power)
        n   = int(np.ceil(2 * ((z_a + z_b) * sigma / mde) ** 2))
        rows.append({"power": power, "n_per_arm": n})
    return pd.DataFrame(rows)


# ════════════════════════════════════════════════════════════════════
# 1. Standard 2×2 DiD — effect recovery
# ════════════════════════════════════════════════════════════════════

class TestStandardDiD:

    def test_estimate_directionally_correct(self, regulatory_df):
        """DiD estimate should be negative (CCPA reduced approval rates)."""
        result = _run_standard_did(regulatory_df)
        assert result["estimate"] < 0, (
            f"Expected negative estimate, got {result['estimate']:.4f}"
        )

    def test_estimate_recovers_true_effect(self, regulatory_df):
        """
        DiD estimate should be within 1.5pp of TRUE_CCPA_EFFECT (-0.025).
        Tolerance is generous — DGP has noise and macro confounders.
        """
        result   = _run_standard_did(regulatory_df)
        estimate = result["estimate"]
        tol      = 0.015
        assert abs(estimate - TRUE_CCPA_EFFECT) < tol, (
            f"Estimate {estimate:.4f} too far from true effect {TRUE_CCPA_EFFECT}. "
            f"Difference: {abs(estimate - TRUE_CCPA_EFFECT):.4f} > tolerance {tol}"
        )

    def test_ci_contains_true_effect(self, regulatory_df):
        """95% CI should contain the true effect in most simulations."""
        result = _run_standard_did(regulatory_df)
        lo, hi = result["ci"]
        assert lo <= TRUE_CCPA_EFFECT <= hi, (
            f"95% CI [{lo:.4f}, {hi:.4f}] does not contain true effect {TRUE_CCPA_EFFECT}"
        )

    def test_returns_required_keys(self, regulatory_df):
        result = _run_standard_did(regulatory_df)
        for key in ["estimate", "se", "pval", "ci", "model"]:
            assert key in result, f"Missing key: {key}"

    def test_se_positive(self, regulatory_df):
        result = _run_standard_did(regulatory_df)
        assert result["se"] > 0, "Standard error must be positive"

    def test_pval_in_range(self, regulatory_df):
        result = _run_standard_did(regulatory_df)
        assert 0 <= result["pval"] <= 1, f"p-value {result['pval']} out of [0,1]"

    def test_different_outcomes(self, regulatory_df):
        """DiD should run without error on multiple outcome variables."""
        for outcome in ["approval_rate", "origination_rate", "avg_ltv"]:
            result = _run_standard_did(regulatory_df, outcome=outcome)
            assert np.isfinite(result["estimate"]), f"Non-finite estimate for {outcome}"

    def test_control_state_sensitivity(self, regulatory_df):
        """Estimate should be stable across different control state sets."""
        estimates = []
        for controls in [["TX"], ["TX","FL"], ["TX","FL","OH"]]:
            sub = regulatory_df[
                regulatory_df["state_code"].isin(["CA"] + controls)
                & regulatory_df["activity_year"].between(2018, 2021)
            ]
            result = _run_standard_did(sub)
            estimates.append(result["estimate"])
        # All estimates should be negative and within 2pp of each other
        assert all(e < 0 for e in estimates), "All estimates should be negative"
        assert max(estimates) - min(estimates) < 0.02, (
            f"Estimates too sensitive to control group: {estimates}"
        )


# ════════════════════════════════════════════════════════════════════
# 2. Event Study — pre-trend validation
# ════════════════════════════════════════════════════════════════════

class TestEventStudy:

    def test_reference_period_is_zero(self, regulatory_df):
        """t = -1 (reference year) must have coefficient exactly 0."""
        es_df = _run_event_study(regulatory_df)
        ref_row = es_df[es_df["t"] == -1]
        assert len(ref_row) == 1, "Reference period row missing"
        assert ref_row["coef"].values[0] == 0.0, (
            "Reference period coefficient must be 0 (by construction)"
        )

    def test_pre_period_coefficients_near_zero(self, regulatory_df):
        """
        Pre-treatment coefficients (t < -1) should be statistically
        indistinguishable from zero — parallel trends test.
        """
        es_df     = _run_event_study(regulatory_df)
        pre_coefs = es_df[es_df["t"] < -1]["coef"]
        for t_val, coef in zip(es_df[es_df["t"] < -1]["t"], pre_coefs):
            assert abs(coef) < 0.03, (
                f"Pre-trend coefficient at t={t_val} is {coef:.4f} — "
                f"exceeds |0.03| threshold, suggesting pre-existing trend"
            )

    def test_post_period_negative(self, regulatory_df):
        """Post-CCPA coefficients (t >= 0) should be negative for CA."""
        es_df      = _run_event_study(regulatory_df)
        post_coefs = es_df[es_df["t"] >= 0]["coef"]
        assert post_coefs.mean() < 0, (
            f"Post-period mean coefficient is {post_coefs.mean():.4f} — expected < 0"
        )

    def test_output_columns_present(self, regulatory_df):
        es_df = _run_event_study(regulatory_df)
        for col in ["t", "coef", "lo", "hi", "pval"]:
            assert col in es_df.columns, f"Missing column: {col}"

    def test_ci_brackets_coefficient(self, regulatory_df):
        """95% CI must bracket the point estimate for all rows."""
        es_df = _run_event_study(regulatory_df)
        for _, row in es_df.iterrows():
            assert row["lo"] <= row["coef"] <= row["hi"], (
                f"CI [{row['lo']:.4f}, {row['hi']:.4f}] does not bracket "
                f"coef {row['coef']:.4f} at t={row['t']}"
            )

    def test_no_duplicate_event_times(self, regulatory_df):
        es_df = _run_event_study(regulatory_df)
        assert es_df["t"].nunique() == len(es_df), "Duplicate event times detected"

    def test_monotone_ci_width(self, regulatory_df):
        """CI widths should generally be finite and positive."""
        es_df = _run_event_study(regulatory_df)
        widths = es_df["hi"] - es_df["lo"]
        assert (widths >= 0).all(), "Negative CI widths detected"
        assert widths.max() < 1.0, f"Implausibly wide CI: {widths.max():.4f}"


# ════════════════════════════════════════════════════════════════════
# 3. DoubleML partialling-out
# ════════════════════════════════════════════════════════════════════

class TestDoubleML:

    def test_estimate_directionally_correct(self, regulatory_df):
        result = _doubleml_estimate(regulatory_df)
        assert result["estimate"] < 0, (
            f"DoubleML estimate {result['estimate']:.4f} should be negative"
        )

    def test_estimate_close_to_ols_did(self, regulatory_df):
        """
        DoubleML and OLS DiD should agree within 1pp when confounders
        are linear (our DGP satisfies this).
        """
        dml = _doubleml_estimate(regulatory_df)
        ols = _run_standard_did(regulatory_df)
        diff = abs(dml["estimate"] - ols["estimate"])
        assert diff < 0.01, (
            f"DoubleML ({dml['estimate']:.4f}) and OLS DiD ({ols['estimate']:.4f}) "
            f"diverge by {diff:.4f} — exceeds 0.01 threshold"
        )

    def test_se_smaller_than_ols(self, regulatory_df):
        """
        DoubleML SEs may be smaller than naive OLS by removing macro variance.
        This is not guaranteed but is the typical result with good covariates.
        Soft assertion — just log if violated.
        """
        dml = _doubleml_estimate(regulatory_df)
        ols = _run_standard_did(regulatory_df)
        if dml["se"] >= ols["se"]:
            import warnings
            warnings.warn(
                f"DoubleML SE ({dml['se']:.4f}) >= OLS SE ({ols['se']:.4f}). "
                "This can happen with weak instruments. Consider adding covariates."
            )

    def test_returns_finite_values(self, regulatory_df):
        result = _doubleml_estimate(regulatory_df)
        for k, v in result.items():
            if k != "ci":
                assert np.isfinite(v), f"Non-finite value for key '{k}': {v}"
        assert all(np.isfinite(c) for c in result["ci"]), "Non-finite CI bounds"


# ════════════════════════════════════════════════════════════════════
# 4. Power analysis
# ════════════════════════════════════════════════════════════════════

class TestPowerAnalysis:

    def test_monotone_power_requires_more_n(self, regulatory_df):
        """Higher target power must require at least as many observations."""
        sigma  = regulatory_df["approval_rate"].std()
        pa_df  = _power_analysis(sigma=sigma, mde=0.01)
        n_vals = pa_df["n_per_arm"].tolist()
        assert n_vals == sorted(n_vals), (
            f"Required n not monotonically increasing with power: {n_vals}"
        )

    def test_larger_mde_requires_fewer_n(self, regulatory_df):
        """Larger MDE → easier to detect → fewer observations needed."""
        sigma  = regulatory_df["approval_rate"].std()
        n_small_mde = _power_analysis(sigma, mde=0.005)["n_per_arm"].iloc[2]
        n_large_mde = _power_analysis(sigma, mde=0.020)["n_per_arm"].iloc[2]
        assert n_small_mde > n_large_mde, (
            f"Small MDE ({n_small_mde}) should need more n than large MDE ({n_large_mde})"
        )

    def test_n_positive_integer(self, regulatory_df):
        sigma = regulatory_df["approval_rate"].std()
        pa_df = _power_analysis(sigma=sigma, mde=0.01)
        assert (pa_df["n_per_arm"] > 0).all(), "All n values must be positive"
        assert pa_df["n_per_arm"].dtype in [int, np.int64, np.int32, object], \
            "n_per_arm should be integer type"

    def test_power_column_values(self, regulatory_df):
        sigma = regulatory_df["approval_rate"].std()
        pa_df = _power_analysis(sigma=sigma, mde=0.01)
        expected_powers = {0.70, 0.80, 0.85, 0.90, 0.95}
        assert set(pa_df["power"]) == expected_powers, (
            f"Power values mismatch: {set(pa_df['power'])} != {expected_powers}"
        )


# ════════════════════════════════════════════════════════════════════
# 5. Triple DiD (investor × CA × post-CCPA)
# ════════════════════════════════════════════════════════════════════

class TestTripleDiD:

    def test_runs_without_error(self, regulatory_df):
        """Triple DiD regression should complete without exception."""
        d = regulatory_df[
            regulatory_df["state_code"].isin(["CA","TX","FL","OH"])
            & regulatory_df["activity_year"].between(2018, 2021)
        ].copy()
        d["treat"] = (d["state_code"] == "CA").astype(int)
        d["post"]  = (d["activity_year"] >= 2020).astype(int)
        d["did"]   = d["treat"] * d["post"]
        d["did3"]  = d["treat"] * d["post"] * d["is_investor_loan"]

        mod = smf.ols(
            "approval_rate ~ treat*post*is_investor_loan"
            " + unemployment_rate + hpi + mortgage_rate_30yr",
            data=d.dropna(),
        ).fit(cov_type="HC3")
        assert mod.params is not None

    def test_investor_interaction_finite(self, regulatory_df):
        """Triple interaction coefficient must be finite."""
        d = regulatory_df[
            regulatory_df["state_code"].isin(["CA","TX","FL","OH"])
            & regulatory_df["activity_year"].between(2018, 2021)
        ].copy()
        d["treat"] = (d["state_code"] == "CA").astype(int)
        d["post"]  = (d["activity_year"] >= 2020).astype(int)

        mod = smf.ols(
            "approval_rate ~ treat*post*is_investor_loan"
            " + unemployment_rate + hpi + mortgage_rate_30yr",
            data=d.dropna(),
        ).fit(cov_type="HC3")

        triple_key = "treat:post:is_investor_loan"
        if triple_key in mod.params:
            assert np.isfinite(mod.params[triple_key]), (
                "Triple DiD coefficient is non-finite"
            )


# ════════════════════════════════════════════════════════════════════
# 6. Staggered DiD — ATT(g,t) shape
# ════════════════════════════════════════════════════════════════════

class TestStaggeredDiD:

    def _att_gt_block(self, df, state, g_year, t_year, never_treated_states):
        """Single 2×2 DiD block for ATT(g,t)."""
        never = df[df["state_code"].isin(never_treated_states)]
        treated = df[df["state_code"] == state]
        block = pd.concat([
            treated[treated["activity_year"].isin([g_year-1, t_year])],
            never[never["activity_year"].isin([g_year-1, t_year])],
        ])
        if len(block) < 10:
            return None
        block = block.copy()
        block["_treat"] = (block["state_code"] == state).astype(int)
        block["_post"]  = (block["activity_year"] == t_year).astype(int)
        block["_did"]   = block["_treat"] * block["_post"]
        try:
            mod = smf.ols(
                "approval_rate ~ _treat + _post + _did"
                " + unemployment_rate + hpi + mortgage_rate_30yr",
                data=block.dropna(),
            ).fit()
            return {"att": mod.params.get("_did", np.nan), "n": len(block)}
        except Exception:
            return None

    def test_pre_period_att_near_zero(self, regulatory_df):
        """ATT(g, g-1) — the period just before treatment — should be ~0."""
        result = self._att_gt_block(
            regulatory_df,
            state="CA", g_year=2020, t_year=2019,
            never_treated_states=["TX","FL","OH"],
        )
        assert result is not None, "Pre-period block returned None"
        assert abs(result["att"]) < 0.02, (
            f"Pre-period ATT(CA, 2019) = {result['att']:.4f} — expected near 0"
        )

    def test_post_period_att_negative(self, regulatory_df):
        """ATT(CA, 2020) — year of treatment — should be negative."""
        result = self._att_gt_block(
            regulatory_df,
            state="CA", g_year=2020, t_year=2020,
            never_treated_states=["TX","FL","OH"],
        )
        assert result is not None, "Post-period block returned None"
        assert result["att"] < 0, (
            f"ATT(CA, 2020) = {result['att']:.4f} — expected negative"
        )

    def test_block_has_observations(self, regulatory_df):
        """Each 2×2 block should contain sufficient observations."""
        result = self._att_gt_block(
            regulatory_df,
            state="CA", g_year=2020, t_year=2021,
            never_treated_states=["TX","FL","OH"],
        )
        assert result is not None
        assert result["n"] >= 10, f"Too few observations in block: {result['n']}"


# ════════════════════════════════════════════════════════════════════
# 7. Synthetic Control — structural checks
# ════════════════════════════════════════════════════════════════════

class TestSyntheticControl:

    @pytest.mark.skipif(
        not __import__("importlib").util.find_spec("pysyncon"),
        reason="pysyncon not installed — pip install pysyncon",
    )
    def test_synthetic_control_runs(self, regulatory_df):
        """Synthetic control should produce weights summing to 1."""
        from pysyncon import Dataprep, Synth

        donor_states = ["TX","FL","OH","NY","IL"]
        panel = regulatory_df[
            regulatory_df["state_code"].isin(["CA"] + donor_states)
        ].groupby(["state_code","activity_year"]).agg(
            approval_rate    =("approval_rate","mean"),
            unemployment_rate=("unemployment_rate","mean"),
            hpi              =("hpi","mean"),
            mortgage_rate_30yr=("mortgage_rate_30yr","mean"),
        ).reset_index()

        all_years = sorted(panel["activity_year"].unique().tolist())
        pre_yrs   = [y for y in all_years if y <= 2019]

        dataprep = Dataprep(
            foo                   = panel,
            predictors            = ["unemployment_rate","hpi","mortgage_rate_30yr"],
            predictors_op         = "mean",
            time_predictors_prior = pre_yrs,
            special_predictors    = [("approval_rate",[2018],"mean"),
                                     ("approval_rate",[2019],"mean")],
            dependent             = "approval_rate",
            unit_variable         = "state_code",
            time_variable         = "activity_year",
            treatment_identifier  = "CA",
            controls_identifier   = donor_states,
            time_optimize_ssr     = pre_yrs,
            time_plot             = all_years,
        )
        synth = Synth()
        synth.fit(dataprep)

        weights = synth.W_weights
        assert len(weights) == len(donor_states), (
            f"Expected {len(donor_states)} weights, got {len(weights)}"
        )
        assert abs(sum(weights) - 1.0) < 1e-4, (
            f"Weights sum to {sum(weights):.6f} — should sum to 1.0"
        )
        assert all(w >= -1e-6 for w in weights), "Negative weights detected"

    @pytest.mark.skipif(
        not __import__("importlib").util.find_spec("pysyncon"),
        reason="pysyncon not installed",
    )
    def test_pre_period_fit(self, regulatory_df):
        """Synthetic CA should closely match actual CA in the pre-period."""
        from pysyncon import Dataprep, Synth

        donor_states = ["TX","FL","OH","NY","IL"]
        panel = regulatory_df[
            regulatory_df["state_code"].isin(["CA"] + donor_states)
        ].groupby(["state_code","activity_year"]).agg(
            approval_rate    =("approval_rate","mean"),
            unemployment_rate=("unemployment_rate","mean"),
            hpi              =("hpi","mean"),
            mortgage_rate_30yr=("mortgage_rate_30yr","mean"),
        ).reset_index()

        all_years = sorted(panel["activity_year"].unique().tolist())
        pre_yrs   = [y for y in all_years if y <= 2019]

        dataprep = Dataprep(
            foo=panel,
            predictors=["unemployment_rate","hpi","mortgage_rate_30yr"],
            predictors_op="mean",
            time_predictors_prior=pre_yrs,
            special_predictors=[("approval_rate",[2018],"mean"),("approval_rate",[2019],"mean")],
            dependent="approval_rate",
            unit_variable="state_code",
            time_variable="activity_year",
            treatment_identifier="CA",
            controls_identifier=donor_states,
            time_optimize_ssr=pre_yrs,
            time_plot=all_years,
        )
        synth = Synth()
        synth.fit(dataprep)

        wide     = panel.pivot(index="activity_year", columns="state_code",
                               values="approval_rate")
        synth_ca = wide[donor_states].values @ np.array([synth.W_weights[s] for s in donor_states])
        actual_ca = wide["CA"].values
        pre_idx   = [i for i, y in enumerate(wide.index) if y <= 2019]

        pre_rmse = np.sqrt(np.mean(
            [(actual_ca[i] - synth_ca[i])**2 for i in pre_idx]
        ))
        assert pre_rmse < 0.02, (
            f"Synthetic control pre-period RMSE too high: {pre_rmse:.4f} > 0.02"
        )
