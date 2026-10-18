# One command: scan the bot, run five traced sessions, verify the chain, reconcile tools.
PY ?= python
STOA ?= stoa

demo:
	"$(STOA)" scan . --no-dashboard --json stoa-registry.json --quiet || true
	"$(PY)" demo.py
	"$(STOA)" runtime verify stoa-traces --key hmac:demo-only-key
	"$(STOA)" runtime reconcile stoa-traces --registry stoa-registry.json
	"$(STOA)" runtime merge stoa-traces --registry stoa-registry.json --out stoa-registry-enriched.json
	@"$(PY)" -c "import json; r=json.load(open('stoa-registry-enriched.json')); print('RT findings:', r['runtime']['rt_findings']); [print(' ', f['rule_id'], f['title']) for a in r['agents'] for f in a['findings'] if f['rule_id'].startswith('RT')]"

clean:
	rm -rf stoa-traces stoa-registry.json stoa-registry-enriched.json

.PHONY: demo clean
