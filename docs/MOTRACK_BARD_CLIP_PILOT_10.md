# MoTrack BARD 10-clip exploratory pilot

Date: 2026-11-06
Scope: frozen, local-only comparison of HypeCut-only, Lightweight V1 and Lightweight V2 on ten short, officially sourced BARD clips. This is not an extension of the paused PL-NBA evaluator.

## Protocol

- BARD labels are joined by exact upstream relative MP4 path in `dataset_paths.csv`.
- Five clips contain `2PT Shot`, `3PT Shot`, `Layup`, or `Dunk`; five have none of those documented labels.
- Four feasibility clips were reused and exactly six further BARD clips were downloaded. No other media were downloaded.
- V1 and V2 use existing X3D-XS weights, mappings and thresholds. No training, calibration, cloud API, Agent, web, or upstream HypeCut change occurred.
- HypeCut uses the existing `basketball-broadcast` profile and is reported only as `SIGNAL_ONLY` proposal coverage, never as a shot classifier.
- BARD labels are clip-level, not in-clip action boundaries. Metrics are clip-level documented-shot presence, not temporal localization or make/miss evaluation.

## Actual run status

All **10/10** MP4 files were decoded and processed by HypeCut, V1, and V2. Every V2 window contained exactly four sampled frames, and V1 had zero window decode failures. For X3D dense-scan signals only, HypeCut segments were clipped at `video_duration - 1.6 s`; original HypeCut plans were retained unchanged for coverage reporting. This prevents invalid starts too close to a short clip's end.

| Path suffix | Duration | Official clip labels | HypeCut candidates | V1 | V2 |
|---|---:|---|---:|---|---|
| `2.mp4` | 9.250 s | 3PT Shot, Rebound | 0 | TP | FN |
| `4.mp4` | 8.583 s | 2PT Shot, Rebound | 1 | TP | FN |
| `13.mp4` | 8.317 s | 2PT Shot | 0 | TP | FN |
| `25.mp4` | 8.517 s | 2PT Shot, Block, Rebound | 1 | TP | FN |
| `28.mp4` | 8.583 s | 3PT Shot | 0 | TP | FN |
| `19.mp4` | 8.317 s | Foul | 1 | FP | TN |
| `37.mp4` | 8.150 s | Turnover | 0 | FP | TN |
| `17.mp4` | 9.117 s | Free Throw | 1 | FP | TN |
| `20.mp4` | 6.450 s | Free Throw | 0 | TN | TN |
| `34.mp4` | 7.117 s | Foul, Foul | 1 | FP | TN |

`FP` means a predicted `shot_attempt` on a clip without a documented shot label. It is not proof that the image contains no shooting-like action: BARD clips can contain multiple actions and no manual annotation was added.

## Metrics (exploratory only)

| Variant | TP | FP | TN | FN | Precision | Recall | F1 | Accuracy |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Lightweight V1 | 5 | 4 | 1 | 0 | 0.556 | 1.000 | 0.714 | 0.600 |
| Lightweight V2 | 0 | 0 | 5 | 5 | undefined (no positive predictions) | 0.000 | undefined | 0.500 |

HypeCut-only produced a proposal for 2/5 documented-shot clips and 3/5 label-negative clips. This is proposal coverage only, not semantic precision/recall.

## Error diagnosis

V1 emits `shot_attempt` whenever `shooting basketball` appears anywhere in X3D's Top-5. Relevant V1 softmax values ranged from **0.000621** to **0.036334**, including label-negative clips. This explains its four exploratory false positives: `19.mp4`, `37.mp4`, `17.mp4`, and `34.mp4`.

V2 retains `shooting_min_softmax=0.12`. All V2 scores were below it: the highest was **0.025692** on label-negative `17.mp4`, while the highest documented-shot score was only **0.018677** on `25.mp4`. V2 therefore emitted no shot candidates and missed all five documented-shot clips.

The immediate contrast is mapping/threshold policy: V1 accepts any Top-5 presence; V2 requires 0.12. More fundamentally, low Kinetics-400 scores overlap between documented-shot and label-negative clips, so this generic class is not a calibrated basketball-shot detector. Short-clip sampling was correct, so no sampling failure explains the result.

With ten clips, this does not show either variant is generally better and does not alter the default model. No parameter was tuned after seeing results.

## Reproducible artifacts

- `run_bard_clip_pilot.py`: isolated runner; creates no web or Agent state.
- `outputs/lightweight_bard_pilot_10/experiment_config.json`: frozen paths and protocol.
- `outputs/lightweight_bard_pilot_10/sample_results.json`: labels, durations, outcomes, counts and timing.
- `outputs/lightweight_bard_pilot_10/samples/<id>/v1_predictions.json`: V1 raw-window Top-5 evidence.
- `outputs/lightweight_bard_pilot_10/samples/<id>/v2_raw_window_predictions.json`: V2 window evidence and timestamps.
- `outputs/lightweight_bard_pilot_10/samples/<id>/hypecut_candidates.json`: unmodified upstream signal plans.
