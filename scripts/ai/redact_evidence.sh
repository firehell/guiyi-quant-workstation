#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="$SCRIPT_DIR/lib${PYTHONPATH:+:$PYTHONPATH}"

usage() {
  echo "Usage: scripts/ai/redact_evidence.sh <mode> [options]"
  echo ""
  echo "Modes:"
  echo "  --file <path>       Redact a single file"
  echo "  --dir <path>        Redact all files in a directory (recursive)"
  echo "  --check <path>      Check only; report sensitive items, no modification"
  echo "  --pg-evidence <file>  Generate PG query evidence summary from SQL file"
  echo ""
  echo "Options:"
  echo "  -n, --dry-run       Preview without modifying files"
  echo "  --pattern <name>    Extra pattern group to load (reserved)"
  echo "  -h, --help          Show this help"
  exit 0
}

MODE=""
TARGET=""
DRY_RUN="false"
PATTERN_GROUP=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --file|--dir|--check|--pg-evidence)
      MODE="${1#--}"
      TARGET="${2:-}"; shift 2
      ;;
    -n|--dry-run) DRY_RUN="true"; shift ;;
    --pattern) PATTERN_GROUP="${2:-}"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

[[ -n "$MODE" ]] || { echo "Mode required: --file, --dir, --check, or --pg-evidence" >&2; exit 2; }
[[ -n "$TARGET" ]] || { echo "Target path required" >&2; exit 2; }
[[ -e "$TARGET" ]] || { echo "Target not found: $TARGET" >&2; exit 4; }

case "$MODE" in
  file|check)
    dry_flag="False"
    [[ "$DRY_RUN" == "true" || "$MODE" == "check" ]] && dry_flag="True"
    python3 - "$TARGET" "$dry_flag" "$MODE" <<'PY'
import json, sys
from pathlib import Path
from result_bundler import redact_file, RedactionPatterns

target = Path(sys.argv[1])
dry_run = sys.argv[2] == "True"
mode = sys.argv[3]

if not target.is_file():
    print(json.dumps({"error": "not a file", "path": str(target)}))
    sys.exit(4)

if mode == "check":
    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except Exception:
        print(json.dumps({"path": str(target), "status": "unreadable"}))
        sys.exit(4)
    hits = RedactionPatterns.check_sensitive(content)
    result = {"path": str(target), "status": "has_sensitive" if hits else "clean", "patterns_detected": hits}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if hits:
        sys.exit(1)
else:
    result = redact_file(target, dry_run=dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["changes"] > 0:
        print(f"[REDACTED] {result['path']}: {result['patterns_detected']}", file=sys.stderr)
PY
    ;;

  dir)
    dry_flag="False"
    [[ "$DRY_RUN" == "true" ]] && dry_flag="True"
    python3 - "$TARGET" "$dry_flag" <<'PY'
import json, sys
from pathlib import Path
from result_bundler import redact_directory

target = Path(sys.argv[1])
dry_run = sys.argv[2] == "True"

results = redact_directory(target, dry_run=dry_run)
changed = [r for r in results if r["changes"] > 0]
total = len(results)

print(json.dumps({
    "directory": str(target),
    "total_files": total,
    "redacted": len(changed),
    "dry_run": dry_run,
    "results": results,
}, ensure_ascii=False, indent=2))

if changed:
    print(f"[REDACTED] {len(changed)}/{total} files had sensitive content", file=sys.stderr)
else:
    print(f"[OK] All {total} files clean", file=sys.stderr)
PY
    ;;

  pg-evidence)
    python3 - "$TARGET" <<'PY'
import json, sys
from pathlib import Path
from result_bundler import pg_evidence_summary

target = Path(sys.argv[1])
try:
    query_text = target.read_text(encoding="utf-8")
except Exception as e:
    print(json.dumps({"error": str(e)}))
    sys.exit(4)

summary = pg_evidence_summary(query_text)
print(json.dumps(summary, ensure_ascii=False, indent=2))
sys.stderr.write("[OK] PG evidence summary generated (connection details omitted)\n")
PY
    ;;

  *) echo "Unknown mode: $MODE" >&2; exit 2 ;;
esac
