"""Local X3D candidate analysis and a deterministic, no-network MoTrack agent.

This module deliberately treats Kinetics-400 labels as *action evidence*, not as
ground truth for basketball outcomes.  It is an extension of HypeCut's existing
signals: low-rate whole-video windows prevent HypeCut-only blind spots, while
dense windows around HypeCut segments add temporal evidence where it matters.
"""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import tempfile
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import torch

from .security import session_directory

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "lightweight"
FFMPEG = ROOT / "tools" / "ffmpeg" / "bin" / "ffmpeg"
FFPROBE = ROOT / "tools" / "ffmpeg" / "bin" / "ffprobe"
TORCH_HOME = ROOT / ".cache" / "torch"
LABELS_PATH = ROOT / ".cache" / "lightweight" / "kinetics_classnames.json"
VIDEO_IDS = {
    "cbf": ROOT / "inputs" / "cbf_3x3_tour.mp4",
    "doug": ROOT / "inputs" / "doug_mcdermott.mp4",
}
HYPECUT = {
    "cbf": ROOT / "outputs" / "real" / "cbf" / "default.json",
    "doug": ROOT / "outputs" / "real" / "doug" / "default.json",
}
HYPECUT_FALLBACK_DIRS = {
    "cbf": ROOT / "outputs" / "real" / "cbf",
    "doug": ROOT / "outputs" / "real" / "doug",
}
EVENT_TYPES = {"shot_attempt", "made_basket", "missed_shot", "pass", "rebound", "steal", "fast_break", "UNKNOWN", "basketball_action_candidate", "dunk", "dribble"}
ALIASES = {"shot": "shot_attempt", "shoot": "shot_attempt", "投篮": "shot_attempt", "出手": "shot_attempt", "命中": "made_basket", "得分": "made_basket", "扣篮": "dunk", "灌篮": "dunk"}
ANALYSIS_VERSION = "2.1"
SHOT_LIKE_TYPES = {"shot_attempt", "dunk"}
BASKETBALL_LABELS = {
    "dunking basketball": ("dunk", "扣篮动作"),
    "shooting basketball": ("shot_attempt", "投篮动作"),
    "dribbling basketball": ("dribble", "运球动作"),
    "playing basketball": ("basketball_action_candidate", "篮球动作"),
}
EVENT_TYPE_ZH = {
    "shot_attempt": "疑似投篮",
    "dunk": "疑似扣篮",
    "dribble": "运球动作",
    "basketball_action_candidate": "篮球动作",
    "made_basket": "疑似得分",
    "missed_shot": "疑似未进",
    "pass": "传球",
    "rebound": "篮板",
    "steal": "抢断",
    "fast_break": "快攻",
    "hypecut_candidate": "HypeCut 信号片段",
    "UNKNOWN": "未知动作",
}

# ---------- editing language / renderer ----------
# The local agent is also a tiny deterministic editor.  These presets keep the
# result readable: a tight reel uses more cuts, a relaxed reel lets a play
# breathe.  They are intentionally exposed in the UI so users can see exactly
# what the machine is doing.
PACE_PRESETS = {
    "tight": {"segment": 2.6, "min": 1.6, "max": 3.4, "pre": 1.1, "post": 1.2, "max_clips": 14},
    "standard": {"segment": 3.9, "min": 2.6, "max": 5.2, "pre": 1.6, "post": 1.9, "max_clips": 10},
    "relaxed": {"segment": 5.8, "min": 4.0, "max": 7.6, "pre": 2.3, "post": 2.6, "max_clips": 7},
}
PACE_ZH = {"tight": "紧凑快剪", "standard": "标准节奏", "relaxed": "舒缓沉浸"}
TRANSITION_ZH = {"fade": "淡入淡出", "cut": "硬切直出"}
REPLAY_SPEED = 0.55
REPLAY_MAX_SOURCE = 2.5
FONT_CJK = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc")
FONT_LATIN = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")


def normalize_edit_style(value: Any = None) -> dict[str, Any]:
    """Return a validated editing style, accepting dicts or short strings."""
    style = {"pace": "standard", "transition": "fade", "captions": True, "slow_motion": False}
    if isinstance(value, str):
        low = value.strip().lower()
        if any(word in low for word in ("紧凑", "快剪", "快节奏", "tight")):
            style["pace"] = "tight"
        elif any(word in low for word in ("舒缓", "慢节奏", "沉浸", "relaxed")):
            style["pace"] = "relaxed"
        if any(word in low for word in ("硬切", "直切", "cut")):
            style["transition"] = "cut"
        if any(word in low for word in ("无字幕", "不要字幕", "no caption")):
            style["captions"] = False
        if any(word in low for word in ("慢放", "慢动作", "回放", "slow")):
            style["slow_motion"] = True
        return style
    if isinstance(value, dict):
        pace = str(value.get("pace", style["pace"])).lower()
        if pace in PACE_PRESETS:
            style["pace"] = pace
        transition = str(value.get("transition", style["transition"])).lower()
        if transition in TRANSITION_ZH:
            style["transition"] = transition
        for key in ("captions", "slow_motion"):
            if key in value:
                raw = value[key]
                if isinstance(raw, str):
                    style[key] = raw.strip().lower() in {"1", "true", "yes", "on", "是"}
                else:
                    style[key] = bool(raw)
    return style


def edit_style_from_text(text: str, base: dict[str, Any] | None = None) -> dict[str, Any]:
    style = normalize_edit_style(base)
    low = (text or "").lower()
    if any(word in low for word in ("紧凑", "快剪", "快节奏", "利落")):
        style["pace"] = "tight"
    elif any(word in low for word in ("舒缓", "慢节奏", "沉浸", "呼吸感")):
        style["pace"] = "relaxed"
    if any(word in low for word in ("硬切", "直切", "不要转场", "无转场")):
        style["transition"] = "cut"
    elif any(word in low for word in ("淡入淡出", "黑场", "转场")):
        style["transition"] = "fade"
    if any(word in low for word in ("不要字幕", "无字幕", "去掉字幕", "关闭字幕")):
        style["captions"] = False
    elif any(word in low for word in ("字幕", "标注", "说明文字")):
        style["captions"] = True
    if any(word in low for word in ("慢放", "慢动作", "回放", "slow motion")):
        style["slow_motion"] = True
    elif any(word in low for word in ("不要慢放", "关闭慢放", "正常速度")):
        style["slow_motion"] = False
    return style


