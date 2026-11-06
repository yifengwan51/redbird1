"""Plan-shaping tests that do not require CUDA, network access, or FFmpeg."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

try:
    from integrations.lightweight import fit_clips_to_target
except Exception as exc:  # pragma: no cover - only when optional deps are absent
    fit_clips_to_target = None
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


if __name__ == "__main__":
    unittest.main()
