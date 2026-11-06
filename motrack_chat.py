#!/usr/bin/env python3
"""Stateful HTADC Function Calling chat over cached MoTrack visual events."""
from __future__ import annotations
import json,os,subprocess,sys,uuid
from pathlib import Path
from openai import OpenAI
ROOT=Path(__file__).resolve().parent; OUT=ROOT/'outputs/agent_chat'; OUT.mkdir(parents=True,exist_ok=True); FF=ROOT/'tools/ffmpeg/bin/ffmpeg'; PROBE=ROOT/'tools/ffmpeg/bin/ffprobe'
TOOLS=[{'type':'function','function':{'name':'search_events','description':'Search cached MODEL_PREDICTED basketball events only.','parameters':{'type':'object','properties':{'event_type':{'type':'string'},'start_time':{'type':'number'},'end_time':{'type':'number'},'min_confidence':{'type':'number'}},'additionalProperties':False}}},{'type':'function','function':{'name':'update_highlight_plan','description':'Create/update plan from event IDs with context and duration cap.','parameters':{'type':'object','properties':{'event_ids':{'type':'array','items':{'type':'string'}},'target_duration':{'type':'number'},'pre_context':{'type':'number'},'post_context':{'type':'number'}},'required':['event_ids'],'additionalProperties':False}}},{'type':'function','function':{'name':'render_highlights','description':'Render current plan locally.','parameters':{'type':'object','properties':{},'additionalProperties':False}}},{'type':'function','function':{'name':'verify_render','description':'Probe current output.','parameters':{'type':'object','properties':{},'additionalProperties':False}}},{'type':'function','function':{'name':'generate_recap','description':'Write evidence-bounded recap.','parameters':{'type':'object','properties':{},'additionalProperties':False}}}]
class Chat:
 def __init__(self,video):
  self.video=Path(video).resolve(); self.events=[e|{'event_id':f'vision-{i+1}'} for i,e in enumerate(json.loads((ROOT/'outputs/semantic_vision_live/basketball_events.json').read_text())['events']) if e['video_path'].endswith(self.video.name)];self.plan=None;self.trace=[];self.hist=[{'role':'system','content':'You are MoTrack. Use tools. Cached events are MODEL_PREDICTED, never human verified. Never claim made baskets, scores, teams or players without evidence. Reuse cached vision; do not request new image analysis.'}];self.usage=[]
  self.client=OpenAI(api_key=os.environ['MOTRACK_API_KEY'],base_url=os.getenv('MOTRACK_API_BASE_URL','http://sub2api.adc-ingress.aeroht.net/v1'),timeout=90,max_retries=0)
 def call(self,name,a):
  if name=='search_events': r=[e for e in self.events if (not a.get('event_type') or e['event_type']==a['event_type']) and e['confidence']>=a.get('min_confidence',0) and (a.get('start_time') is None or e['end_time']>=a['start_time']) and (a.get('end_time') is None or e['start_time']<=a['end_time'])]
  elif name=='update_highlight_plan':
   es=[e for e in self.events if e['event_id'] in a['event_ids']]; pre=float(a.get('pre_context',6));post=float(a.get('post_context',6)); clips=[]
   for e in es: clips.append({'event_id':e['event_id'],'start':max(0,e['start_time']-pre),'end':e['end_time']+post,'event_type':e['event_type'],'confidence':e['confidence']})
   clips.sort(key=lambda x:x['start']); self.plan={'clips':clips,'target_duration':a.get('target_duration',30),'source':str(self.video.relative_to(ROOT))};r=self.plan;(OUT/'highlight_plan.json').write_text(json.dumps(r,indent=2))
  elif name=='render_highlights':
   if not self.plan: raise ValueError('no plan')
   clips=self.plan['clips'] # merge to avoid duplicate context
   a0=min(x['start'] for x in clips);b=max(x['end'] for x in clips); target=float(self.plan.get('target_duration',30)); b=min(b,a0+target)
   subprocess.run([str(FF),'-y','-v','error','-ss',str(a0),'-to',str(b),'-i',str(self.video),'-c','copy',str(OUT/'highlights.mp4')],check=True);r={'path':'outputs/agent_chat/highlights.mp4','start':a0,'end':b}
  elif name=='verify_render': r=json.loads(subprocess.check_output([str(PROBE),'-v','error','-show_entries','format=duration:stream=codec_type','-of','json',str(OUT/'highlights.mp4')]))
  elif name=='generate_recap':
   r={'events':[{'event_id':x['event_id'],'event_type':x['event_type'],'confidence':x['confidence'],'statement':'Model-predicted shot attempt; result is unconfirmed.','verification_status':'MODEL_PREDICTED'} for x in self.plan['clips']]};(OUT/'match_recap.json').write_text(json.dumps(r,indent=2))
  else: raise ValueError('unapproved tool')
  self.trace.append({'tool':name,'arguments':a,'result':r});return r
 def turn(self,text):
  self.hist.append({'role':'user','content':text})
  for _ in range(8):
   x=self.client.chat.completions.create(model=os.getenv('MOTRACK_API_MODEL','deepseek-v4.1-flash'),messages=self.hist,tools=TOOLS,tool_choice='auto',max_tokens=250,temperature=0.1);m=x.choices[0].message;self.usage.append(x.usage.model_dump() if x.usage else {}); self.hist.append(m.model_dump(exclude_none=True))
   if not m.tool_calls: break
   for tc in m.tool_calls:
    try:r=self.call(tc.function.name,json.loads(tc.function.arguments))
    except Exception as e:r={'error':type(e).__name__,'message':str(e)}
    self.hist.append({'role':'tool','tool_call_id':tc.id,'content':json.dumps(r)})
  self.save();return m.content or ''
 def save(self):
  (OUT/'session_history.json').write_text(json.dumps(self.hist,ensure_ascii=False,indent=2));(OUT/'tool_trace.json').write_text(json.dumps(self.trace,ensure_ascii=False,indent=2));(OUT/'api_usage.json').write_text(json.dumps(self.usage,indent=2));(OUT/'run_summary.json').write_text(json.dumps({'cached_vision':True,'requests':len(self.usage),'events':len(self.events)},indent=2))
if __name__=='__main__':
 c=Chat(sys.argv[1]);
 for line in sys.stdin:
  if line.strip() in ('exit','quit'):break
  print(c.turn(line.strip()))
