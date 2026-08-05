#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PID_DIR="${PROJECT_ROOT}/.run/dev"

KEEP_DOCKER=0

info() { printf '[dev-down] %s\n' "$*"; }
warn() { printf '[dev-down] WARN: %s\n' "$*" >&2; }
fail() { printf '[dev-down] ERROR: %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<'EOF'
用法: ./scripts/dev/dev-down.sh [--keep-docker]

  --keep-docker   仅停止应用进程，保留 PostgreSQL / Redis 容器运行
EOF
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --keep-docker)
        KEEP_DOCKER=1
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        warn "未知参数: $1"
        usage
        exit 1
        ;;
    esac
  done
}

is_pid_alive() {
  local pid="$1"
  kill -0 "$pid" 2>/dev/null
}

process_command() {
  local pid="$1"
  ps -p "$pid" -o command= 2>/dev/null || true
}

pid_matches_service() {
  local pid="$1"
  local expected="$2"
  local command
  command="$(process_command "$pid")"
  [[ "$command" == *"$PROJECT_ROOT"* && "$command" == *"$expected"* ]]
}

child_pids() {
  local parent_pid="$1"
  if command -v pgrep >/dev/null 2>&1; then
    pgrep -P "$parent_pid" 2>/dev/null || true
    return 0
  fi
  ps -eo pid=,ppid= 2>/dev/null | awk -v parent="$parent_pid" '$2 == parent { print $1 }'
}

collect_process_tree() {
  local parent_pid="$1"
  local child_pid
  while IFS= read -r child_pid; do
    [[ -n "$child_pid" ]] || continue
    collect_process_tree "$child_pid"
  done < <(child_pids "$parent_pid")
  printf '%s\n' "$parent_pid"
}

signal_process_tree() {
  local signal="$1"
  shift
  local process_pid
  for process_pid in "$@"; do
    is_pid_alive "$process_pid" || continue
    kill "-${signal}" "$process_pid" 2>/dev/null || true
  done
}

tree_is_alive() {
  local process_pid
  for process_pid in "$@"; do
    if is_pid_alive "$process_pid"; then
      return 0
    fi
  done
  return 1
}

stop_pid_file() {
  local name="$1"
  local pid_file="$2"
  local expected="$3"

  if [[ ! -f "$pid_file" ]]; then
    info "${name}: 未找到 PID 文件，跳过"
    return 0
  fi

  local pid
  pid="$(cat "$pid_file")"
  if [[ -z "$pid" ]]; then
    rm -f "$pid_file"
    return 0
  fi

  if ! is_pid_alive "$pid"; then
    info "${name}: 进程 ${pid} 已不存在"
    rm -f "$pid_file"
    return 0
  fi

  if ! pid_matches_service "$pid" "$expected"; then
    warn "${name}: PID ${pid} 不像本项目服务，拒绝停止"
    warn "${name}: PID 文件: ${pid_file}"
    warn "${name}: 当前命令: $(process_command "$pid")"
    fail "请人工确认该 PID 后再处理，避免误杀非本项目进程"
  fi

  local tree_output
  tree_output="$(collect_process_tree "$pid")"
  local process_tree=()
  local process_pid
  while IFS= read -r process_pid; do
    [[ -n "$process_pid" ]] && process_tree+=("$process_pid")
  done <<<"$tree_output"

  info "${name}: 停止进程树 ${pid} (${#process_tree[@]} processes)..."
  signal_process_tree TERM "${process_tree[@]}"

  local waited=0
  while tree_is_alive "${process_tree[@]}" && (( waited < 10 )); do
    sleep 1
    waited=$((waited + 1))
  done

  if tree_is_alive "${process_tree[@]}"; then
    warn "${name}: 进程树 ${pid} 未完全响应 TERM，发送 KILL"
    signal_process_tree KILL "${process_tree[@]}"
  fi

  rm -f "$pid_file"
  info "${name}: 已停止"
}

main() {
  parse_args "$@"

  info "停止归一量化开发环境..."

  stop_pid_file "前端" "${PID_DIR}/web.pid" "pnpm dev"
  stop_pid_file "Worker(signals)" "${PID_DIR}/worker-signals.pid" "app.worker signals"
  stop_pid_file "Worker(backtests)" "${PID_DIR}/worker-backtests.pid" "app.worker backtests"
  stop_pid_file "API" "${PID_DIR}/api.pid" "uvicorn app.main:app"

  if [[ "$KEEP_DOCKER" -eq 1 ]]; then
    info "保留 Docker 容器运行 (--keep-docker)"
  else
    if command -v docker >/dev/null 2>&1; then
      info "停止 Docker 基础依赖..."
      (
        cd "$PROJECT_ROOT"
        docker compose down
      )
    else
      warn "未找到 docker 命令，跳过 docker compose down"
    fi
  fi

  info "开发环境已停止"
}

main "$@"
