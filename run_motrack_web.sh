#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$ROOT/.venv_lightweight/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="/home/ht/miniforge3/envs/vlm/bin/python3.12"
fi
if ! "$PYTHON" -c 'import fastapi, uvicorn' >/dev/null 2>&1; then
  echo "MoTrack Web: 缺少 FastAPI/Uvicorn；请使用项目既有 Python 环境启动。" >&2
  exit 2
fi
if [[ -x "$ROOT/.venv_lightweight/bin/python" ]] && ! "$PYTHON" -c 'import torch, pytorchvideo, cv2' >/dev/null 2>&1; then
  echo "MoTrack Web: 本地 X3D 依赖不完整；请修复 $ROOT/.venv_lightweight。" >&2
  exit 2
fi
exec "$PYTHON" -m uvicorn web.backend.app:app --host 127.0.0.1 --port 8765
