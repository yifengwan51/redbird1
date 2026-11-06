#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
if [[ -n "${MOTRACK_PYTHON:-}" ]]; then
  PYTHON_BIN="$MOTRACK_PYTHON"
elif [[ -x "/home/ht/miniforge3/envs/vlm/bin/python3.12" ]]; then
  PYTHON_BIN="/home/ht/miniforge3/envs/vlm/bin/python3.12"
elif [[ -x "$ROOT/.venv_lightweight/bin/python" ]]; then
  PYTHON_BIN="$ROOT/.venv_lightweight/bin/python"
else
  PYTHON_BIN="$(command -v python3.12 || command -v python3 || true)"
fi
if [[ -z "$PYTHON_BIN" || ! -x "$PYTHON_BIN" ]]; then
  echo "MoTrack: no Python interpreter found; set MOTRACK_PYTHON." >&2
  exit 2
fi
if [[ -z "${MOTRACK_API_KEY:-}" && -r "$ROOT/.secrets/htadc_api_key" ]]; then MOTRACK_API_KEY="$(<"$ROOT/.secrets/htadc_api_key")"; export MOTRACK_API_KEY; fi
if [[ -z "${MOTRACK_API_KEY:-}" ]]; then read -r -s -p 'MOTRACK_API_KEY: ' MOTRACK_API_KEY; echo; export MOTRACK_API_KEY; fi
export MOTRACK_API_BASE_URL="${MOTRACK_API_BASE_URL:-http://sub2api.adc-ingress.aeroht.net/v1}"
if [[ "$MOTRACK_API_BASE_URL" == http://* ]]; then
  echo "WARNING: using the internal plaintext HTTP proxy; API keys are visible on the network path." >&2
  export MOTRACK_ALLOW_INSECURE_HTTP="${MOTRACK_ALLOW_INSECURE_HTTP:-1}"
fi
export MOTRACK_API_MODEL="${MOTRACK_API_MODEL:-deepseek-v4.1-flash}"
exec "$PYTHON_BIN" "$ROOT/semantic_vision.py"
