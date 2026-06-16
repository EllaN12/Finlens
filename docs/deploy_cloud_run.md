# FinLens — Cloud Run Deployment Runbook
## Option A: Cloud Scheduler + Cloud Run Jobs (Scale-to-Zero)

**Architecture:** Cloud Scheduler triggers a Cloud Run Job once per month.
The Job runs `ingest → dbt run → dbt test` in a single container.
The Streamlit app runs as a Cloud Run Service that scales to zero between visits.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│  PIPELINE (runs 1st of every month, 6:00 AM ET)             │
│                                                              │
│  Cloud Scheduler ──► Cloud Run Job: finlens-pipeline        │
│  cron: 0 11 1 * *       [1] python ingest/ingest_latest.py  │
│  (UTC = 11AM = 6AM ET)  [2] dbt run --select marts          │
│                         [3] dbt test --select marts          │
│                              │                               │
│                              ▼                               │
│                         BigQuery                             │
│                         raw_hmda / raw_fred   (raw)          │
│                         finlens_dev_marts     (marts)        │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  APP (always available, scales to zero between visits)       │
│                                                              │
│  Cloud Run Service: finlens-app                              │
│    streamlit run app/finlens_app.py                          │
│    reads finlens_dev_marts on demand (cached 1hr in app)     │
│    ~10-15 sec cold start on first visit after idle period    │
└─────────────────────────────────────────────────────────────┘
```

---

## Prerequisites

| Tool | Version | Install |
|---|---|---|
| gcloud CLI | latest | `brew install google-cloud-sdk` |
| Docker Desktop | latest | https://docs.docker.com/desktop/mac/ |
| Python | 3.11+ | already in `.venv` |
| make | built-in | macOS built-in |

> **Apple Silicon (M1/M2/M3/M4):** Docker builds target `linux/amd64` automatically
> via `--platform linux/amd64` in the Makefile. Build times are slightly longer due
> to cross-compilation but images are fully compatible with Cloud Run.

Authenticate:
```bash
gcloud auth login
gcloud auth application-default login
gcloud config set project YOUR_GCP_PROJECT_ID
```

Make sure Docker Desktop is running before any `make build-*` or `make deploy-*` command:
```bash
open -a Docker   # then wait ~30 seconds for the whale icon to stop animating
docker info      # should print system info with no errors
```

---

## Environment Variables

All values live in `.env` at the project root. Copy from the template:

```bash
cp .env.example .env   # edit with your values
```

Required variables:

| Variable | Description | Value used |
|---|---|---|
| `GCP_PROJECT` | GCP project ID | `project-58b73547-8fb7-4cff-b60` |
| `GCP_REGION` | Deployment region | `us-central1` |
| `BQ_DATASET_MARTS` | BigQuery marts dataset | `finlens_dev_marts` |
| `BQ_DATASET_RAW_HMDA` | BigQuery raw HMDA dataset | `raw_hmda` |
| `BQ_DATASET_RAW_FRED` | BigQuery raw FRED dataset | `raw_fred` |
| `FRED_API_KEY` | FRED API key (free at fred.stlouisfed.org) | `abcdef1234...` |

> **Note on `BQ_DATASET_MARTS`:** dbt writes marts to `finlens_dev_marts` when using
> the `dev` target (default). The app and Cloud Run service must both point to the
> same dataset. Current value: `finlens_dev_marts`.

Verify everything loaded:
```bash
make env-check
```

---

## Phase 1 — One-Time GCP Setup

> Run once per GCP project. Safe to re-run (idempotent).

```bash
make setup-gcp
```

This command:
1. Enables required GCP APIs (Cloud Run, Cloud Scheduler, Cloud Build, Artifact Registry, BigQuery, Secret Manager)
2. Creates Artifact Registry repository `finlens` in your region
3. Creates service account `finlens-sa` with least-privilege IAM roles
4. Configures Docker to authenticate with Artifact Registry

**IAM roles granted to `finlens-sa`:**

| Role | Purpose |
|---|---|
| `roles/bigquery.dataEditor` | Read/write BigQuery tables |
| `roles/bigquery.jobUser` | Execute BigQuery queries and jobs |
| `roles/secretmanager.secretAccessor` | Read secrets at runtime |
| `roles/run.invoker` | Allow Cloud Scheduler to trigger Cloud Run |

---

## Phase 2 — BigQuery Dataset Setup

Create the BigQuery datasets (one-time):

```bash
bq mk --location=US --dataset ${GCP_PROJECT}:raw_hmda
bq mk --location=US --dataset ${GCP_PROJECT}:raw_fred
bq mk --location=US --dataset ${GCP_PROJECT}:finlens_dev_marts
bq mk --location=US --dataset ${GCP_PROJECT}:finlens_dev_staging
bq mk --location=US --dataset ${GCP_PROJECT}:finlens_dev_intermediate
```

Or via Console: BigQuery → Create Dataset for each name above.

Verify datasets exist:
```bash
bq ls --project_id=${GCP_PROJECT}
```

---

## Phase 3 — Build dbt Marts Locally (Before First Deploy)

dbt must run locally first to populate BigQuery before the app can serve data.
The Makefile exports `.env` vars automatically — no manual `export` needed.

```bash
make dbt-all
```

Expected output — all 9 models pass, 6 tests pass:
```
... 7 of 9 OK created sql table model finlens_dev_marts.mart_regulatory_cohort
... 6 of 9 OK created sql table model finlens_dev_marts.mart_lending_funnel
... Done. PASS=9 WARN=0 ERROR=0 SKIP=0 NO-OP=0 TOTAL=9
... Done. PASS=6 WARN=0 ERROR=0 SKIP=0 NO-OP=0 TOTAL=6
```

> **Important:** If you run dbt directly from the shell (outside `make`), you must
> export env vars manually first — dbt does not auto-load `.env`:
> ```bash
> export $(grep -v '^#' .env | xargs) && cd finlens_dbt && ../.venv/bin/dbt run --profiles-dir . --target dev
> ```

Verify tables landed in the right dataset:
```bash
bq ls --project_id=${GCP_PROJECT} finlens_dev_marts
# Expected: mart_kpi_dashboard, mart_lending_funnel, mart_regulatory_cohort, mart_unit_economics
```

---

## Phase 4 — Build & Deploy

### 4a. Full deploy (first time or after code changes)

```bash
make deploy-all
```

This runs in order:
1. `docker build --platform linux/amd64` → `Dockerfile.pipeline` → `finlens-pipeline:latest`
2. `docker build --platform linux/amd64` → `Dockerfile` → `finlens-app:latest`
3. `docker push` both images to Artifact Registry
4. `gcloud run jobs create/update finlens-pipeline`
5. `gcloud run deploy finlens-app` (prints the live URL at the end)

### 4b. Deploy only the app (after UI changes)

```bash
make deploy-app
```

### 4c. Deploy only the pipeline (after ingest/dbt changes)

```bash
make deploy-pipeline
```

---

## Phase 5 — Create Cloud Scheduler Trigger

One-time setup to schedule the monthly pipeline run:

```bash
gcloud scheduler jobs create http finlens-monthly-pipeline \
  --location ${GCP_REGION} \
  --schedule "0 11 1 * *" \
  --uri "https://${GCP_REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${GCP_PROJECT}/jobs/finlens-pipeline:run" \
  --http-method POST \
  --oauth-service-account-email finlens-sa@${GCP_PROJECT}.iam.gserviceaccount.com \
  --time-zone "UTC" \
  --description "FinLens monthly HMDA ingest + dbt pipeline"
