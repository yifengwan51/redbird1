"""Bounded tool agent for basketball-highlights; no arbitrary shell execution."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


EVENT_TYPES = {"dunk", "three_pointer", "block", "steal", "fast_break", "layup", "scoring_play", "celebration", "defensive_play", "unknown"}
VISION_EVENT_TYPES = {"shot_attempt", "made_basket", "missed_shot", "steal", "rebound", "pass", "fast_break", "UNKNOWN"}


@dataclass
class AgentState:
    root: Path
    video: Path
    duration: float
    max_calls: int = 12
    api_budget_calls: int = 6
    calls: int = 0
    api_calls: int = 0
    seen_candidates: set[str] = field(default_factory=set)
    log: list[dict[str, Any]] = field(default_factory=list)


def validate_event(item: dict[str, Any], duration: float) -> dict[str, Any]:
    start, end = float(item["start"]), float(item["end"])
    if not (0 <= start < end <= duration):
        raise ValueError("event timestamps must be inside the original video")
    event_type = item.get("event_type", "unknown")
    if event_type not in EVENT_TYPES:
        event_type = "unknown"
    confidence = min(1.0, max(0.0, float(item.get("confidence", 0.0))))
    score = min(100, max(0, int(item.get("highlight_score", 0))))
    evidence = [float(x) for x in item.get("evidence_timestamps", [])]
    if any(x < start or x > end for x in evidence):
        raise ValueError("evidence timestamps must lie inside the candidate")
    return {"start": start, "end": end, "event_type": event_type, "highlight_score": score,
            "confidence": confidence, "evidence_timestamps": evidence,
            "description": str(item.get("description", "")), "uncertainty": str(item.get("uncertainty", "")),
            "source": "vlm_inference"}


def validate_vision_event(item: dict[str, Any], window_start: float, window_end: float) -> dict[str, Any]:
    """Validate one model-produced vision event against its source window.

    The vision model is an untrusted JSON producer.  Timestamps are clamped to
    the window, zero-length events are widened to a minimal evidence interval,
    confidence is clamped, and unknown labels become ``UNKNOWN``.
    """
    if not isinstance(item, dict):
        raise ValueError("event must be an object")
    event_type = str(item.get("event_type", "UNKNOWN"))
    if event_type not in VISION_EVENT_TYPES:
        event_type = "UNKNOWN"
    try:
        start, end = float(item["start_time"]), float(item["end_time"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("event timestamps must be numeric") from exc
    if end < start:
        start, end = end, start
    start = min(max(window_start, start), window_end)
    end = min(max(window_start, end), window_end)
    if end - start < 0.5:
        end = min(window_end, start + 0.5)
    if end <= start:
        raise ValueError("event timestamps must lie inside the source window")
    try:
        confidence = float(item.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = min(1.0, max(0.0, confidence))
    frames = []
    for value in item.get("evidence_frames", []) or []:
        try:
            frame = float(value)
        except (TypeError, ValueError):
            continue
        if start <= frame <= end:
            frames.append(round(frame, 3))
    if not frames:
        frames = [round((start + end) / 2, 3)]
    result = dict(item)
    result.update({
        "event_type": event_type,
        "start_time": round(start, 3),
        "end_time": round(end, 3),
        "confidence": round(confidence, 6),
        "evidence_frames": frames,
        "verification_status": "UNVERIFIED" if event_type == "UNKNOWN" else "MODEL_PREDICTED",
    })
    return result


class BoundedAgent:
    """Executes only named local tools and writes an auditable call log."""
    def __init__(self, state: AgentState, tools: dict[str, Callable[..., Any]]) -> None:
        self.state, self.tools = state, tools

    def call(self, name: str, arguments: dict[str, Any]) -> Any:
        if name not in self.tools:
            raise ValueError(f"unapproved tool: {name}")
        if self.state.calls >= self.state.max_calls:
            raise RuntimeError("maximum tool-call count reached")
        self.state.calls += 1
        try:
            result = self.tools[name](**arguments)
            self.state.log.append({"tool": name, "arguments": arguments, "status": "ok"})
            return result
        except Exception as exc:
            self.state.log.append({"tool": name, "arguments": arguments, "status": "error", "error": type(exc).__name__})
            raise

    def write_log(self, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.state.log, ensure_ascii=False, indent=2), encoding="utf-8")
