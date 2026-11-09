"""Real FFmpeg render of a synthetic clip: duration, replay and clamp contract.

Skipped when the project-local FFmpeg is missing.  Runs in ~10-30 s.
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1]))

try:
    import integrations.lightweight as lw
except Exception:  # pragma: no cover - only when optional deps are absent
    lw = None

AVAILABLE = lw is not None and lw.FFMPEG.is_file() and lw.FFPROBE.is_file()


def probe_duration(path: Path) -> float:
    raw = subprocess.check_output([str(lw.FFPROBE), "-v", "error", "-show_entries", "format=duration",
                                   "-of", "json", str(path)], text=True, timeout=30)
    return float(json.loads(raw)["format"]["duration"])


@unittest.skipUnless(AVAILABLE, "project FFmpeg or lightweight dependencies are unavailable")
class RenderEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Inside the repo: VIDEO_IDS paths must resolve under ROOT.
        cls.tmp = Path(tempfile.mkdtemp(dir=str(lw.ROOT / "outputs")))
        cls.source = cls.tmp / "synthetic.mp4"
        subprocess.run([str(lw.FFMPEG), "-y", "-v", "error",
                        "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=40",
                        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=40",
                        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-shortest", str(cls.source)], check=True, timeout=120)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def events(self):
        return [{"event_id": f"s{i}", "event_type": "shot_attempt", "start_time": t, "end_time": t + 1.6,
                 "raw_model_score": score, "display_name": "疑似投篮"}
                for i, (t, score) in enumerate([(3, .5), (11, .9), (19, .6), (27, .7), (34, .4)])]

    def render(self, target, style):
        style = lw.normalize_edit_style(style)
        meta = lw.duration_meta(target, 40.0)
        clips = lw.build_montage(self.events(), meta["effective_duration"], 40.0, style)
        plan = {"target_duration": meta["effective_duration"], "clips": clips, "edit_style": style, **meta}
        destination = self.tmp / f"out_{target}_{style['pace']}_{int(style['slow_motion'])}.mp4"
        with mock.patch.dict(lw.VIDEO_IDS, {"synthetic": self.source}):
            result = lw.render_plan("synthetic", plan, destination)
        return result, destination

    def test_exact_duration_with_fade_and_captions(self):
        result, path = self.render(20, {"pace": "standard", "transition": "fade", "captions": True})
        self.assertAlmostEqual(probe_duration(path), 20.0, delta=0.05)
        self.assertGreaterEqual(len(result["segments"]), 2)
        self.assertFalse(result["duration_clamped"])

    def test_slow_motion_replay_tight_cut(self):
        result, path = self.render(15, {"pace": "tight", "transition": "cut", "captions": False, "slow_motion": True})
        self.assertAlmostEqual(probe_duration(path), 15.0, delta=0.05)
        self.assertTrue(any(seg.get("replay") for seg in result["segments"]))

    def test_music_and_effects_keep_exact_duration(self):
        style = {"pace": "tight", "transition": "flash", "look": "cinematic", "zoom": True,
                 "music": "hype", "slow_motion": True, "title": "测试标题"}
        result, path = self.render(20, style)
        self.assertTrue(result["music_applied"])
        self.assertAlmostEqual(probe_duration(path), 20.0, delta=0.05)
        raw = subprocess.check_output([str(lw.FFPROBE), "-v", "error", "-show_entries", "stream=codec_type",
                                       "-of", "json", str(path)], text=True, timeout=30)
        self.assertEqual(sorted(s["codec_type"] for s in json.loads(raw)["streams"]), ["audio", "video"])

    def test_request_longer_than_source_is_clamped_and_explained(self):
        result, path = self.render(60, {"pace": "standard"})
        self.assertAlmostEqual(probe_duration(path), 40.0, delta=0.08)
        self.assertTrue(result["duration_clamped"])
        self.assertIn("原片只有 40.0 秒", result["duration_note"])


if __name__ == "__main__":
    unittest.main()
