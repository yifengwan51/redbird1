#!/usr/bin/env python3
"""Run the auditable local Lightweight V2 pipeline without network APIs."""
from __future__ import annotations

import argparse
import json

from integrations.lightweight_v2 import run_comparison, v2_events


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("video_id", choices=["cbf", "doug"])
    parser.add_argument("--duration", type=float, default=15)
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(json.dumps(v2_events(args.video_id, force=args.force) if args.audit_only else run_comparison(args.video_id, args.duration, args.force), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
