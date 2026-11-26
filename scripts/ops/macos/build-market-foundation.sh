#!/usr/bin/env bash
# Build the opt-in Market release in the checkout supplied by the release operator.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
python="$root/services/quant-api/.venv/bin/python"
[[ -x "$python" && -f "$root/services/quant-api/uv.lock" ]]
# EventEngine needs no GUI or VeighNa trading plugins. Lock the official pure
# Python wheel independently so uv does not install the desktop dependency tree.
uv pip install --python "$python" --no-deps --only-binary :all: --require-hashes -r - <<'REQ'
vnpy==4.4.0 --hash=sha256:e496e63a6b6954c2313396ace3a5ffac9d86b354c0da5900dcbcd8bef60dae06
REQ
"$python" - <<'PY'
from importlib.metadata import version
from vnpy.event import Event, EventEngine

if version("vnpy") != "4.4.0" or version("rqdatac") != "3.5.6.1":
    raise SystemExit("MARKET_BUILD_DEPENDENCY_UNPROVEN")
engine = EventEngine()
engine.put(Event("guiyi-market-build-smoke"))
PY
VITE_GUIYI_MARKET_FOUNDATION=1 pnpm --dir "$root/apps/quant-web" run build
