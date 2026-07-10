#!/usr/bin/env bash
set -euo pipefail

PUBLIC_BASE_URL="${PUBLIC_BASE_URL:-}"
BASIC_AUTH_USER="${BASIC_AUTH_USER:-}"
BASIC_AUTH_PASS="${BASIC_AUTH_PASS:-}"

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
    warn "$name 上游不可达 (${status:-000})。排查: Mac mini ./scripts/local-tunnel-healthcheck.sh → ECS ./scripts/tunnel-healthcheck.sh → Nginx upstream 18080/18000"
    return 1
  fi
  [[ "$status" == "$expected" ]]
}

main() {
  local expected="401"
  if [[ -n "$BASIC_AUTH_USER" ]]; then
    expected="200"
  fi
  info "HTTPS / Basic Auth Gate"
  check_url web_home / "$expected"
  check_url web_market /market "$expected"
  check_url api_healthz /healthz "$expected"
  check_url api_dominants /api/v1/market/dominants "$expected"
  info "overall=passed"
}

main "$@"
