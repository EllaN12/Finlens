"""
ingest/ingest_latest.py — FinLens full data ingestion
======================================================
Automatically detects ALL available years from HMDA (CFPB) and FRED,
then loads every one of them into BigQuery.  Re-running is safe — each
table is WRITE_TRUNCATE so data is never doubled.

Usage
-----
    # Preview what would run — no downloads, no BQ writes
    python ingest/ingest_latest.py --dry-run

    # Load everything
    python ingest/ingest_latest.py

    # One source only
    python ingest/ingest_latest.py --source hmda
    python ingest/ingest_latest.py --source fred

Environment variables
---------------------
    GCP_PROJECT                    your GCP project ID
    FRED_API_KEY                   free key → https://fred.stlouisfed.org/docs/api/api_key.html
    GOOGLE_APPLICATION_CREDENTIALS path to service-account JSON (or use ADC)
    HMDA_DATA_DIR                  local cache dir for HMDA CSVs  (default: ./data/hmda)
    GCP_REGION                     BigQuery dataset location       (default: US)
"""

from __future__ import annotations

import argparse
import io
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
import pandas as pd

# ── Central config (loads .env automatically) ─────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import cfg

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level  = logging.INFO,
    format = "%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt= "%H:%M:%S",
)
log = logging.getLogger("finlens.ingest")

# ─────────────────────────────────────────────────────────────────────────────
# Convenience aliases from central config
# ─────────────────────────────────────────────────────────────────────────────
PROJECT  = cfg.project
FRED_KEY = cfg.fred_api_key
REGION   = cfg.region
HMDA_DIR = cfg.hmda_data_dir

STATES   = cfg.ingest_states

HMDA_MIN_YEAR  = cfg.hmda_min_year
CURRENT_YEAR   = datetime.now().year

HMDA_TABLE = cfg.table(cfg.bq_dataset_raw_hmda, "hmda_lar_raw")
FRED_TABLE = cfg.table(cfg.bq_dataset_raw_fred, "fred_macro_raw")

# CFPB Data Browser v2 API — requires year + at least one filter param
CFPB_API = "https://ffiec.cfpb.gov/v2/data-browser-api/view/csv"
# All action_taken codes so we get originated + denied + etc.
HMDA_ACTIONS = "1,2,3,4,5,6,7,8"

# Columns aligned with raw_hmda.hmda_lar_raw (run.py / dbt sources)
HMDA_DESIRED_COLS = [
    "activity_year", "state_code", "county_code",
    "action_taken", "loan_type", "loan_purpose",
    "loan_amount", "property_value", "interest_rate", "rate_spread",
    "combined_loan_to_value_ratio", "income", "debt_to_income_ratio",
    "applicant_credit_score_type", "denial_reason_1", "denial_reason_2",
    "derived_loan_product_type", "derived_dwelling_category",
    "derived_race", "derived_sex", "applicant_age",
    "lien_status", "occupancy_type", "loan_term", "total_units",
]
# CFPB CSV column names that differ from our BQ schema
HMDA_COLUMN_ALIASES = {
    "loan_to_value_ratio": "combined_loan_to_value_ratio",
    "denial_reason-1":   "denial_reason_1",
    "denial_reason-2":   "denial_reason_2",
}

# FRED series: metric name → function(state) → series_id
FRED_SERIES = {
    "unemployment_rate":  lambda s: f"{s}UR",        # e.g. CAUR
    "hpi":                lambda s: f"{s}STHPI",     # e.g. CASTHPI
    "mortgage_rate_30yr": lambda _: "MORTGAGE30US",  # national, same for all states
}


# ─────────────────────────────────────────────────────────────────────────────
# Detect available years
# ─────────────────────────────────────────────────────────────────────────────

def _hmda_year_available(year: int) -> bool:
    """Return True if CFPB serves loan-level data for this filing year."""
    try:
        r = requests.get(
            "https://ffiec.cfpb.gov/v2/data-browser-api/view/aggregations",
            params={"years": str(year), "states": "CA", "actions_taken": "5"},
            timeout=10,
        )
        return r.status_code == 200
    except Exception:
        return False


