#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PID_DIR="${PROJECT_ROOT}/.run/dev"

KEEP_DOCKER=0

info() { printf '[dev-down] %s\n' "$*"; }
warn() { printf '[dev-down] WARN: %s\n' "$*" >&2; }

usage() {
  cat <<'EOF'
用法: ./scripts/dev-down.sh [--keep-docker]

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

stop_pid_file() {
  local name="$1"
  local pid_file="$2"

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

  info "${name}: 停止进程 ${pid}..."
  kill -TERM "$pid" 2>/dev/null || true

  local waited=0
  while is_pid_alive "$pid" && (( waited < 10 )); do
    sleep 1
    waited=$((waited + 1))
  done

  if is_pid_alive "$pid"; then
    warn "${name}: 进程 ${pid} 未响应 TERM，发送 KILL"
    kill -KILL "$pid" 2>/dev/null || true
  fi

  rm -f "$pid_file"
  info "${name}: 已停止"
}

main() {
  parse_args "$@"

  info "停止归一量化开发环境..."

  stop_pid_file "前端" "${PID_DIR}/web.pid"
  stop_pid_file "Worker(signals)" "${PID_DIR}/worker-signals.pid"
  stop_pid_file "Worker(backtests)" "${PID_DIR}/worker-backtests.pid"
  stop_pid_file "API" "${PID_DIR}/api.pid"

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
