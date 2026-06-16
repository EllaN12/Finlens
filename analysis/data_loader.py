"""Load mart tables from BigQuery using central config (.env → cfg)."""
#%%
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
from google.cloud import bigquery

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from config import cfg


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


def _query_mart(table: str) -> pd.DataFrame:
    client = bigquery.Client(project=cfg.project or None)
    fq = f"`{cfg.project}.{cfg.bq_dataset_marts}.{table}`"
    df = client.query(f"SELECT * FROM {fq}").to_dataframe(
        create_bqstorage_client=False
    )
    df.columns = df.columns.str.lower()
    return _coerce_numpy_dtypes(df)


def load_regulatory_cohort() -> pd.DataFrame:
    return _query_mart("mart_regulatory_cohort")


def load_funnel() -> pd.DataFrame:
    return _query_mart("mart_lending_funnel")


def load_kpi_dashboard() -> pd.DataFrame:
    return _query_mart("mart_kpi_dashboard")

# %%
