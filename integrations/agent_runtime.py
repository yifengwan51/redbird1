"""Safe, provider-neutral function-calling runtime and local MoTrack tools."""
from __future__ import annotations
import json, subprocess, uuid
from pathlib import Path
from typing import Any

from .motrack_agent import AgentState

TOOL_SCHEMAS = [
 {"type":"function","function":{"name":"list_candidates","parameters":{"type":"object","properties":{},"additionalProperties":False}}},
 {"type":"function","function":{"name":"get_candidate_detail","parameters":{"type":"object","properties":{"candidate_id":{"type":"string"}},"required":["candidate_id"],"additionalProperties":False}}},
 {"type":"function","function":{"name":"get_video_info","parameters":{"type":"object","properties":{},"additionalProperties":False}}},
 {"type":"function","function":{"name":"get_evidence_frames","parameters":{"type":"object","properties":{"candidate_id":{"type":"string"}},"required":["candidate_id"],"additionalProperties":False}}},
 {"type":"function","function":{"name":"create_highlight_plan","parameters":{"type":"object","properties":{"clips":{"type":"array","items":{"type":"object","properties":{"candidate_id":{"type":"string"},"start":{"type":"number"},"end":{"type":"number"}},"required":["candidate_id","start","end"]}}},"required":["clips"],"additionalProperties":False}}},
 {"type":"function","function":{"name":"render_highlights","parameters":{"type":"object","properties":{"plan_id":{"type":"string"}},"required":["plan_id"],"additionalProperties":False}}},
 {"type":"function","function":{"name":"verify_render","parameters":{"type":"object","properties":{"output_path":{"type":"string"}},"required":["output_path"],"additionalProperties":False}}},
 {"type":"function","function":{"name":"generate_recap","parameters":{"type":"object","properties":{"plan_id":{"type":"string"}},"required":["plan_id"],"additionalProperties":False}}},
]

class LocalTools:
 def __init__(self, root: Path, video: Path, candidates: Path, out: Path):
  self.root,self.video,self.out=root.resolve(),video.resolve(),out.resolve(); self.out.mkdir(parents=True,exist_ok=True)
  self.data=json.loads(candidates.read_text()); self.duration=float(self.data["source_duration"]); self.plans={}
 def _candidate(self,cid):
  if not cid.startswith("candidate-"): raise ValueError("invalid candidate_id")
  i=int(cid.split("-",1)[1])-1
  if i<0 or i>=len(self.data["segments"]): raise ValueError("candidate not found")
  return self.data["segments"][i]
 def list_candidates(self):
  return [{"candidate_id":f"candidate-{i+1}","start":x["start"],"end":x["end"],"score":x["score"],"reasons":x.get("reasons",{})} for i,x in enumerate(self.data["segments"])]
 def get_candidate_detail(self,candidate_id): return {"candidate_id":candidate_id,**self._candidate(candidate_id),"source":"hypecut"}
 def get_video_info(self):
  probe=self.root/"tools/ffmpeg/bin/ffprobe"; raw=subprocess.check_output([str(probe),"-v","error","-show_entries","format=duration:stream=codec_type,codec_name,r_frame_rate","-of","json",str(self.video)])
  return json.loads(raw)
 def get_evidence_frames(self,candidate_id):
  c=self._candidate(candidate_id); p=self.out/f"{candidate_id}_evidence.jpg"; ff=self.root/"tools/ffmpeg/bin/ffmpeg"
  subprocess.run([str(ff),"-y","-v","error","-ss",str((c["start"]+c["end"])/2),"-i",str(self.video),"-frames:v","1",str(p)],check=True)
  return {"candidate_id":candidate_id,"frame":str(p.relative_to(self.root)),"timestamp":round((c["start"]+c["end"])/2,3),"note":"Frame is evidence of imagery only; event type remains UNVERIFIED."}
 def create_highlight_plan(self,clips):
  if not clips: raise ValueError("clips cannot be empty")
  selected=[]
  for x in clips:
   c=self._candidate(x["candidate_id"]); a,b=float(x["start"]),float(x["end"])
   if not (0<=a<b<=self.duration): raise ValueError("clip outside video")
   selected.append({"candidate_id":x["candidate_id"],"start":a,"end":b,"score":c["score"],"reasons":c.get("reasons",{}),"event_type":"UNVERIFIED"})
  selected.sort(key=lambda x:x["start"])
  if any(a["end"]>b["start"] for a,b in zip(selected,selected[1:])): raise ValueError("overlapping clips")
  pid="plan-"+uuid.uuid4().hex[:8]; self.plans[pid]=selected
  path=self.out/f"{pid}.json"; path.write_text(json.dumps({"source":str(self.video),"segments":selected},indent=2))
  return {"plan_id":pid,"path":str(path.relative_to(self.root)),"clips":len(selected)}
 def render_highlights(self,plan_id):
  clips=self.plans[plan_id]; ff=self.root/"tools/ffmpeg/bin/ffmpeg"; output=self.out/f"{plan_id}.mp4"; parts=[]
  for i,c in enumerate(clips):
   q=self.out/f"{plan_id}_{i}.mp4"; subprocess.run([str(ff),"-y","-v","error","-ss",str(c["start"]),"-to",str(c["end"]),"-i",str(self.video),"-c","copy",str(q)],check=True); parts.append(q)
  listing=self.out/f"{plan_id}.concat.txt"; listing.write_text("".join(f"file '{p.name}'\n" for p in parts))
  subprocess.run([str(ff),"-y","-v","error","-f","concat","-safe","0","-i",str(listing),"-c","copy",str(output)],check=True)
  return {"plan_id":plan_id,"output_path":str(output.relative_to(self.root)),"status":"rendered"}
 def verify_render(self,output_path):
  p=(self.root/output_path).resolve()
  if self.root not in p.parents or not p.is_file(): raise ValueError("unapproved output path")
  raw=subprocess.check_output([str(self.root/"tools/ffmpeg/bin/ffprobe"),"-v","error","-show_entries","format=duration:stream=codec_type,codec_name","-of","json",str(p)])
  x=json.loads(raw); kinds={s.get("codec_type") for s in x.get("streams",[])}
  return {"output_path":output_path,"duration":float(x["format"]["duration"]),"has_video":"video" in kinds,"has_audio":"audio" in kinds,"status":"verified"}
 def generate_recap(self,plan_id):
  events=[{"clip":i+1,"start":c["start"],"end":c["end"],"candidate_score":c["score"],"trigger_signals":c["reasons"],"event_type":"UNVERIFIED","evidence":"HypeCut signal evidence only; no semantic model or human verification.","recap":"Selected for candidate score; basketball action outcome is unverified.","verification_status":"UNVERIFIED"} for i,c in enumerate(self.plans[plan_id])]
  p=self.out/f"{plan_id}_recap.json"; p.write_text(json.dumps({"events":events},indent=2)); return {"path":str(p.relative_to(self.root)),"events":len(events)}

