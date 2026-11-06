from __future__ import annotations
import json, os, subprocess, threading, uuid
from pathlib import Path
from urllib.parse import quote
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from integrations.security import ensure_inside, validate_session_id

ROOT=Path(__file__).resolve().parents[2]; OUT=ROOT/'outputs'; FF=ROOT/'tools/ffmpeg/bin/ffmpeg'; PROBE=ROOT/'tools/ffmpeg/bin/ffprobe'
app=FastAPI(title='MoTrack Web MVP'); jobs={}; chat_sessions={}
lightweight_sessions={}
app.mount('/app',StaticFiles(directory=ROOT/'web/frontend'),name='app')
VIDEOS={'cbf':{'id':'cbf','name':'ČBF 3x3 Tour','path':'inputs/cbf_3x3_tour.mp4'},'doug':{'id':'doug','name':'Doug McDermott','path':'inputs/doug_mcdermott.mp4'}}
VIDEO_FILES={'cbf':'cbf_3x3_tour.mp4','doug':'doug_mcdermott.mp4'}
VISION_CACHE=OUT/'semantic_vision_live/basketball_events.json'
MAX_UPLOAD_BYTES=200*1024*1024
def safe(p:Path):
 p=p.resolve()
 if ROOT not in p.parents and p!=ROOT: raise HTTPException(403,'拒绝项目外路径')
 return p
def read(p): return json.loads(safe(p).read_text())
def _session_id(payload:dict) -> str:
 raw=payload.get('session_id')
 if raw in (None,''): return uuid.uuid4().hex[:12]
 try: return validate_session_id(raw)
 except ValueError: raise HTTPException(400,'无效的 session_id')
def _session_output(base:Path,sid:str) -> Path:
 try: directory=ensure_inside(ROOT,base/sid)
 except ValueError: raise HTTPException(400,'无效的 session_id')
 directory.mkdir(parents=True,exist_ok=True); return directory
def video_duration(video:str) -> float:
 try:
  raw=subprocess.check_output([str(PROBE),'-v','error','-show_entries','format=duration','-of','json',str(ROOT/VIDEOS[video]['path'])],text=True,timeout=30)
  return float(json.loads(raw)['format']['duration'])
 except Exception:
  return 0.0
def best_window(items:list[dict],duration:float,video_len:float=0.0) -> tuple[float,float,list[dict]]:
 """Pick one continuous source window that fills the requested duration.

 Previously the LLM job used ``min(start+duration, max(event end)+2)``, so a
 20 s request with events clustered in a 10 s span produced only 10 s.  Here
 the window length always equals the requested duration (clamped to the
 source), while still covering as many strong events as possible.
 """
 if not items: raise ValueError('没有符合条件的事件')
 duration=float(duration)
 if video_len>0: duration=min(duration,video_len)
 duration=max(0.5,duration)
 def score(event:dict) -> float:
  for key in ('confidence','final_ranking_score','raw_model_score','hypecut_score'):
   value=event.get(key)
   if isinstance(value,(int,float)): return float(value)
  return 0.0
 best:tuple[tuple[int,float],float,float,list[dict]]|None=None
 for anchor in items:
  starts=[max(0.0,float(anchor['start_time'])-2.0),
          max(0.0,float(anchor.get('end_time',anchor['start_time']))+2.0-duration)]
  for start in starts:
   if video_len>0: start=min(start,max(0.0,video_len-duration))
   start=max(0.0,start); end=start+duration
   inside=[e for e in items if float(e['start_time'])<end and float(e.get('end_time',e['start_time']))>start]
   key=(len(inside),sum(score(e) for e in inside))
   if best is None or key>best[0]: best=(key,start,end,inside)
 if best is None: raise ValueError('没有符合条件的事件')
 _,start,end,inside=best
 if not inside: inside=items[:1]
 return start,end,inside
def events(video, mode='llm', variant='v1'):
 if mode=='lightweight':
  if variant!='v1':
   from integrations.lightweight_v2 import candidates_for_variant
   return candidates_for_variant(video,variant)
  from integrations.lightweight import events as local_events
  return local_events(video, analyze_if_missing=False)
 if not VISION_CACHE.is_file(): raise HTTPException(503,'缓存视觉事件缺失；请先运行 semantic_vision.py 或使用 Lightweight 模式')
 try: payload=read(VISION_CACHE)
 except Exception: raise HTTPException(503,'缓存视觉事件无法解析；请重新生成')
 items=payload.get('events') if isinstance(payload,dict) else None
 if not isinstance(items,list): raise HTTPException(503,'缓存视觉事件格式无效；请重新生成')
 name=VIDEO_FILES[video]
 return [e|{'source_video_id':video,'source_model':'deepseek-v4.1-flash','evidence_source':'CACHED_VISION'} for e in items if isinstance(e,dict) and Path(e.get('video_path','')).name==name]
