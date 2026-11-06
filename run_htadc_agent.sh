#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
if [[ -z "${MOTRACK_API_KEY:-}" && -r "$ROOT/.secrets/htadc_api_key" ]]; then MOTRACK_API_KEY="$(<"$ROOT/.secrets/htadc_api_key")"; export MOTRACK_API_KEY; fi
if [[ -z "${MOTRACK_API_KEY:-}" ]]; then
  read -r -s -p 'MOTRACK_API_KEY: ' MOTRACK_API_KEY; echo
  export MOTRACK_API_KEY
fi
export MOTRACK_API_BASE_URL="${MOTRACK_API_BASE_URL:-http://sub2api.adc-ingress.aeroht.net/v1}"
if [[ "$MOTRACK_API_BASE_URL" == http://* ]]; then
  echo "WARNING: using the internal plaintext HTTP proxy; API keys are visible on the network path." >&2
  export MOTRACK_ALLOW_INSECURE_HTTP="${MOTRACK_ALLOW_INSECURE_HTTP:-1}"
fi
export MOTRACK_API_MODEL="${MOTRACK_API_MODEL:-deepseek-v4.1-flash}"
if [[ " $* " != *" --allow-api "* ]]; then
  echo "MoTrack: live-agent makes paid API calls. Re-run with --allow-api after approval:" >&2
  echo "  $ROOT/run_htadc_agent.sh inputs/game.mp4 --allow-api" >&2
  exit 2
fi
exec "$ROOT/run_motrack.sh" live-agent "$@"
