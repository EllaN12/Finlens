# FinLens — Deployment Protocol
## Google Cloud Platform + Streamlit

---

## Architecture Overview

```
CFPB HMDA API ──┐
                ├──► Cloud Composer (Airflow) ──► BigQuery Raw ──► dbt ──► BigQuery Mart ──► Cloud Run (Streamlit)
FRED Macro API ─┘
```

| Layer | GCP Service | Purpose |
|-------|-------------|---------|
| Orchestration | Cloud Composer (Airflow) | Schedule ingestion DAGs and dbt runs |
| Storage | BigQuery | Raw tables, staging models, analytics marts |
| Transformation | dbt Core on Composer | Staging → Mart transformations + data tests |
| Secrets | Secret Manager | API keys, service account credentials |
| Container Registry | Artifact Registry | Docker images for the Streamlit app |
| App Hosting | Cloud Run | Serverless, auto-scaling Streamlit container |
| CI/CD | Cloud Build | Trigger on GitHub push → build → deploy |

---

## Phase 1 — GCP Project & IAM Setup

```bash
# 1. Create project
gcloud projects create finlens-prod --name="FinLens"
gcloud config set project finlens-prod

# 2. Link billing account
gcloud billing projects link finlens-prod --billing-account=BILLING_ACCOUNT_ID

# 3. Enable required APIs
gcloud services enable \
  bigquery.googleapis.com \
  run.googleapis.com \
  composer.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  cloudbuild.googleapis.com \
  cloudscheduler.googleapis.com

# 4. Create service account
gcloud iam service-accounts create finlens-sa \
  --display-name="FinLens Service Account"

# 5. Grant roles
SA=finlens-sa@finlens-prod.iam.gserviceaccount.com
gcloud projects add-iam-policy-binding finlens-prod --member="serviceAccount:$SA" --role="roles/bigquery.admin"
gcloud projects add-iam-policy-binding finlens-prod --member="serviceAccount:$SA" --role="roles/composer.worker"
gcloud projects add-iam-policy-binding finlens-prod --member="serviceAccount:$SA" --role="roles/run.admin"
gcloud projects add-iam-policy-binding finlens-prod --member="serviceAccount:$SA" --role="roles/artifactregistry.writer"
gcloud projects add-iam-policy-binding finlens-prod --member="serviceAccount:$SA" --role="roles/secretmanager.secretAccessor"

# 6. Create and download key
gcloud iam service-accounts keys create ~/finlens-sa-key.json --iam-account=$SA
```

---

## Phase 2 — BigQuery Datasets

```bash
# Create datasets (US multi-region for HMDA compliance)
bq mk --location=US --dataset finlens-prod:finlens_raw
bq mk --location=US --dataset finlens-prod:finlens_staging
bq mk --location=US --dataset finlens-prod:finlens_mart

# Verify
bq ls --project_id=finlens-prod
```

**Table partitioning — HMDA applications:**
```sql
CREATE OR REPLACE TABLE `finlens-prod.finlens_raw.hmda_applications`
PARTITION BY RANGE_BUCKET(activity_year, GENERATE_ARRAY(2018, 2030, 1))
CLUSTER BY state_code, income_tier
AS SELECT * FROM `finlens-prod.finlens_raw.hmda_applications_load`;
```

---

## Phase 3 — Secret Manager

```bash
# Store HMDA API key
echo -n "YOUR_HMDA_API_KEY" | \
  gcloud secrets create hmda-api-key --data-file=-

# Store FRED API key
echo -n "YOUR_FRED_API_KEY" | \
  gcloud secrets create fred-api-key --data-file=-

# Store service account JSON (for Streamlit runtime)
gcloud secrets create finlens-sa-key \
  --data-file=~/finlens-sa-key.json

# Grant Cloud Run access to secrets
gcloud secrets add-iam-policy-binding finlens-sa-key \
  --member="serviceAccount:$SA" --role="roles/secretmanager.secretAccessor"
```

---

## Phase 4 — dbt Core Setup

