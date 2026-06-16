# FinLens — Regulatory Analytics Platform for Consumer Lending
### Complete Build Guide: BigQuery · dbt · Airflow · DiD · Synthetic Controls · Streamlit

---

## Table of Contents

1. [Project Architecture Overview](#1-architecture)
   - [1.1 Central Configuration (`config.py`)](#11-central-configuration-configpy)
2. [BigQuery Setup — Step by Step](#2-bigquery-setup)
3. [Data Ingestion: HMDA + FRED API](#3-data-ingestion)
4. [dbt Model Architecture](#4-dbt-model-architecture)
5. [Orchestration with Airflow](#5-orchestration-with-airflow)
6. [DiD Analysis — 5 Use Cases](#6-did-analysis)
7. [Synthetic Control Method](#7-synthetic-control-method)
8. [Regulatory Impact on Real Estate Investor ROI](#8-real-estate-investor-roi-impact)
9. [Streamlit App — Funnel Dashboard + Regulatory Explorer](#9-streamlit-app)
10. [Portfolio Narrative Map](#10-portfolio-narrative-map)
11. [**Scenario Testing Framework — 5 Privacy Law Impact Scenarios**](#11-scenario-testing-framework)

---

## 1. Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                          FinLens Data Stack                              │
├─────────────────┬─────────────────────┬──────────────────────────────────┤
│    Ingestion    │      Warehouse       │           Consume                │
│                 │                      │                                  │
│  HMDA CSVs      │   Google BigQuery    │   Streamlit Cloud                │
│  (CFPB)     ───►│   (free tier:        │   ┌──────────────────────┐      │
│                 │    10 GB storage,    │   │  Tab 1: Lending      │      │
│  FRED API   ───►│    1 TB queries/mo)  │   │  Funnel Dashboard    │      │
│                 │                      │   │  (replaces Tableau)  │      │
│  Airflow DAGs   │   dbt Core           │   ├──────────────────────┤      │
│  (orchestrate)  │   stg → int → mart  │   │  Tab 2: Regulatory   │      │
│                 │                      │   │  Impact Explorer     │      │
│  Python         │   DiD / Synth Ctrl  │   │  (DiD + ROI)         │      │
│  (causal layer) │   (runs on marts)   │   └──────────────────────┘      │
└─────────────────┴─────────────────────┴──────────────────────────────────┘

Free tier summary:
  BigQuery   — 10 GB storage free, 1 TB queries/month free (no trial clock)
  dbt Core   — free, open source
  Airflow    — free, self-hosted locally
  Streamlit  — free deploy on Streamlit Community Cloud
```

**Stack changes from Snowflake version:**
- `snowflake-connector-python` → `google-cloud-bigquery`
- `dbt-snowflake` → `dbt-bigquery`
- Warehouses/schemas → GCP Projects/Datasets
- Airflow SnowflakeHook/Operator → BigQueryHook/Operator
- Tableau Public → Streamlit (Tab 1: funnel, Tab 2: regulatory explorer)

---

### 1.1 Central Configuration (`config.py`)

All environment-dependent settings and shared domain constants live in a single frozen dataclass in `config.py` at the project root. Every other module imports it with one line — no scattered `os.environ` calls, no duplicated lists.

```python
from config import cfg

client = bigquery.Client(project=cfg.project)
key    = cfg.fred_api_key
states = cfg.ingest_states
```

`config.py` auto-discovers and loads the nearest `.env` file on import, so all other modules stay clean.

**Loading priority (highest → lowest):**
1. Real environment variables — shell / CI / Cloud Run
2. `.env` file in the project root — local development
3. Built-in defaults

#### Environment variables

| Variable | Description | Default |
|---|---|---|
| `GCP_PROJECT` | Google Cloud project ID | *(required)* |
| `GCP_REGION` | BigQuery dataset location | `US` |
| `FRED_API_KEY` | FRED API key | *(required for ingestion)* |
| `HMDA_DATA_DIR` | Local cache directory for HMDA CSVs | `./data/hmda` |

> `GOOGLE_APPLICATION_CREDENTIALS` is **not** needed — authentication uses ADC
> (`gcloud auth application-default login`). The Python BigQuery client picks it up automatically.

Copy `.env.example` to `.env` and fill in your values before running anything:

```bash
cp .env.example .env
# edit .env — set GCP_PROJECT and FRED_API_KEY (no credentials path needed)
```

#### Domain constants

These are declared once in `config.py` and imported everywhere via `cfg.*`. Never re-declare them in other files.

| `cfg` attribute | Value | Consumed by |
|---|---|---|
| `cfg.states` | `["CA","TX","FL","OH","NY","IL"]` | App dashboard filters |
| `cfg.ingest_states` | `["CA","TX","FL","OH","NY","IL","WA"]` | HMDA/FRED ingestion (WA added for broader FRED coverage) |
| `cfg.default_control_states` | `["TX","FL","OH","NY","IL"]` | DiD / synthetic-control donor pool default |
| `cfg.hmda_min_year` | `2018` | Ingestion year-range floor |
| `cfg.app_years` | `[2018 … 2023]` | App year slider |
| `cfg.loan_types` | `["conventional","fha","va","usda"]` | App multiselect |
| `cfg.income_tiers` | `["low_income",…,"high_income"]` | App multiselect |
| `cfg.covariates` | `["unemployment_rate","hpi","mortgage_rate_30yr"]` | DiD regression controls |
| `cfg.cfpb_url_template` | `https://ffiec.cfpb.gov/…/{year}/…` | CFPB bulk-download URL |

#### BigQuery dataset references

| `cfg` attribute | Dataset | Helper |
|---|---|---|
| `cfg.bq_dataset_raw_hmda` | `raw_hmda` | `cfg.table("raw_hmda", "lar_2023")` |
| `cfg.bq_dataset_raw_fred` | `raw_fred` | |
| `cfg.bq_dataset_staging` | `staging` | |
| `cfg.bq_dataset_intermediate` | `intermediate` | |
| `cfg.bq_dataset_marts` | `marts` | `cfg.mart("mart_lending_funnel")` |

#### Helper methods

```python
cfg.table("raw_hmda", "lar_2023")   # → "your-project.raw_hmda.lar_2023"
cfg.mart("mart_lending_funnel")      # → "your-project.marts.mart_lending_funnel"
cfg.validate()                       # raises EnvironmentError if required vars are missing
cfg.print_dbt_profile()              # prints a ready-to-paste profiles.yml snippet
```

#### Verify your setup

```bash
python config.py --validate   # checks GCP_PROJECT and FRED_API_KEY are set
python config.py --dbt        # prints profiles.yml snippet
```

---

## 2. BigQuery Setup

### 2.1 Create GCP Project

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Click **Select a project → New Project**
   - Name: `finlens-analytics`
   - Note your **Project ID** (e.g., `project-58b73547-8fb7-4cff-b60`)
3. Enable billing (required for BigQuery, but free tier covers this project)
4. Enable the BigQuery API: **APIs & Services → Enable APIs → BigQuery API → Enable**

### 2.2 Authenticate with Application Default Credentials (ADC)

> **Note:** JSON service-account key creation is blocked by the org policy
> `constraints/iam.disableServiceAccountKeyCreation`. FinLens uses
> **Application Default Credentials (ADC)** throughout — no key file needed.

```bash
# Install gcloud CLI first: https://cloud.google.com/sdk/docs/install
gcloud auth login
gcloud config set project project-58b73547-8fb7-4cff-b60

# Authenticate ADC — this is the only credential step needed
gcloud auth application-default login

# Verify ADC is active
unset GOOGLE_APPLICATION_CREDENTIALS
gcloud auth application-default print-access-token
```

Grant your **user account** (or a service account if running in CI) BigQuery roles:

```bash
PROJECT="project-58b73547-8fb7-4cff-b60"
USER="ellac.ndalla@gmail.com"   # replace with your Google account

gcloud projects add-iam-policy-binding $PROJECT \
    --member="user:$USER" \
    --role="roles/bigquery.dataEditor"

gcloud projects add-iam-policy-binding $PROJECT \
    --member="user:$USER" \
    --role="roles/bigquery.jobUser"
```

All Python clients (`google-cloud-bigquery`, dbt, Airflow) pick up ADC automatically —
no `GOOGLE_APPLICATION_CREDENTIALS` env variable is required.

### 2.3 Create BigQuery Datasets

BigQuery uses **Datasets** where Snowflake used schemas. Run in the BigQuery console or via CLI:

```bash
# Via gcloud CLI
PROJECT="project-58b73547-8fb7-4cff-b60"
REGION="US"   # multi-region — best for free tier (no egress charges within US)

for dataset in raw_hmda raw_fred staging intermediate marts; do
  bq mk \
    --dataset \
    --location=$REGION \
    --description="FinLens: $dataset layer" \
    ${PROJECT}:${dataset}
  echo "Created dataset: $dataset"
done
```

Or in Python:

```python
# setup/create_datasets.py
from google.cloud import bigquery

PROJECT = "project-58b73547-8fb7-4cff-b60"
REGION  = "US"

client   = bigquery.Client(project=PROJECT)
datasets = ["raw_hmda", "raw_fred", "staging", "intermediate", "marts"]

for ds_id in datasets:
    dataset = bigquery.Dataset(f"{PROJECT}.{ds_id}")
    dataset.location = REGION
    client.create_dataset(dataset, exists_ok=True)
    print(f"Dataset ready: {ds_id}")
```

### 2.4 Create Raw Tables

```python
# setup/create_tables.py
from google.cloud import bigquery

PROJECT = "project-58b73547-8fb7-4cff-b60"
client  = bigquery.Client(project=PROJECT)

# ── HMDA LAR raw table ───────────────────────────────────────────────
hmda_schema = [
    bigquery.SchemaField("activity_year",               "INTEGER"),
    bigquery.SchemaField("state_code",                  "STRING"),
    bigquery.SchemaField("county_code",                 "STRING"),
    bigquery.SchemaField("action_taken",                "INTEGER"),
    bigquery.SchemaField("loan_type",                   "INTEGER"),
    bigquery.SchemaField("loan_purpose",                "INTEGER"),
    bigquery.SchemaField("loan_amount",                 "FLOAT64"),
    bigquery.SchemaField("property_value",              "FLOAT64"),
    bigquery.SchemaField("interest_rate",               "FLOAT64"),
    bigquery.SchemaField("rate_spread",                 "FLOAT64"),
    bigquery.SchemaField("combined_loan_to_value_ratio","FLOAT64"),
    bigquery.SchemaField("income",                      "FLOAT64"),
    bigquery.SchemaField("debt_to_income_ratio",        "STRING"),
    bigquery.SchemaField("applicant_credit_score_type", "INTEGER"),
    bigquery.SchemaField("denial_reason_1",             "INTEGER"),
    bigquery.SchemaField("denial_reason_2",             "INTEGER"),
    bigquery.SchemaField("derived_loan_product_type",   "STRING"),
    bigquery.SchemaField("derived_dwelling_category",   "STRING"),
    bigquery.SchemaField("derived_race",                "STRING"),
    bigquery.SchemaField("derived_sex",                 "STRING"),
    bigquery.SchemaField("applicant_age",               "STRING"),
    bigquery.SchemaField("lien_status",                 "INTEGER"),
    bigquery.SchemaField("occupancy_type",              "INTEGER"),
    bigquery.SchemaField("loan_term",                   "INTEGER"),
    bigquery.SchemaField("total_units",                 "STRING"),
    bigquery.SchemaField("_loaded_at",                  "TIMESTAMP"),
]

hmda_table = bigquery.Table(f"{PROJECT}.raw_hmda.hmda_lar_raw", schema=hmda_schema)
hmda_table.time_partitioning = bigquery.TimePartitioning(
    type_=bigquery.TimePartitioningType.DAY,
    field="_loaded_at",
)
hmda_table.clustering_fields = ["state_code", "activity_year"]
client.create_table(hmda_table, exists_ok=True)
print("Created: raw_hmda.hmda_lar_raw (partitioned + clustered)")

# ── FRED macro raw table ─────────────────────────────────────────────
fred_schema = [
    bigquery.SchemaField("series_id",    "STRING"),
    bigquery.SchemaField("state_code",   "STRING"),
    bigquery.SchemaField("metric_name",  "STRING"),
    bigquery.SchemaField("period_date",  "DATE"),
    bigquery.SchemaField("value",        "FLOAT64"),
    bigquery.SchemaField("_loaded_at",   "TIMESTAMP"),
]

fred_table = bigquery.Table(f"{PROJECT}.raw_fred.fred_macro_raw", schema=fred_schema)
client.create_table(fred_table, exists_ok=True)
print("Created: raw_fred.fred_macro_raw")
```

> **Free tier tip:** Clustering on `state_code` + `activity_year` means BigQuery scans only the relevant partitions for state/year filters — dramatically reduces bytes billed against your 1 TB monthly quota.

---

## 3. Data Ingestion

### 3.1 Install Dependencies

```bash
pip install google-cloud-bigquery google-cloud-bigquery-storage \
    pandas pyarrow requests tqdm
```

### 3.2 Download HMDA Data

```bash
mkdir -p ~/finlens/data/hmda

for year in 2018 2019 2020 2021 2022 2023; do
  echo "Downloading HMDA LAR $year..."
  curl -L \
    "https://ffiec.cfpb.gov/data-browser/data/${year}/csv?category=states" \
    -o ~/finlens/data/hmda/hmda_lar_${year}.zip
  unzip ~/finlens/data/hmda/hmda_lar_${year}.zip \
    -d ~/finlens/data/hmda/${year}/
done

# For faster prototyping — single state slice via CFPB Data Browser:
# https://ffiec.cfpb.gov/data-browser/ → filter by state → download CSV
```

### 3.3 HMDA Ingestion → BigQuery

```python
# ingestion/load_hmda.py
import os
import glob
import argparse
from datetime import datetime, timezone
import pandas as pd
from google.cloud import bigquery

PROJECT   = "project-58b73547-8fb7-4cff-b60"
TABLE_ID  = f"{PROJECT}.raw_hmda.hmda_lar_raw"
DATA_DIR  = os.path.expanduser("~/finlens/data/hmda")

KEEP_COLS = [
    "activity_year", "state_code", "county_code",
    "action_taken", "loan_type", "loan_purpose",
    "loan_amount", "property_value", "interest_rate", "rate_spread",
    "combined_loan_to_value_ratio", "income", "debt_to_income_ratio",
    "applicant_credit_score_type", "denial_reason_1", "denial_reason_2",
    "derived_loan_product_type", "derived_dwelling_category",
    "derived_race", "derived_sex", "applicant_age",
    "lien_status", "occupancy_type", "loan_term", "total_units",
]

NUMERIC_COLS = [
    "loan_amount", "property_value", "interest_rate", "rate_spread",
    "combined_loan_to_value_ratio", "income",
]

INT_COLS = [
    "activity_year", "action_taken", "loan_type", "loan_purpose",
    "applicant_credit_score_type", "denial_reason_1", "denial_reason_2",
    "lien_status", "occupancy_type", "loan_term",
]

def load_year(year: int, client: bigquery.Client):
    files = glob.glob(f"{DATA_DIR}/{year}/*.csv")
    if not files:
        print(f"  No files for {year} — skipping")
        return

    dfs = []
    for f in files:
        print(f"  Reading {os.path.basename(f)}...")
        df = pd.read_csv(
            f,
            usecols=lambda c: c in KEEP_COLS,
            dtype=str,
            na_values=["NA", "Exempt", "", "null", "nan"],
            low_memory=False,
        )
        dfs.append(df)

    df = pd.concat(dfs, ignore_index=True)
    df["activity_year"] = year

    # Cast types
    for col in NUMERIC_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in INT_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")

    df["_loaded_at"] = datetime.now(timezone.utc)

    print(f"  Loading {len(df):,} rows for {year} → BigQuery...")

    job_config = bigquery.LoadJobConfig(
        write_disposition = bigquery.WriteDisposition.WRITE_APPEND,
        schema_update_options = [
            bigquery.SchemaUpdateOption.ALLOW_FIELD_ADDITION
        ],
        # Use parquet for reliable type inference
        source_format = bigquery.SourceFormat.PARQUET,
    )

    # Load via parquet (faster + type-safe vs CSV)
    job = client.load_table_from_dataframe(df, TABLE_ID, job_config=job_config)
    job.result()   # wait for completion
    print(f"  Done — {year}: {job.output_rows:,} rows loaded")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=None,
                        help="Single year to load; omit for all years")
    args   = parser.parse_args()
    client = bigquery.Client(project=PROJECT)

    years = [args.year] if args.year else list(range(2018, 2024))
    for year in years:
        print(f"\n=== HMDA {year} ===")
        load_year(year, client)

    print("\nIngestion complete.")

if __name__ == "__main__":
    main()
```

### 3.4 FRED API Ingestion → BigQuery

```python
# ingestion/load_fred.py
import os
import requests
import pandas as pd
from datetime import datetime, timezone, date
from google.cloud import bigquery

PROJECT   = "project-58b73547-8fb7-4cff-b60"
TABLE_ID  = f"{PROJECT}.raw_fred.fred_macro_raw"
FRED_KEY  = os.environ["FRED_API_KEY"]
BASE_URL  = "https://api.stlouisfed.org/fred/series/observations"

# NOTE: in ingest/ingest_latest.py this comes from cfg.ingest_states
STATES = ["CA", "TX", "FL", "OH", "NY", "IL", "WA", "CO", "VA"]

SERIES_TEMPLATES = {
    "unemployment_rate": "{state}UR",
    "hpi":               "{state}STHPI",
}

NATIONAL_SERIES = {
    "mortgage_rate_30yr": "MORTGAGE30US",
}

def fetch_series(series_id: str) -> pd.DataFrame:
    r = requests.get(BASE_URL, params={
        "series_id":         series_id,
        "api_key":           FRED_KEY,
        "file_type":         "json",
        "observation_start": "2017-01-01",
        "observation_end":   str(date.today()),
    }, timeout=30)
    r.raise_for_status()
    obs = r.json().get("observations", [])
    df  = pd.DataFrame(obs)[["date", "value"]]
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["date"]  = pd.to_datetime(df["date"]).dt.date
    return df

def build_macro_df() -> pd.DataFrame:
    rows = []
    for state in STATES:
        for metric, tmpl in SERIES_TEMPLATES.items():
            sid = tmpl.format(state=state)
            try:
                df = fetch_series(sid)
                df["series_id"]   = sid
                df["state_code"]  = state
                df["metric_name"] = metric
                rows.append(df)
                print(f"  OK  {sid} ({len(df)} obs)")
            except Exception as e:
                print(f"  ERR {sid}: {e}")

    for metric, sid in NATIONAL_SERIES.items():
        df = fetch_series(sid)
        for state in STATES:
            d = df.copy()
            d["series_id"]   = sid
            d["state_code"]  = state
            d["metric_name"] = metric
            rows.append(d)
        print(f"  OK  {sid} (national → broadcast to all states)")

    out = pd.concat(rows, ignore_index=True)
    out = out.rename(columns={"date": "period_date", "value": "value"})
    out["_loaded_at"] = datetime.now(timezone.utc)
    return out

def main():
    client = bigquery.Client(project=PROJECT)
    df     = build_macro_df()

    job_config = bigquery.LoadJobConfig(
        write_disposition = bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    job = client.load_table_from_dataframe(df, TABLE_ID, job_config=job_config)
    job.result()
    print(f"\nFRED loaded: {job.output_rows:,} rows → {TABLE_ID}")

if __name__ == "__main__":
    main()
```

---

## 4. dbt Model Architecture

### 4.1 Install & Init

```bash
pip install dbt-bigquery

# The finlens_dbt/ folder already exists in the repo.
# If starting from scratch:
#   dbt init finlens_dbt

cd finlens_dbt
```

#### packages.yml

Create `finlens_dbt/packages.yml` to declare dbt package dependencies.
`dbt-utils` provides common macros (date spine, surrogate keys, pivot helpers):

```yaml
# finlens_dbt/packages.yml
packages:
  - package: dbt-labs/dbt_utils
    version: [">=1.0.0", "<2.0.0"]
```

Then install packages before your first `dbt run`:

```bash
dbt deps    # downloads packages into dbt_packages/ (git-ignored)
```

> **Note:** If you see `Warning: No packages were found in packages.yml`,
> the file is missing — create it as above and re-run `dbt deps`.

### 4.2 profiles.yml

The `profiles.yml` lives inside the `finlens_dbt/` project folder (committed to the repo).
It uses `method: oauth` so dbt picks up ADC automatically — no key file required.

```yaml
# finlens_dbt/profiles.yml
finlens:
  target: dev
  outputs:
    dev:
      type: bigquery
      method: oauth                          # uses gcloud ADC — no key file needed
      project: "{{ env_var('GCP_PROJECT') }}"
      dataset: finlens_dev
      location: US
      threads: 4
      timeout_seconds: 300
      priority: interactive

    prod:
      type: bigquery
      method: oauth
      project: "{{ env_var('GCP_PROJECT') }}"
      dataset: finlens_prod
      location: US
      threads: 8
      timeout_seconds: 600
      priority: batch
```

Set `GCP_PROJECT` in your `.env` (already excluded from git via `.gitignore`):

```bash
GCP_PROJECT=project-58b73547-8fb7-4cff-b60
```

### 4.3 dbt_project.yml

```yaml
# finlens_dbt/dbt_project.yml
name: finlens_dbt
version: "1.0.0"
config-version: 2

profile: finlens

model-paths: ["models"]
seed-paths:  ["seeds"]
test-paths:  ["tests"]
macro-paths: ["macros"]
analysis-paths: ["analyses"]

target-path: "target"
clean-targets: ["target", "dbt_packages"]

vars:
  start_year: 2018
  end_year:   2024          # includes 2024 HMDA data
  treatment_state: "CA"

models:
  finlens_dbt:
    staging:
      +materialized: view
      +schema: staging
    intermediate:
      +materialized: view
      +schema: intermediate
    marts:
      +materialized: table
      +schema: marts
```

### 4.4 Sources

```yaml
# models/staging/_sources.yml
version: 2

sources:
  - name: hmda
    project: project-58b73547-8fb7-4cff-b60
    dataset: raw_hmda
    tables:
      - name: hmda_lar_raw
        columns:
          - name: activity_year
            tests: [not_null]
          - name: state_code
            tests: [not_null]
          - name: action_taken
            tests:
              - not_null
              - accepted_values:
                  values: [1, 2, 3, 4, 5, 6, 7, 8]

  - name: fred
    project: project-58b73547-8fb7-4cff-b60
    dataset: raw_fred
    tables:
      - name: fred_macro_raw
        columns:
          - name: state_code
            tests: [not_null]
          - name: metric_name
            tests:
              - accepted_values:
                  values: ['unemployment_rate', 'hpi', 'mortgage_rate_30yr']
```

### 4.5 Staging Models

#### `stg_hmda_lar.sql`

```sql
-- models/staging/stg_hmda_lar.sql
WITH source AS (
    SELECT * FROM {{ source('hmda', 'hmda_lar_raw') }}
),

cleaned AS (
    SELECT
        CAST(activity_year AS INT64)                            AS activity_year,
        state_code,
        county_code,
        DATE(CAST(activity_year AS INT64), 7, 1)               AS application_mid_year_date,

        -- Action classification
        CAST(action_taken AS INT64)                             AS action_taken_code,
        CASE CAST(action_taken AS INT64)
            WHEN 1 THEN 'originated'
            WHEN 2 THEN 'approved_not_accepted'
            WHEN 3 THEN 'denied'
            WHEN 4 THEN 'withdrawn'
            WHEN 5 THEN 'incomplete'
            WHEN 6 THEN 'purchased'
            WHEN 7 THEN 'preapproval_denied'
            WHEN 8 THEN 'preapproval_approved'
            ELSE 'unknown'
        END                                                     AS action_taken_label,

        -- Loan attributes
        CAST(loan_type AS INT64)                                AS loan_type_code,
        CASE CAST(loan_type AS INT64)
            WHEN 1 THEN 'conventional'
            WHEN 2 THEN 'fha'
            WHEN 3 THEN 'va'
            WHEN 4 THEN 'usda'
        END                                                     AS loan_type_label,
        CAST(loan_purpose AS INT64)                             AS loan_purpose_code,
        CASE CAST(loan_purpose AS INT64)
            WHEN 1  THEN 'purchase'
            WHEN 2  THEN 'home_improvement'
            WHEN 31 THEN 'refinance'
            WHEN 32 THEN 'cash_out_refinance'
            WHEN 4  THEN 'other'
        END                                                     AS loan_purpose_label,
        derived_loan_product_type                               AS loan_product_type,
        derived_dwelling_category                               AS dwelling_category,
        CAST(lien_status AS INT64)                             AS lien_status,
        CAST(occupancy_type AS INT64)                          AS occupancy_type,

        -- Financial metrics
        SAFE_CAST(loan_amount AS FLOAT64)                       AS loan_amount,
        SAFE_CAST(property_value AS FLOAT64)                    AS property_value,
        SAFE_CAST(interest_rate AS FLOAT64)                     AS interest_rate,
        SAFE_CAST(rate_spread AS FLOAT64)                       AS rate_spread,
        SAFE_CAST(combined_loan_to_value_ratio AS FLOAT64)      AS cltv_ratio,
        SAFE_CAST(income AS FLOAT64)                            AS income_thousands,
        SAFE_CAST(income AS FLOAT64) * 1000                     AS income_annual,
        debt_to_income_ratio                                    AS dti_bucket,
        SAFE_CAST(loan_term AS INT64)                           AS loan_term_months,

        -- Denial reasons
        SAFE_CAST(denial_reason_1 AS INT64)                     AS denial_reason_1,
        SAFE_CAST(denial_reason_2 AS INT64)                     AS denial_reason_2,

        -- Demographics
        derived_race                                            AS applicant_race,
        derived_sex                                             AS applicant_sex,
        applicant_age                                           AS applicant_age_bucket,

        -- Quality flags
        IF(SAFE_CAST(loan_amount AS FLOAT64)   IS NULL, 1, 0)  AS flag_missing_loan_amount,
        IF(SAFE_CAST(income AS FLOAT64)        IS NULL, 1, 0)  AS flag_missing_income,
        IF(SAFE_CAST(interest_rate AS FLOAT64) IS NULL, 1, 0)  AS flag_missing_rate,

        _loaded_at

    FROM source
    WHERE CAST(activity_year AS INT64) BETWEEN 2018 AND 2023
      AND state_code IS NOT NULL
      AND CAST(action_taken AS INT64) BETWEEN 1 AND 8
)

SELECT * FROM cleaned
```

#### `stg_fred_macro.sql`

```sql
-- models/staging/stg_fred_macro.sql
WITH source AS (
    SELECT * FROM {{ source('fred', 'fred_macro_raw') }}
)

SELECT
    state_code,
    DATE_TRUNC(period_date, YEAR)                               AS macro_year_date,
    EXTRACT(YEAR FROM period_date)                              AS macro_year,
    AVG(IF(metric_name = 'unemployment_rate', value, NULL))     AS unemployment_rate,
    AVG(IF(metric_name = 'hpi',               value, NULL))     AS hpi,
    AVG(IF(metric_name = 'mortgage_rate_30yr', value, NULL))    AS mortgage_rate_30yr
FROM source
WHERE EXTRACT(YEAR FROM period_date) BETWEEN 2017 AND 2023
GROUP BY 1, 2, 3
```

### 4.6 Intermediate Models

#### `int_applications_enriched.sql`

```sql
-- models/intermediate/int_applications_enriched.sql
WITH hmda AS (
    SELECT * FROM {{ ref('stg_hmda_lar') }}
),
macro AS (
    SELECT * FROM {{ ref('stg_fred_macro') }}
)

SELECT
    h.*,
    m.unemployment_rate,
    m.hpi,
    m.mortgage_rate_30yr,

    -- Derived financial ratios
    ROUND(h.loan_amount / NULLIF(h.income_annual, 0), 2)            AS loan_to_income_ratio,
    ROUND(h.loan_amount / NULLIF(h.property_value, 0), 2)           AS ltv_ratio_derived,
    ROUND(h.loan_amount * (h.interest_rate / 100), 0)               AS annual_interest_revenue_proxy,

    -- DiD treatment flags
    IF(h.state_code = 'CA', 1, 0)                                   AS is_california,
    IF(h.activity_year >= 2020, 1, 0)                               AS is_post_ccpa,
    IF(h.state_code = 'CA' AND h.activity_year >= 2020, 1, 0)       AS is_treated,

    -- Staggered DiD flags
    CASE
        WHEN h.state_code = 'CA' AND h.activity_year >= 2020 THEN 1
        WHEN h.state_code = 'VA' AND h.activity_year >= 2023 THEN 1
        WHEN h.state_code = 'CO' AND h.activity_year >= 2023 THEN 1
        ELSE 0
    END                                                             AS is_treated_staggered,

    CASE
        WHEN h.state_code = 'CA' THEN 2020
        WHEN h.state_code = 'VA' THEN 2023
        WHEN h.state_code = 'CO' THEN 2023
        ELSE NULL
    END                                                             AS treatment_year

FROM hmda h
LEFT JOIN macro m
    ON  h.state_code    = m.state_code
    AND h.activity_year = m.macro_year
```

#### `int_approval_flags.sql`

```sql
-- models/intermediate/int_approval_flags.sql
WITH base AS (
    SELECT * FROM {{ ref('int_applications_enriched') }}
)

SELECT
    *,
    IF(action_taken_code IN (1, 2, 8), 1, 0)  AS is_approved,
    IF(action_taken_code = 1, 1, 0)            AS is_originated,
    IF(action_taken_code IN (3, 7), 1, 0)      AS is_denied,
    IF(action_taken_code IN (4, 5), 1, 0)      AS is_withdrawn_or_incomplete,

    CASE denial_reason_1
        WHEN 1 THEN 'debt_to_income'
        WHEN 2 THEN 'employment_history'
        WHEN 3 THEN 'credit_history'
        WHEN 4 THEN 'collateral'
        WHEN 5 THEN 'insufficient_cash'
        WHEN 6 THEN 'unverifiable_info'
        WHEN 7 THEN 'credit_app_incomplete'
        WHEN 8 THEN 'mortgage_insurance_denied'
        WHEN 9 THEN 'other'
        ELSE NULL
    END                                        AS denial_reason_label,

    CASE
        WHEN income_annual < 50000                       THEN 'low_income'
        WHEN income_annual BETWEEN 50000 AND 99999       THEN 'moderate_income'
        WHEN income_annual BETWEEN 100000 AND 199999     THEN 'middle_income'
        WHEN income_annual >= 200000                     THEN 'high_income'
        ELSE 'unknown'
    END                                        AS income_tier,

    CASE
        WHEN loan_amount < 150000                        THEN 'small'
        WHEN loan_amount BETWEEN 150000 AND 417000       THEN 'conforming'
        WHEN loan_amount > 417000                        THEN 'jumbo'
        ELSE 'unknown'
    END                                        AS loan_size_tier

FROM base
```

#### `int_loan_cohorts.sql`

```sql
--  /int_loan_cohorts.sql
WITH base AS (
    SELECT * FROM {{ ref('int_approval_flags') }}
)

SELECT
    *,
    CONCAT('VTG-', CAST(activity_year AS STRING))   AS vintage_label,

    CASE
        WHEN activity_year BETWEEN 2018 AND 2019 THEN 'pre_ccpa'
        WHEN activity_year = 2020               THEN 'ccpa_transition'
        WHEN activity_year BETWEEN 2021 AND 2023 THEN 'post_ccpa'
    END                                             AS regulatory_era,

    CASE
        WHEN activity_year BETWEEN 2018 AND 2021 THEN 'low_rate_era'
        WHEN activity_year BETWEEN 2022 AND 2023 THEN 'rising_rate_era'
    END                                             AS rate_era,

    IF(occupancy_type = 2 AND action_taken_code IN (1,2), 1, 0) AS is_investor_loan

FROM base
```

### 4.7 Mart Models

#### `mart_lending_funnel.sql`

```sql
-- models/marts/mart_lending_funnel.sql
WITH base AS (
    SELECT * FROM {{ ref('int_loan_cohorts') }}
)

SELECT
    activity_year,
    state_code,
    regulatory_era,
    loan_type_label,
    loan_purpose_label,
    loan_size_tier,
    income_tier,

    COUNT(*)                                                        AS total_applications,
    SUM(is_approved)                                                AS total_approved,
    SUM(is_originated)                                              AS total_originated,
    SUM(is_denied)                                                  AS total_denied,
    SUM(is_withdrawn_or_incomplete)                                 AS total_withdrawn,

    ROUND(SAFE_DIVIDE(SUM(is_approved),   COUNT(*)), 4)             AS approval_rate,
    ROUND(SAFE_DIVIDE(SUM(is_originated), COUNT(*)), 4)             AS origination_rate,
    ROUND(SAFE_DIVIDE(SUM(is_denied),     COUNT(*)), 4)             AS denial_rate,
    ROUND(SAFE_DIVIDE(SUM(is_originated), SUM(is_approved)), 4)    AS close_rate,

    ROUND(AVG(IF(is_originated=1, loan_amount,    NULL)), 0)        AS avg_loan_amount,
    ROUND(SUM(IF(is_originated=1, loan_amount,    0)),    0)        AS total_loan_volume,
    ROUND(AVG(IF(is_originated=1, interest_rate,  NULL)), 3)        AS avg_interest_rate

FROM base
GROUP BY 1,2,3,4,5,6,7
```

#### `mart_unit_economics.sql`

```sql
-- models/marts/mart_unit_economics.sql
WITH base AS (
    SELECT * FROM {{ ref('int_loan_cohorts') }}
    WHERE is_originated = 1
)

SELECT
    activity_year,
    vintage_label,
    regulatory_era,
    rate_era,
    state_code,
    loan_type_label,
    loan_size_tier,
    income_tier,
    is_investor_loan,

    COUNT(*)                                                            AS loan_count,
    ROUND(AVG(loan_amount), 0)                                          AS avg_loan_amount,
    ROUND(SUM(loan_amount), 0)                                          AS total_loan_volume,
    ROUND(AVG(annual_interest_revenue_proxy), 0)                        AS avg_annual_interest_revenue,
    ROUND(SUM(annual_interest_revenue_proxy), 0)                        AS total_interest_revenue_proxy,
    ROUND(AVG(loan_amount) * 0.015, 0)                                  AS est_origination_cost_per_loan,
    ROUND(AVG(loan_amount) * 0.003, 0)                                  AS est_annual_servicing_cost,
    ROUND(
        AVG(annual_interest_revenue_proxy)
        - AVG(loan_amount) * 0.015
        - AVG(loan_amount) * 0.003,
    0)                                                                  AS est_contribution_margin,
    ROUND(
        SAFE_DIVIDE(
            AVG(annual_interest_revenue_proxy)
            - AVG(loan_amount) * 0.015
            - AVG(loan_amount) * 0.003,
            AVG(loan_amount)
        ),
    4)                                                                  AS est_contribution_margin_pct,
    ROUND(AVG(ltv_ratio_derived), 3)                                    AS avg_ltv,
    ROUND(AVG(loan_to_income_ratio), 3)                                 AS avg_lti,
    ROUND(AVG(cltv_ratio), 3)                                           AS avg_cltv

FROM base
GROUP BY 1,2,3,4,5,6,7,8,9
```

#### `mart_regulatory_cohort.sql`

```sql
-- models/marts/mart_regulatory_cohort.sql
WITH base AS (
    SELECT * FROM {{ ref('int_loan_cohorts') }}
    WHERE state_code IN ('CA','TX','FL','OH','NY','IL','WA','CO','VA')
)

SELECT
    activity_year,
    state_code,
    regulatory_era,
    is_california,
    is_post_ccpa,
    is_treated,
    is_treated_staggered,
    treatment_year,
    loan_type_label,
    loan_purpose_label,
    income_tier,
    is_investor_loan,

    COUNT(*)                                                        AS n_applications,
    SUM(is_approved)                                                AS n_approved,
    SUM(is_originated)                                              AS n_originated,
    ROUND(AVG(CAST(is_approved AS FLOAT64)), 4)                    AS approval_rate,
    ROUND(AVG(CAST(is_originated AS FLOAT64)), 4)                  AS origination_rate,
    ROUND(AVG(IF(is_approved=1, loan_amount,  NULL)), 0)           AS avg_approved_loan_amount,
    ROUND(AVG(IF(is_approved=1, income_annual,NULL)), 0)           AS avg_approved_income,
    ROUND(AVG(CAST(flag_missing_income AS FLOAT64)), 4)            AS pct_missing_income,
    ROUND(AVG(IF(is_approved=1, interest_rate,NULL)), 4)           AS avg_interest_rate,
    ROUND(AVG(IF(is_approved=1, ltv_ratio_derived,NULL)), 4)       AS avg_ltv,
    AVG(unemployment_rate)                                          AS unemployment_rate,
    AVG(hpi)                                                        AS hpi,
    AVG(mortgage_rate_30yr)                                         AS mortgage_rate_30yr

FROM base
GROUP BY 1,2,3,4,5,6,7,8,9,10,11,12
```

#### `mart_kpi_dashboard.sql`

```sql
-- models/marts/mart_kpi_dashboard.sql
WITH funnel AS (SELECT * FROM {{ ref('mart_lending_funnel') }}),
     econ   AS (SELECT * FROM {{ ref('mart_unit_economics') }})

SELECT
    f.activity_year,
    f.state_code,
    f.regulatory_era,
    f.loan_type_label,
    f.income_tier,
    f.total_applications,
    f.approval_rate,
    f.origination_rate,
    f.denial_rate,
    f.avg_loan_amount,
    f.avg_interest_rate,
    f.total_loan_volume,
    e.avg_annual_interest_revenue,
    e.est_contribution_margin,
    e.est_contribution_margin_pct,
    e.avg_ltv,
    e.avg_lti,
    e.loan_count  AS originated_loan_count

FROM funnel f
LEFT JOIN econ e
    ON  f.activity_year   = e.activity_year
    AND f.state_code      = e.state_code
    AND f.loan_type_label = e.loan_type_label
    AND f.income_tier     = e.income_tier
```

### 4.8 Run dbt

ADC is active from `gcloud auth application-default login` — no credential export needed.

```bash
cd finlens_dbt

dbt deps
dbt run --select staging
dbt run --select intermediate
dbt run --select marts
dbt test
dbt docs generate && dbt docs serve   # http://localhost:8080
```

---

## 5. Orchestration with Airflow

### 5.1 Install with BigQuery Provider

```bash
pip install "apache-airflow==2.9.1" \
    apache-airflow-providers-google \
    apache-airflow-providers-http \
    dbt-bigquery \
    --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-2.9.1/constraints-3.11.txt"

export AIRFLOW_HOME=/Users/ellandalla/Finlens/airflow
airflow db init
airflow users create \
    --username admin --firstname Ella --lastname Admin \
    --role Admin --email ndallaella@gmail.com --password admin123

airflow scheduler &
airflow webserver --port 8080 &
```

### 5.2 BigQuery Connection

Airflow uses ADC when no key path is specified. Set the connection to use the
`google_cloud_platform` type with no key file — the Airflow worker process inherits
the ADC credentials from the environment.

```bash
airflow connections add bigquery_finlens \
    --conn-type google_cloud_platform \
    --conn-extra "{\"project\": \"project-58b73547-8fb7-4cff-b60\", \"num_retries\": 2}"

# GCP_PROJECT and FRED_API_KEY are read from the Finlens repo .env via config.py — no Airflow variables needed
```

### 5.3 Main Pipeline DAG

```python
# dags/finlens_pipeline.py
from __future__ import annotations
import os, subprocess
from datetime import datetime, timedelta
from pathlib import Path

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.google.cloud.operators.bigquery import BigQueryCheckOperator
from airflow.providers.google.cloud.hooks.bigquery import BigQueryHook
from airflow.utils.trigger_rule import TriggerRule
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
from config import cfg  # loads .env → GCP_PROJECT, FRED_API_KEY

HMDA_YEARS    = list(range(2018, 2025))   # 2018–2024 inclusive
DBT_PROJECT   = str(REPO_ROOT / "finlens_dbt")
INGESTION_DIR = str(REPO_ROOT / "ingest")
GCP_CONN      = "bigquery_finlens"
GCP_PROJECT   = cfg.project

DEFAULT_ARGS = {
    "owner":            "ella",
    "depends_on_past":  False,
    "email":            ["ndallaella@gmail.com"],
    "email_on_failure": True,
    "retries":          2,
    "retry_delay":      timedelta(minutes=5),
    "execution_timeout": timedelta(hours=3),
}

def _run(cmd, cwd=None, env=None):
    # ADC + .env (GCP_PROJECT, FRED_API_KEY) via config / inherited os.environ
    env_full = {
        **os.environ,
        "GCP_PROJECT": cfg.project,
        **({"FRED_API_KEY": cfg.fred_api_key} if cfg.fred_api_key else {}),
        **(env or {}),
    }
    r = subprocess.run(cmd, cwd=cwd, env=env_full, capture_output=True, text=True)
    print(r.stdout[-3000:])
    if r.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} failed:\n{r.stderr[-1000:]}")

def ingest_hmda_year(year: int, **ctx):
    _run(
        ["python", "ingest_latest.py", "--source", "hmda", "--year", str(year)],
        cwd=INGESTION_DIR,
    )

def ingest_fred(**ctx):
    if not cfg.fred_api_key:
        raise ValueError("FRED_API_KEY missing — set it in .env at the Finlens project root")
    _run(["python", "ingest_latest.py", "--source", "fred"], cwd=INGESTION_DIR)

def run_dbt_command(select=None, command="run", full_refresh=False, **ctx):
    cmd = ["dbt", command]
    if select:       cmd += ["--select", select]
    if full_refresh: cmd.append("--full-refresh")
    cmd += ["--profiles-dir", os.path.expanduser("~/.dbt"),
            "--project-dir", DBT_PROJECT, "--target", "prod"]
    _run(cmd)

def check_row_counts(**ctx):
    hook = BigQueryHook(gcp_conn_id=GCP_CONN)
    tables = [
        "marts.mart_lending_funnel",
        "marts.mart_unit_economics",
        "marts.mart_kpi_dashboard",
        "marts.mart_regulatory_cohort",
    ]
    failures = []
    for t in tables:
        rows = hook.get_first(f"SELECT COUNT(*) FROM `{GCP_PROJECT}.{t}`")[0]
        print(f"  {t}: {rows:,} rows")
        if rows == 0:
            failures.append(f"{t} is EMPTY")
    if failures:
        raise ValueError("\n".join(failures))
    print("Quality gate passed.")

with DAG(
    dag_id       = "finlens_annual_pipeline",
    default_args = DEFAULT_ARGS,
    description  = "FinLens: HMDA+FRED ingestion → dbt → BigQuery marts",
    schedule     = "0 6 1 2 *",
    start_date   = datetime(2024, 2, 1),
    catchup      = False,
    max_active_runs = 1,
    tags         = ["finlens", "hmda", "bigquery", "dbt"],
) as dag:

    hmda_tasks = [
        PythonOperator(
            task_id=f"ingest_hmda_{y}",
            python_callable=ingest_hmda_year,
            op_kwargs={"year": y},
            pool="bigquery_pool",
        )
        for y in HMDA_YEARS
    ]

    fred_task = PythonOperator(
        task_id="ingest_fred",
        python_callable=ingest_fred,
    )

    dbt_staging = PythonOperator(
        task_id="dbt_run_staging",
        python_callable=run_dbt_command,
        op_kwargs={"select": "staging"},
        trigger_rule=TriggerRule.ALL_SUCCESS,
    )

    dbt_intermediate = PythonOperator(
        task_id="dbt_run_intermediate",
        python_callable=run_dbt_command,
        op_kwargs={"select": "intermediate"},
    )

    dbt_marts = PythonOperator(
        task_id="dbt_run_marts",
        python_callable=run_dbt_command,
        op_kwargs={"select": "marts"},
    )

    dbt_test = PythonOperator(
        task_id="dbt_test",
        python_callable=run_dbt_command,
        op_kwargs={"command": "test"},
    )

    dbt_docs = PythonOperator(
        task_id="dbt_docs_generate",
        python_callable=run_dbt_command,
        op_kwargs={"command": "docs generate"},
    )

    quality_gate = PythonOperator(
        task_id="bigquery_row_count_check",
        python_callable=check_row_counts,
    )

    # Dependency graph
    [*hmda_tasks, fred_task] >> dbt_staging
    dbt_staging >> dbt_intermediate >> dbt_marts >> dbt_test >> dbt_docs >> quality_gate
```

### 5.4 Nightly Monitoring DAG

```python
# dags/finlens_monitoring.py
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.google.cloud.hooks.bigquery import BigQueryHook
from datetime import datetime, timedelta
import statistics

GCP_CONN    = "bigquery_finlens"
GCP_PROJECT = "project-58b73547-8fb7-4cff-b60"
DEFAULT_ARGS = {"owner":"ella","retries":1,"retry_delay":timedelta(minutes=2),
                "email":["ndallaella@gmail.com"],"email_on_failure":True}

def check_approval_rate_drift(**ctx):
    hook = BigQueryHook(gcp_conn_id=GCP_CONN)
    rows = hook.get_records(f"""
        SELECT activity_year, AVG(approval_rate)
        FROM `{GCP_PROJECT}.marts.mart_regulatory_cohort`
        WHERE state_code = 'CA'
        GROUP BY activity_year ORDER BY activity_year
    """)
    rates = [r[1] for r in rows]
    hist, latest = rates[:-1], rates[-1]
    mu, sigma = statistics.mean(hist), statistics.stdev(hist)
    z = (latest - mu) / sigma if sigma else 0
    print(f"CA approval rate z-score: {z:.2f}")
    if abs(z) > 3:
        raise ValueError(f"Approval rate drift detected — z={z:.2f}")

def check_table_freshness(**ctx):
    hook  = BigQueryHook(gcp_conn_id=GCP_CONN)
    stale = []
    for t in ["mart_lending_funnel","mart_unit_economics","mart_regulatory_cohort"]:
        hrs = hook.get_first(f"""
            SELECT TIMESTAMP_DIFF(CURRENT_TIMESTAMP(),MAX(_loaded_at),HOUR)
            FROM `{GCP_PROJECT}.marts.{t}`
        """)[0]
        print(f"  {t}: {hrs}h old")
        if hrs and hrs > 48: stale.append(t)
    if stale:
        raise ValueError(f"Stale tables: {stale}")

with DAG(
    dag_id="finlens_monitoring",
    default_args=DEFAULT_ARGS,
    schedule="0 7 * * *",
    start_date=datetime(2024,1,1),
    catchup=False,
    tags=["finlens","monitoring"],
) as dag:
    PythonOperator(task_id="check_approval_rate_drift",
                   python_callable=check_approval_rate_drift)
    PythonOperator(task_id="check_table_freshness",
                   python_callable=check_table_freshness)
```

```bash
airflow pools set bigquery_pool 4 "Max concurrent BigQuery jobs"
```

---

## 6. DiD Analysis — 5 Use Cases

### Setup: BigQuery Data Loader

```python
# analysis/data_loader.py
import os
import pandas as pd
from google.cloud import bigquery

PROJECT = "project-58b73547-8fb7-4cff-b60"

def load_regulatory_cohort() -> pd.DataFrame:
    client = bigquery.Client(project=PROJECT)
    df = client.query("""
        SELECT * FROM `project-58b73547-8fb7-4cff-b60.marts.mart_regulatory_cohort`
    """).to_dataframe()
    df.columns = df.columns.str.lower()
    return df

def load_funnel() -> pd.DataFrame:
    client = bigquery.Client(project=PROJECT)
    return client.query("""
        SELECT * FROM `project-58b73547-8fb7-4cff-b60.marts.mart_lending_funnel`
    """).to_dataframe()

def load_kpi_dashboard() -> pd.DataFrame:
    client = bigquery.Client(project=PROJECT)
    return client.query("""
        SELECT * FROM `project-58b73547-8fb7-4cff-b60.marts.mart_kpi_dashboard`
    """).to_dataframe()
```

### 6a. Standard 2×2 DiD — CCPA Baseline

```python
# analysis/did_standard.py
import pandas as pd
import numpy as np
import statsmodels.formula.api as smf
import matplotlib.pyplot as plt
from data_loader import load_regulatory_cohort

def run_standard_did(outcome="approval_rate"):
    df = load_regulatory_cohort()
    df_did = df[
        df["state_code"].isin(["CA","TX","FL","OH"])
        & df["activity_year"].between(2018, 2021)
    ].copy()

    model = smf.ols(
        f"{outcome} ~ is_california + is_post_ccpa + is_treated"
        " + unemployment_rate + hpi + mortgage_rate_30yr",
        data=df_did
    ).fit(cov_type="HC3")

    est  = model.params["is_treated"]
    pval = model.pvalues["is_treated"]
    ci   = model.conf_int().loc["is_treated"]

    print(f"\nStandard DiD — {outcome}")
    print(f"  ATT:    {est:+.4f} ({est*100:+.2f} pp)")
    print(f"  95% CI: [{ci[0]:.4f}, {ci[1]:.4f}]")
    print(f"  p-val:  {pval:.4f}")

    return model, df_did

if __name__ == "__main__":
    run_standard_did()
```

### 6b. Staggered DiD — Multi-State Rollouts

```python
# analysis/did_staggered.py
import pandas as pd, numpy as np, warnings
import statsmodels.formula.api as smf
from data_loader import load_regulatory_cohort

TREATMENT_YEARS = {"CA": 2020, "VA": 2023, "CO": 2023}
NEVER_TREATED   = ["TX", "FL", "OH", "NY", "IL"]

def att_gt(df, outcome, covariates):
    """Simplified Callaway-Sant'Anna ATT(g,t) via 2x2 DiD blocks."""
    never = df[df["state_code"].isin(NEVER_TREATED)].copy()
    results = []
    for state, g in TREATMENT_YEARS.items():
        treated = df[df["state_code"] == state].copy()
        for t in df["activity_year"].unique():
            if t < g - 1:
                continue
            block = pd.concat([
                treated[treated["activity_year"].isin([g-1, t])],
                never[never["activity_year"].isin([g-1, t])]
            ])
            block["_treat"] = (block["state_code"] == state).astype(int)
            block["_post"]  = (block["activity_year"] == t).astype(int)
            block["_did"]   = block["_treat"] * block["_post"]
            covs = " + ".join(covariates) if covariates else "1"
            try:
                mod = smf.ols(f"{outcome} ~ _treat+_post+_did+{covs}", data=block).fit(cov_type="HC3")
                results.append({
                    "cohort_state": state, "cohort_g": g, "calendar_year": t,
                    "event_time": t - g,
                    "att": mod.params["_did"], "se": mod.bse["_did"],
                    "pval": mod.pvalues["_did"], "n": len(block),
                })
            except Exception as e:
                warnings.warn(f"{state} t={t}: {e}")
    return pd.DataFrame(results)

def run_staggered_did():
    df  = load_regulatory_cohort()
    df2 = df[df["state_code"].isin(list(TREATMENT_YEARS)+NEVER_TREATED)].copy()
    results = att_gt(df2, "approval_rate",
                     ["unemployment_rate","hpi","mortgage_rate_30yr"])
    print(results[["cohort_state","event_time","att","se","pval"]].to_string())
    print(f"\nAvg ATT: {results['att'].mean():+.4f}")
    return results

if __name__ == "__main__":
    run_staggered_did()
```

### 6c. Event Study / Dynamic DiD

```python
# analysis/did_event_study.py
import pandas as pd, numpy as np
import statsmodels.formula.api as smf
import matplotlib.pyplot as plt
from data_loader import load_regulatory_cohort

def run_event_study(outcome="approval_rate"):
    df = load_regulatory_cohort()
    df_es = df[df["state_code"].isin(["CA","TX","FL","OH"])].copy()
    df_es["event_time"] = df_es["activity_year"] - 2020

    for t in df_es["event_time"].unique():
        if t == -1: continue
        col = f"ca_t{'p' if t>=0 else 'm'}{abs(t)}"
        df_es[col] = ((df_es["is_california"]==1) & (df_es["event_time"]==t)).astype(int)

    dummies  = [c for c in df_es.columns if c.startswith("ca_t")]
    formula  = f"{outcome} ~ is_california + {' + '.join(dummies)} + unemployment_rate + hpi + mortgage_rate_30yr + C(activity_year)"
    model    = smf.ols(formula, data=df_es).fit(cov_type="HC3")

    event_times = sorted(df_es["event_time"].unique())
    coefs = []
    for t in event_times:
        if t == -1:
            coefs.append({"t": t, "coef": 0.0, "lo": 0.0, "hi": 0.0})
        else:
            col = f"ca_t{'p' if t>=0 else 'm'}{abs(t)}"
            if col in model.params:
                coefs.append({"t": t, "coef": model.params[col],
                              "lo": model.conf_int().loc[col,0],
                              "hi": model.conf_int().loc[col,1]})

    coef_df = pd.DataFrame(coefs)

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.errorbar(coef_df["t"], coef_df["coef"],
                yerr=[coef_df["coef"]-coef_df["lo"], coef_df["hi"]-coef_df["coef"]],
                fmt="o-", capsize=5, color="steelblue")
    ax.axhline(0, color="black", lw=0.8)
    ax.axvline(-0.5, color="red", ls="--", alpha=0.6, label="CCPA")
    ax.set_title(f"Event Study: CCPA Effect on {outcome}")
    ax.set_xlabel("Event Time"); ax.set_ylabel("DiD Coefficient")
    ax.legend(); plt.tight_layout()
    plt.savefig("outputs/event_study.png", dpi=150)
    print("Saved outputs/event_study.png")
    return model, coef_df

if __name__ == "__main__":
    run_event_study()
```

### 6d. Triple DiD (DiDiD) — Investor vs Owner-Occupied Loans

```python
# analysis/did_triple.py
import statsmodels.formula.api as smf
from data_loader import load_regulatory_cohort

def run_triple_did():
    df = load_regulatory_cohort()
    df_did3 = df[
        df["state_code"].isin(["CA","TX","FL","OH"])
        & df["activity_year"].between(2018, 2021)
    ].copy()

    model = smf.ols(
        "approval_rate ~ is_california * is_post_ccpa * is_investor_loan"
        " + unemployment_rate + hpi + mortgage_rate_30yr + C(state_code)",
        data=df_did3
    ).fit(cov_type="HC3")

    key = "is_california:is_post_ccpa:is_investor_loan"
    if key in model.params:
        est, pval, ci = model.params[key], model.pvalues[key], model.conf_int().loc[key]
        print(f"Triple DiD (Investor × CA × Post-CCPA): {est:+.4f} (p={pval:.4f})")
        print(f"95% CI: [{ci[0]:.4f}, {ci[1]:.4f}]")
    return model

if __name__ == "__main__":
    run_triple_did()
```

### 6e. Heterogeneous Treatment Effects — CausalForest

```python
# analysis/did_heterogeneous.py
import pandas as pd, numpy as np
import statsmodels.formula.api as smf
import matplotlib.pyplot as plt
from econml.dml import CausalForestDML
from sklearn.ensemble import GradientBoostingRegressor, GradientBoostingClassifier
from data_loader import load_regulatory_cohort

def run_hte_by_income_tier():
    df = load_regulatory_cohort()
    df_hte = df[df["state_code"].isin(["CA","TX","FL","OH"])
                & df["activity_year"].between(2018,2021)].copy()

    results = {}
    for tier in df_hte["income_tier"].dropna().unique():
        sub = df_hte[df_hte["income_tier"]==tier].copy()
        if len(sub) < 30: continue
        mod = smf.ols(
            "approval_rate ~ is_california+is_post_ccpa+is_treated"
            "+unemployment_rate+hpi+mortgage_rate_30yr",
            data=sub
        ).fit(cov_type="HC3")
        results[tier] = {"att": mod.params.get("is_treated",np.nan),
                         "se":  mod.bse.get("is_treated",np.nan),
                         "pval":mod.pvalues.get("is_treated",np.nan)}

    res_df = pd.DataFrame(results).T.sort_values("att")
    print("HTE by Income Tier:\n", res_df.round(4))

    fig, ax = plt.subplots(figsize=(8,4))
    ax.barh(res_df.index, res_df["att"], xerr=1.96*res_df["se"],
            capsize=4, color="steelblue", alpha=0.75)
    ax.axvline(0, color="black", lw=0.8)
    ax.set_title("Heterogeneous CCPA Effect by Income Tier")
    ax.set_xlabel("DiD ATT")
    plt.tight_layout()
    plt.savefig("outputs/hte_income.png", dpi=150)
    return res_df

def run_causal_forest():
    df = load_regulatory_cohort()
    df_cf = df[df["state_code"].isin(["CA","TX","FL","OH"])
               & df["activity_year"].between(2018,2021)].dropna(
               subset=["approval_rate","unemployment_rate","hpi","mortgage_rate_30yr"]).copy()

    X_cols = ["unemployment_rate","hpi","mortgage_rate_30yr",
              "avg_approved_loan_amount","avg_approved_income"]
    X = df_cf[X_cols].fillna(df_cf[X_cols].median())
    T = df_cf["is_treated"].values
    Y = df_cf["approval_rate"].values

    est = CausalForestDML(
        model_y=GradientBoostingRegressor(n_estimators=100),
        model_t=GradientBoostingClassifier(n_estimators=100),
        n_estimators=200, random_state=42,
    )
    est.fit(Y, T, X=X)
    te, lb, ub = est.effect_interval(X, alpha=0.05)
    df_cf["cate"] = te
    print("CATE by income tier:\n",
          df_cf.groupby("income_tier")["cate"].agg(["mean","std","count"]).round(4))
    return df_cf

if __name__ == "__main__":
    run_hte_by_income_tier()
    run_causal_forest()
```

---

## 7. Synthetic Control Method

```python
# analysis/synthetic_control.py
import pandas as pd, numpy as np
import matplotlib.pyplot as plt
from pysyncon import Dataprep, Synth
from data_loader import load_regulatory_cohort

def run_synthetic_control(outcome="approval_rate"):
    df = load_regulatory_cohort()
    panel = df.groupby(["state_code","activity_year"]).agg(
        approval_rate    =("approval_rate","mean"),
        origination_rate =("origination_rate","mean"),
        avg_ltv          =("avg_ltv","mean"),
        unemployment_rate=("unemployment_rate","mean"),
        hpi              =("hpi","mean"),
        mortgage_rate_30yr=("mortgage_rate_30yr","mean"),
        pct_missing_income=("pct_missing_income","mean"),
    ).reset_index()

    donor_states = ["TX","FL","OH","NY","IL","WA"]
    panel_sc = panel[panel["state_code"].isin(["CA"]+donor_states)].copy()

    dataprep = Dataprep(
        foo=panel_sc,
        predictors=["unemployment_rate","hpi","mortgage_rate_30yr"],
        predictors_op="mean",
        time_predictors_prior=list(range(2018,2020)),
        special_predictors=[(outcome,[2018],"mean"),(outcome,[2019],"mean")],
        dependent=outcome,
        unit_variable="state_code",
        time_variable="activity_year",
        treatment_identifier="CA",
        controls_identifier=donor_states,
        time_optimize_ssr=list(range(2018,2020)),
        time_plot=list(range(2018,2024)),
    )
    synth = Synth()
    synth.fit(dataprep)

    panel_wide = panel_sc.pivot(index="activity_year",columns="state_code",values=outcome)
    synthetic_ca = panel_wide[donor_states].values @ synth.W_weights
    actual_ca    = panel_wide["CA"].values
    gap          = actual_ca - synthetic_ca
    years        = panel_wide.index.tolist()

    fig, axes = plt.subplots(2,1,figsize=(12,8))
    axes[0].plot(years, actual_ca,    "b-o", label="Actual CA")
    axes[0].plot(years, synthetic_ca, "r--s", label="Synthetic CA")
    axes[0].axvline(x=2019.5, color="gray", ls="--", label="CCPA")
    axes[0].set_title(f"Synthetic Control: {outcome}"); axes[0].legend()

    colors = ["crimson" if g < 0 else "steelblue" for g in gap]
    axes[1].bar(years, gap, color=colors, alpha=0.75)
    axes[1].axhline(0, color="black", lw=0.8)
    axes[1].axvline(x=2019.5, color="gray", ls="--")
    axes[1].set_title("Treatment Effect Gap (Actual – Synthetic CA)")
    plt.tight_layout()
    plt.savefig("outputs/synthetic_control.png", dpi=150)
    print("Saved outputs/synthetic_control.png")

    print("\nSynthetic CA donor weights:")
    for s, w in zip(donor_states, synth.W_weights):
        if w > 0.01: print(f"  {s}: {w:.4f}")

    return gap

if __name__ == "__main__":
    run_synthetic_control()
```

---

## 8. Real Estate Investor ROI Impact

### 8.1 Transmission Channels

```
CCPA / Privacy Regulation
        │
        ├─► Tighter underwriting → Fewer approved buyers → Demand ↓ → HPI growth ↓
        ├─► Wider credit spreads → Higher investor borrowing cost → Cash flow ↓
        └─► Slower origination → Reduced market liquidity → Exit premium ↑

ROI Impact:
  1. HPI growth compression  (demand shock via DiD approval rate estimate)
  2. Financing cost increase  (spread widening from HMDA rate data)
  3. Cash flow reduction      (NOI stable but debt service rises)
  4. Exit liquidity discount  (fewer buyers = harder to sell)
```

### 8.2 Investor ROI Model

```python
# analysis/investor_roi_impact.py
import pandas as pd, numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
from data_loader import load_regulatory_cohort

BASE = {
    "property_value":       500_000,
    "ltv":                  0.75,
    "loan_term_yrs":        30,
    "hold_period_yrs":      5,
    "gross_rent_multiplier": 18,
    "vacancy_rate":         0.05,
    "operating_expense_ratio": 0.40,
    "annual_appreciation":  0.04,
    "flip_hold_months":     6,
    "flip_renovation_pct":  0.10,
    "flip_selling_costs":   0.06,
}

def rental_roi(params, interest_rate, approval_delta=0.0):
    pv, ltv   = params["property_value"], params["ltv"]
    loan      = pv * ltv
    equity    = pv - loan
    r_mo      = interest_rate / 12
    n         = params["loan_term_yrs"] * 12
    pmt       = loan * (r_mo*(1+r_mo)**n) / ((1+r_mo)**n - 1)
    gross_rent= pv / params["gross_rent_multiplier"]
    noi       = gross_rent * (1-params["vacancy_rate"]) * (1-params["operating_expense_ratio"])
    net_cf    = noi - pmt*12
    adj_apprec= params["annual_appreciation"] + approval_delta * (-0.30)
    term_val  = pv * (1+adj_apprec)**params["hold_period_yrs"]
    bal       = loan * ((1+r_mo)**n - (1+r_mo)**(params["hold_period_yrs"]*12)) / ((1+r_mo)**n - 1)
    terminal_equity = term_val - bal - term_val*0.06
    total_return    = net_cf*params["hold_period_yrs"] + (terminal_equity - equity)
    ann_roi         = total_return / (equity * params["hold_period_yrs"])
    return {"annualized_roi": ann_roi, "net_cash_flow_pa": net_cf,
            "cap_rate": noi/pv, "dscr": noi/(pmt*12),
            "adjusted_appreciation": adj_apprec, "equity": equity}

def flip_roi(params, interest_rate, approval_delta=0.0):
    pv         = params["property_value"]
    loan       = pv * params["ltv"]
    equity     = pv - loan
    hold_mo    = params["flip_hold_months"]
    reno       = pv * params["flip_renovation_pct"]
    carry      = loan * (interest_rate/12) * hold_mo
    total_in   = equity + reno + carry
    adj_apprec = params["annual_appreciation"] + approval_delta*(-0.30)
    arv        = pv * (1 + adj_apprec*(hold_mo/12)) + reno*1.20
    net_proc   = arv - loan - arv*params["flip_selling_costs"]
    profit     = net_proc - total_in
    roi_hold   = profit / total_in
    ann_roi    = (1+roi_hold)**(12/hold_mo) - 1
    return {"annualized_roi": ann_roi, "roi_hold_period": roi_hold,
            "arv": arv, "gross_profit": profit, "total_cost": total_in}

def run_scenario_analysis():
    df      = load_regulatory_cohort()
    pre_rate  = df[df["state_code"].eq("CA") & df["activity_year"].isin([2018,2019])]["avg_interest_rate"].mean()
    post_rate = df[df["state_code"].eq("CA") & df["activity_year"].isin([2020,2021])]["avg_interest_rate"].mean()
    did_est   = -0.018   # replace with actual DiD output

    scenarios = {
        "Baseline\n(Pre-CCPA)":     {"rate": pre_rate/100,        "delta": 0.0},
        "Post-CCPA\n(Observed)":    {"rate": post_rate/100,        "delta": did_est},
        "Stress\n(2× Effect)":      {"rate": (post_rate+0.5)/100,  "delta": did_est*2},
    }

    print(f"CA Avg Rate Pre:  {pre_rate:.3f}% | Post: {post_rate:.3f}%")
    print(f"DiD Estimate:     {did_est:+.4f} ({did_est*100:+.2f} pp)\n")

    rental_res = {n: rental_roi(BASE, s["rate"], s["delta"]) for n, s in scenarios.items()}
    flip_res   = {n: flip_roi(BASE,   s["rate"], s["delta"]) for n, s in scenarios.items()}

    print("=" * 65)
    print("RENTAL INVESTOR ROI")
    print("=" * 65)
    for metric in ["annualized_roi","net_cash_flow_pa","cap_rate","dscr","adjusted_appreciation"]:
        row = f"{metric:<32}"
        for n in scenarios:
            v = rental_res[n][metric]
            fmt = f"{v:.1%}" if metric in ["annualized_roi","cap_rate","adjusted_appreciation"] else f"${v:,.0f}" if "cash" in metric else f"{v:.2f}"
            row += f"  {fmt:>18}"
        print(row)

    fig, axes = plt.subplots(1,2,figsize=(13,5))
    names   = [n.replace("\n"," ") for n in scenarios]
    colors  = ["#2196F3","#FF9800","#F44336"]
    r_rois  = [rental_res[n]["annualized_roi"]*100 for n in scenarios]
    fl_rois = [flip_res[n]["annualized_roi"]*100   for n in scenarios]

    for ax, rois, title in zip(axes, [r_rois, fl_rois],
                                ["Buy-and-Hold Annualized ROI","Fix-and-Flip Annualized ROI"]):
        bars = ax.bar(names, rois, color=colors, alpha=0.85, edgecolor="white", width=0.5)
        ax.yaxis.set_major_formatter(mtick.PercentFormatter())
        ax.set_title(f"{title}\n(CA, $500K Property, 75% LTV)")
        ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)
        for bar, roi in zip(bars, rois):
            ax.text(bar.get_x()+bar.get_width()/2, bar.get_height()+0.2,
                    f"{roi:.1f}%", ha="center", va="bottom", fontweight="bold")
        ax.tick_params(axis="x", rotation=10)

    plt.tight_layout()
    plt.savefig("outputs/investor_roi.png", dpi=150)
    print("Saved outputs/investor_roi.png")
    return rental_res, flip_res

if __name__ == "__main__":
    run_scenario_analysis()
```

---

## 9. Streamlit App — Funnel Dashboard + Regulatory Explorer

### 9.1 Install & Deploy

```bash
pip install streamlit plotly pandas google-cloud-bigquery \
    statsmodels scipy pymc numpy

# Run locally
streamlit run app/finlens_app.py

# Deploy free to Streamlit Community Cloud:
# 1. Push repo to GitHub
# 2. Go to share.streamlit.io → Deploy
# 3. Add GCP service account JSON to Streamlit Secrets
```

### 9.2 Credentials Configuration

**Local development** — ADC handles auth automatically after:

```bash
gcloud auth application-default login
```

No secrets file is needed locally; `google-cloud-bigquery` picks up ADC by default.

**Streamlit Community Cloud deployment** — Streamlit Cloud cannot use your local ADC.
Create a dedicated service account for the deployed app (JSON keys are allowed for
deployment service accounts even when blocked for developer machines):

```bash
gcloud iam service-accounts create finlens-streamlit \
    --display-name="FinLens Streamlit Deploy"

gcloud projects add-iam-policy-binding project-58b73547-8fb7-4cff-b60 \
    --member="serviceAccount:finlens-streamlit@project-58b73547-8fb7-4cff-b60.iam.gserviceaccount.com" \
    --role="roles/bigquery.dataViewer"

gcloud iam service-accounts keys create streamlit-key.json \
    --iam-account=finlens-streamlit@project-58b73547-8fb7-4cff-b60.iam.gserviceaccount.com
```

In Streamlit Cloud dashboard → **App Settings → Secrets**, paste:

```toml
# .streamlit/secrets.toml  (Streamlit Cloud Secrets — never commit this file)
[gcp]
project = "project-58b73547-8fb7-4cff-b60"
credentials = '''
{ ...paste contents of streamlit-key.json here... }
'''
```

Add `.streamlit/secrets.toml` to `.gitignore` for local use.

### 9.3 Full Streamlit App

```python
# app/finlens_app.py
"""
FinLens — Regulatory Analytics Platform
Two-tab Streamlit app:
  Tab 1: Lending Funnel Dashboard  (replaces Tableau)
  Tab 2: Regulatory Impact Explorer (DiD + Investor ROI)
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import statsmodels.formula.api as smf
import json, os
from google.cloud import bigquery
from google.oauth2 import service_account

# ── Page config ──────────────────────────────────────────────────────
st.set_page_config(
    page_title = "FinLens — Regulatory Analytics",
    page_icon  = "🏦",
    layout     = "wide",
    initial_sidebar_state = "expanded",
)

st.markdown("""
<style>
    .metric-card {
        background: #f8f9fa; border-radius: 8px;
        padding: 16px; text-align: center;
    }
    .metric-value { font-size: 28px; font-weight: 700; color: #1f3b6e; }
    .metric-label { font-size: 12px; color: #666; margin-top: 4px; }
</style>
""", unsafe_allow_html=True)

# ── BigQuery client ──────────────────────────────────────────────────
@st.cache_resource
def get_bq_client():
    try:
        # Streamlit Cloud: load from secrets
        cred_dict = json.loads(st.secrets["gcp"]["credentials"])
        creds     = service_account.Credentials.from_service_account_info(cred_dict)
        return bigquery.Client(project=st.secrets["gcp"]["project"], credentials=creds)
    except Exception:
        # Local: use GOOGLE_APPLICATION_CREDENTIALS env var
        return bigquery.Client(project="project-58b73547-8fb7-4cff-b60")

CLIENT  = get_bq_client()
PROJECT = "project-58b73547-8fb7-4cff-b60"

@st.cache_data(ttl=3600, show_spinner="Loading data from BigQuery...")
def load_table(table: str) -> pd.DataFrame:
    df = CLIENT.query(
        f"SELECT * FROM `{PROJECT}.marts.{table}`"
    ).to_dataframe()
    df.columns = df.columns.str.lower()
    return df

# ── ROI helpers ──────────────────────────────────────────────────────
def rental_roi(pv, ltv, interest_rate, hold_yrs, annual_appreciation, approval_delta):
    loan   = pv * ltv
    equity = pv - loan
    r_mo   = interest_rate / 12
    n      = 30 * 12
    pmt    = loan * (r_mo*(1+r_mo)**n) / ((1+r_mo)**n - 1)
    noi    = (pv/18) * 0.95 * 0.60
    net_cf = noi - pmt*12
    adj_ap = annual_appreciation + approval_delta*(-0.30)
    tv     = pv * (1+adj_ap)**hold_yrs
    bal    = loan * ((1+r_mo)**n - (1+r_mo)**(hold_yrs*12)) / ((1+r_mo)**n - 1)
    total_return = net_cf*hold_yrs + (tv - bal - tv*0.06 - equity)
    return {
        "annualized_roi":       total_return / (equity * hold_yrs),
        "net_cash_flow_pa":     net_cf,
        "cap_rate":             noi / pv,
        "dscr":                 noi / (pmt*12),
        "adj_appreciation":     adj_ap,
        "equity":               equity,
    }

def flip_roi(pv, ltv, interest_rate, hold_months, annual_appreciation, approval_delta):
    loan     = pv * ltv
    equity   = pv - loan
    reno     = pv * 0.10
    carry    = loan * (interest_rate/12) * hold_months
    total_in = equity + reno + carry
    adj_ap   = annual_appreciation + approval_delta*(-0.30)
    arv      = pv * (1 + adj_ap*(hold_months/12)) + reno*1.20
    net_proc = arv - loan - arv*0.06
    profit   = net_proc - total_in
    return {
        "annualized_roi": (1 + profit/total_in)**(12/hold_months) - 1,
        "gross_profit":   profit,
        "arv":            arv,
        "total_cost":     total_in,
    }

# ── Sidebar ──────────────────────────────────────────────────────────
with st.sidebar:
    st.image("https://img.icons8.com/color/96/bank-building.png", width=60)
    st.title("FinLens")
    st.caption("Regulatory Analytics · HMDA 2018–2023")
    st.divider()

    st.subheader("📊 Funnel Filters")
    year_range  = st.slider("Year Range", 2018, 2023, (2018, 2023))
    loan_types  = st.multiselect(
        "Loan Types", ["conventional","fha","va","usda"],
        default=["conventional","fha"]
    )
    income_tiers = st.multiselect(
        "Income Tiers", ["low_income","moderate_income","middle_income","high_income"],
        default=["moderate_income","middle_income","high_income"]
    )

    st.divider()
    st.subheader("⚖️ DiD Controls")
    treatment_state  = st.selectbox("Treatment State", ["CA"])
    control_states   = st.multiselect("Control States",["TX","FL","OH","NY","IL"],
                                       default=["TX","FL","OH"])
    pre_period       = st.slider("Pre-Period", 2018, 2019, (2018, 2019))
    post_period      = st.slider("Post-Period", 2020, 2023, (2020, 2021))
    did_outcome      = st.selectbox("DiD Outcome",
                                    ["approval_rate","origination_rate","avg_ltv","pct_missing_income"])

    st.divider()
    st.subheader("🏠 Investor Profile")
    prop_value    = st.number_input("Property Value ($)", 200_000, 2_000_000, 500_000, 50_000)
    ltv_pct       = st.slider("LTV", 0.50, 0.80, 0.75, 0.05)
    hold_yrs      = st.slider("Hold Period (yrs)", 1, 10, 5)
    base_apprec   = st.slider("Base Appreciation (%/yr)", 1.0, 8.0, 4.0, 0.5) / 100
    investor_type = st.radio("Strategy", ["Buy-and-Hold", "Fix-and-Flip"])

# ═══════════════════════════════════════════════════════════════════════
# TABS
# ═══════════════════════════════════════════════════════════════════════
tab1, tab2 = st.tabs([
    "📊 Lending Funnel Dashboard",
    "⚖️ Regulatory Impact Explorer",
])

# ──────────────────────────────────────────────────────────────────────
# TAB 1 — LENDING FUNNEL DASHBOARD
# ──────────────────────────────────────────────────────────────────────
with tab1:
    st.header("Lending Funnel Dashboard")
    st.caption("Application → Approval → Origination · Powered by BigQuery + dbt")

    funnel_df = load_table("mart_lending_funnel")
    kpi_df    = load_table("mart_kpi_dashboard")

    # Apply filters
    f_df = funnel_df[
        funnel_df["activity_year"].between(*year_range)
        & funnel_df["loan_type_label"].isin(loan_types)
        & funnel_df["income_tier"].isin(income_tiers)
    ]

    # ── KPI Scorecards ────────────────────────────────────────────────
    total_apps  = int(f_df["total_applications"].sum())
    avg_apr     = f_df["approval_rate"].mean()
    avg_orig    = f_df["origination_rate"].mean()
    avg_denial  = f_df["denial_rate"].mean()
    avg_loan    = f_df["avg_loan_amount"].mean()
    total_vol   = f_df["total_loan_volume"].sum()

    c1,c2,c3,c4,c5,c6 = st.columns(6)
    for col, label, val, fmt in zip(
        [c1,c2,c3,c4,c5,c6],
        ["Total Applications","Approval Rate","Origination Rate",
         "Denial Rate","Avg Loan Amount","Total Volume ($B)"],
        [total_apps, avg_apr, avg_orig, avg_denial, avg_loan, total_vol/1e9],
        ["{:,.0f}","{:.1%}","{:.1%}","{:.1%}","${:,.0f}","${:.2f}B"]
    ):
        col.markdown(f"""
        <div class="metric-card">
          <div class="metric-value">{fmt.format(val)}</div>
          <div class="metric-label">{label}</div>
        </div>""", unsafe_allow_html=True)

    st.markdown("---")

    row1_l, row1_r = st.columns([1.2, 1])

    # ── Approval Rate by State (Choropleth Map) ───────────────────────
    with row1_l:
        st.subheader("Approval Rate by State")
        state_agg = f_df.groupby("state_code").agg(
            approval_rate=("approval_rate","mean"),
            total_apps=("total_applications","sum"),
        ).reset_index()

        fig_map = px.choropleth(
            state_agg,
            locations="state_code",
            locationmode="USA-states",
            color="approval_rate",
            scope="usa",
            color_continuous_scale="RdYlGn",
            range_color=[0.5, 0.85],
            hover_data={"total_apps": ":,.0f", "approval_rate": ":.1%"},
            labels={"approval_rate": "Approval Rate", "state_code": "State"},
        )
        fig_map.update_layout(
            height=320,
            margin=dict(l=0,r=0,t=20,b=0),
            coloraxis_colorbar=dict(tickformat=".0%"),
        )
        st.plotly_chart(fig_map, use_container_width=True)

    # ── Funnel Waterfall ──────────────────────────────────────────────
    with row1_r:
        st.subheader("Application Funnel")
        funnel_totals = f_df.agg({
            "total_applications": "sum",
            "total_approved":     "sum",
            "total_originated":   "sum",
            "total_denied":       "sum",
            "total_withdrawn":    "sum",
        })
        fig_funnel = go.Figure(go.Funnel(
            y=["Applications","Approved","Originated","Denied","Withdrawn"],
            x=[
                funnel_totals["total_applications"],
                funnel_totals["total_approved"],
                funnel_totals["total_originated"],
                funnel_totals["total_denied"],
                funnel_totals["total_withdrawn"],
            ],
            textinfo="value+percent initial",
            marker_color=["#1f3b6e","#2196F3","#4CAF50","#F44336","#FF9800"],
        ))
        fig_funnel.update_layout(height=320, margin=dict(l=0,r=0,t=20,b=0))
        st.plotly_chart(fig_funnel, use_container_width=True)

    row2_l, row2_r = st.columns(2)

    # ── Approval Rate Trend by Regulatory Era ─────────────────────────
    with row2_l:
        st.subheader("Approval Rate Trend by State")
        trend_states = control_states + [treatment_state]
        trend_df = funnel_df[
            funnel_df["state_code"].isin(trend_states)
            & funnel_df["activity_year"].between(*year_range)
            & funnel_df["loan_type_label"].isin(loan_types)
        ].groupby(["activity_year","state_code"])["approval_rate"].mean().reset_index()

        fig_trend = px.line(
            trend_df, x="activity_year", y="approval_rate",
            color="state_code", markers=True,
            color_discrete_map={treatment_state: "#F44336"},
            labels={"approval_rate":"Approval Rate","activity_year":"Year"},
        )
        fig_trend.add_vline(x=2019.5, line_dash="dash",
                            line_color="gray", annotation_text="CCPA")
        fig_trend.update_yaxes(tickformat=".0%")
        fig_trend.update_layout(height=300, margin=dict(l=0,r=0,t=20,b=0))
        st.plotly_chart(fig_trend, use_container_width=True)

    # ── Approval Rate by Income Tier ──────────────────────────────────
    with row2_r:
        st.subheader("Approval Rate by Income Tier")
        tier_order = ["low_income","moderate_income","middle_income","high_income"]
        tier_df = f_df.groupby(["income_tier","activity_year"])["approval_rate"].mean().reset_index()
        tier_df["income_tier"] = pd.Categorical(tier_df["income_tier"],
                                                 categories=tier_order, ordered=True)
        tier_df = tier_df.sort_values("income_tier")

        fig_tier = px.bar(
            tier_df.groupby("income_tier")["approval_rate"].mean().reset_index(),
            x="income_tier", y="approval_rate",
            color="income_tier",
            color_discrete_sequence=px.colors.sequential.Blues[2:],
            labels={"approval_rate":"Avg Approval Rate","income_tier":"Income Tier"},
        )
        fig_tier.update_yaxes(tickformat=".0%")
        fig_tier.update_layout(height=300, margin=dict(l=0,r=0,t=20,b=0),
                               showlegend=False)
        st.plotly_chart(fig_tier, use_container_width=True)

    # ── Contribution Margin by Vintage ────────────────────────────────
    st.subheader("Unit Economics — Contribution Margin by Vintage Cohort")
    econ_df = load_table("mart_unit_economics")
    econ_f  = econ_df[
        econ_df["loan_type_label"].isin(loan_types)
        & econ_df["income_tier"].isin(income_tiers)
    ].groupby("vintage_label").agg(
        avg_loan_amount         =("avg_loan_amount","mean"),
        avg_annual_interest_rev =("avg_annual_interest_revenue","mean"),
        est_orig_cost           =("est_origination_cost_per_loan","mean"),
        est_servicing_cost      =("est_annual_servicing_cost","mean"),
        est_contribution_margin =("est_contribution_margin","mean"),
    ).reset_index().sort_values("vintage_label")

    fig_wf = go.Figure()
    fig_wf.add_trace(go.Bar(name="Interest Revenue",
                             x=econ_f["vintage_label"],
                             y=econ_f["avg_annual_interest_rev"],
                             marker_color="#2196F3"))
    fig_wf.add_trace(go.Bar(name="Origination Cost",
                             x=econ_f["vintage_label"],
                             y=-econ_f["est_orig_cost"],
                             marker_color="#FF9800"))
    fig_wf.add_trace(go.Bar(name="Servicing Cost",
                             x=econ_f["vintage_label"],
                             y=-econ_f["est_servicing_cost"],
                             marker_color="#F44336"))
    fig_wf.add_trace(go.Scatter(name="Net Margin",
                                 x=econ_f["vintage_label"],
                                 y=econ_f["est_contribution_margin"],
                                 mode="lines+markers",
                                 line=dict(color="darkgreen", width=2.5)))
    fig_wf.update_layout(
        barmode="relative",
        height=300,
        margin=dict(l=0,r=0,t=20,b=0),
        yaxis_tickformat="$,.0f",
        legend=dict(orientation="h", y=1.1),
    )
    st.plotly_chart(fig_wf, use_container_width=True)

# ──────────────────────────────────────────────────────────────────────
# TAB 2 — REGULATORY IMPACT EXPLORER
# ──────────────────────────────────────────────────────────────────────
with tab2:
    st.header("Regulatory Impact Explorer")
    st.caption("Difference-in-Differences · CCPA Effect on Lending · Real Estate Investor ROI")

    reg_df = load_table("mart_regulatory_cohort")

    subtab1, subtab2, subtab3, subtab4 = st.tabs([
        "Parallel Trends", "DiD Estimate", "Event Study", "Investor ROI"
    ])

    # ── Parallel Trends ───────────────────────────────────────────────
    with subtab1:
        st.subheader("Parallel Trends Check")
        st.info("Pre-period lines should be parallel for DiD to be valid.")

        plot_states = [treatment_state] + control_states
        pt_df = reg_df[
            reg_df["state_code"].isin(plot_states)
            & reg_df["activity_year"].between(pre_period[0], post_period[1])
        ].groupby(["activity_year","state_code"])[did_outcome].mean().reset_index()

        fig_pt = px.line(
            pt_df, x="activity_year", y=did_outcome,
            color="state_code", markers=True,
            color_discrete_map={treatment_state: "#F44336"},
            labels={did_outcome: did_outcome.replace("_"," ").title(),
                    "activity_year": "Year"},
        )
        fig_pt.add_vline(x=pre_period[1]+0.5, line_dash="dash",
                         line_color="red", annotation_text="Treatment")
        if "rate" in did_outcome or "pct" in did_outcome:
            fig_pt.update_yaxes(tickformat=".1%")
        fig_pt.update_layout(height=380)
        st.plotly_chart(fig_pt, use_container_width=True)

    # ── DiD Estimate ──────────────────────────────────────────────────
    with subtab2:
        st.subheader("DiD Regression Results")

        df_did = reg_df[
            reg_df["state_code"].isin([treatment_state]+control_states)
            & reg_df["activity_year"].between(pre_period[0], post_period[1])
        ].copy()
        df_did["treat"] = (df_did["state_code"]==treatment_state).astype(int)
        df_did["post"]  = (df_did["activity_year"] > pre_period[1]).astype(int)
        df_did["did"]   = df_did["treat"] * df_did["post"]

        with st.spinner("Running DiD regression..."):
            mod = smf.ols(
                f"{did_outcome} ~ treat + post + did"
                " + unemployment_rate + hpi + mortgage_rate_30yr",
                data=df_did
            ).fit(cov_type="HC3")

        did_c  = mod.params.get("did", 0)
        did_p  = mod.pvalues.get("did", 1)
        did_ci = mod.conf_int().loc["did"] if "did" in mod.conf_int().index else [0,0]

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("DiD Estimate (β₃)", f"{did_c:+.4f}",
                  delta=f"{did_c*100:+.2f} pp")
        m2.metric("p-value", f"{did_p:.4f}",
                  delta="Significant ✓" if did_p < 0.05 else "Not significant",
                  delta_color="normal" if did_p < 0.05 else "off")
        m3.metric("95% CI Low",  f"{did_ci[0]:.4f}")
        m4.metric("95% CI High", f"{did_ci[1]:.4f}")

        # Means table
        means = df_did.groupby(["treat","post"])[did_outcome].mean().unstack()
        means.index   = ["Control", "Treatment (CA)"]
        means.columns = [f"Pre ({pre_period[0]}-{pre_period[1]})",
                         f"Post ({post_period[0]}-{post_period[1]})"]
        means["Δ (Post–Pre)"]  = means.iloc[:,1] - means.iloc[:,0]
        did_manual = means.loc["Treatment (CA)","Δ (Post–Pre)"] - \
                     means.loc["Control","Δ (Post–Pre)"]
        means.loc["DiD"] = ["—", "—", f"{did_manual:+.4f}"]

        st.dataframe(means.round(4), use_container_width=True)

        with st.expander("Full regression output"):
            st.code(str(mod.summary()), language="text")

    # ── Event Study ───────────────────────────────────────────────────
    with subtab3:
        st.subheader("Event Study — Dynamic Treatment Effects")
        st.caption("Coefficients at t=−1 omitted as reference. Pre-period ≈ 0 validates parallel trends.")

        df_es = reg_df[reg_df["state_code"].isin([treatment_state]+control_states)].copy()
        df_es["event_time"] = df_es["activity_year"] - (pre_period[1]+1)
        df_es["treat"]      = (df_es["state_code"]==treatment_state).astype(int)

        for t in df_es["event_time"].unique():
            if t == -1: continue
            col = f"ca_t{'p' if t>=0 else 'm'}{abs(t)}"
            df_es[col] = ((df_es["treat"]==1)&(df_es["event_time"]==t)).astype(int)

        dummies   = [c for c in df_es.columns if c.startswith("ca_t")]
        if dummies:
            formula_es = (f"{did_outcome} ~ treat + {' + '.join(dummies)}"
                          " + unemployment_rate + hpi + mortgage_rate_30yr + C(activity_year)")
            mod_es = smf.ols(formula_es, data=df_es).fit(cov_type="HC3")

            event_times = sorted(df_es["event_time"].unique())
            es_rows = []
            for t in event_times:
                col = f"ca_t{'p' if t>=0 else 'm'}{abs(t)}"
                if t == -1:
                    es_rows.append({"t":t,"coef":0.0,"lo":0.0,"hi":0.0})
                elif col in mod_es.params:
                    es_rows.append({"t":t,
                                    "coef": mod_es.params[col],
                                    "lo":   mod_es.conf_int().loc[col,0],
                                    "hi":   mod_es.conf_int().loc[col,1]})

            es_df = pd.DataFrame(es_rows)

            fig_es = go.Figure()
            fig_es.add_trace(go.Scatter(
                x=es_df["t"], y=es_df["coef"],
                error_y=dict(type="data",
                             array=es_df["hi"]-es_df["coef"],
                             arrayminus=es_df["coef"]-es_df["lo"],
                             visible=True),
                mode="markers+lines",
                marker=dict(size=9, color="#1f3b6e"),
                line=dict(color="#1f3b6e"),
                name="DiD Coefficient",
            ))
            fig_es.add_hline(y=0, line_dash="dash", line_color="black", line_width=0.8)
            fig_es.add_vline(x=-0.5, line_dash="dot",  line_color="red",
                             annotation_text="Treatment", annotation_position="top right")
            fig_es.update_layout(
                height=380,
                xaxis_title="Event Time (t=0: treatment year)",
                yaxis_title="DiD Coefficient",
                title=f"Event Study: CCPA Effect on {did_outcome.replace('_',' ').title()}",
            )
            st.plotly_chart(fig_es, use_container_width=True)

    # ── Investor ROI ──────────────────────────────────────────────────
    with subtab4:
        st.subheader("Real Estate Investor ROI — Regulatory Scenario Analysis")
        st.caption("DiD approval rate estimate translated into HPI demand shock → ROI impact")

        ca_pre_rate  = reg_df[reg_df["state_code"].eq("CA")
                              & reg_df["activity_year"].isin(range(pre_period[0], pre_period[1]+1))
                              ]["avg_interest_rate"].mean() or 4.5
        ca_post_rate = reg_df[reg_df["state_code"].eq("CA")
                              & reg_df["activity_year"].isin(range(post_period[0], post_period[1]+1))
                              ]["avg_interest_rate"].mean() or 5.0

        did_est_input = st.number_input(
            "DiD Estimate from 'DiD Estimate' tab (approval rate)",
            value=float(round(did_c, 4)) if "did_c" in dir() else -0.018,
            min_value=-0.20, max_value=0.10, step=0.001, format="%.4f"
        )

        st.markdown(f"""
        **Transmission mechanism:**
        A `{did_est_input:+.3f}` ({did_est_input*100:+.2f} pp) approval rate shock
        → reduces buyer demand pool → HPI growth compresses by
        `{abs(did_est_input)*0.30*100:.2f}` pp (empirical elasticity: 1pp approval ≈ 0.3pp HPI)
        """)

        scenarios = {
            "Baseline (Pre-Reg)":   {"rate": ca_pre_rate/100,        "delta": 0.0},
            "Post-CCPA (Observed)": {"rate": ca_post_rate/100,        "delta": did_est_input},
            "Stress (2× Effect)":   {"rate": (ca_post_rate+0.5)/100,  "delta": did_est_input*2},
        }

        if investor_type == "Buy-and-Hold":
            results = {
                n: rental_roi(prop_value, ltv_pct, s["rate"], hold_yrs,
                              base_apprec, s["delta"])
                for n, s in scenarios.items()
            }
            metrics = [
                ("Annualized ROI",       "annualized_roi",    "{:.1%}"),
                ("Net Cash Flow/yr",     "net_cash_flow_pa",  "${:,.0f}"),
                ("Cap Rate",             "cap_rate",          "{:.2%}"),
                ("DSCR",                 "dscr",              "{:.2f}"),
                ("Adj. Appreciation",    "adj_appreciation",  "{:.2%}"),
            ]
        else:
            results = {
                n: flip_roi(prop_value, ltv_pct, s["rate"], 6,
                            base_apprec, s["delta"])
                for n, s in scenarios.items()
            }
            metrics = [
                ("Annualized ROI",  "annualized_roi", "{:.1%}"),
                ("Hold ROI",        "roi_hold_period" if "roi_hold_period" in list(results.values())[0] else "annualized_roi", "{:.1%}"),
                ("ARV",             "arv",            "${:,.0f}"),
                ("Gross Profit",    "gross_profit",   "${:,.0f}"),
                ("Total Cost In",   "total_cost",     "${:,.0f}"),
            ]

        # Metrics table
        table_data = []
        for label, key, fmt in metrics:
            row = {"Metric": label}
            for sc_name in scenarios:
                val = results[sc_name].get(key, 0)
                row[sc_name] = fmt.format(val)
            table_data.append(row)
        st.dataframe(pd.DataFrame(table_data).set_index("Metric"), use_container_width=True)

        # ROI bar chart
        sc_names = list(scenarios.keys())
        roi_vals = [results[n]["annualized_roi"]*100 for n in sc_names]
        colors   = ["#2196F3","#FF9800","#F44336"]

        fig_roi = go.Figure(go.Bar(
            x=sc_names, y=roi_vals,
            marker_color=colors,
            text=[f"{v:.1f}%" for v in roi_vals],
            textposition="outside",
        ))
        fig_roi.update_layout(
            yaxis=dict(title="Annualized ROI (%)", ticksuffix="%"),
            height=360,
            title=f"{investor_type} ROI: ${prop_value:,.0f} Property · {ltv_pct:.0%} LTV · {hold_yrs}yr Hold",
            showlegend=False,
        )
        st.plotly_chart(fig_roi, use_container_width=True)

        # Sensitivity heatmap
        st.subheader("ROI Sensitivity: Rate × Regulatory Shock")
        rates  = np.arange(0.035, 0.085, 0.005)
        deltas = np.arange(-0.06, 0.01, 0.01)
        grid   = np.zeros((len(deltas), len(rates)))

        for i, d in enumerate(deltas):
            for j, r in enumerate(rates):
                if investor_type == "Buy-and-Hold":
                    res = rental_roi(prop_value, ltv_pct, r, hold_yrs, base_apprec, d)
                else:
                    res = flip_roi(prop_value, ltv_pct, r, 6, base_apprec, d)
                grid[i, j] = res["annualized_roi"] * 100

        fig_heat = go.Figure(go.Heatmap(
            z=grid,
            x=[f"{r:.1%}" for r in rates],
            y=[f"{d:+.0%}" for d in deltas],
            colorscale="RdYlGn",
            text=[[f"{v:.1f}%" for v in row] for row in grid],
            texttemplate="%{text}",
            colorbar=dict(title="Ann. ROI (%)"),
        ))
        fig_heat.update_layout(
            xaxis_title="Mortgage Rate",
            yaxis_title="Approval Rate Shock (DiD)",
            height=380,
            title="Investor ROI Sensitivity Heatmap",
        )
        st.plotly_chart(fig_heat, use_container_width=True)

        st.info(
            "**Methodology:** Approval rate δ from DiD is translated to HPI impact "
            "via empirical elasticity (1pp approval rate ≈ 0.3pp HPI growth). "
            "Interest rates from actual CA HMDA averages pre/post CCPA."
        )

# ── Footer ────────────────────────────────────────────────────────────
st.divider()
st.caption(
    "FinLens · Data: HMDA (CFPB) 2018–2023 · Macro: FRED (St. Louis Fed) · "
    "Warehouse: Google BigQuery · Transforms: dbt Core · "
    "Orchestration: Apache Airflow · Built with Streamlit + Plotly"
)
```

---

## 10. Analytical Coverage Map

| Analysis Layer | Streamlit Surface | Data Product | Method |
|---|---|---|---|
| Market Overview | Tab 1: Funnel chart, state map, approval rate trend | `mart_lending_funnel` + `mart_kpi_dashboard` | Descriptive / trend |
| Regulatory Impact | Tab 2 Scenario 1: 2×2 DiD | `mart_regulatory_cohort` | Causal inference |
| Multi-state Impact | Tab 2 Scenario 2: Staggered DiD | `mart_regulatory_cohort` | Causal inference |
| Timing Validation | Tab 2 Scenario 3: Event Study | `mart_regulatory_cohort` | Causal inference |
| Mechanism Test | Tab 2 Scenario 4: Triple DiD | `mart_regulatory_cohort` | Causal inference |
| Distributional Impact | Tab 2 Scenario 5: HTE / CausalForest | `mart_regulatory_cohort` | Causal ML |

---

## Quick Start Checklist

```
□  1.  Create GCP project at console.cloud.google.com — 10 min
□  2.  Authenticate: gcloud auth login && gcloud auth application-default login — 5 min
       (JSON key creation is blocked by org policy; ADC is used throughout)
□  3.  Grant your user BigQuery roles (dataEditor + jobUser) — 5 min
□  4.  Run: python setup/create_datasets.py && python setup/create_tables.py — 5 min
□  5.  Copy .env.example → .env; fill in GCP_PROJECT and FRED_API_KEY only
       (no GOOGLE_APPLICATION_CREDENTIALS needed with ADC)
□  5b. Verify: python config.py --validate   ← confirms env is wired up
□  6.  pip install -r requirements.txt — 5 min
□  7.  Download HMDA CSVs (start with 1 state for speed) — 20 min
       https://ffiec.cfpb.gov/data-browser/ → filter by state → download CSV
□  8.  python ingest/ingest_latest.py --source hmda --dry-run  (preview first)
□  9.  python ingest/ingest_latest.py  (loads HMDA 2018–2024 + FRED)
□ 10.  cd finlens_dbt && dbt run && dbt test && dbt docs serve — 30 min
□ 11.  streamlit run app/finlens_app.py
       Tab 1: mortgage funnel KPIs · Tab 2: all 5 causal scenarios
□ 12.  Push to GitHub → deploy at share.streamlit.io
       → create finlens-streamlit service account → add JSON to Streamlit Secrets (§9.2)
□ 13.  Airflow: airflow db init && add bigquery_finlens connection → trigger DAG
□ 14.  Run scenario tests: pytest tests/ -v
```

---

*FinLens · HMDA public data from CFPB · Macroeconomic controls from FRED (St. Louis Fed)*
*Stack: Google BigQuery (free tier) · dbt Core · Apache Airflow · Streamlit + Plotly*

---

## 11. Scenario Testing Framework

### 11.1 Design Philosophy

All five scenarios share the same underlying data (`mart_regulatory_cohort`) and the same
research question — did consumer data-privacy regulation change mortgage lending outcomes?
Each scenario applies a distinct econometric method to answer a progressively deeper causal
question:

```
mart_regulatory_cohort (HMDA × FRED)
              │
              ▼  ScenarioRunner (base class)
              │
   ┌──────────┼──────────┬──────────┬──────────┐
   ▼          ▼          ▼          ▼          ▼
  S1         S2         S3         S4         S5
 2×2 DiD  Staggered  Event     Triple     HTE /
 (CCPA     DiD        Study     DiD       CausalForest
 vs ctrl)  (CA/VA/CO) (timing)  (mechan.) (income tier)
   │          │          │          │          │
   ▼          ▼          ▼          ▼          ▼
Did it    Consistent  When did   Owner-occ  Who bears
happen?   across      lenders    vs investor the burden?
          states?     adjust?    effect?
```

**One Streamlit app, one left-rail selector — all five scenarios on demand.**

### 11.2 Project Structure

```
finlens/
├── config.py                        ← central config (env vars + domain constants)
├── .env                             ← local secrets (never committed)
├── .env.example                     ← template — copy to .env and fill in values
├── scenarios/
│   ├── __init__.py
│   ├── base.py                      ← abstract ScenarioRunner + ScenarioResult dataclass
│   ├── scenario_s1_did.py           ← Standard 2×2 DiD (HC3-robust OLS)
│   ├── scenario_s2_staggered.py     ← Staggered DiD (cohort ATTs)
│   ├── scenario_s3_event.py         ← Event Study (dynamic coefficients)
│   ├── scenario_s4_triple.py        ← Triple DiD (mechanism test)
│   ├── scenario_s5_hte.py           ← HTE / CausalForest (income tier CATE)
│   └── runner.py                    ← unified dispatcher + run_scenario_by_number()
├── ingest/
│   └── ingest_latest.py             ← HMDA + FRED ingestion
├── analysis/
│   └── data_loader.py
└── app/
    └── finlens_app.py               ← Streamlit app (Tab 1 funnel + Tab 2 scenarios)
```

> All files import config with `from config import cfg`. Domain constants (`states`, `loan_types`, `covariates`, etc.) live exclusively in `config.py` — see §1.1 for the full reference.

### 11.3 Base Scenario Class

```python
# scenarios/base.py
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import pandas as pd
import plotly.graph_objects as go

@dataclass
class ScenarioResult:
    """Standardized output contract — all scenarios return this shape."""
    scenario_name:   str
    effect_label:    str          # human label for the estimate

    # Core estimate
    primary_estimate:    float        # main effect size (ATT or avg CATE)
    primary_se:          float
    primary_pval:        float
    primary_ci:          tuple[float, float]

    # Narrative
    executive_summary:   str          # 2-3 sentence plain-English conclusion
    methodology_note:    str          # brief description of the estimator pipeline

    # Plotly figures (rendered in Streamlit)
    fig_primary:         go.Figure    # main results chart
    fig_secondary:       go.Figure    # supporting chart
    fig_tertiary:        go.Figure | None = None  # optional third chart

    # Raw results for download
    results_df:          pd.DataFrame = field(default_factory=pd.DataFrame)


class ScenarioRunner(ABC):
    """Abstract base — all five scenarios implement this interface."""

    def __init__(self, df: pd.DataFrame,
                 treatment_state: str = "CA",
                 control_states: list[str] = None,
                 pre_years: tuple[int,int] = (2018, 2019),
                 post_years: tuple[int,int] = (2020, 2021),
                 outcome: str = "approval_rate"):
        self.df              = df
        self.treatment_state = treatment_state
        self.control_states  = control_states or ["TX","FL","OH"]
        self.pre_years       = pre_years
        self.post_years      = post_years
        self.outcome         = outcome

    def _panel(self) -> pd.DataFrame:
        """State × year panel filtered to treatment + control states."""
        keep = [self.treatment_state] + self.control_states
        years = list(range(self.pre_years[0], self.post_years[1] + 1))
        return self.df[
            self.df["state_code"].isin(keep)
            & self.df["activity_year"].isin(years)
        ].copy()

    @abstractmethod
    def run(self) -> ScenarioResult:
        """Execute all estimation steps and return a ScenarioResult."""
        ...

    @property
    @abstractmethod
    def name(self) -> str: ...
```


### 11.4 Scenario S1 — Standard 2×2 DiD (CCPA vs. Control States)

**Business question:** Did CCPA measurably change mortgage lending outcomes in California
relative to comparable non-adopting states (TX, FL, OH), and if so, by how much?

**Method:** HC3-robust OLS with state fixed effects and macro controls (unemployment rate,
HPI, 30yr mortgage rate). Treatment: CA post-2020. Control: TX, FL, OH.

```python
# scenarios/scenario_s1_did.py
from .base import ScenarioResult, ScenarioRunner
import statsmodels.formula.api as smf

class ScenarioS1DiD(ScenarioRunner):

    @property
    def name(self) -> str:
        return "S1_2x2_DiD"

    def run(self) -> ScenarioResult:
        d = self._panel()
        d["treat"] = (d["state_code"] == self.treatment_state).astype(int)
        d["post"]  = (d["activity_year"] > self.pre_years[1]).astype(int)
        d["did"]   = d["treat"] * d["post"]

        mod = smf.ols(
            f"{self.outcome} ~ treat + post + did + "
            "unemployment_rate + hpi + mortgage_rate_30yr + C(state_code)",
            data=d.dropna()
        ).fit(cov_type="HC3")

        est  = float(mod.params["did"])
        se   = float(mod.bse["did"])
        pval = float(mod.pvalues["did"])
        ci   = tuple(mod.conf_int().loc["did"])

        return ScenarioResult(
            scenario_name     = self.name,
            effect_label      = f"CCPA ATT — {self.outcome}",
            primary_estimate  = est,
            primary_se        = se,
            primary_pval      = pval,
            primary_ci        = ci,
            executive_summary = (
                f"CCPA {'reduced' if est < 0 else 'increased'} {self.outcome} "
                f"by {abs(est*100):.2f} pp in CA vs. control states "
                f"(ATT={est:+.4f}, SE={se:.4f}, p={pval:.4f})."
            ),
            methodology_note  = "Standard 2×2 DiD · HC3 SEs · state FE · macro controls.",
            fig_primary       = ...,   # time-series line chart
            fig_secondary     = ...,   # 2×2 means table
        )
```

**Key outputs:**
- 2×2 means table (Pre/Post × CA/Control)
- ATT coefficient + 95% CI
- Time-series chart with post-law amber shading

---

### 11.5 Scenario S2 — Staggered DiD (CCPA / VCDPA / CPA)

**Business question:** Is there a consistent causal effect across all adopting states, or
does it vary by law design and adoption cohort?

**Method:** Cohort-specific 2×2 DiD for CA (2020), VA (2023), CO (2023) using never-treated
states as controls. Averages across cohorts approximate the Callaway & Sant'Anna ATT
aggregator (avoids TWFE bias from using early-treated units as controls for later ones).

```python
# scenarios/scenario_s2_staggered.py
TREATED_COHORTS = {
    "CA": {"law_year": 2020, "law_name": "CCPA"},
    "VA": {"law_year": 2023, "law_name": "VCDPA"},
    "CO": {"law_year": 2023, "law_name": "CPA"},
}

class ScenarioS2Staggered(ScenarioRunner):

    @property
    def name(self) -> str:
        return "S2_Staggered_DiD"

    def _cohort_did(self, treated_state: str, law_year: int) -> dict:
        """Clean 2×2 DiD for one cohort vs. never-treated controls."""
        never_treated = [s for s in self.control_states if s not in TREATED_COHORTS]
        pre  = (law_year - 2, law_year - 1)
        post = (law_year,     law_year + 1)
        d = self.df[
            self.df["state_code"].isin([treated_state] + never_treated)
            & self.df["activity_year"].between(pre[0], post[1])
        ].copy()
        d["treat"] = (d["state_code"] == treated_state).astype(int)
        d["post"]  = (d["activity_year"] >= law_year).astype(int)
        d["did"]   = d["treat"] * d["post"]
        mod = smf.ols(f"{self.outcome} ~ treat + post + did", data=d.dropna()).fit(cov_type="HC3")
        return {"estimate": float(mod.params["did"]), "se": float(mod.bse["did"]),
                "pval": float(mod.pvalues["did"])}

    def run(self) -> ScenarioResult:
        results = {st: self._cohort_did(st, meta["law_year"])
                   for st, meta in TREATED_COHORTS.items()
                   if st in self.df["state_code"].values}
        mean_att = sum(r["estimate"] for r in results.values()) / len(results)
        ...
```

**Key outputs:**
- Per-cohort ATT bar chart (CA / VA / CO with 95% CI)
- Relative-year trend lines (treated − control diff by years since law)
- Mean ATT across cohorts

---

### 11.6 Scenario S3 — Event Study (Dynamic Coefficients)

**Business question:** When exactly did lenders change behaviour relative to CCPA's
enactment date — and does the timing rule out alternative explanations?

**Method:** Dynamic DiD with leads (β₋₄…β₋₂) and lags (β₀…β₊₃) around the law effective
date. t = −1 omitted as reference period. HC3-robust SEs.

```python
# scenarios/scenario_s3_event.py
class ScenarioS3Event(ScenarioRunner):

    @property
    def name(self) -> str:
        return "S3_Event_Study"

    def run(self) -> ScenarioResult:
        d = self._panel()
        d["treat"]      = (d["state_code"] == self.treatment_state).astype(int)
        d["event_time"] = d["activity_year"] - (self.pre_years[1] + 1)
        ref_t = -1

        for t in d["event_time"].unique():
            if t == ref_t: continue
            col = f"ca_t{'p' if t>=0 else 'm'}{abs(int(t))}"
            d[col] = ((d["treat"]==1) & (d["event_time"]==t)).astype(int)

        dummies = [c for c in d.columns if c.startswith("ca_t")]
        mod = smf.ols(
            f"{self.outcome} ~ treat + {' + '.join(dummies)} + C(activity_year)",
            data=d.dropna()
        ).fit(cov_type="HC3")
        ...
```

**Pre-trend F-test:** Max |pre-period coefficient| < 0.015 → parallel trends supported.

**Key outputs:**
- Dynamic coefficient plot (leads and lags with 95% CI error bars)
- Pre-trend verdict card
- Peak effect period identification

---

### 11.7 Scenario S4 — Triple DiD (Mechanism Test)

**Business question:** Did CCPA specifically harm owner-occupied applicants — who are
CCPA-covered natural persons — more than investor borrowers who are outside the law's scope?

**Method:** Triple DiD (DiDiD) = (CA − Control) × (Owner-Occ − Investor) × (Post − Pre).
Investor loans within CA serve as a within-treated-state placebo. A significant DiDiD
coefficient isolates CCPA's data-restriction mechanism from California-specific macro shocks.

```python
# scenarios/scenario_s4_triple.py
class ScenarioS4TripleDiD(ScenarioRunner):

    @property
    def name(self) -> str:
        return "S4_Triple_DiD"

    def run(self) -> ScenarioResult:
        d = self._panel()
        d["treat"]  = (d["state_code"] == self.treatment_state).astype(int)
        d["post"]   = (d["activity_year"] > self.pre_years[1]).astype(int)
        d["owner"]  = (d["occupancy_type"] == 1).astype(int)   # 1=owner-occ, 2=investor
        d["didid"]  = d["treat"] * d["post"] * d["owner"]      # triple interaction
        d["did_t"]  = d["treat"] * d["post"]
        d["did_o"]  = d["treat"] * d["owner"]
        d["post_o"] = d["post"]  * d["owner"]

        mod = smf.ols(
            f"{self.outcome} ~ treat+post+owner+did_t+did_o+post_o+didid+C(state_code)",
            data=d.dropna()
        ).fit(cov_type="HC3")

        est = float(mod.params["didid"])   # the DiDiD coefficient
        ...
```

**Interpretation:** If `didid` is significant and investor loans within CA are flat, the
driver is CCPA's personal-data restriction — not a California macro shock.

**Key outputs:**
- Grouped bar chart: Pre/Post × Owner-Occ/Investor × CA/Control
- DiDiD decomposition table
- Mechanism interpretation card

---

### 11.8 Scenario S5 — Heterogeneous Treatment Effects (Income Tier)

**Business question:** Does the lending impact of CCPA fall disproportionately on
lower-income borrowers — and which borrower characteristics drive the heterogeneity?

**Method:** Stratified OLS DiD run independently per FFIEC income tier (low / moderate /
middle / high). Optional EconML CausalForestDML provides a continuous CATE estimate using
GBM nuisance models. Install with `pip install econml`.

```python
# scenarios/scenario_s5_hte.py
TIER_ORDER = ["low_income", "moderate_income", "middle_income", "high_income"]

class ScenarioS5HTE(ScenarioRunner):

    @property
    def name(self) -> str:
        return "S5_HTE_CausalForest"

    def _tier_did(self, tier: str) -> dict:
        sub = self.df[self.df["income_tier"] == tier]
        d   = sub[sub["state_code"].isin(
                [self.treatment_state] + self.control_states)].copy()
        d["treat"] = (d["state_code"] == self.treatment_state).astype(int)
        d["post"]  = (d["activity_year"] > self.pre_years[1]).astype(int)
        d["did"]   = d["treat"] * d["post"]
        mod = smf.ols(f"{self.outcome} ~ treat+post+did", data=d.dropna()).fit(cov_type="HC3")
        return {"estimate": float(mod.params["did"]), "se": float(mod.bse["did"]),
                "pval": float(mod.pvalues["did"])}

    def run(self) -> ScenarioResult:
        tier_results = {t: self._tier_did(t) for t in TIER_ORDER}
        # Optional CausalForest CATE
        try:
            from econml.dml import CausalForestDML
            # ... fit and extract per-tier avg CATE ...
        except ImportError:
            pass   # falls back to stratified OLS only
        ...
```

**Policy implication:** If low-income borrowers experience larger negative ATTs than
high-income borrowers, CCPA may widen the credit-access gap by income — a fair-lending
finding despite consumer-friendly legislative intent.

**Key outputs:**
- Horizontal bar chart: ATT by income tier with 95% CI
- ATT gradient line chart (OLS vs. CausalForest CATE if available)
- Per-tier significance flags

---

### 11.9 Unified Runner

```python
# scenarios/runner.py
from .scenario_s1_did       import ScenarioS1DiD
from .scenario_s2_staggered import ScenarioS2Staggered
from .scenario_s3_event     import ScenarioS3Event
from .scenario_s4_triple    import ScenarioS4TripleDiD
from .scenario_s5_hte       import ScenarioS5HTE

SCENARIO_MAP = {
    "S1 — Standard 2×2 DiD (CCPA vs. Control)":        ScenarioS1DiD,
    "S2 — Multi-State Staggered DiD (CCPA/VCDPA/CPA)": ScenarioS2Staggered,
    "S3 — Event Study (Dynamic Coefficients)":          ScenarioS3Event,
    "S4 — Triple DiD (Investor vs. Owner-Occ)":         ScenarioS4TripleDiD,
    "S5 — Income Tier HTE (CausalForest)":              ScenarioS5HTE,
}

def run_scenario(scenario_key, df, treatment_state="CA",
                 control_states=None, pre_years=(2018,2019),
                 post_years=(2020,2021), outcome="approval_rate"):
    runner = SCENARIO_MAP[scenario_key](
        df=df, treatment_state=treatment_state,
        control_states=control_states or ["TX","FL","OH","NY","IL"],
        pre_years=pre_years, post_years=post_years, outcome=outcome,
    )
    return runner.run()

def run_scenario_by_number(number: int, df, **kwargs):
    """Call by number (1–5) for convenience."""
    key = list(SCENARIO_MAP.keys())[number - 1]
    return run_scenario(key, df, **kwargs)
```

---

### 11.10 Running Scenarios

```bash
# 1. Install dependencies
pip install statsmodels plotly streamlit google-cloud-bigquery
pip install econml   # optional — required for CausalForest in Scenario 5

# 2. Run a single scenario from Python
python - <<'EOF'
import sys; sys.path.insert(0, '.')
from scenarios.runner import run_scenario_by_number
from app.finlens_app import _synthetic_regulatory

df     = _synthetic_regulatory()
result = run_scenario_by_number(1, df)   # Scenario 1 — 2×2 DiD
print(result.executive_summary)
print(f"ATT = {result.primary_estimate:+.4f}  SE = {result.primary_se:.4f}  p = {result.primary_pval:.4f}")
EOF

# 3. Run all five in sequence
python - <<'EOF'
import sys; sys.path.insert(0, '.')
from scenarios.runner import SCENARIO_MAP, run_scenario
from app.finlens_app import _synthetic_regulatory

df = _synthetic_regulatory()
for key, cls in SCENARIO_MAP.items():
    r = run_scenario(key, df)
    sig = "✓" if r.primary_pval < 0.05 else "·"
    print(f"{sig}  {key:<52}  ATT={r.primary_estimate*100:+.2f}pp  p={r.primary_pval:.3f}")
EOF

# 4. Launch Streamlit (all 5 scenarios in Tab 2)
streamlit run app/finlens_app.py
```

---

### 11.11 Scenario Summary

| # | Method | Business question | Key output |
|---|---|---|---|
| 1 | 2×2 DiD (HC3 OLS) | Did CCPA change lending in CA vs. TX/FL/OH? | ATT coefficient + 2×2 means table |
| 2 | Staggered DiD | Consistent effect across CA/VA/CO? | Cohort ATT bar chart |
| 3 | Event Study | When did lenders adjust — before or after the law? | Dynamic β plot + pre-trend test |
| 4 | Triple DiD | Owner-occupied borrowers hit harder than investors? | DiDiD coefficient + grouped bars |
| 5 | HTE / CausalForest | Low-income borrowers bear the largest burden? | ATT by income tier + CATE gradient |

> Scenarios build sequentially: S1 establishes the fact → S2 generalises it → S3 validates
> timing → S4 isolates the mechanism → S5 maps who is most affected.

---

*FinLens · HMDA public data (CFPB) · Macro controls from FRED (St. Louis Fed)*
*Stack: Google BigQuery · dbt Core · Apache Airflow · Streamlit + Plotly · statsmodels · EconML*
