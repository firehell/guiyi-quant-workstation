#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:8000}"
WEB_BASE_URL="${WEB_BASE_URL:-http://127.0.0.1:5173}"
POSTGRES_CONTAINER="guiyi-postgres"
REDIS_CONTAINER="guiyi-redis"
POSTGRES_USER="${POSTGRES_USER:-guiyi}"
POSTGRES_DB="${POSTGRES_DB:-guiyi_quant}"

OUTPUT_JSON=0
ALLOW_DEGRADED=0

usage() {
  cat <<'EOF'
用法: ./scripts/dev-healthcheck.sh [--json] [--no-start] [--allow-degraded]

  --json       输出机器可读 JSON
  --no-start   兼容只读检查语义；本脚本始终不会启动服务
  --allow-degraded
               诊断模式：runtime business status=degraded 时不使脚本失败
EOF
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --json)
        OUTPUT_JSON=1
        shift
        ;;
      --no-start)
        shift
        ;;
      --allow-degraded)
        ALLOW_DEGRADED=1
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        printf '[dev-healthcheck] ERROR: 未知参数: %s\n' "$1" >&2
        usage
        exit 1
        ;;
    esac
  done
}

CHECK_NAMES=()
CHECK_STATUS=()
CHECK_DETAILS=()

record_check() {
  CHECK_NAMES+=("$1")
  CHECK_STATUS+=("$2")
  CHECK_DETAILS+=("$3")
}

run_http_check() {
  local name="$1"
  local url="$2"
  if ! command -v curl >/dev/null 2>&1; then
    record_check "$name" "failed" "curl_missing"
    return 1
  fi
  local status
  status="$(curl -fsS -m 5 -o /dev/null -w '%{http_code}' "$url" 2>/dev/null || true)"
  if [[ "$status" =~ ^[23][0-9][0-9]$ ]]; then
    record_check "$name" "passed" "http_${status}"
    return 0
  fi
  record_check "$name" "failed" "http_${status:-unreachable}"
  return 1
}

run_runtime_health_check() {
  local name="$1"
  local url="$2"
  if ! command -v curl >/dev/null 2>&1 || ! command -v python3 >/dev/null 2>&1; then
    record_check "$name" "failed" "curl_or_python_missing"
    return 1
  fi
  local body status runtime_status
  body="$(mktemp)"
  status="$(curl -sS -m 5 -o "$body" -w '%{http_code}' "$url" 2>/dev/null || true)"
  if [[ ! "$status" =~ ^[23][0-9][0-9]$ ]]; then
    rm -f "$body"
    record_check "$name" "failed" "http_${status:-unreachable}"
    return 1
  fi
  runtime_status="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8")).get("status", "missing"))' "$body" 2>/dev/null || true)"
  rm -f "$body"
  case "$runtime_status" in
    ok)
      record_check "$name" "passed" "http_${status}_business_ok"
      return 0
      ;;
    degraded)
      if [[ "$ALLOW_DEGRADED" -eq 1 ]]; then
        record_check "$name" "passed" "http_${status}_business_degraded_allowed"
        return 0
      fi
      ;;
  esac
  record_check "$name" "failed" "http_${status}_business_${runtime_status:-missing}"
  return 1
}

run_docker_exec_check() {
  local name="$1"
  local command_text="$2"
  if ! command -v docker >/dev/null 2>&1; then
    record_check "$name" "failed" "docker_missing"
    return 1
  fi
  if eval "$command_text" >/dev/null 2>&1; then
    record_check "$name" "passed" "ok"
    return 0
  fi
  record_check "$name" "failed" "command_failed"
  return 1
}

json_check() {
  local comma="$1"
  local index="$2"
  printf '%s{"name":"%s","status":"%s","detail":"%s"}' \
    "$comma" "${CHECK_NAMES[$index]}" "${CHECK_STATUS[$index]}" "${CHECK_DETAILS[$index]}"
}

print_json() {
  local overall="$1"
  printf '{'
  printf '"project_root":"%s",' "$PROJECT_ROOT"
  printf '"api_base_url":"%s",' "$API_BASE_URL"
  printf '"web_base_url":"%s",' "$WEB_BASE_URL"
  printf '"status":"%s",' "$overall"
  printf '"checks":['
  local idx
  for idx in "${!CHECK_NAMES[@]}"; do
    if [[ "$idx" -eq 0 ]]; then
      json_check "" "$idx"
    else
      json_check "," "$idx"
    fi
  done
  printf ']}\n'
}

print_human() {
  local overall="$1"
  printf '[dev-healthcheck] 项目根目录: %s\n' "$PROJECT_ROOT"
  printf '[dev-healthcheck] API: %s\n' "$API_BASE_URL"
  printf '[dev-healthcheck] Web: %s\n' "$WEB_BASE_URL"
  printf '\n'
  local idx
  for idx in "${!CHECK_NAMES[@]}"; do
    printf '  %-18s %-7s %s\n' "${CHECK_NAMES[$idx]}" "${CHECK_STATUS[$idx]}" "${CHECK_DETAILS[$idx]}"
  done
  printf '\n[dev-healthcheck] overall=%s\n' "$overall"
}

main() {
  parse_args "$@"

  local failures=0
  run_http_check "api_healthz" "${API_BASE_URL}/healthz" || failures=$((failures + 1))
  run_http_check "api_health" "${API_BASE_URL}/api/health" || failures=$((failures + 1))
  run_runtime_health_check "runtime_health" "${API_BASE_URL}/api/runtime/health" || failures=$((failures + 1))
  run_http_check "web_home" "${WEB_BASE_URL}/" || failures=$((failures + 1))
  run_docker_exec_check "postgres" "docker exec ${POSTGRES_CONTAINER} pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}" || failures=$((failures + 1))
  run_docker_exec_check "redis" "docker exec ${REDIS_CONTAINER} sh -c 'REDISCLI_AUTH=\"\$REDIS_PASSWORD\" redis-cli ping' | grep -q PONG" || failures=$((failures + 1))

  local overall="passed"
  if [[ "$failures" -gt 0 ]]; then
    overall="failed"
  fi

  if [[ "$OUTPUT_JSON" -eq 1 ]]; then
    print_json "$overall"
  else
    print_human "$overall"
  fi

  if [[ "$failures" -gt 0 ]]; then
    return 1
  fi
}

main "$@"
