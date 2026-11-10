import unittest

import numpy as np

from integrations import highlight


def shot(t, outcome, **kw):
    base = {"made": 1.25, "missed": 0.45, "unknown": 0.5}[outcome]
    return {"start_time": t - 2, "end_time": t + 1, "peak_time": t, "outcome": outcome,
            "evidence_source": "LOCAL_DETECTOR", "final_ranking_score": base, "raw_model_score": 0.9, **kw}


class HighlightTest(unittest.TestCase):
    def test_groups_keep_their_order(self):
        db = np.full(600, -40.0)
        db[100:130] = -20.0          # loud cheer after t=10 (a miss)
        ev = [shot(10, "missed", shot_range=12), shot(30, "made"), shot(40, "unknown"),
              {"start_time": 20, "end_time": 22, "raw_model_score": 0.99, "final_ranking_score": 0.99}]
        highlight.score(ev, db)
        s = {e.get("outcome", "x3d"): e["final_ranking_score"] for e in ev}
        self.assertEqual(s["missed"], 0.45)
        self.assertEqual(s["unknown"], 0.5)
        self.assertEqual(s["x3d"], 0.99)
        self.assertGreaterEqual(s["made"], 1.25)

    def test_made_ranked_by_signals(self):
        db = np.full(600, -40.0)
        db[203:230] = -25.0          # cheer after the t=20 make
        ev = [shot(20, "made", shot_range=9), shot(40, "made", shot_range=1)]
        highlight.score(ev, db)
        self.assertGreater(ev[0]["final_ranking_score"], ev[1]["final_ranking_score"])
        self.assertLessEqual(ev[0]["final_ranking_score"], 1.75)

    def test_uncertain_make_gets_no_bonus(self):
        ev = [shot(20, "made", shot_range=9, uncertain=True)]
        highlight.score(ev, None)
        self.assertEqual(ev[0]["final_ranking_score"], 1.25)

    def test_streak(self):
        ev = [shot(t, "made", team=0) for t in (10, 20, 30)]
        highlight.score(ev, None)
        self.assertEqual([e["highlight"]["signals"]["streak"] for e in ev], [0.0, 0.333, 0.667])


if __name__ == "__main__":
    unittest.main()
