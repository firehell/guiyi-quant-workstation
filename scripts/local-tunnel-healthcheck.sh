#!/usr/bin/env bash
set -euo pipefail

FRPC_CONFIG="${FRPC_CONFIG:-/usr/local/etc/frp/frpc.toml}"
if [[ ! -f "$FRPC_CONFIG" && -f /opt/homebrew/etc/frp/frpc.toml ]]; then
  FRPC_CONFIG=/opt/homebrew/etc/frp/frpc.toml
fi
if [[ ! -f "$FRPC_CONFIG" && -f "$HOME/.local/etc/frp/frpc.toml" ]]; then
  FRPC_CONFIG="$HOME/.local/etc/frp/frpc.toml"
fi

info() { printf '[local-tunnel-healthcheck] %s\n' "$*"; }
warn() { printf '[local-tunnel-healthcheck] WARN: %s\n' "$*" >&2; }

check_listen() {
  local port="$1"
  local name="$2"
  if command -v lsof >/dev/null 2>&1; then
    if lsof -nP -iTCP:"${port}" -sTCP:LISTEN >/dev/null 2>&1; then
      printf '  %-18s LISTEN\n' "$name"
      return 0
    fi
  elif command -v ss >/dev/null 2>&1; then
    if ss -lntp 2>/dev/null | grep -q ":${port} "; then
      printf '  %-18s LISTEN\n' "$name"
      return 0
    fi
  fi
  printf '  %-18s NOT_LISTEN\n' "$name"
  return 1
}

check_http() {
  local name="$1"
  local url="$2"
  local status time_total
  status="$(curl -sS -m 5 -o /dev/null -w '%{http_code}' "$url" 2>/dev/null || true)"
  status="${status:-000}"
  time_total="$(curl -sS -m 5 -o /dev/null -w '%{time_total}' "$url" 2>/dev/null || true)"
  time_total="${time_total:-0}"
  printf '  %-18s %s  %.3fs  %s\n' "$name" "$status" "$time_total" "$url"
  case "$status" in
    200|204|301|302|401) return 0 ;;
    000) warn "$name 不可达 (Empty reply / connection refused)"; return 1 ;;
    *) warn "$name 异常状态: $status"; return 1 ;;
  esac
}

main() {
  info "Mac mini 本地服务与 FRPC 诊断"
  printf '\n=== 端口监听 ===\n'
  local failures=0
  check_listen 5173 "web_5173" || failures=$((failures + 1))
  check_listen 8000 "api_8000" || failures=$((failures + 1))

  printf '\n=== 本地 HTTP ===\n'
  check_http "web_home" "http://127.0.0.1:5173/" || failures=$((failures + 1))
  check_http "api_health" "http://127.0.0.1:8000/api/health" || failures=$((failures + 1))

  printf '\n=== FRPC 进程 ===\n'
  if pgrep -af frpc >/dev/null 2>&1; then
    pgrep -af frpc | sed 's/^/  /'
  else
    warn "frpc 进程未运行。执行: brew services start frpc"
    failures=$((failures + 1))
  fi

  printf '\n=== FRPC 配置 ===\n'
  if [[ -f "$FRPC_CONFIG" ]]; then
    grep -E '^(serverAddr|serverPort|name|localIP|localPort|remotePort)' "$FRPC_CONFIG" | sed 's/^/  /' || true
    info "配置文件: ${FRPC_CONFIG}"
  else
    warn "未找到 ${FRPC_CONFIG}, 请参考 deploy/frp/frpc.toml.example"
    failures=$((failures + 1))
  fi

  printf '\n'
  if [[ "$failures" -gt 0 ]]; then
    info "overall=failed ($failures checks)"
    info "修复: ./scripts/server-recover.sh --confirm-production-restart；确认本地通过后再人工重启 frpc"
    exit 1
  fi
  info "overall=passed"
  info "下一步: 在腾讯云 ECS 运行 ./scripts/tunnel-healthcheck.sh"
}

main "$@"
