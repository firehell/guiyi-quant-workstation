#!/usr/bin/env bash
set -euo pipefail

PUBLIC_BASE_URL="${PUBLIC_BASE_URL:-}"
BASIC_AUTH_USER="${BASIC_AUTH_USER:-}"
BASIC_AUTH_PASS="${BASIC_AUTH_PASS:-}"
CHECK_PUBLIC_PORTS="${CHECK_PUBLIC_PORTS:-1}"

info() { printf '[public-healthcheck] %s\n' "$*"; }
warn() { printf '[public-healthcheck] WARN: %s\n' "$*" >&2; }
fail() { printf '[public-healthcheck] ERROR: %s\n' "$*" >&2; exit 1; }

[[ "$PUBLIC_BASE_URL" == https://* ]] || fail "PUBLIC_BASE_URL 必须显式设置为 HTTPS URL"
if [[ -n "$BASIC_AUTH_USER" || -n "$BASIC_AUTH_PASS" ]]; then
  [[ -n "$BASIC_AUTH_USER" && -n "$BASIC_AUTH_PASS" ]] || fail "BASIC_AUTH_USER 与 BASIC_AUTH_PASS 必须同时设置"
fi

check_url() {
  local name="$1" path="$2" expected="$3" url status
  url="${PUBLIC_BASE_URL%/}${path}"
  if [[ -n "$BASIC_AUTH_USER" ]]; then
    status="$(curl -sS --fail-with-body --max-time 15 -u "${BASIC_AUTH_USER}:${BASIC_AUTH_PASS}" -o /dev/null -w '%{http_code}' "$url" 2>/dev/null || true)"
  else
    status="$(curl -sS --max-time 15 -o /dev/null -w '%{http_code}' "$url" 2>/dev/null || true)"
  fi
  printf '  %-20s status=%s expected=%s url=%s\n' "$name" "${status:-000}" "$expected" "$url"
  if [[ "${status:-000}" == "502" || "${status:-000}" == "000" ]]; then
    warn "$name 上游不可达 (${status:-000})。排查: Mac mini ./scripts/ops/network/local-tunnel-healthcheck.sh → ECS ./scripts/ops/network/tunnel-healthcheck.sh → Nginx upstream 18080/18000"
    return 1
  fi
  [[ "$status" == "$expected" ]]
}

check_http_redirect() {
  local http_url status location
  http_url="http://${PUBLIC_BASE_URL#https://}"
  status="$(curl -sS --max-time 15 -o /dev/null -w '%{http_code}' "$http_url" 2>/dev/null || true)"
  location="$(curl -sS --max-time 15 -o /dev/null -w '%{redirect_url}' "$http_url" 2>/dev/null || true)"
  printf '  %-20s status=%s expected=301/308 location=%s\n' "http_redirect" "${status:-000}" "${location:-missing}"
  [[ "$status" == "301" || "$status" == "308" ]] && [[ "$location" == https://* ]]
}

check_websocket() {
  local expected="$1" status auth_args=()
  if [[ -n "$BASIC_AUTH_USER" ]]; then
    auth_args=(-u "${BASIC_AUTH_USER}:${BASIC_AUTH_PASS}")
  fi
  status="$(curl -sS --http1.1 --max-time 5 -o /dev/null -w '%{http_code}' \
    "${auth_args[@]}" \
    -H 'Connection: Upgrade' \
    -H 'Upgrade: websocket' \
    -H 'Sec-WebSocket-Version: 13' \
    -H 'Sec-WebSocket-Key: Z3VpeWktcHVibGljLWhlYWx0aA==' \
    "${PUBLIC_BASE_URL%/}/api/v1/market/ws?series_kind=actual_dominant&symbol=jm&frequency=1m" 2>/dev/null || true)"
  printf '  %-20s status=%s expected=%s\n' "websocket_upgrade" "${status:-000}" "$expected"
  [[ "$status" == "$expected" ]]
}

check_closed_ports() {
  [[ "$CHECK_PUBLIC_PORTS" == "1" ]] || return 0
  local host port failures=0
  command -v python3 >/dev/null 2>&1 || fail "公网端口检查需要 python3"
  command -v nc >/dev/null 2>&1 || fail "公网端口检查需要 nc"
  host="$(python3 -c 'from urllib.parse import urlparse; import sys; print(urlparse(sys.argv[1]).hostname or "")' "$PUBLIC_BASE_URL")"
  [[ -n "$host" ]] || fail "无法从 PUBLIC_BASE_URL 解析主机名"
  for port in 5432 6379 8000 5173 18000 18080; do
    if nc -z -w 3 "$host" "$port" >/dev/null 2>&1; then
      printf '  public_port_%-8s OPEN expected=CLOSED\n' "$port"
      failures=$((failures + 1))
    else
      printf '  public_port_%-8s CLOSED\n' "$port"
    fi
  done
  [[ "$failures" -eq 0 ]]
}

main() {
  local expected="401"
  if [[ -n "$BASIC_AUTH_USER" ]]; then
    expected="200"
  fi
  info "HTTPS / Basic Auth Gate"
  check_http_redirect
  check_url web_home / "$expected"
  check_url web_market /market "$expected"
  check_url api_healthz /healthz "$expected"
  check_url api_dominants /api/v1/market/dominants "$expected"
  if [[ "$expected" == "401" ]]; then
    check_websocket 401
  else
    check_websocket 101
  fi
  check_closed_ports
  info "overall=passed"
}

main "$@"
