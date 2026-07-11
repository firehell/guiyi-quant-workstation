#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
source "$SCRIPT_DIR/_work_level_lib.sh"

WRITE_REGISTRY=false
REGISTRY="${REPO_ROOT}/docs/workflows/worktree_registry.md"

usage() {
  echo "Usage: scripts/ai/list_worktrees.sh [--write-registry]"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --write-registry) WRITE_REGISTRY=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

cd "$REPO_ROOT"

echo "# Worktree list ($(date -u +%Y-%m-%dT%H:%M:%SZ))"
echo ""
printf "%-55s %-35s %s\n" "PATH" "BRANCH" "DIRTY"
printf "%s\n" "$(printf '%.0s-' {1..120})"

WT_LINES=()
while IFS= read -r line; do
  WT_LINES+=("$line")
done < <(git worktree list)

for line in "${WT_LINES[@]}"; do
  [[ -n "$line" ]] || continue
  wt_path="$(printf '%s' "$line" | awk '{print $1}')"
  branch="$(printf '%s' "$line" | sed -nE 's/.*\[([^]]+)\].*/\1/p')"
  dirty="clean"
  if [[ -n "$(git -C "$wt_path" status --porcelain 2>/dev/null || true)" ]]; then
    dirty="dirty"
  fi
  printf "%-55s %-35s %s\n" "$wt_path" "$branch" "$dirty"
done

echo ""
echo "## TASK mappings (from docs/tasks/*.md)"
for task_file in docs/tasks/TASK-*.md; do
  [[ -f "$task_file" ]] || continue
  task_id="$(extract_task_meta_field "$task_file" "Task ID")"
  [[ -n "$task_id" ]] || task_id="$(basename "$task_file" .md)"
  level="$(extract_work_level "$task_file")"
  branch="$(extract_task_meta_field "$task_file" Branch)"
  wt="$(extract_task_meta_field "$task_file" Worktree)"
  status="$(extract_task_meta_field "$task_file" Status)"
  echo "- $task_id | $level | branch=$branch | worktree=$wt | status=$status"
done

if [[ "$WRITE_REGISTRY" == true ]]; then
  {
    echo "# Worktree Registry"
    echo ""
    echo "> 自动生成：\`scripts/ai/list_worktrees.sh --write-registry\`"
    echo "> 更新时间：$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo ""
    echo "## 规范"
    echo ""
    echo "- 默认根目录：\`../guiyi-parallel/\`（\`GUIYI_WORKTREE_ROOT\` 可覆盖）"
    echo "- L1/L2 新任务：\`scripts/ai/init_task_worktree.sh --task <TASK_ID>\`"
    echo "- 主仓库 worktree 仅用于只读验收；新开发请用 parallel worktree"
    echo ""
    echo "## 当前 worktree"
    echo ""
    echo "| Path | Branch | Dirty | Notes |"
    echo "|------|--------|-------|-------|"
    for line in "${WT_LINES[@]}"; do
      wt_path="$(printf '%s' "$line" | awk '{print $1}')"
      branch="$(printf '%s' "$line" | sed -nE 's/.*\[([^]]+)\].*/\1/p')"
      dirty="clean"
      [[ -n "$(git -C "$wt_path" status --porcelain 2>/dev/null || true)" ]] && dirty="dirty"
      note=""
      case "$wt_path" in
        *guiyi-quant-workstation) note="主仓库；新 L1/L2 任务勿在此开发" ;;
        *web-indicators*) note="legacy overlay indicators" ;;
        *htdy-core*) note="火天大有 core" ;;
        *data-audit*) note="数据资产审计" ;;
        *jm-live-gate*) note="JM live runtime gate" ;;
        *live-runtime*) note="v1 live runtime closure" ;;
        *work-levels-home-direct*) note="L0/L1/L2 工作级别治理" ;;
      esac
      echo "| \`$wt_path\` | \`$branch\` | $dirty | $note |"
    done
    echo ""
    echo "## TASK 登记"
    echo ""
    for task_file in docs/tasks/TASK-*.md; do
      [[ -f "$task_file" ]] || continue
      task_id="$(extract_task_meta_field "$task_file" "Task ID")"
      [[ -n "$task_id" ]] || continue
      level="$(extract_work_level "$task_file")"
      branch="$(extract_task_meta_field "$task_file" Branch)"
      wt="$(extract_task_meta_field "$task_file" Worktree)"
      status="$(extract_task_meta_field "$task_file" Status)"
      echo "- **$task_id** — $level, branch=\`$branch\`, worktree=\`$wt\`, status=$status"
    done
  } > "$REGISTRY"
  echo ""
  echo "[OK] Registry written: $REGISTRY"
fi
