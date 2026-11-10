"""Shot rules on synthetic RF-DETR rows: rim lock, ball path, made/missed/unknown."""
import unittest

from integrations import shots

RIM = [0.7, 480, 295, 520, 305]          # centre (500, 300), 40 x 10 px
FAR_RIM = [0.9, 100, 295, 140, 305]      # the hoop at the other end


def ball(x, y, conf=0.8, r=6):
    return [conf, x - r, y - r, x + r, y + r]


def row(t, balls=(), rim=RIM, bib=(), scorer=()):
    return {"t": round(t, 3), "f": int(t * 30), "ball": list(balls), "rim": [rim] if rim else [],
            "ball-in-basket": list(bib), "scorer": list(scorer)}


def path(points, start=1.0, rim=RIM):
    """One row per 1/30 s along straight segments between (x, y) points."""
    rows, t = [], start
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        for i in range(6):
            f = i / 6
            rows.append(row(t, [ball(x1 + f * (x2 - x1), y1 + f * (y2 - y1))], rim=rim))
            t += 1 / 30
    return rows


class ShotRulesTest(unittest.TestCase):
    def outcomes(self, rows):
        return [a["outcome"] for a in shots._attempts(rows)]

    def test_ball_dropping_through_rim_is_made(self):
        rows = path([(420, 200), (480, 250), (500, 290), (502, 340), (504, 400)])
        self.assertEqual(self.outcomes(rows), ["made"])

    def test_slow_or_hidden_drop_after_rim_is_still_made(self):
        """A make whose ball is hidden by the net / drops slowly must not flip to a miss (bug 2026-11-10)."""
        rows = path([(420, 200), (480, 250), (500, 290), (502, 312)]) + [row(1.7 + i / 30) for i in range(20)]
        self.assertEqual(self.outcomes(rows), ["made"])

    def test_ball_falling_beside_rim_is_missed(self):
        rows = path([(560, 200), (570, 260), (575, 320), (580, 380)])
        self.assertEqual(self.outcomes(rows), ["missed"])

    def test_ball_in_basket_run_is_made_without_a_tracked_arc(self):
        rows = [row(1 + i / 30, bib=[[0.8, 485, 295, 515, 330]]) for i in range(3)]
        self.assertEqual(self.outcomes(rows), ["made"])

    def test_single_ball_in_basket_frame_is_not_enough(self):
        rows = [row(1.0, bib=[[0.8, 485, 295, 515, 330]]), row(1.5)]
        self.assertEqual(self.outcomes(rows), [])

    def test_no_rim_in_view_means_no_judgement(self):
        rows = path([(420, 200), (500, 290), (504, 400)], rim=None)
        self.assertEqual(self.outcomes(rows), [])

    def test_rim_does_not_jump_to_the_other_hoop(self):
        rows = [row(1.0), row(1.05, rim=FAR_RIM), row(1.1)]
        hoops, _ = shots._track(rows)
        self.assertTrue(all(abs(h[0] - 500) < 1 for h in hoops))

    def test_made_shot_event_has_plain_name_and_ranks_first(self):
        made = shots.shot_events("v", path([(420, 200), (500, 290), (504, 400)]), "x")[0]
        missed = shots.shot_events("v", path([(560, 200), (575, 320), (580, 380)]), "x")[0]
        self.assertEqual(made["display_name"], "跳投 · 进了")
        self.assertGreater(made["final_ranking_score"], missed["final_ranking_score"])
        self.assertLessEqual(made["start_time"], made["peak_time"])

    def test_summary_counts_only_judged_shots_for_percentage(self):
        ev = [{"evidence_source": "LOCAL_DETECTOR", "outcome": o, "shot_kind": "jump"} for o in ("made", "made", "missed", "unknown")]
        s = shots.summary(ev + [{"evidence_source": "LOCAL_X3D"}])
        self.assertEqual((s["attempts"], s["made"], s["missed"], s["unknown"], s["fg_pct"]), (4, 2, 1, 1, 67))


if __name__ == "__main__":
    unittest.main()
