#!/usr/bin/env python3
"""CLI entry point for the offline lightweight MoTrack Agent."""
from __future__ import annotations
import argparse
import json
from integrations.lightweight import LightweightSession, analyze

parser = argparse.ArgumentParser(description="MoTrack local X3D + deterministic Agent")
parser.add_argument("video_id", choices=["cbf", "doug"])
parser.add_argument("message", nargs="?", help="A supported Chinese command")
parser.add_argument("--analyze", action="store_true", help="Run/cache local X3D analysis only")
parser.add_argument("--force", action="store_true", help="Re-run local X3D instead of cache")
args = parser.parse_args()
if args.analyze:
    print(json.dumps(analyze(args.video_id, force=args.force), ensure_ascii=False, indent=2))
elif args.message:
    session = LightweightSession(video_id=args.video_id)
    print(json.dumps(session.ask(args.message), ensure_ascii=False, indent=2))
else:
    parser.error("provide --analyze or a supported message")
