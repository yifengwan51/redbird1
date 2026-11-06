#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -z "${MOTRACK_API_KEY:-}" && -r "$ROOT/.secrets/htadc_api_key" ]]; then MOTRACK_API_KEY="$(<"$ROOT/.secrets/htadc_api_key")"; export MOTRACK_API_KEY; fi
if [[ -z "${MOTRACK_API_KEY:-}" ]]; then
  read -r -s -p 'MOTRACK_API_KEY: ' MOTRACK_API_KEY; echo
  export MOTRACK_API_KEY
fi
export MOTRACK_API_BASE_URL="${MOTRACK_API_BASE_URL:-http://sub2api.adc-ingress.aeroht.net/v1}"
export MOTRACK_API_MODEL="${MOTRACK_API_MODEL:-deepseek-v4.1-flash}"
exec "$ROOT/run_motrack.sh" live-agent "$@"
