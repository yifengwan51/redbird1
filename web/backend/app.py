from __future__ import annotations
import json, shutil, subprocess, threading, time, uuid, os
from pathlib import Path
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

ROOT=Path(__file__).resolve().parents[2]; OUT=ROOT/'outputs'; FF=ROOT/'tools/ffmpeg/bin/ffmpeg'; PROBE=ROOT/'tools/ffmpeg/bin/ffprobe'
app=FastAPI(title='MoTrack Web MVP'); jobs={}; chat_sessions={}
lightweight_sessions={}
app.mount('/app',StaticFiles(directory=ROOT/'web/frontend'),name='app')
def safe(p:Path):
 p=p.resolve()
 if ROOT not in p.parents and p!=ROOT: raise HTTPException(403,'拒绝项目外路径')
 return p
def read(p): return json.loads(safe(p).read_text())
VIDEOS={'cbf':{'id':'cbf','name':'ČBF 3x3 Tour','path':'inputs/cbf_3x3_tour.mp4'},'doug':{'id':'doug','name':'Doug McDermott','path':'inputs/doug_mcdermott.mp4'}}
def events(video, mode='llm', variant='v1'):
 if mode=='lightweight':
  if variant!='v1':
   from integrations.lightweight_v2 import candidates_for_variant
   return candidates_for_variant(video,variant)
  from integrations.lightweight import events as local_events
  return local_events(video, analyze_if_missing=False)
 return [e|{'source_video_id':'doug' if 'doug_' in e['video_path'] else 'cbf','source_model':'deepseek-v4.1-flash','evidence_source':'CACHED_VISION'} for e in read(OUT/'semantic_vision_live/basketball_events.json')['events'] if video in e['video_path']]
@app.get('/api/v1/health')
def health(): return {'status':'ok','modes':['llm','lightweight'],'bind':'127.0.0.1'}
@app.get('/api/v1/capabilities')
def caps(): return {'llm':{'available':True,'cached_vision':True,'live_vision_requires_explicit_action':True},'lightweight':{'available':True,'model':'PyTorchVideo X3D-XS / Kinetics-400','network_required':False,'limitations':'Generic action candidates only; no confirmed makes, steals, rebounds, identity, or possession.'}}
@app.get('/api/v1/videos')
def videos(): return list(VIDEOS.values())
@app.get('/api/v1/videos/{video_id}/events')
def get_events(video_id:str,mode:str='llm',variant:str='v1'):
 if video_id not in VIDEOS: raise HTTPException(404,'未知视频')
 if mode not in {'llm','lightweight'}: raise HTTPException(400,'不支持的模式')
 if variant not in {'v1','v2','hypecut'}: raise HTTPException(400,'不支持的候选版本')
 return {'events':events(video_id,mode,variant),'mode':mode,'candidate_version':variant if mode=='lightweight' else None}
@app.get('/api/v1/videos/{video_id}/candidates')
def candidates(video_id:str,variant:str='v2'):
 if video_id not in VIDEOS or variant not in {'v1','v2','hypecut'}: raise HTTPException(404,'未知视频或版本')
 return {'video_id':video_id,'candidate_version':variant,'events':events(video_id,'lightweight',variant)}
@app.get('/api/v1/videos/{video_id}/recap')
def recap(video_id:str):
 p=OUT/'agent_multimodal/match_recap.json' if video_id=='cbf' else OUT/'agent_deepseek/match_recap.json'
 return read(p) if p.exists() else {'status':'UNAVAILABLE'}
@app.get('/api/v1/media/{kind}/{name}')
def media(kind:str,name:str):
 base={'source':ROOT/'inputs','highlight':OUT/'agent_chat_optimized','job':OUT/'web_jobs'}.get(kind)
 if not base or '/' in name or '\\' in name: raise HTTPException(400,'无效资源名')
 p=safe(base/name)
 if not p.is_file(): raise HTTPException(404,'文件不存在')
 return FileResponse(p)
