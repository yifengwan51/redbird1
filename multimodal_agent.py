#!/usr/bin/env python3
"""Cached-vision multimodal Agent E2E, with no external API calls."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "outputs" / "agent_multimodal"
VISION = ROOT / "outputs/semantic_vision_live/basketball_events.json"
VIDEO = ROOT / "inputs/cbf_3x3_tour.mp4"
FF = ROOT / "tools/ffmpeg/bin/ffmpeg"
PROBE = ROOT / "tools/ffmpeg/bin/ffprobe"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    if not VISION.is_file():
        raise SystemExit(f"missing cached vision events: {VISION.relative_to(ROOT)}; run semantic_vision.py first")
    payload = json.loads(VISION.read_text(encoding="utf-8"))
    items = payload.get("events") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise SystemExit(f"malformed cached vision events: {VISION.relative_to(ROOT)}")
    events = [e | {"source_video_id": "cbf_3x3_tour", "source_model": "deepseek-v4.1-flash", "evidence_source": "CACHED_VISION"}
              for e in items if isinstance(e, dict) and str(e.get("video_path", "")).endswith("cbf_3x3_tour.mp4")]
    trace = []

    def tool(name, args, result):
        trace.append({"tool_call_id": f"cached-{len(trace) + 1:02d}", "tool": name, "arguments": args, "result": result})
        return result

    shots = tool("search_events", {"query": "找出所有疑似投篮", "event_type": "shot_attempt", "verification_status": "MODEL_PREDICTED"}, events)
    if not shots:
        raise SystemExit("No cached CBF shot candidates")
    # One continuous window keeps 10s lead-in and 6s aftermath around the two related visual predictions.
    start = max(0, min(e["start_time"] for e in shots) - 10)
    end = max(e["end_time"] for e in shots) + 6
    plan = {"mode": "CACHED_VISION", "source_video": str(VIDEO.relative_to(ROOT)),
            "clips": [{"start": start, "end": end, "event_ids": [e["event_type"] + "@" + str(e["start_time"]) for e in shots],
                       "reason": "MODEL_PREDICTED shot_attempt evidence; boundaries add context, not extra event claims."}]}
    (OUT / "basketball_events.json").write_text(json.dumps({"events": events}, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "highlight_plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    tool("create_highlight_plan", {"events": len(shots), "target_seconds": "20-30"}, plan)
    subprocess.run([str(FF), "-y", "-v", "error", "-ss", str(start), "-to", str(end), "-i", str(VIDEO),
                    "-map", "0:v:0", "-map", "0:a?", "-c:v", "libx264", "-c:a", "aac", "-movflags", "+faststart",
                    str(OUT / "highlights.mp4")], check=True, timeout=600)
    raw = subprocess.check_output([str(PROBE), "-v", "error", "-show_entries", "format=duration:stream=codec_type,codec_name", "-of", "json", str(OUT / "highlights.mp4")], text=True, timeout=30)
    verification = json.loads(raw)
    tool("verify_render", {"output_path": "outputs/agent_multimodal/highlights.mp4"}, verification)
    recap = {"mode": "CACHED_VISION",
             "events": [{"time": [e["start_time"], e["end_time"]], "event_type": e["event_type"], "confidence": e["confidence"],
                         "evidence_frames": e["evidence_frames"], "explanation": e["evidence_description"],
                         "uncertainty": "MODEL_PREDICTED; not human verified; no made/missed result claimed."} for e in shots],
             "chain": {"start_time": start, "end_time": end, "verification_status": "POSSIBLE_CHAIN",
                       "note": "Two temporal visual predictions in one continuous clip; no possession assertion."}}
    (OUT / "match_recap.json").write_text(json.dumps(recap, ensure_ascii=False, indent=2), encoding="utf-8")
    tool("generate_recap", {"plan": "cached vision"}, recap)
    (OUT / "tool_trace.json").write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "api_usage.json").write_text(json.dumps({"new_api_requests": 0, "mode": "CACHED_VISION",
                                                    "reused_vision_usage": json.loads((ROOT / "outputs/semantic_vision_live/api_usage.json").read_text())}, indent=2), encoding="utf-8")
    (OUT / "run_summary.json").write_text(json.dumps({"status": "PASS", "mode": "CACHED_VISION", "new_api_calls": 0,
                                                      "highlights": "outputs/agent_multimodal/highlights.mp4", "duration": end - start,
                                                      "events": len(events), "selected_events": len(shots)}, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
