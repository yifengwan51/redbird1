"""Chat intent parsing and multi-turn re-editing, without CUDA, network or FFmpeg."""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

try:
    import integrations.lightweight as lw
    from integrations.lightweight import edit_style_from_text, parse_intent
except Exception:  # pragma: no cover - only when optional deps are absent
    lw = None


@unittest.skipIf(lw is None, "lightweight dependencies are unavailable")
class ParseIntentTests(unittest.TestCase):
    CASES = [
        # (message, has_plan, action, duration, clip_count)
        ("生成20秒投篮高光", False, "generate", 20.0, None),
        ("做一个30秒精彩集锦", False, "generate", 30.0, None),
        ("帮我重新做一个15秒集锦", True, "generate", 15.0, None),
        ("生成进球集锦", False, "generate", None, None),
        ("生成 3 段投篮高光", False, "generate", None, 3),
        ("改成硬切", True, "restyle", None, None),
        ("加慢放回看", True, "restyle", None, None),
        ("不要字幕", True, "restyle", None, None),
        ("改成紧凑", True, "restyle", None, None),
        ("延长到30秒", True, "resize", 30.0, None),
        ("缩短到10秒", True, "resize", 10.0, None),
        ("改成15秒", True, "resize", 15.0, None),
        ("再短一点", True, "resize", None, None),
        ("保留最精彩的3个片段", True, "trim", None, 3),
        ("只留两段", True, "trim", None, 2),
        ("缩短到15秒", False, "generate", 15.0, None),
        ("保留3段", False, "generate", None, 3),
        ("再短一点", False, "need_plan", None, None),
        ("进了吗", True, "outcome", None, None),
        ("这个投篮是否命中", False, "outcome", None, None),
        ("找出所有疑似投篮", False, "search", None, None),
        ("解释这段视频", False, "recap", None, None),
        ("导出视频", True, "export", None, None),
        ("导出视频", False, "need_plan", None, None),
        ("怎么用", False, "help", None, None),
        ("你好", False, "none", None, None),
    ]

    def test_table(self):
        for message, has_plan, action, duration, count in self.CASES:
            with self.subTest(message=message, has_plan=has_plan):
                intent = parse_intent(message, has_plan)
                self.assertEqual(intent.action, action)
                self.assertEqual(intent.duration, duration)
                self.assertEqual(intent.clip_count, count)

    def test_resize_direction(self):
        self.assertEqual(parse_intent("长一点", True).direction, "longer")
        self.assertEqual(parse_intent("再短一点", True).direction, "shorter")

    def test_style_negation_wins(self):
        on = {"pace": "standard", "transition": "fade", "captions": True, "slow_motion": True}
        self.assertFalse(edit_style_from_text("不要慢放", on)["slow_motion"])
        self.assertFalse(edit_style_from_text("去掉字幕", on)["captions"])
        self.assertTrue(edit_style_from_text("加慢放", {**on, "slow_motion": False})["slow_motion"])
        self.assertEqual(edit_style_from_text("改成硬切", on)["transition"], "cut")


EVENTS = [
    {"event_id": f"e{i}", "event_type": kind, "start_time": start, "end_time": start + 1.6,
     "raw_model_score": score, "display_name": kind}
    for i, (kind, start, score) in enumerate([
        ("shot_attempt", 3, .6), ("dunk", 12, .8), ("dribble", 25, .4),
        ("shot_attempt", 40, .7), ("shot_attempt", 55, .5), ("basketball_action_candidate", 70, .3),
    ])
]


if lw is not None:
    class FakeSession(lw.LightweightSession):
        """Real dispatcher and planner; no video probe, scan or FFmpeg render."""

        def __post_init__(self):
            self.output_dir = Path(tempfile.mkdtemp(dir=str(lw.ROOT / "outputs")))
            self.video_duration = 90.0
            self.renders = 0

        def _events(self):
            return [dict(x) for x in EVENTS]

        def _render(self):
            self.renders += 1
            self.state = "OUTPUT_VERIFIED"
            return {"duration": sum(c["output_duration"] for c in self.plan["clips"])}


@unittest.skipIf(lw is None, "lightweight dependencies are unavailable")
class SessionReEditTests(unittest.TestCase):
    def setUp(self):
        self.session = FakeSession()
        self.session.ask("生成20秒投篮高光")

    def tearDown(self):
        shutil.rmtree(self.session.output_dir, ignore_errors=True)

    def plays(self):
        return [c for c in self.session.plan["clips"] if not c.get("replay")]

    def test_restyle_keeps_duration_and_rerenders(self):
        before = self.session.renders
        reply = self.session.ask("改成硬切")["reply"]
        self.assertEqual(self.session.plan["target_duration"], 20.0)
        self.assertEqual(self.session.edit_style["transition"], "cut")
        self.assertEqual(self.session.renders, before + 1)
        self.assertIn("硬切", reply)

    def test_slow_motion_toggle_rerenders(self):
        self.session.ask("加慢放回看")
        self.assertTrue(any(c.get("replay") for c in self.session.plan["clips"]))
        self.session.ask("不要慢放")
        self.assertFalse(any(c.get("replay") for c in self.session.plan["clips"]))
        self.assertEqual(self.session.plan["target_duration"], 20.0)

    def test_lengthen(self):
        self.session.ask("延长到30秒")
        self.assertEqual(self.session.plan["target_duration"], 30.0)

    def test_trim_counts_plays_not_replays(self):
        self.session.ask("加慢放回看")
        reply = self.session.ask("保留最精彩的3个片段")["reply"]
        self.assertEqual(len(self.plays()), 3)
        self.assertIn("3 个片段", reply)
        # The count survives a later style change.
        self.session.ask("改成紧凑")
        self.assertEqual(len(self.plays()), 3)

    def test_goal_reel_generates_with_caveat(self):
        result = self.session.ask("生成进球集锦")
        self.assertIn("output", result)
        self.assertIn("无法确认是否进球", result["reply"])

    def test_reply_carries_style_so_page_does_not_undo_chat_edit(self):
        # The page sends its toggles with every message.  The reply must carry
        # the style in effect; once the page adopts it, "改成硬切" sticks.
        page = {"pace": "standard", "transition": "fade", "captions": True, "slow_motion": False}
        reply = self.session.ask("改成硬切", edit_style=page)
        self.assertEqual(reply["edit_style"]["transition"], "cut")
        page = reply["edit_style"]  # what applyEditStyle() does in index.html
        self.session.ask("延长到30秒", edit_style=page)
        self.assertEqual(self.session.edit_style["transition"], "cut")

    def test_duration_beyond_source_is_explained(self):
        self.session.video_duration = 18.0
        result = self.session.ask("延长到30秒")
        self.assertAlmostEqual(self.session.plan["target_duration"], 18.0)
        self.assertIn("原片只有 18.0 秒", result["reply"])


if __name__ == "__main__":
    unittest.main()
