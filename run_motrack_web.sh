#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
if [[ -n "${MOTRACK_PYTHON:-}" ]]; then
  PYTHON="$MOTRACK_PYTHON"
elif [[ -x "$ROOT/.venv_lightweight/bin/python" ]]; then
  PYTHON="$ROOT/.venv_lightweight/bin/python"
elif [[ -x "/home/ht/miniforge3/envs/vlm/bin/python3.12" ]]; then
  PYTHON="/home/ht/miniforge3/envs/vlm/bin/python3.12"
else
  PYTHON="$(command -v python3.12 || command -v python3 || true)"
fi
if [[ -z "$PYTHON" || ! -x "$PYTHON" ]]; then
  echo "MoTrack Web: no Python interpreter found; set MOTRACK_PYTHON." >&2
  exit 2
fi
if ! "$PYTHON" -c 'import fastapi, uvicorn' >/dev/null 2>&1; then
  echo "MoTrack Web: 缺少 FastAPI/Uvicorn；请使用项目既有 Python 环境启动。" >&2
  exit 2
fi
if [[ -x "$ROOT/.venv_lightweight/bin/python" ]] && ! "$PYTHON" -c 'import torch, pytorchvideo, cv2' >/dev/null 2>&1; then
  echo "MoTrack Web: 当前 Python 缺少本地 X3D 依赖（torch/pytorchvideo/cv2）；请使用 .venv_lightweight 或设置 MOTRACK_PYTHON。" >&2
  exit 2
fi
export MOTRACK_API_BASE_URL="${MOTRACK_API_BASE_URL:-http://sub2api.adc-ingress.aeroht.net/v1}"
if [[ "$MOTRACK_API_BASE_URL" == http://* ]]; then
  echo "WARNING: using the internal plaintext HTTP proxy; API keys are visible on the network path." >&2
  export MOTRACK_ALLOW_INSECURE_HTTP="${MOTRACK_ALLOW_INSECURE_HTTP:-1}"
fi
# --remote: also open a public HTTPS tunnel so a phone can use MoTrack from
# anywhere (access code required; the server itself stays on 127.0.0.1).
if [[ "${1:-}" == "--remote" ]]; then
  export MOTRACK_REMOTE=1
  echo "MoTrack: 手机访问已开启，在电脑页面点「📱 手机用」查看二维码和口令。" >&2
fi
export MOTRACK_PORT="${MOTRACK_PORT:-8765}"
if ! [[ "$MOTRACK_PORT" =~ ^[1-9][0-9]{0,4}$ ]] || (( MOTRACK_PORT > 65535 )); then
  echo "MoTrack Web: MOTRACK_PORT must be a valid TCP port (1-65535)." >&2
  exit 2
fi
exec "$PYTHON" -m uvicorn web.backend.app:app --host 127.0.0.1 --port "$MOTRACK_PORT" --app-dir "$ROOT"
