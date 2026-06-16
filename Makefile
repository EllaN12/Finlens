## FinLens project tasks — Usage: make <target>
## Run `make help` for a full list of targets.

DBT       := .venv/bin/dbt
STREAMLIT := .venv/bin/streamlit
ENV_FILE  := .env

# Load .env silently: -include won't fail if .env is absent or has parse quirks
-include $(ENV_FILE)
export

# Artifact Registry image paths
REGION    ?= $(GCP_REGION)
REPO      ?= finlens
REGISTRY  := $(REGION)-docker.pkg.dev/$(GCP_PROJECT)/$(REPO)
IMG_APP      := $(REGISTRY)/finlens-app:latest
IMG_PIPELINE := $(REGISTRY)/finlens-pipeline:latest

.PHONY: help \
        dbt-run dbt-test dbt-mart dbt-all \
        app env-check \
        build-app build-pipeline \
        push-app push-pipeline \
        deploy-app deploy-pipeline \
        deploy-all \
        run-pipeline \
        logs-pipeline logs-app \
        setup-gcp

# ── Local development ──────────────────────────────────────────────────────

help:
	@echo ""
	@echo "FinLens Makefile targets"
	@echo "────────────────────────────────────────────────"
	@echo "  LOCAL"
	@echo "    app            Start Streamlit app locally"
	@echo "    dbt-run        Run all dbt models"
	@echo "    dbt-test       Run dbt tests"
	@echo "    dbt-mart       Run mart_regulatory_cohort only"
	@echo "    dbt-all        dbt-run + dbt-test"
	@echo "    env-check      Print loaded env vars"
	@echo ""
	@echo "  DOCKER"
	@echo "    build-app      Build Streamlit app image"
	@echo "    build-pipeline Build ingest+dbt pipeline image"
	@echo "    push-app       Push app image to Artifact Registry"
	@echo "    push-pipeline  Push pipeline image to Artifact Registry"
	@echo ""
	@echo "  DEPLOY"
	@echo "    deploy-app     Deploy app to Cloud Run Service (scale-to-zero)"
	@echo "    deploy-pipeline Deploy pipeline to Cloud Run Job"
	@echo "    deploy-all     Build + push + deploy both"
	@echo ""
	@echo "  OPS"
	@echo "    run-pipeline   Manually trigger the Cloud Run Job now"
	@echo "    logs-pipeline  Tail Cloud Run Job logs"
	@echo "    logs-app       Tail Cloud Run Service logs"
	@echo "    setup-gcp      One-time GCP project setup (IAM, APIs, registry)"
	@echo "────────────────────────────────────────────────"
	@echo ""

dbt-run:
	cd finlens_dbt && ../$(DBT) run

dbt-test:
	cd finlens_dbt && ../$(DBT) test

dbt-mart:
	cd finlens_dbt && ../$(DBT) run -s mart_regulatory_cohort

dbt-all: dbt-run dbt-test

app:
	$(STREAMLIT) run app/finlens_app.py --server.port 8501 --server.headless true

env-check:
	@echo "GCP_PROJECT  = $(GCP_PROJECT)"
	@echo "GCP_REGION   = $(GCP_REGION)"
	@echo "BQ_DATASET   = $(BQ_DATASET_MARTS)"
	@echo "REGISTRY     = $(REGISTRY)"

# ── Docker build ────────────────────────────────────────────────────────────

build-app:
	docker build --platform linux/amd64 -f Dockerfile -t $(IMG_APP) .
	@echo "Built: $(IMG_APP)"

build-pipeline:
	docker build --platform linux/amd64 -f Dockerfile.pipeline -t $(IMG_PIPELINE) .
	@echo "Built: $(IMG_PIPELINE)"

# ── Docker push ─────────────────────────────────────────────────────────────

push-app: build-app
	docker push $(IMG_APP)

push-pipeline: build-pipeline
	docker push $(IMG_PIPELINE)

# ── Cloud Run deploy ────────────────────────────────────────────────────────

