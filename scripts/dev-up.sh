#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
RUN_DIR="${PROJECT_ROOT}/.run"
PID_DIR="${RUN_DIR}/dev"
LOG_DIR="${RUN_DIR}/logs"

API_DIR="${PROJECT_ROOT}/services/quant-api"
WEB_DIR="${PROJECT_ROOT}/apps/quant-web"

POSTGRES_CONTAINER="guiyi-postgres"
REDIS_CONTAINER="guiyi-redis"

info() { printf '[dev-up] %s\n' "$*"; }
warn() { printf '[dev-up] WARN: %s\n' "$*" >&2; }
fail() { printf '[dev-up] ERROR: %s\n' "$*" >&2; exit 1; }

# 本脚本仅用于本地开发与临时 smoke，不是 FRPC 公网长期运行入口。
# 长期运行使用 deploy/launchd 监督 API、静态 Web 和两个 worker。

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "缺少命令: $1"
}

is_pid_alive() {
  local pid="$1"
  kill -0 "$pid" 2>/dev/null
}

read_pid() {
  local pid_file="$1"
  if [[ -f "$pid_file" ]]; then
    cat "$pid_file"
  fi
}

port_in_use() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"${port}" -sTCP:LISTEN >/dev/null 2>&1
    return $?
  fi
  return 1
}

check_port_available() {
  local port="$1"
  local name="$2"
  local pid_file="$3"
  local existing_pid
  existing_pid="$(read_pid "$pid_file" || true)"
  if [[ -n "${existing_pid:-}" ]] && is_pid_alive "$existing_pid"; then
    return 0
  fi
  if port_in_use "$port"; then
    fail "端口 ${port} 已被占用（${name}），请先停止冲突进程或运行 ./scripts/dev-down.sh"
  fi
}

start_background() {
  local name="$1"
  local pid_file="$2"
  local log_file="$3"
  shift 3

  local existing_pid
  existing_pid="$(read_pid "$pid_file" || true)"
  if [[ -n "${existing_pid:-}" ]] && is_pid_alive "$existing_pid"; then
    warn "${name} 已在运行 (PID ${existing_pid})，跳过启动"
    return 0
  fi
  if [[ -n "${existing_pid:-}" ]]; then
    warn "${name} PID 文件已 stale，安全清理: ${pid_file}"
    rm -f "$pid_file"
  fi

  mkdir -p "$(dirname "$pid_file")" "$(dirname "$log_file")"
  : >"$log_file"

  (
    cd "$PROJECT_ROOT"
    exec "$@"
  ) >>"$log_file" 2>&1 &

  local pid=$!
  disown "$pid" 2>/dev/null || true
  echo "$pid" >"$pid_file"
  sleep 1
  if ! is_pid_alive "$pid"; then
    warn "${name} 启动失败，日志末尾:"
    tail -n 20 "$log_file" >&2 || true
    fail "${name} 启动失败，请查看日志: ${log_file}"
  fi
  info "${name} 已启动 (PID ${pid})，日志: ${log_file}"
}