```bash
# Install
pip install dbt-bigquery

# Initialise project (run from repo root)
dbt init finlens

# Configure profiles.yml (~/.dbt/profiles.yml)
cat > ~/.dbt/profiles.yml << 'EOF'
finlens:
  target: prod
  outputs:
    prod:
      type: bigquery
      method: service-account
      project: finlens-prod
      dataset: finlens_mart
      keyfile: /secrets/finlens-sa-key.json
      location: US
      threads: 4
      timeout_seconds: 300
EOF

# Test connection
dbt debug

# Run models and tests
dbt deps
dbt run  --target prod
dbt test --target prod
```

**dbt project structure:**
```
finlens/
  models/
    staging/
      stg_hmda_applications.sql
      stg_fred_macro.sql
    marts/
      regulatory_panel.sql          # state × year aggregated panel
      income_tier_panel.sql         # income tier × state × year
      investor_loan_panel.sql       # owner vs investor split
  tests/
    assert_approval_rate_bounded.sql
    assert_no_null_state_code.sql
```

---

## Phase 5 — Cloud Composer (Airflow)

```bash
# Create Composer environment (takes ~20 min)
gcloud composer environments create finlens-composer \
  --location=us-central1 \
  --image-version=composer-2.5.0-airflow-2.6.3 \
  --machine-type=n1-standard-2 \
  --service-account=$SA

# Upload DAGs
BUCKET=$(gcloud composer environments describe finlens-composer \
  --location=us-central1 --format="value(config.dagGcsPrefix)")

gsutil cp airflow/dags/hmda_ingest_dag.py   $BUCKET/
gsutil cp airflow/dags/fred_ingest_dag.py   $BUCKET/
gsutil cp airflow/dags/dbt_run_dag.py       $BUCKET/

# Set Airflow variables
gcloud composer environments run finlens-composer \
  --location=us-central1 variables -- \
  set BQ_PROJECT finlens-prod

gcloud composer environments run finlens-composer \
  --location=us-central1 variables -- \
  set DBT_TARGET prod
```

**DAG schedule:**

| DAG | Schedule | Trigger |
|-----|----------|---------|
| `hmda_ingest_dag` | `0 5 * * 1` (weekly, Mon 05:00 UTC) | Pulls latest HMDA vintage from CFPB API |
| `fred_ingest_dag` | `0 6 * * *` (daily 06:00 UTC) | Updates unemployment, HPI, mortgage rate |
| `dbt_run_dag` | Triggered by ingestion success | Runs `dbt run && dbt test` after each ingest |

---

## Phase 6 — Containerise the Streamlit App

**Dockerfile** (place in repo root):
```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Cloud Run requires port 8080
EXPOSE 8080

# Streamlit startup
CMD ["streamlit", "run", "app/finlens_app.py", \
     "--server.port=8080", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
```

**requirements.txt (minimum):**
```
streamlit>=1.32
pandas>=2.0
numpy>=1.26
statsmodels>=0.14
plotly>=5.20
google-cloud-bigquery>=3.17
google-cloud-secret-manager>=2.20
db-dtypes>=1.2
econml>=0.15           # optional — for CausalForest supplemental
scikit-learn>=1.4
```

---

## Phase 7 — Build & Push Docker Image

```bash
# Create Artifact Registry repository
gcloud artifacts repositories create finlens-repo \
  --repository-format=docker \
  --location=us-central1

# Authenticate Docker
gcloud auth configure-docker us-central1-docker.pkg.dev

# Set image tag
IMAGE=us-central1-docker.pkg.dev/finlens-prod/finlens-repo/finlens-app

# Build (from repo root)
docker build -t $IMAGE:latest .

# Push
docker push $IMAGE:latest
```

---

## Phase 8 — Deploy to Cloud Run

```bash
IMAGE=us-central1-docker.pkg.dev/finlens-prod/finlens-repo/finlens-app

gcloud run deploy finlens-app \
  --image          $IMAGE:latest \
  --platform       managed \
  --region         us-central1 \
  --service-account $SA \
  --allow-unauthenticated \
  --memory         2Gi \
  --cpu            2 \
  --min-instances  1 \
  --max-instances  10 \
  --port           8080 \
  --set-secrets    GOOGLE_APPLICATION_CREDENTIALS=finlens-sa-key:latest \
  --set-env-vars   GCP_PROJECT=finlens-prod,BQ_DATASET=finlens_mart
```

