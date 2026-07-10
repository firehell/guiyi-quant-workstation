#!/usr/bin/env bash
#
# codex_plan.sh — 只读 plan 模式入口（COLLAB_PROTOCOL §6 / §11）
#
# 行为：
#   - 以只读模式启动 Codex CLI，产出 plan 文本到 scripts/ai/.out/<task-id>/plan.md
#   - 不修改任何仓库业务代码、不 git commit、不 git push、不写数据库、不发送
#
# 护栏（appendix B 铁律）：
#   - plan 只读：脚本本身不写任何仓库文件，仅写 .out/ 产物目录
#   - 不读 .env / 不打印密钥
#   - 不 push / merge / deploy / 不删数据 / 不交易
#
# 退出码：
#   0  成功（plan.md 已生成）
#   2  参数错误
#   3  Codex CLI 不可用
#   4  TASK 文件不存在
set -euo pipefail

OUT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/.out"
TS="$(date +%FT%T)"
log() { printf '[%s] %s %s\n' "$1" "$TS" "${2:-}"; }

TASK_ID=""
PROMPT_FILE=""

usage() {
  cat <<EOF
用法: codex_plan.sh --task <TASK-ID> [--prompt <plan_prompt_file>]

  --task <ID>      任务单编号（用于定位 tasks/<ID>.md 与产物目录）
  --prompt <file>  可选的 Codex Plan Prompt 文件（默认读任务单第 15 节）
  -h, --help       显示本帮助
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --task) shift; TASK_ID="${1:-}"; [[ $# -gt 0 ]] && shift || true ;;
    --prompt) shift; PROMPT_FILE="${1:-}"; [[ $# -gt 0 ]] && shift || true ;;
    -h|--help) usage; exit 0 ;;
    *) log "[ERR] 未知参数: $1"; usage; exit 2 ;;
  esac
done

if [[ -z "$TASK_ID" ]]; then
  log "[ERR] 必须提供 --task <TASK-ID>"; usage; exit 2
fi

# 定位任务单（兼容仓库内常见位置）
TASK_FILE=""
for cand in \
  "tasks/${TASK_ID}.md" \
  "tasks/examples/${TASK_ID}.md" \
  "docs/tasks/examples/${TASK_ID}.md" \
  "workstation/tasks/${TASK_ID}.md"; do
  if [[ -f "$cand" ]]; then TASK_FILE="$cand"; break; fi
done

if [[ -z "$TASK_FILE" ]]; then
  log "[ERR] 未找到任务单，尝试过: tasks/ tasks/examples/ docs/tasks/examples/ workstation/tasks/"; exit 4
fi

if ! command -v codex >/dev/null 2>&1; then
  log "[ERR] codex not found —— 请先安装并登录 Codex CLI"; exit 3
fi

OUT_DIR="${OUT_ROOT}/${TASK_ID}"
mkdir -p "$OUT_DIR"
PLAN_FILE="${OUT_DIR}/plan.md"

log "[STEP] 进入只读 plan 模式 (task=${TASK_ID})"
log "[STEP] 任务单: ${TASK_FILE}"
log "[STEP] plan 输出: ${PLAN_FILE}"

# 构建 plan 提示词：默认从任务单第 15 节提取；否则用 --prompt 文件
PROMPT_TMP="$(mktemp)"
if [[ -n "$PROMPT_FILE" ]]; then
  if [[ ! -f "$PROMPT_FILE" ]]; then log "[ERR] --prompt 文件不存在: $PROMPT_FILE"; exit 4; fi
  cat "$PROMPT_FILE" > "$PROMPT_TMP"
else
  # 抽取任务单第 15 节（## 15. 开头到下一个 ## 之前）作为 plan prompt
  awk '/^## 15\./{f=1;next} /^## /{if(f)exit} f{print}' "$TASK_FILE" > "$PROMPT_TMP" || true
  if [[ ! -s "$PROMPT_TMP" ]]; then
    log "[WARN] 未从任务单第 15 节提取到 plan prompt，使用通用只读 plan 指令"
    cat >> "$PROMPT_TMP" <<'PROMPT'
你现在是 Codex CLI，处于 plan（只读）模式。请只读取仓库与文档，不写任何业务代码，
产出 plan 文本说明将如何完成该任务。严格遵守：不碰业务代码/数据/策略/.env，
不 git push/merge/deploy，不真实发送。
PROMPT
  fi
fi

log "[STEP] 调用 codex（只读，不写仓库业务代码）"
# --readonly 保证 Codex 不能修改仓库；plan 文本写入 .out/ 产物（脚本自身允许写产物目录）
if codex --readonly --prompt "$(cat "$PROMPT_TMP")" > "$PLAN_FILE" 2> "${OUT_DIR}/plan.err"; then
  log "[OK] plan 已生成: ${PLAN_FILE}"
else
  log "[ERR] codex plan 执行失败，详见 ${OUT_DIR}/plan.err"
  rm -f "$PROMPT_TMP"
  exit 1
fi

rm -f "$PROMPT_TMP"
log "[OK] codex_plan.sh 完成（只读，未修改仓库业务代码）"
exit 0
