# FinLens — Mortgage Analytics & Privacy Law Impact Platform

A causal inference research platform analyzing the effect of US consumer data privacy laws (CCPA, VCDPA, CPA) on mortgage lending outcomes using HMDA data from 2018–2023.

**Live Demo:** https://finlens-app-360526413047.us-central1.run.app/

---

## Overview

FinLens investigates whether state-level consumer data privacy regulation has a measurable effect on mortgage credit access. The platform ingests loan-level HMDA application data and macroeconomic FRED series, transforms them through a dbt pipeline into analysis-ready marts, and runs five causal inference (difference-in-differences) scenarios against the result. Findings are surfaced through a two-tab Streamlit app and a presentation deck for stakeholder review.

### Business / Research Questions

1. **Do consumer data privacy laws reduce mortgage approval rates?** — Does CCPA in California show a measurable drop in approvals relative to control states?
2. **Do any effects fall disproportionately on lower-income borrowers?** — Is there a widening credit-access gap by income tier under privacy regulation?
3. **Does the investor loan channel behave differently from owner-occupied loans under privacy regulation?** — Are data-broker-dependent investor loans more exposed to CCPA's data restrictions than owner-occupied loans?

**Laws studied:**

| Law | State | Effective | Scope |
|---|---|---|---|
| **CCPA** | California | January 2020 | Broad opt-out rights — most comprehensive US state privacy law |
| **VCDPA** | Virginia | January 2023 | Narrower opt-out scope; controller/processor framework |
| **CPA** | Colorado | July 2023 | Opt-in for sensitive data; universal opt-out mechanism |

---

## Key Components

| Component | Role |
|---|---|
| **`ingest/ingest_latest.py`** | Pulls HMDA loan-level records and FRED macro series into BigQuery raw tables |
| **`finlens_dbt/`** | dbt Core project — staging → intermediate → marts transformation layer |
| **`scenarios/`** | Five causal inference (DiD) scenario modules + shared base class and runner |
| **`app/finlens_app.py`** | Two-tab Streamlit app — lending funnel overview and privacy law impact explorer |
| **`airflow/dags/`** | Airflow DAGs for orchestrating ingestion and dbt runs |
| **`outputs/build_pptx.js`** | Generates the stakeholder-facing FinLens presentation deck (`FinLens_Presentation.pptx`) |
| **`config.py`** | Central frozen-dataclass config — env vars, domain constants, BigQuery dataset/table helpers |
| **Cloud Run + Cloud Scheduler** | Production deployment — scale-to-zero Streamlit service + scheduled monthly pipeline job |

---

## Data Sources

| Source | Coverage | Key Fields |
|---|---|---|
| **HMDA** (CFPB) | 2018–2023, 9 states | `action_taken`, `loan_amount`, `income`, LTV, DTI bucket, loan type |
| **FRED** (St. Louis Fed) | 2018–2023, state-level | `unemployment_rate`, HPI, 30-year mortgage rate |

**States:** CA, TX, FL, OH, NY, IL, WA, CO, VA

- **Treatment states:** CA (2020), VA (2023), CO (2023)
- **Control states:** TX, FL, OH, NY, IL

---

## Methods & Tools

### Architecture

```
HMDA (CFPB API)          FRED (St. Louis Fed API)
     │                          │
     └──────────┬───────────────┘
                ▼
        ingest/ingest_latest.py
                │
                ▼
         BigQuery (raw)
          raw_hmda.hmda_lar_raw
          raw_fred.fred_macro_raw
                │
                ▼
         dbt Core (finlens_dbt)
          staging → intermediate → marts
                │
                ▼
         BigQuery (marts)
          finlens_dev_marts.*
                │
                ▼
         Streamlit App
          app/finlens_app.py
```

**Stack:** BigQuery · dbt Core · Streamlit · Python (statsmodels) · Airflow · Cloud Run · Cloud Scheduler

### Causal Inference Models (ML / Statistical)

All models use **HC3-robust OLS** via `statsmodels`. The parallel-trends identifying assumption is tested directly in Scenario 3.

