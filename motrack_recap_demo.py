#!/usr/bin/env python3
import argparse,json
from integrations.recap_agent import RecapAgent
p=argparse.ArgumentParser();p.add_argument('query',nargs='?',default='analyze most exciting possession');p.add_argument('--build-review',action='store_true');a=p.parse_args();r=RecapAgent();
if a.build_review: print(json.dumps(r.review_artifacts(),ensure_ascii=False,indent=2))
elif '最精彩' in a.query or 'key' in a.query: print(json.dumps(r.analyze_key_possession(r.build_event_chains()[0]),ensure_ascii=False,indent=2))
else: print(json.dumps(r.search_events(a.query),ensure_ascii=False,indent=2))
