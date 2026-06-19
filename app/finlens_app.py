#%%
"""
finlens_app.py  —  FinLens Mortgage Analytics Platform
=======================================================
Tab 1  — Mortgage Market Overview  (funnel + KPIs + trends)
Tab 2  — Privacy Law Impact        (5 causal inference scenarios)

Run:
    streamlit run app/finlens_app.py

Requires BigQuery marts written by dbt after ingest_latest.py.
Set GCP_PROJECT in .env and authenticate via ADC or service-account credentials.
"""

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import statsmodels.formula.api as smf
import streamlit as st

warnings.filterwarnings("ignore")

# ── Project root on path so config + scenarios import cleanly ────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from config import cfg

try:
    from scenarios.runner import run_scenario, SCENARIO_MAP
    SCENARIOS_AVAILABLE = True
except ImportError:
    SCENARIOS_AVAILABLE = False

# ═════════════════════════════════════════════════════════════════════════════
# PAGE CONFIG & GLOBAL CSS
# ═════════════════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="FinLens | Mortgage Analytics",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
  [data-testid="stAppViewContainer"] { background: #fafbfc; }
  .kpi-card {
    background: white; border-radius: 10px; padding: 16px 20px;
    box-shadow: 0 1px 4px rgba(0,0,0,.08); text-align: center;
    border-left: 4px solid #1f77b4;
  }
  .kpi-val   { font-size: 1.55em; font-weight: 700; color: #1a3a6b; }
  .kpi-label { font-size: .78em; color: #666; margin-top: 4px;
               text-transform: uppercase; letter-spacing: .04em; font-weight: 600; }
  .kpi-delta { font-size: .82em; margin-top: 2px; }
  .policy-box {
    padding: 14px 18px; border-radius: 8px; margin-bottom: 14px;
    background: #e8f4fd; border-left: 5px solid #1f77b4;
    font-size: .93em;
  }
</style>
""", unsafe_allow_html=True)

# ── Colour palette ───────────────────────────────────────────────────────────
C_TREAT   = "#1f77b4"
C_CTRL    = "#7f7f7f"
C_APPROVE = "#2ca02c"
C_DENY    = "#d62728"
C_AMBER   = "rgba(255,200,60,0.13)"

# ── Domain constants (from cfg where possible) ───────────────────────────────
STATES       = cfg.states                   # ["CA","TX","FL","OH","NY","IL"]
YEARS        = cfg.app_years                # [2018..2023]
LOAN_TYPES   = cfg.loan_types
INCOME_TIERS = cfg.income_tiers
COVARIATES   = cfg.covariates               # ["unemployment_rate","hpi","mortgage_rate_30yr"]

TREATED_STATES = {"CA": 2020, "VA": 2023, "CO": 2023}

SCENARIO_LABELS = {
    1: "Scenario 1 — CCPA: CA vs. Control States (2×2 DiD)",
    2: "Scenario 2 — Multi-State Rollout (Staggered DiD)",
    3: "Scenario 3 — Lender Behaviour Timeline (Event Study)",
    4: "Scenario 4 — Investor vs. Owner-Occ (Triple DiD)",
    5: "Scenario 5 — Income Tier Heterogeneity (Interaction DiD)",
}

# Human-readable labels for outcome column names used in chart titles / axes
OUTCOME_LABELS = {
    "approval_rate":    "Approval Rate",
    "origination_rate": "Origination Rate",
    "denial_rate":      "Denial Rate",
    "avg_ltv":          "Avg Loan-to-Value (LTV) Ratio",
    "avg_dti":          "Avg Debt-to-Income (DTI) Ratio",
}

def outcome_label(col: str) -> str:
    """Return a human-readable label for an outcome column."""
    return OUTCOME_LABELS.get(col, col.replace("_", " ").title())

# ═════════════════════════════════════════════════════════════════════════════
# DATA LAYER — BigQuery only
# ═════════════════════════════════════════════════════════════════════════════

def _coerce_numpy_dtypes(df: pd.DataFrame) -> pd.DataFrame:
    """BigQuery nullable extension dtypes (Int64, etc.) break statsmodels/patsy."""
    for col in df.columns:
        dtype = df[col].dtype
        if not pd.api.types.is_extension_array_dtype(dtype):
            continue
        if pd.api.types.is_bool_dtype(dtype):
            df[col] = df[col].fillna(0).astype("int64")
        elif pd.api.types.is_integer_dtype(dtype):
            if df[col].isna().any():
                df[col] = df[col].astype("float64")
            else:
                df[col] = df[col].astype("int64")
        elif pd.api.types.is_float_dtype(dtype):
            df[col] = df[col].astype("float64")
    return df


@st.cache_resource(show_spinner=False)
def _get_bq_client():
    from google.cloud import bigquery
    from google.oauth2 import service_account

    try:
        cred_json = st.secrets["gcp"]["credentials"]
        creds = service_account.Credentials.from_service_account_info(
            json.loads(cred_json)
        )
        project = st.secrets["gcp"].get("project", cfg.project)
        return bigquery.Client(project=project, credentials=creds)
    except Exception:
        pass
    return bigquery.Client(project=cfg.project or None)


def _bq_setup_hint() -> str:
    return (
        "1. Set `GCP_PROJECT` and `BQ_DATASET_MARTS` in `.env`\n"
        "2. Authenticate: `gcloud auth application-default login`\n"
        "3. Build marts: `python ingest/ingest_latest.py` then `dbt run --select marts`"
    )


@st.cache_data(ttl=3600, show_spinner="Loading from BigQuery…")
def _bq_table(table: str) -> pd.DataFrame:
    if not cfg.project:
        raise EnvironmentError("GCP_PROJECT is not set. Add it to your .env file.")
    client = _get_bq_client()
    fq = f"`{cfg.project}.{cfg.bq_dataset_marts}.{table}`"
    try:
        # REST API only — avoids bigquerystorage.googleapis.com (DNS issues on some networks)
        df = client.query(f"SELECT * FROM {fq}").to_dataframe(
            create_bqstorage_client=False
        )
    except Exception as exc:
        err = str(exc)
        if "Not found" in err or "404" in err or "notFound" in err:
            raise RuntimeError(
                f"BigQuery table `{cfg.bq_dataset_marts}.{table}` not found. "
                f"If dbt wrote elsewhere, set BQ_DATASET_MARTS in .env."
            ) from exc
        raise
    df.columns = df.columns.str.lower()
    return _coerce_numpy_dtypes(df)


def load_regulatory() -> pd.DataFrame:
    return _bq_table("mart_regulatory_cohort")


def load_funnel() -> pd.DataFrame:
    return _bq_table("mart_lending_funnel")


# ═════════════════════════════════════════════════════════════════════════════
# DiD COMPUTATION HELPERS
# ═════════════════════════════════════════════════════════════════════════════

def run_standard_did(df, treatment_state, control_states,
                     pre_years, post_years, outcome) -> dict:
    d = df[
        df["state_code"].isin([treatment_state] + control_states)
        & df["activity_year"].between(pre_years[0], post_years[1])
    ].copy()
    d["treat"] = (d["state_code"] == treatment_state).astype(int)
    d["post"]  = (d["activity_year"] > pre_years[1]).astype(int)
    d["did"]   = d["treat"] * d["post"]
    missing_cols = [c for c in [outcome] + COVARIATES if c not in d.columns]
    if missing_cols:
        raise KeyError(
            f"Column(s) {missing_cols} not found in the regulatory panel. "
            "Re-run `dbt run -s mart_regulatory_cohort` to add them."
        )
    d = d.dropna(subset=[outcome] + COVARIATES)
    if len(d) < 10:
        return {"estimate": 0, "se": 0, "pval": 1, "ci": (0, 0), "df": d}
    formula = f"{outcome} ~ treat + post + did + {' + '.join(COVARIATES)} + C(state_code)"
    mod = smf.ols(formula, data=d).fit(cov_type="HC3")
    return {
        "estimate": float(mod.params.get("did", 0)),
        "se":       float(mod.bse.get("did", 0)),
        "pval":     float(mod.pvalues.get("did", 1)),
        "ci":       tuple(mod.conf_int().loc["did"]) if "did" in mod.conf_int().index else (0, 0),
        "model":    mod,
        "df":       d,
    }


def run_event_study(df, treatment_state, control_states,
                    pre_years, post_years, outcome) -> pd.DataFrame:
    d = df[df["state_code"].isin([treatment_state] + control_states)].copy()
    d["treat"]      = (d["state_code"] == treatment_state).astype(int)
    d["post"]       = (d["activity_year"] > pre_years[1]).astype(int)
    d["event_time"] = d["activity_year"] - (pre_years[1] + 1)
    ref_t = -1
    for t in d["event_time"].unique():
        if t == ref_t:
            continue
        col = f"ca_t{'p' if t >= 0 else 'm'}{abs(int(t))}"
        d[col] = ((d["treat"] == 1) & (d["event_time"] == t)).astype(int)
    dummies = [c for c in d.columns if c.startswith("ca_t")]
    if not dummies:
        return pd.DataFrame()
    avail_covs = [c for c in COVARIATES if c in d.columns]
    mod = smf.ols(
        f"{outcome} ~ treat + {' + '.join(dummies)}"
        f" + {' + '.join(avail_covs)} + C(activity_year)",
        data=d.dropna(subset=[outcome] + avail_covs)
    ).fit(cov_type="HC3")
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
    return pd.DataFrame(rows)


# ═════════════════════════════════════════════════════════════════════════════
# UI HELPERS
# ═════════════════════════════════════════════════════════════════════════════

def kpi_card(label: str, value: str, delta: str = "", delta_color: str = "#555"):
    delta_html = (f'<div class="kpi-delta" style="color:{delta_color}">{delta}</div>'
                  if delta else "")
    st.markdown(
        f'<div class="kpi-card">'
        f'  <div class="kpi-val">{value}</div>'
        f'  <div class="kpi-label">{label}</div>'
        f'  {delta_html}'
        f'</div>',
        unsafe_allow_html=True,
    )


def policy_banner(law: str, states: str, effective: str, scope: str):
    st.markdown(
        f'<div class="policy-box">'
        f'<strong>⚖️ {law}</strong> &nbsp;·&nbsp; Effective {effective} &nbsp;·&nbsp; {states}<br>'
        f'<span style="color:#444">{scope}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )


def att_metric(label: str, coef: float, se: float):
    ci_lo, ci_hi = coef - 1.96 * se, coef + 1.96 * se
    sig = (ci_lo > 0 or ci_hi < 0)
    sig_text = "✅ p < 0.05" if sig else "⚠️ n.s. at 5%"
    color = C_DENY if coef < 0 else C_APPROVE
    kpi_card(
        label,
        f"{coef * 100:+.2f} pp",
        f"95% CI [{ci_lo * 100:+.2f}, {ci_hi * 100:+.2f}] &nbsp;·&nbsp; {sig_text}",
        delta_color=color,
    )


def shade_post_law(fig, law_year: int, x_max: int):
    fig.add_vrect(
        x0=law_year - 0.5, x1=x_max + 0.5,
        fillcolor=C_AMBER, opacity=1, line_width=0,
    )


def _add_occupancy_label(df: pd.DataFrame) -> pd.DataFrame:
    """Map mart columns to owner/investor labels (BQ marts use is_investor_loan)."""
    d = df.copy()
    if "occupancy_type" in d.columns:
        d["occ_label"] = d["occupancy_type"].map({1: "Owner-Occupied", 2: "Investor"})
    elif "is_investor_loan" in d.columns:
        d["occ_label"] = np.where(
            d["is_investor_loan"] == 1, "Investor", "Owner-Occupied"
        )
    else:
        d["occ_label"] = np.nan
    return d


# ═════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ═════════════════════════════════════════════════════════════════════════════

with st.sidebar:
    st.markdown("## 🏦 FinLens")
    try:
        _get_bq_client()
        st.success("Live · BigQuery", icon="🟢")
        st.caption(f"Marts dataset: `{cfg.bq_dataset_marts}`")
    except Exception as exc:
        st.error("BigQuery connection failed.")
        st.code(str(exc))
        st.markdown(_bq_setup_hint())
        st.stop()

    st.divider()
    st.markdown("### Funnel Filters")
    year_range   = st.slider("Year range", YEARS[0], YEARS[-1], (YEARS[0], YEARS[-1]))
    sel_states   = st.multiselect("States", STATES, default=STATES)
    sel_loans    = st.multiselect("Loan types", LOAN_TYPES, default=["conventional", "fha"])
    sel_tiers    = st.multiselect("Income tiers", INCOME_TIERS,
                                  default=["moderate_income", "middle_income", "high_income"])

    st.divider()
    st.markdown("### DiD Configuration")
    treat_state  = st.selectbox("Treatment state", ["CA", "VA", "CO"], index=0)
    ctrl_states  = st.multiselect("Control states", ["TX", "FL", "OH", "NY", "IL"],
                                  default=["TX", "FL", "OH"])
    pre_period   = st.slider("Pre-period",  YEARS[0], YEARS[-1] - 1, (2018, 2019))
    post_period  = st.slider("Post-period", YEARS[0] + 1, YEARS[-1], (2020, 2021))
    did_outcome  = st.selectbox(
        "DiD outcome",
        ["approval_rate", "origination_rate", "denial_rate", "avg_ltv", "avg_dti"],
        format_func=lambda x: x.replace("_", " ").title()
    )


# ═════════════════════════════════════════════════════════════════════════════
# LOAD DATA
# ═════════════════════════════════════════════════════════════════════════════

try:
    with st.spinner("Loading data from BigQuery…"):
        reg_df = load_regulatory()
        fun_df = load_funnel()
except Exception as exc:
    st.error(f"Failed to load BigQuery marts: {exc}")
    st.markdown(_bq_setup_hint())
    st.stop()

# ═════════════════════════════════════════════════════════════════════════════
# HEADER
# ═════════════════════════════════════════════════════════════════════════════

st.markdown("""
<div style="background:linear-gradient(90deg,#1f3c6b,#1f77b4);
            padding:18px 28px;border-radius:12px;margin-bottom:18px">
  <span style="color:white;font-size:1.8em;font-weight:800">🏦 FinLens</span>
  <span style="color:#aad4f5;font-size:1.0em;margin-left:14px">
    Mortgage Analytics &amp; Privacy Law Impact Platform
  </span>
</div>
""", unsafe_allow_html=True)

tab1, tab2 = st.tabs([
    "📊  Mortgage Market Overview",
    "⚖️  Privacy Law Impact — 5 Scenarios",
])


# ═════════════════════════════════════════════════════════════════════════════
# TAB 1  —  MORTGAGE MARKET OVERVIEW
# ═════════════════════════════════════════════════════════════════════════════

with tab1:
    st.markdown("### Mortgage Market Overview")
    st.caption("Application → Approval → Origination funnel · HMDA 2018–2023")
    st.divider()

    # Apply sidebar filters
    ff = fun_df[
        fun_df["activity_year"].between(*year_range)
        & fun_df["state_code"].isin(sel_states)
        & fun_df["loan_type_label"].isin(sel_loans)
        & fun_df["income_tier"].isin(sel_tiers)
    ]
    rf = reg_df[
        reg_df["activity_year"].between(*year_range)
        & reg_df["state_code"].isin(sel_states)
        & reg_df["loan_type_label"].isin(sel_loans)
        & reg_df["income_tier"].isin(sel_tiers)
    ]

    # ── KPI row ──────────────────────────────────────────────────────────────
    total_apps = int(ff["total_applications"].sum())
    avg_apr    = float(ff["approval_rate"].mean())
    avg_orig   = float(ff["origination_rate"].mean())
    avg_deny   = float(ff["denial_rate"].mean())
    avg_loan   = float(ff["avg_loan_amount"].mean())
    total_vol  = float(ff["total_loan_volume"].sum())

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1: kpi_card("Total Applications", f"{total_apps:,.0f}")
    with c2: kpi_card("Avg Approval Rate", f"{avg_apr:.1%}",
                      delta_color=C_APPROVE if avg_apr >= .70 else C_DENY)
    with c3: kpi_card("Origination Rate",  f"{avg_orig:.1%}")
    with c4: kpi_card("Avg Denial Rate",   f"{avg_deny:.1%}",
                      delta_color=C_DENY if avg_deny >= .25 else C_APPROVE)
    with c5: kpi_card("Avg Loan Amount",   f"${avg_loan:,.0f}")
    with c6: kpi_card("Total Volume",      f"${total_vol / 1e9:.1f}B")

    st.markdown("---")

    # ── Row 1: State choropleth + Application funnel ──────────────────────────
    col_map, col_fn = st.columns([1.3, 1])

    with col_map:
        st.markdown("#### Approval Rate by State")
        map_metric = st.selectbox(
            "Map metric",
            ["approval_rate", "denial_rate", "avg_loan_amount", "origination_rate"],
            format_func=lambda x: x.replace("_", " ").title(),
            key="map_metric_t1",
        )
        map_df = ff.groupby("state_code")[map_metric].mean().reset_index()
        fig_map = px.choropleth(
            map_df, locations="state_code", locationmode="USA-states",
            color=map_metric, scope="usa",
            color_continuous_scale="RdYlGn" if "rate" in map_metric else "Blues",
            range_color=([0.5, 0.9] if "approval" in map_metric else None),
            labels={map_metric: map_metric.replace("_", " ").title()},
        )
        fig_map.update_layout(height=310, margin=dict(l=0, r=0, t=10, b=0))
        if "rate" in map_metric:
            fig_map.update_coloraxes(colorbar_tickformat=".0%")
        st.plotly_chart(fig_map, use_container_width=True)

    with col_fn:
        st.markdown("#### Application Funnel")
        ft = ff.agg({
            "total_applications": "sum", "total_approved": "sum",
            "total_originated": "sum", "total_denied": "sum", "total_withdrawn": "sum",
        })
        fig_fn = go.Figure(go.Funnel(
            y=["Applications", "Approved", "Originated", "Denied", "Withdrawn"],
            x=[ft["total_applications"], ft["total_approved"],
               ft["total_originated"],  ft["total_denied"], ft["total_withdrawn"]],
            textinfo="value+percent initial",
            marker_color=[C_TREAT, C_APPROVE, "#ff7f0e", C_DENY, "#9467bd"],
        ))
        fig_fn.update_layout(height=310, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig_fn, use_container_width=True)

    # ── Row 2: Approval trend by state + Income tier bars ────────────────────
    col_ts, col_tier = st.columns(2)

    with col_ts:
        st.markdown("#### Approval Rate Trend by State")
        trend_df = fun_df[
            fun_df["state_code"].isin(sel_states)
            & fun_df["activity_year"].between(*year_range)
            & fun_df["loan_type_label"].isin(sel_loans)
        ].groupby(["activity_year", "state_code"])["approval_rate"].mean().reset_index()

        fig_ts = px.line(
            trend_df, x="activity_year", y="approval_rate",
            color="state_code", markers=True,
            color_discrete_map={treat_state: C_TREAT},
            labels={"approval_rate": "Approval Rate", "activity_year": "Year",
                    "state_code": "State"},
        )
        # shade post-law for any treated states in selection
        for st_code, law_yr in TREATED_STATES.items():
            if st_code in sel_states and law_yr <= year_range[1]:
                fig_ts.add_vrect(
                    x0=law_yr - 0.5, x1=year_range[1] + 0.5,
                    fillcolor=C_AMBER, opacity=1, line_width=0,
                    annotation_text=f"{st_code} law",
                    annotation_position="top left",
                )
        fig_ts.update_yaxes(tickformat=".0%")
        fig_ts.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig_ts, use_container_width=True)
        st.caption("🟡 Shaded = post-law period for each treated state")

    with col_tier:
        st.markdown("#### Approval Rate by Income Tier")
        tier_order = ["low_income", "moderate_income", "middle_income", "high_income"]
        tier_df = ff.groupby("income_tier")["approval_rate"].mean().reindex(tier_order).reset_index()
        fig_tier = px.bar(
            tier_df, x="income_tier", y="approval_rate",
            color="income_tier",
            color_discrete_sequence=["#90CAF9", "#42A5F5", "#1E88E5", "#0D47A1"],
            labels={"approval_rate": "Avg Approval Rate", "income_tier": "Income Tier"},
            text_auto=".1%",
        )
        fig_tier.update_yaxes(tickformat=".0%")
        fig_tier.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=0),
                               showlegend=False)
        st.plotly_chart(fig_tier, use_container_width=True)

    # ── Row 3: Loan type breakdown + Denial rate by year ─────────────────────
    col_lt, col_deny = st.columns(2)

    with col_lt:
        st.markdown("#### Volume by Loan Type")
        lt_df = ff.groupby("loan_type_label")["total_originated"].sum().reset_index()
        fig_lt = px.pie(lt_df, names="loan_type_label", values="total_originated",
                        color_discrete_sequence=px.colors.qualitative.Set2,
                        hole=0.4)
        fig_lt.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig_lt, use_container_width=True)

    with col_deny:
        st.markdown("#### Denial Rate Over Time by State")
        deny_df = fun_df[
            fun_df["state_code"].isin(sel_states)
            & fun_df["activity_year"].between(*year_range)
        ].groupby(["activity_year", "state_code"])["denial_rate"].mean().reset_index()
        fig_deny = px.line(
            deny_df, x="activity_year", y="denial_rate",
            color="state_code", markers=True,
            color_discrete_map={treat_state: C_DENY},
            labels={"denial_rate": "Denial Rate", "activity_year": "Year",
                    "state_code": "State"},
        )
        fig_deny.update_yaxes(tickformat=".0%")
        fig_deny.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig_deny, use_container_width=True)


# ═════════════════════════════════════════════════════════════════════════════
# TAB 2  —  PRIVACY LAW IMPACT (5 SCENARIOS)
# ═════════════════════════════════════════════════════════════════════════════

with tab2:
    st.markdown("### Privacy Law Impact Analysis")
    st.caption(
        "Causal inference across 5 econometric scenarios · "
        "HMDA 2018–2023 × FRED macro controls"
    )
    st.divider()

    col_nav, col_main = st.columns([0.27, 0.73])

    with col_nav:
        st.markdown("**Select scenario**")
        selected_sc = st.radio(
            label="",
            options=list(SCENARIO_LABELS.keys()),
            format_func=lambda k: SCENARIO_LABELS[k],
            label_visibility="collapsed",
        )
        st.divider()
        st.caption(
            "Each scenario answers a distinct causal question.\n\n"
            "**1** establishes the fact · **2** generalises across states · "
            "**3** validates timing · **4** isolates the mechanism · "
            "**5** maps who bears the burden."
        )
        if SCENARIOS_AVAILABLE:
            st.success("Scenario package loaded", icon="✅")
        else:
            st.info("Scenarios package unavailable — check PYTHONPATH includes the project root.", icon="ℹ️")

    with col_main:

        # ── SCENARIO 1 — Standard 2×2 DiD ────────────────────────────────────
        if selected_sc == 1:
            policy_banner(
                "California Consumer Privacy Act (CCPA)",
                "California", "January 1 2020",
                "Grants consumers rights to know, delete, and opt-out of sale of personal "
                "data. Restricts lenders' use of third-party behavioural credit signals for "
                "CA residents.",
            )
            st.markdown(
                "**Business question:** Did CCPA measurably change mortgage lending outcomes "
                "in California relative to comparable non-adopting states (TX, FL, OH)?"
            )

            with st.spinner("Running DiD regression…"):
                did = run_standard_did(
                    reg_df, treat_state, ctrl_states,
                    pre_period, post_period, did_outcome,
                )

            att_metric("DiD ATT — " + outcome_label(did_outcome),
                       did["estimate"], did["se"])
            st.markdown("---")

            # Means 2×2 table
            d_tbl = reg_df[
                reg_df["state_code"].isin([treat_state] + ctrl_states)
                & reg_df["activity_year"].between(pre_period[0], post_period[1])
            ].copy()
            d_tbl["group"]  = d_tbl["state_code"].apply(
                lambda s: f"Treatment ({treat_state})" if s == treat_state else "Control")
            d_tbl["period"] = d_tbl["activity_year"].apply(
                lambda y: "Pre" if y <= pre_period[1] else "Post")
            means = d_tbl.groupby(["group", "period"])[did_outcome].mean().unstack()
            if means.shape == (2, 2):
                means["Δ (Post − Pre)"] = means["Post"] - means["Pre"]
                st.markdown("##### 2×2 Means Table")
                st.dataframe(means.style.format("{:.4f}"), use_container_width=True)

            # Time-series chart
            st.markdown(f"##### {outcome_label(did_outcome)} — Treatment vs. Control")
            ts_df = reg_df[
                reg_df["state_code"].isin([treat_state] + ctrl_states)
                & reg_df["activity_year"].between(pre_period[0], post_period[1])
            ].copy()
            ts_df["group"] = ts_df["state_code"].apply(
                lambda s: f"{treat_state} (treated)" if s == treat_state else "Control avg")
            ts_agg = ts_df.groupby(["activity_year", "group"])[did_outcome].mean().reset_index()
            fig = px.line(ts_agg, x="activity_year", y=did_outcome, color="group",
                          markers=True,
                          color_discrete_map={f"{treat_state} (treated)": C_TREAT,
                                              "Control avg": C_CTRL})
            shade_post_law(fig, post_period[0], post_period[1])
            fig.add_vline(x=post_period[0] - 0.5, line_dash="dash",
                          line_color=C_TREAT, annotation_text="Law effective")
            if "rate" in did_outcome:
                fig.update_yaxes(tickformat=".1%")
            fig.update_layout(height=340, margin=dict(t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)

            with st.expander("Full OLS output (HC3-robust)"):
                if "model" in did and did["model"] is not None:
                    _mod = did["model"]
                    _ci  = _mod.conf_int()
                    _coef_df = pd.DataFrame({
                        "term":   _mod.params.index,
                        "coef":   _mod.params.values,
                        "se":     _mod.bse.values,
                        "lo":     _ci.iloc[:, 0].values,
                        "hi":     _ci.iloc[:, 1].values,
                        "pval":   _mod.pvalues.values,
                    })
                    # ── Model fit KPIs ────────────────────────────────────────
                    _k1, _k2, _k3, _k4 = st.columns(4)
                    _k1.metric("R²",          f"{_mod.rsquared:.4f}")
                    _k2.metric("Adj. R²",     f"{_mod.rsquared_adj:.4f}")
                    _k3.metric("N",           f"{int(_mod.nobs):,}")
                    _k4.metric("F-stat (HC3)",f"{_mod.fvalue:.1f}  p={_mod.f_pvalue:.3g}")

                    # ── Coefficient forest plot ───────────────────────────────
                    _sig  = _coef_df["pval"] < 0.05
                    _colors = np.where(_sig, "#1f77b4", "#aec7e8")
                    _fig_coef = go.Figure()
                    _fig_coef.add_trace(go.Scatter(
                        x=_coef_df["coef"], y=_coef_df["term"],
                        mode="markers",
                        marker=dict(size=10, color=_colors.tolist(),
                                    line=dict(width=1, color="white")),
                        error_x=dict(
                            type="data",
                            array=(_coef_df["hi"] - _coef_df["coef"]).tolist(),
                            arrayminus=(_coef_df["coef"] - _coef_df["lo"]).tolist(),
                            visible=True, thickness=1.8, color="#555",
                        ),
                        hovertemplate=(
                            "<b>%{y}</b><br>"
                            "coef = %{x:.4f}<br>"
                            "95 CI [%{customdata[0]:.4f}, %{customdata[1]:.4f}]<br>"
                            "p = %{customdata[2]:.4f}<extra></extra>"
                        ),
                        customdata=_coef_df[["lo","hi","pval"]].values,
                        name="",
                    ))
                    _fig_coef.add_vline(x=0, line_dash="dash", line_color="#888", line_width=1)
                    _fig_coef.update_layout(
                        title="Coefficient Plot — 95% CI (blue = p < 0.05)",
                        xaxis_title="Coefficient estimate",
                        yaxis=dict(autorange="reversed"),
                        height=max(280, len(_coef_df) * 36),
                        margin=dict(l=10, r=10, t=40, b=10),
                        plot_bgcolor="#fafbfc",
                    )
                    st.plotly_chart(_fig_coef, use_container_width=True)

                    # ── Styled coefficient table ──────────────────────────────
                    _tbl = _coef_df.copy()
                    _tbl["coef"]  = _tbl["coef"].map("{:+.4f}".format)
                    _tbl["se"]    = _tbl["se"].map("{:.4f}".format)
                    _tbl["95% CI"]= _tbl.apply(
                        lambda r: f"[{r['lo']:+.4f}, {r['hi']:+.4f}]", axis=1)
                    _tbl["p-val"] = _tbl["pval"].map(
                        lambda p: f"{p:.4f}" + (" ✱✱✱" if p<.001 else " ✱✱" if p<.01
                                                 else " ✱" if p<.05 else ""))
                    _tbl = _tbl[["term","coef","se","95% CI","p-val"]]
                    _tbl.columns = ["Term","Coef","Std Err","95% CI","p-value"]

                    def _highlight_sig(row):
                        raw_p = _coef_df.loc[
                            _coef_df["term"] == row["Term"], "pval"
                        ].values
                        p = raw_p[0] if len(raw_p) else 1.0
                        bg = "#dff0d8" if p < 0.05 else ""
                        return [f"background-color: {bg}"] * len(row)

                    st.dataframe(
                        _tbl.style.apply(_highlight_sig, axis=1),
                        hide_index=True, use_container_width=True,
                    )
                    st.caption(
                        "✱ p<0.05 · ✱✱ p<0.01 · ✱✱✱ p<0.001 · "
                        "Green rows = significant at 5%. "
                        "HC3 heteroscedasticity-robust standard errors."
                    )

        # ── SCENARIO 2 — Staggered DiD ────────────────────────────────────────
        elif selected_sc == 2:
            policy_banner(
                "Staggered Rollout — CCPA (CA 2020) · VCDPA (VA 2023) · CPA (CO 2023)",
                "CA / VA / CO", "2020 – 2023",
                "Three laws with different opt-in/out scopes adopted at different times. "
                "Callaway & Sant'Anna estimator avoids the biased 'early vs. late treated' "
                "comparison of classic TWFE.",
            )
            st.markdown(
                "**Business question:** Is there a consistent causal effect across all "
                "adopting states, or does it vary by law design and adoption cohort?"
            )

            # Compute per-cohort DiD using available data
            cohort_results = {}
            for st_code, law_yr in TREATED_STATES.items():
                if st_code in reg_df["state_code"].values:
                    r = run_standard_did(
                        reg_df, st_code, [s for s in ["TX", "FL", "OH"] if s in reg_df["state_code"].values],
                        (law_yr - 2, law_yr - 1), (law_yr, law_yr + 1), did_outcome,
                    )
                    cohort_results[st_code] = r

            c1, c2, c3 = st.columns(3)
            law_names = {"CA": "CCPA (broad)", "VA": "VCDPA (narrower)", "CO": "CPA (opt-in)"}
            for col, (st_code, r) in zip([c1, c2, c3], cohort_results.items()):
                with col:
                    att_metric(f"ATT — {st_code}\n({law_names.get(st_code, '')})",
                               r["estimate"], r["se"])

            st.markdown("---")

            # ATT(g,t) plot — approximate using year-by-year DiD estimates
            st.markdown("##### ATT Estimates by Cohort (years relative to law)")
            colours = {"CA": C_TREAT, "VA": "#ff7f0e", "CO": "#9467bd"}
            fig = go.Figure()
            for st_code, law_yr in TREATED_STATES.items():
                if st_code not in cohort_results:
                    continue
                est, se = cohort_results[st_code]["estimate"], cohort_results[st_code]["se"]
                ts = reg_df[
                    reg_df["state_code"].isin([st_code, "TX", "FL", "OH"])
                    & reg_df["activity_year"].between(law_yr - 2, law_yr + 2)
                ].copy()
                ts["rel"] = ts["activity_year"] - law_yr
                grp_avg = ts.groupby(["rel", "state_code"])[did_outcome].mean().unstack()
                if st_code in grp_avg.columns and "TX" in grp_avg.columns:
                    diff = grp_avg[st_code] - grp_avg[["TX", "FL", "OH"]].mean(axis=1)
                    diff = diff.dropna().reset_index()
                    fig.add_trace(go.Scatter(
                        x=diff["rel"], y=diff[0] * 100 if not diff.empty else [],
                        mode="lines+markers", name=st_code,
                        line=dict(color=colours[st_code], width=2),
                    ))
            fig.add_hline(y=0, line_dash="dash", line_color="#999")
            fig.add_vrect(x0=-0.5, x1=2.5, fillcolor=C_AMBER, opacity=1, line_width=0,
                          annotation_text="Post-law", annotation_position="top left")
            fig.update_layout(
                xaxis_title="Years relative to law enactment",
                yaxis_title=f"Δ {outcome_label(did_outcome)} (pp)",
                height=360, margin=dict(t=10, b=10), legend_title="State",
            )
            st.plotly_chart(fig, use_container_width=True)

            with st.expander("📐 Why Callaway & Sant'Anna?"):
                st.markdown("""
Classic TWFE DiD is **biased** in staggered adoption settings because it uses already-treated
units as controls for later-treated ones. Callaway & Sant'Anna (2021) constructs clean 2×2
comparisons for each cohort (g) × time (t) pair, then aggregates to a single ATT free from
contamination. Full C&S requires the `csdid` or `pyfixest` package — the estimates above use
cohort-specific standard DiD as an approximation.
                """)

        # ── SCENARIO 3 — Event Study ──────────────────────────────────────────
        elif selected_sc == 3:
            policy_banner(
                "Event Study — Dynamic Coefficients Around CCPA Enactment",
                "California vs. Control", f"Window t−{post_period[0]-pre_period[0]} to t+{post_period[1]-pre_period[1]+1}",
                "Dynamic DiD reveals *when* lender behaviour changed and validates the "
                "parallel-trends assumption via a pre-trend F-test.",
            )
            st.markdown(
                "**Business question:** When exactly did lenders change behaviour relative "
                "to CCPA's enactment date — and does the timing rule out alternative "
                "explanations?"
            )

            with st.spinner("Running event study…"):
                es_df = run_event_study(
                    reg_df, treat_state, ctrl_states,
                    pre_period, post_period, did_outcome,
                )

            if es_df.empty:
                st.warning("Not enough variation — try a wider year range in the sidebar.")
            else:
                pre_coefs = es_df[es_df["t"] < -1]["coef"]
                max_pre   = float(pre_coefs.abs().max()) if len(pre_coefs) else 0.0
                sig_flag  = max_pre < 0.015

                c1, c2 = st.columns(2)
                with c1:
                    kpi_card(
                        "Pre-trend test (max |β|)",
                        f"{max_pre:.4f}",
                        delta=("✅ Parallel trends supported" if sig_flag
                               else "⚠️ Pre-trend detected — interpret with caution"),
                        delta_color=C_APPROVE if sig_flag else C_DENY,
                    )
                with c2:
                    peak_row = es_df.loc[es_df["coef"].idxmin()]
                    kpi_card(
                        "Peak treatment effect",
                        f"t={int(peak_row.t):+d} → {peak_row.coef * 100:+.2f} pp",
                        delta="Years after law effective date",
                    )

                st.markdown("---")

                colors_es = [C_DENY if p < .05 else "#aec7e8" for p in es_df["pval"]]
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=es_df["t"], y=es_df["coef"] * 100,
                    error_y=dict(type="data",
                                 array=(es_df["hi"] - es_df["coef"]) * 100,
                                 arrayminus=(es_df["coef"] - es_df["lo"]) * 100,
                                 visible=True, thickness=1.5),
                    mode="markers+lines",
                    marker=dict(size=10, color=colors_es),
                    line=dict(color=C_TREAT, width=1.5),
                ))
                fig.add_hline(y=0, line_dash="dash", line_color="#aaa")
                fig.add_vline(x=-0.5, line_dash="dot", line_color=C_TREAT,
                              annotation_text="Law effective",
                              annotation_position="top right")
                if not pre_coefs.empty:
                    fig.add_vrect(
                        x0=float(es_df[es_df["t"] < -1]["t"].min()) - 0.5, x1=-0.5,
                        fillcolor="rgba(100,180,255,0.08)", opacity=1, line_width=0,
                        annotation_text="Pre-period (should ≈ 0)",
                        annotation_position="top left",
                    )
                shade_post_law(fig, 0, int(es_df["t"].max()))
                fig.update_layout(
                    xaxis_title="Period relative to law effective date (t=0)",
                    yaxis_title=f"β coefficient — {outcome_label(did_outcome)} (pp)",
                    height=380, margin=dict(t=10, b=10),
                )
                fig.update_xaxes(tickvals=list(es_df["t"].astype(int)),
                                 ticktext=[f"t{t:+d}" for t in es_df["t"].astype(int)])
                st.plotly_chart(fig, use_container_width=True)

                st.markdown("""
**Reading the chart:**
Coefficients before t=0 should be near zero (parallel-trends test). A downward slope
starting at t=0 shows lenders tightening credit post-CCPA. Significant pre-period
coefficients would invalidate the causal interpretation.
                """)

        # ── SCENARIO 4 — Triple DiD ───────────────────────────────────────────
        elif selected_sc == 4:
            policy_banner(
                "Triple DiD — Mechanism Test: Owner-Occupied vs. Investor Loans",
                "California vs. TX/FL/OH", "Pre/Post CCPA 2020",
                "CCPA protects *natural persons*, not LLCs or investor entities. "
                "If the law drives the effect it should concentrate in owner-occupied loans.",
            )
            st.markdown(
                "**Business question:** Did CCPA specifically harm owner-occupied applicants "
                "— who are CCPA-covered natural persons — more than investor borrowers who are "
                "outside the law's personal-data scope?"
            )

            # Build pre/post × owner/investor × CA/control table
            d4 = reg_df[
                reg_df["state_code"].isin([treat_state] + ctrl_states)
                & reg_df["activity_year"].between(pre_period[0], post_period[1])
            ].copy()
            d4["group"]  = d4["state_code"].apply(
                lambda s: f"{treat_state} (treated)" if s == treat_state else "Control")
            d4["period"] = d4["activity_year"].apply(
                lambda y: "Pre" if y <= pre_period[1] else "Post")
            d4 = _add_occupancy_label(d4)
            if d4["occ_label"].isna().all():
                st.warning(
                    "Triple DiD requires `is_investor_loan` or `occupancy_type` "
                    "in mart_regulatory_cohort."
                )
                st.stop()
            d4 = d4.dropna(subset=["occ_label"])

            agg4 = d4.groupby(["group", "occ_label", "period"])[did_outcome].mean().reset_index()

            # DiDiD
            def _mean(g, o, p):
                r = agg4[(agg4.group == g) & (agg4.occ_label == o) & (agg4.period == p)]
                return float(r[did_outcome].mean()) if not r.empty else 0.0

            ca_oo_pre  = _mean(f"{treat_state} (treated)", "Owner-Occupied", "Pre")
            ca_oo_post = _mean(f"{treat_state} (treated)", "Owner-Occupied", "Post")
            ca_inv_pre  = _mean(f"{treat_state} (treated)", "Investor", "Pre")
            ca_inv_post = _mean(f"{treat_state} (treated)", "Investor", "Post")
            ct_oo_pre  = _mean("Control", "Owner-Occupied", "Pre")
            ct_oo_post = _mean("Control", "Owner-Occupied", "Post")
            ct_inv_pre  = _mean("Control", "Investor", "Pre")
            ct_inv_post = _mean("Control", "Investor", "Post")

            didid = ((ca_oo_post - ca_oo_pre) - (ca_inv_post - ca_inv_pre)) - \
                    ((ct_oo_post - ct_oo_pre) - (ct_inv_post - ct_inv_pre))

            # Derive SE from OLS triple interaction so significance is data-driven
            _avail_covs4 = [c for c in COVARIATES if c in d4.columns]
            d4_reg = d4.dropna(subset=[did_outcome] + _avail_covs4).copy()
            d4_reg["_treat"] = (d4_reg["state_code"] == treat_state).astype(int)
            d4_reg["_post"]  = (d4_reg["activity_year"] > pre_period[1]).astype(int)
            d4_reg["_inv"]   = (d4_reg["occ_label"] == "Investor").astype(int)
            try:
                _mod3 = smf.ols(
                    f"{did_outcome} ~ _treat*_post*_inv + {' + '.join(_avail_covs4)} + C(state_code)",
                    data=d4_reg,
                ).fit(cov_type="HC3")
                _triple_key = "_treat:_post:_inv"
                didid_se = float(_mod3.bse.get(_triple_key, np.nan))
            except Exception:
                didid_se = float("nan")

            att_metric(
                "Triple DiD (DiDiD) — Owner-Occ vs. Investor in Treated vs. Control",
                didid, didid_se if np.isfinite(didid_se) else 0.0,
            )
            st.markdown("---")

            st.markdown(f"##### {outcome_label(did_outcome)} — by Group, Occupancy, Period")
            fig = px.bar(
                agg4, x="occ_label", y=did_outcome,
                color="period", facet_col="group", barmode="group",
                color_discrete_map={"Pre": C_CTRL, "Post": C_TREAT},
                text_auto=".3f" if "rate" not in did_outcome else ".1%",
                labels={did_outcome: outcome_label(did_outcome),
                        "occ_label": "Occupancy Type"},
            )
            if "rate" in did_outcome:
                fig.update_yaxes(tickformat=".0%")
            fig.update_layout(height=360, margin=dict(t=30, b=10))
            fig.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1]))
            st.plotly_chart(fig, use_container_width=True)

            st.markdown("""
**Mechanism logic:** If investor loans in the treated state also decline post-law at the same
rate as owner-occupied, the driver is likely a **state-level macro shock**, not the privacy law.
A large gap between owner-occupied and investor reactions (in the treated state but not in
controls) is the signature of CCPA's personal-data restriction mechanism.
            """)

        # ── SCENARIO 5 — Heterogeneous Treatment Effects ───────────────────────
        elif selected_sc == 5:
            policy_banner(
                "Heterogeneous Treatment Effects — Income Tier",
                "California vs. Control", "CCPA 2020",
                "Stratified OLS DiD and Interaction DiD by FFIEC income tier. "
                "Tests whether the CCPA lending impact falls disproportionately on lower-income borrowers.",
            )
            st.markdown(
                "**Business question:** Does the lending impact of CCPA fall "
                "disproportionately on lower-income borrowers?"
            )

            # Stratified DiD per income tier
            tier_order = ["low_income", "moderate_income", "middle_income", "high_income"]
            tier_labels = {
                "low_income": "Low", "moderate_income": "Moderate",
                "middle_income": "Middle", "high_income": "High",
            }
            tier_results = {}
            for tier in tier_order:
                sub = reg_df[reg_df["income_tier"] == tier]
                if len(sub) > 20:
                    r = run_standard_did(sub, treat_state, ctrl_states,
                                         pre_period, post_period, did_outcome)
                    tier_results[tier] = r

            # CATE bar chart
            if tier_results:
                cate_df = pd.DataFrame([
                    {"tier": tier_labels[t],
                     "cate": r["estimate"] * 100,
                     "lo":   r["ci"][0] * 100,
                     "hi":   r["ci"][1] * 100,
                     "sig":  r["pval"] < 0.05}
                    for t, r in tier_results.items()
                ])
                bar_colors = {
                    "Low":      C_DENY,
                    "Moderate": "#ff7f0e",
                    "Middle":   C_CTRL,
                    "High":     C_APPROVE,
                }
                fig = go.Figure()
                for _, row in cate_df.iterrows():
                    fig.add_trace(go.Bar(
                        y=[row["tier"]], x=[row["cate"]],
                        orientation="h",
                        name=row["tier"],
                        marker_color=bar_colors.get(row["tier"], C_TREAT),
                        error_x=dict(
                            type="data",
                            array=[row["hi"] - row["cate"]],
                            arrayminus=[row["cate"] - row["lo"]],
                            visible=True,
                        ),
                        text=f"{row['cate']:+.2f} pp",
                        textposition="outside",
                    ))
                fig.add_vline(x=0, line_dash="dash", line_color="#999")
                fig.update_layout(
                    xaxis_title=f"ATT — {outcome_label(did_outcome)} (pp)",
                    yaxis_title="FFIEC Income Tier",
                    showlegend=False, height=300,
                    margin=dict(t=10, b=10, l=10, r=80),
                )
                st.plotly_chart(fig, use_container_width=True)

            # KPI cards per tier
            st.markdown("##### Stratified ATT by Income Tier")
            cols5 = st.columns(len(tier_order))
            for col, tier in zip(cols5, tier_order):
                with col:
                    if tier in tier_results:
                        r = tier_results[tier]
                        att_metric(tier_labels[tier], r["estimate"], r["se"])

            st.markdown("---")

            # ── Interaction DiD: differential CATE by income tier ────────────
            st.markdown("##### Interaction DiD — Differential Treatment Effect by Income Tier")
            st.caption(
                "Single pooled regression with `did × C(income_tier)` interaction terms. "
                "Each coefficient = pp difference in CCPA effect relative to the "
                "**high-income** reference tier (HC3-robust SEs)."
            )
            if "income_tier" in reg_df.columns:
                d5 = reg_df[
                    reg_df["state_code"].isin([treat_state] + ctrl_states)
                    & reg_df["activity_year"].between(pre_period[0], post_period[1])
                    & reg_df[did_outcome].notna()
                    & reg_df["income_tier"].notna()
                ].copy()
                d5["treat"] = (d5["state_code"] == treat_state).astype(int)
                d5["post"]  = (d5["activity_year"] > pre_period[1]).astype(int)
                d5["did"]   = d5["treat"] * d5["post"]

                # Force high_income as reference so all interaction coefs show the
                # differential effect on lower tiers relative to the best-off group.
                _TIER_CAT = pd.CategoricalDtype(
                    categories=["high_income","middle_income","moderate_income","low_income"],
                    ordered=False,
                )
                d5["income_tier"] = d5["income_tier"].astype(_TIER_CAT)

                macro_cols = [c for c in COVARIATES if c in d5.columns]
                d5 = d5.dropna(subset=[did_outcome] + macro_cols)

                if len(d5) >= 20:
                    _cov_str = " + ".join(macro_cols)
                    _formula = (
                        f"{did_outcome} ~ treat + post + did"
                        f" + C(income_tier) + did:C(income_tier)"
                        + (f" + {_cov_str}" if _cov_str else "")
                        + " + C(state_code)"
                    )
                    _imod = smf.ols(_formula, data=d5).fit(cov_type="HC3")

                    # Extract did:C(income_tier)[T.xxx] interaction terms
                    _ref_tier = "high_income"
                    _tier_display = {
                        "low_income":      "Low",
                        "moderate_income": "Moderate",
                        "middle_income":   "Middle",
                        "high_income":     "High (ref)",
                    }
                    _irows = []
                    # Reference tier — by construction coef = 0
                    _irows.append({
                        "tier": _ref_tier,
                        "label": "High (ref)",
                        "coef": 0.0, "se": 0.0,
                        "lo": 0.0, "hi": 0.0, "pval": np.nan,
                    })
                    for _t in ["low_income", "moderate_income", "middle_income"]:
                        _key = f"did:C(income_tier)[T.{_t}]"
                        if _key in _imod.params:
                            _ci = _imod.conf_int().loc[_key]
                            _irows.append({
                                "tier":  _t,
                                "label": _tier_display[_t],
                                "coef":  float(_imod.params[_key]),
                                "se":    float(_imod.bse[_key]),
                                "lo":    float(_ci[0]),
                                "hi":    float(_ci[1]),
                                "pval":  float(_imod.pvalues[_key]),
                            })

                    # Also grab the baseline did coef (= high-income ATT)
                    _base_key = "did"
                    _base_coef = float(_imod.params.get(_base_key, np.nan))
                    _base_se   = float(_imod.bse.get(_base_key, np.nan))
                    _base_ci   = _imod.conf_int().loc[_base_key] if _base_key in _imod.conf_int().index else (np.nan, np.nan)
                    _base_pval = float(_imod.pvalues.get(_base_key, np.nan))

                    # Absolute ATT per tier = baseline (high) + interaction coef
                    for _r in _irows:
                        _r["abs_att"]    = _base_coef + _r["coef"]
                        _r["abs_att_lo"] = float(_base_ci[0]) + _r["lo"]
                        _r["abs_att_hi"] = float(_base_ci[1]) + _r["hi"]

                    _idf = pd.DataFrame(_irows)

                    # ── Coefficient forest plot ──────────────────────────────
                    _tier_colors_map = {
                        "Low":      "#d62728",
                        "Moderate": "#ff7f0e",
                        "Middle":   "#7f7f7f",
                        "High (ref)": "#2ca02c",
                    }
                    _fig_int = go.Figure()

                    # Absolute ATT bars
                    for _, _r in _idf.iterrows():
                        _sig = not np.isnan(_r["pval"]) and _r["pval"] < 0.05
                        _color = _tier_colors_map.get(_r["label"], "#333")
                        _fig_int.add_trace(go.Bar(
                            name=_r["label"],
                            x=[_r["label"]],
                            y=[_r["abs_att"] * 100],
                            marker_color=_color,
                            opacity=0.85,
                            error_y=dict(
                                type="data",
                                array=[(_r["abs_att_hi"] - _r["abs_att"]) * 100],
                                arrayminus=[(_r["abs_att"] - _r["abs_att_lo"]) * 100],
                                visible=True,
                            ),
                            text=f"{'✱ ' if _sig else ''}{_r['abs_att']*100:+.2f} pp",
                            textposition="outside",
                        ))

                    _fig_int.add_hline(y=0, line_dash="dash", line_color="#aaa")
                    _fig_int.update_layout(
                        title=f"Absolute ATT by Income Tier — {outcome_label(did_outcome)}",
                        yaxis_title="ATT (percentage points)",
                        xaxis_title="Income Tier",
                        showlegend=False, height=380,
                        margin=dict(t=45, b=10, l=10, r=80),
                    )
                    st.plotly_chart(_fig_int, use_container_width=True)

                    # ── Differential effect table ────────────────────────────
                    st.markdown("**Differential CATE vs. High-income (interaction coefficients)**")
                    _tbl_rows = []
                    for _, _r in _idf.iterrows():
                        _star = "" if np.isnan(_r["pval"]) else (
                            " ✱✱✱" if _r["pval"] < .001 else
                            " ✱✱"  if _r["pval"] < .01  else
                            " ✱"   if _r["pval"] < .05  else " n.s.")
                        _tbl_rows.append({
                            "Tier":               _r["label"],
                            "Abs ATT (pp)":       f"{_r['abs_att']*100:+.2f}",
                            "Δ vs High-inc (pp)": f"{_r['coef']*100:+.2f}" if not np.isnan(_r["pval"]) else "—",
                            "95% CI (Δ)":         f"[{_r['lo']*100:+.2f}, {_r['hi']*100:+.2f}]" if not np.isnan(_r["pval"]) else "ref",
                            "p-value":            f"{_r['pval']:.4f}{_star}" if not np.isnan(_r["pval"]) else "—",
                        })

                    def _hl_int(row):
                        raw = _idf.loc[_idf["label"] == row["Tier"], "pval"].values
                        p = raw[0] if len(raw) else 1.0
                        bg = "#dff0d8" if (not np.isnan(p) and p < 0.05) else ""
                        return [f"background-color: {bg}"] * len(row)

                    st.dataframe(
                        pd.DataFrame(_tbl_rows).style.apply(_hl_int, axis=1),
                        hide_index=True, use_container_width=True,
                    )

                    # ── Joint F-test of heterogeneity ────────────────────────
                    _int_keys = [k for k in _imod.params.index
                                 if k.startswith("did:C(income_tier)")]
                    if _int_keys:
                        from statsmodels.stats.anova import anova_lm
                        _ftest = _imod.f_test(
                            [f"({k} = 0)" for k in _int_keys]
                        )
                        _fp  = float(_ftest.pvalue)
                        _fv  = float(_ftest.fvalue.flat[0]) if hasattr(_ftest.fvalue, "flat") else float(_ftest.fvalue)
                        _verdict = "✅ Heterogeneity is statistically significant" if _fp < 0.10 \
                                   else "⚠️ No statistically significant heterogeneity detected"
                        st.info(
                            f"**Joint F-test of `did × income_tier` interactions**: "
                            f"F = {_fv:.2f}, p = {_fp:.4f} — {_verdict} at 10% level.",
                            icon="📐",
                        )

                    # ── Disparity metric ─────────────────────────────────────
                    _low_row  = _idf[_idf["tier"] == "low_income"]
                    _high_row = _idf[_idf["tier"] == "high_income"]
                    if not _low_row.empty and not _high_row.empty:
                        _disp = (_low_row["abs_att"].values[0] - _high_row["abs_att"].values[0]) * 100
                        _disp_dir = "larger negative" if _disp < 0 else "larger positive"
                        st.metric(
                            label="Low-income vs High-income ATT disparity",
                            value=f"{_disp:+.2f} pp",
                            help="Positive = low-income borrowers benefited more (or were hurt less). "
                                 "Negative = low-income borrowers were hurt more by CCPA.",
                        )
                else:
                    st.info("Not enough observations for interaction DiD after filtering.")
            else:
                st.info("Column `income_tier` not found in data — interaction DiD unavailable.")

            st.markdown("""
**Policy implication:** A privacy law that restricts lender data access sounds consumer-friendly
— but if thin-file, low-income borrowers lose more credit access than prime borrowers (who have
long credit histories independent of third-party behavioural data), CCPA could **widen the
credit-access gap by income** without any discriminatory intent. A negative ATT disparity
(low-income hurt more than high-income) is the most policy-relevant finding of this scenario.
            """)


# ═════════════════════════════════════════════════════════════════════════════
# FOOTER
# ═════════════════════════════════════════════════════════════════════════════

st.divider()
sc_txt = "✅ scenarios package loaded" if SCENARIOS_AVAILABLE else "ℹ️ scenarios package not found"
st.caption(
    f"FinLens · 🟢 Live · BigQuery · {sc_txt} · "
    "Data: HMDA (CFPB) 2018–2023 · Macro: FRED (St. Louis Fed) · "
    "Stack: BigQuery · dbt · Airflow · Streamlit + Plotly"
)

# %%
