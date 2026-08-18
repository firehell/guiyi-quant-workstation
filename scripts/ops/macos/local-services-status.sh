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
  com.guiyi.quant-alert
)
failed=0
PINNED_WECHAT_COURIER_COMMIT="981bd14e238302b2a0e206cb5f28e8e2505bb874"

plist_root() {
  local label="$1"
  local plist="${AGENT_DIR}/${label}.plist"
  if [[ ! -f "$plist" ]]; then
    printf 'missing'
    return 0
  fi
  plutil -extract EnvironmentVariables.GUIYI_PROJECT_ROOT raw -o - "$plist" 2>/dev/null || printf 'unknown'
}

plist_value() {
  local label="$1" key="$2" plist="${AGENT_DIR}/${label}.plist"
  if [[ ! -f "$plist" ]]; then
    printf 'missing'
    return 0
  fi
  plutil -extract "EnvironmentVariables.${key}" raw -o - "$plist" 2>/dev/null || printf 'missing'
}

record_failure() {
  failed=$((failed + 1))
}

printf '[local-services-status] readonly=true\n'
printf '[local-services-status] inspector_repo=%s\n' "$PROJECT_ROOT"
wechat_courier_status=not_installed
wechat_courier_root="$(plist_value com.guiyi.quant-alert GUIYI_WECHAT_COURIER_ROOT)"
if [[ "$wechat_courier_root" != "missing" && -e "$wechat_courier_root" ]]; then
  wechat_courier_status=invalid
  if [[ -d "$wechat_courier_root/source/.git" \
    && -f "$wechat_courier_root/source/wechat_courier.py" \
    && -x "$wechat_courier_root/venv/bin/python" \
    && -d "$wechat_courier_root/runtime" \
    && -d "$wechat_courier_root/tmp" \
    && -d "$wechat_courier_root/cache/clang" ]]; then
    courier_commit="$(/usr/bin/git -C "$wechat_courier_root/source" rev-parse HEAD 2>/dev/null || true)"
    courier_dirty="$(/usr/bin/git -C "$wechat_courier_root/source" status --porcelain 2>/dev/null || printf 'invalid')"
    courier_head="$(tr -d '\n' < "$wechat_courier_root/source/.git/HEAD" 2>/dev/null || true)"
    private_modes=true
    expected_owner="$(id -u)"
    for private_directory in "$wechat_courier_root" "$wechat_courier_root/runtime" "$wechat_courier_root/tmp" "$wechat_courier_root/cache/clang"; do
      if [[ "$(stat -f '%Lp' "$private_directory" 2>/dev/null || true)" != "700" \
        || "$(stat -f '%u' "$private_directory" 2>/dev/null || true)" != "$expected_owner" ]]; then
        private_modes=false
      fi
    done
    if [[ "$courier_commit" == "$PINNED_WECHAT_COURIER_COMMIT" \
      && "$courier_head" == "$PINNED_WECHAT_COURIER_COMMIT" \
      && -z "$courier_dirty" && "$private_modes" == "true" ]]; then
      wechat_courier_status=ready
    fi
  fi
fi
printf '[local-services-status] external.wechat_courier.commit=%s\n' "$PINNED_WECHAT_COURIER_COMMIT"
printf '[local-services-status] external.wechat_courier.status=%s\n' "$wechat_courier_status"
printf '[local-services-status] alert.notification_channel=wechat-courier\n'
printf '[local-services-status] alert.notification_group_alias=primary_alert_group\n'

runtime_root="$(plist_root "$API_LABEL")"
printf '[local-services-status] supervised_runtime_root=%s\n' "$runtime_root"

runtime_checkout_commit=unknown
runtime_checkout_detached=unknown
runtime_checkout_clean=unknown
if [[ "$runtime_root" == "missing" || "$runtime_root" == "unknown" || ! -d "$runtime_root" ]]; then
  record_failure
