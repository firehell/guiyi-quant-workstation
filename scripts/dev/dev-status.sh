#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PID_DIR="${PROJECT_ROOT}/.run/dev"
LOG_DIR="${PROJECT_ROOT}/.run/logs"

POSTGRES_CONTAINER="guiyi-postgres"
REDIS_CONTAINER="guiyi-redis"

OUTPUT_JSON=0

usage() {
  cat <<'EOF'
用法: ./scripts/dev/dev-status.sh [--json]

  --json   输出机器可读 JSON
EOF
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --json)
        OUTPUT_JSON=1
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        printf '[dev-status] ERROR: 未知参数: %s\n' "$1" >&2
        usage
        exit 1
        ;;
    esac
  done
}

is_pid_alive() {
  local pid="$1"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

read_pid() {
  local pid_file="$1"
  if [[ -f "$pid_file" ]]; then
    tr -d '[:space:]' <"$pid_file"
  fi
}

process_command() {
  local pid="$1"
  ps -p "$pid" -o command= 2>/dev/null || true
}

pid_state() {
  local pid_file="$1"
  local expected="$2"
  local pid command
  pid="$(read_pid "$pid_file" || true)"
  if [[ -z "${pid:-}" ]]; then
    printf 'missing'
    return 0
  fi
  if ! is_pid_alive "$pid"; then
    printf 'stale'
    return 0
  fi
  command="$(process_command "$pid")"
  if [[ "$command" == *"$PROJECT_ROOT"* && "$command" == *"$expected"* ]]; then
    printf 'running'
    return 0
  fi
  printf 'foreign'
}

port_state() {
  local port="$1"
  if ! command -v lsof >/dev/null 2>&1; then
    printf 'unknown'
    return 0
  fi
  if lsof -nP -iTCP:"${port}" -sTCP:LISTEN >/dev/null 2>&1; then
    printf 'listening'
    return 0
  fi
  printf 'closed'
}

container_state() {
  local name="$1"
  if ! command -v docker >/dev/null 2>&1; then
    printf 'docker_missing'
    return 0
  fi
  local running
  running="$(docker inspect -f '{{.State.Running}}' "$name" 2>/dev/null || true)"
  case "$running" in
    true) printf 'running' ;;
    false) printf 'stopped' ;;
    *) printf 'missing' ;;
  esac
}

service_pid() {
  read_pid "$1" || true
}

print_service_human() {
  local label="$1"
  local pid_file="$2"
  local expected="$3"
  local port="$4"
  local log_file="$5"
  local state pid port_status
  state="$(pid_state "$pid_file" "$expected")"
  pid="$(service_pid "$pid_file")"
  if [[ -n "$port" ]]; then
    port_status="$(port_state "$port")"
  else
    port_status="-"
  fi
  printf '  %-18s pid=%-8s state=%-8s port=%-10s log=%s\n' \
    "$label" "${pid:-"-"}" "$state" "$port_status" "$log_file"
}

print_service_json() {
  local comma="$1"
  local name="$2"
  local pid_file="$3"
  local expected="$4"
  local port="$5"
  local log_file="$6"
  local state pid port_status
  state="$(pid_state "$pid_file" "$expected")"
  pid="$(service_pid "$pid_file")"
  if [[ -n "$port" ]]; then
    port_status="$(port_state "$port")"
  else
    port_status="not_applicable"
  fi
  printf '%s{"name":"%s","pid":"%s","state":"%s","port":"%s","port_status":"%s","pid_file":"%s","log_file":"%s"}' \
    "$comma" "$name" "${pid:-}" "$state" "${port:-}" "$port_status" "$pid_file" "$log_file"
}

print_json() {
  printf '{'
  printf '"project_root":"%s",' "$PROJECT_ROOT"
  printf '"pid_dir":"%s",' "$PID_DIR"
  printf '"log_dir":"%s",' "$LOG_DIR"
  printf '"services":['
  print_service_json "" "api" "${PID_DIR}/api.pid" "uvicorn app.main:app" "8000" "${LOG_DIR}/api.log"
  print_service_json "," "worker-backtests" "${PID_DIR}/worker-backtests.pid" "app.worker backtests" "" "${LOG_DIR}/worker-backtests.log"
  print_service_json "," "worker-signals" "${PID_DIR}/worker-signals.pid" "app.worker signals" "" "${LOG_DIR}/worker-signals.log"
  print_service_json "," "web" "${PID_DIR}/web.pid" "pnpm dev" "5173" "${LOG_DIR}/web.log"
  printf '],'
  printf '"ports":{'
  printf '"api_8000":"%s",' "$(port_state 8000)"
  printf '"web_5173":"%s",' "$(port_state 5173)"
  printf '"postgres_5432":"%s",' "$(port_state 5432)"
  printf '"redis_6379":"%s"' "$(port_state 6379)"
  printf '},'
  printf '"containers":{'
  printf '"postgres":"%s",' "$(container_state "$POSTGRES_CONTAINER")"
  printf '"redis":"%s"' "$(container_state "$REDIS_CONTAINER")"
  printf '}'
  printf '}\n'
}

print_human() {
  printf '[dev-status] 项目根目录: %s\n' "$PROJECT_ROOT"
  printf '[dev-status] PID 目录: %s\n' "$PID_DIR"
  printf '[dev-status] 日志目录: %s\n' "$LOG_DIR"
  printf '\n进程:\n'
  print_service_human "API" "${PID_DIR}/api.pid" "uvicorn app.main:app" "8000" "${LOG_DIR}/api.log"
  print_service_human "Worker(backtests)" "${PID_DIR}/worker-backtests.pid" "app.worker backtests" "" "${LOG_DIR}/worker-backtests.log"
  print_service_human "Worker(signals)" "${PID_DIR}/worker-signals.pid" "app.worker signals" "" "${LOG_DIR}/worker-signals.log"
  print_service_human "Web" "${PID_DIR}/web.pid" "pnpm dev" "5173" "${LOG_DIR}/web.log"
  printf '\n端口:\n'
  printf '  API 8000:      %s\n' "$(port_state 8000)"
  printf '  Web 5173:      %s\n' "$(port_state 5173)"
  printf '  PostgreSQL:    %s\n' "$(port_state 5432)"
  printf '  Redis:         %s\n' "$(port_state 6379)"
  printf '\nDocker:\n'
  printf '  %s: %s\n' "$POSTGRES_CONTAINER" "$(container_state "$POSTGRES_CONTAINER")"
  printf '  %s:    %s\n' "$REDIS_CONTAINER" "$(container_state "$REDIS_CONTAINER")"
}

main() {
  parse_args "$@"
  if [[ "$OUTPUT_JSON" -eq 1 ]]; then
    print_json
  else
    print_human
  fi
}

main "$@"
