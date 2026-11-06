# HTADC live E2E status

No live model request was made: `MOTRACK_API_KEY` was absent in the execution environment. HTTPS validation failed because the presented certificate does not match `sub2api.adc-ingress.aeroht.net`; the provided HTTP endpoint answered 401 without credentials. HTTP therefore carries plaintext transport risk and must only be used on the approved internal network.

Implemented: `HTADCModel` uses the provided OpenAI-compatible proxy, `deepseek-v4.1-flash` by default (override with `MOTRACK_API_MODEL`), Chat Completions function calling, 700 output-token cap, 12-call runtime cap, usage capture, and the existing sandboxed LocalTools. Start with `./run_htadc_agent.sh inputs/cbf_3x3_tour.mp4`; it reads the key with hidden input if `MOTRACK_API_KEY` is unset.

Live acceptance remains NOT TESTED: model availability, tool calls, image understanding, token usage and cost cannot be claimed without a key. Mock MP4 workflow remains separate and verified.
