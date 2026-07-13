#!/usr/bin/env bash
# Execute the first fenced bash block under TASK §18.0 without eval.
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"; OUT_ROOT="$REPO_ROOT/.ai/results"
TASK_ID=""
while [[ $# -gt 0 ]]; do
  case "$1" in --task) TASK_ID="${2:-}"; shift 2;; --scope) shift 2;; -h|--help) echo "Usage: scripts/ai/run_tests.sh --task <TASK_ID>"; exit 0;; *) echo "Unknown argument: $1" >&2; exit 2;; esac
done
[[ -n "$TASK_ID" ]] || { echo "--task is required" >&2; exit 2; }; cd "$REPO_ROOT"
TASK_FILE=""
for candidate in "docs/tasks/${TASK_ID}.md" ".ai/tasks/${TASK_ID}.md" "docs/tasks/examples/${TASK_ID}.md"; do [[ -f "$candidate" ]] && { TASK_FILE="$candidate"; break; }; done
OUT_DIR="$OUT_ROOT/$TASK_ID"; mkdir -p "$OUT_DIR"
COMMANDS_FILE="$OUT_DIR/commands_executed.tsv"; RESULTS_FILE="$OUT_DIR/test_results.tsv"; FAILED_FILE="$OUT_DIR/failed_commands.txt"; SKIPPED_FILE="$OUT_DIR/skipped_tests.txt"
: > "$COMMANDS_FILE"; : > "$RESULTS_FILE"; : > "$FAILED_FILE"; : > "$SKIPPED_FILE"
CMDS="$(mktemp)"; trap 'rm -f "$CMDS"' EXIT
if [[ -n "$TASK_FILE" ]]; then
  awk '
    /^### 18\.0 自动化测试命令/ {section=1; next}
    section && /^### / {exit}
    section && /^```bash[[:space:]]*$/ {block=1; next}
    block && /^```[[:space:]]*$/ {exit}
    block {print}
  ' "$TASK_FILE" > "$CMDS"
fi
if ! grep -q '[^[:space:]#]' "$CMDS"; then
  printf '%s\n' 'git diff --check' 'bash -n scripts/ai/*.sh' > "$CMDS"
  echo "TASK §18.0 missing; used fallback: git diff --check + bash -n scripts/ai/*.sh" > "$SKIPPED_FILE"
fi

is_safe_command() {
  local command="$1"
  [[ "$command" =~ ^[[:space:]]*(git|bash|grep|rg)[[:space:]] || "$command" =~ ^[[:space:]]*python[[:space:]]+-m[[:space:]]+pytest[[:space:]] ]] || return 1
  [[ ! "$command" =~ (^|[[:space:]])(rm|sudo|ssh|scp)([[:space:]]|$) ]] || return 1
  [[ ! "$command" =~ git[[:space:]]+(push|merge|reset|checkout|clean|commit) ]] || return 1
  [[ ! "$command" =~ (danger-full-access|dangerously-bypass-approvals-and-sandbox) ]] || return 1
  [[ ! "$command" =~ (^|[^[:alnum:]_])(curl|wget|nc|netcat)([^[:alnum:]_]|$) ]] || return 1
  [[ ! "$command" =~ (\>\>|>|<|\;|\&\&|\|\||\$\() ]] || return 1
  [[ "$command" != *'`'* ]] || return 1
}

overall=0; index=0
while IFS= read -r command || [[ -n "$command" ]]; do
  [[ -z "${command//[[:space:]]/}" || "$command" =~ ^[[:space:]]*# ]] && continue
  index=$((index + 1)); printf '%s\t%s\n' "$index" "$command" >> "$COMMANDS_FILE"
  if ! is_safe_command "$command"; then
    printf '%s\n' "$command" >> "$FAILED_FILE"; printf '%s\t126\tREJECTED\t%s\n' "$index" "$command" >> "$RESULTS_FILE"
    echo "[REJECTED] unsafe test command: $command" >&2; overall=1; continue
  fi
  echo "[TEST $index] $command"
  set +e
  bash --noprofile --norc -c "$command" 2>&1 | tee -a "$OUT_DIR/test.log"
  rc=${PIPESTATUS[0]}
  set -e
  printf '%s\t%s\t%s\t%s\n' "$index" "$rc" "$([[ $rc -eq 0 ]] && echo PASS || echo FAIL)" "$command" >> "$RESULTS_FILE"
  if [[ $rc -ne 0 ]]; then printf '%s\n' "$command" >> "$FAILED_FILE"; overall=1; fi
done < "$CMDS"
# ── WS-V2-007: Post-test redaction & large log detection ──────────
if [[ "${GUIYI_SKIP_REDACT:-}" != "1" ]]; then
  "$SCRIPT_DIR/redact_evidence.sh" --file "$OUT_DIR/test.log" 2>/dev/null || true
  # Also redact any other output files
  for f in "$OUT_DIR"/*.log "$OUT_DIR"/*.txt; do
    [[ -f "$f" ]] && "$SCRIPT_DIR/redact_evidence.sh" --file "$f" 2>/dev/null || true
  done
fi
# Large log detection (1 MB threshold)
"$SCRIPT_DIR/_evidence_lib.sh" && detect_large_logs "$OUT_DIR" 2>/dev/null || true
[[ $overall -eq 0 ]] && echo "[OK] all declared tests passed" || echo "[FAIL] one or more declared tests failed" >&2
exit "$overall"
