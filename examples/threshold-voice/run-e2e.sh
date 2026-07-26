#!/usr/bin/env bash
# Focused regression check for the Threshold fixture -- confirms every
# deliberately planted finding, both MCP client/server gaps, the DECL001 and
# DECL003 contradictions, and the DECL004 scan-blindness demonstration still
# hold as Stoa evolves. Not a full feature-surface test (see meridian-ops
# for that).
#
# Usage: STOA=/path/to/stoa ./run-e2e.sh   (defaults to `stoa` on PATH)
set -uo pipefail
STOA="${STOA:-stoa}"
FIX="$(cd "$(dirname "$0")" && pwd)"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
cp -R "$FIX/." "$WORK/repo"; cd "$WORK/repo"
rm -f run-e2e.sh README.md

pass=0; fail=0
check(){ if eval "$2" >/dev/null 2>&1; then printf '  \033[32m✓\033[0m %s\n' "$1"; pass=$((pass+1));
         else printf '  \033[31m✗\033[0m %s\n' "$1"; fail=$((fail+1)); fi; }
J(){ python3 -c "import json,sys; d=json.load(open('$1')); sys.exit(0 if ($2) else 1)"; }

echo "== scan =="
"$STOA" scan . --no-git --json reg.json --html rep.html >/dev/null 2>&1

check "11 agent candidates detected" "J reg.json \"d['summary']['agent_candidates']==11\""
check "multi-agent, multi-framework (langchain/langgraph/crewai/mcp)" \
  "J reg.json \"{'langchain','langgraph','crewai','mcp'} <= {fw for a in d['agents'] for fw in a['frameworks']}\""
check "TypeScript file scanned (widget_client.ts)" "J reg.json \"any(a['language']=='typescript' for a in d['agents'])\""

echo "== dimension coverage (one finding per registry dimension) =="
RULES="python3 -c \"import json;d=json.load(open('reg.json'));ff=[f for a in d['agents'] for f in a['findings']]+d['repository_findings'];print(' '.join(sorted({f['rule_id'] for f in ff})))\""
FIRED=$(eval $RULES)
for r in AI001 AI002 AI003 AI005 AI006 AI007 CTRL005 CTRL007; do
  check "rule $r fired" "echo '$FIRED' | grep -qw $r"
done

echo "== MCP client/server gaps =="
check "intake_tools.py detected as MCP server (framework=mcp)" \
  "J reg.json \"any('mcp' in a['frameworks'] for a in d['agents'] if a['path']=='mcp/intake_tools.py')\""
check "widget_client.ts (a pure MCP CLIENT) is ALSO classified framework=mcp -- the misclassification gap" \
  "J reg.json \"any('mcp' in a['frameworks'] for a in d['agents'] if a['path']=='web/widget_client.ts')\""
check "calendar_client.py (pure MCP client, no other agentic signal) is invisible -- never an agent" \
  "J reg.json \"not any(a['path']=='integrations/calendar_client.py' for a in d['agents'])\""

echo "== autonomy ladder =="
check "escalation_agent (decision_agent) inferred unrestricted_autonomous" \
  "J reg.json \"any(a['autonomy_level']['level']=='unrestricted_autonomous' for a in d['agents'] if a['id']=='10f550b50eee')\""
check "consent_manager inferred recommend_only (the clean baseline)" \
  "J reg.json \"any(a['autonomy_level']['level']=='recommend_only' for a in d['agents'] if a['id']=='1637c00f9757')\""
check "incentive_agent inferred bounded_autonomous (a real cap, no approval)" \
  "J reg.json \"any(a['autonomy_level']['level']=='bounded_autonomous' for a in d['agents'] if a['id']=='e5c88969570b')\""

echo "== contradiction detector =="
check "DECL001 fires for escalation_agent (declared human_approved, inferred unrestricted)" \
  "J reg.json \"any(f['rule_id']=='DECL001' for a in d['agents'] for f in a['findings'])\""
check "DECL001 carries both code evidence and declared_ref" \
  "J reg.json \"(lambda f: f['path'] and f['declared_ref']['key'])(next(f for a in d['agents'] for f in a['findings'] if f['rule_id']=='DECL001'))\""
check "consent_manager (agent) has zero DECL contradictions -- the good-citizen baseline" \
  "J reg.json \"not any(f['rule_id'].startswith('DECL') for a in d['agents'] if a['id']=='1637c00f9757' for f in a['findings'])\""
check "conversation_agent declares data_classes=[personal] with no DECL004 -- the scan-blindness gap" \
  "J reg.json \"not any(f['rule_id']=='DECL004' for a in d['agents'] if a['id']=='b9ae54475608' for f in a['findings'])\""
check "incentive_agent has move_funds permission, no declared economic_authority -- DECL003" \
  "J reg.json \"any(f['rule_id']=='DECL003' for a in d['agents'] if a['id']=='e5c88969570b' for f in a['findings'])\""
check "Contradictions section present in HTML report" "grep -q 'id=\"contradictions\"' rep.html"

echo "== assurance export =="
"$STOA" export --assurance reg.json --format md --out packet.md >/dev/null 2>&1
check "assurance packet exported with all 14 areas" "[ \$(grep -c '^### Area ' packet.md) -eq 14 ]"
check "assurance packet lists DECL001 in Contradictions" "grep -q DECL001 packet.md"
"$STOA" export --assurance reg.json --format json --out packet.json >/dev/null 2>&1
check "Economic authority area is genuinely populated (not empty)" \
  "J packet.json \"bool(d['areas']['economic_authority']['agents'])\""

echo
printf 'RESULT: \033[32m%d passed\033[0m, ' "$pass"
if [ "$fail" -gt 0 ]; then printf '\033[31m%d failed\033[0m\n' "$fail"; exit 1; else printf '0 failed\n'; fi
