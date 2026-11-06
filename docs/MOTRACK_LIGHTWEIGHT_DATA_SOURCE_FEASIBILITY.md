# MoTrack Lightweight: data-source feasibility

Date: 2026-11-06
Scope: identify a legally accessible, label-aligned small basketball sample for
future frozen HypeCut-only / Lightweight V1 / Lightweight V2 comparison.  This
does **not** extend the paused PL-NBA framework and does not report accuracy.

## Result

| Source | Actual access | Video–label relation | Downloaded | Usable metric now |
|---|---|---|---:|---|
| BARD | Public official Hugging Face files | Exact file-path key in upstream `dataset_paths.csv` | 4 MP4 / 26,571,676 bytes | Clip-level shot-presence only |
| MultiSports | Metadata public, file access gated | Documented frame-indexed action tubes | 0 | None until a licensed account accepts the gate and a small aligned subset is available |
| PL-NBA | Existing JSON retained; no aligned local video | Not established | 0 new video | None |

## BARD verification

The BARD project describes 14,676 final clips and publishes video clips on its
official Hugging Face repository under CC BY 4.0.  Its upstream
`dataset/dataset_paths.csv` has one relative video path plus structured action
labels per row.  The Hugging Face repository uses the same game-directory and
MP4 path convention.  Therefore this is a direct, auditable file-to-label
join, rather than a title- or time-based inference.

Downloaded and checked with the project FFprobe:

| Relative source path | Labels | Duration | Bytes | Label class |
|---|---|---:|---:|---|
| `bkn-vs-det-0022400861/2.mp4` | `3PT Shot`, `Rebound` | 9.250 s | 7,148,212 | shot-present |
| `bkn-vs-det-0022400861/4.mp4` | `2PT Shot`, `Rebound` | 8.583 s | 6,833,538 | shot-present |
| `bkn-vs-det-0022400861/19.mp4` | `Foul` | 8.317 s | 6,452,185 | no shot label |
| `bkn-vs-det-0022400861/37.mp4` | `Turnover` | 8.150 s | 6,137,741 | no shot label |

All four downloads matched the SHA-256 object digest declared by Hugging Face
LFS and are listed with local SHA-256 plus FFprobe metadata in
`outputs/lightweight_data_feasibility/bard/samples/manifest.json`.

### Boundary of the BARD ground truth

The retrieved BARD labels are **clip-level multi-label annotations**.  They do
not define the start/end frame of each action inside a clip.  Consequently:

- valid: clip-level binary/label-set metrics such as whether a clip contains
  one of `2PT Shot`, `3PT Shot`, `Layup`, or `Dunk`;
- invalid: event localization TP/FP/FN at ±1/±2/±3 seconds, or treating a
  model candidate timestamp as a BARD ground-truth timestamp.

The four clips validate the source and mapping only; they are too small and
from one game to yield meaningful quality claims.

## MultiSports check

MultiSports documents raw frames and `multisports_GT.pkl`; its GT has class
names, video IDs, frame counts, and per-frame action tubes.  Basketball labels
include pass, drive, dribble, 3-point shot, 2-point shot, free throw, rebound,
steal, and related actions.  Thus, if access is granted, it can support real
temporal localization evaluation after a frame-rate/alignment check.

At this check, the official Hugging Face repository required login and
acceptance of CC BY-NC 4.0 conditions before its content could be accessed.
The repository reports 65.1 GB and its documented primary media archive is
`rawframes.tar`.  No condition was bypassed, no archive was downloaded, and
no permission-restricted URL was used.  It is therefore not yet a usable
small-sample source in this workspace.

## Lowest-cost next experiment

Create a **frozen BARD clip-level pilot manifest** with 40 clips: 20 with at
least one documented shot label (`2PT Shot`, `3PT Shot`, `Layup`, or `Dunk`)
and 20 with none.  The existing four verified files show typical storage of
about 6--7 MB per clip, so this is expected to be a few hundred MB, not an
archive-scale download.  Before execution, freeze selection by deterministic
path order or random seed and retain the manifest.

Run HypeCut-only, V1, and V2 unmodified.  For V1/V2, report clip-level
shot-candidate detection against the BARD clip label.  HypeCut-only has no
semantic shot label; report it separately as clip-level highlight-proposal
coverage, never as a shot-recognition precision/recall score.  Do not tune
thresholds on the pilot.  A later held-out manifest is required for any tuning
or comparative conclusion.

## Isolation and non-actions

- No cloud API call, model download, model retraining, threshold change, or
  web/Agent/HypeCut modification occurred.
- No PL-NBA code or artifacts were altered; its existing JSON feasibility
  evidence remains retained.
- No MultiSports data was downloaded.
