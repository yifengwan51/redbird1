#!/usr/bin/env python3
"""PL-NBA feasibility discovery and aligned-manifest evaluator (no video download)."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from integrations.benchmark import ROOT, discover, evaluate_manifest

OUT = ROOT / "outputs" / "lightweight_benchmark"
SOURCE = OUT / "source" / "extracted" / "PL-NBA-JSON"
parser = argparse.ArgumentParser()
sub = parser.add_subparsers(dest="cmd", required=True)
sub.add_parser("discover")
evaluate = sub.add_parser("evaluate")
evaluate.add_argument("--manifest", type=Path, required=True)
evaluate.add_argument("--predictions", type=Path, required=True)
args = parser.parse_args()
OUT.mkdir(parents=True, exist_ok=True)
if args.cmd == "discover":
    data = discover(SOURCE)
    (OUT / "annotation_inventory.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"files": data["annotation_file_count"], "games": data["game_count"], "shot_events": data["shot_event_count"]}, ensure_ascii=False))
else:
    print(json.dumps(evaluate_manifest(json.loads(args.manifest.read_text()), args.predictions, OUT), ensure_ascii=False, indent=2))
