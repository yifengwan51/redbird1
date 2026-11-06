#!/usr/bin/env python3
"""Auditable HTADC vision test: frames are sent as data:image/jpeg URLs, never paths."""
from __future__ import annotations
import base64, hashlib, json, os, sys, io
from pathlib import Path
from PIL import Image
from openai import OpenAI

ROOT=Path(__file__).resolve().parent; OUT=ROOT/'outputs/semantic_vision_live'; OUT.mkdir(parents=True,exist_ok=True)
CASES={'doug':(8.0,16.0,[ROOT/f'outputs/semantic_validation/frames/doug_{x}s.jpg' for x in (8,10,12,14,16)]),'cbf':(75.0,83.0,[ROOT/f'outputs/semantic_validation/frames/cbf_{x}s.jpg' for x in (75,77,79,81,83)])}
PROMPT='''You inspect consecutive basketball-video frames. Return ONLY JSON: {"events":[{"event_type":"shot_attempt|made_basket|missed_shot|steal|rebound|pass|fast_break|UNKNOWN","start_time":number,"end_time":number,"evidence_frames":[number],"evidence_description":string,"confidence":number,"verification_status":"MODEL_PREDICTED|UNVERIFIED","player":null,"team":null}]}. Do not infer score, player, team, or made basket unless visually supported. A shot with unknown result is shot_attempt. This is model prediction, never human verification.'''
def part(p):
 raw=p.read_bytes(); im=Image.open(p).convert('RGB'); w,h=im.size
 if max(w,h)>768: im.thumbnail((768,768)); buf=io.BytesIO(); im.save(buf,format='JPEG',quality=82,optimize=True); b=buf.getvalue()
 else: b=raw
 sw,sh=Image.open(io.BytesIO(b)).size
 return {'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+base64.b64encode(b).decode()},'_audit':{'file':str(p.relative_to(ROOT)),'source_sha256':hashlib.sha256(raw).hexdigest(),'sent_sha256':hashlib.sha256(b).hexdigest(),'width':sw,'height':sh,'bytes':len(b)}}
def run(name):
 start,end,frames=CASES[name]; entries=[part(p) for p in frames]; audit={'case':name,'model':os.getenv('MOTRACK_API_MODEL','deepseek-v4.1-flash'),'base_url':os.getenv('MOTRACK_API_BASE_URL','http://sub2api.adc-ingress.aeroht.net/v1'),'timestamps':[start+(end-start)*i/(len(frames)-1) for i in range(len(frames))],'images':[x['_audit'] for x in entries]}
 content=[{'type':'text','text':PROMPT+f' Video range: {start}-{end}s. Frame timestamps: {audit["timestamps"]}.'}]+[{k:v for k,v in x.items() if k!='_audit'} for x in entries]
 key=os.getenv('MOTRACK_API_KEY');
 if not key: raise RuntimeError('MOTRACK_API_KEY is required')
 c=OpenAI(api_key=key,base_url=audit['base_url'],timeout=90,max_retries=0)
 r=c.chat.completions.create(model=audit['model'],messages=[{'role':'user','content':content}],max_tokens=700,temperature=0.1,response_format={'type':'json_object'})
 audit.update({'request_id':getattr(r,'_request_id',None),'usage':r.usage.model_dump() if r.usage else {},'image_content_blocks':len(entries)})
 try: events=json.loads(r.choices[0].message.content).get('events',[])
 except Exception: events=[]
 for e in events: e['verification_status']='MODEL_PREDICTED' if e.get('event_type')!='UNKNOWN' else 'UNVERIFIED'; e['source']='HTADC vision sequence'; e['video_path']=str((ROOT/'inputs'/('doug_mcdermott.mp4' if name=='doug' else 'cbf_3x3_tour.mp4')).relative_to(ROOT))
 (OUT/f'{name}_events.json').write_text(json.dumps({'events':events},ensure_ascii=False,indent=2)); return audit,events
if __name__=='__main__':
 audits=[]; all_events=[]
 for n in CASES:
  a,e=run(n);audits.append(a);all_events+=e
 (OUT/'vision_requests_audit.json').write_text(json.dumps(audits,indent=2));(OUT/'basketball_events.json').write_text(json.dumps({'events':all_events},ensure_ascii=False,indent=2));(OUT/'api_usage.json').write_text(json.dumps([a['usage'] for a in audits],indent=2))
