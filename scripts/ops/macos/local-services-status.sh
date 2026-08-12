#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
AGENT_DIR="${HOME}/Library/LaunchAgents"
API_LABEL="com.guiyi.quant-api"
labels=(
  com.guiyi.quant-api
  com.guiyi.quant-web
  com.guiyi.quant-live
  com.guiyi.quant-after-market
)
failed=0

plist_root() {
  local label="$1"
  local plist="${AGENT_DIR}/${label}.plist"
  if [[ ! -f "$plist" ]]; then
    printf 'missing'
    return 0
  fi
  plutil -extract EnvironmentVariables.GUIYI_PROJECT_ROOT raw -o - "$plist" 2>/dev/null || printf 'unknown'
}

record_failure() {
  failed=$((failed + 1))
}

printf '[local-services-status] readonly=true\n'
printf '[local-services-status] inspector_repo=%s\n' "$PROJECT_ROOT"

runtime_root="$(plist_root "$API_LABEL")"
printf '[local-services-status] supervised_runtime_root=%s\n' "$runtime_root"

runtime_commit=unknown
runtime_detached=unknown
runtime_clean=unknown
if [[ "$runtime_root" == "missing" || "$runtime_root" == "unknown" || ! -d "$runtime_root" ]]; then
  record_failure
elif git -C "$runtime_root" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  runtime_commit="$(git -C "$runtime_root" rev-parse --short=8 HEAD 2>/dev/null || printf 'unknown')"
  if git -C "$runtime_root" symbolic-ref -q HEAD >/dev/null 2>&1; then
    runtime_detached=false
  else
    runtime_detached=true
  fi
  if [[ -z "$(git -C "$runtime_root" status --porcelain 2>/dev/null)" ]]; then
    runtime_clean=true
  else
    runtime_clean=false
  fi
else
  record_failure
fi
printf '[local-services-status] runtime_commit=%s\n' "$runtime_commit"
printf '[local-services-status] runtime_detached=%s\n' "$runtime_detached"
printf '[local-services-status] runtime_clean=%s\n' "$runtime_clean"
[[ "$runtime_commit" != "unknown" && "$runtime_detached" == "true" && "$runtime_clean" == "true" ]] || record_failure

marker_enabled=false
if [[ "$runtime_root" != "missing" && "$runtime_root" != "unknown" && -f "$runtime_root/.run/market-runtime-enabled" ]]; then
  marker_enabled=true
fi
printf '[local-services-status] market_runtime_enabled=%s\n' "$marker_enabled"

for label in "${labels[@]}"; do
  root="$(plist_root "$label")"
  required=false
  case "$label" in
    com.guiyi.quant-api|com.guiyi.quant-web) required=true ;;
    com.guiyi.quant-live|com.guiyi.quant-after-market) [[ "$marker_enabled" == "true" ]] && required=true ;;
  esac

  if [[ "$root" != "missing" && "$root" != "$runtime_root" ]]; then
    printf '[local-services-status] %s root_mismatch root=%s\n' "$label" "$root"
    record_failure
  elif [[ "$root" == "missing" && "$required" == "true" ]]; then
    printf '[local-services-status] %s missing plist=missing\n' "$label"
    record_failure
    continue
  fi

  if launch_output="$(launchctl print "gui/$UID/$label" 2>/dev/null)"; then
    state="$(printf '%s\n' "$launch_output" | sed -n 's/^[[:space:]]*state = //p' | head -1)"
    state="${state:-unknown}"
    state="${state// /_}"
    printf '[local-services-status] %s loaded state=%s root=%s\n' "$label" "$state" "$root"
    if [[ "$required" == "true" && "$label" != "com.guiyi.quant-after-market" && "$state" != "running" ]]; then
      record_failure
    fi
  else
    printf '[local-services-status] %s missing root=%s\n' "$label" "$root"
    [[ "$required" == "true" ]] && record_failure
  fi
done

check_http_200() {
  local name="$1" url="$2" status
  status="$(curl -sS --max-time 5 -o /dev/null -w '%{http_code}' "$url" 2>/dev/null || true)"
  printf '[local-services-status] health.%s status=%s\n' "$name" "${status:-000}"
  [[ "$status" == "200" ]] || record_failure
}

check_http_200 api http://127.0.0.1:8000/api/health
check_http_200 web http://127.0.0.1:5173/

runtime_payload="$(curl -sS --max-time 5 http://127.0.0.1:8000/api/runtime/health 2>/dev/null || true)"
if python3 -c 'import json, sys; p=json.loads(sys.argv[1]); raise SystemExit(0 if p.get("status") == "ok" and p.get("readonly") is True else 1)' "$runtime_payload" >/dev/null 2>&1; then
  printf '[local-services-status] health.runtime status=ok readonly=true\n'
else
  printf '[local-services-status] health.runtime status=failed\n'
  record_failure
fi

if [[ "$failed" -eq 0 ]]; then
  printf '[local-services-status] overall=passed\n'
  exit 0
fi
printf '[local-services-status] overall=failed failures=%s\n' "$failed"
exit 1