class FunctionLoop:
 def __init__(self,model,tools:LocalTools,max_calls=16): self.model,self.tools,self.max_calls=model,tools,max_calls; self.trace=[]
 def run(self,user):
  messages=[{"role":"user","content":user}]; seen=set()
  for _ in range(self.max_calls):
   msg=self.model.complete(messages,tools=TOOL_SCHEMAS); messages.append(msg); calls=msg.get("tool_calls",[])
   if not calls: return {"final":msg.get("content",""),"trace":self.trace}
   for call in calls:
    name=call.get("function",{}).get("name"); raw=call.get("function",{}).get("arguments","{}")
    try: args=json.loads(raw); key=(name,json.dumps(args,sort_keys=True));
    except Exception: args=None; key=(name,raw)
    if key in seen: result={"error":"duplicate tool call"}
    else:
     seen.add(key)
     try: result=getattr(self.tools,name)(**args) if name in {x["function"]["name"] for x in TOOL_SCHEMAS} and isinstance(args,dict) else {"error":"invalid tool or parameters"}
     except Exception as e: result={"error":type(e).__name__,"message":str(e)}
    self.trace.append({"tool_call_id":call.get("id"),"tool":name,"arguments":args,"result":result})
    messages.append({"role":"tool","tool_call_id":call.get("id"),"content":json.dumps(result)})
  return {"final":"stopped: maximum tool calls reached","trace":self.trace}

class MockModel:
 def __init__(self): self.n=0
 def complete(self,messages,tools):
  self.n+=1; ids=lambda name,args:{"id":f"mock-{self.n}-{name}","type":"function","function":{"name":name,"arguments":json.dumps(args)}}
  if self.n==1:return {"role":"assistant","tool_calls":[ids("list_candidates",{}),ids("get_video_info",{})]}
  if self.n==2:return {"role":"assistant","tool_calls":[ids("create_highlight_plan",{"clips":[{"candidate_id":"candidate-3","start":74.0,"end":83.0},{"candidate_id":"candidate-5","start":110.0,"end":117.0},{"candidate_id":"candidate-6","start":146.0,"end":153.0}]})]}
  if self.n==3:return {"role":"assistant","tool_calls":[ids("render_highlights",{"plan_id":json.loads(messages[-1]["content"])["plan_id"]})]}
  if self.n==4:
   rendered=json.loads(messages[-1]["content"])
   return {"role":"assistant","tool_calls":[ids("verify_render",{"output_path":rendered["output_path"]}),ids("generate_recap",{"plan_id":rendered["plan_id"]})]}
  return {"role":"assistant","content":"Mock workflow complete; all events are UNVERIFIED."}

class HTADCModel:
 """OpenAI-compatible Chat Completions adapter for the approved HTADC proxy."""
 def __init__(self, api_key, base_url="http://sub2api.adc-ingress.aeroht.net/v1", model="deepseek-v4.1-flash"):
  from openai import OpenAI
  self.client=OpenAI(api_key=api_key,base_url=base_url,timeout=45,max_retries=0); self.model=model; self.usage=[]
 def complete(self,messages,tools):
  r=self.client.chat.completions.create(model=self.model,messages=messages,tools=tools,tool_choice="auto",max_tokens=700,temperature=0.1)
  m=r.choices[0].message; u=r.usage
  self.usage.append({"model":self.model,"prompt_tokens":getattr(u,"prompt_tokens",None),"completion_tokens":getattr(u,"completion_tokens",None),"total_tokens":getattr(u,"total_tokens",None)})
  calls=[]
  for c in m.tool_calls or []: calls.append({"id":c.id,"type":"function","function":{"name":c.function.name,"arguments":c.function.arguments}})
  return {"role":"assistant","content":m.content or "","tool_calls":calls}
