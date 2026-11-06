#!/usr/bin/env python3
"""MoTrack command line: baseline HypeCut orchestration and guarded Agent entrypoint."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
UPSTREAM = ROOT / "hypecut_upstream"
OUT = ROOT / "outputs"


def require_inside(path: str | Path) -> Path:
    candidate = Path(path).expanduser().resolve()
    root = ROOT.resolve()
    if root not in (candidate, *candidate.parents):
        raise ValueError(f"path must stay under {root}")
    return candidate


def run_hypecut(arguments: list[str]) -> None:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError("FFmpeg/FFprobe are not on PATH. HypeCut requires them; no fallback is used.")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(UPSTREAM / "src") + os.pathsep + env.get("PYTHONPATH", "")
    subprocess.run([sys.executable, "-m", "hypecut", *arguments], cwd=UPSTREAM, env=env, check=True, timeout=1800)


def make_contact_sheet(video: Path, destination: Path, plan_path: Path | None = None) -> None:
    """Call HypeCut's public contact-sheet API around its CLI quiet-flag defect."""
    sys.path.insert(0, str(UPSTREAM / "src"))
    from hypecut.contact import contact_sheet
    from hypecut.ffmpeg import probe
    info = probe(video)
    segments = None
    if plan_path and plan_path.exists():
        from hypecut.plan import load_plan
        try:
            plan, _ = load_plan(plan_path, source=video)
            segments = plan.segments
        except ValueError:  # empty plans do not have renderable segments
            segments = None
    contact_sheet(info, destination, segments=segments, count=12)


def render_hypecut_plan(plan_path: Path, video: Path, output: Path) -> None:
    """Render an already-audited plan and request HypeCut JSON/EDL sidecars."""
    sys.path.insert(0, str(UPSTREAM / "src"))
    from hypecut.pipeline import render_plan
    from hypecut.plan import load_plan
    plan, config = load_plan(plan_path, source=video)
    render_plan(plan, output, config, write_sidecar=True)


def video_path(value: str) -> Path:
    path = require_inside(value)
    if not path.is_file() or path.suffix.lower() not in {".mp4", ".mov", ".mkv", ".avi", ".webm"}:
        raise argparse.ArgumentTypeError("video must be an existing supported file inside tiqu1")
    return path


def baseline(video: Path, target: int, max_clips: int) -> None:
    clips, highlights, diagnostics = OUT / "clips", OUT / "highlights", OUT / "diagnostics"
    for folder in (clips, highlights, diagnostics): folder.mkdir(parents=True, exist_ok=True)
    plan = clips / "candidate_highlights.json"
    sheet = diagnostics / "contact_sheet.png"
    selected = diagnostics / "selected_contact_sheet.png"
    profile = ROOT / "configs" / "basketball-broadcast.yaml"
    # HypeCut plans include exact source metadata/configuration and reasons.
    make_contact_sheet(video, sheet)
    run_hypecut(["analyze", str(video), "--profile", str(profile), "--target", str(target),
                 "--max-clips", str(max_clips), "--json", str(plan)])
    make_contact_sheet(video, selected, plan)
    render_hypecut_plan(plan, video, highlights / "highlights.mp4")
    # Keep our promised stable filename even though upstream writes a sidecar beside MP4.
    sidecar = highlights / "highlights.hypecut.json"
    if not sidecar.exists():
        raise RuntimeError("HypeCut render completed without its expected JSON sidecar")
    shutil.copy2(sidecar, highlights / "highlight_plan.json")


TOOL_DEFINITIONS = [
    {"type": "function", "function": {"name": "probe_video", "description": "Read local video metadata.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "analyze_candidates", "description": "Run local HypeCut candidate analysis.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "inspect_candidate", "description": "Sample candidate frames for visual verification.", "parameters": {"type": "object", "properties": {"candidate_id": {"type": "string"}}, "required": ["candidate_id"]}}},
    {"type": "function", "function": {"name": "refine_candidate", "description": "Sample a candidate more densely when evidence is inadequate.", "parameters": {"type": "object", "properties": {"candidate_id": {"type": "string"}}, "required": ["candidate_id"]}}},
    {"type": "function", "function": {"name": "build_highlight_plan", "description": "Deduplicate and select verified candidate events.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "render_highlights", "description": "Render the approved local plan to MP4.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "generate_recap", "description": "Write an evidence-bounded recap.", "parameters": {"type": "object", "properties": {}}}},
]


