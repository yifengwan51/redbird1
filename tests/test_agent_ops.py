"""Multi-step chat for both assistants: compound sentences, segments, ranges, order, captions, undo."""
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from integrations import edit_ops

try:
    from tests.test_intent import FakeSession, EVENTS
    from integrations import lightweight as lw
except Exception:  # pragma: no cover - optional deps
    lw = None


class ParseOpsTest(unittest.TestCase):
    def test_split_keeps_number_lists_and_quoted_titles(self):
        self.assertEqual(edit_ops.split_clauses("去掉第1，3段，然后节奏快一点"), ["去掉第1、3段", "节奏快一点"])
        self.assertEqual(edit_ops.split_clauses("标题改成“快，准，狠”"), ["标题改成“快，准，狠”"])

    def test_segments_ranges_order_captions(self):
        ops = edit_ops.parse_ops("去掉第二段和第4段", 5, 120)
        self.assertEqual(ops.remove, [2, 4])
        self.assertEqual(edit_ops.parse_ops("最后一段不要了", 5, 120).remove, [5])
        self.assertEqual(edit_ops.parse_ops("只保留第1、3段", 5, 120).keep, [1, 3])
        self.assertEqual(edit_ops.parse_ops("只要后半段", 5, 120).range, (60.0, None))
        self.assertEqual(edit_ops.parse_ops("最后2分钟", 5, 300).range, (180.0, None))
        self.assertEqual(edit_ops.parse_ops("1:30以后", 5, 300).range, (90.0, None))
        self.assertEqual(edit_ops.parse_ops("最精彩的放最后", 5, 120).order, "climax")
        self.assertEqual(edit_ops.parse_ops("第2段字幕改成“压哨三分”", 5, 120).captions, {2: "压哨三分"})
        self.assertTrue(edit_ops.parse_ops("撤销", 5, 120).undo)
        self.assertFalse(edit_ops.parse_ops("节奏快一点", 5, 120).any)

    def test_pronoun_uses_the_tapped_clip(self):
        self.assertEqual(edit_ops.resolve_pronoun("去掉这段", 3), "去掉第3段")
        self.assertEqual(edit_ops.resolve_pronoun("去掉这段", None), "去掉这段")

    def test_reorder_keeps_replay_after_its_play(self):
        segs = [{"event_id": "a", "raw_model_score": .9}, {"event_id": "a", "replay": True},
                {"event_id": "b", "raw_model_score": .2}, {"event_id": "c", "raw_model_score": .5}]
        out = edit_ops.reorder(segs, "climax")
        self.assertEqual([(s["event_id"], bool(s.get("replay"))) for s in out], [("b", False), ("c", False), ("a", False), ("a", True)])

    def test_did_you_mean(self):
        self.assertIn("去掉第 2 段", edit_ops.did_you_mean("删第二个片段"))


@unittest.skipIf(lw is None, "lightweight dependencies are unavailable")
class FreeAssistantTest(unittest.TestCase):
    def setUp(self):
        self.s = FakeSession()
        self.s.ask("生成20秒投篮高光")

    def tearDown(self):
        shutil.rmtree(self.s.output_dir, ignore_errors=True)

    def plays(self):
        return [c for c in self.s.plan["clips"] if not c.get("replay")]

    def test_remove_a_segment_then_undo(self):
        before = [c["event_id"] for c in self.plays()]
        r = self.s.ask("去掉第2段")
        self.assertIn("去掉了第 2 段", r["reply"])
        self.assertNotIn(before[1], [c["event_id"] for c in self.plays()])
        self.assertTrue(r["can_undo"])
        self.s.ask("撤销")
        self.assertEqual([c["event_id"] for c in self.plays()], before)

    def test_keep_only_listed_segments(self):
        ids = [c["event_id"] for c in self.plays()]
        self.s.ask("只保留第1、3段")
        self.assertEqual(sorted(c["event_id"] for c in self.plays()), sorted([ids[0], ids[2]]))

    def test_compound_sentence_applies_every_part(self):
        renders = self.s.renders
        r = self.s.ask("改成硬切，然后只要后半段，最精彩的放最后")
        self.assertEqual(self.s.edit_style["transition"], "cut")
        self.assertEqual(self.s.time_range, (45.0, None))
        self.assertEqual(self.s.order, "climax")
        self.assertTrue(all(float(c["end_time"]) > 45 for c in self.plays()))
        self.assertGreater(self.s.renders, renders)
        self.assertIn("成片", r["reply"])

    def test_tapped_clip_and_caption(self):
        third = self.plays()[2]["event_id"] if len(self.plays()) > 2 else self.plays()[-1]["event_id"]
        n = 3 if len(self.plays()) > 2 else len(self.plays())
        self.s.ask("这段字幕改成“关键一球”", selected_segment=n)
        self.assertEqual(next(c["label"] for c in self.plays() if c["event_id"] == third), "关键一球")

    def test_unknown_message_suggests_close_commands(self):
        r = self.s.ask("删第二个片段吧")
        self.assertTrue(r["suggestions"])

    def test_suggestions_follow_the_plan(self):
        r = self.s.ask("节奏快一点")
        self.assertIn("撤销", r["suggestions"])



class PromptTemplateTest(unittest.TestCase):
    def test_ai_system_prompt_formats(self):
        """A stray { } in the prompt makes every AI turn fall back to the basic editor."""
        from integrations import llm_agent
        text = llm_agent.SYSTEM_PROMPT.format(video_name="v", duration=1, shooting="", moments="", plan="")
        self.assertIn('segment_captions={"2":"压哨三分"}', text)

    def test_more_ways_to_remove_and_questions_do_not_edit(self):
        self.assertEqual(edit_ops.parse_ops("删第二个片段吧", 4, 100).remove, [2])
        ops = edit_ops.parse_ops("后半段谁更准", 4, 100)
        self.assertIsNone(ops.range)
        self.assertEqual(ops.rest, "后半段谁更准")


if __name__ == "__main__":
    unittest.main()
