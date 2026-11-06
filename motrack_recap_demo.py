#!/usr/bin/env python3
import argparse
import json

from integrations.recap_agent import RecapAgent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("query", nargs="?", default="analyze most exciting possession")
    parser.add_argument("--build-review", action="store_true")
    args = parser.parse_args()
    agent = RecapAgent()
    if args.build_review:
        print(json.dumps(agent.review_artifacts(), ensure_ascii=False, indent=2))
    elif "最精彩" in args.query or "key" in args.query:
        chains = agent.build_event_chains()
        if not chains:
            print(json.dumps({"status": "NO_EVENTS"}, ensure_ascii=False))
            return 0
        print(json.dumps(agent.analyze_key_possession(chains[0]), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(agent.search_events(args.query), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
