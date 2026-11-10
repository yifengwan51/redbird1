"""Player numbering, team split and shot attribution on synthetic detector rows."""
import unittest

from integrations import players, lightweight
from tests.test_shots import RIM, ball

RED, BLUE = [50.0, 170.0, 150.0], [45.0, 140.0, 90.0]


def person(x, y, colour, conf=0.9, h=120):
    return [conf, x - 25, y - h / 2, x + 25, y + h / 2, *colour]


def rows_two_teams(seconds=4.0, shooter_x=300, shot_t=2.0):
    """Four people walking slowly; the red one at shooter_x holds the ball, then shoots at the rim."""
    out, t = [], 0.0
    while t < seconds:
        walk = 10 * t
        ppl = [person(shooter_x + walk, 500, RED), person(700 - walk, 520, BLUE),
               person(150 + walk, 540, RED), person(900 - walk, 480, BLUE)]
        r = {"t": round(t, 3), "f": int(t * 30), "rim": [RIM], "ball-in-basket": [], "scorer": [], "holder": [], "player": ppl, "referee": []}
        if t < shot_t:
            r["holder"] = [person(shooter_x + walk, 500, RED, 0.8)]
            r["ball"] = [ball(shooter_x + walk, 470)]
        else:  # ball flies to the rim and drops through
            f = min(1.0, (t - shot_t) / 0.6)
            x, y = shooter_x + walk + f * (500 - shooter_x - walk), 470 - f * 190 if f < 1 else 280 + (t - shot_t - 0.6) * 300
            r["ball"] = [ball(x, y)]
        out.append(r)
        t += 1 / 30
    return out


class PlayersTest(unittest.TestCase):
    def test_tracks_split_into_two_teams(self):
        tr = players.track(rows_two_teams())
        self.assertEqual(len(tr), 4)
        team = players.teams(tr)
        self.assertIsNotNone(team)
        reds = {tr_["id"] for tr_ in tr if tr_["colour"][2] > 120}
        self.assertEqual(len({team[i] for i in reds}), 1)
        self.assertNotEqual(team[next(iter(reds))], team[next(i for i in team if i not in reds)])

    def test_shot_goes_to_the_ball_holder(self):
        out = players.analyse(rows_two_teams())
        self.assertEqual(len(out["players"]), 1)
        p = out["players"][0]
        self.assertEqual((p["number"], p["attempts"]), (1, 1))
        self.assertLess(abs(p["thumb"]["box"][0] + 25 - 300), 60)   # the red shooter, not someone else
        self.assertTrue(out["teams"])

    def test_track_survives_a_short_occlusion(self):
        rows = rows_two_teams(seconds=3.0)
        for r in rows:
            if 1.0 <= r["t"] <= 1.6:
                r["player"] = r["player"][1:]; r["holder"] = []
        ids = players.track(rows)
        self.assertEqual(len(ids), 4)

    def test_no_people_boxes_means_no_roster(self):
        rows = [{"t": 0.0, "f": 0, "ball": [], "rim": [RIM], "ball-in-basket": [], "scorer": []}]
        self.assertEqual(players.analyse(rows)["players"], [])


class PlayerIntentTest(unittest.TestCase):
    def test_player_phrases(self):
        self.assertEqual(lightweight.player_from_text("只看3号的集锦"), 3)
        self.assertEqual(lightweight.player_from_text("12号球员进了几个"), 12)
        self.assertIsNone(lightweight.player_from_text("去掉第3段"))
        self.assertIsNone(lightweight.player_from_text("20秒集锦"))
        it = lightweight.parse_intent("只看2号", has_plan=True)
        self.assertEqual((it.action, it.player), ("generate", 2))
        self.assertTrue(lightweight.parse_intent("换回所有人", has_plan=True).all_players)


if __name__ == "__main__":
    unittest.main()
