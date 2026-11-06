"""Local-only event-detection benchmark primitives for aligned basketball clips."""
from __future__ import annotations
import csv
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SHOT_LABELS = {"2ptShot", "3ptShot", "Layup", "Dunk", "PutBack", "Putback"}

def parse_possession_timestamp(value: str) -> float:
    """PL-NBA strings like 07:50 represent 7.50 seconds inside a possession."""
    left, right = value.split(":", 1)
    if not (left.isdigit() and right.isdigit()):
        raise ValueError(f"invalid timestamp: {value}")
    return int(left) + int(right) / 100.0

def normalize_events(annotation: dict[str, Any], source: str) -> list[dict[str, Any]]:
    events = []
    for event in annotation.get("events", []):
        label = event.get("event_label")
        if label not in SHOT_LABELS:
            continue
        timestamp = event.get("timestamp_video", {})
        try:
            start, end = parse_possession_timestamp(timestamp["start"]), parse_possession_timestamp(timestamp["end"])
        except (KeyError, ValueError):
            continue
        events.append({"gt_id": f"{annotation.get('possession_id')}:{event.get('event_id')}", "event_type": "shot_attempt", "dataset_label": label,
                       "start_time": start, "end_time": end, "center_time": (start + end) / 2, "result": event.get("result"),
                       "video_id": annotation.get("video_id"), "possession_id": annotation.get("possession_id"), "annotation_source": source})
    return events

def discover(annotation_root: Path) -> dict[str, Any]:
    files = sorted(annotation_root.rglob("*.json")); labels: dict[str, int] = {}; games = set(); possessions = []; shot_events = []
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8")); games.add(data.get("video_id"))
        for item in data.get("events", []): labels[item.get("event_label", "UNKNOWN")] = labels.get(item.get("event_label", "UNKNOWN"), 0) + 1
        normalized = normalize_events(data, str(path.relative_to(annotation_root)))
        shot_events.extend(normalized)
        possessions.append({"annotation_path": str(path.relative_to(annotation_root)), "video_id": data.get("video_id"), "possession_id": data.get("possession_id"), "shot_event_count": len(normalized), "max_relative_seconds": max([x["end_time"] for x in normalized], default=None)})
    return {"annotation_file_count": len(files), "game_count": len(games), "event_label_counts": labels, "shot_label_mapping": sorted(SHOT_LABELS), "shot_event_count": len(shot_events), "possessions": possessions, "ground_truth_events": shot_events}

def one_to_one_match(predictions: list[dict[str, Any]], ground_truth: list[dict[str, Any]], tolerance: float) -> dict[str, Any]:
    """Closest-center greedy matching; a prediction and truth each match once."""
    pairs = []
    for pi, pred in enumerate(predictions):
        if pred.get("event_type") != "shot_attempt": continue
        pc = float(pred.get("center_time", (float(pred["start_time"]) + float(pred["end_time"])) / 2))
        for gi, truth in enumerate(ground_truth):
            tc = float(truth.get("center_time", (float(truth["start_time"]) + float(truth["end_time"])) / 2))
            delta = abs(pc - tc)
            if delta <= tolerance: pairs.append((delta, pi, gi))
    used_p, used_g, matches = set(), set(), []
    for delta, pi, gi in sorted(pairs):
        if pi in used_p or gi in used_g: continue
        used_p.add(pi); used_g.add(gi); matches.append({"prediction_index": pi, "ground_truth_index": gi, "center_error_seconds": round(delta, 6), "prediction": predictions[pi], "ground_truth": ground_truth[gi]})
    fp = [p for i, p in enumerate(predictions) if p.get("event_type") == "shot_attempt" and i not in used_p]
    fn = [g for i, g in enumerate(ground_truth) if i not in used_g]
    tp = len(matches); precision = tp / (tp + len(fp)) if tp + len(fp) else None; recall = tp / (tp + len(fn)) if tp + len(fn) else None
    f1 = (2 * precision * recall / (precision + recall)) if precision is not None and recall is not None and precision + recall else None
    return {"tolerance_seconds": tolerance, "TP": tp, "FP": len(fp), "FN": len(fn), "precision": precision, "recall": recall, "f1": f1, "matches": matches, "false_positives": fp, "false_negatives": fn}

def evaluate_manifest(manifest: dict[str, Any], prediction_root: Path, destination: Path) -> dict[str, Any]:
    """Score only manifest samples marked ALIGNED; others are exclusions."""
    destination.mkdir(parents=True, exist_ok=True); methods = ("hypecut", "v1", "v2"); rows = []; details = {}; excluded = []
    for sample in manifest.get("samples", []):
        if sample.get("alignment_status") != "ALIGNED":
            excluded.append({"sample_id": sample.get("sample_id"), "reason": sample.get("alignment_reason", "not aligned")}); continue
        annotation = ROOT / sample["annotation_path"]; video = ROOT / sample["video_path"]
        if not annotation.is_file() or not video.is_file():
            excluded.append({"sample_id": sample.get("sample_id"), "reason": "missing annotation or video"}); continue
        gt = normalize_events(json.loads(annotation.read_text()), sample["annotation_path"]); offset = float(sample.get("clip_offset_seconds", 0))
        for item in gt: item["start_time"] += offset; item["end_time"] += offset; item["center_time"] += offset
        for method in methods:
            prediction_path = prediction_root / method / f"{sample['sample_id']}.json"
            if not prediction_path.is_file(): excluded.append({"sample_id": sample.get("sample_id"), "method": method, "reason": "prediction missing"}); continue
            preds = json.loads(prediction_path.read_text()).get("events", [])
            for tolerance in (1.0, 2.0, 3.0):
                score = one_to_one_match(preds, gt, tolerance); key = f"{sample['sample_id']}:{method}:±{tolerance:g}s"; details[key] = score
                rows.append({"sample_id": sample["sample_id"], "method": method, "tolerance_seconds": tolerance, **{k: score[k] for k in ("TP", "FP", "FN", "precision", "recall", "f1")}})
    (destination / "match_details.json").write_text(json.dumps(details, ensure_ascii=False, indent=2), encoding="utf-8")
    (destination / "exclusions.json").write_text(json.dumps(excluded, ensure_ascii=False, indent=2), encoding="utf-8")
    with (destination / "metrics.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["sample_id", "method", "tolerance_seconds", "TP", "FP", "FN", "precision", "recall", "f1"]); writer.writeheader(); writer.writerows(rows)
    return {"status": "COMPLETED" if rows else "BLOCKED_OR_NO_ALIGNED_SAMPLES", "scored_rows": len(rows), "excluded_samples": excluded}
