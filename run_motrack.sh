#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Reuses the existing Python 3.12 environment; creates nothing and installs nothing.
PYTHON_BIN="${MOTRACK_PYTHON:-/home/ht/miniforge3/envs/vlm/bin/python3.12}"
# Project-scoped only: this PATH is exported to this process and its children,
# never written to shell profiles or system configuration.
FFMPEG_BIN="$ROOT/tools/ffmpeg/bin"
if [[ ! -x "$FFMPEG_BIN/ffmpeg" || ! -x "$FFMPEG_BIN/ffprobe" ]]; then
  echo "MoTrack: project-local ffmpeg/ffprobe missing at $FFMPEG_BIN" >&2
  exit 2
fi
export PATH="$FFMPEG_BIN:$PATH"
exec "$PYTHON_BIN" "$ROOT/motrack.py" "$@"
