"""复盘 report: periods, streaks, notes and export from detector shot events."""
import unittest

from integrations import review


def shot(t, outcome, kind="jump"):
    return {"evidence_source": "LOCAL_DETECTOR", "start_time": t, "end_time": t + 2, "outcome": outcome, "shot_kind": kind}


class ReviewTest(unittest.TestCase):
    def test_periods_cover_the_video_and_count_shots(self):
        r = review.build("v", [shot(10, "made"), shot(70, "missed"), shot(130, "unknown")], 150)
        self.assertEqual(r["period_seconds"], 60)
        self.assertEqual([p["attempts"] for p in r["periods"]], [1, 1, 1])
        self.assertEqual(r["periods"][-1]["end"], 150)
        self.assertEqual((r["stats"]["made"], r["stats"]["fg_pct"]), (1, 50))

    def test_long_game_uses_ten_minute_periods(self):
        self.assertEqual(review.build("v", [], 2 * 3600)["period_seconds"], 600)

    def test_streaks_skip_unknown_and_need_three(self):
        ev = [shot(1, "made"), shot(5, "unknown"), shot(9, "made"), shot(13, "made"), shot(17, "missed"), shot(21, "missed")]
        streaks = review.build("v", ev, 60)["streaks"]
        self.assertEqual([(s["outcome"], s["count"]) for s in streaks], [("made", 3)])

    def test_no_shots_still_lists_other_moments(self):
        other = {"evidence_source": "LOCAL_X3D", "start_time": 4.0, "end_time": 5.6, "display_name": "疑似扣篮", "raw_model_score": 0.8}
        r = review.build("v", [other], 20)
        self.assertEqual(r["stats"]["attempts"], 0)
        self.assertEqual(r["moments"][0]["label"], "疑似扣篮")
        self.assertIn("没有检测到出手", r["notes"][0])

    def test_hot_period_only_named_when_clear(self):
        tie = review.build("v", [shot(10, "made"), shot(70, "made")], 120)
        self.assertFalse(any("进球最多" in n for n in tie["notes"]))
        clear = review.build("v", [shot(10, "made"), shot(20, "made"), shot(70, "made")], 120)
        self.assertTrue(any("进球最多的时段是 0:00–1:00" in n for n in clear["notes"]))

    def test_recap_input_has_only_given_facts(self):
        text = review.recap_input(review.build("v", [shot(95, "made"), shot(30, "missed")], 120))
        self.assertIn("进球时间：1:35", text)
        self.assertIn("命中率 50%", text)

    def test_export_escapes_title(self):
        page = review.to_html(review.build("v", [shot(3, "made")], 30), "<script>x</script>", "复盘")
        self.assertNotIn("<script>x", page)
        self.assertIn("赛后复盘", page)


if __name__ == "__main__":
    unittest.main()