elif git -C "$runtime_root" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  runtime_checkout_commit="$(git -C "$runtime_root" rev-parse HEAD 2>/dev/null || printf 'unknown')"
  if git -C "$runtime_root" symbolic-ref -q HEAD >/dev/null 2>&1; then
    runtime_checkout_detached=false
  else
    runtime_checkout_detached=true
  fi
  if [[ -z "$(git -C "$runtime_root" status --porcelain 2>/dev/null)" ]]; then
    runtime_checkout_clean=true
  else
    runtime_checkout_clean=false
  fi
else
  record_failure
fi
printf '[local-services-status] runtime_checkout_commit=%s\n' "${runtime_checkout_commit:0:8}"
printf '[local-services-status] runtime_checkout_detached=%s\n' "$runtime_checkout_detached"
printf '[local-services-status] runtime_checkout_clean=%s\n' "$runtime_checkout_clean"
[[ "$runtime_checkout_commit" != "unknown" && "$runtime_checkout_detached" == "true" && "$runtime_checkout_clean" == "true" ]] || record_failure

marker_enabled=false
if [[ "$runtime_root" != "missing" && "$runtime_root" != "unknown" && -f "$runtime_root/.run/market-runtime-enabled" ]]; then
  marker_enabled=true
fi
printf '[local-services-status] market_runtime_enabled=%s\n' "$marker_enabled"

alert_marker_enabled=false
if [[ "$runtime_root" != "missing" && "$runtime_root" != "unknown" && -f "$runtime_root/.run/alert-runtime-enabled" ]]; then
  alert_marker_enabled=true
fi
printf '[local-services-status] alert_runtime_enabled=%s\n' "$alert_marker_enabled"

execution_review_roll=disabled
execution_review_roll_marker="$runtime_root/.run/execution-review-roll-enabled"
if [[ "$runtime_root" != "missing" && "$runtime_root" != "unknown" && ( -e "$execution_review_roll_marker" || -L "$execution_review_roll_marker" ) ]]; then
  if [[ -f "$execution_review_roll_marker" && ! -L "$execution_review_roll_marker" ]] \
    && [[ "$(stat -f '%Lp' "$execution_review_roll_marker" 2>/dev/null || printf 'unknown')" == "600" ]] \
    && cmp -s "$execution_review_roll_marker" <(printf 'enabled\n'); then
    execution_review_roll=enabled
  else
    execution_review_roll=invalid
    record_failure
  fi
fi
printf '[local-services-status] execution_review_roll=%s\n' "$execution_review_roll"

for label in "${labels[@]}"; do
  root="$(plist_root "$label")"
  required=false
  case "$label" in
    com.guiyi.quant-api|com.guiyi.quant-web) required=true ;;
    com.guiyi.quant-live|com.guiyi.quant-after-market) [[ "$marker_enabled" == "true" ]] && required=true ;;
    com.guiyi.quant-alert) [[ "$alert_marker_enabled" == "true" ]] && required=true ;;
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
    loaded_root="$(printf '%s\n' "$launch_output" | sed -n 's/^[[:space:]]*GUIYI_PROJECT_ROOT => //p' | head -1)"
    loaded_root="${loaded_root:-unknown}"
    loaded_commit="$(printf '%s\n' "$launch_output" | sed -n 's/^[[:space:]]*GUIYI_RUNTIME_COMMIT => //p' | head -1)"
    loaded_commit="${loaded_commit:-unknown}"
    printf '[local-services-status] %s loaded state=%s root=%s loaded_commit=%s\n' "$label" "$state" "$loaded_root" "${loaded_commit:0:8}"
    if [[ "$loaded_root" != "$runtime_root" ]]; then
      printf '[local-services-status] %s loaded_root_mismatch configured_root=%s\n' "$label" "$root"
      record_failure
    fi
    if [[ "$loaded_commit" != "$runtime_checkout_commit" ]]; then
      printf '[local-services-status] %s commit_mismatch checkout_commit=%s loaded_commit=%s\n' "$label" "${runtime_checkout_commit:0:8}" "${loaded_commit:0:8}"
      record_failure
    fi
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
