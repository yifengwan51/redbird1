"""How exciting each play is: one score per event for "本场最佳" ranking.

The score never contradicts what the detector called and never changes which
plays a montage picks against the old ranking (made 1.25 > X3D <= 1 >
unknown 0.5 > missed 0.45): only made shots get a bonus, and it keeps them in
1.25..1.75, so only the order among made shots changes.  Other events keep
their score; their "highlight" signals are recorded for display only.

Signals inside a group (each 0..1, missing signals count as 0):
  crowd   - loudness rise just after the play over the seconds before it
            (cheers).  Audio is optional; clips without sound skip it.
  range   - how far from the rim the shot started (in rim widths).
  streak  - this team's / the game's run of consecutive makes.
  kind    - a layup / drive is a bit more exciting than a set shot.
Uncertain calls (shots.uncertain) never get a bonus: a doubtful make must not
headline the reel.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import numpy as np

AUDIO_RATE = 8000
HOP_S = 0.1
CROWD_BEFORE = (-4.0, -0.5)   # reference: the build-up before the shot
CROWD_AFTER = (0.3, 3.0)      # where cheers land
CROWD_ZERO_DB = 4.0           # a random moment rises ~4 dB (eval clips, median)
CROWD_FULL_DB = 10.0
RANGE_FULL = 6.0              # rim widths from the rim: a long shot
WEIGHTS = {"crowd": 0.35, "range": 0.3, "streak": 0.2, "kind": 0.15}
MADE_BASE = 1.25             # the old made score; X3D moments never exceed 1.0
SPAN = 0.5


def loudness(video: Path, ffmpeg: Path) -> np.ndarray | None:
    """dB loudness every HOP_S seconds, or None if the video has no sound."""
    try:
        raw = subprocess.run([str(ffmpeg), "-v", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", str(AUDIO_RATE),
                              "-f", "s16le", "-"], capture_output=True, timeout=300, check=False).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    x = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
    hop = int(AUDIO_RATE * HOP_S)
    if len(x) < hop * 20:
        return None
    frames = x[: len(x) // hop * hop].reshape(-1, hop)
    return 20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1e-5)


def crowd(db: np.ndarray | None, t: float) -> float:
    """Loudness rise just after the play over the few seconds before it (cheers)."""
    if db is None:
        return 0.0
    pre = db[max(0, int((t + CROWD_BEFORE[0]) / HOP_S)): max(0, int((t + CROWD_BEFORE[1]) / HOP_S))]
    post = db[max(0, int((t + CROWD_AFTER[0]) / HOP_S)): max(0, int((t + CROWD_AFTER[1]) / HOP_S))]
    if not len(pre) or not len(post):
        return 0.0
    rise = float(np.percentile(post, 90) - np.median(pre))
    return float(np.clip((rise - CROWD_ZERO_DB) / (CROWD_FULL_DB - CROWD_ZERO_DB), 0.0, 1.0))


def _group(e: dict[str, Any]) -> str:
    if e.get("evidence_source") != "LOCAL_DETECTOR":
        return "x3d"
    return e.get("outcome") if e.get("outcome") in ("made", "missed") else "unknown"


def score(events: list[dict[str, Any]], db: np.ndarray | None = None) -> list[dict[str, Any]]:
    """Adds "highlight" {score, signals} and sets final_ranking_score; returns the list."""
    run: dict[Any, int] = {}
    for e in sorted(events, key=lambda e: float(e.get("peak_time", e["start_time"]))):
        g = _group(e)
        t = float(e.get("peak_time", (float(e["start_time"]) + float(e["end_time"])) / 2))
        sig = {"crowd": round(crowd(db, t), 3), "range": 0.0, "streak": 0.0, "kind": 0.0}
        if g in ("made", "missed", "unknown"):
            sig["range"] = round(min(1.0, float(e.get("shot_range") or 0.0) / RANGE_FULL), 3)
            sig["kind"] = 1.0 if e.get("shot_kind") == "layup" else 0.0
            key = e.get("team")
            if g == "made":
                run[key] = run.get(key, 0) + 1
                sig["streak"] = round(min(1.0, (run[key] - 1) / 3), 3)
            elif g == "missed":
                run[key] = 0
        bonus = 0.0 if e.get("uncertain") else sum(WEIGHTS[k] * v for k, v in sig.items())
        old = float(e.get("final_ranking_score", e.get("raw_model_score", 0.0)) or 0.0)
        new = MADE_BASE + SPAN * bonus if g == "made" else old
        e["highlight"] = {"score": round(new, 3), "bonus": round(bonus, 3), "signals": sig}
        e["final_ranking_score"] = round(new, 3)
    return events
