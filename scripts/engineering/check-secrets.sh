#!/usr/bin/env bash
# Secret scan — never prints secret values; only path + pattern family.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
cd "$REPO_ROOT"

STRICT=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --strict) STRICT=true; shift ;;
    -h|--help)
      echo "Usage: scripts/engineering/check-secrets.sh [--strict]"
      exit 0
      ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

python3 - "$REPO_ROOT" "$STRICT" <<'PY'
from __future__ import annotations

import re
import sys
from pathlib import Path

repo = Path(sys.argv[1]).resolve()
strict = sys.argv[2] == "true"

# Detect assignment-like secrets without echoing the value.
PATTERN = re.compile(
    r"(?i)(DATABASE_URL|QYWX_WEBHOOK|api[_-]?key|access[_-]?token|password|secret|webhook)\s*[:=]\s*\S+"
)

# Only scan text-ish tracked-ish trees; skip large/binary dirs.
SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "data", "dist", "build",
    "__pycache__", ".ai", ".workbuddy",
}
SKIP_SUFFIX = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".parquet", ".pyc", ".lock"}

hits: list[str] = []
scanned = 0
for path in repo.rglob("*"):
    if not path.is_file():
        continue
    if any(part in SKIP_DIRS for part in path.parts):
        continue
    if path.suffix.lower() in SKIP_SUFFIX:
        continue
    if path.stat().st_size > 1_000_000:
        continue
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        continue
    scanned += 1
    for i, line in enumerate(text.splitlines(), 1):
        if not PATTERN.search(line):
            continue
        # Skip obvious placeholders / docs examples
        lower = line.lower()
        if "replace-with-" in lower or "example" in lower or "redacted" in lower:
            continue
        if "os.getenv" in lower or "environ" in lower:
            continue
        # Report family only — never the value
        m = PATTERN.search(line)
        family = m.group(1) if m else "secret"
        rel = path.relative_to(repo)
        hits.append(f"{rel}:{i}: family={family}")

print(f"[OK] scanned_files={scanned}")
if hits:
    print(f"[FAIL] potential_secret_assignments={len(hits)} (values not printed)")
    for h in hits[:30]:
        print(f"  {h}")
    if len(hits) > 30:
        print(f"  ... and {len(hits) - 30} more")
    sys.exit(1 if strict else 0)

print("[OK] no high-confidence secret assignments found")
sys.exit(0)
PY
