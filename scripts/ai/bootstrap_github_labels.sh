#!/usr/bin/env bash
# Bootstrap GitHub labels for the GitHub Native control plane.
set -euo pipefail

APPLY=false
LIST_ONLY=false
REPO_NAME=""

usage() {
  cat <<'EOF'
Usage: scripts/ai/bootstrap_github_labels.sh [options]

Options:
  --apply          Create/update labels through gh. Default is dry-run.
  --dry-run        Print planned operations only (default).
  --list           Print label specs as TSV and exit.
  --repo <owner/repo>
  -h, --help       Show help.

The script is idempotent: existing labels are edited, missing labels are created.
It never deletes labels, closes Issues, or modifies TASK files.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply) APPLY=true; shift ;;
    --dry-run) APPLY=false; shift ;;
    --list) LIST_ONLY=true; shift ;;
    --repo) REPO_NAME="${2:-}"; [[ -n "$REPO_NAME" ]] || { echo "--repo requires a value" >&2; exit 2; }; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

label_specs() {
  cat <<'EOF'
type/task|1D76DB|标准 TASK 生命周期 Issue
type/bug|D73A4A|可复现缺陷
type/design|5319E7|架构、流程或 ADR 设计
area/workstation|5319E7|AI 工作站、dispatcher、TASK、Issue、PR、Gate
area/data|1D76DB|数据中心、RQData、Parquet、DuckDB、质量检查
area/web|0E8A16|Web 工作台、页面、前端交互
area/indicator|B60205|指标、策略信号、K 线 marker
area/runtime|FBCA04|本地 runtime、worker、scheduler、实时观察
status/draft|EDEDED|远程入口草稿
status/requirement-ready|C5DEF5|TASK 或需求入口已可读
status/plan-ready|BFD4F2|Plan 已产出，等待或已进入审批
status/approved|FEF2C0|用户已批准进入实现或执行
status/executing|FBCA04|Codex 或 CodeBuddy 正在执行
status/testing|F9D0C4|测试或 Gate 验证中
status/reviewing|D4C5F9|GPT、人工或外部 Review 中
status/delivery-ready|C2E0C6|已形成可审查交付
status/blocked|D73A4A|阻塞、失败或需要重做 Plan
status/closed|0E8A16|用户确认关闭
risk/r0|B60205|最高风险，必须外部审查和强审批
risk/r1|D73A4A|高风险，涉及核心 Gate 或生产边界
risk/r2|FBCA04|中风险，局部代码或规则调整
risk/r3|C2E0C6|低风险，文档、模板或只读治理
ai/gpt-authored|D4C5F9|GPT 创建或主导需求/架构草稿
ai/codex-executed|BFDADC|Codex 执行实现或验证
review/gpt-required|5319E7|需要 GPT 外部审查
type/refactor|FBCA04|Legacy: 重构
type/docs|0075CA|Legacy: 文档
type/test|0E8A16|Legacy: 测试
area/strategy|B60205|Legacy: 策略
area/realtime|FBCA04|Legacy: 实时监听
area/alert|D93F0B|Legacy: 通知告警
area/backtest|0E8A16|Legacy: 回测
area/deploy|006B75|Legacy: 部署运维
status/approved-dev|FEF2C0|Legacy: APPROVED_DEV
status/coding|FBCA04|Legacy: CODING
status/failed|D73A4A|Legacy: FAILED
status/replan|E99695|Legacy: REPLAN
risk/low|C2E0C6|Legacy: 低风险
risk/medium|FBCA04|Legacy: 中风险
risk/high|D73A4A|Legacy: 高风险
ai/workbuddy|D4C5F9|Legacy: WorkBuddy
ai/codebuddy|C5DEF5|Legacy: CodeBuddy
ai/codex|BFDADC|Legacy: Codex
EOF
}

if [[ "$LIST_ONLY" == true ]]; then
  label_specs
  exit 0
fi

if [[ "$APPLY" != true ]]; then
  echo "[DRY-RUN] GitHub label bootstrap plan"
  while IFS='|' read -r name color description; do
    [[ -n "$name" ]] || continue
    printf 'would ensure label: %s color=%s description=%s\n' "$name" "$color" "$description"
  done < <(label_specs)
  echo "[DRY-RUN] pass --apply to create/update labels with gh"
  exit 0
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "gh CLI not found. Install: brew install gh && gh auth login" >&2
  exit 1
fi

if ! gh auth status >/dev/null 2>&1; then
  echo "gh is not authenticated. Run: gh auth login" >&2
  exit 1
fi

if [[ -n "$REPO_NAME" ]]; then
  existing_labels="$(gh label list --repo "$REPO_NAME" --limit 1000 --json name --jq '.[].name')"
else
  existing_labels="$(gh label list --limit 1000 --json name --jq '.[].name')"
fi

label_exists() {
  local needle="$1"
  printf '%s\n' "$existing_labels" | grep -Fxq "$needle"
}

while IFS='|' read -r name color description; do
  [[ -n "$name" ]] || continue
  if label_exists "$name"; then
    if [[ -n "$REPO_NAME" ]]; then
      gh label edit "$name" --repo "$REPO_NAME" --color "$color" --description "$description" >/dev/null
    else
      gh label edit "$name" --color "$color" --description "$description" >/dev/null
    fi
    echo "[OK] updated label: $name"
  else
    if [[ -n "$REPO_NAME" ]]; then
      gh label create "$name" --repo "$REPO_NAME" --color "$color" --description "$description" >/dev/null
    else
      gh label create "$name" --color "$color" --description "$description" >/dev/null
    fi
    echo "[OK] created label: $name"
  fi
done < <(label_specs)

echo "[OK] GitHub labels bootstrapped"
