#!/usr/bin/env bash
# Build the opt-in Market release in the checkout supplied by the release operator.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
python="$root/services/quant-api/.venv/bin/python"
case "${1:-}" in
    "") ;;
    --data-only)
        [[ "$#" == 1 ]]
        PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$root/services/quant-api" python3 - "$root" <<'PYCODE'
from pathlib import Path
import sys

from app.market_release_identity import MARKET_TAG_PREFIX
from app.market_version import MARKET_RELEASE_VERSION
from app.runtime_bindings import _git, read_bindings, verify_release

root = Path(sys.argv[1])
tag = MARKET_TAG_PREFIX + MARKET_RELEASE_VERSION
if root.name != "release-" + tag.replace("/", "-"):
    raise SystemExit("MARKET_BUILD_RELEASE_DIRECTORY_REQUIRED")
verify_release(root, tag, _git(root, "rev-parse", "HEAD"))
registry = read_bindings()
if registry and any(Path(binding.root) == root for binding in registry.services.values()):
    raise SystemExit("MARKET_BUILD_ACTIVE_RELEASE")
print(tag)
PYCODE
        UV_PROJECT_ENVIRONMENT="$root/services/quant-api/.venv" uv sync --locked --project "$root/services/quant-api"
        ;;
    *) exit 64 ;;
esac
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
if [[ "${1:-}" != --data-only ]]; then
    VITE_GUIYI_MARKET_FOUNDATION=1 pnpm --dir "$root/apps/quant-web" run build
fi