deploy-app: push-app
	gcloud run deploy finlens-app \
	  --image $(IMG_APP) \
	  --region $(REGION) \
	  --platform managed \
	  --allow-unauthenticated \
	  --port 8080 \
	  --memory 1Gi \
	  --cpu 1 \
	  --min-instances 0 \
	  --max-instances 3 \
	  --timeout 300 \
	  --set-env-vars GCP_PROJECT=$(GCP_PROJECT),BQ_DATASET_MARTS=$(BQ_DATASET_MARTS) \
	  --service-account finlens-sa@$(GCP_PROJECT).iam.gserviceaccount.com
	@echo ""
	@echo "App deployed. URL:"
	@gcloud run services describe finlens-app --region $(REGION) --format 'value(status.url)'

deploy-pipeline: push-pipeline
	gcloud run jobs update finlens-pipeline \
	  --image $(IMG_PIPELINE) \
	  --region $(REGION) \
	  --memory 2Gi \
	  --cpu 2 \
	  --task-timeout 3600 \
	  --max-retries 2 \
	  --set-env-vars GCP_PROJECT=$(GCP_PROJECT),BQ_DATASET_MARTS=$(BQ_DATASET_MARTS),FRED_API_KEY=$(FRED_API_KEY) \
	  --service-account finlens-sa@$(GCP_PROJECT).iam.gserviceaccount.com \
	|| \
	gcloud run jobs create finlens-pipeline \
	  --image $(IMG_PIPELINE) \
	  --region $(REGION) \
	  --memory 2Gi \
	  --cpu 2 \
	  --task-timeout 3600 \
	  --max-retries 2 \
	  --set-env-vars GCP_PROJECT=$(GCP_PROJECT),BQ_DATASET_MARTS=$(BQ_DATASET_MARTS),FRED_API_KEY=$(FRED_API_KEY) \
	  --service-account finlens-sa@$(GCP_PROJECT).iam.gserviceaccount.com
	@echo "Pipeline job deployed."

deploy-all: push-app push-pipeline deploy-app deploy-pipeline
	@echo "Full deployment complete."

# ── Ops ─────────────────────────────────────────────────────────────────────

run-pipeline:
	gcloud run jobs execute finlens-pipeline --region $(REGION) --wait
	@echo "Pipeline execution complete."

logs-pipeline:
	gcloud logging read \
	  'resource.type="cloud_run_job" resource.labels.job_name="finlens-pipeline"' \
	  --limit 100 --format 'value(textPayload)' --project $(GCP_PROJECT)

logs-app:
	gcloud run services logs tail finlens-app --region $(REGION)

# ── One-time GCP setup ───────────────────────────────────────────────────────

setup-gcp:
	@echo "=== Enabling required APIs ==="
	gcloud services enable \
	  run.googleapis.com \
	  cloudscheduler.googleapis.com \
	  cloudbuild.googleapis.com \
	  artifactregistry.googleapis.com \
	  bigquery.googleapis.com \
	  secretmanager.googleapis.com \
	  --project $(GCP_PROJECT)

	@echo "=== Creating Artifact Registry repository ==="
	gcloud artifacts repositories create $(REPO) \
	  --repository-format docker \
	  --location $(REGION) \
	  --description "FinLens Docker images" \
	  --project $(GCP_PROJECT) || true

	@echo "=== Creating service account ==="
	gcloud iam service-accounts create finlens-sa \
	  --display-name "FinLens Service Account" \
	  --project $(GCP_PROJECT) || true

	@echo "=== Granting IAM roles ==="
	gcloud projects add-iam-policy-binding $(GCP_PROJECT) \
	  --member "serviceAccount:finlens-sa@$(GCP_PROJECT).iam.gserviceaccount.com" \
	  --role "roles/bigquery.dataEditor"
	gcloud projects add-iam-policy-binding $(GCP_PROJECT) \
	  --member "serviceAccount:finlens-sa@$(GCP_PROJECT).iam.gserviceaccount.com" \
	  --role "roles/bigquery.jobUser"
	gcloud projects add-iam-policy-binding $(GCP_PROJECT) \
	  --member "serviceAccount:finlens-sa@$(GCP_PROJECT).iam.gserviceaccount.com" \
	  --role "roles/secretmanager.secretAccessor"
	gcloud projects add-iam-policy-binding $(GCP_PROJECT) \
	  --member "serviceAccount:finlens-sa@$(GCP_PROJECT).iam.gserviceaccount.com" \
	  --role "roles/run.invoker"

	@echo "=== Authorizing Docker to push to Artifact Registry ==="
	gcloud auth configure-docker $(REGION)-docker.pkg.dev

	@echo ""
	@echo "GCP setup complete. Next: make deploy-all"
