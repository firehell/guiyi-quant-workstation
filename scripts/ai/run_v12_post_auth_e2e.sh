#!/usr/bin/env bash
# Run V1.2 Post-Auth GitHub Issue E2E for TASK-20260709-002.
# Requires: gh auth login, labels per docs/workflows/github_labels.md
set -euo pipefail

TASK_ID="TASK-20260709-002-workstation-v1.2-github-issue-trace"
TASK_FILE="docs/tasks/examples/${TASK_ID}.md"
RESULT_DIR=".ai/results/${TASK_ID}"

usage() {
  echo "Usage: scripts/ai/run_v12_post_auth_e2e.sh [--skip-labels] [--skip-create]" >&2
  echo "  --skip-labels  Skip gh label create (labels already exist)" >&2
  echo "  --skip-create  Skip issue create/link (TASK already has GitHub Issue)" >&2
}

SKIP_LABELS=false
SKIP_CREATE=false
while [ $# -gt 0 ]; do
  case "$1" in
    --skip-labels) SKIP_LABELS=true ;;
    --skip-create) SKIP_CREATE=true ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
  esac
  shift
done

GIT_ROOT="$(git rev-parse --show-toplevel)"
cd "$GIT_ROOT"

if ! command -v gh >/dev/null 2>&1; then
  echo "gh CLI not found. Install: brew install gh" >&2
  exit 1
fi

if ! gh auth status >/dev/null 2>&1; then
  echo "gh is not authenticated. Run: gh auth login" >&2
  exit 1
fi

if [ ! -f "$TASK_FILE" ]; then
  echo "Task file not found: $TASK_FILE" >&2
  exit 1
fi

echo "==> Repository: $(gh repo view --json nameWithOwner -q .nameWithOwner)"
echo "==> TASK: $TASK_ID"

if [ "$SKIP_LABELS" = false ]; then
  echo "==> Creating GitHub labels (idempotent)..."
  gh label create "type/task"      --description "标准开发任务" --color "1D76DB" 2>/dev/null || true
  gh label create "type/bug"       --description "缺陷修复"   --color "D73A4A" 2>/dev/null || true
  gh label create "type/refactor"  --description "重构"       --color "FBCA04" 2>/dev/null || true
  gh label create "type/docs"      --description "文档"       --color "0075CA" 2>/dev/null || true
  gh label create "type/test"      --description "测试"       --color "0E8A16" 2>/dev/null || true
  gh label create "status/requirement-ready" --description "任务单就绪"     --color "C5DEF5" 2>/dev/null || true
  gh label create "status/plan-ready"        --description "Plan 完成"      --color "BFD4F2" 2>/dev/null || true
  gh label create "status/approved-dev"      --description "批准开发"       --color "FEF2C0" 2>/dev/null || true
  gh label create "status/coding"            --description "开发中"         --color "FBCA04" 2>/dev/null || true
  gh label create "status/testing"           --description "测试中"         --color "F9D0C4" 2>/dev/null || true
  gh label create "status/delivery-ready"    --description "可交付"         --color "C2E0C6" 2>/dev/null || true
  gh label create "status/closed"            --description "已完成"         --color "0E8A16" 2>/dev/null || true
  gh label create "status/failed"            --description "执行失败"       --color "D73A4A" 2>/dev/null || true
  gh label create "status/replan"            --description "需重新 Plan"    --color "E99695" 2>/dev/null || true
  gh label create "area/workstation" --description "AI 工作站" --color "5319E7" 2>/dev/null || true
  gh label create "area/data"        --description "数据中心"  --color "1D76DB" 2>/dev/null || true
  gh label create "area/strategy"    --description "策略"      --color "B60205" 2>/dev/null || true
  gh label create "area/realtime"    --description "实时监听"  --color "FBCA04" 2>/dev/null || true
  gh label create "area/alert"       --description "通知告警"  --color "D93F0B" 2>/dev/null || true
  gh label create "area/backtest"    --description "回测"      --color "0E8A16" 2>/dev/null || true
  gh label create "area/deploy"      --description "部署运维"  --color "006B75" 2>/dev/null || true
  gh label create "risk/low"    --description "低风险" --color "C2E0C6" 2>/dev/null || true
  gh label create "risk/medium" --description "中风险" --color "FBCA04" 2>/dev/null || true
  gh label create "risk/high"   --description "高风险" --color "D73A4A" 2>/dev/null || true
  gh label create "ai/workbuddy" --description "WorkBuddy" --color "D4C5F9" 2>/dev/null || true
  gh label create "ai/codebuddy" --description "CodeBuddy" --color "C5DEF5" 2>/dev/null || true
  gh label create "ai/codex"     --description "Codex"     --color "BFDADC" 2>/dev/null || true
  echo "Labels:"
  gh label list | grep -E '^(type|status|area|risk|ai)/' || true
