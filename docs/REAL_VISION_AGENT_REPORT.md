# Real vision Agent repair

## Confirmed root cause

The historic live `tool_trace.json` proves frame extraction occurred, but it also proves only local paths and text were returned. The live FunctionLoop serialized those results as tool-message JSON; no `image_url` or `input_image` block was sent. Therefore the former live model did **not** see images, and its UNVERIFIED result was correct.

## Repair

`semantic_vision.py` loads five consecutive JPEGs per test, holds their timestamps, downscales oversized images in memory to at most 768px, base64-encodes the transmitted bytes, and sends genuine Chat Completions `image_url` data URLs. Its audit deliberately records only file name, source/sent SHA-256, sent dimensions/bytes, timestamp, model, request ID and token usage—never key or base64.

Run:

```bash
cd /home/ht/motrack/tiqu1
./run_semantic_vision.sh
```

It hides the single API-key entry and writes outputs to `outputs/semantic_vision_live/`. HTTP is the explicitly configured internal HTADC endpoint; HTTPS previously failed certificate-host validation, so use only on the approved internal network.

## Actual live result

PASS: two real HTADC Chat Completions requests completed with `deepseek-v4.1-flash`. The audit records two request IDs and five real `image_url` blocks per request; model descriptions cite visual features at the corresponding frame times, so this is evidence that the proxy accepted rather than silently discarded images.

- Doug 8–16s: `shot_attempt`, 9–12s, confidence 0.38. The model describes a red player near the basket and contested action, but explicitly says release/result are unclear.
- ČBF 75–83s: two `shot_attempt` predictions: 77s (0.65, player rises near rim with ball) and 81–83s (0.58, ball above head shooting motion). It does **not** claim made/missed basket, player, team, score, steal, rebound, pass or fast break.

All three are `MODEL_PREDICTED`, never human-verified. Event files, combined event index, and a complete redacted request audit are in `outputs/semantic_vision_live/`.

Usage returned by the proxy: 12,262 tokens (Doug) and 16,244 (ČBF), total **28,506**; completion/reasoning tokens dominate. The proxy returned no price/rate data, so actual dollar cost cannot be truthfully calculated from the available records. This is two model requests (under the 10-request cap); future runs should lower output/reasoning allocation because this usage is high relative to the $0.10 target.

The script was syntax-tested and its image blocks are downscaled to at most 768px before transmission. Existing results remain untouched.