**Verify deployment:**
```bash
gcloud run services describe finlens-app \
  --region=us-central1 \
  --format="value(status.url)"
# → https://finlens-app-xxxx-uc.a.run.app
```

---

## Phase 9 — CI/CD with Cloud Build

**cloudbuild.yaml** (place in repo root):
```yaml
steps:
  # 1. Run dbt tests
  - name: python:3.11
    entrypoint: bash
    args:
      - -c
      - pip install dbt-bigquery && dbt test --target prod

  # 2. Build Docker image
  - name: gcr.io/cloud-builders/docker
    args: [build, -t, $_IMAGE_TAG, .]

  # 3. Push to Artifact Registry
  - name: gcr.io/cloud-builders/docker
    args: [push, $_IMAGE_TAG]

  # 4. Deploy to Cloud Run
  - name: gcr.io/google.com/cloudsdktool/cloud-sdk
    entrypoint: gcloud
    args:
      - run
      - deploy
      - finlens-app
      - --image=$_IMAGE_TAG
      - --region=us-central1
      - --platform=managed

substitutions:
  _IMAGE_TAG: us-central1-docker.pkg.dev/finlens-prod/finlens-repo/finlens-app:$COMMIT_SHA

triggers:
  - branch: main   # trigger on push to main
```

```bash
# Connect GitHub repo to Cloud Build
gcloud builds triggers create github \
  --repo-name=Finlens \
  --repo-owner=ellandalla \
  --branch-pattern="^main$" \
  --build-config=cloudbuild.yaml
```

---

## Alternative — Streamlit Community Cloud (Prototype Only)

| | Community Cloud | Cloud Run (Production) |
|--|----------------|----------------------|
| Cost | Free | ~$20–80/month |
| Setup | 5 min (GitHub OAuth) | ~2 hours |
| BigQuery IAM | Limited | Full control |
| Private repo | Paid plan | Yes |
| Custom domain | No | Yes |
| Auto-scaling | No | Yes (0→10 instances) |
| Recommended for | Demos / prototypes | Production |

**Community Cloud steps:**
1. Push code to GitHub (public or private with paid plan)
2. Go to [share.streamlit.io](https://share.streamlit.io) → New app
3. Select repo → branch → `app/finlens_app.py`
4. Add secrets in Streamlit Cloud UI: `GCP_PROJECT`, `GOOGLE_APPLICATION_CREDENTIALS` (paste SA JSON)
5. Deploy → get `https://finlens.streamlit.app`

---

## Deployment Checklist

- [ ] GCP project created and billing linked
- [ ] All 6 APIs enabled
- [ ] Service account created with correct roles
- [ ] Service account key stored in Secret Manager
- [ ] BigQuery datasets: `finlens_raw`, `finlens_staging`, `finlens_mart`
- [ ] HMDA partition table created and loaded
- [ ] dbt `dbt debug` passes against BigQuery
- [ ] dbt `dbt run && dbt test` completes with 0 failures
- [ ] Cloud Composer environment running and DAGs uploaded
- [ ] Airflow DAG variables set (`BQ_PROJECT`, `DBT_TARGET`)
- [ ] Docker image builds locally: `docker build -t finlens-app .`
- [ ] Docker image pushed to Artifact Registry
- [ ] Cloud Run service deployed and returning 200
- [ ] App URL loads Streamlit dashboard in browser
- [ ] Cloud Build trigger connected to GitHub main branch
- [ ] Budget alert set ($50/month threshold)
- [ ] `min-instances = 1` set to avoid cold starts for demo

---

## Estimated Monthly Cost (Production)

| Service | Config | Est. Cost |
|---------|--------|-----------|
| BigQuery | ~10 GB storage + 50 GB query/month | ~$5 |
| Cloud Composer | Small environment, 1 worker | ~$150 |
| Cloud Run | 1 min instance + ~1k requests/day | ~$10 |
| Artifact Registry | <1 GB images | ~$0.10 |
| Secret Manager | 4 secrets | ~$0.24 |
| Cloud Build | 120 free min/day | ~$0 |
| **Total** | | **~$165/month** |

> **Cost tip:** Use Cloud Scheduler + Cloud Run Jobs instead of Cloud Composer to reduce orchestration cost to ~$1/month for low-frequency pipelines.
