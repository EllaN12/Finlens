"""
FinLens annual pipeline DAG — reads GCP_PROJECT and FRED_API_KEY from repo .env via config.py.
"""
#%%
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.google.cloud.hooks.bigquery import BigQueryHook
from airflow.utils.trigger_rule import TriggerRule

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
from config import cfg

HMDA_YEARS = list(range(2018, 2025))
DBT_PROJECT = str(REPO_ROOT / "finlens_dbt")
INGESTION_DIR = str(REPO_ROOT / "ingest")
GCP_CONN = "bigquery_finlens"
GCP_PROJECT = cfg.project

DEFAULT_ARGS = {
    "owner": "ella",
    "depends_on_past": False,
    "email": ["ndallaella@gmail.com"],
    "email_on_failure": True,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "execution_timeout": timedelta(hours=3),
}


def _run(cmd, cwd=None, env=None):
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
    cmd = ["dbt"] + (command.split() if isinstance(command, str) else list(command))
    if select:
        cmd += ["--select", select]
    if full_refresh:
        cmd.append("--full-refresh")
    cmd += [
        "--profiles-dir",
        str(REPO_ROOT / "finlens_dbt"),
        "--project-dir",
        DBT_PROJECT,
        "--target",
        "prod",
    ]
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
    dag_id="finlens_annual_pipeline",
    default_args=DEFAULT_ARGS,
    description="FinLens: HMDA+FRED ingestion → dbt → BigQuery marts",
    schedule="0 6 1 2 *",
    start_date=datetime(2024, 2, 1),
    catchup=False,
    max_active_runs=1,
    tags=["finlens", "hmda", "bigquery", "dbt"],
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

    fred_task = PythonOperator(task_id="ingest_fred", python_callable=ingest_fred)

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

    [*hmda_tasks, fred_task] >> dbt_staging
    dbt_staging >> dbt_intermediate >> dbt_marts >> dbt_test >> dbt_docs >> quality_gate

# %%
