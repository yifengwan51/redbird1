#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -z "${MOTRACK_API_KEY:-}" && -r "$ROOT/.secrets/htadc_api_key" ]]; then export MOTRACK_API_KEY="$(<"$ROOT/.secrets/htadc_api_key")"; fi
exec /home/ht/miniforge3/envs/vlm/bin/python3.12 "$ROOT/motrack_chat.py" "$@"