| Scenario | Method | Treatment | Outcome |
|---|---|---|---|
| **S1 — Standard DiD** | 2×2 Difference-in-Differences | CA vs. TX/FL/OH (pre/post 2020) | `approval_rate` |
| **S2 — Staggered DiD** | Callaway & Sant'Anna approximation | CA/VA/CO cohorts | `approval_rate` |
| **S3 — Event Study** | Dynamic DiD with leads & lags | CA CCPA (t=−4 to t+3) | `approval_rate` |
| **S4 — Triple DiD** | CA × Post × InvestorLoan | Investor vs. owner-occupied | `approval_rate` |
| **S5 — Income Tier HTE** | Interaction DiD × income_tier | CA vs. controls | `approval_rate` |

**Outcome columns available:** `approval_rate`, `origination_rate`, `denial_rate`, `avg_ltv`, `avg_dti`

### dbt Models

**Staging**
| Model | Description |
|---|---|
| `stg_hmda_lar` | Cleaned HMDA loan-level records with derived fields (LTV, DTI bucket, income tier) |
| `stg_fred_macro` | Pivoted FRED macro series by state × year |

**Intermediate**
| Model | Description |
|---|---|
| `int_applications_enriched` | HMDA joined with FRED macro controls |
| `int_approval_flags` | Binary flags: `is_approved`, `is_originated`, `is_denied` |
| `int_loan_cohorts` | Treatment × post indicators, regulatory era labels, staggered DiD cohorts |

**Marts**
| Model | Description |
|---|---|
| `mart_regulatory_cohort` | State × year panel with approval rate, denial rate, avg LTV, avg DTI, macro controls — primary DiD input |
| `mart_lending_funnel` | Application → approval → origination funnel by state, year, loan type |
| `mart_unit_economics` | Avg loan amount, income, interest rate by income tier and state |
| `mart_kpi_dashboard` | Aggregated KPIs for Streamlit overview tab |

> **DTI note:** HMDA stores DTI as categorical buckets (`<20%`, `20%-<30%`, etc.). The mart maps each bucket to its numeric midpoint and averages to produce `avg_dti`.

### Streamlit App

Two-tab layout:

**Tab 1 — Mortgage Market Overview**
- Funnel KPIs (applications → approvals → originations)
- State-level trends and comparisons
- Loan type and income tier breakdowns

**Tab 2 — Privacy Law Impact**
- Scenario selector (S1–S5)
- DiD coefficient chart with confidence intervals
- Treatment vs. control trend lines
- Event study dynamic plot
- Income tier heterogeneity bar chart

---

## Key Findings

- **No statistically significant aggregate effect** of CCPA on mortgage approval rates (DiD ATT: +3.24 pp, p = 0.54)
- **Directional income disparity:** low-income borrowers saw +1.32 pp vs. +3.85 pp for high-income borrowers — a −2.53 pp gap, though not statistically significant (F = 0.11, p = 0.95)
- **Investor loan channel** warrants further investigation via Triple DiD — data-broker dependence is a plausible differential exposure mechanism
- **Data limitation:** state × year aggregation limits statistical power; individual loan-level analysis is recommended for definitive conclusions

---

## File Structure

```
Finlens/
├── app/
│   └── finlens_app.py          # Streamlit application (2-tab layout)
├── finlens_dbt/
│   ├── models/
│   │   ├── staging/            # stg_hmda_lar, stg_fred_macro
│   │   ├── intermediate/       # int_* enrichment and flag models
│   │   └── marts/              # mart_* aggregated analytical tables
│   ├── profiles.yml            # BigQuery connection (dev=oauth)
│   └── dbt_project.yml
├── ingest/
│   └── ingest_latest.py        # HMDA + FRED ingestion to BigQuery
├── scenarios/
│   ├── base.py                  # Shared DiD base class
│   ├── runner.py                # Scenario dispatcher
│   ├── scenario_s1_did.py       # Standard 2×2 DiD
│   ├── scenario_s2_staggered.py # Staggered DiD
│   ├── scenario_s3_event.py     # Event study
│   ├── scenario_s4_triple.py    # Triple DiD
│   └── scenario_s5_hte.py       # Income tier heterogeneity
├── airflow/
│   └── dags/                    # Airflow orchestration DAGs
├── outputs/
│   ├── build_pptx.js            # Node.js PPTX presentation builder
│   └── FinLens_Presentation.pptx
├── docs/
│   ├── deploy_cloud_run.md      # Full GCP deployment runbook
│   └── deployment_protocol.md
├── tests/                       # Data quality + scenario unit tests
├── config.py                    # Central config (env vars + domain constants)
├── Dockerfile                   # Cloud Run Service image (Streamlit app)
├── Dockerfile.pipeline          # Cloud Run Job image (ingest + dbt)
├── cloudbuild.yaml              # CI/CD: build + push + deploy on git push
├── Makefile                     # All dev + deploy commands
├── .env.example                 # Environment variable template
└── requirements.txt             # Python dependencies
```

