#!/usr/bin/env bash
#
# codex_dev.sh — 开发模式入口（COLLAB_PROTOCOL §7 / §12）
#
# 行为：
#   - 以开发模式启动 Codex CLI，允许在 workspace 内写文件
#   - 完成后自动调用 run_tests.sh --scope all
#
# 护栏（dev 模式硬约束，违反即中止）：
#   - 不修改 .env / token / webhook / 密钥
#   - 不 git push / merge / deploy
#   - 不删除数据（DB/parquet/日志）
#   - 不真实发送企业微信（除非显式 --run-send --confirm-observation-only 且用户授权）
#   - 不自动交易 / 不生成订单草稿
#   - 默认 dry-run / observation-only
#
# 退出码：
#   0  成功
#   2  参数错误
#   3  Codex CLI 不可用
#   5  护栏自检失败（越权请求）
set -euo pipefail

OUT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/.out"
TS="$(date +%FT%T)"
log() { printf '[%s] %s %s\n' "$1" "$TS" "${2:-}"; }

TASK_ID=""
PLAN_FILE=""
RUN_SEND=0
CONFIRM_OBS=0

usage() {
  cat <<EOF
用法: codex_dev.sh --task <TASK-ID> [--plan <plan_file>] [--run-send --confirm-observation-only]

  --task <ID>                 任务单编号
  --plan <file>               已确认的 plan.md（默认 scripts/ai/.out/<ID>/plan.md）
  --run-send                  显式允许真实发送（仍需 --confirm-observation-only 与用户授权）
  --confirm-observation-only  确认仅为 observation-only 真实动作
  -h, --help                  显示本帮助
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --task) shift; TASK_ID="${1:-}"; [[ $# -gt 0 ]] && shift || true ;;
    --plan) shift; PLAN_FILE="${1:-}"; [[ $# -gt 0 ]] && shift || true ;;
    --run-send) RUN_SEND=1; shift ;;
    --confirm-observation-only) CONFIRM_OBS=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) log "[ERR] 未知参数: $1"; usage; exit 2 ;;
  esac
done

if [[ -z "$TASK_ID" ]]; then
  log "[ERR] 必须提供 --task <TASK-ID>"; usage; exit 2
fi

# 护栏自检：真实发送需双重显式确认
if [[ "$RUN_SEND" -eq 1 && "$CONFIRM_OBS" -ne 1 ]]; then
  log "[ERR] 真实发送需同时传 --run-send --confirm-observation-only 且由你授权"; exit 5
fi
if [[ "$RUN_SEND" -eq 1 ]]; then
  log "[WARN] 真实发送已开启（observation-only），仅在你显式授权下生效"
fi

if ! command -v codex >/dev/null 2>&1; then
  log "[ERR] codex not found —— 请先安装并登录 Codex CLI"; exit 3
fi

OUT_DIR="${OUT_ROOT}/${TASK_ID}"
mkdir -p "$OUT_DIR"
if [[ -z "$PLAN_FILE" ]]; then
  PLAN_FILE="${OUT_DIR}/plan.md"
fi
if [[ ! -f "$PLAN_FILE" ]]; then
  log "[WARN] plan 文件不存在: ${PLAN_FILE}；将继续（Codex 按任务单第 16 节开发）"
fi

# 越权护栏：扫描任务单，若含要求改 .env/自动 push 等字样则中止（防御性提示，非阻断解析）
TASK_FILE=""
for cand in "tasks/${TASK_ID}.md" "tasks/examples/${TASK_ID}.md" "docs/tasks/examples/${TASK_ID}.md" "workstation/tasks/${TASK_ID}.md"; do
  if [[ -f "$cand" ]]; then TASK_FILE="$cand"; break; fi
done
if [[ -n "$TASK_FILE" ]]; then
  if grep -qiE '修改\s*\.env|git\s+push|git\s+merge|git\s+deploy|删除.*数据|rm\s+-rf' "$TASK_FILE" 2>/dev/null; then
    log "[WARN] 任务单含潜在越权关键词，请人工复核护栏（脚本仍按只读/默认 dry-run 执行）"
  fi
fi

log "[STEP] 进入 dev 模式 (task=${TASK_ID})"
log "[STEP] 调用 codex（workspace-write，默认 dry-run）"
# 开发模式允许写 workspace；真实发送/交易依赖上面护栏
DEV_PROMPT="按 plan 实现任务 ${TASK_ID}。默认 dry-run / observation-only；"
DEV_PROMPT+="禁止修改 .env/token/webhook/密钥；禁止 git push/merge/deploy；禁止删数据；禁止自动交易。"
if [[ -n "$PLAN_FILE" && -f "$PLAN_FILE" ]]; then
  DEV_PROMPT+=$'\n\n已确认 plan:\n'"$(cat "$PLAN_FILE")"
fi

if codex --prompt "$DEV_PROMPT" > "${OUT_DIR}/dev.log" 2>&1; then
  log "[OK] codex dev 完成"
else
  log "[ERR] codex dev 执行失败，详见 ${OUT_DIR}/dev.log"
  exit 1
fi

# 开发完成后自动跑测试
log "[STEP] 自动调用 run_tests.sh --scope all"
"${BASH_SOURCE[0]%/*}/run_tests.sh" --task "$TASK_ID" --scope all

log "[OK] codex_dev.sh 完成（未 push / merge / deploy，默认 dry-run）"
exit 0
