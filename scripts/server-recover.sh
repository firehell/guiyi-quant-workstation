#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
API_DIR="${PROJECT_ROOT}/services/quant-api"

info() { printf '[server-recover] %s\n' "$*"; }
warn() { printf '[server-recover] WARN: %s\n' "$*" >&2; }

main() {
  info "项目根目录: ${PROJECT_ROOT}"
  info "诊断当前状态..."
  "${SCRIPT_DIR}/dev-status.sh" || true

  info "停止应用进程（保留 Docker）..."
  "${SCRIPT_DIR}/dev-down.sh" --keep-docker

  if [[ -d "${API_DIR}" ]]; then
    info "执行数据库迁移..."
    (
      cd "${API_DIR}"
      uv run alembic upgrade head
    )
  else
    warn "未找到 ${API_DIR}，跳过 alembic"
  fi

  info "重新启动开发环境..."
  "${SCRIPT_DIR}/dev-up.sh"

  info "本机健康检查..."
  "${SCRIPT_DIR}/dev-healthcheck.sh"

  info "若 Nginx 仍 502，请检查: sudo nginx -t && sudo tail -30 /var/log/nginx/error.log"
  info "公网验收: BASIC_AUTH_USER=... BASIC_AUTH_PASS=... ${SCRIPT_DIR}/public-healthcheck.sh"
}

main "$@"
