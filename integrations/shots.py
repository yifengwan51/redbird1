"""Shot attempts and made baskets from a basketball detector.

Model: the RF-DETR basketball detector from OpenHoopVision-core
(github.com/feifeifei85/OpenHoopVision-core, Apache-2.0 per its README),
trained on amateur and youth game footage.  Classes: ball, holder, rim,
scorer, player, referee, ball-in-basket.  On fixed-camera and amateur clips it
finds the rim in 95-100% of frames; the previous NBA-trained YOLOX found it
in 0-15% (docs/SHOT_DETECTION_VALIDATION.md).

Scan: every frame is too slow on CPU, and a shot near the rim lasts well under
a second, so the video is scanned in two passes.  A coarse pass samples
COARSE_FPS frames per second; wherever the ball comes near the rim, a dense
pass reads every frame around that moment.  Rows are cached per video.

Rules (the usual single-camera method, as in avishah3's shot tracker and
ShotTracker): lock the rim and reject jumps to the other hoop; follow the ball
that moves continuously; an attempt starts when the ball enters the zone above
the rim; it is made when the ball's path crosses the rim height inside the rim,
or the detector sees ball-in-basket on consecutive frames; it is missed when
the rim stayed in view and neither happened; otherwise unknown.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

import cv2

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "models" / "ohv" / "rf-detr-basketball.pth"
MODEL_URL = "https://media.githubusercontent.com/media/feifeifei85/OpenHoopVision-core/HEAD/weights/rf-detr-basketball.pth"
MODEL_SHA256 = "69409cbefc4b92c3cd194fb7f877c6e58e52548909e05e3b5467fe0e2fe188c5"
CACHE = ROOT / "outputs" / "shots"
KEEP = ("ball", "rim", "ball-in-basket", "scorer", "player", "holder", "referee")
PEOPLE = ("player", "holder", "scorer")     # boxes that also get a jersey colour [L, a, b]
PEOPLE_MIN = 0.35
SCAN_VERSION = "3-rfdetr-people"
SHORT_SIDE = 512            # detector input short side (rim/ball found reliably at 512)
COARSE_FPS = 5.0
SAMPLE_FPS = COARSE_FPS     # name kept for callers
DENSE_BEFORE, DENSE_AFTER = 1.0, 1.5   # seconds read at full rate around a ball-near-rim moment
BATCH = 8

# rule parameters (tuned on half of the NUS clips, scored on the other half)
RIM_MIN = 0.3
BALL_MIN = 0.25
BIB_MIN = 0.7
BIB_RUN = 3
UP_W = 4.0                  # up zone: within UP_W rim widths sideways ...
UP_H = 2.0                  # ... and up to UP_H rim heights (or 1.5 widths) above the rim
RIM_X = 0.5                 # crossing must land within RIM_X rim widths of the rim centre
RESOLVE_S = 2.5             # an attempt must resolve within this many seconds
BOUNCE_S = 0.0              # a "through" ball that rises back above the rim within this time is a miss (0 = off)
DROP_W = 0.0                # after crossing, the ball must fall this many rim widths below the rim (0 = off)
DROP_S = 0.8                # ... within this many seconds after the crossing
BIB_NEAR = 0.0              # ball-in-basket box must sit within this many rim widths of the rim (0 = off)
COOLDOWN_S = 1.0
# "needs a look" (does not change the call): on the NBA clips, through-rim makes
# where the ball sat near the rim a long time and crossed off-centre were wrong
# ~40% of the time vs ~10% for the rest (docs/SHOT_DETECTION_VALIDATION.md).
UNSURE_TRACK = 19
UNSURE_CROSS = 0.15

SHOT_ZH = {"jump": "跳投", "layup": "上篮/扣篮"}
OUTCOME_ZH = {"made": "进了", "missed": "没进", "unknown": ""}

_lock = threading.Lock()
_model: Any = None
_device = "cpu"


def available() -> bool:
    if not MODEL.is_file():
        return False
    try:
        import rfdetr  # noqa: F401
    except ImportError:
        return False
    return True


def download_model() -> Path:
    """Fetch the detector and verify its SHA-256 before it is ever loaded."""
    import urllib.request
    MODEL.parent.mkdir(parents=True, exist_ok=True)
    part = MODEL.with_suffix(".part")
    with urllib.request.urlopen(MODEL_URL, timeout=120) as res, part.open("wb") as out:
        while chunk := res.read(1 << 20):
            out.write(chunk)
    if hashlib.sha256(part.read_bytes()).hexdigest() != MODEL_SHA256:
        part.unlink(missing_ok=True)
        raise RuntimeError("detector checksum mismatch")
    os.replace(part, MODEL)
    return MODEL


def _load(device: str) -> Any:
    from rfdetr import from_checkpoint
    try:
        return from_checkpoint(str(MODEL), device=device)
    except TypeError:
        return from_checkpoint(str(MODEL))


def _get_model() -> Any:
    """GPU when it has room (other jobs often hold most of it), else CPU."""
    global _model, _device
    if _model is None:
        import torch
        device = "cpu"
        if torch.cuda.is_available():
            free, _ = torch.cuda.mem_get_info()
            device = "cuda" if free > 2.5 * 2**30 else "cpu"
        _device = device
        _model = _load(device)
    return _model


def _predict(frames: list[Any]) -> list[Any]:
    global _model, _device
    rgb = [cv2.cvtColor(f, cv2.COLOR_BGR2RGB) for f in frames]
    h, w = rgb[0].shape[:2]
    s = min(1.0, SHORT_SIDE / min(h, w), 1333 / max(h, w))
    shape = (max(32, int(h * s) // 32 * 32), max(32, int(w * s) // 32 * 32))
    model = _get_model()
    try:
        out = model.predict(rgb, threshold=0.15, shape=shape, include_source_image=False)
    except RuntimeError as exc:  # CUDA out of memory: another job took the GPU
        if _device != "cuda" or "out of memory" not in str(exc).lower():
            raise
        import torch
        torch.cuda.empty_cache()
        _device, _model = "cpu", _load("cpu")
        out = _model.predict(rgb, threshold=0.15, shape=shape, include_source_image=False)
    return out if isinstance(out, list) else [out]


def _jersey(frame: Any, x1: float, y1: float, x2: float, y2: float) -> list[float]:
    """Median Lab colour of the torso (upper-middle of the person box)."""
    h, w = frame.shape[:2]
    bw, bh = x2 - x1, y2 - y1
    a, b = int(max(0, y1 + 0.18 * bh)), int(min(h, y1 + 0.48 * bh))
    c, d = int(max(0, x1 + 0.3 * bw)), int(min(w, x2 - 0.3 * bw))
    if b - a < 2 or d - c < 2:
        return [0.0, 0.0, 0.0]
    lab = cv2.cvtColor(frame[a:b, c:d], cv2.COLOR_BGR2LAB).reshape(-1, 3)
    import numpy as np
    return [round(float(v), 1) for v in np.median(lab, axis=0)]


def _row(t: float, frame_index: int, det: Any, names: list[str], frame: Any = None) -> dict[str, Any]:
    row: dict[str, Any] = {"t": round(t, 3), "f": frame_index, **{k: [] for k in KEEP}}
    for cid, conf, (x1, y1, x2, y2) in zip(det.class_id, det.confidence, det.xyxy):
        name = names[int(cid)]
        if name in KEEP:
            if name in PEOPLE + ("referee",) and conf < PEOPLE_MIN:
                continue
            box = [round(float(conf), 3), round(float(x1), 1), round(float(y1), 1),
                   round(float(x2), 1), round(float(y2), 1)]
            if name in PEOPLE and frame is not None:
                box += _jersey(frame, float(x1), float(y1), float(x2), float(y2))
            row[name].append(box)
    return row


def _near_rim(row: dict[str, Any]) -> bool:
    rims = [b for b in row["rim"] if b[0] >= RIM_MIN]
    if any(b[0] >= 0.4 for b in row["ball-in-basket"]):
        return True
    for r in rims:
        cx, cy, w, h = _center(r)
        for b in row["ball"]:
            if b[0] >= BALL_MIN:
                bx, by, _, _ = _center(b)
                if abs(bx - cx) < 3 * w and cy - max(4 * h, 2.5 * w) < by < cy + 2 * h:
                    return True
    return False


# ---------- scan (cached) ----------
def _cache_path(video_id: str) -> Path:
    return CACHE / f"{video_id}_rows.json"


def scan(video_id: str, video: Path, fingerprint: str,
         progress: Callable[[int, int], None] | None = None) -> list[dict[str, Any]]:
    """Coarse pass everywhere, dense pass near the rim; rows sorted by time."""
    path = _cache_path(video_id)
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        if cached.get("version") == SCAN_VERSION and cached.get("fingerprint") == fingerprint:
            return cached["rows"]
    except (OSError, ValueError, KeyError):
        pass
    with _lock:
        started = time.perf_counter()
        names = list(_get_model().class_names)
        cap = cv2.VideoCapture(str(video))
        if not cap.isOpened():
            raise RuntimeError(f"cannot decode {video.name}")
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        step = max(1, round(fps / COARSE_FPS))
        rows: dict[int, dict[str, Any]] = {}
        batch: list[tuple[int, Any]] = []

        def flush() -> None:
            for (index, frame), det in zip(batch, _predict([f for _, f in batch])):
                rows[index] = _row(index / fps, index, det, names, frame)
            batch.clear()

        index = 0
        while cap.grab():
            if index % step == 0:
                ok, frame = cap.retrieve()
                if ok:
                    batch.append((index, frame))
                if len(batch) >= BATCH:
                    flush()
                    if progress:
                        progress(round(70 * index / max(1, total)), 100)
            index += 1
        if batch:
            flush()
        # dense windows around every coarse frame with the ball near the rim
        windows: list[list[int]] = []
        for i in sorted(rows):
            if _near_rim(rows[i]):
                a, b = max(0, i - round(DENSE_BEFORE * fps)), i + round(DENSE_AFTER * fps)
                if windows and a <= windows[-1][1]:
                    windows[-1][1] = max(windows[-1][1], b)
                else:
                    windows.append([a, b])
        dense_total = sum(b - a for a, b in windows) or 1
        done = 0
        for a, b in windows:
            cap.set(cv2.CAP_PROP_POS_FRAMES, a)
            for index in range(a, b + 1):
                ok, frame = cap.read()
                if not ok:
                    break
                if index not in rows:
                    batch.append((index, frame))
                if len(batch) >= BATCH:
                    flush()
            if batch:
                flush()
            done += b - a
            if progress:
                progress(70 + round(30 * done / dense_total), 100)
        cap.release()
    ordered = [rows[i] for i in sorted(rows)]
    CACHE.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(".part")
    part.write_text(json.dumps({"version": SCAN_VERSION, "fingerprint": fingerprint, "fps": fps, "device": _device,
                                "dense_windows": len(windows), "seconds": round(time.perf_counter() - started, 1),
                                "rows": ordered}), encoding="utf-8")
    os.replace(part, path)
    return ordered


# ---------- rules: rows -> shot events ----------
def _center(b: list[float]) -> tuple[float, float, float, float]:
    return ((b[1] + b[3]) / 2, (b[2] + b[4]) / 2, b[3] - b[1], b[4] - b[2])


def _track(rows: list[dict[str, Any]]) -> tuple[list[Any], list[tuple[int, float, float, float]]]:
    """Per-row locked hoop (cx, cy, w, h, t_seen) and the continuous ball path."""
    hoop: tuple | None = None
    hoops: list[Any] = []
    ball: tuple | None = None
    balls: list[tuple[int, float, float, float]] = []
    for k, r in enumerate(rows):
        t = r["t"]
        rims = [b for b in r["rim"] if b[0] >= RIM_MIN]
        if rims:
            c = _center(max(rims, key=lambda b: b[0]))
            jump = hoop is not None and t - hoop[4] < 0.2 and math.dist(c[:2], hoop[:2]) > 0.5 * math.hypot(hoop[2], hoop[3])
            if not jump:
                hoop = (*c, t)
        hoops.append(hoop if hoop is not None and t - hoop[4] <= 1.5 else None)
        cands = [_center(b) + (b[0],) for b in r["ball"] if b[0] >= BALL_MIN]
        if cands:
            c = (min(cands, key=lambda c: math.dist(c[:2], ball[:2])) if ball is not None and t - ball[5] < 1.0
                 else max(cands, key=lambda c: c[4]))
            ok = c[2] < 1.6 * c[3] and c[3] < 1.6 * c[2]
            if ok and ball is not None and t - ball[5] < 0.2 and math.dist(c[:2], ball[:2]) > 4 * math.hypot(ball[2], ball[3]):
                ok = False
            if ok:
                ball = (*c[:4], c[4], t)
                balls.append((k, t, c[0], c[1]))
    return hoops, balls


def _bib_runs(rows: list[dict[str, Any]], hoops: list[Any] | None = None) -> list[float]:
    """Start times of BIB_RUN+ consecutive ball-in-basket rows (optionally only at the locked rim)."""
    starts, run, first, last_t = [], 0, 0.0, -9.0
    for k, r in enumerate(rows):
        h = hoops[k] if hoops is not None and k < len(hoops) else None

        def at_rim(b: list[float]) -> bool:
            if not BIB_NEAR or h is None:
                return True
            cx, cy, _, _ = _center(b)
            return abs(cx - h[0]) < BIB_NEAR * h[2] and h[1] - BIB_NEAR * h[2] < cy < h[1] + 2 * BIB_NEAR * h[2]
        hit = any(b[0] >= BIB_MIN and at_rim(b) for b in r["ball-in-basket"])
        if hit and run and r["t"] - last_t <= 0.25:
            run += 1
        elif hit:
            run, first = 1, r["t"]
        else:
            run = 0
        if hit:
            last_t = r["t"]
        if run == BIB_RUN:
            starts.append(first)
    return starts


def _attempts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    hoops, balls = _track(rows)
    bibs = _bib_runs(rows, hoops)
    out: list[dict[str, Any]] = []
    active: dict[str, Any] | None = None
    for n, (k, t, x, y) in enumerate(balls):
        h = hoops[k]
        if active and t - active["t"] > RESOLVE_S:
            active = _close(active, rows, hoops, bibs, None)
            out.append(active)
            active = None
        if h is None:
            continue
        hx, hy, hw, hh, _ = h
        top, bottom = hy - 0.5 * hh, hy + 0.5 * hh
        in_up = abs(x - hx) < UP_W * hw and hy - max(UP_H * hh, 1.5 * hw) < y < top
        if active is None and in_up and (not out or t - out[-1]["end"] > COOLDOWN_S):
            active = {"t": t, "k": k, "first_ball": n, "hoop": h}
        if active and y > bottom and n > active["first_ball"]:
            above = max((j for j in range(active["first_ball"], n) if balls[j][3] < top), default=None)
            crossing = None
            if above is not None:
                (_, _, x1, y1), (_, _, x2, y2) = balls[above][:4], balls[above + 1][:4]
                crossing = x1 if y2 == y1 else x1 + (top - y1) * (x2 - x1) / (y2 - y1)
            made = crossing is not None and abs(crossing - hx) < RIM_X * hw
            fall = [b[3] for b in balls[n:] if b[1] - t <= 1.5]
            active["cross"] = None if crossing is None else round(abs(crossing - hx) / hw, 3)
            active["drop"] = round((max(fall, default=y) - bottom) / hw, 3)
            active["track"] = n - active["first_ball"] + 1
            if made and (BOUNCE_S or DROP_W):
                after = [b for b in balls[n:] if b[1] - t <= max(BOUNCE_S, DROP_S)]
                if BOUNCE_S and any(b[3] < top and b[1] - t <= BOUNCE_S for b in after[1:]):
                    made = False        # came back up: rattled out or passed in front of the rim
                if DROP_W and max((b[3] for b in after), default=y) < bottom + DROP_W * hw:
                    made = False        # never dropped clearly below the rim
            active = _close(active, rows, hoops, bibs, t, made)
            out.append(active)
            active = None
    if active:
        out.append(_close(active, rows, hoops, bibs, None))
    # a ball-in-basket run that no tracked attempt explains is still a make
    for b in bibs:
        if not any(a["start"] - 0.5 <= b <= a["end"] + 0.5 for a in out):
            out.append({"t": b - 0.8, "start": b - 0.8, "end": b + 0.4, "outcome": "made", "via": "ball_in_basket",
                        "kind": "jump", "hoop": None,
                        "evidence": {"cross": None, "drop": None, "track": 0, "bib": _bib_strength(rows, b - 0.3, b + 0.9)}})
    return sorted(out, key=lambda a: a["t"])


def _close(a: dict[str, Any], rows: list[dict[str, Any]], hoops: list[Any], bibs: list[float],
           end_t: float | None, crossed_in: bool = False) -> dict[str, Any]:
    t0 = a["t"]
    end = end_t if end_t is not None else t0 + RESOLVE_S
    bib = any(t0 - 0.3 <= b <= end + 0.5 for b in bibs)
    window = [h for r, h in zip(rows, hoops) if t0 <= r["t"] <= end]
    rim_seen = bool(window) and sum(h is not None for h in window) / len(window) >= 0.5
    if crossed_in or bib:
        outcome, via = "made", "ball_in_basket" if bib and not crossed_in else "through_rim"
    elif rim_seen:
        outcome, via = "missed", "rim_in_view"
    else:
        outcome, via = "unknown", "rim_not_visible"
    ev = {"cross": a.get("cross"), "drop": a.get("drop"), "track": a.get("track", 0),
          "bib": _bib_strength(rows, t0 - 0.3, end + 0.5)}
    return {"t": t0, "start": t0, "end": end, "outcome": outcome, "via": via,
            "kind": _kind(rows, a["k"], a["hoop"]), "hoop": a["hoop"], "evidence": ev}


def _bib_strength(rows: list[dict[str, Any]], t0: float, t1: float) -> float:
    """Sum of ball-in-basket confidences (>= 0.4) in a time window: 0 = never seen."""
    return round(sum(max((b[0] for b in r["ball-in-basket"] if b[0] >= 0.4), default=0.0)
                     for r in rows if t0 <= r["t"] <= t1), 3)


def _kind(rows: list[dict[str, Any]], k: int, hoop: tuple) -> str:
    """Layup if the shooter (scorer box) is within ~3 rim widths of the rim when the ball goes up."""
    hx, hy, hw, _, _ = hoop
    for r in rows[max(0, k - 15):k + 1]:
        for b in r["scorer"]:
            if b[0] >= 0.4:
                cx, _, _, _ = _center(b)
                if abs(cx - hx) < 3 * hw and b[2] < hy + 6 * hw:
                    return "layup"
    return "jump"


def uncertain(a: dict[str, Any]) -> bool:
    ev = a.get("evidence") or {}
    if a["outcome"] == "unknown":
        return False
    if a["via"] == "through_rim":
        return ev.get("track", 0) >= UNSURE_TRACK and (ev.get("cross") or 0) >= UNSURE_CROSS
    return False


def shot_range(rows: list[dict[str, Any]], a: dict[str, Any], before: float = 1.6) -> float | None:
    """Horizontal distance from shooter to rim, in rim widths (None if unseen)."""
    h = a.get("hoop")
    if not h:
        return None
    hx, hw = h[0], max(1e-6, h[2])
    for r in reversed([r for r in rows if a["t"] - before <= r["t"] <= a["t"]]):
        for role in ("scorer", "holder"):
            boxes = [b for b in r.get(role, []) if len(b) >= 5 and b[0] >= 0.4]
            if boxes:
                b = max(boxes, key=lambda b: b[0])
                return round(abs((b[1] + b[3]) / 2 - hx) / hw, 2)
    return None


def shot_events(video_id: str, rows: list[dict[str, Any]], video_path: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for a in _attempts(rows):
        outcome, kind = a["outcome"], a["kind"]
        start = max(0.0, a["start"] - 2.0)              # include the release and wind-up
        end = a["end"] + (1.5 if outcome == "made" else 1.0)
        score = {"made": 0.9, "missed": 0.55, "unknown": 0.5}[outcome]
        events.append({
            "event_id": f"shot-{video_id}-{round(a['t'] * 10):05d}",
            "source_video_id": video_id,
            "video_path": video_path,
            "event_type": "dunk" if kind == "layup" else "shot_attempt",
            "shot_kind": kind,
            "outcome": outcome,
            "action_label": "layup" if kind == "layup" else "jump-shot",
            "action_label_zh": SHOT_ZH[kind],
            "display_name": SHOT_ZH[kind] + (" · " + OUTCOME_ZH[outcome] if OUTCOME_ZH[outcome] else ""),
            "start_time": round(start, 2),
            "end_time": round(end, 2),
            "peak_time": round(a["t"], 2),
            "raw_model_score": score,
            "final_ranking_score": round(score + (0.35 if outcome == "made" else -0.1 if outcome == "missed" else 0.0), 3),
            "outcome_evidence": {"via": a["via"], **(a.get("evidence") or {})},
            "shot_range": shot_range(rows, a),
            "uncertain": uncertain(a),
            "source_model": "RF-DETR basketball detector (OpenHoopVision-core)",
            "evidence_source": "LOCAL_DETECTOR",
            "verification_status": "MODEL_PREDICTED",
            "semantic_limit": "Outcome is inferred from ball/rim tracking; 'unknown' means the rim was not visible enough to judge.",
        })
    return events


def summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    shots = [e for e in events if e.get("evidence_source") == "LOCAL_DETECTOR"]
    made = sum(e["outcome"] == "made" for e in shots)
    missed = sum(e["outcome"] == "missed" for e in shots)
    judged = made + missed
    return {"attempts": len(shots), "made": made, "missed": missed, "unknown": len(shots) - judged,
            "fg_pct": round(100 * made / judged) if judged else None,
            "jump": sum(e["shot_kind"] == "jump" for e in shots), "layup": sum(e["shot_kind"] == "layup" for e in shots)}
