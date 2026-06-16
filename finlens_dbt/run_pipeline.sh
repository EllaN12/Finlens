#!/usr/bin/env bash
# Full dbt pipeline: staging → intermediate → marts → test → docs
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

./dbt.sh run --select staging
./dbt.sh run --select intermediate
./dbt.sh run --select marts
./dbt.sh test
./dbt.sh docs generate
echo "Docs ready. Serve with: ./dbt.sh docs serve --port 8081"
