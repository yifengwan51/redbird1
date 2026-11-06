#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
# Reuses an existing Python 3.12 environment; creates nothing and installs nothing.
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
# Project-scoped only: this PATH is exported to this process and its children,
# never written to shell profiles or system configuration.
FFMPEG_BIN="$ROOT/tools/ffmpeg/bin"
if [[ ! -x "$FFMPEG_BIN/ffmpeg" || ! -x "$FFMPEG_BIN/ffprobe" ]]; then
  echo "MoTrack: project-local ffmpeg/ffprobe missing at $FFMPEG_BIN" >&2
  exit 2
fi
export PATH="$FFMPEG_BIN:$PATH"
exec "$PYTHON_BIN" "$ROOT/motrack.py" "$@"
