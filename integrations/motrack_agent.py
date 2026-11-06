"""Bounded tool agent for basketball-highlights; no arbitrary shell execution."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


EVENT_TYPES = {"dunk", "three_pointer", "block", "steal", "fast_break", "layup", "scoring_play", "celebration", "defensive_play", "unknown"}


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
