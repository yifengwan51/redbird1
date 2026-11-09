"""VIP redemption and the AI editor's argument handling (no model calls).

The model itself is exercised live, not simulated: run
``MOTRACK_LIVE_TESTS=1`` to include ``LiveModelTests`` (costs a few requests).
"""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1]))

from integrations import vip

try:
    import integrations.llm_agent as ai
    import integrations.lightweight as lw
    HAVE_DATA = (lw.OUT / "latest_cbf.json").is_file() and lw.VIDEO_IDS["cbf"].is_file()
except Exception:  # pragma: no cover - optional deps
    ai = None
    HAVE_DATA = False


class VipTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.patch = mock.patch.multiple(vip, SECRETS=self.tmp, CODES_FILE=self.tmp / "vip_codes", TOKENS_FILE=self.tmp / "tokens.json")
        self.patch.start()
        self.env = mock.patch.dict(os.environ, {"MOTRACK_VIP_MODE": "prod"})
        self.env.start()
        vip._attempts.clear()
        (self.tmp / "vip_codes").write_text("MOTRACK-TEST1\n", encoding="utf-8")

    def tearDown(self):
        self.env.stop()
        self.patch.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_valid_code_issues_token_case_insensitive(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MOTRACK_VIP_CODES", None)
            token = vip.activate(" motrack-test1 ")
        self.assertTrue(vip.is_vip(token))
        self.assertNotIn(token, (self.tmp / "tokens.json").read_text())  # only the hash is stored

    def test_invalid_code_and_token(self):
        os.environ.pop("MOTRACK_VIP_CODES", None)
        with self.assertRaises(ValueError):
            vip.activate("WRONG")
        self.assertFalse(vip.is_vip("not-a-token"))
        self.assertFalse(vip.is_vip(None))

    def test_dev_mode_makes_everyone_vip(self):
        with mock.patch.dict(os.environ, {"MOTRACK_VIP_MODE": "dev"}):
            self.assertTrue(vip.is_vip(None))
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MOTRACK_VIP_MODE", None)
            self.assertTrue(vip.dev_mode())  # development default

    def test_rate_limit(self):
        os.environ.pop("MOTRACK_VIP_CODES", None)
        for _ in range(vip.MAX_ATTEMPTS_PER_MINUTE):
            with self.assertRaises(ValueError):
                vip.activate("WRONG")
        with self.assertRaises(PermissionError):
            vip.activate("MOTRACK-TEST1")


@unittest.skipUnless(HAVE_DATA, "needs the cached ČBF analysis and source video")
class EditorArgumentTests(unittest.TestCase):
    def setUp(self):
        self.editor = ai.LLMEditor("cbf", "ai-unittest", video_name="ČBF")
        plays = [m for m in self.editor.pool[:3]]
        # A plan whose first three segments are the first three moments.
        self.editor.session.plan = {"clips": [{"event_id": m["event_id"], "start_time": m["start_time"], "end_time": m["end_time"]} for m in plays],
                                    "target_duration": 20.0}
        self.ids = [m["moment_id"] for m in plays]

    def tearDown(self):
        shutil.rmtree(self.editor.session.output_dir, ignore_errors=True)

    def test_remove_segment_maps_to_moment_and_accumulates(self):
        settings, _, _ = self.editor._validated({"remove_segments": [2]})
        self.assertEqual(settings["exclude"], [self.ids[1]])
        self.editor.settings = settings
        settings, _, _ = self.editor._validated({"pace": "tight"})  # later edits keep earlier removals
        self.assertEqual(settings["exclude"], [self.ids[1]])

    def test_pin_overrides_removal_and_reset_clears(self):
        self.editor.settings["exclude"] = [self.ids[0]]
        settings, _, _ = self.editor._validated({"pin_moments": [self.ids[0]]})
        self.assertEqual(settings["include"], [self.ids[0]])
        self.assertEqual(settings["exclude"], [])
        self.editor.settings = settings | {"start_after": 70.0}
        settings, _, _ = self.editor._validated({"reset_choices": True})
        self.assertEqual((settings["include"], settings["exclude"], settings["start_after"]), ([], [], None))

    def test_bad_values_are_reported_not_applied(self):
        settings, style, notes = self.editor._validated({"duration": 500, "remove_segments": [9], "pin_moments": ["m999"], "pace": "warp"})
        self.assertEqual(settings["duration"], 60.0)
        self.assertEqual(style["pace"], "standard")
        self.assertTrue(any("第 9 段" in n for n in notes))
        self.assertTrue(any("m999" in n for n in notes))


@unittest.skipUnless(HAVE_DATA and os.getenv("MOTRACK_LIVE_TESTS") == "1", "live model test; set MOTRACK_LIVE_TESTS=1")
class LiveModelTests(unittest.TestCase):
    def test_generate_then_remove_segment(self):
        editor = ai.LLMEditor("cbf", "ai-livetest", video_name="ČBF 3x3 Tour")
        try:
            first = editor.generate(20, "shots", {"pace": "standard"})
            self.assertAlmostEqual(first["output"]["duration"], 20.0, delta=0.05)
            second_moment = editor._moment_of(editor.session._plays(editor.session.plan)[1]["event_id"])
            reply = editor.turn("去掉第2段")
            self.assertIn(second_moment, editor.settings["exclude"])
            self.assertTrue(reply["reply"])
        finally:
            shutil.rmtree(editor.session.output_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
