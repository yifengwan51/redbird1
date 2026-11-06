#!/usr/bin/env python3
"""Cost-bounded real LLM chat; controller deterministically completes valid plans."""
from __future__ import annotations
import json,os,subprocess
from pathlib import Path
from openai import OpenAI
R=Path(__file__).resolve().parent;O=R/'outputs/agent_chat_optimized';O.mkdir(parents=True,exist_ok=True);FF=R/'tools/ffmpeg/bin/ffmpeg';P=R/'tools/ffmpeg/bin/ffprobe'
E=[e|{'id':f'vision-{i+1}'} for i,e in enumerate(json.loads((R/'outputs/semantic_vision_live/basketball_events.json').read_text())['events']) if 'cbf_3x3' in e['video_path']]
aliases={'shot':'shot_attempt','shoot':'shot_attempt','投篮':'shot_attempt','出手':'shot_attempt'}
TOOLS=[{'type':'function','function':{'name':'search_events','parameters':{'type':'object','properties':{'event_type':{'type':'string'},'min_confidence':{'type':'number'}},'additionalProperties':False}}},{'type':'function','function':{'name':'create_plan','parameters':{'type':'object','properties':{'event_ids':{'type':'array','items':{'type':'string'}},'target_duration':{'type':'number'},'pre_context':{'type':'number'},'post_context':{'type':'number'}},'required':['event_ids'],'additionalProperties':False}}}]
class Run:
 def __init__(self):
  self.c=OpenAI(api_key=os.environ['MOTRACK_API_KEY'],base_url=os.getenv('MOTRACK_API_BASE_URL','http://sub2api.adc-ingress.aeroht.net/v1'),timeout=90,max_retries=0);self.plan=None;self.trace=[];self.usage=[];self.hist=[{'role':'system','content':'MoTrack cached-vision editor. Valid event types: shot_attempt,made_basket,missed_shot,pass,rebound,steal,fast_break,UNKNOWN. Aliases shot/shoot/投篮/出手 mean shot_attempt. Events are MODEL_PREDICTED; never claim made basket without evidence. Use one tool only if needed. After plan creation controller renders/verifies.'},{'role':'system','content':'Video cbf_3x3_tour, 156.4s. Cached events: vision-2 shot_attempt 77s confidence .65; vision-3 shot_attempt 81-83s confidence .58. Both result unknown. Current plan: none.'}]
 def search(self,a):
  t=aliases.get(a.get('event_type',''),a.get('event_type'));return [x for x in E if (not t or x['event_type']==t) and x['confidence']>=a.get('min_confidence',0)]
 def make(self,a):
  es=[x for x in E if x['id'] in a['event_ids']];pre=float(a.get('pre_context',2));post=float(a.get('post_context',2));self.plan={'clips':[{'event_id':x['id'],'start':max(0,x['start_time']-pre),'end':x['end_time']+post,'event_type':x['event_type'],'confidence':x['confidence']} for x in es],'target_duration':float(a.get('target_duration',15))};(O/'highlight_plan.json').write_text(json.dumps(self.plan,indent=2));return self.plan
 def complete_plan(self):
  a=min(x['start'] for x in self.plan['clips']);b=min(max(x['end'] for x in self.plan['clips']),a+self.plan['target_duration']);subprocess.run([str(FF),'-y','-v','error','-ss',str(a),'-to',str(b),'-i',str(R/'inputs/cbf_3x3_tour.mp4'),'-c','copy',str(O/'highlights.mp4')],check=True);v=json.loads(subprocess.check_output([str(P),'-v','error','-show_entries','format=duration:stream=codec_type','-of','json',str(O/'highlights.mp4')]));self.trace += [{'initiator':'CONTROLLER','tool':'render_highlights','result':{'start':a,'end':b,'path':'outputs/agent_chat_optimized/highlights.mp4'}},{'initiator':'CONTROLLER','tool':'verify_render','result':v}];(O/'match_recap.json').write_text(json.dumps({'events':[{'event_id':x['event_id'],'event_type':x['event_type'],'confidence':x['confidence'],'verification_status':'MODEL_PREDICTED','note':'Shot result unconfirmed.'} for x in self.plan['clips']]},indent=2));return v
 def turn(self,text):
  self.hist.append({'role':'user','content':text});x=self.c.chat.completions.create(model='deepseek-v4.1-flash',messages=self.hist,tools=TOOLS,tool_choice='auto',max_tokens=100,temperature=0.1,extra_body={'reasoning_effort':'low'});m=x.choices[0].message;self.usage.append(x.usage.model_dump() if x.usage else {});self.hist.append(m.model_dump(exclude_none=True))
  for tc in m.tool_calls or []:
   a=json.loads(tc.function.arguments);res=self.search(a) if tc.function.name=='search_events' else self.make(a);self.trace.append({'initiator':'LLM','tool_call_id':tc.id,'tool':tc.function.name,'arguments':a,'result':res});self.hist.append({'role':'tool','tool_call_id':tc.id,'content':json.dumps(res)})
   if tc.function.name=='create_plan': self.complete_plan()
  if m.tool_calls and not (m.content or '').strip():
   follow=self.c.chat.completions.create(model='deepseek-v4.1-flash',messages=self.hist,max_tokens=100,temperature=0.1,extra_body={'reasoning_effort':'low'}); self.usage.append(follow.usage.model_dump() if follow.usage else {}); m=follow.choices[0].message; self.hist.append(m.model_dump(exclude_none=True))
  self.save();return m.content or ''
 def save(self):
  (O/'session_history.json').write_text(json.dumps(self.hist,ensure_ascii=False,indent=2));(O/'tool_trace.json').write_text(json.dumps(self.trace,ensure_ascii=False,indent=2));(O/'api_usage.json').write_text(json.dumps(self.usage,indent=2));(O/'run_summary.json').write_text(json.dumps({'state':'TASK_COMPLETED' if self.plan and (O/'highlights.mp4').exists() else 'INTENT_PARSED','requests':len(self.usage),'cached_vision':True},indent=2))
if __name__=='__main__':
 r=Run()
 for q in ['帮我生成一段投篮高光。','缩短到15秒。','解释这些片段。','这些投篮是否命中了？']: print(r.turn(q))