---

## Installation & Setup

### 1. Prerequisites

```bash
# Python virtual environment
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Google Cloud authentication
gcloud auth login
gcloud auth application-default login
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env: set GCP_PROJECT, FRED_API_KEY, and other values
make env-check   # verify vars loaded
```

### 3. Build marts

```bash
make dbt-all     # run all dbt models + tests against BigQuery
```

### 4. Run the app

```bash
make app         # starts Streamlit on http://localhost:8501
```

---

## Cloud Deployment (GCP)

Deployment uses **Cloud Scheduler + Cloud Run Jobs** (Option A, scale-to-zero).
Full instructions: [`docs/deploy_cloud_run.md`](docs/deploy_cloud_run.md)

**Quick start:**

```bash
make setup-gcp      # one-time: enable APIs, create service account + IAM roles
make dbt-all        # build marts in BigQuery first
make deploy-all     # build + push Docker images + deploy to Cloud Run
```

**Monthly pipeline** runs automatically on the 1st of each month at 6:00 AM ET via Cloud Scheduler → Cloud Run Job:
1. `ingest_latest.py` → pulls HMDA + FRED data into BigQuery raw
2. `dbt run --select marts` → builds all mart tables
3. `dbt test` → validates data quality

### Cost estimate

| Component | Monthly cost |
|---|---|
| Cloud Scheduler (1 job) | Free |
| Cloud Run Job (1 run × 30 min) | Free |
| Cloud Run Service (scale-to-zero) | Free |
| BigQuery (~8 GB storage + queries) | Free |
| Artifact Registry (~500 MB) | ~$0.05 |
| **Total** | **~$0.05/month** |

---

## Makefile Reference

```bash
# Local development
make app              # run Streamlit locally on :8501
make dbt-run          # run all dbt models
make dbt-test         # run dbt tests
make dbt-mart         # run mart_regulatory_cohort only
make dbt-all          # dbt-run + dbt-test
make env-check        # print loaded env vars

# Docker
make build-app        # build Streamlit app image (linux/amd64)
make build-pipeline   # build ingest+dbt pipeline image (linux/amd64)
make push-app         # push app image to Artifact Registry
make push-pipeline    # push pipeline image to Artifact Registry

# Deploy
make deploy-app       # build + push + deploy Streamlit app to Cloud Run
make deploy-pipeline  # build + push + deploy pipeline job to Cloud Run
make deploy-all       # full build + push + deploy for both

# Ops
make run-pipeline     # manually trigger ingest + dbt now
make logs-pipeline    # view Cloud Run Job logs
make logs-app         # view Cloud Run Service logs
make setup-gcp        # one-time GCP setup (APIs, SA, IAM, registry)
```

---

## Requirements

- Python 3.11+
- Google Cloud project with BigQuery enabled
- FRED API key (free at https://fred.stlouisfed.org/docs/api/api_key.html)
- `gcloud` CLI authenticated via Application Default Credentials
- Docker Desktop (for Cloud Run deployment)
- Node.js + pptxgenjs (for PPTX presentation generation only)

---

## Acknowledgments

- **[Consumer Financial Protection Bureau (CFPB)](https://ffiec.cfpb.gov/)** — HMDA Loan/Application Register (LAR) data
- **[Federal Reserve Bank of St. Louis (FRED)](https://fred.stlouisfed.org/)** — state-level unemployment, HPI, and mortgage rate series
- **[dbt Labs](https://www.getdbt.com/)** — dbt Core transformation framework
- **[statsmodels](https://www.statsmodels.org/)** — HC3-robust OLS regression used across all DiD scenarios
- **[Streamlit](https://streamlit.io/)** — analytics app framework
- **Google Cloud Platform** — BigQuery, Cloud Run, Cloud Scheduler, Artifact Registry
