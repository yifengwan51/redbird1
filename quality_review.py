#!/usr/bin/env python3
"""Build a static, offline human-review package from existing MoTrack artifacts."""
from __future__ import annotations

import html
import json
from pathlib import Path

R = Path(__file__).resolve().parent
O = R / "outputs" / "quality_review"


def main() -> int:
    O.mkdir(parents=True, exist_ok=True)
    source = R / "outputs/semantic_vision_live/basketball_events.json"
    if not source.is_file():
        raise SystemExit(f"missing cached vision events: {source}")
    vision = json.loads(source.read_text(encoding="utf-8"))["events"]
    events = []
    for index, event in enumerate(vision, 1):
        video = "doug" if "doug_" in event["video_path"] else "cbf"
        events.append({
            "event_id": f"{video}-model-{index:03d}",
            "source_video_id": video,
            "event_type": event["event_type"],
            "start_time": event["start_time"],
            "end_time": event["end_time"],
            "confidence": event["confidence"],
            "verification_status": event["verification_status"],
            "evidence": event["evidence_description"],
            "evidence_frames": event["evidence_frames"],
            "source_model": "deepseek-v4.1-flash",
        })
    template = {
        "schema_version": "1.0",
        "matching_rule": {"time_tolerance_seconds": 2.0, "same_event_type_required": True},
        "events": [{"event_id": e["event_id"], "human_event_type": "UNREVIEWED", "verdict": "UNREVIEWED",
                    "start_time": e["start_time"], "end_time": e["end_time"], "notes": ""} for e in events],
        "missed_events": [],
        "highlight_review": {"completeness": "UNREVIEWED", "duplicate_clip_count": None, "meaningless_seconds": None, "notes": ""},
    }
    (O / "events.json").write_text(json.dumps({"events": events}, ensure_ascii=False, indent=2), encoding="utf-8")
    (O / "human_review_template.json").write_text(json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8")
    rows = "".join(
        "<tr><td>{id}</td><td>{video}</td><td>{start:.1f}-{end:.1f}</td><td>{type}</td><td>{confidence}</td>"
        "<td>{status}</td><td><select data-id=\"{id}\"><option>UNREVIEWED</option><option>correct</option>"
        "<option>incorrect</option><option>type_error</option><option>boundary_issue</option></select></td></tr>".format(
            id=html.escape(e["event_id"], quote=True),
            video=html.escape(e["source_video_id"], quote=True),
            start=e["start_time"], end=e["end_time"],
            type=html.escape(str(e["event_type"])),
            confidence=html.escape(str(e["confidence"]), quote=True),
            status=html.escape(str(e["verification_status"]), quote=True),
        )
        for e in events
    )
    page = """<!doctype html><meta charset=utf-8><title>MoTrack Human Review</title>
<style>body{{font:14px sans-serif;max-width:1100px;margin:auto}}video{{width:48%;vertical-align:top}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #bbb;padding:6px}}textarea{{width:100%;height:70px}}</style>
<h1>MoTrack 人工审核</h1><p>模型预测不是人工真值。先回看原视频，再填写 verdict。未完成全部审核时指标为 UNVERIFIED。</p>
<h2>ČBF 对照</h2><video controls src="../../inputs/cbf_3x3_tour.mp4"></video><video controls src="../agent_chat_optimized/highlights.mp4"></video>
<h2>Doug 原视频</h2><video controls src="../../inputs/doug_mcdermott.mp4"></video>
<h2>模型事件</h2><table><tr><th>ID</th><th>视频</th><th>时间</th><th>模型类型</th><th>置信度</th><th>状态</th><th>人工 verdict</th></tr>{rows}</table>
<h2>遗漏事件</h2><p>每行：source_video_id,event_type,start_time,end_time,notes</p><textarea id=missed placeholder="cbf,shot_attempt,90,93,example"></textarea>
<p><button onclick=save()>保存到浏览器</button> <button onclick=download()>下载 human_review.json</button></p>
<pre id=status>Metrics: UNVERIFIED — requires completed human review and manually added missed events.</pre>
<script>
const key='motrack-quality-review-v1';
function data(){{return {{schema_version:'1.0',events:[...document.querySelectorAll('select')].map(x=>({{event_id:x.dataset.id,verdict:x.value}})),missed_events:document.getElementById('missed').value.split('\\n').filter(Boolean),metrics:'UNVERIFIED until human ground truth complete'}}}}
function save(){{localStorage.setItem(key,JSON.stringify(data()));status.textContent='Saved locally. Download JSON to make a project review artifact.'}}
function download(){{let b=new Blob([JSON.stringify(data(),null,2)],{{type:'application/json'}}),a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='human_review.json';a.click()}}
let old=localStorage.getItem(key);if(old){{let d=JSON.parse(old);d.events.forEach(e=>{{let x=document.querySelector('[data-id="'+e.event_id+'"]');if(x)x.value=e.verdict}});missed.value=(d.missed_events||[]).join('\\n')}}
</script>
""".format(rows=rows)
    (O / "review.html").write_text(page, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
