"""Player numbering, team split and shot attribution from the detector rows.

Rows come from shots.scan(): person boxes (player / holder / scorer) with a
torso colour [conf, x1, y1, x2, y2, L, a, b].  No extra model is run.

1. Per row, merge overlapping person boxes (a holder is also a player).
2. Track: match boxes to live tracks by overlap, distance and jersey colour
   (Hungarian assignment); unmatched confident boxes start new tracks.
3. Stitch: a track that ends and another that starts soon after, nearby and
   in the same colour, are the same person (occlusion breaks tracks).
4. Teams: 2-means on the tracks' jersey colours (only if the two colours
   are clearly apart; otherwise no team split).
5. A shot belongs to the person holding / shooting the ball just before the
   ball enters the zone above the rim: the "scorer" box first, then "holder",
   then whoever is closest to the ball.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy.optimize import linear_sum_assignment

from integrations import shots

# Off for users until identity holds across a game: on fixed-camera amateur clips
# (wuhs, issaquah; ~8 people in view) a person's track lasts ~12 s median, so one
# player gets 8-9 numbers in 3 minutes (docs/SHOT_DETECTION_VALIDATION.md).
ENABLED = False
MAX_GAP_S = 1.2          # a live track may miss detections this long
NEW_MIN = 0.5            # confidence to start a track
MIN_OBS = 4              # shorter tracks are noise
STITCH_GAP_S = 4.0
STITCH_COLOUR = 18.0     # Lab distance
TEAM_SPLIT = 14.0        # min Lab distance between the two team colours
ATTR_BEFORE_S = 1.6      # look this far back from the attempt for the shooter
MAX_PLAYERS = 12         # more distinct shooters than this: numbering is not trustworthy
MAX_TRACKS_PER_MIN = 30  # edited footage (camera cuts) breaks every track; ČBF reel: ~56/min


def _iou(a: list[float], b: list[float]) -> float:
    x1, y1, x2, y2 = max(a[1], b[1]), max(a[2], b[2]), min(a[3], b[3]), min(a[4], b[4])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = (a[3] - a[1]) * (a[4] - a[2]) + (b[3] - b[1]) * (b[4] - b[2]) - inter
    return inter / union if union > 0 else 0.0


def _colour(b: list[float]) -> np.ndarray | None:
    return np.array(b[5:8], float) if len(b) >= 8 and any(b[5:8]) else None


def _cdist(a: np.ndarray | None, b: np.ndarray | None) -> float:
    if a is None or b is None:
        return 0.0
    # chroma (a, b) separates jerseys better than lightness
    return float(math.sqrt(0.5 * (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2))


def people(row: dict[str, Any]) -> list[dict[str, Any]]:
    """Merged person boxes in one row, each with role flags."""
    cands = ([(b, "scorer") for b in row.get("scorer", [])] + [(b, "holder") for b in row.get("holder", [])]
             + [(b, "player") for b in row.get("player", [])])
    out: list[dict[str, Any]] = []
    for b, role in sorted(cands, key=lambda c: -c[0][0]):
        if len(b) < 5:
            continue
        same = next((p for p in out if _iou(p["box"], b) > 0.55), None)
        if same:
            same[role] = True
            if same["colour"] is None:
                same["colour"] = _colour(b)
        else:
            out.append({"box": b, "colour": _colour(b), "scorer": role == "scorer", "holder": role == "holder"})
    return out


def _centre(b: list[float]) -> tuple[float, float, float]:
    return (b[1] + b[3]) / 2, (b[2] + b[4]) / 2, max(1.0, b[4] - b[2])


def track(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Tracks: {"id", "obs": [(row_index, t, person)], "colour"} after stitching."""
    live: list[dict[str, Any]] = []
    done: list[dict[str, Any]] = []
    for k, r in enumerate(rows):
        t = r["t"]
        for tr in [tr for tr in live if t - tr["obs"][-1][1] > MAX_GAP_S]:
            live.remove(tr); done.append(tr)
        dets = people(r)
        if live and dets:
            cost = np.full((len(live), len(dets)), 9.0)
            for i, tr in enumerate(live):
                _, lt, lp = tr["obs"][-1]
                lx, ly, lh = _centre(lp["box"])
                dt = max(1 / 30, t - lt)
                for j, d in enumerate(dets):
                    x, y, h = _centre(d["box"])
                    dist = math.hypot(x - lx, y - ly) / max(lh, h)
                    if dist > 0.35 + 1.5 * dt:          # people move about 1.5 body heights a second at most
                        continue
                    cd = _cdist(tr["colour"], d["colour"])
                    if cd > 35:
                        continue
                    cost[i, j] = 0.45 * (1 - _iou(lp["box"], d["box"])) + 0.35 * dist + 0.2 * cd / 35
            ri, ci = linear_sum_assignment(cost)
            used = set()
            for i, j in zip(ri, ci):
                if cost[i, j] < 1.0:
                    tr = live[i]
                    tr["obs"].append((k, t, dets[j]))
                    if dets[j]["colour"] is not None:
                        tr["colour"] = dets[j]["colour"] if tr["colour"] is None else 0.9 * tr["colour"] + 0.1 * dets[j]["colour"]
                    used.add(j)
            dets = [d for j, d in enumerate(dets) if j not in used]
        for d in dets:
            if d["box"][0] >= NEW_MIN:
                live.append({"obs": [(k, t, d)], "colour": d["colour"]})
    tracks = [tr for tr in done + live if len(tr["obs"]) >= MIN_OBS]
    return _stitch(sorted(tracks, key=lambda tr: tr["obs"][0][1]))


