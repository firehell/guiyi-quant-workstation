#!/usr/bin/env bash
set -euo pipefail

PUBLIC_BASE_URL="${PUBLIC_BASE_URL:-http://124.221.95.93}"
BASIC_AUTH_USER="${BASIC_AUTH_USER:-}"
BASIC_AUTH_PASS="${BASIC_AUTH_PASS:-}"

info() { printf '[public-healthcheck] %s\n' "$*"; }
warn() { printf '[public-healthcheck] WARN: %s\n' "$*" >&2; }

curl_auth_args=()
if [[ -n "$BASIC_AUTH_USER" && -n "$BASIC_AUTH_PASS" ]]; then
  curl_auth_args=(-u "${BASIC_AUTH_USER}:${BASIC_AUTH_PASS}")
elif [[ -n "$BASIC_AUTH_USER" || -n "$BASIC_AUTH_PASS" ]]; then
  warn "BASIC_AUTH_USER 与 BASIC_AUTH_PASS 需同时设置，否则只能检测 401"
fi

check_url() {
  local name="$1"
  local path="$2"
  local url="${PUBLIC_BASE_URL%/}${path}"
  local status time_total

  if ! command -v curl >/dev/null 2>&1; then
    warn "缺少 curl"
    return 1
  fi

  local raw
  if [[ ${#curl_auth_args[@]} -gt 0 ]]; then
    raw="$(curl -sS -m 15 -o /dev/null -w '%{http_code} %{time_total}' "${curl_auth_args[@]}" "$url" 2>/dev/null || echo "000 0")"
  else
    raw="$(curl -sS -m 15 -o /dev/null -w '%{http_code} %{time_total}' "$url" 2>/dev/null || echo "000 0")"
  fi
  status="${raw%% *}"
  time_total="${raw#* }"

  printf '  %-22s %s  %.3fs  %s\n' "$name" "$status" "$time_total" "$url"

  case "$status" in
    200|204|301|302)
      return 0
      ;;
    401)
      if [[ ${#curl_auth_args[@]} -eq 0 ]]; then
        warn "$name 返回 401（需 Basic Auth：设置 BASIC_AUTH_USER / BASIC_AUTH_PASS）"
        return 0
      fi
      warn "$name 认证失败，请检查 BASIC_AUTH_USER / BASIC_AUTH_PASS"
      return 1
      ;;
    502|000)
      warn "$name 上游不可达 ($status)。请在服务器执行: ./scripts/dev-status.sh && ./scripts/server-recover.sh"
      return 1
      ;;
    *)
      warn "$name 异常状态码: $status"
      return 1
      ;;
  esac
}

main() {
  info "公网入口: ${PUBLIC_BASE_URL}"
  if [[ ${#curl_auth_args[@]} -gt 0 ]]; then
    info "使用 Basic Auth 用户: ${BASIC_AUTH_USER}"
  else
    info "未配置 Basic Auth，401 视为 Nginx 存活"
  fi
  printf '\n'

  local failures=0
  check_url "web_home" "/" || failures=$((failures + 1))
  check_url "web_market" "/market" || failures=$((failures + 1))
  check_url "api_healthz" "/healthz" || failures=$((failures + 1))
  check_url "api_dominants" "/api/v1/market/dominants" || failures=$((failures + 1))

  printf '\n'
  if [[ "$failures" -gt 0 ]]; then
    info "overall=failed (${failures} checks)"
    exit 1
  fi
  info "overall=passed"
}

main "$@"
