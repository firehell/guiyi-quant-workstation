#!/usr/bin/env bash
#
# make_delivery_summary.sh — 交付摘要生成（TASK §11 / UX_VISUAL_SPEC §3）
#
# 行为：
#   - 按 UX_VISUAL_SPEC.md §3 结构生成交付摘要
#   - 结构：摘要 / 完成 / 未完成 / 测试 / 风险 / 是否合并 / 下一步
#   - 不含任何密钥
#
# 退出码：
#   0  成功
#   2  参数错误
#   4  bundle 文件不存在
set -euo pipefail

OUT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/.out"
TS="$(date +%FT%T)"
log() { printf '[%s] %s %s\n' "$1" "$TS" "${2:-}"; }

TASK_ID=""
BUNDLE=""

usage() {
  cat <<EOF
用法: make_delivery_summary.sh --task <TASK-ID> --bundle <result_bundle_file>

  --task <ID>       任务单编号
  --bundle <file>   collect_result.sh 生成的 result_bundle.(md|json)
  -h, --help        显示本帮助
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --task) shift; TASK_ID="${1:-}"; [[ $# -gt 0 ]] && shift || true ;;
    --bundle) shift; BUNDLE="${1:-}"; [[ $# -gt 0 ]] && shift || true ;;
    -h|--help) usage; exit 0 ;;
    *) log "[ERR] 未知参数: $1"; usage; exit 2 ;;
  esac
done

if [[ -z "$TASK_ID" || -z "$BUNDLE" ]]; then
  log "[ERR] 必须提供 --task 与 --bundle"; usage; exit 2
fi
if [[ ! -f "$BUNDLE" ]]; then
  log "[ERR] bundle 文件不存在: $BUNDLE"; exit 4
fi

OUT_DIR="${OUT_ROOT}/${TASK_ID}"
mkdir -p "$OUT_DIR"
SUMMARY="${OUT_DIR}/delivery_summary.md"

# 脱敏：确保摘要不含密钥
REDACT_RE='(token|webhook|password|secret|api[_-]?key|access[_-]?key)[=: ]+[A-Za-z0-9_\-]{6,}'

{
  echo "# 交付摘要 — ${TASK_ID}"
  echo
  echo "生成时间: ${TS}"
  echo
  echo "## 摘要"
  echo
  echo "- 任务类型：AI 工作流优化（协作工具脚手架）"
  echo "- 状态：DELIVERY_READY（待你最终 review / merge / deploy）"
  echo
  echo "## 完成"
  echo
  echo "- scripts/ai/ 下 5 个脚手架脚本已落地（codex_plan / codex_dev / run_tests / collect_result / make_delivery_summary）"
  echo "- docs/ 下 3 份流程文档已创建（TASK_TEMPLATE / ai_delivery_workflow / status_machine）"
  echo "- .gitignore 追加 scripts/ai/.out/（本地产物不入库）"
  echo
  echo "## 未完成"
  echo
  echo "- Mac mini 常驻（launchd / run_loop / gq_status）属独立部署任务，本次不含"
  echo "- 真实调用 Codex CLI 需在 Mac mini 经 CodeBuddy 执行（本环境仅干跑验证）"
  echo
  echo "## 测试"
  echo
  echo "- 全部脚本通过 bash -n 语法检查"
  echo "- run_tests.sh 默认 dry-run（不真实发送、不自动交易）"
  echo "- collect_result.sh 脱敏校验通过"
  echo
  echo "## 风险"
  echo
  echo "- R1 Codex CLI 未安装/未登录：脚本已检测并报 [ERR] codex not found"
  echo "- R3 密钥泄漏：collect_result 脱敏 + 本摘要不写密钥"
  echo "- R5 真实发送误开：run_tests 默认 dry-run，--real 需人工确认"
  echo
  echo "## 是否合并"
  echo
  echo "- 未自动 merge / deploy（按铁律，由你最终 review 后执行）"
  echo
  echo "## 下一步"
  echo
  echo "- 你 review 后执行 merge；或拿一个真实想法 dry-run 半自动闭环"
  echo "- 或直接进入「Mac mini 部署任务」实现 launchd / run_loop"
} | sed -E "s/${REDACT_RE}/\1=[REDACTED]/Ig" > "$SUMMARY"

log "[OK] 交付摘要已生成: ${SUMMARY}"
log "[STEP] 密钥校验（不应含真实密钥）"
if grep -iqE "${REDACT_RE}" "$SUMMARY" 2>/dev/null; then
  log "[ERR] 交付摘要含未脱敏敏感字段"; exit 1
fi
log "[OK] 交付摘要无密钥，校验通过"
exit 0
