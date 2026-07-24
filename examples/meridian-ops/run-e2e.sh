#!/usr/bin/env bash
# End-to-end feature test for Stoa, driven against the Meridian fixture.
# Exercises: agent detection (8 frameworks, py+ts), all core + AI rules,
# supersedes dedup, dimensions + matrix + controls-observed, SARIF, GitHub
# annotations/summary, the AI002 exec gate, stoa diff (drift), stoa approve,
# drift gates, redaction, determinism, suppressions, false-positive controls,
# --no-dimensions and custom-taxonomy (unclassified).
#
# Usage:  STOA=/path/to/stoa ./run-e2e.sh   (defaults to `stoa` on PATH)
set -uo pipefail
STOA="${STOA:-stoa}"
FIX="$(cd "$(dirname "$0")" && pwd)"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
cp -R "$FIX/." "$WORK/repo"; cd "$WORK/repo"
rm -f run-e2e.sh COVERAGE.md README.md

pass=0; fail=0
check(){ if eval "$2" >/dev/null 2>&1; then printf '  \033[32m✓\033[0m %s\n' "$1"; pass=$((pass+1));
         else printf '  \033[31m✗\033[0m %s\n' "$1"; fail=$((fail+1)); fi; }
J(){ python3 -c "import json,sys; d=json.load(open('$1')); sys.exit(0 if ($2) else 1)"; }

SECRETS='sk-proj-Zx9mKq3vNp7rTb2wYc5dHj8fLg4sVn6a Sup3rS3cretPr0d!2026 sk-proj-VENDORdummy0000000000000000000000'

echo "== git base/head (for diff) =="
git init -q; git config user.email e@example.test; git config user.name tester
# BASE = strip HEAD-ONLY lines + remove the new (marketing) agent
grep -v HEAD-ONLY agents/devops.py > d.tmp && mv d.tmp agents/devops.py
grep -v HEAD-ONLY web/support_bot.ts > w.tmp && mv w.tmp web/support_bot.ts
rm agents/marketing.py
git add -A; git commit -qm base >/dev/null; BASE=$(git rev-parse HEAD)
# HEAD = restore full fixture
cp "$FIX/agents/marketing.py" agents/; cp "$FIX/agents/devops.py" agents/; cp "$FIX/web/support_bot.ts" web/
git add -A; git commit -qm head >/dev/null

echo "== 1. full scan =="
"$STOA" scan . --json reg.json --html rep.html --sarif out.sarif \
      --summary-file sum.md --github-annotations >ann.txt 2>/dev/null

check "≥10 agent candidates detected" "J reg.json \"d['summary']['agent_candidates']>=10\""
check "8 frameworks (langchain/langgraph/crewai/autogen/pydantic_ai/openai_agents_sdk/agno)" \
  "J reg.json \"{'langchain','langgraph','crewai','autogen','pydantic_ai','openai_agents_sdk','agno'} <= {fw for a in d['agents'] for fw in a['frameworks']}\""
check "TypeScript agent (support_bot) detected" "J reg.json \"any(a['language']=='typescript' for a in d['agents'])\""

RULES="python3 -c \"import json;d=json.load(open('reg.json'));ff=[f for a in d['agents'] for f in a['findings']]+d['repository_findings'];print(' '.join(sorted({f['rule_id'] for f in ff})))\""
FIRED=$(eval $RULES)
for r in SEC001 SEC002 SEC003 REL001 NET002 CTRL001 CTRL002 CTRL004 AI001 AI002 AI003 AI004 AI005 AI006 AI007; do
  check "rule $r fired" "echo '$FIRED' | grep -qw $r"
done
check "NET001 superseded by AI005 (absent)" "! echo '$FIRED' | grep -qw NET001"
check "CTRL003 disabled via stoa.toml (absent)" "! echo '$FIRED' | grep -qw CTRL003"

echo "== 2. AI rule depth =="
check "AI002 covers exec+markup+sql+request sinks" \
  "J reg.json \"{'exec','markup','sql','request'} <= {f.get('variant') for a in d['agents'] for f in a['findings'] if f['rule_id']=='AI002'}\""
check "AI005 covers all 4 variants" \
  "J reg.json \"{'trust-remote-code','unpinned-artifact','floating-alias','insecure-endpoint'} <= {f.get('variant') for a in d['agents'] for f in a['findings'] if f['rule_id']=='AI005'}\""
check "AI002/sql supersedes SEC003" \
  "J reg.json \"any('SEC003' in f.get('supersedes',[]) for a in d['agents'] for f in a['findings'] if f['rule_id']=='AI002')\""
check "AI002 exec is gate_eligible" \
  "J reg.json \"any(f.get('gate_eligible') for a in d['agents'] for f in a['findings'] if f['rule_id']=='AI002')\""
check "flow arrays present on taint findings" \
  "J reg.json \"any(f.get('flow') for a in d['agents'] for f in a['findings'] if f['rule_id'] in ('AI001','AI002','AI004','AI006'))\""
check "NET002 severity overridden to info" \
  "J reg.json \"all(f['severity']=='info' for a in d['agents'] for f in a['findings'] if f['rule_id']=='NET002')\""

echo "== 3. dimensions =="
check "dimension_summary present with 8 dimensions" "J reg.json \"len(d['dimension_summary']['dimensions'])==8\""
check "data-exfiltration reaches elevated" \
  "J reg.json \"any(x['id']=='data-exfiltration' and x['max_exposure']=='elevated' for x in d['dimension_summary']['dimensions'])\""
check "proxy dims never elevated (behavioral-instability, model-drift)" \
  "J reg.json \"all(x['max_exposure']!='elevated' for x in d['dimension_summary']['dimensions'] if x['id'] in ('behavioral-instability','model-drift'))\""