load_env_files() {
  if [[ -f "${PROJECT_ROOT}/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "${PROJECT_ROOT}/.env"
    set +a
  fi
}

ensure_env_file() {
  if [[ ! -f "${PROJECT_ROOT}/.env" ]]; then
    if [[ -f "${PROJECT_ROOT}/.env.example" ]]; then
      cp "${PROJECT_ROOT}/.env.example" "${PROJECT_ROOT}/.env"
      warn "已从 .env.example 创建 .env，请确认 DATABASE_URL 与 docker-compose 一致"
    else
      fail "未找到 .env 或 .env.example"
    fi
  fi
}

normalize_database_url() {
  local url="$1"
  case "$url" in
    postgresql://*)
      printf 'postgresql+psycopg://%s' "${url#postgresql://}"
      ;;
    postgres://*)
      printf 'postgresql+psycopg://%s' "${url#postgres://}"
      ;;
    *)
      printf '%s' "$url"
      ;;
  esac
}

validate_database_url() {
  load_env_files
  local db_url="${DATABASE_URL:-}"
  db_url="$(normalize_database_url "$db_url")"

  if [[ -z "$db_url" || -z "${POSTGRES_PASSWORD:-}" ]]; then
    fail "DATABASE_URL、POSTGRES_PASSWORD 必须在本地 .env 中显式配置"
  fi
  if [[ -z "${REDIS_PASSWORD:-}" ]]; then
    warn "本地 .env 未设置 REDIS_PASSWORD；本次进程复用 POSTGRES_PASSWORD，生产环境禁止复用"
    export REDIS_PASSWORD="$POSTGRES_PASSWORD"
  fi
  if [[ -z "${REDIS_URL:-}" || "$REDIS_URL" == "redis://127.0.0.1:6379/0" ]]; then
    export REDIS_URL="redis://:${REDIS_PASSWORD}@127.0.0.1:6379/0"
  fi
  if [[ "$db_url" == *"replace-with-"* || "${POSTGRES_PASSWORD}" == replace-with-* || "${REDIS_PASSWORD}" == replace-with-* || "$REDIS_URL" == *"replace-with-"* ]]; then
    fail ".env 仍包含模板占位凭据，请先设置本机随机密码；脚本不会回显凭据"
  fi
  export DATABASE_URL="${db_url}"
  export POSTGRES_USER="${POSTGRES_USER:-guiyi}"
  export POSTGRES_DB="${POSTGRES_DB:-guiyi_quant}"
}

wait_for_container() {
  local name="$1"
  local check_cmd="$2"
  local timeout="${3:-60}"
  local elapsed=0

  info "等待 ${name} 就绪..."
  while (( elapsed < timeout )); do
    if eval "$check_cmd" >/dev/null 2>&1; then
      info "${name} 已就绪"
      return 0
    fi
    sleep 2
    elapsed=$((elapsed + 2))
  done
  fail "${name} 在 ${timeout}s 内未就绪"
}

main() {
  info "项目根目录: ${PROJECT_ROOT}"

  require_cmd docker
  require_cmd uv
  require_cmd pnpm
  require_cmd curl
  docker compose version >/dev/null 2>&1 || fail "需要 Docker Compose v2（docker compose）"

  mkdir -p "$PID_DIR" "$LOG_DIR"

  ensure_env_file
  validate_database_url

  check_port_available 8000 "API" "${PID_DIR}/api.pid"
  check_port_available 5173 "前端" "${PID_DIR}/web.pid"

  info "启动 Docker 基础依赖 (PostgreSQL / Redis)..."
  (
    cd "$PROJECT_ROOT"
    docker compose up -d
  )

  wait_for_container "$POSTGRES_CONTAINER" \
    "docker exec ${POSTGRES_CONTAINER} pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"
  wait_for_container "$REDIS_CONTAINER" \
    "docker exec ${REDIS_CONTAINER} sh -c 'REDISCLI_AUTH=\"\$REDIS_PASSWORD\" redis-cli ping' | grep -q PONG"

  info "安装/同步后端依赖..."
  (
    cd "$API_DIR"
    uv sync
  )

  info "执行数据库迁移..."
  (
    cd "$API_DIR"
    uv run alembic upgrade head
  )

  info "安装/同步前端依赖..."
  (
    cd "$WEB_DIR"
    pnpm install
  )

  start_background "API" "${PID_DIR}/api.pid" "${LOG_DIR}/api.log" \
    bash -lc "cd '${API_DIR}' && uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload"

  start_background "Worker(backtests)" "${PID_DIR}/worker-backtests.pid" "${LOG_DIR}/worker-backtests.log" \
    bash -lc "cd '${API_DIR}' && uv run python -m app.worker backtests"

  start_background "Worker(signals)" "${PID_DIR}/worker-signals.pid" "${LOG_DIR}/worker-signals.log" \
    bash -lc "cd '${API_DIR}' && uv run python -m app.worker signals"

  start_background "前端" "${PID_DIR}/web.pid" "${LOG_DIR}/web.log" \
    bash -lc "cd '${WEB_DIR}' && pnpm dev --host 127.0.0.1 --port 5173"

  info "执行健康检查..."
  local api_ok=0 web_ok=0
  for _ in $(seq 1 30); do
    if curl -sf "http://127.0.0.1:8000/api/health" >/dev/null 2>&1; then
      api_ok=1
      break
    fi
    sleep 1
  done
  for _ in $(seq 1 30); do
    if curl -sf -o /dev/null "http://127.0.0.1:5173" 2>/dev/null; then
      web_ok=1
      break
    fi
    sleep 1
  done

  printf '\n'
  info "========== 归一量化开发环境已启动 =========="
  printf '  前端:       http://127.0.0.1:5173\n'
  printf '  后端 API:   http://127.0.0.1:8000\n'
  printf '  API 文档:   http://127.0.0.1:8000/docs\n'
  printf '\n'
  printf '  进程 PID:\n'
  printf '    API:              %s\n' "$(read_pid "${PID_DIR}/api.pid")"
  printf '    Worker(backtests): %s\n' "$(read_pid "${PID_DIR}/worker-backtests.pid")"
  printf '    Worker(signals):   %s\n' "$(read_pid "${PID_DIR}/worker-signals.pid")"
  printf '    前端:              %s\n' "$(read_pid "${PID_DIR}/web.pid")"
  printf '\n'
  printf '  日志目录:   %s\n' "$LOG_DIR"
  printf '  停止命令:   ./scripts/dev-down.sh\n'
  printf '\n'

  if [[ "$api_ok" -ne 1 ]]; then
    warn "API 健康检查未通过，请查看 ${LOG_DIR}/api.log"
    tail -n 20 "${LOG_DIR}/api.log" >&2 || true
  fi
  if [[ "$web_ok" -ne 1 ]]; then
    warn "前端健康检查未通过，请查看 ${LOG_DIR}/web.log"
    tail -n 20 "${LOG_DIR}/web.log" >&2 || true
  fi

  if [[ "$api_ok" -ne 1 || "$web_ok" -ne 1 ]]; then
    fail "开发环境健康检查未通过（FRPC 隧道将返回 Empty reply）。请修复日志后重试，并执行 brew services restart frpc"
  fi
}

main "$@"