@app.get('/api/v1/health')
def health(): return {'status':'ok','modes':['llm','lightweight'],'bind':'127.0.0.1'}
@app.get('/api/v1/capabilities')
def caps(): return {'llm':{'available':VISION_CACHE.is_file(),'cached_vision':VISION_CACHE.is_file(),'live_vision_requires_explicit_action':True,'requires_cache':True},'lightweight':{'available':True,'model':'PyTorchVideo X3D-XS / Kinetics-400','network_required':False,'limitations':'Generic action candidates only; no confirmed makes, steals, rebounds, identity, or possession.'}}
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
def recap(video_id:str,mode:str='llm',variant:str='v1'):
 if video_id not in VIDEOS: raise HTTPException(404,'未知视频')
 if mode not in {'llm','lightweight'}: raise HTTPException(400,'不支持的模式')
 if variant not in {'v1','v2','hypecut'}: raise HTTPException(400,'不支持的候选版本')
 from integrations.lightweight import EVENT_TYPE_ZH
 def score(e):
  for key in ('confidence','final_ranking_score','raw_model_score','hypecut_score'):
   value=e.get(key)
   if isinstance(value,(int,float)): return float(value)
  return 0.0
 version=variant if mode=='lightweight' else None
 try:
  es=events(video_id,mode,variant)
 except HTTPException as exc:
  return {'source_video_id':video_id,'mode':mode,'candidate_version':version,'status':'UNAVAILABLE','summary':str(exc.detail),'events':[]}
 if not es:
  return {'source_video_id':video_id,'mode':mode,'candidate_version':version,'status':'EMPTY','summary':'这段视频还没有可用的分析事件，请先生成高光或运行一次分析。','events':[]}
 ranked=sorted(es,key=score,reverse=True)[:5]
 lines=[]
 for index,event in enumerate(ranked,1):
  name=event.get('display_name') or EVENT_TYPE_ZH.get(event.get('event_type',''),'篮球动作')
  start=float(event.get('start_time',0.0)); end=float(event.get('end_time',start))
  lines.append(f"{index}. {name}（{start:.1f}–{end:.1f} 秒，置信度 {score(event):.2f}）")
 note=('以上均为本地 X3D 通用动作候选，不确认进球、球员或回合归属。' if mode=='lightweight'
       else '以上基于缓存视觉证据，结果需要人工回看确认。')
 summary=f"本视频共识别到 {len(es)} 个候选片段。最值得关注的是：\n"+'\n'.join(lines)
 return {'source_video_id':video_id,'mode':mode,'candidate_version':version,'status':'AVAILABLE',
         'event_count':len(es),'events':ranked,'summary':summary,'note':note,
         'verification_status':'MODEL_PREDICTED'}
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
 vid=payload.get('video_id','cbf'); types=payload.get('event_types',['shot_attempt'])
 try: duration=float(payload.get('target_duration',15))
 except (TypeError,ValueError): raise HTTPException(400,'目标时长无效')
 mode=payload.get('mode','llm')
 variant=payload.get('candidate_version','v1')
 if mode=='lightweight':
  from integrations.lightweight import LightweightSession
  if vid not in VIDEOS: raise HTTPException(404,'未知视频')
  if not 5<=duration<=60 or not isinstance(types,list): raise HTTPException(400,'轻量模式仅支持 5-60 秒和合法事件类型')
  jid='lw-'+uuid.uuid4().hex[:12]
  if variant not in {'v1','v2','hypecut'}: raise HTTPException(400,'不支持的候选版本')
  session=LightweightSession(video_id=vid,session_id=jid,candidate_version=variant); lightweight_sessions[jid]=session
  prompt=('生成投篮高光 ' if ('shot_attempt' in types and variant!='hypecut') else '生成篮球高光 ') + f'{duration}秒'
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
 if vid not in VIDEOS or not 5<=duration<=60 or not isinstance(types,list): raise HTTPException(400,'仅支持 5-60 秒和合法事件类型')
 es=[e for e in events(vid) if e['event_type'] in types]
 if not es: raise HTTPException(422,'没有符合缓存视觉证据的事件')
 jid='job-'+uuid.uuid4().hex[:8]; d=OUT/'web_jobs'/jid; d.mkdir(parents=True)
 jobs[jid]={'id':jid,'status':'queued','initiator':'CONTROLLER','events':es}
 def work():
  try:
   jobs[jid]['status']='running'
   a,b,included=best_window(es,duration,video_duration(vid))
   dest=d/'highlights.mp4'; subprocess.run([str(FF),'-y','-v','error','-ss',str(a),'-to',str(b),'-i',str(ROOT/VIDEOS[vid]['path']),'-map','0:v:0','-map','0:a?','-c:v','libx264','-c:a','aac','-movflags','+faststart',str(dest)],check=True,timeout=600)
   probe=json.loads(subprocess.check_output([str(PROBE),'-v','error','-show_entries','format=duration:stream=codec_type','-of','json',str(dest)],text=True,timeout=30)); plan={'source_video_id':vid,'window_start':a,'window_end':b,'requested_duration':duration,'clips':[{'start':a,'end':b,'event_ids':[e['event_type']+'@'+str(e['start_time']) for e in included]}],'verification_status':'MODEL_PREDICTED'}
   (d/'highlight_plan.json').write_text(json.dumps(plan,indent=2));(d/'trace.json').write_text(json.dumps([{'initiator':'CONTROLLER','tool':'render_highlights'},{'initiator':'CONTROLLER','tool':'verify_render','result':probe}],indent=2));rel=f'outputs/web_jobs/{jid}/highlights.mp4';jobs[jid].update(status='completed',result={'path':rel,'video':'/api/v1/artifact?path='+quote(rel),'duration':probe['format']['duration'],'requested_duration':duration,'plan':plan})
  except Exception as e: jobs[jid].update(status='failed',error=type(e).__name__)
 threading.Thread(target=work,daemon=True).start(); return jobs[jid]