def agent(video: Path, allow_api: bool) -> None:
    """Initialize a function-calling run; paid requests remain opt-in."""
    from integrations.deepseek import DeepSeekClient, DeepSeekSettings
    from integrations.motrack_agent import AgentState
    if not allow_api:
        raise RuntimeError("Agent mode may make paid API calls. Add --allow-api only after approval.")
    settings = DeepSeekSettings.from_env()
    state = AgentState(ROOT, video, 0.0)
    client = DeepSeekClient(settings, allow_network=True)
    prompt = ("You are a basketball-highlight editor. Use only supplied functions. Do not claim a score, "
              "made shot, player identity, or team state without temporal visual evidence. When uncertain use unknown.")
    # A request is intentionally made only after --allow-api and key validation.
    response = client.complete([{"role": "system", "content": prompt}, {"role": "user", "content": "Probe the video and start a bounded analysis."}], tools=TOOL_DEFINITIONS)
    OUT.joinpath("diagnostics").mkdir(parents=True, exist_ok=True)
    OUT.joinpath("diagnostics", "agent_initial_response.json").write_text(
        json.dumps({"tool_calls": [x.model_dump() for x in (response.choices[0].message.tool_calls or [])], "usage": client.usage}, ensure_ascii=False, indent=2), encoding="utf-8")
    # Tool execution is deliberately not fabricated: it follows only genuine model calls in the next implementation step.
    print("Initial function-calling response recorded. This is a legacy smoke test; use `live-agent --allow-api` for the full loop.")

def _find_candidates(video: Path) -> Path | None:
    """Find the real HypeCut plan whose recorded source matches this video."""
    root = ROOT / "outputs" / "real"
    if not root.is_dir():
        return None
    for candidate in sorted(root.glob("*/default.json")):
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if Path(data.get("source", "")).name == video.name:
            return candidate
    return None


def live_agent(video: Path, allow_api: bool, candidates: Path | None = None) -> None:
    """Run the bounded live HTADC loop; key is supplied only by environment."""
    if not allow_api:
        raise RuntimeError("live-agent makes paid API calls. Add --allow-api only after approval.")
    key=os.getenv("MOTRACK_API_KEY","")
    if not key: raise RuntimeError("MOTRACK_API_KEY is required")
    from integrations.agent_runtime import FunctionLoop, HTADCModel, LocalTools
    candidate = require_inside(candidates) if candidates is not None else _find_candidates(video)
    if not candidate or not candidate.exists():
        raise RuntimeError(f"no HypeCut candidate plan found for {video.name}; run baseline first or pass --candidates")
    data = json.loads(candidate.read_text(encoding="utf-8"))
    if data.get("source") and Path(data["source"]).name != video.name:
        raise RuntimeError(f"candidate plan source does not match {video.name}")
    out=OUT/"agent_deepseek"; tools=LocalTools(ROOT,video,candidate,out)
    model=HTADCModel(key, os.getenv("MOTRACK_API_BASE_URL"), os.getenv("MOTRACK_API_MODEL","deepseek-v4.1-flash"))
    result=FunctionLoop(model,tools,max_calls=12).run("Use candidates and evidence; select up to three, keep context, render, verify, recap. Do not claim unverified basketball events as facts.")
    out.mkdir(parents=True,exist_ok=True); (out/"tool_trace.json").write_text(json.dumps(result,indent=2)); (out/"api_usage.json").write_text(json.dumps(model.usage,indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="MoTrack basketball highlights")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("baseline", help="offline HypeCut analysis + render")
    p.add_argument("video", type=video_path); p.add_argument("--target", type=int, default=120); p.add_argument("--max-clips", type=int, default=8)
    p = sub.add_parser("agent", help="DeepSeek function-calling entrypoint (paid API opt-in)")
    p.add_argument("video", type=video_path); p.add_argument("--allow-api", action="store_true")
    p = sub.add_parser("live-agent", help="approved HTADC live function-calling loop (paid API opt-in)")
    p.add_argument("video", type=video_path)
    p.add_argument("--allow-api", action="store_true", help="explicitly approve paid API calls")
    p.add_argument("--candidates", type=Path, help="HypeCut candidate JSON (defaults to the matching outputs/real plan)")
    args = parser.parse_args()
    try:
        if args.command == "baseline": baseline(args.video, args.target, args.max_clips)
        elif args.command == "agent": agent(args.video, args.allow_api)
        else: live_agent(args.video, args.allow_api, args.candidates)
    except Exception as exc:
        print(f"MoTrack: {exc}", file=sys.stderr)
        return 2
    return 0

if __name__ == "__main__": raise SystemExit(main())