@app.get('/api/v1/artifact')
def artifact(path:str):
 p=safe(ROOT/path)
 allowed=(OUT/'lightweight_agent', OUT/'lightweight', OUT/'lightweight_quality_v2', OUT/'web_jobs', OUT/'web_chat')
 if not any(base.resolve() in (p, *p.parents) for base in allowed): raise HTTPException(403,'不允许的产物路径')
 if not p.is_file() or p.suffix.lower() not in {'.mp4','.json'}: raise HTTPException(404,'产物不存在或类型不允许')
 return FileResponse(p)
@app.post('/api/v1/highlights')
def highlights(payload:dict):
 vid=payload.get('video_id','cbf'); duration=float(payload.get('target_duration',15)); types=payload.get('event_types',['shot_attempt'])
 mode=payload.get('mode','llm')
 variant=payload.get('candidate_version','v1')
 if mode=='lightweight':
  from integrations.lightweight import LightweightSession
  if vid not in VIDEOS: raise HTTPException(404,'未知视频')
  if not 5<=duration<=60 or not isinstance(types,list): raise HTTPException(400,'轻量模式仅支持 5-60 秒和合法事件类型')
  jid='lw-'+uuid.uuid4().hex[:12]
  if variant not in {'v1','v2','hypecut'}: raise HTTPException(400,'不支持的候选版本')
  session=LightweightSession(video_id=vid,session_id=jid,candidate_version=variant); lightweight_sessions[jid]=session
  prompt=('生成投篮高光 ' if 'shot_attempt' in types else '生成篮球高光 ') + f'{duration}秒'
  jobs[jid]={'id':jid,'mode':'lightweight','candidate_version':variant,'status':'queued','stage':'QUEUED','session_id':jid,'video_id':vid,'initiator':'CONTROLLER','prompt':prompt}
  def local_work():
   jobs[jid].update(status='running',stage='LOCAL_AGENT_RUNNING')
   result=session.ask(prompt)
   if result.get('failure'):
    jobs[jid].update(status='failed',stage=result['failure'].get('stage','FAILED'),error=result['failure'],result=result)
   else:
    jobs[jid].update(status='completed',stage='OUTPUT_VERIFIED',result=result)
  threading.Thread(target=local_work,daemon=True).start()
  return jobs[jid]
 if mode!='llm': raise HTTPException(400,'不支持的模式')
 if vid!='cbf' or not 5<=duration<=60 or not isinstance(types,list): raise HTTPException(400,'当前仅支持 ČBF、5-60 秒和合法事件类型')
 es=[e for e in events('cbf') if e['event_type'] in types]
 if not es: raise HTTPException(422,'没有符合缓存视觉证据的事件')
 jid='job-'+uuid.uuid4().hex[:8]; d=OUT/'web_jobs'/jid; d.mkdir(parents=True); jobs[jid]={'id':jid,'status':'queued','initiator':'CONTROLLER','events':es}
 def work():
  try:
   jobs[jid]['status']='running'; a=max(0,min(e['start_time'] for e in es)-2);b=min(a+duration,max(e['end_time'] for e in es)+2)
   dest=d/'highlights.mp4'; subprocess.run([str(FF),'-y','-v','error','-ss',str(a),'-to',str(b),'-i',str(ROOT/VIDEOS[vid]['path']),'-c','copy',str(dest)],check=True)
   probe=json.loads(subprocess.check_output([str(PROBE),'-v','error','-show_entries','format=duration:stream=codec_type','-of','json',str(dest)])); plan={'source_video_id':vid,'clips':[{'start':a,'end':b,'event_ids':[e['event_type']+'@'+str(e['start_time']) for e in es]}],'verification_status':'MODEL_PREDICTED'}
   (d/'highlight_plan.json').write_text(json.dumps(plan,indent=2));(d/'trace.json').write_text(json.dumps([{'initiator':'CONTROLLER','tool':'render_highlights'},{'initiator':'CONTROLLER','tool':'verify_render','result':probe}],indent=2));jobs[jid].update(status='completed',result={'video':f'/api/v1/media/job/{jid}/highlights.mp4','duration':probe['format']['duration'],'plan':plan})
  except Exception as e: jobs[jid].update(status='failed',error=type(e).__name__)
 threading.Thread(target=work,daemon=True).start(); return jobs[jid]
