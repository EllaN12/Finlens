"""
config.py — Central configuration for FinLens
==============================================
Single source of truth for every environment variable and shared domain constant used across:
  - ingest/ingest_latest.py
  - app/finlens_app.py
  - scenarios/ (base, runner, P1, P2, P3, P4, P5)
  - dbt profiles.yml (values printed by print_dbt_profile())
  - Airflow DAGs

Usage
-----
    from config import cfg

    client = bigquery.Client(project=cfg.project)
    key    = cfg.fred_api_key

Loading order (highest priority wins)
--------------------------------------
    1. Real environment variables  (set in shell / CI / Cloud Run)
    2. .env file in the project root  (local development)
    3. Built-in defaults

The .env file is NEVER imported automatically by Python — this module
calls load_dotenv() explicitly so all other files just do `from config import cfg`.
"""
#%%

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from dataclasses import dataclass, field

# ── Locate and load .env ──────────────────────────────────────────────────────
# Walk up from this file's directory to find the project root .env
def _find_env_file() -> Path | None:
    here = Path(__file__).resolve().parent
    for directory in [here, *here.parents]:
        candidate = directory / ".env"
        if candidate.exists():
            return candidate
    return None

def _sanitize_google_credentials() -> None:
    """
    this function is used to sanitize the google credentials file.
    An empty or corrupt key file makes google.auth fail before it can fall back to
    Application Default Credentials (e.g. `gcloud auth application-default login`).
    """
    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if not path:
        return
    cred_file = Path(path)
    invalid = (
        not cred_file.is_file()
        or cred_file.stat().st_size == 0
    )
    if not invalid:
        try:
            json.loads(cred_file.read_text())
        except (json.JSONDecodeError, OSError):
            invalid = True
    if invalid:
        os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)


try:
    from dotenv import load_dotenv
    _env_file = _find_env_file()
    if _env_file:
        load_dotenv(_env_file, override=False)   # env vars already set take priority
        _loaded_from = str(_env_file)
    else:
        _loaded_from = "none (no .env file found)"
except ImportError:
    _loaded_from = "none (python-dotenv not installed)"

_sanitize_google_credentials()


# ── Config dataclass ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class FinLensConfig:
    """Immutable config object — import `cfg` rather than constructing directly."""

    # Google Cloud
    project    : str  = field(default_factory=lambda: os.environ.get("GCP_PROJECT", ""))
    region     : str  = field(default_factory=lambda: os.environ.get("GCP_REGION", "US"))
    credentials: str  = field(default_factory=lambda: os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", ""))

    # FRED API
    fred_api_key: str = field(default_factory=lambda: os.environ.get("FRED_API_KEY", ""))

    # Local paths
    hmda_data_dir: Path = field(default_factory=lambda:
        Path(os.environ.get("HMDA_DATA_DIR", "./data/hmda"))
    )

    # BigQuery dataset names (override via BQ_DATASET_* if needed)
    bq_dataset_raw_hmda      : str = field(default_factory=lambda: os.environ.get("BQ_DATASET_RAW_HMDA", "raw_hmda"))
    bq_dataset_raw_fred      : str = field(default_factory=lambda: os.environ.get("BQ_DATASET_RAW_FRED", "raw_fred"))
    bq_dataset_staging       : str = field(default_factory=lambda: os.environ.get("BQ_DATASET_STAGING", "staging"))
    bq_dataset_intermediate  : str = field(default_factory=lambda: os.environ.get("BQ_DATASET_INTERMEDIATE", "intermediate"))
    bq_dataset_marts         : str = field(default_factory=lambda: os.environ.get("BQ_DATASET_MARTS", "marts"))

    # Streamlit / local dev: 1 = synthetic data, 0 = query BigQuery marts
    finlens_demo: bool = field(
        default_factory=lambda: os.environ.get("FINLENS_DEMO", "0").strip().lower() in ("1", "true", "yes")
    )

    # ── Domain constants ──────────────────────────────────────────────────────

    # States shown in the Streamlit app (6 states)
    states: list = field(default_factory=lambda: ["CA", "TX", "FL", "OH", "NY", "IL"])

    # States pulled during ingestion — includes WA for fuller FRED coverage
    ingest_states: list = field(default_factory=lambda: ["CA", "TX", "FL", "OH", "NY", "IL", "WA"])

    # Default donor pool for DiD / synthetic control scenarios
    default_control_states: list = field(default_factory=lambda: ["TX", "FL", "OH", "NY", "IL"])

    # Year range and categorical filters used by the app
    hmda_min_year : int  = 2018
    app_years     : list = field(default_factory=lambda: list(range(2018, 2024)))
    loan_types    : list = field(default_factory=lambda: ["conventional", "fha", "va", "usda"])
    income_tiers  : list = field(default_factory=lambda: [
        "low_income", "moderate_income", "middle_income", "high_income"
    ])
    covariates    : list = field(default_factory=lambda: [
        "unemployment_rate", "hpi", "mortgage_rate_30yr"
    ])

    # CFPB bulk-download URL template (one zip per year)
    cfpb_url_template: str = (
        "https://ffiec.cfpb.gov/v2/data-browser-api/view/csv"
        "?states={states}&years={year}&actions_taken=1,2,3,4,5,6,7,8"
    )

    # ── Derived helpers ───────────────────────────────────────────────────────

    def table(self, dataset: str, table: str) -> str:
        """Return a fully-qualified BigQuery table reference."""
        return f"{self.project}.{dataset}.{table}"

    def mart(self, table: str) -> str:
        """Shorthand for marts dataset tables."""
        return self.table(self.bq_dataset_marts, table)

    def validate(self, require_fred: bool = True) -> None:
        """
        Raise EnvironmentError if required variables are missing.
        Call this at the top of scripts that need live credentials.
        """
        missing = []
        if not self.project:
            missing.append("GCP_PROJECT")
        if require_fred and not self.fred_api_key:
            missing.append("FRED_API_KEY")
        if missing:
            raise EnvironmentError(
                f"Missing required environment variables: {missing}\n"
                f"Copy .env.example to .env and fill in the values."
            )

    def print_dbt_profile(self) -> None:
        """Print a ready-to-paste dbt profiles.yml snippet."""
        print(f"""
# ~/.dbt/profiles.yml
finlens:
  target: prod
  outputs:
    prod:
      type: bigquery
      method: service-account
      project: {self.project}
      dataset: {self.bq_dataset_staging}
      location: {self.region}
      keyfile: {self.credentials or '/path/to/key.json'}
      threads: 4
      timeout_seconds: 300
""")

    def __repr__(self) -> str:
        key_preview = (self.fred_api_key[:6] + "…") if self.fred_api_key else "NOT SET"
        cred_set    = bool(self.credentials)
        return (
            f"FinLensConfig("
            f"project={self.project!r}, "
            f"region={self.region!r}, "
            f"credentials_set={cred_set}, "
            f"fred_api_key={key_preview!r}"
            f")"
        )


# ── Module-level singleton ────────────────────────────────────────────────────

cfg = FinLensConfig()


# ── CLI helper ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"\n.env loaded from : {_loaded_from}")
    print(f"Config           : {cfg}\n")

    if "--dbt" in sys.argv:
        cfg.print_dbt_profile()

    if "--validate" in sys.argv:
        try:
            cfg.validate()
            print("✓ All required variables are set.")
        except EnvironmentError as e:
            print(f"✗ {e}")
            sys.exit(1)

# %%
