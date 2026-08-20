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

manifest_value() {
  local manifest="$1" key="$2"
  python3 - "$manifest" "$key" <<'PY'
import json
import sys

try:
    value = json.load(open(sys.argv[1], encoding="utf-8"))[sys.argv[2]]
    if not isinstance(value, str) or not value or any(ord(character) < 32 for character in value):
        raise ValueError
    print(value)
except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
    raise SystemExit(1)
PY
}

command_version_matches() {
  local executable="$1" expected="$2"
  python3 - "$executable" "$expected" <<'PY'
import subprocess
import sys

try:
    result = subprocess.run(
        [sys.argv[1], "--version"],
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
        env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
    )
except (OSError, subprocess.SubprocessError):
    raise SystemExit(1)
raise SystemExit(0 if result.returncode == 0 and result.stdout.strip() == sys.argv[2] else 1)
PY
}

json_version_matches() {
  local path="$1" expected="$2"
  python3 - "$path" "$expected" <<'PY'
import json
import sys

try:
    version = json.load(open(sys.argv[1], encoding="utf-8"))["version"]
except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
    raise SystemExit(1)
raise SystemExit(0 if version == sys.argv[2] else 1)
PY
}

plugin_modules_valid() {
  local root="$1" manifest="$2"
  python3 - "$root" "$manifest" <<'PY'
import json
import os
from pathlib import PurePosixPath
import stat
import sys
import unicodedata

root, manifest_path = sys.argv[1:]
try:
    modules = json.load(open(manifest_path, encoding="utf-8"))["plugin_modules"]
    if not isinstance(modules, dict) or set(modules) != {"accounts", "inbound", "send"}:
        raise ValueError
    exact_root = os.path.realpath(root)
    for value in modules.values():
        if (
            not isinstance(value, str)
            or not value
            or value.strip() != value
            or "\\" in value
            or any(unicodedata.category(character).startswith("C") for character in value)
        ):
            raise ValueError
        relative = PurePosixPath(value)
        if relative.is_absolute() or str(relative) != value:
            raise ValueError
        if any(part in {"", ".", ".."} for part in relative.parts):
            raise ValueError
        expected = os.path.join(exact_root, *relative.parts)
        metadata = os.lstat(expected)
        if not stat.S_ISREG(metadata.st_mode) or os.path.realpath(expected) != expected:
            raise ValueError
except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
    raise SystemExit(1)
PY
}

launch_value() {
  local output="$1" key="$2"
  printf '%s\n' "$output" | sed -n "s/^[[:space:]]*${key} => //p" | head -1
}

