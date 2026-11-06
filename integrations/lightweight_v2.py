"""Auditable V2 processing for MoTrack's local X3D feature extractor.

V2 is intentionally a conservative ranking layer, not a claim that Kinetics-400
is a calibrated basketball event detector.  It retains every scanned window,
then exposes the rules used to group and rank generic action candidates.
"""
from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import cv2
from integrations.lightweight import ROOT, OUT, VIDEO_IDS, _hype_segments, _json, _video_info, _windows, render_plan, X3D

QUALITY_OUT = ROOT / "outputs" / "lightweight_quality_v2"

@dataclass(frozen=True)
class V2Config:
    shooting_min_softmax: float = 0.12
    basketball_min_softmax: float = 0.08
    merge_gap_seconds: float = 1.0
    merge_iou: float = 0.25
    pre_context: float = 2.0
    post_context: float = 2.0
    min_clip_seconds: float = 3.0
    weights: tuple[float, float, float] = (0.70, 0.25, 0.05)  # visual, HypeCut, support

def _intersection_over_union(a: dict[str, Any], b: dict[str, Any]) -> float:
    overlap=max(0.0,min(a['end_time'],b['end_time'])-max(a['start_time'],b['start_time']))
    union=max(a['end_time'],b['end_time'])-min(a['start_time'],b['start_time'])
    return overlap/union if union else 0.0

def _segment_for(start: float, segments: list[dict[str, Any]]) -> dict[str, Any] | None:
    for segment in segments:
        if float(segment['start']) <= start <= float(segment['end']): return segment
    return None

def _label_score(top5: list[dict[str, Any]], label: str) -> float:
    return next((float(x['softmax_score']) for x in top5 if x['label']==label), 0.0)

def _frames_v2(video: Path, start: float) -> tuple[list[Any],list[float]]:
    """Mirror X3D Hub's 1.6 s (4*12/30) clip plus uniform subsampling.

    We decode four positions uniformly across the 48-frame nominal clip. This
    replaces V1's hand-written end-point sampling only for V2; actual seek times
    are returned and written to the audit so decoder precision is visible.
    """
    cap=cv2.VideoCapture(str(video))
    if not cap.isOpened(): raise RuntimeError(f'cannot decode {video.name}')
    fps=cap.get(cv2.CAP_PROP_FPS) or 30.0
    # UniformTemporalSubsample spans [0, T-1] rather than treating 1.6 s as a
    # fifth sample. Floating frame positions preserve this intent at non-30 fps.
    offsets=[(47.0*i/3.0)/fps for i in range(4)]
    frames=[];times=[]
    for offset in offsets:
        timestamp=start+offset;cap.set(cv2.CAP_PROP_POS_MSEC,timestamp*1000);ok,frame=cap.read()
        if not ok: continue
        frames.append(frame);times.append(round(timestamp,6))
    cap.release()
    if len(frames)!=4: raise RuntimeError('insufficient decodable frames for X3D V2 window')
    return frames,times

