#!/usr/bin/env bash
# Build the dashboard UI once and place the compiled single-file template
# where the Python package ships it. Needs Node (see ui/.nvmrc) and pnpm.
# Users of the published wheel never run this: the release workflow does.
set -euo pipefail
cd "$(dirname "$0")/.."
pnpm --dir ui install --frozen-lockfile
pnpm --dir ui build
cp ui/dist/index.html src/stoa/templates/dashboard.html
python3 - <<'PY'
from pathlib import Path
path = Path("src/stoa/templates/dashboard.html")
size = path.stat().st_size
budget = 1_500_000
print(f"dashboard template: {size:,} bytes ({size / 1024:.0f} KB), budget {budget:,}")
if size > budget:
    raise SystemExit("dashboard template exceeds the 1.5 MB budget")
PY
