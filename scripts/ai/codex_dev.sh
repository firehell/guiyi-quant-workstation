#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"; OUT_ROOT="$REPO_ROOT/.ai/results"
source "$SCRIPT_DIR/_approve_lib.sh"
source "$SCRIPT_DIR/_work_level_lib.sh"
TASK_ID=""; PLAN_FILE=""
usage() { echo "Usage: scripts/ai/codex_dev.sh --task <TASK_ID> [--plan <plan_result.md>]"; }
while [[ $# -gt 0 ]]; do case "$1" in --task) TASK_ID="${2:-}"; shift 2;; --plan) PLAN_FILE="${2:-}"; shift 2;; -h|--help) usage; exit 0;; *) echo "Unknown argument: $1" >&2; exit 2;; esac; done
[[ -n "$TASK_ID" ]] || { usage >&2; exit 2; }; cd "$REPO_ROOT"
TASK_FILE="$(resolve_task_file "$TASK_ID" || true)"
[[ -n "$TASK_FILE" ]] || { echo "TASK not found: $TASK_ID" >&2; exit 4; }
check_issue_gate "$TASK_FILE" || exit $?
check_worktree_gate "$TASK_FILE" || exit $?
ISSUE="$(extract_task_meta_field "$TASK_FILE" "GitHub Issue")"
[[ -n "$PLAN_FILE" ]] || PLAN_FILE="$OUT_ROOT/$TASK_ID/plan_result.md"
APPROVAL_FILE="$REPO_ROOT/.ai/approvals/${TASK_ID}.json"
check_branch "$TASK_FILE"
verify_approval_v3 "$APPROVAL_FILE" "$TASK_ID" "$TASK_FILE" "$PLAN_FILE" "DEV" "$REPO_ROOT" "false"
command -v codex >/dev/null 2>&1 || { echo "codex CLI not found" >&2; exit 3; }
OUT_DIR="$OUT_ROOT/$TASK_ID"; mkdir -p "$OUT_DIR"
BEFORE_NAMES="$(mktemp)"; trap 'rm -f "$BEFORE_NAMES"' EXIT
git status --porcelain | sed 's/^...//' | sort -u > "$BEFORE_NAMES"; HEAD_BEFORE="$(git rev-parse HEAD)"
section() { awk -v prefix="## $1." '$0 ~ "^" prefix {on=1} on && $0 ~ /^## / && $0 !~ "^" prefix {exit} on {print}' "$TASK_FILE"; }
DEV_PROMPT="$(
  echo '你是 Codex CLI，处于 dev（workspace-write）模式。执行已批准 Plan。'
  echo '严格遵守 TASK 的允许/禁止路径；禁止 push/merge/deploy、凭证读取、数据删除和自动交易。'
  echo; echo '===== FULL TASK ====='; cat "$TASK_FILE"
  echo; echo '===== APPROVED PLAN ====='; cat "$PLAN_FILE"
  echo; echo '===== APPROVAL RECORD ====='; cat "$APPROVAL_FILE"
  for n in 7 16 18 19; do echo; echo "===== TASK SECTION $n ====="; section "$n"; done
  echo; echo '===== PRE-DEV GIT STATUS ====='; git status --short --branch
)"
echo "[DEV] task=$TASK_ID issue=$ISSUE branch=$(git branch --show-current)"
codex exec -s workspace-write "$DEV_PROMPT" > "$OUT_DIR/dev.log" 2>&1 || { echo "Codex Dev failed; see $OUT_DIR/dev.log" >&2; exit 1; }
[[ "$(git rev-parse HEAD)" == "$HEAD_BEFORE" ]] || { echo "Gate failed: Codex changed HEAD" >&2; exit 6; }
python3 - "$TASK_FILE" "$BEFORE_NAMES" <<'PY'
import re, subprocess, sys
text=open(sys.argv[1],encoding="utf-8").read(); section=text.split("## 7.",1)[1].split("## 8.",1)[0]
allowed=[x for x in re.findall(r"`([^`]+)`",section.split("**禁止修改**",1)[0]) if not x.startswith("相关")]
before=set(open(sys.argv[2],encoding="utf-8").read().splitlines())
now={line[3:] for line in subprocess.run(["git","status","--porcelain"],text=True,capture_output=True,check=True).stdout.splitlines() if len(line)>3}
bad=sorted(p for p in now-before if not any(p==a or (a.endswith("/") and p.startswith(a)) for a in allowed))
if bad: print("Scope Gate failed; unexpected new changes:\n- "+"\n- ".join(bad),file=sys.stderr); raise SystemExit(6)
PY
"$SCRIPT_DIR/run_tests.sh" --task "$TASK_ID"
echo "[OK] Dev and declared tests completed; no push/merge/deploy performed"