def audit_windows(video_id: str, config: V2Config=V2Config()) -> dict[str, Any]:
    """Run every V2 scan window and persist unfiltered X3D evidence."""
    video=VIDEO_IDS[video_id]; info=_video_info(video); segments=_hype_segments(video_id)
    runner=X3D(); rows=[]; total_start=time.perf_counter()
    if runner.device.type=='cuda': torch = __import__('torch'); torch.cuda.reset_peak_memory_stats()
    for number,(start,sampling,segment) in enumerate(_windows(video_id,info['duration']),1):
        began=time.perf_counter(); frames,timestamps=_frames_v2(video,start)
        detail=runner.classify_detailed(frames)
        seg=segment or _segment_for(start,segments)
        top5=detail['top5']; shooting=_label_score(top5,'shooting basketball')
        basketball=max((_label_score(top5,label) for label in ('playing basketball','dribbling basketball','dunking basketball')),default=0.0)
        # Only a sufficiently strong shooting class is a *candidate* shot. Other
        # basketball labels remain generic activity candidates. No outcome class.
        if shooting >= config.shooting_min_softmax:
            event_type='shot_attempt'
        elif basketball >= config.basketball_min_softmax:
            event_type='basketball_action_candidate'
        else:
            event_type='UNKNOWN'
        rows.append({
            'window_id':f'{video_id}-w{number:03d}','source_video_id':video_id,
            'start_time':timestamps[0],'end_time':timestamps[-1],'frame_timestamps':timestamps,
            'input_frame_count':len(frames),'input_shape':detail['input_shape'],'sampling_strategy':sampling,
            'x3d_top5':top5,'softmax_score_type':detail['score_type'],
            'shooting_basketball_softmax':round(shooting,6),'best_basketball_activity_softmax':round(basketball,6),
            'inference_seconds':round(time.perf_counter()-began,6),
            'hypecut_signal':{'segment_score':seg.get('score') if seg else None,'reasons':seg.get('reasons') if seg else {},'segment_start':seg.get('start') if seg else None,'segment_end':seg.get('end') if seg else None},
            'v2_initial_event_type':event_type,'final_event_id':None,'final_event_type':None,
        })
    return {'schema_version':'2.0','video_id':video_id,'source_video':str(video.relative_to(ROOT)),
            'model':{'name':'PyTorchVideo X3D-XS','mode':'eval','device':str(runner.device),'model_load_seconds':runner.load_seconds,'gpu_model_memory_bytes':runner.memory_bytes,
                     'preprocessing':'BGR decoded by OpenCV → RGB; normalize mean=.45/std=.225; short-side resize 182; center crop 182; 4 uniformly sampled frames across a 4x12/30fps nominal clip.'},
            'config':asdict(config),'video_duration':info['duration'],'window_count':len(rows),'inference_total_seconds':round(time.perf_counter()-total_start,3),
            'peak_gpu_memory_bytes':int(__import__('torch').cuda.max_memory_allocated()) if runner.device.type=='cuda' else 0,'windows':rows}

def _raw_candidates(audit: dict[str,Any]) -> list[dict[str,Any]]:
    values=[]
    for row in audit['windows']:
        if row['v2_initial_event_type']=='UNKNOWN': continue
        visual=row['shooting_basketball_softmax'] if row['v2_initial_event_type']=='shot_attempt' else row['best_basketball_activity_softmax']
        values.append({'event_type':row['v2_initial_event_type'],'start_time':row['start_time'],'end_time':row['end_time'],'visual_score':visual,
                       'hypecut_score':float(row['hypecut_signal']['segment_score'] or 0.0),'source_window_ids':[row['window_id']],
                       'source_windows':[row], 'source_video_id':audit['video_id']})
    return values

def merge_candidates(audit: dict[str,Any], config:V2Config=V2Config()) -> list[dict[str,Any]]:
    """Group same conservative type only when overlap/gap is evidence-compatible."""
    merged=[]
    for item in sorted(_raw_candidates(audit),key=lambda x:(x['event_type'],x['start_time'])):
        current=merged[-1] if merged and merged[-1]['event_type']==item['event_type'] else None
        close=current and (item['start_time']-current['end_time']<=config.merge_gap_seconds or _intersection_over_union(current,item)>=config.merge_iou)
        if not close:
            merged.append(item);continue
        current['start_time']=min(current['start_time'],item['start_time']); current['end_time']=max(current['end_time'],item['end_time'])
        current['visual_score']=max(current['visual_score'],item['visual_score']);current['hypecut_score']=max(current['hypecut_score'],item['hypecut_score'])
        current['source_window_ids']+=item['source_window_ids'];current['source_windows']+=item['source_windows']
    wv,wh,ws=config.weights
    for index,event in enumerate(sorted(merged,key=lambda x:x['start_time']),1):
        support=min(1.0,len(event['source_window_ids'])/3.0)
        event['event_id']=f"v2-{audit['video_id']}-{index:03d}";event['temporal_support_score']=round(support,6)
        event['ranking_components']={'visual_action_relevance':round(event['visual_score'],6),'hypecut_signal':round(event['hypecut_score'],6),'temporal_support':round(support,6),'weights':{'visual':wv,'hypecut':wh,'support':ws}}
        event['final_ranking_score']=round(wv*event['visual_score']+wh*event['hypecut_score']+ws*support,6)
        event['verification_status']='MODEL_PREDICTED';event['source_model']='PyTorchVideo X3D-XS (Kinetics-400)'
        event['time_localization_method']='merged 1.6s scan windows; peak score retained';event['semantic_limit']='Not ground truth; generic Kinetics label is not a made/missed basket, steal, rebound, or possession.'
        for row in event['source_windows']:
            row['final_event_id']=event['event_id'];row['final_event_type']=event['event_type']
        del event['source_windows']
    return sorted(merged,key=lambda x:(-x['final_ranking_score'],x['start_time']))

