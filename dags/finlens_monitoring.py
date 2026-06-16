#%%

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
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
    if len(rates) < 2:
        print("Not enough years of data to compute drift — skipping.")
        return
    hist, latest = rates[:-1], rates[-1]
    mu = statistics.mean(hist)
    sigma = statistics.stdev(hist) if len(hist) >= 2 else 0
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
