"""Shot attempts and made baskets from a basketball object detector.

Model: YOLOX-M fine-tuned on Roboflow ``basketball-player-detection-3``
(CC BY 4.0), published by ortizeg on Hugging Face under Apache-2.0.  It
detects the ball, the rim, "ball-in-basket", and shooting poses
(jump shot, layup/dunk, block) per frame.  It runs on CPU through OpenCV DNN,
about 60 ms per frame, so no extra runtime is needed.

The scan samples SAMPLE_FPS frames per second and keeps a compact per-frame
row (best score and box per useful class).  Rows are cached, so thresholds
can be tuned without rescanning the video.

A made basket needs evidence near the rim after the shot: either the model's
"ball-in-basket" class, or the ball centre passing down through the rim box.
"Missed" is claimed only when the rim was clearly in view and neither signal
appeared; otherwise the outcome stays "unknown".  These are model guesses,
not verified results.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "models" / "hoop" / "yolox_m_basketball_640.onnx"
MODEL_URL = "https://huggingface.co/ortizeg/basketball-yolox-m-640/resolve/main/yolox_m_basketball_640.onnx"
MODEL_SHA256 = "5f2f05c6890f513a06e6c94154363b351c1eefde0c57b2c9b16c2d48557d5c77"
CACHE = ROOT / "outputs" / "shots"
CLASSES = ("ball", "ball-in-basket", "number", "player", "player-in-possession",
           "player-jump-shot", "player-layup-dunk", "player-shot-block", "referee", "rim")
KEEP = {"ball": 0, "ball-in-basket": 1, "player-jump-shot": 5, "player-layup-dunk": 6, "player-shot-block": 7, "rim": 9}
INPUT = 640
SAMPLE_FPS = 5.0
SCAN_VERSION = "1"      # bump when the per-frame row format changes
EVENTS_VERSION = "1"    # bump when the rules below change (no rescan needed)

SHOT_MIN = 0.40         # shooting-pose score that starts a shot attempt
SHOT_GAP = 1.2          # frames closer than this belong to the same attempt
MAKE_WINDOW = (-0.4, 3.0)   # seconds around the shot peak to look for a make
BIB_MIN = 0.30          # "ball-in-basket" score that counts as a make
RIM_MIN = 0.45          # rim score that counts as "rim in view"
BALL_MIN = 0.20
RIM_VIEW_FRAC = 0.6     # share of the make window the rim must be visible to claim a miss

SHOT_ZH = {"jump": "跳投", "layup": "上篮/扣篮"}
OUTCOME_ZH = {"made": "进了", "missed": "没进", "unknown": ""}

_lock = threading.Lock()
_net: Any = None


def available() -> bool:
    return MODEL.is_file()


def download_model() -> Path:
    """Fetch the detector from Hugging Face and verify its checksum."""
    MODEL.parent.mkdir(parents=True, exist_ok=True)
    part = MODEL.with_suffix(".part")
    with urllib.request.urlopen(MODEL_URL, timeout=60) as res, part.open("wb") as out:
        while chunk := res.read(1 << 20):
            out.write(chunk)
    digest = hashlib.sha256(part.read_bytes()).hexdigest()
    if digest != MODEL_SHA256:
        part.unlink(missing_ok=True)
        raise RuntimeError("detector checksum mismatch")
    os.replace(part, MODEL)
    return MODEL


def _model() -> Any:
    global _net
    if _net is None:
        _net = cv2.dnn.readNetFromONNX(str(MODEL))
    return _net


def _detect(frame: np.ndarray) -> dict[str, list[float]]:
    """Best score and box (cx, cy, w, h in source pixels) per kept class."""
    h, w = frame.shape[:2]
    r = min(INPUT / h, INPUT / w)
    nh, nw = round(h * r), round(w * r)
    canvas = np.full((INPUT, INPUT, 3), 114, np.uint8)  # YOLOX letterbox: top-left, pad 114, BGR, 0-255
    canvas[:nh, :nw] = cv2.resize(frame, (nw, nh))
    net = _model()
    net.setInput(canvas.transpose(2, 0, 1)[None].astype(np.float32))
    pred = net.forward()[0]
    scores = pred[:, 4:5] * pred[:, 5:]
    row: dict[str, list[float]] = {}
    for name, c in KEEP.items():
        k = int(scores[:, c].argmax())
        row[name] = [round(float(scores[k, c]), 3)] + [round(float(v / r), 1) for v in pred[k, :4]]
    return row


# ---------- scan (cached) ----------
def _cache_path(video_id: str) -> Path:
    return CACHE / f"{video_id}_rows.json"


def scan(video_id: str, video: Path, fingerprint: str,
         progress: Callable[[int, int], None] | None = None) -> list[dict[str, Any]]:
    """Per-frame detector rows at SAMPLE_FPS, cached per video fingerprint."""
    path = _cache_path(video_id)
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        if cached.get("version") == SCAN_VERSION and cached.get("fingerprint") == fingerprint:
            return cached["rows"]
    except (OSError, ValueError, KeyError):
        pass
    with _lock:
        cap = cv2.VideoCapture(str(video))
        if not cap.isOpened():
            raise RuntimeError(f"cannot decode {video.name}")
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        step = max(1, round(fps / SAMPLE_FPS))
        rows: list[dict[str, Any]] = []
        index = 0
        started = time.perf_counter()
        while cap.grab():
            if index % step == 0:
                ok, frame = cap.retrieve()
                if ok:
                    rows.append({"t": round(index / fps, 2), **_detect(frame)})
                if progress and len(rows) % 25 == 0:
                    progress(index, max(total, index + 1))
            index += 1
        cap.release()
    CACHE.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(".part")
    part.write_text(json.dumps({"version": SCAN_VERSION, "fingerprint": fingerprint, "sample_fps": SAMPLE_FPS,
                                "seconds": round(time.perf_counter() - started, 1), "rows": rows}), encoding="utf-8")
    os.replace(part, path)
    return rows
