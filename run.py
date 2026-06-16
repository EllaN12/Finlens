
### 2.3 Create BigQuery Datasets
# setup/create_datasets.py

#%%

from google.cloud import bigquery
from config import cfg
PROJECT = cfg.project
REGION  = "US"


client   = bigquery.Client(project=PROJECT)
key    = cfg.fred_api_key
states = cfg.ingest_states
datasets = ["raw_hmda", "raw_fred", "staging", "intermediate", "marts"]

for ds_id in datasets:
    dataset = bigquery.Dataset(f"{PROJECT}.{ds_id}")
    dataset.location = REGION
    client.create_dataset(dataset, exists_ok=True)
    print(f"Dataset ready: {ds_id}")
    


#%%
### 2.4 Create Raw Tables
# setup/create_tables.py
from google.cloud import bigquery

PROJECT = cfg.project
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


# Or list every table currently in your Finlens datasets
for ds_id in datasets:
    for tbl in client.list_tables(f"{PROJECT}.{ds_id}"):
        print(tbl.full_table_id.replace(":", "."))
        
        
# %%
### 3.3 HMDA Ingestion → BigQuery

import os
import glob
import argparse
from datetime import datetime, timezone
import pandas as pd
from google.cloud import bigquery

PROJECT   = cfg.project
TABLE_ID  = cfg.table(cfg.bq_dataset_raw_hmda, "hmda_lar_raw")
DATA_DIR  = str(cfg.hmda_data_dir)

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

def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=None,
                        help="Single year to load; omit for all years")
    args = parser.parse_args(argv)
    client = bigquery.Client(project=PROJECT)

    years = [args.year] if args.year else list(range(2018, 2024))
    for year in years:
        print(f"\n=== HMDA {year} ===")
        load_year(year, client)

    print("\nIngestion complete.")


# Notebook: call main([]) or load_year(2018, client) — do not rely on auto-run below.
if __name__ == "__main__":
    import sys
    if "ipykernel" not in sys.modules:
        main()



### 5.3 Main Pipeline DAG ###
# dags/finlens_pipeline.py
from __future__ import annotations
import os, subprocess, sys
from datetime import datetime, timedelta
from pathlib import Path

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.google.cloud.hooks.bigquery import BigQueryHook
from airflow.utils.trigger_rule import TriggerRule

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))
from config import cfg  # loads .env → FRED_API_KEY, GCP_PROJECT

#%%
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


# %%
# dags/finlens_monitoring.py
import sys
from pathlib import Path

_monitor_repo = Path(__file__).resolve().parent
if str(_monitor_repo) not in sys.path:
    sys.path.insert(0, str(_monitor_repo))
from config import cfg

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.google.cloud.hooks.bigquery import BigQueryHook
from datetime import datetime, timedelta
import statistics

GCP_CONN    = "bigquery_finlens"
GCP_PROJECT = cfg.project
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
# %%
