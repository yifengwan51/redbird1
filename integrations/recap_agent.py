"""Evidence-bounded event retrieval, chains, recap, and local review artifacts."""
from __future__ import annotations
import json, html
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

class RecapAgent:
 def __init__(self, run=ROOT/'outputs/agent_deepseek'):
  self.run=Path(run); plan=json.loads(next(p for p in self.run.glob('plan-*.json') if '_recap' not in p.name).read_text()); source=plan['source']
  self.events=[]
  for i,s in enumerate(plan['segments'],1): self.events.append({'event_id':f'event-{i:03d}','event_type':'UNVERIFIED','start_time':s['start'],'end_time':s['end'],'confidence':round(float(s['score']),4),'evidence':{'signals':s['reasons'],'source':'HypeCut candidate + DeepSeek selection; no semantic visual conclusion'},'video_path':source,'player':'UNKNOWN','team':'UNKNOWN','possession':'UNKNOWN','verification_status':'UNVERIFIED'})
 def save(self):
  (self.run/'basketball_events.json').write_text(json.dumps({'events':self.events},indent=2)); return self.run/'basketball_events.json'
 def search_events(self,query='',event_type=None,start_time=None,end_time=None,min_confidence=0):
  q=(query or '').lower(); wanted=(event_type or '').lower()
  aliases={'投篮':'shot','抢断':'steal','篮板':'rebound','助攻':'assist','快攻':'fast_break'}
  if any(k in q for k in aliases) or wanted in aliases.values(): return [] # no visual classification evidence
  return [e for e in self.events if e['confidence']>=min_confidence and (start_time is None or e['end_time']>=start_time) and (end_time is None or e['start_time']<=end_time)]
 def build_event_chains(self,gap=12):
  chains=[]
  for e in self.events:
   if not chains or e['start_time']-chains[-1]['end_time']>gap: chains.append({'chain_id':f'chain-{len(chains)+1:03d}','start_time':e['start_time'],'end_time':e['end_time'],'event_ids':[e['event_id']],'ordered_events':[e],'evidence':['Temporal proximity only; no possession evidence.'],'verification_status':'POSSIBLE_CHAIN'})
   else: chains[-1]['end_time']=e['end_time'];chains[-1]['event_ids'].append(e['event_id']);chains[-1]['ordered_events'].append(e)
  return chains
 def analyze_key_possession(self,chain):
  return {'time_range':[chain['start_time'],chain['end_time']],'ordered_events':chain['event_ids'],'key_timepoints':[e['start_time'] for e in chain['ordered_events']],'summary':'A sequence of selected candidate windows; no possession, player, or basketball action is confirmed.','uncertainty':'No semantic event labels or ball-possession evidence.','verification_status':chain['verification_status']}
 def review_artifacts(self):
  self.save(); chains=self.build_event_chains(); recap={'chains':chains,'key_possessions':[self.analyze_key_possession(c) for c in chains]}; (self.run/'match_recap.json').write_text(json.dumps(recap,indent=2))
  labels=self.run/'human_review.json'; labels.write_text(json.dumps({'instructions':'Set verdict to correct, incorrect, missed, type_error, or boundary_issue after viewing the video. Metrics remain UNVERIFIED until completed.','items':[{'event_id':e['event_id'],'verdict':'UNREVIEWED','notes':''} for e in self.events]},indent=2))
  rows=''.join(f"<tr><td>{e['event_id']}</td><td>{e['start_time']:.3f}-{e['end_time']:.3f}</td><td>{e['confidence']}</td><td>{html.escape(e['event_type'])}</td><td>UNREVIEWED</td></tr>" for e in self.events)
  (self.run/'review.html').write_text(f"<html><body><h1>MoTrack review</h1><video controls width=720 src='plan-9542430a.mp4'></video><table border=1><tr><th>ID</th><th>Time</th><th>Score</th><th>Type</th><th>Human verdict</th></tr>{rows}</table><p>Edit human_review.json before calculating Precision/Recall/F1/Coverage: UNVERIFIED.</p></body></html>")
  return recap