def duration_meta(requested: float, source_duration: float) -> dict[str, Any]:
    """Explain the physical limit instead of silently returning the wrong length."""
    requested = max(0.0, float(requested))
    source_duration = max(0.0, float(source_duration))
    effective = min(requested, source_duration) if source_duration else requested
    effective = max(5.0, effective) if effective else effective
    clamped = source_duration > 0 and requested > source_duration + 0.05
    if clamped:
        note = (
            f"原片只有 {source_duration:.1f} 秒，无法生成 {requested:g} 秒；"
            f"已按全片时长生成 {effective:.1f} 秒的精华版。"
        )
    else:
        note = ""
    return {
        "requested_duration": round(requested, 3),
        "effective_duration": round(effective, 3),
        "source_duration": round(source_duration, 3),
        "duration_clamped": clamped,
        "duration_note": note,
    }


def _score_of(item: dict[str, Any]) -> float:
    for key in ("final_ranking_score", "raw_model_score", "ranking_score", "hypecut_score", "confidence"):
        value = item.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return 0.0


def _center_of(item: dict[str, Any]) -> float:
    return (float(item["start_time"]) + float(item["end_time"])) / 2.0


def _dedupe_events(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse near-duplicate scan windows, keeping the strongest evidence."""
    kept: list[dict[str, Any]] = []
    for item in sorted(items, key=lambda x: (float(x["start_time"]), -_score_of(x))):
        if kept and float(item["start_time"]) <= float(kept[-1]["end_time"]) + 0.25:
            if _score_of(item) > _score_of(kept[-1]):
                kept[-1] = item
            continue
        kept.append(dict(item))
    return kept


def _select_for_montage(items: list[dict[str, Any]], count: int, target: float) -> list[dict[str, Any]]:
    if not items:
        return []
    unique = _dedupe_events(items)
    min_gap = max(1.6, (target / max(1, count)) * 0.65)
    chosen: list[dict[str, Any]] = []
    for item in sorted(unique, key=_score_of, reverse=True):
        if any(abs(_center_of(item) - _center_of(other)) < min_gap for other in chosen):
            continue
        chosen.append(item)
        if len(chosen) >= count:
            break
    if not chosen:
        chosen = [max(unique, key=_score_of)]
    return sorted(chosen, key=lambda x: float(x["start_time"]))


def _waterfill(caps: list[float], target: float) -> list[float]:
    """Split ``target`` across clips without ever exceeding a clip's cap."""
    target = max(0.0, float(target))
    allocs = [0.0] * len(caps)
    remaining = list(range(len(caps)))
    left = target
    while remaining and left > 1e-6:
        share = left / len(remaining)
        capped = [i for i in remaining if caps[i] <= share + 1e-6]
        if not capped:
            for i in remaining:
                allocs[i] = share
            left = 0.0
            break
        for i in capped:
            allocs[i] = max(0.0, caps[i])
            left -= allocs[i]
            remaining.remove(i)
        left = max(0.0, left)
    # Floating-point residue belongs to the strongest (first) uncapped clip.
    diff = target - sum(allocs)
    if abs(diff) > 1e-9 and allocs:
        index = max(range(len(allocs)), key=lambda i: caps[i] - allocs[i])
        allocs[index] = max(0.0, min(caps[index], allocs[index] + diff))
    return allocs


def _expand_windows(windows: list[list[float]], limits: list[tuple[float, float]], target: float) -> None:
    """Grow context windows into unused source until they can hold ``target``."""
    deficit = target - sum(hi - lo for lo, hi in windows)
    if deficit <= 1e-6:
        return
    guard = 0
    while deficit > 1e-6 and guard < 40:
        guard += 1
        moved = 0.0
        for i, (lo, hi) in enumerate(windows):
            cap_left = max(0.0, lo - limits[i][0])
            cap_right = max(0.0, limits[i][1] - hi)
            capacity = cap_left + cap_right
            if capacity <= 1e-9:
                continue
            take = min(deficit - moved, capacity)
            if take <= 1e-9:
                continue
            total = cap_left + cap_right
            add_left = take * (cap_left / total) if total else 0.0
            add_right = take - add_left
            windows[i][0] = lo - add_left
            windows[i][1] = min(limits[i][1], hi + add_right)
            moved += take
        if moved <= 1e-6:
            break
        deficit -= moved


def build_montage(
    items: list[dict[str, Any]],
    target: float,
    source_duration: float,
    style: dict[str, Any] | None = None,
    max_clips: int | None = None,
) -> list[dict[str, Any]]:
    """Turn ranked candidates into a timed, non-overlapping highlight montage.

    Every returned segment has ``start_time``/``end_time`` (source seconds),
    ``output_duration`` (seconds in the final MP4) and an optional ``speed``.
    The sum of output durations is exactly ``target`` (minus floating noise).
    """
    style = normalize_edit_style(style)
    cfg = PACE_PRESETS[style["pace"]]
    target = max(0.1, min(float(target), max(0.1, float(source_duration))))
    limit = int(max_clips or cfg["max_clips"])
    desired = max(1, min(limit, round(target / cfg["segment"])))
    chosen = _select_for_montage(items, desired, target)
    if not chosen:
        return []

    # Chronological boundaries give each play its own slice of the source.
    centers = [_center_of(item) for item in chosen]
    limits: list[tuple[float, float]] = []
    for index in range(len(chosen)):
        left = 0.0 if index == 0 else (centers[index - 1] + centers[index]) / 2.0
        right = source_duration if index == len(chosen) - 1 else (centers[index] + centers[index + 1]) / 2.0
        limits.append((max(0.0, left), min(source_duration, right)))

    windows: list[list[float]] = []
    for index, item in enumerate(chosen):
        left, right = limits[index]
        lo = max(left, float(item["start_time"]) - cfg["pre"])
        hi = min(right, float(item["end_time"]) + cfg["post"])
        if hi - lo < cfg["min"]:
            mid = (lo + hi) / 2.0
            lo = max(left, mid - cfg["min"] / 2.0)
            hi = min(right, lo + cfg["min"])
            lo = max(left, hi - cfg["min"])
        windows.append([lo, hi])
    _expand_windows(windows, limits, target)

    # Optional slow-motion replay of the strongest play.  It deliberately
    # reuses a short source window, exactly like a broadcast replay.
    replay: dict[str, Any] | None = None
    replay_output = 0.0
    if style["slow_motion"] and target >= 9.0:
        anchor = max(chosen, key=_score_of)
        anchor_window = windows[chosen.index(anchor)]
        span = min(REPLAY_MAX_SOURCE, anchor_window[1] - anchor_window[0])
        if span >= 1.2:
            center = min(max(_center_of(anchor), anchor_window[0] + span / 2.0), anchor_window[1] - span / 2.0)
            replay = {
                "start_time": round(center - span / 2.0, 3),
                "end_time": round(center + span / 2.0, 3),
                "speed": REPLAY_SPEED,
                "output_duration": round(span / REPLAY_SPEED, 3),
                "replay": True,
                "anchor_event_id": anchor.get("event_id"),
                "label": "慢放回看 · " + (anchor.get("display_name") or EVENT_TYPE_ZH.get(anchor.get("event_type", ""), "精彩动作")),
                "event_type": anchor.get("event_type", "basketball_action_candidate"),
                "raw_model_score": _score_of(anchor),
            }
            replay_output = float(replay["output_duration"])
            # Replays are precious but should never crowd out the actual plays.
            if target - replay_output < len(chosen) * 1.2:
                replay = None
                replay_output = 0.0

    content_target = max(0.0, target - replay_output)
    caps = [max(0.1, hi - lo) for lo, hi in windows]
    allocs = _waterfill(caps, content_target)
    if allocs:
        allocs[-1] = max(0.0, allocs[-1] + (content_target - sum(allocs)))

    segments: list[dict[str, Any]] = []
    for index, item in enumerate(chosen):
        lo, hi = windows[index]
        out = max(0.2, min(float(allocs[index]), hi - lo))
        center = min(max(_center_of(item), lo + out / 2.0), hi - out / 2.0)
        start = round(center - out / 2.0, 3)
        end = round(start + out, 3)
        if end > source_duration:
            end = round(source_duration, 3)
            start = round(max(lo, end - out), 3)
        segments.append({
            "event_id": item.get("event_id"),
            "start_time": start,
            "end_time": end,
            "output_duration": round(end - start, 3),
            "speed": 1.0,
            "replay": False,
            "event_type": item.get("event_type", "basketball_action_candidate"),
            "display_name": item.get("display_name") or EVENT_TYPE_ZH.get(item.get("event_type", ""), "篮球动作"),
            "action_label_zh": item.get("action_label_zh"),
            "raw_model_score": _score_of(item),
            "verification_status": item.get("verification_status", "MODEL_PREDICTED"),
        })

    if replay:
        # Insert the replay straight after the play it revisits.
        anchor_id = replay.get("anchor_event_id")
        insert_at = next((i + 1 for i, seg in enumerate(segments) if seg.get("event_id") == anchor_id), len(segments))
        segments.insert(insert_at, replay)

    # Make the output exactly match the requested duration, even after rounding.
    diff = target - sum(float(seg["output_duration"]) for seg in segments)
    if abs(diff) > 1e-6 and segments:
        candidates = [i for i, seg in enumerate(segments) if not seg.get("replay")] or list(range(len(segments)))
        index = candidates[-1]
        seg = segments[index]
        new_out = max(0.2, float(seg["output_duration"]) + diff)
        seg["output_duration"] = round(new_out, 3)
        if not seg.get("replay"):
            seg["end_time"] = round(min(source_duration, float(seg["start_time"]) + new_out), 3)
    return segments


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _json(path: Path, default: Any) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default


def _fingerprint(video: Path) -> str:
    """Cheap content identity check so replaced source videos invalidate caches."""
    stat = video.stat()
    return f"{stat.st_size}:{stat.st_mtime_ns}"


def _video_info(video: Path) -> dict[str, Any]:
    raw = subprocess.check_output([str(FFPROBE), "-v", "error", "-show_entries", "format=duration:stream=codec_type,r_frame_rate", "-of", "json", str(video)], text=True, timeout=30)
    data = json.loads(raw)
    duration = float(data["format"]["duration"])
    return {"duration": duration, "streams": data.get("streams", []), "probe": data}


class X3D:
    """Official PyTorchVideo Hub X3D-XS, cached strictly inside this project."""
    def __init__(self) -> None:
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.labels = {int(v): k.strip('"') for k, v in _json(LABELS_PATH, {}).items()}
        if not self.labels:
            raise RuntimeError("missing official Kinetics label cache")
        os.environ["TORCH_HOME"] = str(TORCH_HOME)
        before = torch.cuda.memory_allocated() if self.device.type == "cuda" else 0
        started = time.perf_counter()
        # skip_validation avoids GitHub API credentials; Hub source and checkpoint
        # are already downloaded from their official URLs into project cache.
        self.model = torch.hub.load("facebookresearch/pytorchvideo", "x3d_xs", pretrained=True, trust_repo=True, skip_validation=True).eval().to(self.device)
        self.load_seconds = round(time.perf_counter() - started, 3)
        self.memory_bytes = int(torch.cuda.memory_allocated() - before) if self.device.type == "cuda" else 0

    def _input(self, frames: list[np.ndarray]) -> torch.Tensor:
        # Hub documentation for X3D-XS: 4 frames x sample rate 12, crop 182.
        tensor = torch.from_numpy(np.stack([cv2.cvtColor(x, cv2.COLOR_BGR2RGB) for x in frames])).permute(3, 0, 1, 2).float() / 255.0
        tensor = (tensor - torch.tensor([0.45, 0.45, 0.45])[:, None, None, None]) / torch.tensor([0.225, 0.225, 0.225])[:, None, None, None]
        # Resize short side to 182 then center crop: no torchvision-video API
        # dependency, and exactly the documented X3D spatial preprocessing.
        _, _, h, w = tensor.shape
        scale = 182 / min(h, w)
        tensor = torch.nn.functional.interpolate(tensor.permute(1, 0, 2, 3), size=(round(h * scale), round(w * scale)), mode="bilinear", align_corners=False).permute(1, 0, 2, 3)
        _, _, h, w = tensor.shape
        y, x = (h - 182) // 2, (w - 182) // 2
        return tensor[:, :, y:y + 182, x:x + 182].unsqueeze(0).to(self.device)

    def classify_detailed(self, frames: list[np.ndarray]) -> dict[str, Any]:
        tensor = self._input(frames)
        with torch.inference_mode():
            logits = self.model(tensor)[0]
            scores = torch.softmax(logits, dim=0)
        values, indices = scores.topk(5)
        top5 = [{"label": self.labels.get(int(i), f"class_{int(i)}"), "class_id": int(i),
                 "logit": round(float(logits[int(i)]), 6), "softmax_score": round(float(v), 6)}
                for v, i in zip(values.detach().cpu(), indices.detach().cpu())]
        return {"top5": top5, "input_shape": list(tensor.shape), "score_type": "softmax(logits)"}

    def classify(self, frames: list[np.ndarray]) -> list[dict[str, Any]]:
        """V1 compatibility: retain its legacy field while V2 uses detailed audit."""
        return [{"label": x["label"], "class_id": x["class_id"], "raw_model_score": x["softmax_score"]}
                for x in self.classify_detailed(frames)["top5"]]


def _frames(video: Path, start: float, duration: float = 1.6) -> tuple[list[np.ndarray], list[float]]:
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise RuntimeError(f"cannot decode {video.name}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frames, times = [], []
    for offset in (0.0, duration / 3, duration * 2 / 3, duration):
        t = start + offset
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        if not ok:
            continue
        frames.append(frame)
        times.append(round(t, 3))
    cap.release()
    if len(frames) != 4:
        raise RuntimeError("insufficient decodable frames for X3D window")
    return frames, times


def _hype_segments(video_id: str) -> list[dict[str, Any]]:
    """Return the primary HypeCut candidate segments for a video.

    ``default.json`` is the plan produced by the normal baseline flow.  Older
    checkouts only had profile-specific files (e.g. ``sports-broadcast.json``),
    so fall back to the richest available profile instead of silently returning
    an empty HypeCut-only timeline.
    """
    primary = _json(HYPECUT[video_id], {})
    segments = primary.get("segments") if isinstance(primary, dict) else None
    if isinstance(segments, list) and segments:
        return segments
    best: list[dict[str, Any]] = []
    directory = HYPECUT_FALLBACK_DIRS[video_id]
    if directory.is_dir():
        for path in sorted(directory.glob("*.json")):
            data = _json(path, {})
            candidate = data.get("segments") if isinstance(data, dict) else None
            if isinstance(candidate, list) and len(candidate) > len(best):
                best = candidate
    return best


def _windows(video_id: str, duration: float) -> list[tuple[float, str, dict[str, Any] | None]]:
    # 4 s global cadence, augmented at 2 s cadence near HypeCut candidates.
    # Four-second sampling keeps the local scan affordable while giving the
    # editor enough temporal candidates to fill a 20-second request.
    merged: dict[int, tuple[float, str, dict[str, Any] | None]] = {}
    global_times = list(np.arange(0.0, max(0.1, duration - 1.7), 4.0))
    if duration > 1.7:
        global_times.append(max(0.0, duration - 1.7))
    for t in global_times:
        merged[round(float(t) * 10)] = (float(t), "full_video_low_frequency", None)
    for segment in _hype_segments(video_id):
        for t in np.arange(float(segment["start"]), float(segment["end"]), 2.0):
            key = round(float(t) * 10)
            merged[key] = (float(t), "hypecut_dense", segment)
    return [merged[k] for k in sorted(merged)]


def _event_from_window(video_id: str, start: float, times: list[float], top: list[dict[str, Any]], source: str, segment: dict[str, Any] | None) -> dict[str, Any] | None:
    # Rank only the four Kinetics basketball classes.  The previous version
    # always ranked a low-confidence "shooting basketball" score even when the
    # strongest basketball evidence was a dunk, which made the highlight
    # ranking look almost random.  The chosen class is still model evidence,
    # never a made/missed-basket conclusion.
    basketball = [x for x in top if x["label"] in BASKETBALL_LABELS]
    if not basketball:
        return None
    primary = max(basketball, key=lambda x: float(x["raw_model_score"]))
    event_type, label_zh = BASKETBALL_LABELS[primary["label"]]
    signals = {x["label"]: round(float(x["raw_model_score"]), 6) for x in basketball}
    return {
        "event_id": f"lw-{video_id}-{round(start * 10):05d}",
        "source_video_id": video_id,
        "video_path": str(VIDEO_IDS[video_id].relative_to(ROOT)),
        "event_type": event_type,
        "action_label": primary["label"],
        "action_label_zh": label_zh,
        "display_name": EVENT_TYPE_ZH.get(event_type, label_zh),
        "start_time": round(times[0], 3),
        "end_time": round(times[-1], 3),
        "raw_model_score": primary["raw_model_score"],
        "basketball_signals": signals,
        "score_kind": "Kinetics-400 softmax; not a calibrated basketball-event probability",
        "source_model": "PyTorchVideo X3D-XS (Kinetics-400)",
        "model_version": "pytorchvideo hub main / X3D_XS.pyth",
        "visual_action_evidence": {"top5": top, "matched_label": primary["label"], "frame_timestamps": times},
        "hypecut_signal": {"sampling": source, "segment_score": segment.get("score") if segment else None, "reasons": segment.get("reasons") if segment else {}},
        "evidence_source": "LOCAL_X3D",
        "verification_status": "MODEL_PREDICTED",
        "semantic_limit": "Generic Kinetics action evidence only; this does not verify a made/missed basket, steal, rebound, player, team, or possession.",
        "time_localization_method": "1.6s X3D sample window",
    }


def _merge(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for event in sorted(events, key=lambda x: (x["start_time"], -x["raw_model_score"])):
        if result and event["event_type"] == result[-1]["event_type"] and event["start_time"] - result[-1]["end_time"] <= 2.0:
            if event["raw_model_score"] > result[-1]["raw_model_score"]:
                result[-1] = event
            continue
        result.append(event)
    return result


def analyze(video_id: str, force: bool = False) -> dict[str, Any]:
    if video_id not in VIDEO_IDS:
        raise ValueError("unknown video id")
    latest = OUT / f"latest_{video_id}.json"
    video = VIDEO_IDS[video_id]
    fingerprint = _fingerprint(video)
    if latest.exists() and not force:
        cached = _json(latest, {})
        # A cache is reusable only when it was produced by the current analysis
        # pipeline and the source file has not changed.  Legacy caches without
        # a version are intentionally re-analysed so users see the improved
        # basketball-class ranking instead of stale, misleading candidates.
        if cached.get("analysis_version") == ANALYSIS_VERSION and cached.get("source_fingerprint") == fingerprint:
            return cached
    OUT.mkdir(parents=True, exist_ok=True)
    info = _video_info(video)
    started = time.perf_counter()
    runner = X3D()
    raw, failures = [], []
    for start, sampling, segment in _windows(video_id, info["duration"]):
        try:
            frames, times = _frames(video, start)
            top = runner.classify(frames)
            event = _event_from_window(video_id, start, times, top, sampling, segment)
            if event:
                raw.append(event)
        except Exception as exc:
            failures.append({"start_time": start, "error": type(exc).__name__})
    elapsed = time.perf_counter() - started
    events = _merge(raw)
    payload = {
        "schema_version": "1.1", "analysis_version": ANALYSIS_VERSION, "run_id": f"lw-{video_id}-{_now()}", "source_video_id": video_id,
        "source_video": str(video.relative_to(ROOT)), "source_fingerprint": fingerprint, "events": events,
        "event_summary": {kind: sum(1 for event in events if event["event_type"] == kind) for kind in sorted({event["event_type"] for event in events})},
        "hypecut_only_baseline": {"candidate_count": len(_hype_segments(video_id)), "segments": _hype_segments(video_id)},
        "performance": {"device": str(runner.device), "model_load_seconds": runner.load_seconds, "gpu_memory_model_bytes": runner.memory_bytes,
                        "inference_total_seconds": round(elapsed, 3), "seconds_per_video_minute": round(elapsed / (info["duration"] / 60), 3),
                        "windows": len(_windows(video_id, info["duration"])), "raw_candidates": len(raw), "merged_candidates": len(events), "failures": failures},
        "limitations": "No human ground truth was used: Precision/Recall/F1 are UNVERIFIED.",
    }
    stamped = OUT / f"{payload['run_id']}.json"
    stamped.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    latest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def events(video_id: str, analyze_if_missing: bool = False) -> list[dict[str, Any]]:
    if video_id not in VIDEO_IDS:
        raise ValueError("unknown video id")
    latest = OUT / f"latest_{video_id}.json"
    cached = _json(latest, None)
    if cached is None:
        return analyze(video_id).get("events", []) if analyze_if_missing else []
    fingerprint = cached.get("source_fingerprint")
    stale = cached.get("analysis_version") != ANALYSIS_VERSION or (fingerprint and fingerprint != _fingerprint(VIDEO_IDS[video_id]))
    if stale:
        return analyze(video_id, force=True).get("events", []) if analyze_if_missing else []
    return cached.get("events", [])


def render_plan(video_id: str, plan: dict[str, Any], destination: Path) -> dict[str, Any]:
    clips = plan.get("clips", [])
    if not clips:
        raise ValueError("empty highlight plan")
    duration = _video_info(VIDEO_IDS[video_id])["duration"]
    for clip in clips:
        # Clamp model-generated context to the real source length.  A candidate
        # at the very end of the video otherwise gets ``end + 2s`` and fails
        # validation, which previously broke HypeCut-only on short clips.
        start_time = max(0.0, min(float(clip["start_time"]), duration - 0.1))
        end_time = min(duration, max(start_time + 0.1, float(clip["end_time"])))
        clip["start_time"], clip["end_time"] = round(start_time, 3), round(end_time, 3)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # A single timeline span preserves audio/video sync and avoids custom FFmpeg logic.
    start = min(float(x["start_time"]) for x in clips)
    end = max(float(x["end_time"]) for x in clips)
    requested = float(plan.get("target_duration", end - start))
    target = max(0.1, min(requested, duration))
    # Honour the user's requested duration when the source is long enough.
    # Previously this was clamped to the selected clips' span, so asking for
    # 20 s could return only a 10 s file.
    if end - start < target:
        new_end = min(duration, start + target)
        if new_end - start < target:
            start = max(0.0, new_end - target)
        end = new_end
    else:
        end = start + target
    began = time.perf_counter()
    subprocess.run([str(FFMPEG), "-y", "-v", "error", "-ss", str(start), "-to", str(end), "-i", str(VIDEO_IDS[video_id]),
                    "-map", "0:v:0", "-map", "0:a?", "-c:v", "libx264", "-c:a", "aac", "-movflags", "+faststart", str(destination)],
                   check=True, timeout=600)
    probe = json.loads(subprocess.check_output([str(FFPROBE), "-v", "error", "-show_entries", "format=duration:stream=codec_type,codec_name", "-of", "json", str(destination)], text=True, timeout=30))
    return {"path": str(destination.relative_to(ROOT)), "start": round(start, 3), "end": round(end, 3),
            "requested_duration": round(requested, 3),
            "duration": float(probe["format"]["duration"]), "probe": probe, "render_seconds": round(time.perf_counter() - began, 3)}


def _clip_span(clips: list[dict[str, Any]]) -> float:
    if not clips:
        return 0.0
    return max(float(x["end_time"]) for x in clips) - min(float(x["start_time"]) for x in clips)


def fit_clips_to_target(clips: list[dict[str, Any]], target: float, score_key: str = "raw_model_score") -> list[dict[str, Any]]:
    """Drop the weakest clips until the continuous span fits ``target``.

    The renderer only renders one continuous source span.  Without this step a
    plan could list clips that are not actually present in the MP4.  The
    highest-scoring clip is always kept; if a single clip is longer than the
    target its end is clamped.
    """
    target = max(0.1, float(target))
    kept = sorted((dict(x) for x in clips), key=lambda x: float(x["start_time"]))
    if not kept:
        return kept
    while len(kept) > 1 and _clip_span(kept) > target:
        # Remove the lowest-scored clip, preferring one that is not the anchor.
        weakest = min(range(len(kept)), key=lambda i: float(kept[i].get(score_key, kept[i].get("ranking_score", 0.0)) or 0.0))
        kept.pop(weakest)
    kept.sort(key=lambda x: float(x["start_time"]))
    if _clip_span(kept) > target:
        first = kept[0]
        first["end_time"] = min(float(first["end_time"]), float(first["start_time"]) + target)
    return kept


@dataclass
class LightweightSession:
    video_id: str = "cbf"
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    candidate_version: str = "v1"
    plan: dict[str, Any] | None = None
    traces: list[dict[str, Any]] = field(default_factory=list)
    state: str = "INTENT_PARSED"
    output_dir: Path = field(init=False)
    video_duration: float = field(init=False, default=0.0)

    def __post_init__(self) -> None:
        if self.video_id not in VIDEO_IDS:
            raise ValueError("unknown video id")
        if self.candidate_version not in {"v1", "v2", "hypecut"}:
            raise ValueError("unsupported candidate version")
        self.session_id = str(self.session_id)
        self.output_dir = session_directory(ROOT, ROOT / "outputs" / "lightweight_agent", self.session_id)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        try:
            self.video_duration = float(_video_info(VIDEO_IDS[self.video_id])["duration"])
        except Exception:
            self.video_duration = 0.0

    def _trace(self, tool: str, result: Any) -> None:
        self.traces.append({"initiator": "CONTROLLER", "tool": tool, "result": result, "state": self.state})

    def _events(self) -> list[dict[str, Any]]:
        if self.candidate_version == "v1":
            return events(self.video_id, analyze_if_missing=True)
        from integrations.lightweight_v2 import candidates_for_variant
        return candidates_for_variant(self.video_id, self.candidate_version)

    @staticmethod
    def _score(item: dict[str, Any]) -> float:
        return float(item.get("final_ranking_score", item.get("raw_model_score", 0.0)))

    def _make_plan(self, selected: list[dict[str, Any]], target: float = 20.0, max_clips: int = 3) -> dict[str, Any]:
        if not selected:
            raise ValueError("没有满足条件的本地动作候选")
        target = max(5.0, min(60.0, float(target)))
        # Build coherent clusters first.  A highlight is rendered as one
        # continuous source window, so mixing an event at 20s with one at 140s
        # would include over two minutes of unrelated footage.  Ranking a
        # cluster by its strongest candidates keeps the output watchable.
        ordered = sorted(selected, key=lambda x: float(x["start_time"]))
        clusters: list[list[dict[str, Any]]] = []
        gap_limit = max(5.0, target * 0.5)
        for item in ordered:
            if clusters and float(item["start_time"]) - float(clusters[-1][-1]["end_time"]) <= gap_limit:
                clusters[-1].append(item)
            else:
                clusters.append([item])
        def cluster_score(cluster: list[dict[str, Any]]) -> float:
            scores = sorted((self._score(x) for x in cluster), reverse=True)[:3]
            return scores[0] + 0.35 * sum(scores[1:])
        best = max(clusters, key=cluster_score)
        # Greedily add the strongest candidates that still fit one continuous
        # window (including 2s context on each side).
        chosen: list[dict[str, Any]] = []
        for item in sorted(best, key=self._score, reverse=True):
            trial = chosen + [item]
            span = (max(float(x["end_time"]) for x in trial) + 2.0) - (min(float(x["start_time"]) for x in trial) - 2.0)
            if not chosen or span <= target:
                chosen = trial
            if len(chosen) >= max(1, min(max_clips, 8)):
                break
        chosen.sort(key=lambda x: float(x["start_time"]))
        clips = []
        source_end = self.video_duration or (max(float(x["end_time"]) for x in chosen) + 2.0)
        for item in chosen:
            start = max(0.0, float(item["start_time"]) - 2.0)
            end = min(source_end, float(item["end_time"]) + 2.0)
            if end - start < 1.0:
                start = max(0.0, end - 3.0)
            clips.append({
                "event_id": item["event_id"],
                "start_time": round(start, 3),
                "end_time": round(end, 3),
                "event_type": item["event_type"],
                "display_name": item.get("display_name") or EVENT_TYPE_ZH.get(item["event_type"], item["event_type"]),
                "action_label_zh": item.get("action_label_zh"),
                "raw_model_score": self._score(item),
                "verification_status": item["verification_status"],
            })
        clips = fit_clips_to_target(clips, target)
        self.plan = {"schema_version": "1.1", "source_video_id": self.video_id, "target_duration": target, "clips": clips,
                     "evidence_status": "MODEL_PREDICTED",
                     "note": "本地 X3D 只识别通用篮球动作，不确认进球、球员或回合归属。"}
        self.state = "PLAN_CREATED"; self._trace("create_highlight_plan", self.plan)
        (self.output_dir / "highlight_plan.json").write_text(json.dumps(self.plan, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.plan

    @staticmethod
    def _cn_number(value: str) -> int | None:
        digits = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
        if not value:
            return None
        if value.isdigit():
            return int(value)
        if value == "十":
            return 10
        if "十" in value:
            left, _, right = value.partition("十")
            tens = digits.get(left, 1) if left else 1
            ones = digits.get(right, 0) if right else 0
            return tens * 10 + ones
        return digits.get(value)

    @staticmethod
    def _duration_from_text(text: str) -> float | None:
        # "1分30秒", "1.5分钟", "半分钟", "一分钟"
        match = re.search(r"(\d+(?:\.\d+)?)\s*(?:分钟|分|min)\s*(?:(\d+)\s*秒)?", text, re.I)
        if match:
            seconds = float(match.group(1)) * 60 + float(match.group(2) or 0)
            if re.search(r"(?:分钟|分|min)\s*半", text, re.I):
                seconds += 30
            return seconds
        if "半分钟" in text or "半min" in text:
            return 30.0
        match = re.search(r"([零一二两三四五六七八九十]+)\s*(?:分钟|分)", text)
        if match:
            number = LightweightSession._cn_number(match.group(1))
            if number:
                seconds = float(number) * 60
                if re.search(r"(?:分钟|分)\s*半", text):
                    seconds += 30
                return seconds
        match = re.search(r"([零一二两三四五六七八九十]+)\s*秒", text)
        if match:
            number = LightweightSession._cn_number(match.group(1))
            if number:
                return float(number)
        match = re.search(r"(\d+(?:\.\d+)?)\s*(?:秒|s\b)", text, re.I)
        return float(match.group(1)) if match else None

    @staticmethod
    def _count_from_text(text: str) -> int:
        match = re.search(r"(\d+)\s*(?:个|段|片段|条)", text)
        if match:
            return int(match.group(1))
        match = re.search(r"([一二两三四五六七八九十]+)\s*(?:个|段|片段|条)", text)
        if match:
            number = LightweightSession._cn_number(match.group(1))
            if number:
                return number
        return 3

    def _write_plan(self) -> None:
        if self.plan:
            (self.output_dir / "highlight_plan.json").write_text(json.dumps(self.plan, ensure_ascii=False, indent=2), encoding="utf-8")

    def _render(self) -> dict[str, Any]:
        if not self.plan:
            raise ValueError("尚无剪辑计划")
        result = render_plan(self.video_id, self.plan, self.output_dir / "highlights.mp4")
        self.plan["rendered_window"] = {"start": result["start"], "end": result["end"], "duration": result["duration"]}
        # The renderer exports one continuous source span.  Gaps between listed
        # clips are therefore included in the MP4; record that fact explicitly.
        self.plan["render_mode"] = "single_continuous_window"
        self._write_plan()
        self.state = "RENDER_COMPLETED"; self._trace("render_highlights", result)
        self.state = "OUTPUT_VERIFIED"; self._trace("verify_render", result["probe"])
        return result

    def ask(self, message: str) -> dict[str, Any]:
        """Execute a supported local command using state, rather than canned answers."""
        text = message.strip().lower()
        if not text:
            return self._save("请输入一条命令，例如“生成 20 秒投篮高光”。", {})
        try:
            is_hypecut = self.candidate_version == "hypecut"
            is_scoring = any(x in text for x in ("投篮", "出手", "shot", "shoot", "扣篮", "灌篮", "得分", "进球"))
            duration = self._duration_from_text(text)
            is_outcome_question = any(x in text for x in ("命中", "进了", "进球", "得分", "made")) and is_scoring
            is_help = any(x in text for x in ("帮助", "怎么用", "能做什么", "功能", "使用说明"))
            is_search = any(x in text for x in ("找出", "查找", "搜索", "查看", "关键事件", "有哪些", "列出"))
            is_shorten = any(x in text for x in ("缩短", "再短", "剪成", "压缩", "改成", "调整为"))
            is_recap = any(x in text for x in ("解释", "复盘", "分析", "说明", "总结"))
            is_export = any(x in text for x in ("导出", "下载", "保存"))
            is_generate = any(x in text for x in ("生成", "提取", "剪辑", "帮我剪", "帮我做", "做一个", "来一个", "高光", "精彩片段", "集锦", "最精彩", "挑", "选"))

            if is_help:
                return self._save(
                    "我可以帮你：\n"
                    "• 生成 20 秒投篮高光\n"
                    "• 做一个 30 秒精彩集锦\n"
                    "• 找出所有疑似投篮/扣篮\n"
                    "• 缩短到 15 秒 / 保留最精彩的 3 个片段\n"
                    "• 解释这段高光 / 导出视频\n"
                    "直接说你想做什么即可。",
                    {},
                )
            if not any((is_outcome_question, is_shorten, is_export, is_search, is_recap, is_generate)):
                # Do not run a long local scan just to answer an unrelated
                # message.  Give a useful next step instead.
                return self._save(
                    "我可以帮你生成高光、找投篮候选、缩短时长或解释片段。\n"
                    "试试说：“生成 20 秒投篮高光”或“做一个 30 秒精彩集锦”。",
                    {},
                )

            items = self._events()
            self._trace("get_video_info", {"video_id": self.video_id, "candidate_version": self.candidate_version, "events_available": len(items)})

            def matching(pool: list[dict[str, Any]]) -> list[dict[str, Any]]:
                if is_hypecut or not is_scoring:
                    return list(pool)
                return [x for x in pool if x["event_type"] in SHOT_LIKE_TYPES]

            def clamp_target(value: float) -> float:
                total = self.video_duration or 60.0
                return max(5.0, min(60.0, min(float(value), total)))

            if is_outcome_question:
                shot_items = [x for x in items if x["event_type"] in SHOT_LIKE_TYPES]
                self.state = "EVENTS_RETRIEVED"
                self._trace("search_events", {"event_type": "shot_attempt", "count": len(shot_items), "outcome_check": True})
                if is_hypecut:
                    return self._save("HypeCut 只提供画面/音频变化信号，不识别投篮动作，也无法判断是否命中。切换到 Lightweight 模式可以查看本地动作候选。", {"events": []})
                return self._save(
                    f"这段视频里有 {len(shot_items)} 个疑似投篮/扣篮候选，但本地 X3D 只能识别通用动作，不能判断是否命中。建议先生成集锦，再回看确认。",
                    {"events": shot_items},
                )

            if is_shorten and not self.plan:
                if duration is not None:
                    # “缩短到 15 秒” without an existing plan naturally means
                    # “make me a 15-second highlight”.
                    is_shorten = False
                    is_generate = True
                else:
                    return self._save("当前还没有高光计划。先告诉我“生成 20 秒高光”，之后才能继续缩短。", {"failure": {"stage": "STATE_CHECK", "retryable": True}})

            if is_shorten:
                current = float(self.plan["target_duration"])
                target = clamp_target(duration if duration is not None else current - 5.0)
                if abs(target - current) < 0.01:
                    return self._save(f"当前高光已经是约 {current:g} 秒，无需调整。", {"plan": self.plan})
                self.plan["target_duration"] = target
                self._write_plan()
                self._trace("update_highlight_plan", {"target_duration": target, "previous_duration": current})
                output = self._render()
                return self._save(
                    f"已把高光调整为约 {output['duration']:.0f} 秒，并重新生成视频。",
                    {"output": output, "plan": self.plan},
                )

            if is_export and self.plan and not is_generate:
                output = self._render()
                return self._save("已重新导出当前高光，视频可以直接播放或下载。", {"output": output, "plan": self.plan})

            if is_search:
                found = matching(items)
                self.state = "EVENTS_RETRIEVED"
                self._trace("search_events", {"event_type": "shot_attempt" if is_scoring and not is_hypecut else None, "count": len(found)})
                if not found:
                    return self._save("没有找到符合条件的候选。可以试试“找出所有篮球动作”或切换候选版本。", {"events": []})
                ranked = sorted(found, key=self._score, reverse=True)[:3]
                preview = "；".join(
                    f"{float(x['start_time']):.1f}s {x.get('display_name') or EVENT_TYPE_ZH.get(x['event_type'], x['event_type'])}"
                    for x in ranked
                )
                kind = "投篮/扣篮" if is_scoring and not is_hypecut else "篮球动作"
                return self._save(
                    f"找到 {len(found)} 个{kind}候选。最值得先看的是：{preview}。这些只是 AI 推测，建议回看确认。",
                    {"events": found},
                )

            if is_recap:
                if self.plan and self.plan.get("clips"):
                    lines = []
                    for index, clip in enumerate(self.plan["clips"], 1):
                        name = clip.get("display_name") or EVENT_TYPE_ZH.get(clip.get("event_type", ""), "动作")
                        lines.append(f"{index}. {name}，{float(clip['start_time']):.1f}–{float(clip['end_time']):.1f}s")
                    summary = "当前高光包含：" + "；".join(lines) + "。这些是 AI 候选，不能确认进球、球员或回合归属。"
                else:
                    top = sorted(items, key=self._score, reverse=True)[:5]
                    summary = (
                        "这段视频里最值得关注的候选是："
                        + "；".join(
                            f"{float(x['start_time']):.1f}s {x.get('display_name') or EVENT_TYPE_ZH.get(x['event_type'], x['event_type'])}"
                            for x in top
                        )
                        + "。先生成高光可以进一步筛选。"
                    ) if top else "这段视频里暂时没有识别到篮球动作候选。"
                recap = {"source_video_id": self.video_id, "events": self.plan["clips"] if self.plan else [],
                         "verification_status": "MODEL_PREDICTED", "summary": summary}
                self._trace("generate_recap", recap)
                (self.output_dir / "match_recap.json").write_text(json.dumps(recap, ensure_ascii=False, indent=2), encoding="utf-8")
                return self._save(summary, {"recap": recap})

            if is_generate:
                selected = matching(items)
                fallback_note = ""
                if not selected:
                    if not items:
                        return self._save("这段视频里暂时没有识别到篮球动作候选，无法生成高光。可以先换一段视频试试。", {"failure": {"stage": "NO_CANDIDATES", "retryable": True}})
                    selected = list(items)
                    fallback_note = " 没有足够可靠的投篮/扣篮候选，已改用全部篮球动作候选。"
                max_clips = self._count_from_text(text) if any(x in text for x in ("最精彩", "保留", "片段")) else 3
                target = clamp_target(duration if duration is not None else 20.0)
                plan = self._make_plan(selected, target, max_clips)
                output = self._render()
                counts = Counter(c.get("display_name") or EVENT_TYPE_ZH.get(c.get("event_type", ""), "动作") for c in plan["clips"])
                summary = "、".join(f"{name} {count} 段" for name, count in counts.items())
                if is_hypecut:
                    reply = (
                        f"已用 HypeCut 信号生成约 {output['duration']:.0f} 秒候选集锦，共 {len(plan['clips'])} 个片段。"
                        "HypeCut 只检测画面/音频变化，不代表已识别出投篮或进球，请回看确认。"
                    )
                else:
                    reply = (
                        f"高光已生成：约 {output['duration']:.0f} 秒，共 {len(plan['clips'])} 个片段"
                        + (f"（{summary}）" if summary else "")
                        + "。所有事件都是 AI 推测，建议回看原视频确认。"
                    )
                return self._save(reply + fallback_note, {"plan": plan, "output": output})

            return self._save(
                "我可以帮你生成高光、找投篮候选、缩短时长或解释片段。\n"
                "试试说：“生成 20 秒投篮高光”或“做一个 30 秒精彩集锦”。",
                {},
            )
        except Exception as exc:
            failure = {"stage": self.state, "error_type": type(exc).__name__, "message": str(exc), "retryable": isinstance(exc, (RuntimeError, OSError, subprocess.SubprocessError))}
            self._trace("agent_failure", failure)
            return self._save("本地 Agent 在“%s”阶段失败：%s。%s" % (failure["stage"], failure["error_type"], "可以重试。" if failure["retryable"] else "请检查输入后重试。"), {"failure": failure})

    def _save(self, reply: str, extra: dict[str, Any]) -> dict[str, Any]:
        if not extra.get("failure"):
            self.state = "TASK_COMPLETED" if (self.output_dir / "highlights.mp4").exists() else self.state
        (self.output_dir / "tool_trace.json").write_text(json.dumps(self.traces, ensure_ascii=False, indent=2), encoding="utf-8")
        (self.output_dir / "session_history.json").write_text(json.dumps({"video_id": self.video_id, "state": self.state}, ensure_ascii=False, indent=2), encoding="utf-8")
        (self.output_dir / "run_summary.json").write_text(json.dumps({"mode": "lightweight", "candidate_version": self.candidate_version, "state": self.state, "tool_calls": len(self.traces), "cloud_api_calls": 0}, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"reply": reply, "session_id": self.session_id, "mode": "lightweight", "candidate_version": self.candidate_version, "artifacts": str(self.output_dir.relative_to(ROOT)), "state": self.state, **extra}
