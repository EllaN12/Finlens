# ─────────────────────────────────────────────────────────────────────────────
# Dockerfile
# FinLens — Cloud Run Service: Streamlit App
#
# Scales to zero between visits (--min-instances 0).
# Cold start: ~10-15 seconds on first request.
#
# Build:
#   docker build -t finlens-app .
# Run locally:
#   docker run -p 8080:8080 --env-file .env finlens-app
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies (excluding dbt — not needed in the app image)
COPY requirements.txt .
RUN pip install --no-cache-dir $(grep -v 'dbt' requirements.txt | grep -v '^#' | grep -v '^$' | tr '\n' ' ')

# Copy application code
COPY app/        app/
COPY config.py   .
COPY scenarios/  scenarios/

# Streamlit config — disable telemetry, set server options
RUN mkdir -p /app/.streamlit && \
    printf '[server]\nport = 8080\nheadless = true\nenableCORS = false\nenableXsrfProtection = false\n\n[browser]\ngatherUsageStats = false\n' \
    > /app/.streamlit/config.toml

# Cloud Run injects PORT=8080; Streamlit reads it via --server.port
ENV PORT=8080

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8080/_stcore/health || exit 1

CMD ["streamlit", "run", "app/finlens_app.py", \
     "--server.port=8080", \
     "--server.headless=true", \
     "--server.address=0.0.0.0"]