def hmda_available_years() -> list[int]:
    """
    Probe the CFPB Data Browser API for published HMDA filing years.

    The old /view/schema endpoint was removed; we issue a lightweight
    aggregations request per candidate year instead.
    """
    candidates = list(range(HMDA_MIN_YEAR, CURRENT_YEAR + 1))
    years = [y for y in candidates if _hmda_year_available(y)]
    if years:
        log.info(f"CFPB published years: {years}")
        return years

    fallback = list(range(HMDA_MIN_YEAR, CURRENT_YEAR))
    log.warning(
        "Could not probe CFPB for published years — "
        f"using fallback range: {fallback}"
    )
    return fallback


def _hmda_api_url(year: int, states: list[str] | None = None) -> str:
    """Build a CFPB Data Browser CSV download URL for the given year/states."""
    state_list = states or STATES
    params = {
        "years":         str(year),
        "states":        ",".join(state_list),
        "actions_taken": HMDA_ACTIONS,
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{CFPB_API}?{query}"


def _resolve_hmda_columns(header: list[str]) -> tuple[list[str], dict[str, str]]:
    """Map CFPB CSV headers to our BQ column names."""
    available = set(header)
    keep: list[str] = []
    renames: dict[str, str] = {}
    for col in HMDA_DESIRED_COLS:
        if col in available:
            keep.append(col)
            continue
        for src, dst in HMDA_COLUMN_ALIASES.items():
            if src in available and dst == col:
                keep.append(src)
                renames[src] = dst
                break
    return keep, renames


def _valid_csv(path: Path) -> bool:
    """Reject empty files and HTML error pages saved with a .csv/.zip name."""
    if not path.is_file() or path.stat().st_size < 1024:
        return False
    with open(path, "rb") as f:
        head = f.read(256)
    return not head.lstrip().startswith(b"<!") and not head.lstrip().startswith(b"<html")


def fred_available_years() -> list[int]:
    """
    Ask FRED for the most recent annual observation, then return
    every year from HMDA_MIN_YEAR up to that year.
    Falls back to HMDA_MIN_YEAR … current_year-1.
    """
    if not FRED_KEY:
        fallback = list(range(HMDA_MIN_YEAR, CURRENT_YEAR))
        log.warning(f"FRED_API_KEY not set — using fallback years: {fallback}")
        return fallback
    try:
        r = requests.get(
            "https://api.stlouisfed.org/fred/series/observations",
            params={
                "series_id":  "MORTGAGE30US",
                "api_key":    FRED_KEY,
                "file_type":  "json",
                "sort_order": "desc",
                "limit":      1,
                "frequency":  "a",
            },
            timeout=10,
        )
        r.raise_for_status()
        obs       = r.json()["observations"]
        last_year = int(obs[0]["date"][:4]) if obs else CURRENT_YEAR - 1
        years     = list(range(HMDA_MIN_YEAR, last_year + 1))
        log.info(f"FRED latest year: {last_year} → loading {years}")
        return years
    except Exception as e:
        fallback = list(range(HMDA_MIN_YEAR, CURRENT_YEAR))
        log.warning(f"FRED year check failed ({e}) — using fallback: {fallback}")
        return fallback


# ─────────────────────────────────────────────────────────────────────────────
# BigQuery client
# ─────────────────────────────────────────────────────────────────────────────

def _bq():
    from google.cloud import bigquery
    return bigquery.Client(project=PROJECT)


# ─────────────────────────────────────────────────────────────────────────────
# HMDA — download + load
# ─────────────────────────────────────────────────────────────────────────────

def _cached_csv(year: int) -> Optional[Path]:
    cache = HMDA_DIR / str(year)
    if not cache.exists():
        return None
    for csv in sorted(cache.glob("*.csv")):
        if _valid_csv(csv):
            log.info(f"  Using cached CSV: {csv.name}")
            return csv
    return None


def _download_hmda(year: int) -> Path:
    """Stream-download CFPB LAR CSV for cfg.ingest_states; return path to the file."""
    url      = _hmda_api_url(year)
    dest_dir = HMDA_DIR / str(year)
    dest_dir.mkdir(parents=True, exist_ok=True)
    csv_path = dest_dir / f"hmda_lar_{year}.csv"

    log.info(f"  Downloading {url} …")
    with requests.get(url, stream=True, timeout=1800) as r:
        r.raise_for_status()
        ctype = (r.headers.get("content-type") or "").lower()
        if "html" in ctype:
            raise ValueError(
                f"CFPB returned HTML instead of CSV for {year} — check the API URL/filters."
            )
        total = int(r.headers.get("content-length", 0))
        done  = 0
        with open(csv_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
                done += len(chunk)
                if total:
                    print(f"\r    {done/total*100:5.1f}%  ({done>>20} MB)",
                          end="", flush=True)
        print()

    if not _valid_csv(csv_path):
        csv_path.unlink(missing_ok=True)
        raise ValueError(f"Download for {year} is not a valid CSV (empty or HTML).")
    return csv_path


def load_hmda_year(year: int, dry_run: bool = False, *, truncate_first: bool = False) -> None:
    if dry_run:
        src = _cached_csv(year) or _hmda_api_url(year)
        log.info(f"  [DRY-RUN] {src}  →  {HMDA_TABLE}  "
                 f"({'TRUNCATE' if truncate_first else 'APPEND'})")
        return

    from google.cloud import bigquery

    csv_path  = _cached_csv(year) or _download_hmda(year)
    client    = _bq()

    header          = pd.read_csv(csv_path, nrows=0).columns.tolist()
    keep, renames   = _resolve_hmda_columns(header)
    # Always set activity_year from the function argument; drop it from usecols
    # so the CSV value (which may be aliased or inconsistent) doesn't shadow it.
    keep = [c for c in keep if c != "activity_year"]
    if not keep:
        raise ValueError(f"No matching HMDA columns found in {csv_path.name}")

    first_chunk = True
    log.info(f"  Streaming {csv_path.name} → {HMDA_TABLE} …")
    for i, chunk in enumerate(
        pd.read_csv(csv_path, usecols=keep, dtype=str,
                    chunksize=500_000, low_memory=False)
    ):
        chunk = chunk.rename(columns=renames)
        chunk["activity_year"] = year
        chunk["_loaded_at"]    = datetime.now(timezone.utc)
        truncate = truncate_first and first_chunk
        job = client.load_table_from_file(
            file_obj    = io.BytesIO(chunk.to_parquet(index=False)),
            destination = HMDA_TABLE,
            job_config  = bigquery.LoadJobConfig(
                write_disposition = (
                    bigquery.WriteDisposition.WRITE_TRUNCATE if truncate
                    else bigquery.WriteDisposition.WRITE_APPEND
                ),
                autodetect    = True,
                source_format = bigquery.SourceFormat.PARQUET,
            ),
        )
        job.result()
        first_chunk = False
        log.info(f"    chunk {i+1}: {len(chunk):,} rows")

    log.info(f"  ✓ HMDA {year} → {HMDA_TABLE}")


# ─────────────────────────────────────────────────────────────────────────────
# FRED — fetch + load
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_series(series_id: str, start: int, end: int) -> pd.DataFrame:
    r = requests.get(
        "https://api.stlouisfed.org/fred/series/observations",
        params={
            "series_id":         series_id,
            "api_key":           FRED_KEY,
            "file_type":         "json",
            "observation_start": f"{start}-01-01",
            "observation_end":   f"{end}-12-31",
        },
        timeout=15,
    )
    r.raise_for_status()
    obs = r.json().get("observations", [])
    if not obs:
        raise ValueError(f"FRED returned no observations for series {series_id} ({start}–{end})")
    df  = pd.DataFrame(obs)[["date", "value"]]
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["period_date"] = pd.to_datetime(df["date"]).dt.date
    return df[["period_date", "value"]].dropna(subset=["value"])


def load_fred(years: list[int], dry_run: bool = False) -> None:
    if not years:
        return
    if not FRED_KEY:
        log.error("FRED_API_KEY not set — skipping FRED.")
        return

    start, end = min(years), max(years)
    log.info(f"Fetching FRED {start}–{end} for {len(STATES)} states …")

    if dry_run:
        series_count = len(STATES) * 2 + 1   # 2 state series + 1 national
        log.info(f"  [DRY-RUN] Would fetch {series_count} FRED series "
                 f"({start}–{end}) → {FRED_TABLE}  (WRITE_TRUNCATE)")
        return

    rows = []

    for metric, series_fn in FRED_SERIES.items():
        if metric == "mortgage_rate_30yr":
            try:
                df = _fetch_series("MORTGAGE30US", start, end)
                for state in STATES:
                    d = df.copy()
                    d["series_id"]   = "MORTGAGE30US"
                    d["state_code"]  = state
                    d["metric_name"] = metric
                    rows.append(d)
                log.info(f"  ✓ MORTGAGE30US ({len(df)} obs → {len(STATES)} states)")
            except Exception as e:
                log.warning(f"  ✗ MORTGAGE30US: {e}")
        else:
            for state in STATES:
                sid = series_fn(state)
                try:
                    df = _fetch_series(sid, start, end)
                    df["series_id"]   = sid
                    df["state_code"]  = state
                    df["metric_name"] = metric
                    rows.append(df)
                    log.info(f"  ✓ {sid:<12} ({len(df)} obs)")
                except Exception as e:
                    log.warning(f"  ✗ {sid}: {e}")
                time.sleep(0.1)

    if not rows:
        log.error("No FRED data fetched — nothing to load.")
        return

    out = pd.concat(rows, ignore_index=True)
    out["_loaded_at"] = datetime.now(timezone.utc)

    from google.cloud import bigquery
    client = _bq()
    job = client.load_table_from_dataframe(
        out,
        FRED_TABLE,
        job_config=bigquery.LoadJobConfig(
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        ),
    )
    job.result()
    log.info(f"  ✓ FRED → {FRED_TABLE}  ({len(out):,} rows, "
             f"{out['metric_name'].nunique()} metrics × "
             f"{out['state_code'].nunique()} states)")


# ─────────────────────────────────────────────────────────────────────────────
# Orchestration
# ─────────────────────────────────────────────────────────────────────────────

def run_hmda(dry_run: bool) -> None:
    log.info("=" * 60)
    log.info("HMDA — all available years")
    log.info("=" * 60)
    years = hmda_available_years()
    log.info(f"Years to load: {years}")
    for i, year in enumerate(years):
        log.info(f"\n── HMDA {year} ──")
        try:
            load_hmda_year(year, dry_run=dry_run, truncate_first=(i == 0))
        except Exception as e:
            log.error(f"  FAILED ({year}): {e}")


def run_fred(dry_run: bool) -> None:
    log.info("=" * 60)
    log.info("FRED — all available years")
    log.info("=" * 60)
    years = fred_available_years()
    log.info(f"Years to load: {years}")
    load_fred(years, dry_run=dry_run)


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="FinLens — load ALL available HMDA + FRED years into BigQuery"
    )
    parser.add_argument(
        "--source", choices=["hmda", "fred", "both"], default="both",
        help="Which source to load (default: both)",
    )
    parser.add_argument(
        "--year", type=int, default=None,
        help="Single HMDA filing year (requires --source hmda)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be loaded without downloading or writing to BQ",
    )
    args = parser.parse_args()

    if args.year is not None and args.source != "hmda":
        parser.error("--year is only valid with --source hmda")

    if not args.dry_run:
        try:
            cfg.validate(require_fred=(args.source in ("fred", "both")))
        except EnvironmentError as e:
            log.error(str(e))
            sys.exit(1)

    HMDA_DIR.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    if args.source in ("hmda", "both"):
        if args.year is not None:
            log.info(f"\n── HMDA {args.year} (single year) ──")
            load_hmda_year(args.year, dry_run=args.dry_run, truncate_first=False)
        else:
            run_hmda(args.dry_run)
    if args.source in ("fred", "both"):
        run_fred(args.dry_run)
    log.info(f"\nDone in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
