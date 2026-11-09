"""Background music for highlight reels.

Built-in tracks are synthesised locally with numpy (kick, snare, hats, bass,
pads), so they are royalty-free by construction and need no download.  Each
preset has a known tempo, which lets the editor cut on the beat.  Users may
also upload their own track; it is validated with ffprobe and stored under
``outputs/music/uploads``.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import uuid
import wave
import zlib
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
FFMPEG = ROOT / "tools" / "ffmpeg" / "bin" / "ffmpeg"
FFPROBE = ROOT / "tools" / "ffmpeg" / "bin" / "ffprobe"
CACHE = ROOT / "outputs" / "music"
UPLOADS = CACHE / "uploads"
SR = 44100
TRACK_SECONDS = 72.0
SYNTH_VERSION = 2
UPLOAD_ID = re.compile(r"^upload:([0-9a-f]{12})$")
AUDIO_SUFFIXES = {".mp3", ".m4a", ".aac", ".wav", ".ogg", ".flac"}
MAX_UPLOAD_BYTES = 30 * 1024 * 1024

PRESETS = {
    "hype": {"title": "热血", "bpm": 128, "desc": "电子鼓点，适合扣篮快剪"},
    "groove": {"title": "律动", "bpm": 94, "desc": "嘻哈节拍，街球味十足"},
    "chill": {"title": "轻快", "bpm": 110, "desc": "明亮清爽，适合舒缓集锦"},
}
MUSIC_ZH = {"none": "原声", **{k: v["title"] for k, v in PRESETS.items()}}
_lock = threading.Lock()


# ---------- synthesis primitives ----------
def _env(n: int, decay: float) -> np.ndarray:
    return np.exp(-np.arange(n) / (decay * SR))


def _lowpass(x: np.ndarray, cutoff: float) -> np.ndarray:
    spec = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(len(x), 1 / SR)
    spec *= 1.0 / (1.0 + (freqs / cutoff) ** 4)
    return np.fft.irfft(spec, len(x))


def _highpass(x: np.ndarray, cutoff: float) -> np.ndarray:
    return x - _lowpass(x, cutoff)


def _kick(rng: np.random.Generator, punch: float = 1.0) -> np.ndarray:
    n = int(0.42 * SR)
    t = np.arange(n) / SR
    freq = 46 + 110 * punch * np.exp(-t * 32)
    body = np.sin(2 * np.pi * np.cumsum(freq) / SR) * _env(n, 0.13)
    click = _highpass(rng.standard_normal(n), 2500) * _env(n, 0.004) * 0.35
    return np.tanh(1.6 * (body + click)) * 0.95


def _snare(rng: np.random.Generator, tone: float = 185, decay: float = 0.11) -> np.ndarray:
    n = int(0.3 * SR)
    t = np.arange(n) / SR
    noise = _lowpass(_highpass(rng.standard_normal(n), 1300), 8000) * _env(n, decay)
    body = np.sin(2 * np.pi * tone * t) * _env(n, 0.04) * 0.55
    return (noise * 0.75 + body) * 0.8


def _hat(rng: np.random.Generator, decay: float = 0.028) -> np.ndarray:
    n = int(max(0.05, decay * 6) * SR)
    return _highpass(rng.standard_normal(n), 7000) * _env(n, decay) * 0.32


def _crash(rng: np.random.Generator) -> np.ndarray:
    n = int(1.8 * SR)
    return _highpass(rng.standard_normal(n), 5000) * _env(n, 0.45) * 0.22


def _tone(freq: float, seconds: float, harmonics: int = 6, decay: float | None = None,
          odd_only: bool = False, detune: float = 0.0) -> np.ndarray:
    n = int(seconds * SR)
    t = np.arange(n) / SR
    out = np.zeros(n)
    f = freq * (1 + detune)
    for k in range(1, harmonics + 1):
        if odd_only and k % 2 == 0:
            continue
        if f * k > SR / 2.2:
            break
        out += np.sin(2 * np.pi * f * k * t) / (k ** (2.0 if odd_only else 1.0))
    if decay:
        out *= _env(n, decay)
    attack = min(n, int(0.006 * SR))
    out[:attack] *= np.linspace(0, 1, attack)
    release = min(n, int(0.02 * SR))
    out[-release:] *= np.linspace(1, 0, release)
    return out


def _place(track: np.ndarray, sound: np.ndarray, at: float, gain: float = 1.0) -> None:
    start = int(at * SR)
    if start >= len(track):
        return
    end = min(len(track), start + len(sound))
    track[start:end] += sound[: end - start] * gain


def _hz(note: int) -> float:
    return 440.0 * 2 ** ((note - 69) / 12)
# ---------- arrangements ----------
def _hype(rng: np.random.Generator, seconds: float) -> tuple[np.ndarray, np.ndarray]:
    """128 BPM electro: four-on-the-floor, offbeat bass, side-chained pads."""
    beat = 60 / 128; bar = 4 * beat; n = int(seconds * SR)
    drums, bass, pad_l, pad_r, lead = (np.zeros(n) for _ in range(5))
    chords = [[57, 60, 64], [53, 57, 60], [48, 52, 55], [55, 59, 62]]  # Am F C G
    roots = [33, 29, 36, 31]
    kick, clap, hat, ohat, crash = _kick(rng), _snare(rng, 200, 0.09), _hat(rng), _hat(rng, 0.09), _crash(rng)
    bars = int(seconds / bar) + 1
    for b in range(bars):
        t0 = b * bar; ci = b % 4
        if b % 8 == 0:
            _place(drums, crash, t0)
        for q in range(4):
            _place(drums, kick, t0 + q * beat)
            if q in (1, 3):
                _place(drums, clap, t0 + q * beat, 0.85)
            _place(drums, hat, t0 + q * beat + beat / 2, 0.8)
            if q % 2 == 1:
                _place(drums, ohat, t0 + q * beat + beat / 2, 0.45)
            _place(bass, _lowpass(_tone(_hz(roots[ci] + 12), beat * 0.45, 9, 0.12), 900), t0 + q * beat + beat / 2, 0.5)
        for note in chords[ci]:
            _place(pad_l, _tone(_hz(note), bar, 5, detune=-0.004), t0, 0.11)
            _place(pad_r, _tone(_hz(note), bar, 5, detune=0.004), t0, 0.11)
        if b % 8 >= 4:  # an arpeggio lifts the second half of every phrase
            for s in range(8):
                note = chords[ci][s % 3] + 12
                _place(lead, _tone(_hz(note), beat / 2, 4, 0.09, odd_only=True), t0 + s * beat / 2, 0.16)
    t = np.arange(n) / SR
    pump = 0.35 + 0.65 * np.clip(((t % beat) / (beat * 0.55)), 0, 1) ** 1.6  # side-chain to the kick
    left = drums + bass * pump + pad_l * pump + lead * 0.8
    right = drums + bass * pump + pad_r * pump + lead * 1.1
    return left, right


def _groove(rng: np.random.Generator, seconds: float) -> tuple[np.ndarray, np.ndarray]:
    """94 BPM boom-bap: swung hats, sub bass on the kick, electric-piano chords."""
    beat = 60 / 94; bar = 4 * beat; n = int(seconds * SR)
    drums, bass, keys_l, keys_r = (np.zeros(n) for _ in range(4))
    chords = [[62, 65, 69, 72], [55, 59, 62, 65], [48, 52, 55, 59], [57, 60, 64, 67]]  # Dm7 G7 Cmaj7 Am7
    roots = [38, 31, 36, 33]
    kick, snare, hat = _kick(rng, 0.8), _snare(rng, 170, 0.14), _hat(rng, 0.035)
    swing = beat * 0.58
    for b in range(int(seconds / bar) + 1):
        t0 = b * bar; ci = b % 4
        for at in (0.0, 1.5 * beat, 2.0 * beat + swing if b % 2 else 2.5 * beat):
            _place(drums, kick, t0 + at)
            _place(bass, _lowpass(_tone(_hz(roots[ci]), beat * 0.9, 3, 0.35), 260), t0 + at, 0.7)
        for q in (1, 3):
            _place(drums, snare, t0 + q * beat, 0.9)
        for q in range(4):
            _place(drums, hat, t0 + q * beat, 0.55)
            _place(drums, hat, t0 + q * beat + swing, 0.35)
        for at, gain in ((0.0, 0.12), (2.0 * beat + swing, 0.08)):
            for i, note in enumerate(chords[ci]):
                key = _tone(_hz(note), beat * 1.6, 4, 0.5)
                _place(keys_l if i % 2 == 0 else keys_r, key, t0 + at, gain)
                _place(keys_r if i % 2 == 0 else keys_l, key, t0 + at, gain * 0.5)
    return drums + bass + keys_l, drums + bass + keys_r


def _chill(rng: np.random.Generator, seconds: float) -> tuple[np.ndarray, np.ndarray]:
    """110 BPM bright pop: soft kick, shaker, plucked arpeggio over C G Am F."""
    beat = 60 / 110; bar = 4 * beat; n = int(seconds * SR)
    drums, bass, pad, pluck_l, pluck_r = (np.zeros(n) for _ in range(5))
    chords = [[60, 64, 67], [55, 59, 62], [57, 60, 64], [53, 57, 60]]
    roots = [36, 31, 33, 29]
    kick, rim, shaker = _kick(rng, 0.6), _snare(rng, 330, 0.05), _hat(rng, 0.018)
    for b in range(int(seconds / bar) + 1):
        t0 = b * bar; ci = b % 4
        for q in range(4):
            if q in (0, 2):
                _place(drums, kick, t0 + q * beat, 0.75)
            if q in (1, 3):
                _place(drums, rim, t0 + q * beat, 0.5)
            for s in range(4):
                _place(drums, shaker, t0 + q * beat + s * beat / 4, 0.22 if s % 2 else 0.35)
        _place(bass, _lowpass(_tone(_hz(roots[ci]), bar * 0.48, 3, 0.6), 300), t0, 0.55)
        _place(bass, _lowpass(_tone(_hz(roots[ci]), bar * 0.48, 3, 0.6), 300), t0 + 2 * beat, 0.45)
        for note in chords[ci]:
            _place(pad, _tone(_hz(note), bar, 2), t0, 0.06)
        pattern = [0, 1, 2, 1, 0, 2, 1, 2]
        for s, idx in enumerate(pattern):
            note = chords[ci][idx] + 12
            target = pluck_l if s % 2 == 0 else pluck_r
            _place(target, _tone(_hz(note), beat / 2, 6, 0.16), t0 + s * beat / 2, 0.15)
    return drums + bass + pad + pluck_l, drums + bass + pad + pluck_r


ARRANGEMENTS = {"hype": _hype, "groove": _groove, "chill": _chill}
def _master(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    stereo = np.stack([left, right], axis=1)
    stereo -= stereo.mean(axis=0)
    peak = np.max(np.abs(stereo)) or 1.0
    stereo = np.tanh(1.25 * stereo / peak) / np.tanh(1.25)  # gentle glue + soft clip
    return stereo * 0.7  # headroom: AAC overshoots a full-scale master


def preset_track(preset: str) -> Path:
    """Render (once) and return the cached AAC file for a built-in preset."""
    if preset not in PRESETS:
        raise ValueError("unknown music preset")
    target = CACHE / f"{preset}_v{SYNTH_VERSION}.m4a"
    with _lock:
        if target.is_file():
            return target
        CACHE.mkdir(parents=True, exist_ok=True)
        rng = np.random.default_rng(zlib.crc32(preset.encode()))
        stereo = _master(*ARRANGEMENTS[preset](rng, TRACK_SECONDS))
        raw = CACHE / f".{preset}_{uuid.uuid4().hex[:6]}.wav"
        with wave.open(str(raw), "wb") as handle:
            handle.setnchannels(2); handle.setsampwidth(2); handle.setframerate(SR)
            handle.writeframes((stereo * 32767).astype("<i2").tobytes())
        part = target.with_name(target.stem + f".{uuid.uuid4().hex[:6]}.m4a")
        try:
            subprocess.run([str(FFMPEG), "-y", "-v", "error", "-i", str(raw), "-c:a", "aac", "-b:a", "160k", str(part)],
                           check=True, timeout=120)
            os.replace(part, target)
        finally:
            raw.unlink(missing_ok=True); part.unlink(missing_ok=True)
        return target


def resolve(choice: str | None) -> tuple[Path | None, float | None]:
    """(audio file, tempo) for a style's ``music`` value; tempo is None for uploads."""
    if not choice or choice == "none":
        return None, None
    if choice in PRESETS:
        return preset_track(choice), 60.0 / PRESETS[choice]["bpm"]
    match = UPLOAD_ID.match(choice)
    if match:
        meta = upload_meta(match.group(1))
        if meta:
            return UPLOADS / meta["file"], None
    return None, None