def _stitch(tracks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Join a track to an earlier one that ended shortly before, nearby, same colour."""
    merged: list[dict[str, Any]] = []
    for tr in tracks:
        t0 = tr["obs"][0][1]
        x0, y0, h0 = _centre(tr["obs"][0][2]["box"])
        best, best_cost = None, 9.0
        for m in merged:
            t1 = m["obs"][-1][1]
            gap = t0 - t1
            if not 0 < gap <= STITCH_GAP_S:
                continue
            x1, y1, h1 = _centre(m["obs"][-1][2]["box"])
            dist = math.hypot(x0 - x1, y0 - y1) / max(h0, h1)
            cd = _cdist(m["colour"], tr["colour"])
            if dist > 0.8 + 1.0 * gap or cd > STITCH_COLOUR:
                continue
            c = dist / (0.8 + gap) + cd / STITCH_COLOUR + gap / STITCH_GAP_S
            if c < best_cost:
                best, best_cost = m, c
        if best is not None:
            n_old, n_new = len(best["obs"]), len(tr["obs"])
            best["obs"] += tr["obs"]
            if best["colour"] is not None and tr["colour"] is not None:
                best["colour"] = (n_old * best["colour"] + n_new * tr["colour"]) / (n_old + n_new)
        else:
            merged.append(tr)
    for n, m in enumerate(merged):
        m["id"] = n
    return merged


def teams(tracks: list[dict[str, Any]]) -> dict[int, int] | None:
    """Track id -> team 0/1 by 2-means on jersey colour, or None if colours do not split."""
    cols = [(tr["id"], tr["colour"], len(tr["obs"])) for tr in tracks if tr["colour"] is not None and len(tr["obs"]) >= 8]
    if len(cols) < 4:
        return None
    X = np.array([c[1] for c in cols]) * np.array([0.7, 1.0, 1.0])
    w = np.array([c[2] for c in cols], float)
    # init: the two colours farthest apart
    d = np.linalg.norm(X[:, None] - X[None], axis=2)
    i, j = np.unravel_index(np.argmax(d), d.shape)
    C = np.stack([X[i], X[j]])
    for _ in range(20):
        lab = np.argmin(np.linalg.norm(X[:, None] - C[None], axis=2), axis=1)
        if len(set(lab)) < 2:
            return None
        C = np.stack([np.average(X[lab == g], axis=0, weights=w[lab == g]) for g in (0, 1)])
    if np.linalg.norm(C[0] - C[1]) < TEAM_SPLIT:
        return None
    lab = np.argmin(np.linalg.norm(X[:, None] - C[None], axis=2), axis=1)
    out = {cid: int(g) for (cid, _, _), g in zip(cols, lab)}
    # tracks too short for the fit still get the nearer team
    for tr in tracks:
        if tr["id"] not in out and tr["colour"] is not None:
            x = tr["colour"] * np.array([0.7, 1.0, 1.0])
            out[tr["id"]] = int(np.argmin(np.linalg.norm(C - x, axis=1)))
    return out


REID_MAX = 0.35          # max cosine distance to call two tracks the same person (tuned by the split test)
OVERLAP_S = 0.3          # tracks seen together longer than this are different people


def merge_identities(tracks: list[dict[str, Any]], emb: dict[int, np.ndarray], team: dict[int, int] | None,
                     max_dist: float = REID_MAX) -> dict[int, int]:
    """Track id -> identity id: join tracks that look alike, never seen at once, same team."""
    clusters = []
    for tr in tracks:
        clusters.append({"ids": [tr["id"]], "spans": [(tr["obs"][0][1], tr["obs"][-1][1])],
                         "vec": emb.get(tr["id"]), "n": 1, "team": None if team is None else team.get(tr["id"])})

    def clash(a: dict[str, Any], b: dict[str, Any]) -> bool:
        if a["team"] is not None and b["team"] is not None and a["team"] != b["team"]:
            return True
        return any(min(x1, y1) - max(x0, y0) > OVERLAP_S for x0, x1 in a["spans"] for y0, y1 in b["spans"])

    while True:
        best, pair = max_dist, None
        for i, a in enumerate(clusters):
            if a["vec"] is None:
                continue
            for j in range(i + 1, len(clusters)):
                b = clusters[j]
                if b["vec"] is None:
                    continue
                d = 1.0 - float(a["vec"] @ b["vec"])
                if d < best and not clash(a, b):
                    best, pair = d, (i, j)
        if pair is None:
            break
        i, j = pair
        a, b = clusters[i], clusters.pop(j)
        v = a["n"] * a["vec"] + b["n"] * b["vec"]
        a.update(ids=a["ids"] + b["ids"], spans=a["spans"] + b["spans"], vec=v / max(1e-6, float(np.linalg.norm(v))),
                 n=a["n"] + b["n"], team=a["team"] if a["team"] is not None else b["team"])
    return {tid: n for n, c in enumerate(clusters) for tid in c["ids"]}


def _shooter(rows: list[dict[str, Any]], index: dict[int, list[tuple[int, dict[str, Any]]]], t: float) -> tuple[int | None, str]:
    """(track id, how) for the shooter of an attempt that entered the up zone at time t."""
    window = [k for k, r in enumerate(rows) if t - ATTR_BEFORE_S <= r["t"] <= t + 0.1]
    for role in ("scorer", "holder"):
        for k in reversed(window):
            hits = [(tid, p) for tid, p in index.get(k, []) if p[role]]
            if hits:
                return max(hits, key=lambda h: h[1]["box"][0])[0], role
    # fall back: the person nearest the ball in the last row before the attempt with a ball
    for k in reversed(window):
        balls = [b for b in rows[k].get("ball", []) if b[0] >= shots.BALL_MIN]
        if balls and index.get(k):
            bx, by, _ = _centre(max(balls, key=lambda b: b[0]))
            tid, p = min(index[k], key=lambda h: math.hypot(bx - _centre(h[1]["box"])[0], by - _centre(h[1]["box"])[1]))
            x, y, h = _centre(p["box"])
            if math.hypot(bx - x, by - y) < 1.0 * h:
                return tid, "nearest"
    return None, "none"


def analyse(rows: list[dict[str, Any]], embed: Any = None) -> dict[str, Any]:
    """Players with their shots; attempts keyed by round(t, 2) -> player id.

    ``embed(tracks) -> {track id: vector}`` (reid.embed_tracks) joins a person's
    track fragments by appearance; without it only short-gap stitching is done.
    """
    if not any(r.get("player") or r.get("holder") for r in rows):
        return {"players": [], "by_attempt": {}, "teams": False}
    tracks = track(rows)
    team = teams(tracks)
    ident = {tr["id"]: tr["id"] for tr in tracks}
    if embed is not None:
        ident = merge_identities(tracks, embed(tracks), team)
        merged: dict[int, dict[str, Any]] = {}
        for tr in tracks:
            m = merged.setdefault(ident[tr["id"]], {"id": ident[tr["id"]], "obs": [], "colour": tr["colour"]})
            m["obs"] += tr["obs"]
        for m in merged.values():
            m["obs"].sort(key=lambda o: o[1])
        team = None if team is None else {ident[t]: g for t, g in team.items()}
        tracks = list(merged.values())
    index: dict[int, list[tuple[int, dict[str, Any]]]] = {}
    for tr in tracks:
        for k, _, p in tr["obs"]:
            index.setdefault(k, []).append((tr["id"], p))
    attempts = shots._attempts(rows)
    by: dict[int, list[dict[str, Any]]] = {}
    by_attempt: dict[str, dict[str, Any]] = {}
    for a in attempts:
        tid, how = _shooter(rows, index, a["t"])
        if tid is None:
            continue
        by.setdefault(tid, []).append(a)
        by_attempt[f"{a['t']:.2f}"] = {"track": tid, "how": how}
    # number players by how many shots they took, then by first shot
    order = sorted(by, key=lambda tid: (-len(by[tid]), by[tid][0]["t"]))
    number = {tid: n + 1 for n, tid in enumerate(order)}
    tracks_by_id = {tr["id"]: tr for tr in tracks}
    players = []
    for tid in order:
        tr, att = tracks_by_id[tid], by[tid]
        # thumbnail: the largest confident box of this person around their first shot
        near = [o for o in tr["obs"] if abs(o[1] - att[0]["t"]) <= 2.0] or tr["obs"]
        k, t, p = max(near, key=lambda o: o[2]["box"][0] * (o[2]["box"][4] - o[2]["box"][2]))
        made = sum(a["outcome"] == "made" for a in att)
        missed = sum(a["outcome"] == "missed" for a in att)
        players.append({
            "id": f"p{number[tid]}", "number": number[tid], "team": None if team is None else team.get(tid),
            "attempts": len(att), "made": made, "missed": missed,
            "fg_pct": round(100 * made / (made + missed)) if made + missed else None,
            "colour": None if tr["colour"] is None else [round(float(v), 1) for v in tr["colour"]],
            "thumb": {"t": t, "box": [round(v, 1) for v in p["box"][1:5]]},
            "seen": [round(tr["obs"][0][1], 2), round(tr["obs"][-1][1], 2)],
        })
    for v in by_attempt.values():
        v["player"] = f"p{number[v.pop('track')]}"
        v["team"] = None if team is None else next((p["team"] for p in players if p["id"] == v["player"]), None)
    minutes = max(0.5, (rows[-1]["t"] - rows[0]["t"]) / 60)
    reliable = len(players) <= MAX_PLAYERS and len(tracks) / minutes <= MAX_TRACKS_PER_MIN
    return {"players": players, "by_attempt": by_attempt, "teams": team is not None, "reliable": reliable,
            "tracks_per_min": round(len(tracks) / minutes, 1)}
