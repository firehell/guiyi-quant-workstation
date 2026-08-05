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

check_http() {
  local name="$1"
  local url="$2"
  local status time_total err
  err="$(mktemp)"
  status="$(curl -sS -m 5 -o /dev/null -w '%{http_code}' "$url" 2>"$err" || true)"
  status="${status:-000}"
  time_total="$(curl -sS -m 5 -o /dev/null -w '%{time_total}' "$url" 2>/dev/null || true)"
  time_total="${time_total:-0}"
  printf '  %-18s %s  %.3fs  %s\n' "$name" "$status" "$time_total" "$url"
  if [[ "$status" == "000" ]]; then
    if grep -qi 'Empty reply' "$err" 2>/dev/null; then
      warn "$name Empty reply：FRPS 在听但 Mac mini 5173/8000 无 HTTP 或 frpc localPort 错配"
    elif grep -qi 'Connection refused' "$err" 2>/dev/null; then
      warn "$name Connection refused：隧道未建立，检查 Mac mini frpc"
    else
      warn "$name 不可达: $(head -1 "$err")"
    fi
    rm -f "$err"
    return 1
  fi
  rm -f "$err"
  case "$status" in
    200|204|301|302|401) return 0 ;;
    *) warn "$name 异常状态: $status"; return 1 ;;
  esac
}

main() {
  info "腾讯云 ECS FRP 隧道验收（127.0.0.1:${WEB_TUNNEL_PORT} / ${API_TUNNEL_PORT}）"
  printf '\n=== 隧道端口 ===\n'
  local failures=0
  check_listen "$WEB_TUNNEL_PORT" "tunnel_web" || failures=$((failures + 1))
  check_listen "$API_TUNNEL_PORT" "tunnel_api" || failures=$((failures + 1))

  printf '\n=== 隧道 HTTP ===\n'
  check_http "tunnel_web_http" "$WEB_TUNNEL_URL" || failures=$((failures + 1))
  check_http "tunnel_api_http" "$API_TUNNEL_URL" || failures=$((failures + 1))

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