def valid_choice(choice: object) -> bool:
    if choice == "none" or choice in PRESETS:
        return True
    match = UPLOAD_ID.match(str(choice or ""))
    return bool(match and upload_meta(match.group(1)))


def upload_meta(upload_id: str) -> dict | None:
    if not re.fullmatch(r"[0-9a-f]{12}", upload_id or ""):
        return None
    try:
        meta = json.loads((UPLOADS / f"{upload_id}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return meta if (UPLOADS / meta.get("file", "")).is_file() else None


def save_upload(temp: Path, original_name: str) -> dict:
    """Validate an uploaded file as audio and keep it; raise ValueError otherwise."""
    suffix = Path(original_name).suffix.lower()
    if suffix not in AUDIO_SUFFIXES:
        raise ValueError("仅支持 MP3 / M4A / AAC / WAV / OGG / FLAC")
    try:
        raw = subprocess.check_output([str(FFPROBE), "-v", "error", "-show_entries", "format=duration:stream=codec_type",
                                       "-of", "json", str(temp)], text=True, timeout=30)
        data = json.loads(raw)
        seconds = float(data["format"]["duration"])
    except (subprocess.SubprocessError, KeyError, ValueError):
        raise ValueError("这个文件不是可识别的音频")
    if not any(s.get("codec_type") == "audio" for s in data.get("streams", [])):
        raise ValueError("这个文件里没有音频")
    if not 3 <= seconds <= 900:
        raise ValueError("音乐时长需要在 3 秒到 15 分钟之间")
    UPLOADS.mkdir(parents=True, exist_ok=True)
    upload_id = uuid.uuid4().hex[:12]
    name = re.sub(r"[^\w一-鿿 .()-]+", "_", Path(original_name).stem)[:40].strip() or "我的音乐"
    os.replace(temp, UPLOADS / f"{upload_id}{suffix}")
    meta = {"id": f"upload:{upload_id}", "file": f"{upload_id}{suffix}", "title": name, "duration": round(seconds, 1)}
    (UPLOADS / f"{upload_id}.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return meta


def mix_command(video: Path, music: Path, duration: float, keep_original: bool, destination: Path) -> list[str]:
    """Music under the reel: looped, faded, original sound ducked, video copied."""
    fade_out = max(0.0, duration - 1.6)
    music_chain = (f"[1:a]aformat=sample_rates=48000:channel_layouts=stereo,atrim=0:{duration:.3f},"
                   f"afade=t=in:st=0:d=0.4,afade=t=out:st={fade_out:.3f}:d=1.6,volume=0.85[m]")
    if keep_original:
        graph = (f"[0:a]aformat=sample_rates=48000:channel_layouts=stereo,volume=0.28[o];{music_chain};"
                 "[o][m]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]")
    else:
        graph = music_chain.replace("[m]", "[a]")
    return [str(FFMPEG), "-y", "-v", "error", "-i", str(video), "-stream_loop", "-1", "-i", str(music),
            "-filter_complex", graph, "-map", "0:v:0", "-map", "[a]", "-t", f"{duration:.3f}",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-movflags", "+faststart", str(destination)]