def v2_events(video_id:str, force:bool=False, config:V2Config=V2Config()) -> dict[str,Any]:
    destination=QUALITY_OUT / video_id; destination.mkdir(parents=True,exist_ok=True)
    events_file=destination/'candidate_events.json'; audit_file=destination/'raw_window_predictions.json'
    if events_file.exists() and audit_file.exists() and not force: return _json(events_file,{})
    audit=audit_windows(video_id,config); candidates=merge_candidates(audit,config)
    # raw audit must include post-merge assignment for every scanned window.
    audit_file.write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
    raw_count=len(_raw_candidates(audit))
    result={'schema_version':'2.0','candidate_version':'lightweight_v2','video_id':video_id,'config':asdict(config),'events':candidates,
            'candidate_count':len(candidates),'raw_candidate_count':raw_count,'duplicate_merge_ratio':round((raw_count-len(candidates))/raw_count,6) if raw_count else 0,
            'raw_window_count':audit['window_count'],'limitations':'No human truth: Precision/Recall/F1/Coverage are UNVERIFIED.'}
    events_file.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    # The requested canonical audit names refer to ČBF; per-video copies remain
    # isolated below their video directories to prevent cross-video mixing.
    if video_id=='cbf':
        (QUALITY_OUT/'raw_window_predictions.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
        (QUALITY_OUT/'candidate_events.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result

def candidates_for_variant(video_id:str,variant:str) -> list[dict[str,Any]]:
    if variant=='v2': return v2_events(video_id).get('events',[])
    if variant=='v1': return _json(OUT/f'latest_{video_id}.json',{'events':[]}).get('events',[])
    if variant=='hypecut':
        return [{'event_id':f'hype-{video_id}-{i+1}','event_type':'hypecut_candidate','start_time':float(x['start']),'end_time':float(x['end']),
                 'visual_score':None,'hypecut_score':float(x['score']),'final_ranking_score':float(x['score']),'source_window_ids':[],
                 'verification_status':'SIGNAL_ONLY','hypecut_signal':x.get('reasons',{})} for i,x in enumerate(_hype_segments(video_id))]
    raise ValueError('unknown variant')

def make_plan(video_id:str,variant:str,target_duration:float=15.0,max_clips:int=3) -> dict[str,Any]:
    source=candidates_for_variant(video_id,variant)
    ranked=sorted(source,key=lambda x:float(x.get('final_ranking_score',x.get('raw_model_score',0.0))),reverse=True)
    chosen=[]
    for event in ranked:
        start=max(0.0,float(event['start_time'])-2.0);end=float(event['end_time'])+2.0
        if end-start<3.0: end=start+3.0
        if any(max(start,c['start_time'])<min(end,c['end_time']) for c in chosen): continue
        chosen.append({'event_id':event['event_id'],'event_type':event['event_type'],'start_time':start,'end_time':end,'ranking_score':event.get('final_ranking_score',event.get('raw_model_score'))})
        if len(chosen)>=max_clips: break
    return {'schema_version':'2.0','candidate_version':variant,'source_video_id':video_id,'target_duration':target_duration,'clips':sorted(chosen,key=lambda x:x['start_time']),
            'selection_rule':'descending transparent rank, then reject overlapping context windows','verification_status':'MODEL_PREDICTED' if variant!='hypecut' else 'SIGNAL_ONLY'}

def render_variant(video_id:str,variant:str,target_duration:float=15.0) -> dict[str,Any]:
    directory=QUALITY_OUT/video_id/variant;directory.mkdir(parents=True,exist_ok=True)
    plan=make_plan(video_id,variant,target_duration)
    (directory/'highlight_plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
    if not plan['clips']:
        return {'status':'NO_CANDIDATES','plan':plan}
    output=render_plan(video_id,plan,directory/'highlights.mp4')
    return {'status':'COMPLETED','plan':plan,'output':output}

def run_comparison(video_id:str,target_duration:float=15.0,force:bool=False) -> dict[str,Any]:
    if force: v2_events(video_id,force=True)
    else: v2_events(video_id)
    audit=_json(QUALITY_OUT/video_id/'raw_window_predictions.json',{})
    v1=_json(OUT/f'latest_{video_id}.json',{})
    result={'schema_version':'2.0','video_id':video_id,'target_duration':target_duration,'variants':{}}
    for variant in ('hypecut','v1','v2'):
        before=time.perf_counter();run=render_variant(video_id,variant,target_duration)
        source={'hypecut':{'window_count':None,'inference_seconds':0,'peak_gpu_memory_bytes':0},
                'v1':{'window_count':v1.get('performance',{}).get('windows'),'inference_seconds':v1.get('performance',{}).get('inference_total_seconds'),'peak_gpu_memory_bytes':v1.get('performance',{}).get('gpu_memory_model_bytes')},
                'v2':{'window_count':audit.get('window_count'),'inference_seconds':audit.get('inference_total_seconds'),'peak_gpu_memory_bytes':audit.get('peak_gpu_memory_bytes')}}[variant]
        result['variants'][variant]={'candidate_count':len(candidates_for_variant(video_id,variant)),'final_clip_count':len(run.get('plan',{}).get('clips',[])),'source_performance':source,'run':run,'render_wall_seconds':round(time.perf_counter()-before,3)}
    path=QUALITY_OUT/video_id/'comparison_summary.json';path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    cards=[]
    for variant,item in result['variants'].items():
        run=item['run']; video='highlights.mp4' if run['status']=='COMPLETED' else ''
        cards.append(f"<section><h2>{variant}</h2><p>候选：{item['candidate_count']}；状态：{run['status']}</p>" + (f"<video controls src=\"{variant}/{video}\"></video>" if video else "<p>没有可渲染候选。</p>") + "</section>")
    (QUALITY_OUT/video_id/'comparison.html').write_text("<!doctype html><meta charset=utf-8><title>MoTrack V2 对照</title><style>body{background:#08111f;color:#e8eef8;font:16px system-ui;margin:24px}main{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}section{background:#11243d;padding:16px;border-radius:12px}video{width:100%;background:#000}@media(max-width:900px){main{grid-template-columns:1fr}}</style><h1>"+video_id+"：HypeCut / Lightweight V1 / V2 对照</h1><p>没有人工真值；候选数不代表准确率。</p><main>"+''.join(cards)+"</main>",encoding='utf-8')
    if video_id=='cbf':
        for name in ('comparison_summary.json','comparison.html'):
            shutil.copy2(QUALITY_OUT/video_id/name,QUALITY_OUT/name)
        v2dir=QUALITY_OUT/video_id/'v2'
        for name in ('highlight_plan.json','highlights.mp4'):
            if (v2dir/name).is_file(): shutil.copy2(v2dir/name,QUALITY_OUT/name)
    return result
