#!/usr/bin/env bash
# Sourced by both tunnel healthchecks. Each probe records one curl result.
# The caller supplies warn() and may select the ECS tunnel diagnostics.
check_http() {
  local name="$1" url="$2" context="${3:-local}"
  local metrics status time_total extra curl_exit err error
  err="$(mktemp)" || { warn "$name 无法创建探测临时文件"; return 1; }
  if metrics="$(curl -sS -m 5 -o /dev/null -w '%{http_code} %{time_total}' "$url" 2>"$err")"; then
    curl_exit=0
  else
    curl_exit=$?
  fi
  error="$(head -1 "$err")"
  rm -f "$err"
  read -r status time_total extra <<< "$metrics"
  status="${status:-000}"
  time_total="${time_total:-0}"
  if [[ ! "$status" =~ ^[0-9]{3}$ || ! "$time_total" =~ ^[0-9]+([.][0-9]+)?$ || -n "$extra" ]]; then
    warn "$name 无效探测结果 (curl exit=$curl_exit)"
    return 1
  fi
  LC_ALL=C printf '  %-18s %s  %.3fs  %s\n' "$name" "$status" "$time_total" "$url"
  if [[ "$curl_exit" -ne 0 || "$status" == "000" ]]; then
    if [[ "$context" == "tunnel" ]] && grep -qi 'Empty reply' <<< "$error"; then
      warn "$name Empty reply：FRPS 在听但 Mac mini 5173/8000 无 HTTP 或 frpc localPort 错配 (curl exit=$curl_exit)"
    elif [[ "$context" == "tunnel" ]] && grep -qi 'Connection refused' <<< "$error"; then
      warn "$name Connection refused：隧道未建立，检查 Mac mini frpc (curl exit=$curl_exit)"
    else
      warn "$name 不可达 (curl exit=$curl_exit): $error"
    fi
    return 1
  fi
  case "$status" in
    200|204|301|302|401) return 0 ;;
    *) warn "$name 异常状态: $status"; return 1 ;;
  esac
}
