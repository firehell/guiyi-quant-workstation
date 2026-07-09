#!/usr/bin/env bash
# Generate delivery_report_draft.md for WorkBuddy command B.
set -euo pipefail

TASK_ID="${1:-}"
TASK_FILE="${2:-}"

if [ -z "$TASK_ID" ] || [ -z "$TASK_FILE" ]; then
  echo "Usage: scripts/ai/make_delivery_summary.sh <TASK_ID> <task_file>" >&2
  exit 1
fi

if [ ! -f "$TASK_FILE" ]; then
  echo "Task file not found: $TASK_FILE" >&2
  exit 1
fi

GIT_ROOT="$(git rev-parse --show-toplevel)"
cd "$GIT_ROOT"

RESULT_DIR=".ai/results/${TASK_ID}"
EXEC_SUMMARY="${RESULT_DIR}/execution_summary.md"
DRAFT_FILE="${RESULT_DIR}/delivery_report_draft.md"

if [ ! -f "$EXEC_SUMMARY" ]; then
  echo "Execution summary not found: $EXEC_SUMMARY" >&2
  echo "Run: scripts/ai/collect_result.sh ${TASK_ID} ${TASK_FILE}" >&2
  exit 1
fi

TS="$(date +%Y%m%d-%H%M%S)"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
DIFF_STAT="$(git diff --stat 2>/dev/null || true)"

extract_section() {
  local heading="$1"
  awk -v h="$heading" '
    $0 ~ "^## " h { found=1; next }
    found && /^## / { exit }
    found { print }
  ' "$TASK_FILE"
}

GOALS="$(extract_section "目标")"
ACCEPTANCE="$(extract_section "验收标准")"
RISKS="$(extract_section "风险点")"
NOT_DO="$(extract_section "不做事项")"

{
  echo "# Delivery Report Draft"
  echo
  echo "- **TASK_ID**: ${TASK_ID}"
  echo "- **Generated at**: ${TS}"
  echo "- **Branch**: ${BRANCH}"
  echo "- **Task file**: \`${TASK_FILE}\`"
  echo "- **Execution summary**: \`${EXEC_SUMMARY}\`"
  echo
  echo "---"
  echo
  echo "## 1. 本次交付摘要"
  echo
  echo "基于 \`execution_summary.md\` 与任务单自动生成的交付报告草稿，供 WorkBuddy 命令 B 完善。"
  echo
  echo "## 2. 完成内容"
  echo
  echo '```'
  if [ -n "$DIFF_STAT" ]; then
    echo "$DIFF_STAT"
  else
    echo "(see execution_summary for file list)"
  fi
  echo '```'
  echo
  echo "详细变更见: \`${EXEC_SUMMARY}\`"
  echo
  echo "## 3. 未完成内容"
  echo
  echo "（WorkBuddy / 用户填写：对照任务目标与 diff 判断）"
  echo
  echo "### 任务目标（来自任务单）"
  echo
  if [ -n "$GOALS" ]; then
    echo "$GOALS"
  else
    echo "- （任务单中未找到「目标」章节）"
  fi
  echo
  echo "## 4. 测试结论"
  echo
  echo "见 execution_summary 中的 Latest Test Log 章节。"
  echo
  echo "## 5. 风险点"
  echo
  if [ -n "$RISKS" ]; then
    echo "$RISKS"
  else
    echo "- （任务单中未找到「风险点」章节）"
  fi
  echo
  echo "## 6. 是否满足验收标准"
  echo
  echo "（WorkBuddy 对照以下标准逐项判断）"
  echo
  if [ -n "$ACCEPTANCE" ]; then
    echo "$ACCEPTANCE"
  else
    echo "- （任务单中未找到「验收标准」章节）"
  fi
  echo
  echo "## 7. 是否建议合并"
  echo
  echo "（WorkBuddy 填写：是 / 否 / 需返工，并说明理由）"
  echo
  echo "## 8. 合并前人工检查清单"
  echo
  echo "对照 \`docs/delivery_checklist.md\`："
  echo
  echo "- [ ] 任务有书面 prompt"
  echo "- [ ] 首次 Codex  pass 为只读 plan"
  echo "- [ ] 用户明确批准开发"
  echo "- [ ] 使用 codex/ 或 feature/ 专用分支"
  echo "- [ ] 未触碰 .env / 密钥 / data/raw / data/parquet"
  echo "- [ ] 未自动 push / merge / deploy"
  echo "- [ ] git diff --check 通过"
  echo "- [ ] 相关测试已运行或有跳过理由"
  echo
  echo "### 不做事项（来自任务单）"
  echo
  if [ -n "$NOT_DO" ]; then
    echo "$NOT_DO"
  else
    echo "- （任务单中未找到「不做事项」章节）"
  fi
  echo
  echo "## 9. 下一步建议"
  echo
  echo "（WorkBuddy 填写）"
} >"$DRAFT_FILE"

echo "Delivery report draft: $DRAFT_FILE"
cat "$DRAFT_FILE"