@app.get('/api/v1/jobs/{job_id}')
def job(job_id:str):
 if job_id not in jobs: raise HTTPException(404,'任务不存在')
 return jobs[job_id]
@app.get('/api/v1/jobs/{job_id}/trace')
def trace(job_id:str):
 if job_id not in jobs: raise HTTPException(404,'任务不存在')
 if jobs[job_id].get('mode')=='lightweight':
  path=OUT/'lightweight_agent'/job_id/'tool_trace.json'
  if not path.is_file(): raise HTTPException(404,'轨迹尚未生成')
  return read(path)
 path=OUT/'web_jobs'/job_id/'trace.json'
 if not path.is_file(): raise HTTPException(404,'轨迹尚未生成')
 return read(path)
@app.post('/api/v1/chat')
def chat(payload:dict):
 text=str(payload.get('message','')).strip()
 if not text: raise HTTPException(400,'消息不能为空')
 mode=str(payload.get('mode','llm'))
 video_id=str(payload.get('video_id','cbf'))
 variant=str(payload.get('candidate_version','v1'))
 if video_id not in VIDEOS: raise HTTPException(404,'未知视频')
 if mode=='lightweight':
  sid=_session_id(payload)
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
 sid=_session_id(payload)
 try:
  import motrack_chat_optimized as agent
  if sid not in chat_sessions:
   output_dir=_session_output(OUT/'web_chat',sid)
   chat_sessions[sid]=agent.Run(video_id=video_id, output_dir=output_dir, api_key=key)
  elif chat_sessions[sid].video_id != video_id: raise HTTPException(409,'会话属于另一段视频；切换视频后请创建新会话')
  run=chat_sessions[sid]
  reply=run.turn(text)
  return {'reply':reply or '工具调用已完成。','session_id':sid,'mode':'CACHED_VISION','llm_called':True,'artifacts':f'outputs/web_chat/{sid}','output':run.last_output}
 except HTTPException: raise
 except RuntimeError as exc: raise HTTPException(503,str(exc))
 except ValueError as exc: raise HTTPException(400,str(exc))
 except Exception as exc: raise HTTPException(502,f'Agent 调用失败：{type(exc).__name__}')
@app.post('/api/v1/upload')
async def upload(file:UploadFile=File(...)):
 name=Path(file.filename or 'upload.mp4').name
 suffix=Path(name).suffix.lower()
 if suffix not in {'.mp4','.webm'}: raise HTTPException(415,'仅支持 MP4/WebM')
 if file.content_type not in {'video/mp4','video/webm'}: raise HTTPException(415,'仅支持 MP4/WebM')
 target=ROOT/'inputs/uploads';target.mkdir(parents=True,exist_ok=True);dest=target/name;tmp=target/(name+'.part')
 size=0
 try:
  with tmp.open('wb') as out:
   while True:
    chunk=await file.read(1024*1024)
    if not chunk: break
    size+=len(chunk)
    if size>MAX_UPLOAD_BYTES: raise HTTPException(413,'文件超过 200MB')
    out.write(chunk)
  os.replace(tmp,dest)
 finally:
  tmp.unlink(missing_ok=True)
 return {'status':'stored','path':str(dest.relative_to(ROOT)),'note':'上传已保存；任意上传视频的完整 Agent 分析尚未启用。'}