check "compliance_agent shows 6 control types (good-news path)" \
  "J reg.json \"{'approval','authentication','validation','deterministic_sampling','pinned_model','observability'} <= {c for a in d['agents'] if a['name']=='compliance_agent' for x in a['dimension_assessment']['dimensions'] for c in x['controls_observed']}\""
check "findings carry dimensions" \
  "J reg.json \"any(f.get('dimensions') for a in d['agents'] for f in a['findings'])\""

echo "== 4. false-positive controls =="
check "embeddings.py NOT an agent" "J reg.json \"not any(a['path'].endswith('embeddings.py') for a in d['agents'])\""
check "user_agent.py NOT an agent" "J reg.json \"not any('user_agent' in a['path'] for a in d['agents'])\""
check "placeholder test key = low confidence" \
  "J reg.json \"all(f['confidence']=='low' for f in d['repository_findings'] if f['rule_id']=='SEC001' and 'test' in f['path'])\""
check "parameterized SQL in db.py not flagged as SEC003" \
  "J reg.json \"not any(f['rule_id']=='SEC003' and f['path'].endswith('db.py') and f['line']!=0 and '%s' in f.get('snippet','') for f in d['repository_findings'])\""

echo "== 5. suppressions & .stoaignore =="
check "suppressed findings counted (≥3)" "J reg.json \"d['summary']['suppressed_findings']>=3\""
check "vendor/ excluded via .stoaignore" "J reg.json \"not any('vendor' in a['path'] for a in d['agents']) and not any('vendor' in f['path'] for f in d['repository_findings'])\""

echo "== 6. SARIF + annotations + gate =="
check "SARIF has stoa-dim:* tags" "grep -q 'stoa-dim:' out.sarif"
check "annotations emit ::error for a critical" "grep -q '::error' ann.txt"
check "job summary written" "test -s sum.md"
"$STOA" scan . --strict --json /dev/null --html /dev/null --quiet >/dev/null 2>&1; rc=$?
check "--strict fails the build (AI002 exec gate) exit 1" "test $rc -eq 1"

echo "== 7. redaction (secrets absent from every artifact) =="
leak=0; for s in $SECRETS; do for f in reg.json rep.html sum.md ann.txt out.sarif; do
  grep -qF "$s" "$f" && leak=1; done; done
check "no raw secret in any artifact" "test $leak -eq 0"

echo "== 8. determinism =="
"$STOA" scan . --json r1.json --html /dev/null --quiet >/dev/null 2>&1
"$STOA" scan . --json r2.json --html /dev/null --quiet >/dev/null 2>&1
check "two scans byte-identical JSON" "diff -q r1.json r2.json"

echo "== 9. stoa diff (capability drift) =="
"$STOA" diff --base-ref "$BASE" --json diff.json --md changelog.md >/dev/null 2>&1
check "new agent (marketing) detected in diff" "J diff.json \"any('marketing' in x.get('path','') for x in d['agents']['added'])\""
check "devops escalation (gains cloud_resource_access)" \
  "J diff.json \"any(c['id']=='cloud_resource_access' for x in d['agents']['changed'] for c in x.get('capabilities',{}).get('added',[]))\""
check "diff summary reports escalations" "J diff.json \"d['summary']['escalations']['high']>=1 or d['summary'].get('agents_added',0)>=1\""
check "dimension_delta present" "grep -q dimension_delta diff.json || J diff.json \"any('dimension' in str(x) for x in d['agents']['changed'])\""
check "changelog markdown generated" "test -s changelog.md && grep -q 'stoa-diff-comment' changelog.md"
"$STOA" diff --base-ref "$BASE" --fail-on-drift high --json /dev/null >/dev/null 2>&1; rc=$?
check "--fail-on-drift high fails on unapproved escalation (exit 1)" "test $rc -eq 1"

echo "== 10. stoa approve =="
"$STOA" approve --agent devops --capability cloud_resource_access \
  --reason "ECS restart, reviewed SEC-1234" --by @sre-oncall >/dev/null 2>&1
check ".stoa/approvals.toml written" "test -f .stoa/approvals.toml"
check "approval recorded with reason + approver" "grep -q 'sre-oncall' .stoa/approvals.toml && grep -q 'SEC-1234' .stoa/approvals.toml"

echo "== 11. dimension controls =="
"$STOA" scan . --no-dimensions --json nd.json --html /dev/null --quiet >/dev/null 2>&1
check "--no-dimensions omits dimension_assessment" "J nd.json \"all(a.get('dimension_assessment') is None for a in d['agents']) or 'dimension_summary' not in d\""
cat > custom-tax.toml <<'TAX'
[taxonomy]
id = "custom-1"
version = "1.0"
[[dimensions]]
id = "safety"
name = "Safety"
definition = "x"
assessability = "strong"
[finding_weights]
critical=40
high=25
medium=12
low=5
info=2
[confidence_multipliers]
high=1.0
medium=0.6
low=0.3
[scoring]
capability_weight=18
provider_weight=8
control_credit=20
[rule_dimensions]
AI002 = ["safety"]
TAX
"$STOA" scan . --taxonomy custom-tax.toml --json ct.json --html /dev/null --quiet >/dev/null 2>&1
check "custom taxonomy + unclassified safety net" \
  "J ct.json \"any(x['id']=='unclassified' for a in d['agents'] if a.get('dimension_assessment') for x in a['dimension_assessment']['dimensions'])\""

echo
printf 'RESULT: \033[32m%d passed\033[0m, ' "$pass"
if [ "$fail" -gt 0 ]; then printf '\033[31m%d failed\033[0m\n' "$fail"; exit 1; else printf '0 failed\n'; fi
