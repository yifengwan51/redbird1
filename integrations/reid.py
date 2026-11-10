"""Appearance embeddings for player tracks (person re-identification).

Model: OSNet x1.0 trained on MSMT17 (KaiyangZhou/deep-person-reid, MIT;
weights from huggingface.co/kaiyangzhou/osnet).  The network code is vendored
unchanged in integrations/vendor/osnet.py; the weights hold only tensors
(pickle globals checked) and are loaded with weights_only=True.

Per track, up to CROPS_PER_TRACK person crops spread over its lifetime are
embedded (512-d, L2-normalised) and averaged.  About 17 ms a crop on CPU.
Embeddings are cached per video by (frame, box), so re-tracking is free.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path
from typing import Any

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "models" / "reid" / "osnet_x1_0_msmt17.pth"
MODEL_URL = ("https://huggingface.co/kaiyangzhou/osnet/resolve/main/osnet_x1_0_msmt17_combineall_256x128_amsgrad_"
             "ep150_stp60_lr0.0015_b64_fb10_softmax_labelsmooth_flip_jitter.pth")
MODEL_SHA256 = "48df972f72887b95cf3b43b3a07c3a7d2398381aea0f9cae64a7ef11d512b727"
CACHE = ROOT / "outputs" / "shots"
CROPS_PER_TRACK = 8
MIN_BOX_H = 40              # smaller people give useless embeddings
BATCH = 32
_MEAN = np.array([0.485, 0.456, 0.406], np.float32)
_STD = np.array([0.229, 0.224, 0.225], np.float32)

_lock = threading.Lock()
_model: Any = None


def available() -> bool:
    return MODEL.is_file()


def download_model() -> Path:
    import urllib.request
    MODEL.parent.mkdir(parents=True, exist_ok=True)
    part = MODEL.with_suffix(".part")
    with urllib.request.urlopen(MODEL_URL, timeout=120) as res, part.open("wb") as out:
        while chunk := res.read(1 << 20):
            out.write(chunk)
    if hashlib.sha256(part.read_bytes()).hexdigest() != MODEL_SHA256:
        part.unlink(missing_ok=True)
        raise RuntimeError("re-id model checksum mismatch")
    os.replace(part, MODEL)
    return MODEL


def _get_model() -> Any:
    global _model
    if _model is None:
        import torch
        from integrations.vendor.osnet import osnet_x1_0
        m = osnet_x1_0(num_classes=1, pretrained=False, loss="softmax")
        sd = torch.load(str(MODEL), map_location="cpu", weights_only=True)
        sd = sd.get("state_dict", sd)
        sd = {k.replace("module.", ""): v for k, v in sd.items() if not k.replace("module.", "").startswith("classifier")}
        m.load_state_dict(sd, strict=False)
        _model = m.eval()
    return _model


def _embed(crops: list[np.ndarray]) -> np.ndarray:
    import torch
    x = np.stack([cv2.resize(cv2.cvtColor(c, cv2.COLOR_BGR2RGB), (128, 256)).astype(np.float32) / 255.0 for c in crops])
    x = torch.from_numpy(((x - _MEAN) / _STD).transpose(0, 3, 1, 2).copy())
    with torch.inference_mode():
        f = _get_model()(x).numpy()
    return f / np.maximum(1e-6, np.linalg.norm(f, axis=1, keepdims=True))


def _key(frame: int, box: list[float]) -> str:
    return f"{frame}:{int(box[1])}:{int(box[2])}:{int(box[3])}:{int(box[4])}"


def pick(obs: list[tuple[int, float, dict[str, Any]]], n: int = CROPS_PER_TRACK) -> list[tuple[int, float, dict[str, Any]]]:
    """Best crop (big, confident box) in each of n time bins over the track."""
    good = [o for o in obs if o[2]["box"][4] - o[2]["box"][2] >= MIN_BOX_H]
    if not good:
        return []
    t0, t1 = good[0][1], good[-1][1]
    bins: dict[int, tuple[int, float, dict[str, Any]]] = {}
    for o in good:
        b = min(n - 1, int(n * (o[1] - t0) / max(1e-6, t1 - t0)))
        score = o[2]["box"][0] * (o[2]["box"][4] - o[2]["box"][2])
        if b not in bins or score > bins[b][2]["box"][0] * (bins[b][2]["box"][4] - bins[b][2]["box"][2]):
            bins[b] = o
    return [bins[b] for b in sorted(bins)]


def embed_tracks(video: Path, rows: list[dict[str, Any]], tracks: list[dict[str, Any]], cache_id: str,
                 fingerprint: str) -> dict[int, np.ndarray]:
    """Track id -> mean appearance vector (tracks without usable crops are left out)."""
    path = CACHE / f"{cache_id}_reid.npz"
    cache: dict[str, np.ndarray] = {}
    try:
        z = np.load(path, allow_pickle=False)
        if str(z["fingerprint"]) == fingerprint:
            cache = dict(zip([str(k) for k in z["keys"]], z["vecs"]))
    except (OSError, KeyError, ValueError):
        pass
    wanted: dict[int, list[tuple[str, list[float]]]] = {}
    plan: dict[int, list[str]] = {}
    for tr in tracks:
        keys = []
        for k, _, p in pick(tr["obs"]):
            f = rows[k]["f"]
            key = _key(f, p["box"])
            keys.append(key)
            if key not in cache:
                wanted.setdefault(f, []).append((key, p["box"]))
        plan[tr["id"]] = keys
    if wanted:
        with _lock:
            cap = cv2.VideoCapture(str(video))
            crops: list[np.ndarray] = []
            names: list[str] = []
            index, todo = 0, sorted(wanted)
            pos = 0
            while pos < len(todo) and cap.grab():
                if index == todo[pos]:
                    ok, frame = cap.retrieve()
                    if ok:
                        H, W = frame.shape[:2]
                        for key, b in wanted[index]:
                            x1, y1, x2, y2 = int(max(0, b[1])), int(max(0, b[2])), int(min(W, b[3])), int(min(H, b[4]))
                            if x2 - x1 >= 8 and y2 - y1 >= 16:
                                crops.append(frame[y1:y2, x1:x2].copy()); names.append(key)
                    pos += 1
                    if len(crops) >= BATCH:
                        cache.update(zip(names, _embed(crops))); crops, names = [], []
                index += 1
            cap.release()
            if crops:
                cache.update(zip(names, _embed(crops)))
        CACHE.mkdir(parents=True, exist_ok=True)
        part = path.with_suffix(".part.npz")
        np.savez_compressed(part, fingerprint=np.array(fingerprint), keys=np.array(list(cache), dtype=str),
                            vecs=np.array(list(cache.values()), np.float32).reshape(len(cache), -1))
        os.replace(part, path)
    out: dict[int, np.ndarray] = {}
    for tid, keys in plan.items():
        vecs = [cache[k] for k in keys if k in cache]
        if vecs:
            v = np.mean(vecs, axis=0)
            out[tid] = v / max(1e-6, float(np.linalg.norm(v)))
    return out
