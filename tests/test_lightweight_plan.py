"""Plan-shaping tests that do not require CUDA, network access, or FFmpeg."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

try:
    from integrations.lightweight import (
        build_montage,
        duration_meta,
        fit_clips_to_target,
        normalize_edit_style,
    )
except Exception as exc:  # pragma: no cover - only when optional deps are absent
    fit_clips_to_target = None
    build_montage = duration_meta = normalize_edit_style = None
    IMPORT_ERROR = exc


def clip(start, end, score=50):
    return {"start_time": start, "end_time": end, "raw_model_score": score}


@unittest.skipIf(fit_clips_to_target is None, "lightweight dependencies are unavailable")
class FitClipsTests(unittest.TestCase):
    def test_keeps_all_clips_when_span_fits(self):
        clips = [clip(10, 14, 90), clip(15, 19, 20), clip(20, 24, 70)]
        fitted = fit_clips_to_target(clips, 20)
        self.assertEqual([(c["start_time"], c["end_time"]) for c in fitted],
                         [(10, 14), (15, 19), (20, 24)])

    def test_drops_weakest_clip_until_span_fits(self):
        clips = [clip(0, 5, 10), clip(3, 8, 90), clip(7, 12, 50)]
        fitted = fit_clips_to_target(clips, 10)
        self.assertEqual([(c["start_time"], c["end_time"]) for c in fitted],
                         [(3, 8), (7, 12)])

    def test_clamps_single_oversized_clip(self):
        fitted = fit_clips_to_target([clip(10, 40, 90)], 15)
        self.assertEqual(len(fitted), 1)
        self.assertEqual(fitted[0]["end_time"], 25)

    def test_empty_and_small_targets(self):
        self.assertEqual(fit_clips_to_target([], 10), [])
        fitted = fit_clips_to_target([clip(0, 10, 5)], 0)
        self.assertGreater(fitted[0]["end_time"], fitted[0]["start_time"])
        self.assertLessEqual(fitted[0]["end_time"] - fitted[0]["start_time"], 0.1 + 1e-9)

    def test_keeps_highest_scoring_when_all_overlap_target(self):
        clips = [clip(0, 20, 10), clip(5, 25, 99)]
        fitted = fit_clips_to_target(clips, 12)
        self.assertEqual([c["start_time"] for c in fitted], [5])


@unittest.skipIf(build_montage is None, "lightweight dependencies are unavailable")
class MontageTests(unittest.TestCase):
    def events(self):
        return [clip(2 + i * 12, 3.6 + i * 12, 90 - i * 7) | {"event_type": "dunk"} for i in range(6)]

    def test_montage_fills_exact_target_without_overrun(self):
        segments = build_montage(self.events(), 20, 80, normalize_edit_style({"pace": "standard"}))
        self.assertGreaterEqual(len(segments), 2)
        self.assertAlmostEqual(sum(s["output_duration"] for s in segments), 20, places=2)
        self.assertTrue(all(s["start_time"] >= 0 and s["end_time"] <= 80 and s["end_time"] > s["start_time"] for s in segments))

    def test_slow_motion_adds_a_replay_and_keeps_duration(self):
        style = normalize_edit_style({"pace": "standard", "slow_motion": True})
        segments = build_montage(self.events(), 20, 80, style)
        self.assertTrue(any(s.get("replay") for s in segments))
        replay = next(s for s in segments if s.get("replay"))
        self.assertLess(replay["speed"], 1.0)
        self.assertAlmostEqual(sum(s["output_duration"] for s in segments), 20, places=2)

    def test_montage_never_exceeds_short_source(self):
        events = [clip(2 + i * 3, 3.6 + i * 3, 90 - i * 7) | {"event_type": "dunk"} for i in range(6)]
        segments = build_montage(events, 60, 20.48, normalize_edit_style(None))
        self.assertAlmostEqual(sum(s["output_duration"] for s in segments), 20.48, places=2)
        self.assertTrue(all(s["end_time"] <= 20.48 for s in segments))

    def test_duration_meta_explains_source_cap(self):
        meta = duration_meta(30, 20.48)
        self.assertTrue(meta["duration_clamped"])
        self.assertAlmostEqual(meta["effective_duration"], 20.48, places=2)
        self.assertIn("20.5", meta["duration_note"])
        self.assertFalse(duration_meta(15, 20.48)["duration_clamped"])

    def test_style_validation(self):
        style = normalize_edit_style({"pace": "tight", "transition": "cut", "captions": False, "slow_motion": True})
        self.assertEqual({k: style[k] for k in ("pace", "transition", "captions", "slow_motion")},
                         {"pace": "tight", "transition": "cut", "captions": False, "slow_motion": True})
        self.assertEqual((style["look"], style["zoom"], style["music"], style["title"]), ("vivid", False, "none", None))
        self.assertEqual(normalize_edit_style("紧凑，加慢放")["pace"], "tight")
        self.assertTrue(normalize_edit_style("紧凑，加慢放")["slow_motion"])
        self.assertEqual(normalize_edit_style({"pace": "unknown"})["pace"], "standard")


@unittest.skipIf(build_montage is None, "lightweight dependencies are unavailable")
class EffectsVocabularyTests(unittest.TestCase):
    def setUp(self):
        from integrations.lightweight import edit_style_from_text, mentions_style
        self.parse, self.mentions = edit_style_from_text, mentions_style

    def test_music_words(self):
        self.assertEqual(self.parse("加点背景音乐")["music"], "hype")
        self.assertEqual(self.parse("来首嘻哈配乐")["music"], "groove")
        self.assertEqual(self.parse("配乐轻快一点")["music"], "chill")
        self.assertEqual(self.parse("去掉音乐", {"music": "hype"})["music"], "none")
        self.assertEqual(self.parse("换一首", {"music": "hype"})["music"], "groove")
        self.assertEqual(self.parse("节奏燃一点")["music"], "none")  # mood word alone is not a music request

    def test_look_zoom_flash_title(self):
        self.assertEqual(self.parse("做成电影感")["look"], "cinematic")
        self.assertEqual(self.parse("复古一点")["look"], "retro")
        s = self.parse("加点特效")
        self.assertTrue(s["zoom"]); self.assertEqual(s["transition"], "flash")
        s = self.parse("去掉特效", s)
        self.assertFalse(s["zoom"]); self.assertEqual(s["transition"], "fade")
        self.assertEqual(self.parse("标题改成“街球之夜”")["title"], "街球之夜")
        self.assertEqual(self.parse("不要标题")["title"], "")
        for text in ("加热血配乐", "做成黑白", "标题叫 MVP", "加特效"):
            self.assertTrue(self.mentions(text), text)

    def test_unknown_music_falls_back(self):
        self.assertEqual(normalize_edit_style({"music": "upload:000000000000"})["music"], "none")
        self.assertEqual(normalize_edit_style({"music": "../../etc/passwd"})["music"], "none")
        self.assertEqual(normalize_edit_style({"title": "a%{pts}\\b"})["title"], "aptsb")

    def test_beat_snapped_cuts(self):
        events = [clip(2 + i * 12, 3.6 + i * 12, 90 - i * 7) | {"event_type": "dunk"} for i in range(6)]
        style = normalize_edit_style({"pace": "tight"}) | {"music": "hype"}
        segments = build_montage(events, 20, 80, style)
        beat = 60 / 128
        edge = 0.0
        for seg in segments[:-1]:
            edge += seg["output_duration"]
            self.assertAlmostEqual(edge / beat, round(edge / beat), delta=0.01)
        self.assertAlmostEqual(sum(s["output_duration"] for s in segments), 20, places=2)
        self.assertTrue(all(0 <= s["start_time"] < s["end_time"] <= 80 for s in segments))


if __name__ == "__main__":
    unittest.main()