recipients_config_count() {
  local path="$1"
  python3 - "$path" <<'PY'
import json
import os
import re
import stat
import sys
import unicodedata

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
    if set(payload) != {"schema_version", "channel", "account_id", "active_recipients", "retired_aliases"}:
        raise ValueError
    if payload["schema_version"] != 2 or type(payload["schema_version"]) is not int:
        raise ValueError
    if payload["channel"] != "openclaw-weixin":
        raise ValueError
    account = payload["account_id"]
    active = payload["active_recipients"]
    retired = payload["retired_aliases"]
    if not isinstance(active, list) or not 1 <= len(active) <= 4:
        raise ValueError
    if not isinstance(retired, list) or retired != sorted(retired) or len(retired) != len(set(retired)):
        raise ValueError
    aliases = []
    targets = []
    for item in active:
        if not isinstance(item, dict) or set(item) != {"alias", "target_user_id"}:
            raise ValueError
        alias = item["alias"]
        target = item["target_user_id"]
        if not isinstance(alias, str) or re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", alias) is None:
            raise ValueError
        aliases.append(alias)
        targets.append(target)
    if aliases[0] != "owner" or aliases[1:] != sorted(aliases[1:]) or len(aliases) != len(set(aliases)):
        raise ValueError
    if len(targets) != len(set(targets)) or set(aliases) & set(retired):
        raise ValueError
    for alias in retired:
        if not isinstance(alias, str) or re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", alias) is None:
            raise ValueError
    for value in (account, *targets):
        if not isinstance(value, str) or not value or value.strip() != value:
            raise ValueError
        if any(unicodedata.category(character).startswith("C") for character in value):
            raise ValueError
    if any(not target.endswith("@im.wechat") or target == "@im.wechat" for target in targets):
        raise ValueError
    print(len(active))
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

wecom_present=false
clawbot_present=false
courier_present=false
if [[ "$runtime_root" != "missing" && "$runtime_root" != "unknown" ]]; then
  alerts_root="$runtime_root/services/quant-api/app/alerts"
  wecom_path="$alerts_root/wecom.py"
  clawbot_path="$alerts_root/clawbot.py"
  [[ -f "$wecom_path" && ! -L "$wecom_path" ]] && wecom_present=true
  [[ -f "$clawbot_path" && ! -L "$clawbot_path" ]] && clawbot_present=true
  for legacy_courier_path in "$alerts_root"/*courier.py; do
    [[ -e "$legacy_courier_path" || -L "$legacy_courier_path" ]] || continue
    if [[ -f "$legacy_courier_path" && ! -L "$legacy_courier_path" ]]; then
      courier_present=true
      break
    fi
  done
fi
notification_channel=unknown
if [[ "$wecom_present" == "true" && "$clawbot_present" == "false" && "$courier_present" == "false" ]]; then
  notification_channel=wecom
elif [[ "$wecom_present" == "false" && "$clawbot_present" == "true" && "$courier_present" == "false" ]]; then
  notification_channel=clawbot-openclaw-weixin
fi
printf '[local-services-status] alert.notification_channel=%s\n' "$notification_channel"
if [[ "$notification_channel" == "clawbot-openclaw-weixin" ]]; then
  versions_manifest="$runtime_root/deploy/clawbot/versions.json"
  openclaw_version="$(manifest_value "$versions_manifest" openclaw_version 2>/dev/null || printf 'unknown')"
  node_version="$(manifest_value "$versions_manifest" node_version 2>/dev/null || printf 'unknown')"
  plugin_version="$(manifest_value "$versions_manifest" openclaw_weixin_version 2>/dev/null || printf 'unknown')"
  clawbot_identity_valid=true
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
  clawbot_env_names=(
    GUIYI_OPENCLAW_BIN
    GUIYI_OPENCLAW_NODE_BIN
    GUIYI_OPENCLAW_WEIXIN_PLUGIN_ROOT
    GUIYI_OPENCLAW_STATE_DIR
    GUIYI_OPENCLAW_CONFIG_PATH
    GUIYI_ALERT_CLAWBOT_RECIPIENTS_PATH
  )
  for key in "${clawbot_env_names[@]}"; do
    api_value="$(plist_value com.guiyi.quant-api "$key")"
    alert_value="$(plist_value com.guiyi.quant-alert "$key")"
    if [[ "$api_value" == "missing" || "$alert_value" == "missing" || "$api_value" != "$alert_value" ]]; then
      clawbot_identity_valid=false
    fi
    if [[ "$api_loaded" != "true" || "$(launch_value "$api_launch_output" "$key")" != "$api_value" ]]; then
      clawbot_identity_valid=false
    fi
    if [[ "$alert_loaded" == "true" && "$(launch_value "$alert_launch_output" "$key")" != "$alert_value" ]]; then
      clawbot_identity_valid=false
    fi
  done
  if [[ "$alert_marker_enabled" == "true" && "$alert_loaded" != "true" ]]; then
    clawbot_identity_valid=false
  fi
  openclaw_bin="$(plist_value com.guiyi.quant-alert GUIYI_OPENCLAW_BIN)"
  node_bin="$(plist_value com.guiyi.quant-alert GUIYI_OPENCLAW_NODE_BIN)"
  state_dir="$(plist_value com.guiyi.quant-alert GUIYI_OPENCLAW_STATE_DIR)"
  config_path="$(plist_value com.guiyi.quant-alert GUIYI_OPENCLAW_CONFIG_PATH)"
  plugin_root="$(plist_value com.guiyi.quant-alert GUIYI_OPENCLAW_WEIXIN_PLUGIN_ROOT)"
  recipients_path="$(plist_value com.guiyi.quant-alert GUIYI_ALERT_CLAWBOT_RECIPIENTS_PATH)"

  openclaw_status=missing
  if [[ "$openclaw_bin" != "missing" && "$node_bin" != "missing" \
    && "$state_dir" != "missing" && "$config_path" != "missing" \
    && -e "$openclaw_bin" && -e "$node_bin" && -e "$state_dir" && -e "$config_path" ]]; then
    openclaw_status=invalid
    if [[ "$openclaw_version" != "unknown" && "$node_version" != "unknown" \
      && -f "$openclaw_bin" && ! -L "$openclaw_bin" && -x "$openclaw_bin" \
      && -f "$node_bin" && ! -L "$node_bin" && -x "$node_bin" \
      && -d "$state_dir" && ! -L "$state_dir" \
      && -f "$config_path" && ! -L "$config_path" ]] \
      && command_version_matches "$openclaw_bin" "$openclaw_version" \
      && command_version_matches "$node_bin" "$node_version"; then
      openclaw_status=ready
    fi
  fi

  plugin_status=missing
  if [[ "$plugin_root" != "missing" && -e "$plugin_root" ]]; then
    plugin_status=invalid
    if [[ "$plugin_version" != "unknown" && -d "$plugin_root" && ! -L "$plugin_root" \
      && -f "$plugin_root/package.json" && ! -L "$plugin_root/package.json" \
      ]] \
      && json_version_matches "$plugin_root/package.json" "$plugin_version" \
      && plugin_modules_valid "$plugin_root" "$versions_manifest"; then
      plugin_status=ready
    fi
  fi

  recipients_status=missing
  recipient_count=0
  if [[ "$recipients_path" != "missing" && -e "$recipients_path" ]]; then
    recipients_status=invalid
    if configured_count="$(recipients_config_count "$recipients_path" 2>/dev/null)"; then
      recipients_status=ready
      recipient_count="$configured_count"
    fi
  fi
  if [[ "$clawbot_identity_valid" != "true" ]]; then
    openclaw_status=invalid
    plugin_status=invalid
    recipients_status=invalid
    record_failure
  fi
  printf '[local-services-status] external.openclaw.status=%s\n' "$openclaw_status"
  printf '[local-services-status] external.openclaw.version=%s\n' "$openclaw_version"
  printf '[local-services-status] external.openclaw_weixin.status=%s\n' "$plugin_status"
  printf '[local-services-status] external.openclaw_weixin.version=%s\n' "$plugin_version"
  printf '[local-services-status] external.clawbot_recipients_config=%s\n' "$recipients_status"
  printf '[local-services-status] alert.notification_recipient_count=%s\n' "$recipient_count"
  if [[ "$alert_marker_enabled" == "true" \
    && ( "$openclaw_status" != "ready" || "$plugin_status" != "ready" || "$recipients_status" != "ready" ) ]]; then
    record_failure
  fi
fi
if [[ "$alert_marker_enabled" == "true" && "$notification_channel" == "unknown" ]]; then
  record_failure
fi

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
