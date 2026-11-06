#!/usr/bin/env python3
"""Frozen 10-clip BARD pilot for MoTrack's local lightweight variants.

This is deliberately separate from the paused PL-NBA work.  BARD supplies
clip-level labels, so the script reports only clip-level shot-label presence;
it never treats a candidate time as BARD event-localization ground truth.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

import integrations.lightweight as v1
import integrations.lightweight_v2 as v2
from motrack import ROOT, run_hypecut as invoke_hypecut

OUT = ROOT / "outputs" / "lightweight_bard_pilot_10"
SOURCE = ROOT / "outputs" / "lightweight_data_feasibility" / "bard"
VIDEOS = SOURCE / "samples" / "videos"
LABELS = SOURCE / "metadata" / "dataset_paths.csv"
PROFILE = ROOT / "configs" / "basketball-broadcast.yaml"
SHOT_LABELS = {"2PT Shot", "3PT Shot", "Layup", "Dunk"}

# The first four entries are the already downloaded feasibility samples.  The
# remaining six are the only additional files this pilot is permitted to use.
SAMPLES = [
    ("bkn-vs-det-0022400861/2.mp4", "718a363e60769b0baf0ec48f7c57c8c258076cdbaec0ef7031c34f871b3ee40e"),
    ("bkn-vs-det-0022400861/4.mp4", "347794adfc731d6c26ff1877d6b9098143c006776eec022829162f9f9798a455"),
    ("bkn-vs-det-0022400861/19.mp4", "8d72bee59d4510aaeb3e232c38456e99745c90daa2fff1815c3e7012351b8e07"),
    ("bkn-vs-det-0022400861/37.mp4", "1c963e83eddc33326b2938a28f72ecc47b9b8f975f26bd006f1dd2f6dbb53f76"),
    ("bkn-vs-det-0022400861/13.mp4", "edeb5990c82728e3a009d6e04d6a8fcc80004c827b88576d09afa5ecb05b9ab6"),
    ("bkn-vs-det-0022400861/25.mp4", "6957028f5c128ae8933e8784127aa7aa79c0f2b416814976b4264b058e8318aa"),
    ("bkn-vs-det-0022400861/28.mp4", "09fe6f323bd328156efcddd58c3b4e04ccf4e799714a75b7e452552a6eb92a84"),
    ("bkn-vs-det-0022400861/17.mp4", "b00bb5a0a461860af565198ea674dc5d2585a1ebb8ad779c4b008224d0f40f2a"),
    ("bkn-vs-det-0022400861/20.mp4", "5b0fc863c0fb97cc8332592159489acadf1f7d2cc2545a5b41c1d28c37f1e5ff"),
    ("bkn-vs-det-0022400861/34.mp4", "1b7f2fdedc72c45aa9f0cebc2239455c07130b0497906af988ab5538dc328e2f"),
]


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def sample_id(relative: str) -> str:
    return "bard_" + relative.replace(".mp4", "").replace("/", "_").replace("-", "_")


def local_file(relative: str) -> Path:
    return VIDEOS / relative.replace("/", "__")


def load_labels() -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for line in LABELS.read_text(encoding="utf-8").splitlines()[1:]:
        path, actions, _ = line.split(";", 2)
        result[path] = ast.literal_eval(actions)
    return result


def shot_present(actions: list[dict[str, Any]]) -> bool:
    return any(x.get("action") in SHOT_LABELS for x in actions)


def run_hypecut_analysis(video: Path, destination: Path) -> dict[str, Any]:
    """Run the unmodified upstream CLI and retain its plan as SIGNAL_ONLY."""
    began = time.perf_counter()
    try:
        # ``motrack.run_hypecut`` invokes the upstream CLI with its own cwd.
        # Keep the output anchored to this pilot instead of resolving there.
        # ``run_motrack.sh`` normally injects this directory.  This standalone
        # evaluator does the same only around its child process, then restores
        # the caller's environment; no system/user PATH is changed.
        old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{v1.FFMPEG.parent}:{old_path}"
        try:
            invoke_hypecut(["analyze", str(video.resolve()), "--profile", str(PROFILE.resolve()), "--target", "8", "--max-clips", "3", "--json", str(destination.resolve())])
        finally:
            os.environ["PATH"] = old_path
        payload = json.loads(destination.read_text(encoding="utf-8"))
        return {"status": "COMPLETED", "segments": payload.get("segments", []), "wall_seconds": round(time.perf_counter() - began, 6)}
    except Exception as exc:  # Keep V1/V2 results auditable if signal baseline fails.
        return {"status": "ERROR", "segments": [], "wall_seconds": round(time.perf_counter() - began, 6), "error_type": type(exc).__name__, "error": str(exc)}


def run_v1_with_audit(video_id: str, video: Path) -> dict[str, Any]:
    """Exact V1 sampling, mapping and merge logic, plus all-window audit."""
    info = v1._video_info(video)
    runner = v1.X3D()
    started = time.perf_counter()
    rows, raw, failures = [], [], []
    for number, (start, sampling, segment) in enumerate(v1._windows(video_id, info["duration"]), 1):
        began = time.perf_counter()
        try:
            frames, timestamps = v1._frames(video, start)
            top5 = runner.classify(frames)
            event = v1._event_from_window(video_id, start, timestamps, top5, sampling, segment)
            rows.append({"window_id": f"{video_id}-v1-w{number:03d}", "start_time": start, "frame_timestamps": timestamps,
                         "input_frame_count": len(frames), "sampling_strategy": sampling, "x3d_top5": top5,
                         "initial_event_type": event["event_type"] if event else "UNKNOWN",
                         "inference_seconds": round(time.perf_counter() - began, 6)})
            if event:
                raw.append(event)
        except Exception as exc:
            failures.append({"window_id": f"{video_id}-v1-w{number:03d}", "start_time": start, "error_type": type(exc).__name__, "error": str(exc)})
    events = v1._merge(raw)
    return {"schema_version": "bard-pilot-v1-audit-1", "candidate_version": "lightweight_v1", "events": events,
            "raw_windows": rows, "performance": {"device": str(runner.device), "model_load_seconds": runner.load_seconds,
            "gpu_memory_model_bytes": runner.memory_bytes, "inference_total_seconds": round(time.perf_counter() - started, 6),
            "windows": len(rows) + len(failures), "raw_candidates": len(raw), "merged_candidates": len(events), "failures": failures}}


def predicted_shot(events: list[dict[str, Any]]) -> bool:
    return any(x.get("event_type") == "shot_attempt" for x in events)


def classify(label_positive: bool, predicted: bool) -> tuple[str, str | None]:
    if label_positive and predicted:
        return "TP", None
    if not label_positive and predicted:
        return "FP", "shot_attempt candidate on a BARD clip without a documented shot label"
    if not label_positive and not predicted:
        return "TN", None
    return "FN", "no shot_attempt candidate on a BARD clip with a documented shot label"


def metrics(records: list[dict[str, Any]], field: str) -> dict[str, Any]:
    evaluated = [x for x in records if x.get(field, {}).get("status") == "COMPLETED"]
    values = [x[field]["clip_outcome"] for x in evaluated]
    counts = {k: values.count(k) for k in ("TP", "FP", "TN", "FN")}
    precision = counts["TP"] / (counts["TP"] + counts["FP"]) if counts["TP"] + counts["FP"] else None
    recall = counts["TP"] / (counts["TP"] + counts["FN"]) if counts["TP"] + counts["FN"] else None
    f1 = 2 * precision * recall / (precision + recall) if precision is not None and recall is not None and precision + recall else None
    accuracy = (counts["TP"] + counts["TN"]) / len(evaluated) if evaluated else None
    return {"evaluated_clip_count": len(evaluated), **counts, "precision": precision, "recall": recall, "f1": f1, "accuracy": accuracy,
            "metric_scope": "BARD clip-level documented-shot presence only; not action-boundary or made-shot evaluation."}


def process(relative: str, expected_sha: str, labels: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    video = local_file(relative)
    if not video.is_file():
        raise FileNotFoundError(f"missing selected BARD sample: {video}")
    actual_sha = hashlib.sha256(video.read_bytes()).hexdigest()
    if actual_sha != expected_sha:
        raise RuntimeError(f"SHA-256 mismatch: {relative}")
    sid = sample_id(relative)
    directory = OUT / "samples" / sid
    directory.mkdir(parents=True, exist_ok=True)
    actions = labels[relative]
    positive = shot_present(actions)
    probe = v1._video_info(video)
    hypecut_path = directory / "hypecut_candidates.json"
    hype = run_hypecut_analysis(video, hypecut_path)
    # A HypeCut segment may legitimately end at the final frame.  X3D requires
    # a complete 1.6 s input after the scan start, so create a scan-only copy
    # clipped to the last decodable start.  The original plan above remains the
    # sole source for HypeCut coverage reporting.
    scan_hypecut_path = directory / "hypecut_scan_segments.json"
    clipped_segments: list[dict[str, Any]] = []
    last_start = max(0.0, float(probe["duration"]) - 1.6)
    if hype["status"] == "COMPLETED":
        raw_plan = json.loads(hypecut_path.read_text(encoding="utf-8"))
        for segment in raw_plan.get("segments", []):
            copy = dict(segment)
            copy["end"] = min(float(copy["end"]), last_start + 1e-6)
            if float(copy["start"]) <= float(copy["end"]):
                clipped_segments.append(copy)
        raw_plan["segments"] = clipped_segments
        dump(scan_hypecut_path, raw_plan)
    else:
        dump(scan_hypecut_path, {"segments": []})

    # These two maps are project-local process state. They add a new evaluation
    # ID only; no existing video mapping, Agent, web endpoint or cache changes.
    v1.VIDEO_IDS[sid] = video
    v1.HYPECUT[sid] = scan_hypecut_path
    v1_result = run_v1_with_audit(sid, video)
    dump(directory / "v1_predictions.json", v1_result)
    v2_result = v2.v2_events(sid, force=True)
    v2_audit = json.loads((v2.QUALITY_OUT / sid / "raw_window_predictions.json").read_text(encoding="utf-8"))
    dump(directory / "v2_predictions.json", v2_result)
    dump(directory / "v2_raw_window_predictions.json", v2_audit)

    v1_pred = predicted_shot(v1_result["events"])
    v2_pred = predicted_shot(v2_result["events"])
    v1_outcome, v1_reason = classify(positive, v1_pred)
    v2_outcome, v2_reason = classify(positive, v2_pred)
    return {"sample_id": sid, "relative_video_path": relative, "local_file": str(video.relative_to(ROOT)), "bytes": video.stat().st_size,
            "sha256": actual_sha, "duration_seconds": probe["duration"], "ground_truth": {"actions": actions, "shot_label_present": positive,
            "scope_note": "A negative means no documented BARD shot label, not proof that no shooting-like image ever appears."},
            "sampling": {"x3d_nominal_input_seconds": 1.6, "hypecut_segment_count_before_boundary_clip": len(hype["segments"]),
                         "hypecut_segment_count_for_x3d_scan": len(clipped_segments), "v1_window_count": v1_result["performance"]["windows"], "v1_failed_windows": v1_result["performance"]["failures"],
                         "v2_window_count": v2_audit["window_count"], "v2_non_four_frame_windows": [x["window_id"] for x in v2_audit["windows"] if x["input_frame_count"] != 4]},
            "hypecut": {"status": hype["status"], "candidate_count": len(hype["segments"]), "candidate_coverage": bool(hype["segments"]),
                         "wall_seconds": hype["wall_seconds"], "error_type": hype.get("error_type"), "error": hype.get("error"),
                         "semantic_note": "SIGNAL_ONLY: highlighter proposal coverage, not a shot classifier."},
            "v1": {"status": "COMPLETED", "predicted_shot_attempt": v1_pred, "clip_outcome": v1_outcome, "error_reason": v1_reason,
                   "candidate_count": len(v1_result["events"]), "shot_candidate_count": sum(x["event_type"] == "shot_attempt" for x in v1_result["events"]),
                   "inference_seconds": v1_result["performance"]["inference_total_seconds"], "raw_prediction_path": str((directory / "v1_predictions.json").relative_to(ROOT))},
            "v2": {"status": "COMPLETED", "predicted_shot_attempt": v2_pred, "clip_outcome": v2_outcome, "error_reason": v2_reason,
                   "candidate_count": len(v2_result["events"]), "shot_candidate_count": sum(x["event_type"] == "shot_attempt" for x in v2_result["events"]),
                   "inference_seconds": v2_audit["inference_total_seconds"], "raw_prediction_path": str((directory / "v2_predictions.json").relative_to(ROOT))}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean", action="store_true", help="replace only this pilot output directory")
    args = parser.parse_args()
    if args.clean and OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)
    labels = load_labels()
    config = {"dataset": "BARD", "license": "CC-BY-4.0", "sample_count": 10, "selected_paths": [x[0] for x in SAMPLES],
              "run_order": {"first_existing_four": [x[0] for x in SAMPLES[:4]], "then_six_additional": [x[0] for x in SAMPLES[4:]]},
              "shot_label_definition": sorted(SHOT_LABELS), "v1_v2_parameters": "Existing frozen implementation and defaults; no weights/thresholds changed.",
              "hypecut_scope": "Existing HypeCut sports-broadcast profile; reported only as SIGNAL_ONLY proposal coverage.",
              "evaluation_scope": "clip-level label presence; no within-clip timing metrics."}
    dump(OUT / "experiment_config.json", config)
    records: list[dict[str, Any]] = []
    for relative, sha in SAMPLES[:4]:
        records.append(process(relative, sha, labels))
        dump(OUT / "phase_1_existing_four_records.json", records)
    if not all(x["v1"]["status"] == "COMPLETED" and x["v2"]["status"] == "COMPLETED" for x in records):
        dump(OUT / "run_summary.json", {"status": "STOPPED_AFTER_EXISTING_FOUR", "records": records})
        return 2
    for relative, sha in SAMPLES[4:]:
        records.append(process(relative, sha, labels))
    summary = {"status": "COMPLETED", "sample_count": len(records), "v1": metrics(records, "v1"), "v2": metrics(records, "v2"),
               "hypecut_coverage": {"positive_clips_with_any_proposal": sum(x["ground_truth"]["shot_label_present"] and x["hypecut"]["candidate_coverage"] for x in records),
                                    "positive_clip_count": sum(x["ground_truth"]["shot_label_present"] for x in records),
                                    "negative_clips_with_any_proposal": sum(not x["ground_truth"]["shot_label_present"] and x["hypecut"]["candidate_coverage"] for x in records),
                                    "interpretation": "Proposal coverage only; do not read as HypeCut shot-classification precision or recall."},
               "limitations": ["Exploratory n=10 only; no significance claim.", "BARD labels are clip-level and may contain multiple actions.", "Negative means no documented shot label, not visual proof of no shooting-like motion.", "No model weights, thresholds, or mappings were tuned on this pilot."]}
    dump(OUT / "sample_results.json", records)
    dump(OUT / "run_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
