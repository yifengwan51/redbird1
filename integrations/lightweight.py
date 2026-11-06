"""Local X3D candidate analysis and a deterministic, no-network MoTrack agent.

This module deliberately treats Kinetics-400 labels as *action evidence*, not as
ground truth for basketball outcomes.  It is an extension of HypeCut's existing
signals: low-rate whole-video windows prevent HypeCut-only blind spots, while
dense windows around HypeCut segments add temporal evidence where it matters.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "lightweight"
FFMPEG = ROOT / "tools" / "ffmpeg" / "bin" / "ffmpeg"
FFPROBE = ROOT / "tools" / "ffmpeg" / "bin" / "ffprobe"
TORCH_HOME = ROOT / ".cache" / "torch"
LABELS_PATH = ROOT / ".cache" / "lightweight" / "kinetics_classnames.json"
VIDEO_IDS = {
    "cbf": ROOT / "inputs" / "cbf_3x3_tour.mp4",
    "doug": ROOT / "inputs" / "doug_mcdermott.mp4",
}
HYPECUT = {
    "cbf": ROOT / "outputs" / "real" / "cbf" / "sports-broadcast.json",
    "doug": ROOT / "outputs" / "real" / "doug" / "sports-broadcast.json",
}
EVENT_TYPES = {"shot_attempt", "made_basket", "missed_shot", "pass", "rebound", "steal", "fast_break", "UNKNOWN", "basketball_action_candidate"}
ALIASES = {"shot": "shot_attempt", "shoot": "shot_attempt", "投篮": "shot_attempt", "出手": "shot_attempt", "命中": "made_basket", "得分": "made_basket"}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _json(path: Path, default: Any) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default


def _video_info(video: Path) -> dict[str, Any]:
    raw = subprocess.check_output([str(FFPROBE), "-v", "error", "-show_entries", "format=duration:stream=codec_type,r_frame_rate", "-of", "json", str(video)], text=True)
    data = json.loads(raw)
    duration = float(data["format"]["duration"])
    return {"duration": duration, "streams": data.get("streams", []), "probe": data}


class X3D:
    """Official PyTorchVideo Hub X3D-XS, cached strictly inside this project."""
    def __init__(self) -> None:
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.labels = {int(v): k.strip('"') for k, v in _json(LABELS_PATH, {}).items()}
        if not self.labels:
            raise RuntimeError("missing official Kinetics label cache")
        os.environ["TORCH_HOME"] = str(TORCH_HOME)
        before = torch.cuda.memory_allocated() if self.device.type == "cuda" else 0
        started = time.perf_counter()
        # skip_validation avoids GitHub API credentials; Hub source and checkpoint
        # are already downloaded from their official URLs into project cache.
        self.model = torch.hub.load("facebookresearch/pytorchvideo", "x3d_xs", pretrained=True, trust_repo=True, skip_validation=True).eval().to(self.device)
        self.load_seconds = round(time.perf_counter() - started, 3)
        self.memory_bytes = int(torch.cuda.memory_allocated() - before) if self.device.type == "cuda" else 0

    def _input(self, frames: list[np.ndarray]) -> torch.Tensor:
        # Hub documentation for X3D-XS: 4 frames x sample rate 12, crop 182.
        tensor = torch.from_numpy(np.stack([cv2.cvtColor(x, cv2.COLOR_BGR2RGB) for x in frames])).permute(3, 0, 1, 2).float() / 255.0
        tensor = (tensor - torch.tensor([0.45, 0.45, 0.45])[:, None, None, None]) / torch.tensor([0.225, 0.225, 0.225])[:, None, None, None]
        # Resize short side to 182 then center crop: no torchvision-video API
        # dependency, and exactly the documented X3D spatial preprocessing.
        _, _, h, w = tensor.shape
        scale = 182 / min(h, w)
        tensor = torch.nn.functional.interpolate(tensor.permute(1, 0, 2, 3), size=(round(h * scale), round(w * scale)), mode="bilinear", align_corners=False).permute(1, 0, 2, 3)
        _, _, h, w = tensor.shape
        y, x = (h - 182) // 2, (w - 182) // 2
        return tensor[:, :, y:y + 182, x:x + 182].unsqueeze(0).to(self.device)

    def classify_detailed(self, frames: list[np.ndarray]) -> dict[str, Any]:
        tensor = self._input(frames)
        with torch.inference_mode():
            logits = self.model(tensor)[0]
            scores = torch.softmax(logits, dim=0)
        values, indices = scores.topk(5)
        top5 = [{"label": self.labels.get(int(i), f"class_{int(i)}"), "class_id": int(i),
                 "logit": round(float(logits[int(i)]), 6), "softmax_score": round(float(v), 6)}
                for v, i in zip(values.detach().cpu(), indices.detach().cpu())]
        return {"top5": top5, "input_shape": list(tensor.shape), "score_type": "softmax(logits)"}

    def classify(self, frames: list[np.ndarray]) -> list[dict[str, Any]]:
        """V1 compatibility: retain its legacy field while V2 uses detailed audit."""
        return [{"label": x["label"], "class_id": x["class_id"], "raw_model_score": x["softmax_score"]}
                for x in self.classify_detailed(frames)["top5"]]


def _frames(video: Path, start: float, duration: float = 1.6) -> tuple[list[np.ndarray], list[float]]:
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise RuntimeError(f"cannot decode {video.name}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frames, times = [], []
    for offset in (0.0, duration / 3, duration * 2 / 3, duration):
        t = start + offset
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        if not ok:
            continue
        frames.append(frame)
        times.append(round(t, 3))
    cap.release()
    if len(frames) != 4:
        raise RuntimeError("insufficient decodable frames for X3D window")
    return frames, times


def _hype_segments(video_id: str) -> list[dict[str, Any]]:
    return _json(HYPECUT[video_id], {}).get("segments", [])


def _windows(video_id: str, duration: float) -> list[tuple[float, str, dict[str, Any] | None]]:
    # 8 s global cadence, augmented at 2 s cadence near HypeCut candidates.
    merged: dict[int, tuple[float, str, dict[str, Any] | None]] = {}
    for t in np.arange(0.0, max(0.1, duration - 1.7), 8.0):
        merged[round(float(t) * 10)] = (float(t), "full_video_low_frequency", None)
    for segment in _hype_segments(video_id):
        for t in np.arange(float(segment["start"]), float(segment["end"]), 2.0):
            key = round(float(t) * 10)
            merged[key] = (float(t), "hypecut_dense", segment)
    return [merged[k] for k in sorted(merged)]


def _event_from_window(video_id: str, start: float, times: list[float], top: list[dict[str, Any]], source: str, segment: dict[str, Any] | None) -> dict[str, Any] | None:
    basketball = [x for x in top if "basketball" in x["label"]]
    if not basketball:
        return None
    # A shooting label may be lower-ranked than the broad "playing basketball"
    # class. Keep that evidence explicitly, but never upgrade it to a confirmed
    # outcome.  The selected score remains the raw score for the matched label.
    shot = next((x for x in basketball if x["label"] == "shooting basketball"), None)
    primary = shot or basketball[0]
    label = primary["label"]
    event_type = "shot_attempt" if shot else "basketball_action_candidate"
    return {
        "event_id": f"lw-{video_id}-{round(start * 10):05d}",
        "source_video_id": video_id,
        "video_path": str(VIDEO_IDS[video_id].relative_to(ROOT)),
        "event_type": event_type,
        "start_time": round(times[0], 3),
        "end_time": round(times[-1], 3),
        "raw_model_score": primary["raw_model_score"],
        "score_kind": "Kinetics-400 softmax; not a calibrated basketball-event probability",
        "source_model": "PyTorchVideo X3D-XS (Kinetics-400)",
        "model_version": "pytorchvideo hub main / X3D_XS.pyth",
        "visual_action_evidence": {"top5": top, "matched_label": label, "frame_timestamps": times},
        "hypecut_signal": {"sampling": source, "segment_score": segment.get("score") if segment else None, "reasons": segment.get("reasons") if segment else {}},
        "evidence_source": "LOCAL_X3D",
        "verification_status": "MODEL_PREDICTED",
        "semantic_limit": "Generic Kinetics action evidence only; this does not verify a made/missed basket, steal, rebound, player, team, or possession.",
        "time_localization_method": "1.6s X3D sample window",
    }


def _merge(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for event in sorted(events, key=lambda x: (x["start_time"], -x["raw_model_score"])):
        if result and event["event_type"] == result[-1]["event_type"] and event["start_time"] - result[-1]["end_time"] <= 2.0:
            if event["raw_model_score"] > result[-1]["raw_model_score"]:
                result[-1] = event
            continue
        result.append(event)
    return result


def analyze(video_id: str, force: bool = False) -> dict[str, Any]:
    if video_id not in VIDEO_IDS:
        raise ValueError("unknown video id")
    latest = OUT / f"latest_{video_id}.json"
    if latest.exists() and not force:
        return _json(latest, {})
    OUT.mkdir(parents=True, exist_ok=True)
    video = VIDEO_IDS[video_id]
    info = _video_info(video)
    started = time.perf_counter()
    runner = X3D()
    raw, failures = [], []
    for start, sampling, segment in _windows(video_id, info["duration"]):
        try:
            frames, times = _frames(video, start)
            top = runner.classify(frames)
            event = _event_from_window(video_id, start, times, top, sampling, segment)
            if event:
                raw.append(event)
        except Exception as exc:
            failures.append({"start_time": start, "error": type(exc).__name__})
    elapsed = time.perf_counter() - started
    events = _merge(raw)
    payload = {
        "schema_version": "1.0", "run_id": f"lw-{video_id}-{_now()}", "source_video_id": video_id,
        "source_video": str(video.relative_to(ROOT)), "events": events,
        "hypecut_only_baseline": {"candidate_count": len(_hype_segments(video_id)), "segments": _hype_segments(video_id)},
        "performance": {"device": str(runner.device), "model_load_seconds": runner.load_seconds, "gpu_memory_model_bytes": runner.memory_bytes,
                        "inference_total_seconds": round(elapsed, 3), "seconds_per_video_minute": round(elapsed / (info["duration"] / 60), 3),
                        "windows": len(_windows(video_id, info["duration"])), "raw_candidates": len(raw), "merged_candidates": len(events), "failures": failures},
        "limitations": "No human ground truth was used: Precision/Recall/F1 are UNVERIFIED.",
    }
    stamped = OUT / f"{payload['run_id']}.json"
    stamped.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    latest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def events(video_id: str, analyze_if_missing: bool = False) -> list[dict[str, Any]]:
    latest = OUT / f"latest_{video_id}.json"
    if not latest.exists() and analyze_if_missing:
        analyze(video_id)
    return _json(latest, {"events": []}).get("events", [])


def render_plan(video_id: str, plan: dict[str, Any], destination: Path) -> dict[str, Any]:
    clips = plan.get("clips", [])
    if not clips:
        raise ValueError("empty highlight plan")
    duration = _video_info(VIDEO_IDS[video_id])["duration"]
    for clip in clips:
        if not 0 <= float(clip["start_time"]) < float(clip["end_time"]) <= duration:
            raise ValueError("clip outside source video")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # A single timeline span preserves audio/video sync and avoids custom FFmpeg logic.
    start = min(float(x["start_time"]) for x in clips)
    end = max(float(x["end_time"]) for x in clips)
    target = min(float(plan.get("target_duration", end - start)), end - start)
    end = start + target
    began = time.perf_counter()
    subprocess.run([str(FFMPEG), "-y", "-v", "error", "-ss", str(start), "-to", str(end), "-i", str(VIDEO_IDS[video_id]), "-c:v", "libx264", "-c:a", "aac", "-movflags", "+faststart", str(destination)], check=True)
    probe = json.loads(subprocess.check_output([str(FFPROBE), "-v", "error", "-show_entries", "format=duration:stream=codec_type,codec_name", "-of", "json", str(destination)], text=True))
    return {"path": str(destination.relative_to(ROOT)), "duration": float(probe["format"]["duration"]), "probe": probe, "render_seconds": round(time.perf_counter() - began, 3)}


@dataclass
class LightweightSession:
    video_id: str = "cbf"
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    candidate_version: str = "v1"
    plan: dict[str, Any] | None = None
    traces: list[dict[str, Any]] = field(default_factory=list)
    state: str = "INTENT_PARSED"
    output_dir: Path = field(init=False)

    def __post_init__(self) -> None:
        self.output_dir = ROOT / "outputs" / "lightweight_agent" / self.session_id
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _trace(self, tool: str, result: Any) -> None:
        self.traces.append({"initiator": "CONTROLLER", "tool": tool, "result": result, "state": self.state})

    def _events(self) -> list[dict[str, Any]]:
        if self.candidate_version == "v1":
            return events(self.video_id, analyze_if_missing=True)
        from integrations.lightweight_v2 import candidates_for_variant
        return candidates_for_variant(self.video_id, self.candidate_version)

    @staticmethod
    def _score(item: dict[str, Any]) -> float:
        return float(item.get("final_ranking_score", item.get("raw_model_score", 0.0)))

    def _make_plan(self, selected: list[dict[str, Any]], target: float = 20.0, max_clips: int = 3) -> dict[str, Any]:
        if not selected:
            raise ValueError("没有满足条件的本地动作候选")
        # Keep a renderable local timeline.  Ranking distant Kinetics windows and
        # then taking their enclosing span would otherwise create a long, mostly
        # unrelated clip before duration trimming.  This is deterministic, not a
        # claim that the selected windows form a verified possession.
        ranked = sorted(selected, key=self._score, reverse=True)
        anchor = ranked[0]
        nearby = [x for x in ranked if abs(x["start_time"] - anchor["start_time"]) <= max(4.0, target / 2)]
        selected = sorted(nearby[:max(1, min(max_clips, 8))], key=lambda x: x["start_time"])
        clips = []
        for item in selected:
            clips.append({"event_id": item["event_id"], "start_time": max(0, item["start_time"] - 2), "end_time": item["end_time"] + 2,
                          "event_type": item["event_type"], "raw_model_score": self._score(item), "verification_status": item["verification_status"]})
        self.plan = {"schema_version": "1.0", "source_video_id": self.video_id, "target_duration": target, "clips": clips,
                     "evidence_status": "MODEL_PREDICTED", "note": "Local generic-action candidates; no basket outcome is confirmed."}
        self.state = "PLAN_CREATED"; self._trace("create_highlight_plan", self.plan)
        (self.output_dir / "highlight_plan.json").write_text(json.dumps(self.plan, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.plan

    @staticmethod
    def _duration_from_text(text: str) -> float | None:
        match = re.search(r"(\d+(?:\.\d+)?)\s*(?:秒|s\b)", text, re.I)
        return float(match.group(1)) if match else None

    @staticmethod
    def _count_from_text(text: str) -> int:
        match = re.search(r"(\d+)\s*(?:个|段|片段|条)", text)
        if match:
            return int(match.group(1))
        for word, value in {"一个": 1, "两个": 2, "三个": 3, "四个": 4, "五个": 5}.items():
            if word in text:
                return value
        return 3

    def _write_plan(self) -> None:
        if self.plan:
            (self.output_dir / "highlight_plan.json").write_text(json.dumps(self.plan, ensure_ascii=False, indent=2), encoding="utf-8")

    def _render(self) -> dict[str, Any]:
        if not self.plan:
            raise ValueError("尚无剪辑计划")
        result = render_plan(self.video_id, self.plan, self.output_dir / "highlights.mp4")
        self.state = "RENDER_COMPLETED"; self._trace("render_highlights", result)
        self.state = "OUTPUT_VERIFIED"; self._trace("verify_render", result["probe"])
        return result

    def ask(self, message: str) -> dict[str, Any]:
        """Execute a supported local command using state, rather than canned answers."""
        text = message.strip().lower()
        if not text:
            return self._save("请输入一条轻量 Agent 支持的命令。", {})
        try:
            items = self._events()
            self._trace("get_video_info", {"video_id": self.video_id, "candidate_version": self.candidate_version, "events_available": len(items)})
            is_shot = any(x in text for x in ("投篮", "出手", "shot", "shoot"))
            duration = self._duration_from_text(text)
            is_outcome_question = any(x in text for x in ("命中", "进了", "进球", "得分", "made")) and is_shot
            is_search = any(x in text for x in ("找出", "查找", "搜索", "查看", "关键事件", "有哪些"))
            is_shorten = any(x in text for x in ("缩短", "再短", "剪成", "压缩"))
            is_recap = any(x in text for x in ("解释", "复盘", "分析", "说明"))
            is_export = any(x in text for x in ("导出", "下载", "保存视频"))
            is_generate = any(x in text for x in ("生成", "提取", "剪辑", "帮我剪", "高光", "精彩片段", "最精彩"))

            if is_outcome_question:
                found = [x for x in items if x["event_type"] == "shot_attempt"]
                self.state = "EVENTS_RETRIEVED"
                self._trace("search_events", {"event_type": "shot_attempt", "count": len(found), "outcome_check": True})
                return self._save(f"当前有 {len(found)} 个疑似投篮候选，但 X3D 的通用动作证据不包含篮筐结果，不能判断这些投篮是否命中。所有候选仍为 MODEL_PREDICTED。", {"events": found})

            if is_shorten:
                if not self.plan:
                    # “把视频剪成15秒” is naturally an initial creation
                    # request, whereas “缩短/再短一点” needs prior state.
                    if duration is not None and any(x in text for x in ("剪成", "剪辑")):
                        is_shorten = False
                        is_generate = True
                    else:
                        return self._save("无法缩短：当前会话没有已有剪辑计划。请先生成高光，随后再使用“缩短到15秒”。", {"failure": {"stage": "STATE_CHECK", "retryable": True}})
                if is_shorten:
                    current = float(self.plan["target_duration"])
                    target = duration if duration is not None else max(5.0, current - 5.0)
                    if not 5 <= target <= 60:
                        return self._save("目标时长必须在 5 到 60 秒之间，当前计划未修改。", {"failure": {"stage": "PARAMETER_VALIDATION", "retryable": True}})
                    self.plan["target_duration"] = target
                    self._write_plan()
                    self._trace("update_highlight_plan", {"target_duration": target, "previous_duration": current})
                    output = self._render()
                    return self._save(f"已修改当前会话的既有计划为最多 {target:g} 秒，未重新扫描原视频；已重新渲染并通过 FFprobe 验证。", {"output": output, "plan": self.plan})

            if is_export and self.plan and not is_generate:
                output = self._render()
                return self._save("已导出现有剪辑计划并通过 FFprobe 验证。", {"output": output, "plan": self.plan})

            if is_search:
                found = [x for x in items if not is_shot or x["event_type"] == "shot_attempt"]
                self.state = "EVENTS_RETRIEVED"
                self._trace("search_events", {"event_type": "shot_attempt" if is_shot else None, "count": len(found)})
                reply = f"找到 {len(found)} 个本地模型动作候选。它们均为 MODEL_PREDICTED，不能用于确认进球、抢断或球员身份。"
                return self._save(reply, {"events": found})

            if is_recap:
                selected = self.plan["clips"] if self.plan else []
                recap = {"source_video_id": self.video_id, "events": selected, "verification_status": "MODEL_PREDICTED", "summary": "本地 X3D 仅提供通用 Kinetics 动作候选，不能确认投篮是否命中或完整回合关系。"}
                self._trace("generate_recap", recap)
                (self.output_dir / "match_recap.json").write_text(json.dumps(recap, ensure_ascii=False, indent=2), encoding="utf-8")
                prefix = "基于当前高光计划，" if self.plan else "当前尚未生成高光；"
                return self._save(prefix + recap["summary"], {"recap": recap})

            if is_generate:
                selected = [x for x in items if not is_shot or x["event_type"] == "shot_attempt"]
                max_clips = self._count_from_text(text) if any(x in text for x in ("最精彩", "保留", "片段")) else 3
                target = duration if duration is not None else 20.0
                if not 5 <= target <= 60:
                    return self._save("目标时长必须在 5 到 60 秒之间。", {"failure": {"stage": "PARAMETER_VALIDATION", "retryable": True}})
                plan = self._make_plan(selected, target, max_clips)
                output = self._render()
                return self._save("已根据本地 X3D 动作候选建立计划、完成 FFmpeg 渲染并用 FFprobe 验证。事件均未经过人工确认。", {"plan": plan, "output": output})

            return self._save("轻量 Agent 支持：生成篮球/投篮高光、提取精彩片段、找出疑似投篮、缩短/剪成 N 秒、保留最精彩 N 个片段、查看关键事件、解释视频、判断投篮证据和导出视频。开放式体育事实问答不在本地规则 Agent 的能力范围内。", {"failure": {"stage": "INTENT_PARSE", "retryable": False}})
        except Exception as exc:
            failure = {"stage": self.state, "error_type": type(exc).__name__, "message": str(exc), "retryable": isinstance(exc, (RuntimeError, OSError, subprocess.SubprocessError))}
            self._trace("agent_failure", failure)
            return self._save("本地 Agent 在“%s”阶段失败：%s。%s" % (failure["stage"], failure["error_type"], "可以重试。" if failure["retryable"] else "请检查输入后重试。"), {"failure": failure})

    def _save(self, reply: str, extra: dict[str, Any]) -> dict[str, Any]:
        self.state = "TASK_COMPLETED" if (self.output_dir / "highlights.mp4").exists() else self.state
        (self.output_dir / "tool_trace.json").write_text(json.dumps(self.traces, ensure_ascii=False, indent=2), encoding="utf-8")
        (self.output_dir / "session_history.json").write_text(json.dumps({"video_id": self.video_id, "state": self.state}, ensure_ascii=False, indent=2), encoding="utf-8")
        (self.output_dir / "run_summary.json").write_text(json.dumps({"mode": "lightweight", "candidate_version": self.candidate_version, "state": self.state, "tool_calls": len(self.traces), "cloud_api_calls": 0}, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"reply": reply, "session_id": self.session_id, "mode": "lightweight", "candidate_version": self.candidate_version, "artifacts": str(self.output_dir.relative_to(ROOT)), "state": self.state, **extra}
