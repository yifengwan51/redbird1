#!/usr/bin/env python3
"""Run the auditable local Lightweight V2 pipeline without network APIs."""
from __future__ import annotations
import argparse,json
from integrations.lightweight_v2 import run_comparison,v2_events
p=argparse.ArgumentParser();p.add_argument('video_id',choices=['cbf','doug']);p.add_argument('--duration',type=float,default=15);p.add_argument('--audit-only',action='store_true');p.add_argument('--force',action='store_true');a=p.parse_args()
print(json.dumps(v2_events(a.video_id,force=a.force) if a.audit_only else run_comparison(a.video_id,a.duration,a.force),ensure_ascii=False,indent=2))
