"""复盘 corrections overlay and the 'needs a look' flag."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from integrations import corrections, shots
from tests.test_shots import path


def ev(eid, outcome):
    return {"event_id": eid, "evidence_source": "LOCAL_DETECTOR", "outcome": outcome, "shot_kind": "jump",
            "display_name": "跳投 · " + {"made": "进了", "missed": "没进"}[outcome], "final_ranking_score": 0.4}


class CorrectionsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = mock.patch.object(corrections, "DIR", Path(self.tmp.name))
        self.p.start()

    def tearDown(self):
        self.p.stop(); self.tmp.cleanup()

    def test_correction_flips_outcome_name_and_rank(self):
        corrections.set_outcome("v1", "s1", "made", "missed")
        out = corrections.apply("v1", [ev("s1", "missed"), ev("s2", "missed")])
        self.assertEqual(out[0]["outcome"], "made")
        self.assertEqual(out[0]["display_name"], "跳投 · 进了")
        self.assertTrue(out[0]["user_corrected"])
        self.assertGreater(out[0]["final_ranking_score"], 1.0)
        self.assertEqual(out[1]["outcome"], "missed")

    def test_setting_back_to_original_or_none_removes_it(self):
        corrections.set_outcome("v1", "s1", "made", "missed")
        corrections.set_outcome("v1", "s1", "missed", "missed")
        self.assertEqual(corrections.load("v1"), {})
        corrections.set_outcome("v1", "s1", "made", "missed")
        corrections.set_outcome("v1", "s1", None, "missed")
        self.assertEqual(corrections.load("v1"), {})

    def test_bad_input_rejected(self):
        with self.assertRaises(ValueError):
            corrections.set_outcome("v1", "s1", "maybe")
        with self.assertRaises(ValueError):
            corrections.set_outcome("../x", "s1", "made")


class UncertainFlagTest(unittest.TestCase):
    def test_clean_make_is_not_flagged_and_evidence_is_recorded(self):
        a = shots._attempts(path([(420, 200), (480, 250), (500, 290), (502, 340), (504, 400)]))[0]
        self.assertEqual(a["outcome"], "made")
        self.assertFalse(shots.uncertain(a))
        self.assertLess(a["evidence"]["cross"], 0.15)

    def test_long_off_centre_through_rim_make_is_flagged_but_still_made(self):
        a = {"outcome": "made", "via": "through_rim", "evidence": {"track": 30, "cross": 0.3}}
        self.assertTrue(shots.uncertain(a))


if __name__ == "__main__":
    unittest.main()
