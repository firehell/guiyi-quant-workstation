#!/usr/bin/env bash
#
# collect_result.sh — 结果收集与脱敏汇总（COLLAB_PROTOCOL §9）
#
# 行为：
#   - 收集 git diff --stat、改动文件清单、run_tests 报告、plan 结论
#   - 生成 scripts/ai/.out/<task-id>/result_bundle.md（或 .json）
#   - 敏感字段一律脱敏为 [REDACTED]
#
# 护栏：
#   - 不 git push
#   - 不写入 .env / 密钥；结果包中敏感字段一律脱敏
#
# 退出码：
#   0  成功
#   2  参数错误
set -euo pipefail

OUT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/.out"
TS="$(date +%FT%T)"
log() { printf '[%s] %s %s\n' "$1" "$TS" "${2:-}"; }

TASK_ID=""
FORMAT="md"

usage() {
  cat <<EOF
用法: collect_result.sh --task <TASK-ID> [--format md|json]

  --task <ID>    任务单编号
  --format <f>   md | json（默认 md）
  -h, --help     显示本帮助
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --task) shift; TASK_ID="${1:-}"; [[ $# -gt 0 ]] && shift || true ;;
    --format) shift; FORMAT="${1:-md}"; [[ $# -gt 0 ]] && shift || true ;;
    -h|--help) usage; exit 0 ;;
    *) log "[ERR] 未知参数: $1"; usage; exit 2 ;;
  esac
done

if [[ -z "$TASK_ID" ]]; then
  log "[ERR] 必须提供 --task <TASK-ID>"; usage; exit 2
fi
if [[ ! "$FORMAT" =~ ^(md|json)$ ]]; then
  log "[ERR] --format 必须为 md|json"; exit 2
fi

OUT_DIR="${OUT_ROOT}/${TASK_ID}"
mkdir -p "$OUT_DIR"
BUNDLE="${OUT_DIR}/result_bundle.${FORMAT}"

# 脱敏函数：扫描输入，将敏感值替换为 [REDACTED]
REDACT_RE='(token|webhook|password|secret|api[_-]?key|access[_-]?key)[=: ]+[A-Za-z0-9_\-]{6,}'
redact() {
  sed -E "s/${REDACT_RE}/\1=[REDACTED]/Ig"
}

# 收集 git diff --stat（脱敏后写入）
log "[STEP] 收集 git diff --stat"
git diff --stat | redact > "${OUT_DIR}/.diffstat.raw" || true

# 收集改动文件清单
log "[STEP] 收集改动文件清单"
git diff --name-only | redact > "${OUT_DIR}/.changed.files" || true

# 汇总测试报告（若存在）
TEST_SUMMARY="${OUT_DIR}/test-summary.json"
if [[ -f "$TEST_SUMMARY" ]]; then
  log "[STEP] 引入测试摘要: ${TEST_SUMMARY}"
fi

if [[ "$FORMAT" == "md" ]]; then
  {
    echo "# Result Bundle — ${TASK_ID}"
    echo
    echo "生成时间: ${TS}"
    echo
    echo "## Git Diff Stat"
    echo
    echo '```'
    cat "${OUT_DIR}/.diffstat.raw"
    echo '```'
    echo
    echo "## 改动文件清单"
    echo
    echo '```'
    cat "${OUT_DIR}/.changed.files"
    echo '```'
    echo
    echo "## 测试结论"
    echo
    if [[ -f "$TEST_SUMMARY" ]]; then
      echo "- 测试摘要文件: ${TEST_SUMMARY}"
    else
      echo "- 无测试摘要（请先运行 run_tests.sh）"
    fi
    echo
    echo "## 脱敏声明"
    echo
    echo "本结果包中所有 token/webhook/password/secret/api_key 等值均已脱敏为 [REDACTED]。"
  } | redact > "$BUNDLE"
else
  {
    echo "{"
    echo "  \"task_id\": \"${TASK_ID}\","
    echo "  \"generated_at\": \"${TS}\","
    echo "  \"diff_stat\": $(git diff --stat | redact | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))' 2>/dev/null || echo '\"\"'),"
    echo "  \"changed_files\": $(git diff --name-only | redact | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read().splitlines()))' 2>/dev/null || echo '[]'),"
    echo "  \"test_summary\": \"${TEST_SUMMARY}\""
    echo "}"
  } | redact > "$BUNDLE"
fi

log "[OK] 结果包已生成: ${BUNDLE}"
log "[STEP] 脱敏校验（不应出现真实密钥值）"
if grep -iqE "${REDACT_RE}" "$BUNDLE" 2>/dev/null; then
  log "[ERR] 结果包仍含未脱敏敏感字段，请检查 redact 规则"
  exit 1
fi
log "[OK] 脱敏校验通过"
exit 0