@app.get('/api/v1/jobs/{job_id}')
def job(job_id:str):
 if job_id not in jobs: raise HTTPException(404,'任务不存在')
 return jobs[job_id]
@app.get('/api/v1/jobs/{job_id}/trace')
def trace(job_id:str):
 if job_id not in jobs: raise HTTPException(404,'任务不存在')
 if jobs[job_id].get('mode')=='lightweight': return read(OUT/'lightweight_agent'/job_id/'tool_trace.json')
 return read(OUT/'web_jobs'/job_id/'trace.json')
@app.post('/api/v1/chat')
def chat(payload:dict):
 text=str(payload.get('message','')).strip()
 if not text: raise HTTPException(400,'消息不能为空')
 mode=str(payload.get('mode','llm'))
 video_id=str(payload.get('video_id','cbf'))
 variant=str(payload.get('candidate_version','v1'))
 if mode=='lightweight':
  if video_id not in VIDEOS: raise HTTPException(404,'未知视频')
  sid=str(payload.get('session_id') or uuid.uuid4().hex[:12])
  try:
   from integrations.lightweight import LightweightSession
   if variant not in {'v1','v2','hypecut'}: raise HTTPException(400,'不支持的候选版本')
   if sid not in lightweight_sessions: lightweight_sessions[sid]=LightweightSession(video_id=video_id,session_id=sid,candidate_version=variant)
   elif lightweight_sessions[sid].video_id != video_id: raise HTTPException(409,'会话属于另一段视频；切换视频后请创建新会话')
   elif lightweight_sessions[sid].candidate_version != variant: raise HTTPException(409,'会话属于另一候选版本；切换版本后请创建新会话')
   result=lightweight_sessions[sid].ask(text)
   if result.get('failure'): result['error']=result['failure']
   return result
  except HTTPException: raise
  except Exception as exc: raise HTTPException(422,{'stage':'WEB_CHAT','error_type':type(exc).__name__,'retryable':True})
 if mode!='llm': raise HTTPException(400,'不支持的模式')
 key=os.getenv('MOTRACK_API_KEY') or ((ROOT/'.secrets/htadc_api_key').read_text().strip() if (ROOT/'.secrets/htadc_api_key').is_file() else '')
 if not key: raise HTTPException(503,'项目内 HTADC 密钥不可用')
 sid=str(payload.get('session_id') or uuid.uuid4().hex[:12])
 try:
  import motrack_chat_optimized as agent
  if sid not in chat_sessions:
   session_out=OUT/'web_chat'/sid;session_out.mkdir(parents=True,exist_ok=True); agent.O=session_out; os.environ['MOTRACK_API_KEY']=key; chat_sessions[sid]=agent.Run()
  reply=chat_sessions[sid].turn(text)
  return {'reply':reply or '工具调用已完成。','session_id':sid,'mode':'CACHED_VISION','llm_called':True,'artifacts':f'outputs/web_chat/{sid}'}
 except Exception as exc: raise HTTPException(502,f'Agent 调用失败：{type(exc).__name__}')
@app.post('/api/v1/upload')
async def upload(file:UploadFile=File(...)):
 if file.content_type not in {'video/mp4','video/webm'}: raise HTTPException(415,'仅支持 MP4/WebM')
 data=await file.read()
 if len(data)>200*1024*1024: raise HTTPException(413,'文件超过 200MB')
 target=ROOT/'inputs/uploads';target.mkdir(exist_ok=True); name=Path(file.filename or 'upload.mp4').name; (target/name).write_bytes(data)
 return {'status':'stored','path':str((target/name).relative_to(ROOT)),'note':'上传已保存；任意上传视频的完整 Agent 分析尚未启用。'}
