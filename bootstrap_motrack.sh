#!/usr/bin/env bash
# Safe, project-local bootstrap for a fresh MoTrack clone.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

usage() {
  cat <<'EOF'
Usage: ./bootstrap_motrack.sh [--check] [--setup-key] [--samples]

  --check      Check local prerequisites without downloading or changing files.
  --setup-key  Prompt once without echoing and store the HTADC key in
               .secrets/htadc_api_key (directory 700, file 600).
  --samples    Download the two documented CC BY Wikimedia basketball samples
               and convert them into the MP4 paths used by the local web app.

No option is destructive. Existing sample files and an existing key are kept.
Model weights are intentionally not bundled: local analysis downloads official
weights on first use and caches them under this project.
EOF
}

want_check=0
want_key=0
want_samples=0
for arg in "$@"; do
  case "$arg" in
    --check) want_check=1 ;;
    --setup-key) want_key=1 ;;
    --samples) want_samples=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; usage >&2; exit 2 ;;
  esac
done

project_ffmpeg="$ROOT/tools/ffmpeg/bin/ffmpeg"
if [[ -x "$project_ffmpeg" ]]; then
  FFMPEG="$project_ffmpeg"
elif command -v ffmpeg >/dev/null 2>&1; then
  FFMPEG="$(command -v ffmpeg)"
else
  FFMPEG=""
fi

echo "Project: $ROOT"
if [[ -n "$FFMPEG" ]]; then
  echo "FFmpeg: $FFMPEG"
else
  echo "FFmpeg: not found (needed only for --samples conversion)"
fi
if [[ -x "$ROOT/.venv_lightweight/bin/python" ]]; then
  echo "Local Python: $ROOT/.venv_lightweight/bin/python"
else
  echo "Local Python: not found; set up the project Python environment before local X3D analysis."
fi
if [[ -r "$ROOT/.secrets/htadc_api_key" ]]; then
  echo "HTADC key: configured locally"
else
  echo "HTADC key: not configured (only required for live LLM/VIP functions)"
fi

if [[ "$want_key" -eq 1 ]]; then
  if [[ -r "$ROOT/.secrets/htadc_api_key" ]]; then
    echo "HTADC key already exists; leaving it unchanged."
  else
    umask 077
    mkdir -p "$ROOT/.secrets"
    chmod 700 "$ROOT/.secrets"
    read -r -s -p 'MOTRACK_API_KEY (stored locally, not committed): ' entered_key
    echo
    if [[ -z "$entered_key" ]]; then
      echo "No key entered; nothing was written." >&2
      exit 2
    fi
    printf '%s' "$entered_key" > "$ROOT/.secrets/htadc_api_key"
    unset entered_key
    chmod 600 "$ROOT/.secrets/htadc_api_key"
    echo "HTADC key saved only to .secrets/htadc_api_key."
  fi
fi

if [[ "$want_samples" -eq 1 ]]; then
  if [[ -z "$FFMPEG" ]]; then
    echo "Cannot prepare samples: FFmpeg is unavailable." >&2
    exit 2
  fi
  if ! command -v curl >/dev/null 2>&1; then
    echo "Cannot prepare samples: curl is unavailable." >&2
    exit 2
  fi

  originals="$ROOT/inputs/original"
  mkdir -p "$originals"
  download() {
    local target="$1"
    local url="$2"
    if [[ -s "$target" ]]; then
      echo "Keeping existing $(basename "$target")"
      return
    fi
    local temporary="${target}.part"
    rm -f "$temporary"
    echo "Downloading $(basename "$target") from Wikimedia Commons..."
    curl --fail --location --retry 3 --retry-delay 2 --output "$temporary" "$url"
    mv "$temporary" "$target"
  }

  # Attribution and licenses are recorded in docs/ASSET_SETUP.md.
  download "$originals/Doug_McDermott.ogv" \
    "https://commons.wikimedia.org/wiki/Special:Redirect/file/Doug_McDermott.ogv"
  download "$originals/CBF_3x3_Tour_Usti_nad_Labem.webm" \
    "https://commons.wikimedia.org/wiki/Special:Redirect/file/%C4%8CBF_3x3_Tour_22.6._%C3%9Ast%C3%AD_nad_Labem.webm"

  convert() {
    local source="$1"
    local target="$2"
    if [[ -s "$target" ]]; then
      echo "Keeping existing $(basename "$target")"
      return
    fi
    echo "Converting $(basename "$source") to $(basename "$target")..."
    "$FFMPEG" -hide_banner -loglevel error -y -i "$source" \
      -map 0:v:0 -map 0:a? -c:v libx264 -pix_fmt yuv420p -crf 20 -preset medium \
      -c:a aac -movflags +faststart "$target"
  }
  convert "$originals/Doug_McDermott.ogv" "$ROOT/inputs/doug_mcdermott.mp4"
  convert "$originals/CBF_3x3_Tour_Usti_nad_Labem.webm" "$ROOT/inputs/cbf_3x3_tour.mp4"
  echo "Sample preparation complete."
fi

if [[ "$want_check" -eq 1 && "$want_key" -eq 0 && "$want_samples" -eq 0 ]]; then
  echo "Check complete; no files changed."
fi
