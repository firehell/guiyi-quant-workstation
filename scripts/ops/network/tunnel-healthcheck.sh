#!/usr/bin/env bash
set -euo pipefail

WEB_TUNNEL_URL="${WEB_TUNNEL_URL:-http://127.0.0.1:18080/}"
API_TUNNEL_URL="${API_TUNNEL_URL:-http://127.0.0.1:18000/api/health}"
WEB_TUNNEL_PORT="${WEB_TUNNEL_PORT:-18080}"
API_TUNNEL_PORT="${API_TUNNEL_PORT:-18000}"

info() { printf '[tunnel-healthcheck] %s\n' "$*"; }
warn() { printf '[tunnel-healthcheck] WARN: %s\n' "$*" >&2; }

check_listen() {
  local port="$1"
  local name="$2"
  if ss -lntp 2>/dev/null | grep -q ":${port} "; then
    printf '  %-18s LISTEN\n' "$name"
    return 0
  fi
  printf '  %-18s NOT_LISTEN\n' "$name"
  return 1
}

# shellcheck source=http-probe.sh
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/http-probe.sh"

main() {
  info "腾讯云 ECS FRP 隧道验收（127.0.0.1:${WEB_TUNNEL_PORT} / ${API_TUNNEL_PORT}）"
  printf '\n=== 隧道端口 ===\n'
  local failures=0
  check_listen "$WEB_TUNNEL_PORT" "tunnel_web" || failures=$((failures + 1))
  check_listen "$API_TUNNEL_PORT" "tunnel_api" || failures=$((failures + 1))

  printf '\n=== 隧道 HTTP ===\n'
  check_http "tunnel_web_http" "$WEB_TUNNEL_URL" tunnel || failures=$((failures + 1))
  check_http "tunnel_api_http" "$API_TUNNEL_URL" tunnel || failures=$((failures + 1))

  printf '\n'
  if [[ "$failures" -gt 0 ]]; then
    info "overall=failed ($failures checks)"
    info "Mac mini: ./scripts/ops/network/local-tunnel-healthcheck.sh && brew services restart frpc"
    info "ECS Nginx: 确认 upstream 为 18080/18000（deploy/nginx/guiyi-quant.conf）"
    exit 1
  fi
  info "overall=passed"
  info "下一步: 设置 HTTPS PUBLIC_BASE_URL，并分别执行未认证 401 与认证 200 的 public-healthcheck"
}

main "$@"
