#!/usr/bin/env bash
# WS-V2-007: Shell-side evidence collection helpers.
# Source this in dispatch / collect scripts to record evidence entries
# without duplicating Python logic.
# NOTE: does NOT set -e/-u/-o pipefail — caller is responsible.

SCRIPT_DIR="${SCRIPT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
PYTHONPATH="$SCRIPT_DIR/lib${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONPATH

# ── Evidence entry recording ────────────────────────────────────────

record_evidence_entry() {
  local path="$1" generated_by="$2" data_version="${3:-}"
  local git_commit now sha256 size
  git_commit="$(git rev-parse HEAD 2>/dev/null || echo "unknown")"
  now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  sha256="$(shasum -a 256 "$path" 2>/dev/null | cut -d' ' -f1 || echo "")"
  size="$(stat -f%z "$path" 2>/dev/null || echo 0)"

  python3 - "$path" "$generated_by" "$now" "$git_commit" "$data_version" "$sha256" "$size" <<'PY'
import json, sys
from pathlib import Path

entry = {
    "path": sys.argv[1],
    "generated_by": sys.argv[2],
    "generated_at": sys.argv[3],
    "git_commit": sys.argv[4],
    "data_version": sys.argv[5],
    "sha256_checksum": sys.argv[6],
    "size_bytes": int(sys.argv[7]),
}
# Append to evidence_index.jsonl in the out_dir's parent
out_dir = Path(sys.argv[1]).parent
index_file = out_dir / "evidence_index.jsonl"
mode = "a" if index_file.exists() else "w"
with open(index_file, mode, encoding="utf-8") as fh:
    fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
PY
}

# ── Full evidence index collection ──────────────────────────────────

collect_evidence_index() {
  local out_dir="$1" repo_root="${2:-}"
  if [[ -z "$repo_root" ]]; then
    repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
  fi

  if [[ "${GUIYI_SKIP_EVIDENCE_GATE:-}" == "1" ]]; then
    echo "[SKIP] Evidence Gate bypassed (GUIYI_SKIP_EVIDENCE_GATE=1)" >&2
    return 0
  fi

  python3 - "$out_dir" "$repo_root" <<'PY'
import json, sys
from pathlib import Path
from result_bundler import build_evidence_index_json

out_dir = Path(sys.argv[1])
repo_root = Path(sys.argv[2])
idx = build_evidence_index_json(out_dir, repo_root)
(out_dir / "evidence_index.json").write_text(
    json.dumps(idx, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
print(f"[OK] Evidence Index: {idx['total_files']} entries → {out_dir / 'evidence_index.json'}")
PY
}

# ── PG evidence wrapper ─────────────────────────────────────────────

collect_pg_evidence() {
  local query_file="$1" account="${2:-readonly}" snapshot_time="${3:-}"

  python3 - "$query_file" "$account" "$snapshot_time" <<'PY'
import json, sys
from pathlib import Path
from result_bundler import pg_evidence_summary

query_file = Path(sys.argv[1])
account = sys.argv[2]
snapshot_time = sys.argv[3]

if not query_file.is_file():
    print(json.dumps({"error": "query file not found", "path": str(query_file)}))
    sys.exit(4)

try:
    query_text = query_file.read_text(encoding="utf-8")
except Exception as e:
    print(json.dumps({"error": str(e)}))
    sys.exit(4)

summary = pg_evidence_summary(query_text, account=account, snapshot_time=snapshot_time)
out = query_file.with_suffix(".pg_evidence.json")
out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"[OK] PG Evidence: {out}")
PY
}

# ── Redact output directory ─────────────────────────────────────────

redact_output_dir() {
  local out_dir="$1"
  if [[ "${GUIYI_SKIP_REDACT:-}" == "1" ]]; then
    echo "[SKIP] Redaction bypassed (GUIYI_SKIP_REDACT=1)" >&2
    return 0
  fi
  "$SCRIPT_DIR/redact_evidence.sh" --dir "$out_dir" 2>&1
}

# ── Large log detection ─────────────────────────────────────────────

detect_large_logs() {
  local out_dir="$1" threshold="${2:-1048576}"  # 1 MB default
  python3 - "$out_dir" "$threshold" <<'PY'
import json, sys
from pathlib import Path
from result_bundler import handle_large_log

out_dir = Path(sys.argv[1])
threshold = int(sys.argv[2])
large: list[dict] = []

for fpath in sorted(out_dir.rglob("*")):
    if not fpath.is_file():
        continue
    if fpath.suffix.lower() in {".log", ".txt", ".tsv"}:
        result = handle_large_log(fpath, threshold=threshold)
        if result:
            large.append(result)

if large:
    print(json.dumps({"large_logs": len(large), "details": large}, ensure_ascii=False, indent=2))
else:
    print("[]")
PY
}
