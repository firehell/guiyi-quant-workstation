#!/usr/bin/env bash
#
# run_tests.sh — 测试入口（COLLAB_PROTOCOL §8）
#
# 行为：
#   - 运行 pytest（按 --scope unit|integration|all）
#   - 采集通过/失败/跳过，退出码非 0 即失败
#
# 护栏：
#   - 默认 dry-run / mock webhook，不真实发送、不自动交易
#   - --real 需显式且人工确认
#   - 日志过滤 webhook|token|password|secret（脱敏打印）
#
# 退出码：
#   0  测试通过（或 dry-run 完成）
#   2  参数错误
#   3  pytest 不可用
set -uo pipefail

OUT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/.out"
TS="$(date +%FT%T)"
log() { printf '[%s] %s %s\n' "$1" "$TS" "${2:-}"; }

TASK_ID=""
SCOPE="all"
REAL=0

usage() {
  cat <<EOF
用法: run_tests.sh --task <TASK-ID> [--scope unit|integration|all] [--real]

  --task <ID>    任务单编号（用于产物目录与日志过滤上下文）
  --scope <s>    unit | integration | all（默认 all）
  --real         显式真实测试（需人工确认；默认 dry-run）
  -h, --help     显示本帮助
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --task) shift; TASK_ID="${1:-}"; [[ $# -gt 0 ]] && shift || true ;;
    --scope) shift; SCOPE="${1:-all}"; [[ $# -gt 0 ]] && shift || true ;;
    --real) REAL=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) log "[ERR] 未知参数: $1"; usage; exit 2 ;;
  esac
done

if [[ -z "$TASK_ID" ]]; then
  log "[ERR] 必须提供 --task <TASK-ID>"; usage; exit 2
fi
if [[ ! "$SCOPE" =~ ^(unit|integration|all)$ ]]; then
  log "[ERR] --scope 必须为 unit|integration|all"; exit 2
fi

if [[ "$REAL" -eq 1 ]]; then
  log "[WARN] --real 已开启：真实测试（需你人工确认已授权）；默认仍为 mock webhook"
else
  log "[STEP] dry-run 模式（mock webhook，不真实发送、不自动交易）"
fi

if ! command -v pytest >/dev/null 2>&1; then
  log "[ERR] pytest not found —— 请先安装 pytest"; exit 3
fi

OUT_DIR="${OUT_ROOT}/${TASK_ID}"
mkdir -p "$OUT_DIR"
TEST_SUMMARY="${OUT_DIR}/test-summary.json"

# 日志脱敏过滤：任何含 webhook/token/password/secret 的行替换为 [REDACTED]
REDACT_RE='webhook|token|password|secret'
run_redacted() {
  "$@" 2>&1 | sed -E "s/.*(${REDACT_RE}).*/[REDACTED: \1]/Ig" | tee -a "${OUT_DIR}/test.log"
  return "${PIPESTATUS[0]}"
}

# pytest 范围映射
case "$SCOPE" in
  unit) PT_ARGS=(-m "not integration") ;;
  integration) PT_ARGS=(-m "integration") ;;
  all) PT_ARGS=() ;;
esac

log "[STEP] 运行 pytest (scope=${SCOPE})"
set +e
# 仅在 pytest-json-report 插件可用时使用 JSON 报告，否则回退普通 pytest
if pytest --help 2>/dev/null | grep -q -- '--json-report'; then
  run_redacted pytest -q "${PT_ARGS[@]}" --json-report --json-report-file="$TEST_SUMMARY" 2>&1
  RC=$?
else
  log "[WARN] pytest-json-report 插件未安装，回退普通 pytest（不生成 JSON 摘要）"
  run_redacted pytest -q "${PT_ARGS[@]}" 2>&1
  RC=$?
fi
set -e

if [[ "$RC" -eq 0 ]]; then
  log "[OK] 测试通过 (scope=${SCOPE})"
else
  log "[ERR] 测试失败 (scope=${SCOPE}) rc=${RC}"
fi
log "[STEP] 测试摘要: ${TEST_SUMMARY}（含 webhook/token 等已脱敏）"
exit "$RC"
