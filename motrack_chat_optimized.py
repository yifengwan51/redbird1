#!/usr/bin/env python3
"""Cost-bounded real LLM chat; controller deterministically completes valid plans."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from openai import OpenAI

from integrations.api_config import resolve_base_url
from integrations.security import ensure_inside

R = Path(__file__).resolve().parent
DEFAULT_OUT = R / "outputs" / "agent_chat_optimized"
CACHE = R / "outputs" / "semantic_vision_live" / "basketball_events.json"
VIDEO_FILES = {
    "cbf": R / "inputs" / "cbf_3x3_tour.mp4",
    "doug": R / "inputs" / "doug_mcdermott.mp4",
}
FF = R / "tools" / "ffmpeg" / "bin" / "ffmpeg"
PROBE = R / "tools" / "ffmpeg" / "bin" / "ffprobe"
ALIASES = {"shot": "shot_attempt", "shoot": "shot_attempt", "投篮": "shot_attempt", "出手": "shot_attempt"}
TOOLS = [
    {"type": "function", "function": {"name": "search_events", "parameters": {"type": "object", "properties": {"event_type": {"type": "string"}, "min_confidence": {"type": "number"}}, "additionalProperties": False}}},
    {"type": "function", "function": {"name": "create_plan", "parameters": {"type": "object", "properties": {"event_ids": {"type": "array", "items": {"type": "string"}}, "target_duration": {"type": "number"}, "pre_context": {"type": "number"}, "post_context": {"type": "number"}}, "required": ["event_ids"], "additionalProperties": False}}},
]


def _probe_duration(video: Path) -> float | None:
    try:
        raw = subprocess.check_output([str(PROBE), "-v", "error", "-show_entries", "format=duration", "-of", "json", str(video)], text=True, timeout=30)
        return float(json.loads(raw)["format"]["duration"])
    except (OSError, KeyError, ValueError, subprocess.SubprocessError):
        return None


def _load_events(video_id: str) -> list[dict[str, Any]]:
    if video_id not in VIDEO_FILES:
        raise ValueError(f"unknown video_id: {video_id}")
    if not CACHE.is_file():
        raise RuntimeError(f"cached vision events are missing: {CACHE.relative_to(R)}")
    video_name = VIDEO_FILES[video_id].name
    payload = json.loads(CACHE.read_text(encoding="utf-8"))
    all_events = payload.get("events") if isinstance(payload, dict) else None
    if not isinstance(all_events, list):
        raise RuntimeError(f"cached vision events are malformed: {CACHE.relative_to(R)}")
    # Preserve the global ``vision-N`` indexes used by earlier audit files.
    return [event | {"id": f"vision-{index + 1}"} for index, event in enumerate(all_events)
            if isinstance(event, dict) and str(event.get("video_path", "")).endswith(video_name)]


def _clamp(value: Any, low: float, high: float, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return min(high, max(low, number))


class Run:
    def __init__(self, video_id: str = "cbf", output_dir: Path | None = None, api_key: str | None = None):
        if video_id not in VIDEO_FILES:
            raise ValueError(f"unknown video_id: {video_id}")
        self.video_id = video_id
        self.video = VIDEO_FILES[video_id]
        self.output_dir = ensure_inside(R, Path(output_dir) if output_dir else DEFAULT_OUT)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.events = _load_events(video_id)
        self.duration = _probe_duration(self.video)
        self.plan: dict[str, Any] | None = None
        self.last_output: dict[str, Any] | None = None
        self.trace: list[dict[str, Any]] = []
        self.usage: list[dict[str, Any]] = []
        self.model = os.getenv("MOTRACK_API_MODEL", "deepseek-v4.1-flash")
        key = api_key or os.getenv("MOTRACK_API_KEY")
        if not key:
            raise RuntimeError("MOTRACK_API_KEY is required")
        self.client = OpenAI(api_key=key, base_url=resolve_base_url(), timeout=90, max_retries=0)
        summary = "; ".join(
            f"{event['id']} {event.get('event_type')} {event.get('start_time')}-{event.get('end_time')}s confidence {event.get('confidence')}"
            for event in self.events
        ) or "none"
        self.hist = [
            {"role": "system", "content": "MoTrack cached-vision editor. Valid event types: shot_attempt,made_basket,missed_shot,pass,rebound,steal,fast_break,UNKNOWN. Aliases shot/shoot/投篮/出手 mean shot_attempt. Events are MODEL_PREDICTED; never claim made basket without evidence. Use one tool only if needed. After plan creation the controller renders and verifies."},
            {"role": "system", "content": f"Video {video_id} ({self.video.name}), duration {self.duration if self.duration is not None else 'unknown'}s. Cached events: {summary}. Current plan: none."},
        ]

    def search(self, arguments: dict[str, Any]) -> list[dict[str, Any]]:
        wanted = ALIASES.get(arguments.get("event_type", ""), arguments.get("event_type"))
        minimum = _clamp(arguments.get("min_confidence", 0), 0.0, 1.0, 0.0)
        return [event for event in self.events
                if (not wanted or event.get("event_type") == wanted) and float(event.get("confidence", 0)) >= minimum]

    def make(self, arguments: dict[str, Any]) -> dict[str, Any]:
        ids = arguments.get("event_ids") or []
        if not isinstance(ids, list):
            raise ValueError("event_ids must be a list")
        selected = [event for event in self.events if event["id"] in ids]
        if not selected:
            raise ValueError("no known event_ids")
        pre = _clamp(arguments.get("pre_context", 2), 0.0, 30.0, 2.0)
        post = _clamp(arguments.get("post_context", 2), 0.0, 30.0, 2.0)
        target = _clamp(arguments.get("target_duration", 15), 1.0, 60.0, 15.0)
        clips = []
        for event in selected:
            start = max(0.0, float(event["start_time"]) - pre)
            end = float(event["end_time"]) + post
            if self.duration is not None:
                end = min(end, self.duration)
            if end <= start:
                end = start + 0.5
            clips.append({"event_id": event["id"], "start": round(start, 3), "end": round(end, 3),
                          "event_type": event.get("event_type"), "confidence": event.get("confidence")})
        clips.sort(key=lambda item: item["start"])
        merged: list[dict[str, Any]] = []
        for clip in clips:
            if merged and clip["start"] < merged[-1]["end"]:
                merged[-1]["end"] = max(merged[-1]["end"], clip["end"])
                merged[-1]["event_id"] += "," + clip["event_id"]
            else:
                merged.append(clip)
        start = min(clip["start"] for clip in merged)
        end = min(max(clip["end"] for clip in merged), start + target)
        kept = [clip for clip in merged if clip["start"] < end]
        if not kept:
            raise ValueError("selected events do not fit the requested duration")
        for clip in kept:
            clip["end"] = min(clip["end"], end)
        self.plan = {"source_video_id": self.video_id, "source": str(self.video.relative_to(R)),
                     "window_start": round(start, 3), "window_end": round(end, 3),
                     "target_duration": target, "clips": kept,
                     "verification_status": "MODEL_PREDICTED",
                     "note": "Cached vision candidates; shot results remain unconfirmed."}
        (self.output_dir / "highlight_plan.json").write_text(json.dumps(self.plan, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.plan

    def complete_plan(self) -> dict[str, Any]:
        if not self.plan or not self.plan.get("clips"):
            raise ValueError("no plan to render")
        start = float(self.plan["window_start"])
        end = float(self.plan["window_end"])
        if end <= start:
            raise ValueError("invalid render window")
        output = self.output_dir / "highlights.mp4"
        subprocess.run([str(FF), "-y", "-v", "error", "-ss", str(start), "-to", str(end), "-i", str(self.video),
                        "-map", "0:v:0", "-map", "0:a?", "-c:v", "libx264", "-c:a", "aac",
                        "-movflags", "+faststart", str(output)], check=True, timeout=600)
        probe = json.loads(subprocess.check_output([str(PROBE), "-v", "error", "-show_entries", "format=duration:stream=codec_type", "-of", "json", str(output)], text=True, timeout=30))
        self.last_output = {"path": str(output.relative_to(R)), "start": start, "end": end, "duration": float(probe["format"]["duration"]), "probe": probe}
        self.trace += [
            {"initiator": "CONTROLLER", "tool": "render_highlights", "result": self.last_output},
            {"initiator": "CONTROLLER", "tool": "verify_render", "result": probe},
        ]
        recap = {"source_video_id": self.video_id, "events": [
            {"event_id": clip["event_id"], "event_type": clip["event_type"], "confidence": clip["confidence"],
             "verification_status": "MODEL_PREDICTED", "note": "Shot result unconfirmed."}
            for clip in self.plan["clips"]
        ]}
        (self.output_dir / "match_recap.json").write_text(json.dumps(recap, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.last_output

    def turn(self, text: str) -> str:
        self.hist.append({"role": "user", "content": text})
        response = self.client.chat.completions.create(model=self.model, messages=self.hist, tools=TOOLS,
                                                       tool_choice="auto", max_tokens=200, temperature=0.1,
                                                       extra_body={"reasoning_effort": "low"})
        message = response.choices[0].message
        self.usage.append(response.usage.model_dump() if response.usage else {})
        self.hist.append(message.model_dump(exclude_none=True))
        handlers = {"search_events": self.search, "create_plan": self.make}
        for tool_call in message.tool_calls or []:
            name = tool_call.function.name
            arguments: Any = None
            try:
                arguments = json.loads(tool_call.function.arguments or "{}")
                if name not in handlers or not isinstance(arguments, dict):
                    raise ValueError("unapproved tool or parameters")
                result: Any = handlers[name](arguments)
            except Exception as exc:
                result = {"error": type(exc).__name__, "message": str(exc)}
            self.trace.append({"initiator": "LLM", "tool_call_id": tool_call.id, "tool": name,
                               "arguments": arguments if isinstance(arguments, dict) else None, "result": result})
            self.hist.append({"role": "tool", "tool_call_id": tool_call.id, "content": json.dumps(result, ensure_ascii=False)})
            if name == "create_plan" and not (isinstance(result, dict) and result.get("error")):
                try:
                    self.complete_plan()
                except Exception as exc:
                    self.trace.append({"initiator": "CONTROLLER", "tool": "render_highlights", "result": {"error": type(exc).__name__, "message": str(exc)}})
        if message.tool_calls and not (message.content or "").strip():
            follow = self.client.chat.completions.create(model=self.model, messages=self.hist, max_tokens=200,
                                                         temperature=0.1, extra_body={"reasoning_effort": "low"})
            self.usage.append(follow.usage.model_dump() if follow.usage else {})
            message = follow.choices[0].message
            self.hist.append(message.model_dump(exclude_none=True))
        self.save()
        return message.content or "工具调用已完成。"

    def save(self) -> None:
        (self.output_dir / "session_history.json").write_text(json.dumps(self.hist, ensure_ascii=False, indent=2), encoding="utf-8")
        (self.output_dir / "tool_trace.json").write_text(json.dumps(self.trace, ensure_ascii=False, indent=2), encoding="utf-8")
        (self.output_dir / "api_usage.json").write_text(json.dumps(self.usage, ensure_ascii=False, indent=2), encoding="utf-8")
        (self.output_dir / "run_summary.json").write_text(json.dumps({
            "video_id": self.video_id,
            "state": "TASK_COMPLETED" if self.last_output else "INTENT_PARSED",
            "requests": len(self.usage),
            "cached_vision": True,
        }, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="MoTrack cached-vision LLM chat")
    parser.add_argument("--video", choices=sorted(VIDEO_FILES), default="cbf")
    args = parser.parse_args()
    run = Run(video_id=args.video)
    for line in sys.stdin:
        text = line.strip()
        if text in {"exit", "quit"}:
            break
        if text:
            print(run.turn(text))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
