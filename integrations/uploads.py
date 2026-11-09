"""Videos uploaded from a phone or browser: chunked upload, normalise, analyse.

Phone clips are often HEVC, 60 fps, rotated by metadata or variable frame
rate.  Every upload is transcoded once to the editor's house format (H.264,
<=1280 px long side, 30 fps, AAC), so playback, frame sampling and the
renderer behave exactly as for the built-in sources.  Uploads arrive in 8 MB
chunks because the public tunnel limits request bodies.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from . import lightweight as lw

ROOT = lw.ROOT
UPLOADS = ROOT / "inputs" / "uploads"
ID_RE = re.compile(r"^u[0-9a-f]{10}$")
CHUNK = 8 * 1024 * 1024
MAX_BYTES = 1024 * 1024 * 1024
MAX_UPLOADS = 30
MIN_SECONDS, MAX_SECONDS = 3.0, 20 * 60.0
VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm", ".3gp", ".mkv"}
_lock = threading.Lock()
_live: dict[str, dict[str, Any]] = {}      # progress kept in memory, merged over the meta file
on_ready: list[Callable[[], None]] = []     # called when an upload becomes editable or is removed


class OffsetMismatch(ValueError):
    def __init__(self, expected: int):
        super().__init__(f"expected offset {expected}")
        self.expected = expected


def _meta_path(uid: str) -> Path:
    return UPLOADS / f"{uid}.json"


def _raw_path(uid: str) -> Path:
    return UPLOADS / f".{uid}.part"


def video_path(uid: str) -> Path:
    return UPLOADS / f"{uid}.mp4"


def _read(uid: str) -> dict[str, Any] | None:
    if not ID_RE.match(uid or ""):
        return None
    try:
        return json.loads(_meta_path(uid).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write(meta: dict[str, Any]) -> None:
    UPLOADS.mkdir(parents=True, exist_ok=True)
    path = _meta_path(meta["id"])
    part = path.with_name(f".{uuid.uuid4().hex[:6]}_{path.name}")
    part.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    os.replace(part, path)


def get(uid: str) -> dict[str, Any] | None:
    meta = _read(uid)
    return None if meta is None else {**meta, **_live.get(uid, {})}


def all_uploads() -> list[dict[str, Any]]:
    if not UPLOADS.is_dir():
        return []
    items = [get(p.stem) for p in UPLOADS.glob("u*.json") if ID_RE.match(p.stem)]
    return sorted((m for m in items if m), key=lambda m: m.get("created_ts", 0), reverse=True)


def register_ready() -> None:
    """Make every finished upload editable (called at start-up)."""
    for meta in all_uploads():
        if meta.get("status") == "ready" and video_path(meta["id"]).is_file():
            lw.VIDEO_IDS[meta["id"]] = video_path(meta["id"])
        elif meta.get("status") in ("processing", "analyzing"):
            # The server stopped mid-way; the raw file may be gone.
            meta.update(status="failed", error="处理被中断，请重新上传")
            _write(meta)
def _title(filename: str) -> str:
    stem = re.sub(r"[^\w一-鿿 ()-]+", " ", Path(filename or "").stem).strip()
    # Phone names like IMG_4821 say nothing; use the upload time instead.
    if not stem or re.fullmatch(r"(IMG|VID|MOV|PXL|DSC)[_ -]?\d+.*", stem, re.I):
        return "我的视频 " + datetime.now().strftime("%m-%d %H:%M")
    return stem[:30]


def start(filename: str, size: int) -> dict[str, Any]:
    suffix = Path(filename or "").suffix.lower()
    if suffix not in VIDEO_SUFFIXES:
        raise ValueError("请选择视频文件（MP4 / MOV / WebM）")
    if not 0 < int(size) <= MAX_BYTES:
        raise ValueError("视频不能超过 1GB")
    if len(all_uploads()) >= MAX_UPLOADS:
        raise ValueError(f"最多保存 {MAX_UPLOADS} 个视频，请先删除一些")
    uid = "u" + uuid.uuid4().hex[:10]
    meta = {"id": uid, "title": _title(filename), "size": int(size), "suffix": suffix, "status": "uploading",
            "created": datetime.now().isoformat(timespec="seconds"), "created_ts": time.time()}
    UPLOADS.mkdir(parents=True, exist_ok=True)
    _raw_path(uid).write_bytes(b"")
    _write(meta)
    return {"id": uid, "chunk": CHUNK}


def append(uid: str, offset: int, data: bytes) -> int:
    with _lock:
        meta = _read(uid)
        if not meta or meta.get("status") != "uploading":
            raise ValueError("上传已结束或不存在")
        raw = _raw_path(uid)
        have = raw.stat().st_size if raw.exists() else 0
        if offset != have:  # retried or out-of-order chunk: tell the client where to resume
            raise OffsetMismatch(have)
        if have + len(data) > meta["size"]:
            raise ValueError("数据比声明的文件大")
        with raw.open("ab") as handle:
            handle.write(data)
        _live[uid] = {"received": have + len(data), "progress": round(100 * (have + len(data)) / meta["size"])}
        return have + len(data)


def finish(uid: str) -> dict[str, Any]:
    meta = _read(uid)
    if not meta or meta.get("status") != "uploading":
        raise ValueError("上传已结束或不存在")
    raw = _raw_path(uid)
    if not raw.exists() or raw.stat().st_size != meta["size"]:
        raise ValueError("文件还没传完")
    meta.update(status="processing", stage="TRANSCODING")
    _write(meta)
    _live[uid] = {"progress": 0}
    threading.Thread(target=_process, args=(uid,), daemon=True, name=f"upload-{uid}").start()
    return get(uid) or meta


def _probe(path: Path) -> dict[str, Any]:
    raw = subprocess.check_output([str(lw.FFPROBE), "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height",
                                   "-of", "json", str(path)], text=True, timeout=60)
    return json.loads(raw)


def _process(uid: str) -> None:
    meta = _read(uid) or {}
    raw, out = _raw_path(uid), video_path(uid)
    tmp = out.with_name(f".{uid}.transcode.mp4")
    try:
        probe = _probe(raw)
        if not any(s.get("codec_type") == "video" for s in probe.get("streams", [])):
            raise ValueError("这个文件里没有视频画面")
        seconds = float(probe["format"]["duration"])
        if not MIN_SECONDS <= seconds <= MAX_SECONDS:
            raise ValueError("视频时长需要在 3 秒到 20 分钟之间")
        # Rotation metadata is applied by ffmpeg's default autorotate.
        scale = "scale='if(gte(iw,ih),min(1280,iw),-2)':'if(gte(iw,ih),-2,min(1280,ih))'"
        cmd = [str(lw.FFMPEG), "-y", "-v", "error", "-nostats", "-progress", "pipe:1", "-i", str(raw),
               "-map", "0:v:0", "-map", "0:a:0?", "-vf", f"{scale},fps=30,format=yuv420p",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-c:a", "aac", "-b:a", "128k", "-ac", "2", "-ar", "48000",
               "-movflags", "+faststart", str(tmp)]
        with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True) as proc:
            for line in proc.stdout:
                if line.startswith("out_time_ms="):
                    try:
                        _live[uid] = {"stage": "TRANSCODING", "progress": min(99, round(int(line.split("=")[1]) / 1e4 / seconds))}
                    except ValueError:
                        pass
            if proc.wait(timeout=3600) != 0:
                raise ValueError("这个视频格式暂时不支持")
        os.replace(tmp, out)
        raw.unlink(missing_ok=True)
        final = _probe(out)
        stream = next(s for s in final["streams"] if s.get("codec_type") == "video")
        meta.update(status="analyzing", stage="ANALYZING", duration=round(float(final["format"]["duration"]), 3),
                    width=stream.get("width"), height=stream.get("height"))
        _write(meta)
        lw.VIDEO_IDS[uid] = out
        _live[uid] = {"stage": "ANALYZING", "progress": 0}
        result = lw.analyze(uid, progress=lambda done, total: _live.__setitem__(uid, {"stage": "ANALYZING", "progress": round(100 * done / max(1, total))}))
        lw.camera_cuts(uid)
        meta.update(status="ready", stage="READY", events=len(result.get("events", [])))
        _write(meta)
        for callback in on_ready:
            callback()
    except Exception as exc:  # anything: show a friendly reason, keep nothing half-made
        message = str(exc) if re.search(r"[一-鿿]", str(exc)) else "处理失败，请换个视频再试"
        meta.update(status="failed", stage="FAILED", error=message)
        _write(meta)
        lw.VIDEO_IDS.pop(uid, None)
        for path in (raw, tmp, out):
            path.unlink(missing_ok=True)
    finally:
        _live.pop(uid, None)


def delete(uid: str) -> None:
    meta = _read(uid)
    if not meta:
        raise ValueError("视频不存在")
    if meta.get("status") in ("processing", "analyzing"):
        raise ValueError("视频还在处理中，处理完再删除")
    lw.VIDEO_IDS.pop(uid, None)
    for path in (video_path(uid), _raw_path(uid), _meta_path(uid),
                 lw.OUT / f"latest_{uid}.json", lw.OUT / f"shots_{uid}.json",
                 ROOT / "outputs" / "ai_inspect" / f"{uid}.json"):
        path.unlink(missing_ok=True)
    for path in lw.OUT.glob(f"lw-{uid}-*.json"):
        path.unlink(missing_ok=True)
    for path in (ROOT / "outputs" / "web_thumbs").glob(f"{uid}_*.jpg"):
        path.unlink(missing_ok=True)
    for callback in on_ready:
        callback()
