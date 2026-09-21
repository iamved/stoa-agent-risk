#!/usr/bin/env bash
# Regenerate the hosted demo (site/dashboard/index.html) from the Meridian Pay
# fixture, through the same `stoa dashboard` command a customer runs. Run
# scripts/build_dashboard.sh first when the UI changed, and
# ui/fixtures/build.py when the scanner changed. tests/test_dashboard_fixtures.py
# fails when the committed page no longer matches the fixture.
set -euo pipefail
cd "$(dirname "$0")/.."
STOA="${STOA_BIN:-stoa}"
"$STOA" dashboard ui/fixtures/meridian-pay.envelope.json --demo --out site/dashboard/index.html
