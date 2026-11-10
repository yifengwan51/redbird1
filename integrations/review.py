"""Post-game review (复盘): timeline, per-period shooting, streaks, report.

Built only from the cached analysis (detector shots + X3D moments), so it is
instant once a video has been analysed.  Every number is a model estimate;
the report says so once instead of on every line.
"""
from __future__ import annotations

import html
from typing import Any

from .shots import summary as shooting_summary

KIND_ZH = {"jump": "跳投", "layup": "上篮/扣篮"}
OUTCOME_ZH = {"made": "进了", "missed": "没进", "unknown": "看不出"}


def _clock(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    return f"{seconds // 60}:{seconds % 60:02d}"


def _period_length(duration: float) -> float:
    """About 4–8 periods: 10 min for a full game, shorter for short clips."""
    for size in (60, 120, 180, 300, 600):
        if duration / size <= 8:
            return float(size)
    return 600.0


def _streaks(shots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Runs of 3+ judged shots with the same result (unknowns do not break a run)."""
    runs: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    for shot in (s for s in shots if s["outcome"] in ("made", "missed")):
        if current and shot["outcome"] != current[-1]["outcome"]:
            if len(current) >= 3:
                runs.append(current)
            current = []
        current.append(shot)
    if len(current) >= 3:
        runs.append(current)
    return [{"outcome": r[0]["outcome"], "count": len(r), "start": r[0]["time"], "end": r[-1]["time"],
             "text": f"{_clock(r[0]['time'])}–{_clock(r[-1]['time'])} 连续{'命中' if r[0]['outcome'] == 'made' else '没进'} {len(r)} 球"}
            for r in runs]


def build(video_id: str, events: list[dict[str, Any]], duration: float) -> dict[str, Any]:
    shots = sorted(
        ({"time": float(e["start_time"]), "kind": e.get("shot_kind", "jump"),
          "outcome": e.get("outcome", "unknown"), "start": float(e["start_time"]), "end": float(e["end_time"]),
          "id": e.get("event_id", ""), "uncertain": bool(e.get("uncertain")), "corrected": bool(e.get("user_corrected"))}
         for e in events if e.get("evidence_source") == "LOCAL_DETECTOR"),
        key=lambda s: s["time"])
    for s in shots:
        s["label"] = KIND_ZH.get(s["kind"], "投篮") + ("" if s["outcome"] == "unknown" else " · " + OUTCOME_ZH[s["outcome"]])
        s["clock"] = _clock(s["time"])

    # Non-shot moments worth a look (X3D), so the timeline is not empty when
    # the detector found nothing.
    others = sorted(
        ({"time": float(e["start_time"]), "label": e.get("display_name") or "精彩动作", "clock": _clock(float(e["start_time"])),
          "score": float(e.get("final_ranking_score", e.get("raw_model_score", 0)) or 0)}
         for e in events if e.get("evidence_source") != "LOCAL_DETECTOR"),
        key=lambda m: -m["score"])[:8]
    others.sort(key=lambda m: m["time"])

    size = _period_length(duration)
    periods = []
    start = 0.0
    while start < max(duration, 0.1):
        end = min(duration, start + size)
        inside = [s for s in shots if start <= s["time"] < end or (end >= duration and s["time"] >= start)]
        made = sum(s["outcome"] == "made" for s in inside)
        missed = sum(s["outcome"] == "missed" for s in inside)
        periods.append({"label": f"{_clock(start)}–{_clock(end)}", "start": start, "end": end, "attempts": len(inside),
                        "made": made, "missed": missed, "fg_pct": round(100 * made / (made + missed)) if made + missed else None})
        start = end

    stats = shooting_summary(events)
    judged = stats["made"] + stats["missed"]
    made_counts = sorted((p["made"] for p in periods), reverse=True)
    hot = next((p for p in periods if p["made"] == made_counts[0]), None) if made_counts and made_counts[0] >= 2 and (len(made_counts) == 1 or made_counts[0] > made_counts[1]) else None
    notes = []
    if not stats["attempts"]:
        notes.append("这段视频没有检测到出手。")
    else:
        notes.append(f"全场出手 {stats['attempts']} 次，能判断结果的 {judged} 次，进 {stats['made']} 个"
                     + (f"，命中率 {stats['fg_pct']}%。" if stats["fg_pct"] is not None else "。"))
        if stats["unknown"]:
            notes.append(f"有 {stats['unknown']} 次篮筐不在画面里或太小，看不出结果。")
        if hot:
            notes.append(f"进球最多的时段是 {hot['label']}（进 {hot['made']} 个）。")
        busiest = max(periods, key=lambda p: p["attempts"])
        if busiest["attempts"] >= 3:
            notes.append(f"出手最密集的是 {busiest['label']}（{busiest['attempts']} 次）。")
    return {"video_id": video_id, "duration": round(duration, 1), "stats": stats, "shots": shots, "moments": others,
            "periods": periods, "period_seconds": size, "streaks": _streaks(shots), "notes": notes,
            "caveat": "数据由模型自动识别，可能有误；看不出结果的出手不计入命中率。"}


# ---------- AI written recap (VIP) ----------
RECAP_PROMPT = """你是篮球教练助理，根据下面的自动统计写一段赛后复盘，给教练和球员看。
要求：
- 中文，3–4 句，像教练赛后讲话：先一句整体评价，再点出 1–2 个值得回看的时段或球（带原片时间），最后给 1 条篮球上的建议（出手选择、节奏、上篮/跳投比例等）。
- 只用给出的数字和时间，不要编造比分、球员、球队、战术。少堆数字，每句最多一两个。
- "看不出"的出手不要猜结果；最多在结尾用半句话提醒"部分出手结果待回看确认"。建议不要是"补数据""复核统计"。
- 不要提模型、检测、置信度等技术词。

统计：
{data}"""


def recap_input(report: dict[str, Any]) -> str:
    s = report["stats"]
    lines = [f"视频长度 {_clock(report['duration'])}；出手 {s['attempts']}，进 {s['made']}，没进 {s['missed']}，看不出 {s['unknown']}，"
             f"能判断的命中率 {s['fg_pct'] if s['fg_pct'] is not None else '无'}%；跳投 {s['jump']}，上篮/扣篮 {s['layup']}。"]
    lines.append("分时段：" + "；".join(f"{p['label']} 出手{p['attempts']} 进{p['made']} 没进{p['missed']}" for p in report["periods"]))
    if report["streaks"]:
        lines.append("连续：" + "；".join(x["text"] for x in report["streaks"]))
    made = [s for s in report["shots"] if s["outcome"] == "made"]
    if made:
        lines.append("进球时间：" + "、".join(s["clock"] for s in made))
    return "\n".join(lines)


def recap_prompt(report: dict[str, Any]) -> str:
    return RECAP_PROMPT.format(data=recap_input(report))


# ---------- export ----------
def to_html(report: dict[str, Any], title: str, recap: str | None = None) -> str:
    """A self-contained page a coach can open or forward."""
    e = html.escape
    s = report["stats"]
    tiles = [("出手", s["attempts"]), ("进球", s["made"]), ("没进", s["missed"]),
             ("命中率", f"{s['fg_pct']}%" if s["fg_pct"] is not None else "—")]
    shot_rows = "".join(f"<tr><td>{e(x['clock'])}</td><td>{e(KIND_ZH.get(x['kind'], '投篮'))}</td>"
                        f"<td class='{x['outcome']}'>{e(OUTCOME_ZH[x['outcome']])}</td></tr>" for x in report["shots"])
    period_rows = "".join(f"<tr><td>{e(p['label'])}</td><td>{p['attempts']}</td><td>{p['made']}</td><td>{p['missed']}</td>"
                          f"<td>{str(p['fg_pct']) + '%' if p['fg_pct'] is not None else '—'}</td></tr>" for p in report["periods"])
    streaks = "".join(f"<li>{e(x['text'])}</li>" for x in report["streaks"])
    notes = "".join(f"<li>{e(n)}</li>" for n in report["notes"])
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)} · 赛后复盘</title>
<style>
:root{{--bg:#f6f7fb;--card:#fff;--ink:#141a2a;--muted:#5b6478;--line:#e3e6ef;--made:#15803d;--miss:#b42318;--accent:#ff6a1f}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0b1020;--card:#141b2d;--ink:#eef1f8;--muted:#9aa3b8;--line:#263049;--made:#4ade80;--miss:#f87171}}}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 -apple-system,"PingFang SC","Noto Sans CJK SC",sans-serif}}
main{{max-width:860px;margin:0 auto;padding:24px 16px 48px}}
h1{{margin:0 0 4px;font-size:24px}} h2{{font-size:17px;margin:28px 0 10px}}
.sub{{color:var(--muted);margin:0 0 18px}}
.tiles{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}}
.tile{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px;text-align:center}}
.tile b{{display:block;font-size:26px}} .tile span{{color:var(--muted);font-size:13px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 16px}}
table{{width:100%;border-collapse:collapse}} td,th{{padding:7px 8px;border-bottom:1px solid var(--line);text-align:left}}
th{{color:var(--muted);font-weight:600;font-size:13px}} .made{{color:var(--made);font-weight:700}} .missed{{color:var(--miss)}} .unknown{{color:var(--muted)}}
ul{{margin:0;padding-left:20px}} .fine{{color:var(--muted);font-size:12px;margin-top:24px}}
@media (max-width:520px){{.tiles{{grid-template-columns:repeat(2,1fr)}}}}
</style></head><body><main>
<h1>{e(title)} · 赛后复盘</h1><p class="sub">视频长度 {_clock(report['duration'])} · MoTrack 自动生成</p>
<div class="tiles">{''.join(f'<div class="tile"><b>{e(str(v))}</b><span>{e(k)}</span></div>' for k, v in tiles)}</div>
{f'<h2>AI 复盘</h2><div class="card">{e(recap)}</div>' if recap else ''}
<h2>要点</h2><div class="card"><ul>{notes}{streaks}</ul></div>
<h2>分时段</h2><div class="card"><table><tr><th>时段</th><th>出手</th><th>进</th><th>没进</th><th>命中率</th></tr>{period_rows}</table></div>
<h2>每次出手</h2><div class="card">{f'<table><tr><th>时间</th><th>方式</th><th>结果</th></tr>{shot_rows}</table>' if shot_rows else '没有检测到出手。'}</div>
<p class="fine">{e(report['caveat'])}</p>
</main></body></html>"""
