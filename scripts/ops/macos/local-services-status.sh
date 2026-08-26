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
  local label="$1" key="$2"
  local plist="${AGENT_DIR}/${label}.plist"
  if [[ ! -f "$plist" ]]; then
    printf 'missing'
    return 0
  fi
  plutil -extract "EnvironmentVariables.${key}" raw -o - "$plist" 2>/dev/null || printf 'missing'
}

record_failure() {
  failed=$((failed + 1))
}

launch_value() {
  local output="$1" key="$2"
  printf '%s\n' "$output" | sed -n "s/^[[:space:]]*${key} => //p" | head -1
}

notification_config_valid() {
  local path="$1"
  python3 - "$path" <<'PY'
import json
import os
import re
import stat
import sys

path = sys.argv[1]
try:
    parent = os.lstat(os.path.dirname(path))
    metadata = os.lstat(path)
    if not stat.S_ISDIR(parent.st_mode) or stat.S_IMODE(parent.st_mode) != 0o700:
        raise ValueError
    if parent.st_uid != os.getuid() or not stat.S_ISREG(metadata.st_mode):
        raise ValueError
    if stat.S_IMODE(metadata.st_mode) != 0o600 or metadata.st_uid != os.getuid():
        raise ValueError
    payload = json.load(open(path, encoding="utf-8"))
    if set(payload) != {"schema_version", "transport", "transport_config"}:
        raise ValueError
    if payload["schema_version"] != 1 or type(payload["schema_version"]) is not int:
        raise ValueError
    if payload["transport"] != "pushplus":
        raise ValueError
    config = payload["transport_config"]
    if not isinstance(config, dict) or set(config) != {"message_token", "htdy_topic"}:
        raise ValueError
    token = config["message_token"]
    topic = config["htdy_topic"]
    if not isinstance(token, str) or re.fullmatch(r"[A-Za-z0-9]{32}", token) is None:
        raise ValueError
    if not isinstance(topic, str) or not 1 <= len(topic) <= 128 or topic.strip() != topic:
        raise ValueError
    if any(ord(character) < 32 or ord(character) == 127 for character in topic):
        raise ValueError
except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
    raise SystemExit(1)
PY
}

printf '[local-services-status] readonly=true\n'
printf '[local-services-status] inspector_repo=%s\n' "$PROJECT_ROOT"
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

pushplus_present=false
if [[ "$runtime_root" != "missing" && "$runtime_root" != "unknown" ]]; then
  pushplus_path="$runtime_root/services/quant-api/app/alerts/pushplus.py"
  [[ -f "$pushplus_path" && ! -L "$pushplus_path" ]] && pushplus_present=true
fi
notification_channel=unknown
if [[ "$pushplus_present" == "true" ]]; then
  notification_channel=pushplus
fi
printf '[local-services-status] alert.notification_channel=%s\n' "$notification_channel"
if [[ "$notification_channel" == "pushplus" ]]; then
  notification_identity_valid=true
  if api_launch_output="$(launchctl print "gui/$UID/com.guiyi.quant-api" 2>/dev/null)"; then
    api_loaded=true
  else
    api_loaded=false
  fi
  if alert_launch_output="$(launchctl print "gui/$UID/com.guiyi.quant-alert" 2>/dev/null)"; then
    alert_loaded=true
  else
    alert_loaded=false
  fi
  key=GUIYI_ALERT_NOTIFICATION_CONFIG_PATH
  api_value="$(plist_value com.guiyi.quant-api "$key")"
  alert_value="$(plist_value com.guiyi.quant-alert "$key")"
  if [[ "$api_value" == "missing" || "$alert_value" == "missing" || "$api_value" != "$alert_value" ]]; then
    notification_identity_valid=false
  fi
  if [[ "$api_loaded" != "true" || "$(launch_value "$api_launch_output" "$key")" != "$api_value" ]]; then
    notification_identity_valid=false
  fi
  if [[ "$alert_loaded" == "true" && "$(launch_value "$alert_launch_output" "$key")" != "$alert_value" ]]; then
    notification_identity_valid=false
  fi
  if [[ "$alert_marker_enabled" == "true" && "$alert_loaded" != "true" ]]; then
    notification_identity_valid=false
  fi
  notification_config_status=missing
  if [[ "$alert_value" != "missing" && -e "$alert_value" ]]; then
    notification_config_status=invalid
    if notification_config_valid "$alert_value" 2>/dev/null; then
      notification_config_status=ready
    fi
  fi
  if [[ "$notification_identity_valid" != "true" ]]; then
    notification_config_status=invalid
    record_failure
  fi
  printf '[local-services-status] external.pushplus_config=%s\n' "$notification_config_status"
  printf '[local-services-status] alert.notification_audience_count=2\n'
  if [[ "$alert_marker_enabled" == "true" \
    && "$notification_config_status" != "ready" ]]; then
    record_failure
  fi
fi
if [[ "$alert_marker_enabled" == "true" && "$notification_channel" == "unknown" ]]; then
  record_failure
fi

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
