"""User corrections of shot outcomes (复盘 one-tap 对/错).

The detector's own calls are never changed in its cache; a correction is a
small per-video overlay applied when events are read.  So a wrong tap can be
undone, and the overlay doubles as user-made labels for later evaluation.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "outputs" / "corrections"
OUTCOMES = ("made", "missed")
SHOT_ZH = {"jump": "跳投", "layup": "上篮/扣篮"}
OUTCOME_ZH = {"made": "进了", "missed": "没进", "unknown": ""}
_lock = threading.Lock()


def _path(video_id: str) -> Path:
    if not video_id.replace("_", "").replace("-", "").isalnum():
        raise ValueError("bad video id")
    return DIR / f"{video_id}.json"


def load(video_id: str) -> dict[str, dict[str, Any]]:
    try:
        data = json.loads(_path(video_id).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def set_outcome(video_id: str, event_id: str, outcome: str | None, original: str | None = None) -> dict[str, dict[str, Any]]:
    """outcome None removes the correction (back to the detector's call)."""
    if outcome is not None and outcome not in OUTCOMES:
        raise ValueError("outcome must be made or missed")
    with _lock:
        data = load(video_id)
        if outcome is None or outcome == original:
            data.pop(event_id, None)
        else:
            data[event_id] = {"outcome": outcome, "original": original, "at": int(time.time())}
        DIR.mkdir(parents=True, exist_ok=True)
        path = _path(video_id)
        part = path.with_suffix(".part")
        part.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(part, path)
        return data


def apply(video_id: str, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Copies of the events with user corrections applied (and confirmed calls marked)."""
    fixes = load(video_id)
    if not fixes:
        return events
    out = []
    for e in events:
        fix = fixes.get(e.get("event_id", ""))
        if fix and e.get("evidence_source") == "LOCAL_DETECTOR":
            e = dict(e)
            o, kind = fix["outcome"], e.get("shot_kind", "jump")
            delta = {"made": 0.35, "missed": -0.1}
            base = {"made": 0.9, "missed": 0.55}[o]
            e.update(outcome=o, uncertain=False, user_corrected=True, verification_status="USER_CONFIRMED",
                     display_name=SHOT_ZH.get(kind, "投篮") + " · " + OUTCOME_ZH[o],
                     raw_model_score=base, final_ranking_score=round(base + delta[o], 3))
        out.append(e)
    return out