```

**Schedule:** `0 11 1 * *` = 11:00 AM UTC = 6:00 AM ET on the 1st of every month.

Verify it was created:
```bash
gcloud scheduler jobs list --location ${GCP_REGION}
```

---

## Phase 6 — Verify Deployment

### Test the pipeline manually (before waiting for the monthly cron)

```bash
make run-pipeline
```

Expected output:
```
=== [1/3] Ingesting HMDA + FRED data ===
... (ingestion logs) ...
=== [2/3] Running dbt models ===
... (dbt model logs) ...
=== [3/3] Running dbt tests ===
... (dbt test logs) ...
=== Pipeline complete ===
```

### Check the app is live

```bash
gcloud run services describe finlens-app \
  --region ${GCP_REGION} \
  --format 'value(status.url)'
```

Open the URL in a browser. Expect ~10-15 second cold start on first load after an idle period.

### View pipeline logs

```bash
make logs-pipeline
```

### View app logs

```bash
make logs-app
```

---

## Phase 7 — CI/CD (Optional: auto-deploy on git push)

Connect Cloud Build to your GitHub repository:

1. Go to **Cloud Build → Triggers → Connect Repository**
2. Select GitHub and authorize
3. Choose your repo and branch (`main`)
4. Select **Existing Cloud Build configuration** → `cloudbuild.yaml`
5. Add substitution variables:
   - `_REGION` → `us-central1`
   - `_REPO` → `finlens`

After setup, every push to `main` automatically:
- Builds both Docker images tagged with commit SHA
- Pushes to Artifact Registry
- Updates Cloud Run Job + Service

---

## Cost Estimate (Scale-to-Zero)

| Service | Monthly Usage | Cost |
|---|---|---|
| Cloud Scheduler | 1 job | **Free** (3 jobs included) |
| Cloud Run Job | 1 run × 30 min × 2 vCPU | **Free** (within 180K vCPU-sec free tier) |
| Cloud Run Service | scale-to-zero, low traffic | **Free** (within 2M req + 180K vCPU-sec free tier) |
| BigQuery | ~8 GB storage, ~50 queries | **Free** (10 GB storage + 1 TB queries/mo free) |
| Artifact Registry | ~500 MB (2 images) | **~$0.05/mo** |
| Secret Manager | 3 secrets | **Free** (6 secrets included) |
| **Total** | | **~$0.05/mo** |

> Note: If HMDA dataset grows past 10 GB BigQuery storage, add ~$0.02/GB/month.

---

## Retry & Alerting Policy

The Cloud Run Job is configured with `--max-retries 2`:
- On task failure, GCP retries up to 2 times before marking the execution failed
- Monitor job status in Cloud Console → Cloud Run → Jobs → finlens-pipeline

### Set up email alerts on pipeline failure

```bash
# Create alerting policy via Cloud Monitoring (Console recommended)
# Cloud Monitoring → Alerting → Create Policy
# Condition: Cloud Run Job → Execution failed count > 0
# Notification: Email channel
```

---

## Troubleshooting

| Problem | Cause | Fix |
|---|---|---|
| `Cannot connect to Docker daemon` | Docker Desktop not running | `open -a Docker`, wait 30s, retry |
| `must support amd64/linux` | ARM image built on Apple Silicon | Makefile already sets `--platform linux/amd64`; rebuild with `make build-app` |
| `dbt: env_var required: GCP_PROJECT` | Running dbt outside `make` | Use `make dbt-all` or `export $(grep -v '^#' .env \| xargs)` first |
| `BigQuery table not found` | `BQ_DATASET_MARTS` mismatch | Run `bq ls --project_id=$GCP_PROJECT` to find actual dataset; update `.env` and `make deploy-app` |
| `finlens_prod` empty, tables in `finlens_dev_marts` | dbt `dev` target writes to `finlens_dev_*` | Set `BQ_DATASET_MARTS=finlens_dev_marts` in `.env` and redeploy |
| `Permission denied on BigQuery` | SA missing IAM role | Re-run `make setup-gcp` |
| `image not found` in Cloud Run | Image not pushed | Run `make push-pipeline` or `make push-app` |
| App shows blank page | Cold start timeout | Wait 15 seconds and refresh |
| `FRED API key invalid` | Wrong key or not set | Check `.env` → `FRED_API_KEY` |
| Cloud Scheduler trigger 403 | SA missing `run.invoker` role | Re-run `make setup-gcp` |
| dbt tests fail after ingest | Data quality issue in HMDA | Check `make logs-pipeline`, review dbt test output |

---

## File Reference

| File | Purpose |
|---|---|
| `Dockerfile.pipeline` | Container for Cloud Run Job (ingest + dbt) |
| `Dockerfile` | Container for Cloud Run Service (Streamlit app) |
| `.dockerignore` | Excludes secrets, cache, data from build context |
| `cloudbuild.yaml` | CI/CD: build + push + deploy on git push to main |
| `Makefile` | All local dev + deploy commands |
| `.env.example` | Template for all required env vars |
| `finlens_dbt/profiles.yml` | dbt BigQuery connection (dev=oauth writes to `finlens_dev_*`) |
| `docs/deploy_cloud_run.md` | This document |

---

## Quick Reference

```bash
# First time setup
make setup-gcp          # enable APIs, create SA, IAM roles
make dbt-all            # build marts in BigQuery (required before first app deploy)
make deploy-all         # build + push + deploy everything

# Day-to-day ops
make run-pipeline       # manually trigger ingest + dbt now
make logs-pipeline      # view pipeline logs
make logs-app           # view app logs

# After code changes
make deploy-app         # redeploy Streamlit app
make deploy-pipeline    # redeploy ingest + dbt job

# Local development
make app                # run Streamlit locally on :8501
make dbt-all            # run dbt locally
make env-check          # verify .env loaded correctly
```