fi

ISSUE_NUMBER=""
if [ "$SKIP_CREATE" = false ]; then
  echo "==> Creating GitHub Issue from TASK..."
  CREATE_OUT="$(scripts/ai/create_issue_from_task.sh "$TASK_FILE")"
  echo "$CREATE_OUT"
  ISSUE_NUMBER="$(echo "$CREATE_OUT" | awk -F= '/^ISSUE_NUMBER=/{print $2}')"
  if [ -z "$ISSUE_NUMBER" ]; then
    echo "Failed to parse ISSUE_NUMBER from create_issue_from_task.sh output" >&2
    exit 1
  fi
  echo "==> Linking Issue #$ISSUE_NUMBER to TASK..."
  scripts/ai/link_task_issue.sh "$TASK_ID" "$ISSUE_NUMBER" "$TASK_FILE"
else
  ISSUE_NUMBER="$(awk '
    $0 ~ "^## 0\\. 元信息" { in_meta=1; next }
    in_meta && /^## / { exit }
    in_meta && $0 ~ "^\\| GitHub Issue \\|" {
      if (match($0, /#[0-9]+/)) { print substr($0, RSTART + 1, RLENGTH - 1); exit }
    }
  ' "$TASK_FILE")"
  if [ -z "$ISSUE_NUMBER" ]; then
    echo "No GitHub Issue linked in TASK and --skip-create not usable" >&2
    exit 1
  fi
  echo "==> Using existing Issue #$ISSUE_NUMBER"
fi

mkdir -p "$RESULT_DIR"
if [ ! -f "${RESULT_DIR}/plan_result.md" ]; then
  LATEST_PLAN="$(ls -t "${RESULT_DIR}"/codex_plan_*.md 2>/dev/null | head -1 || true)"
  if [ -n "$LATEST_PLAN" ]; then
    cp "$LATEST_PLAN" "${RESULT_DIR}/plan_result.md"
  fi
fi

for f in plan_result.md test_result.md execution_summary.md delivery_report.md; do
  if [ ! -f "${RESULT_DIR}/${f}" ] && [ "$f" = "delivery_report.md" ] && [ -f "${RESULT_DIR}/delivery_report_draft.md" ]; then
    cp "${RESULT_DIR}/delivery_report_draft.md" "${RESULT_DIR}/delivery_report.md"
  fi
  if [ ! -f "${RESULT_DIR}/${f}" ]; then
    echo "Warning: missing ${RESULT_DIR}/${f}" >&2
  fi
done

echo "==> Posting plan comment + PLAN_READY label..."
scripts/ai/comment_issue_result.sh "$TASK_ID" plan "$TASK_FILE"
scripts/ai/update_issue_status.sh "$TASK_ID" PLAN_READY "$TASK_FILE"

echo "==> Posting test comment..."
scripts/ai/comment_issue_result.sh "$TASK_ID" test "$TASK_FILE"

echo "==> Posting execution_summary comment..."
if [ -f "${RESULT_DIR}/execution_summary.md" ]; then
  TS="$(date +%Y-%m-%d\ %H:%M:%S)"
  TMP="$(mktemp)"
  {
    echo "## Execution Summary — ${TASK_ID}"
    echo
    echo "- **Posted at**: ${TS}"
    echo
    echo "---"
    echo
    cat "${RESULT_DIR}/execution_summary.md"
  } >"$TMP"
  gh issue comment "$ISSUE_NUMBER" --body-file "$TMP"
  rm -f "$TMP"
fi

echo "==> Posting delivery comment + DELIVERY_READY label..."
scripts/ai/comment_issue_result.sh "$TASK_ID" delivery "$TASK_FILE"
scripts/ai/update_issue_status.sh "$TASK_ID" DELIVERY_READY "$TASK_FILE"

ISSUE_URL="$(gh issue view "$ISSUE_NUMBER" --json url -q .url)"
echo
echo "==> Post-Auth E2E complete"
echo "ISSUE_NUMBER=$ISSUE_NUMBER"
echo "ISSUE_URL=$ISSUE_URL"
echo
echo "Verify:"
echo "  gh issue view $ISSUE_NUMBER --comments"
echo "  gh issue view $ISSUE_NUMBER --json labels,title,url"
echo
echo "Manual close (optional, after your review):"
echo "  gh issue close $ISSUE_NUMBER --comment 'V1.2 GitHub Issue trace acceptance completed.'"
