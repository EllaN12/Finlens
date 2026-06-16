#!/usr/bin/env bash
# Run dbt with ADC (oauth in profiles.yml). Unset a broken service-account path
# that would otherwise override Application Default Credentials.
set -euo pipefail

unset GOOGLE_APPLICATION_CREDENTIALS

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -f "${ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${ROOT}/.env"
  set +a
fi

: "${GCP_PROJECT:?Set GCP_PROJECT in ${ROOT}/.env or export it before running dbt}"

cd "$(dirname "$0")"
exec dbt "$@"
