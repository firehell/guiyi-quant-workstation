#!/usr/bin/env bash
set -euo pipefail

# 仅在 Mac mini 显式执行：恢复受监督的本地 5173/8000 与两个 worker。
# 不使用 dev-up、Vite dev 或 uvicorn --reload；不会自动重启 FRPC、部署或发送通知。

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
API_DIR="${PROJECT_ROOT}/services/quant-api"

info() { printf '[server-recover] %s\n' "$*"; }
fail() { printf '[server-recover] ERROR: %s\n' "$*" >&2; exit 1; }

main() {
  [[ "${1:-}" == "--confirm-production-restart" ]] || fail "需要显式参数 --confirm-production-restart"
  info "项目根目录: ${PROJECT_ROOT}"

  info "启动本机 PostgreSQL / Redis..."
  (cd "${PROJECT_ROOT}" && docker compose up -d postgres redis)

  info "执行数据库迁移..."
  (cd "${API_DIR}" && uv run alembic upgrade head)

  info "构建 Web 静态产物..."
  pnpm --dir "${PROJECT_ROOT}/apps/quant-web" build

  info "加载 launchd 监督服务..."
  "${SCRIPT_DIR}/install-local-services.sh" --confirm-load

  info "检查受监督服务与本机健康..."
  "${SCRIPT_DIR}/local-services-status.sh"
  "${SCRIPT_DIR}/dev-healthcheck.sh"

  info "本脚本未重启 FRPC；如隧道异常，由人工执行: brew services restart frpc"
  info "Mac mini 隧道诊断: ${SCRIPT_DIR}/local-tunnel-healthcheck.sh"
  info "腾讯云隧道验收: ${SCRIPT_DIR}/tunnel-healthcheck.sh"
  info "公网验收需显式设置 HTTPS PUBLIC_BASE_URL 和 Basic Auth 环境变量"
}

main "$@"
