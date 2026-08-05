#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

info() { printf '[post-reboot-verify] %s\n' "$*"; }
warn() { printf '[post-reboot-verify] WARN: %s\n' "$*" >&2; }

load_env_files() {
  if [[ -f "${PROJECT_ROOT}/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "${PROJECT_ROOT}/.env"
    set +a
  fi
  if [[ -z "${REDIS_PASSWORD:-}" && -n "${POSTGRES_PASSWORD:-}" ]]; then
    export REDIS_PASSWORD="${POSTGRES_PASSWORD}"
  fi
}

ensure_infra_containers() {
  if ! command -v docker >/dev/null 2>&1; then
    warn "未找到 docker 命令"
    return 1
  fi
  if ! docker info >/dev/null 2>&1; then
    warn "Docker daemon 未运行；请先启动 Docker Desktop，或确认 Settings -> General -> Start Docker Desktop when you log in 已开启"
    return 1
  fi
  info "Docker daemon: running"

  local running_count
  running_count="$(docker ps --filter "name=guiyi-postgres" --filter "name=guiyi-redis" --format '{{.Names}}' | wc -l | tr -d ' ')"
  if [[ "$running_count" -ge 2 ]]; then
    info "PostgreSQL / Redis 容器已在运行，跳过 docker compose up"
    return 0
  fi

  load_env_files
  if [[ -z "${POSTGRES_PASSWORD:-}" || -z "${REDIS_PASSWORD:-}" ]]; then
    warn "本地 .env 缺少 POSTGRES_PASSWORD / REDIS_PASSWORD，无法启动 docker compose"
    return 1
  fi
  (cd "${PROJECT_ROOT}" && docker compose up -d postgres redis)
}

main() {
  info "项目根目录: ${PROJECT_ROOT}"
  ensure_infra_containers

  "${SCRIPT_DIR}/local-services-status.sh"
  "${PROJECT_ROOT}/scripts/dev/dev-status.sh" --json
  "${PROJECT_ROOT}/scripts/dev/dev-healthcheck.sh" --json --no-start
}

main "$@"
