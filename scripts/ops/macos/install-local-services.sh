#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
TEMPLATE_DIR="$PROJECT_ROOT/deploy/launchd"
RENDER_DIR="$PROJECT_ROOT/.run/launchd"
MARKET_RUNTIME_MARKER="$PROJECT_ROOT/.run/market-runtime-enabled"
ALERT_RUNTIME_MARKER="$PROJECT_ROOT/.run/alert-runtime-enabled"
AGENT_DIR="$HOME/Library/LaunchAgents"
RUNTIME_DIR="$HOME/Library/Application Support/GuiyiQuant"
LOG_DIR="$HOME/Library/Logs/GuiyiQuant"
MODE="${1:---render-only}"
ALERT_NOTIFICATION_CONFIG_PATH="${GUIYI_ALERT_NOTIFICATION_CONFIG_PATH:-}"

is_safe_absolute_path() {
  local path="$1" component
  local -a components

  [[ "$path" == /* ]] || return 1
  [[ "$path" != *'&'* && "$path" != *'<'* && "$path" != *'>'* \
    && "$path" != *'|'* && "$path" != *\\* \
    && "$path" != *$'\n'* && "$path" != *$'\r'* && "$path" != *$'\t'* ]] || return 1
  IFS='/' read -r -a components <<<"${path#/}"
  for component in "${components[@]}"; do
    [[ -z "$component" || "$component" == "." ]] && continue
    [[ "$component" != ".." ]] || return 1
  done
}

notification_config_ready() {
  local config_parent
  is_safe_absolute_path "$ALERT_NOTIFICATION_CONFIG_PATH" || return 1
  [[ -f "$ALERT_NOTIFICATION_CONFIG_PATH" && ! -L "$ALERT_NOTIFICATION_CONFIG_PATH" ]] || return 1
  config_parent="$(dirname "$ALERT_NOTIFICATION_CONFIG_PATH")"
  [[ -d "$config_parent" && ! -L "$config_parent" ]] || return 1
  [[ "$(stat -f '%Lp' "$ALERT_NOTIFICATION_CONFIG_PATH" 2>/dev/null)" == "600" ]] || return 1
  [[ "$(stat -f '%Lp' "$config_parent" 2>/dev/null)" == "700" ]] || return 1
  [[ "$(stat -f '%u' "$ALERT_NOTIFICATION_CONFIG_PATH" 2>/dev/null)" == "$(id -u)" ]] || return 1
  [[ "$(stat -f '%u' "$config_parent" 2>/dev/null)" == "$(id -u)" ]] || return 1
}

installed_api_notification_paths_match() {
  local api_plist="$AGENT_DIR/com.guiyi.quant-api.plist"
  local installed

  [[ -f "$api_plist" ]] || return 1
  installed="$(plutil -extract EnvironmentVariables.GUIYI_ALERT_NOTIFICATION_CONFIG_PATH raw -o - "$api_plist" 2>/dev/null)" || return 1
  [[ "$installed" == "$ALERT_NOTIFICATION_CONFIG_PATH" ]]
}

RUNTIME_COMMIT="$(git -C "$PROJECT_ROOT" rev-parse HEAD 2>/dev/null)"
if [[ ! "$RUNTIME_COMMIT" =~ ^[0-9a-f]{40}$ ]]; then
  printf '[install-local-services] invalid runtime commit identity\n' >&2
  exit 1
fi
base_labels=(com.guiyi.quant-api com.guiyi.quant-web com.guiyi.quant-log-rotate)
# Establish the new status writer before starting the new live reader.  If a
# later stage fails, cleanup runs in reverse before the exact previous market
# authority is restored from its bounded install preimage.
market_runtime_labels=(com.guiyi.quant-after-market com.guiyi.quant-live)
alert_runtime_labels=(com.guiyi.quant-alert)
weekly_audit_labels=(com.guiyi.quant-weekly-audit)
render_labels=("${base_labels[@]}" "${market_runtime_labels[@]}" "${alert_runtime_labels[@]}" "${weekly_audit_labels[@]}")
load_labels=("${base_labels[@]}")

[[ "$MODE" == "--render-only" || "$MODE" == "--confirm-load" || "$MODE" == "--confirm-market-runtime" || "$MODE" == "--confirm-alert-runtime" || "$MODE" == "--confirm-weekly-audit" ]] || { printf 'usage: %s [--render-only|--confirm-load|--confirm-market-runtime|--confirm-alert-runtime|--confirm-weekly-audit]\n' "$0" >&2; exit 2; }
if [[ "$MODE" == "--confirm-weekly-audit" ]]; then
  api_plist="$AGENT_DIR/com.guiyi.quant-api.plist"
  if [[ ! -f "$api_plist" || -L "$api_plist" ]] \
    || [[ "$(plutil -extract EnvironmentVariables.GUIYI_PROJECT_ROOT raw -o - "$api_plist" 2>/dev/null)" != "$PROJECT_ROOT" ]] \
    || [[ "$(plutil -extract EnvironmentVariables.GUIYI_RUNTIME_COMMIT raw -o - "$api_plist" 2>/dev/null)" != "$RUNTIME_COMMIT" ]]; then
    printf '[install-local-services] weekly audit runtime identity mismatch\n' >&2
    exit 1
  fi
fi
if [[ "$MODE" == "--confirm-alert-runtime" ]]; then
  notification_config_ready || {
    printf '[install-local-services] alert notification config not ready\n' >&2
    exit 1
  }
fi
if [[ -n "$ALERT_NOTIFICATION_CONFIG_PATH" ]] && ! is_safe_absolute_path "$ALERT_NOTIFICATION_CONFIG_PATH"; then
  printf '[install-local-services] invalid alert notification path\n' >&2
  exit 1
fi
if [[ "$MODE" == "--confirm-alert-runtime" ]] && ! installed_api_notification_paths_match; then
  printf '[install-local-services] installed API notification paths do not match\n' >&2
  exit 1
fi
mkdir -p "$RENDER_DIR"

for label in "${render_labels[@]}"; do
  template="$TEMPLATE_DIR/${label}.plist.template"
  output="$RENDER_DIR/${label}.plist"
  sed \
    -e "s|__PROJECT_ROOT__|$PROJECT_ROOT|g" \
    -e "s|__RUNTIME_COMMIT__|$RUNTIME_COMMIT|g" \
    -e "s|__RUNTIME_DIR__|$RUNTIME_DIR|g" \
    -e "s|__LOG_DIR__|$LOG_DIR|g" \
    -e "s|__HOME__|$HOME|g" \
    -e "s|__ALERT_NOTIFICATION_CONFIG_PATH__|$ALERT_NOTIFICATION_CONFIG_PATH|g" \
    "$template" >"$output"
  plutil -lint "$output" >/dev/null
done

printf '[install-local-services] rendered=%s\n' "$RENDER_DIR"
[[ "$MODE" == "--render-only" ]] && exit 0

if [[ "$MODE" == "--confirm-market-runtime" ]]; then
  load_labels=("${market_runtime_labels[@]}")
elif [[ "$MODE" == "--confirm-alert-runtime" ]]; then
  load_labels=("${alert_runtime_labels[@]}")
elif [[ "$MODE" == "--confirm-weekly-audit" ]]; then
  load_labels=("${weekly_audit_labels[@]}")
fi

if [[ "$MODE" == "--confirm-market-runtime" ]]; then
  env -u GUIYI_AFTER_MARKET_STATUS_PATH \
    "$PROJECT_ROOT/scripts/ops/macos/run-local-service.sh" market-runtime-preflight
fi

if [[ "$PROJECT_ROOT" == /Volumes/* && "${GUIYI_ALLOW_EXTERNAL_VOLUME_LAUNCHD:-0}" != "1" ]]; then
  printf '[install-local-services] ERROR: 项目位于外接卷；请先授予后台进程访问外接卷权限，再显式设置 GUIYI_ALLOW_EXTERNAL_VOLUME_LAUNCHD=1。\n' >&2
  exit 3
fi

mkdir -p "$AGENT_DIR" "$RUNTIME_DIR" "$LOG_DIR"
chmod 700 "$RUNTIME_DIR" "$LOG_DIR"

launchd_service_state() {
  local label="$1" output result

  if ! launchctl print "gui/$UID" >/dev/null 2>&1; then
    return 2
  fi
  if output="$(launchctl print "gui/$UID/$label" 2>&1)"; then
    return 0
  else
    result=$?
  fi
  if [[ "$result" != "0" ]] && {
    [[ "$output" == "Could not find service" ]] \
      || [[ "$output" =~ ^Could\ not\ find\ service\ \"[^\"]+\"\ in\ domain\ for\ user\ gui:\ [0-9]+$ ]]
  }; then
    return 1
  fi
  return 2
}

market_preimage_dir=""
market_preimage_paths=(
  "$RUNTIME_DIR/run-local-service.sh"
  "$RUNTIME_DIR/rotate-local-service-logs.sh"
  "$AGENT_DIR/com.guiyi.quant-after-market.plist"
  "$AGENT_DIR/com.guiyi.quant-live.plist"
)
market_preimage_existed=()
market_preimage_labels=(com.guiyi.quant-after-market com.guiyi.quant-live)
market_preimage_loaded=()

discard_market_install_preimage() {
  local index
  [[ -n "$market_preimage_dir" ]] || return 0
  for ((index=0; index < ${#market_preimage_paths[@]}; index++)); do
    rm -f "$market_preimage_dir/$index" || return 1
  done
  rmdir "$market_preimage_dir" || return 1
  market_preimage_dir=""
}

prepare_market_install_preimage() {
  local index label path state
  [[ "$MODE" == "--confirm-market-runtime" ]] || return 0

  market_preimage_dir="$(mktemp -d "$RENDER_DIR/market-install-preimage.XXXXXX")" || return 1
  chmod 700 "$market_preimage_dir" || return 1
  for ((index=0; index < ${#market_preimage_paths[@]}; index++)); do
    path="${market_preimage_paths[$index]}"
    if [[ -e "$path" || -L "$path" ]]; then
      if [[ ! -f "$path" || -L "$path" ]] || ! cp -p "$path" "$market_preimage_dir/$index"; then
        printf '[install-local-services] ERROR: market install preimage invalid path=%s\n' "$path" >&2
        discard_market_install_preimage || true
        return 1
      fi
      market_preimage_existed+=(1)
    else
      market_preimage_existed+=(0)
    fi
  done
  for label in "${market_preimage_labels[@]}"; do
    if launchd_service_state "$label"; then
      market_preimage_loaded+=(1)
    else
      state=$?
      if [[ "$state" == "1" ]]; then
        market_preimage_loaded+=(0)
      else
        printf '[install-local-services] ERROR: market install preimage launchd state unknown label=%s\n' "$label" >&2
        discard_market_install_preimage || true
        return 1
      fi
    fi
  done
}

reload_launch_agent() {
  local label="$1"
  local plist="$2"
  local attempt state=0

  launchctl bootout "gui/$UID/$label" >/dev/null 2>&1 || true
  for attempt in 1 2 3 4 5; do
    if launchd_service_state "$label"; then
      sleep 1
      continue
    else
      state=$?
    fi
    if [[ "$state" == "1" ]]; then
      break
    fi
    printf '[install-local-services] ERROR: launchd state unknown label=%s\n' "$label" >&2
    return 1
  done
  if [[ "$state" == "0" ]]; then
    printf '[install-local-services] ERROR: launchd bootout timed out label=%s\n' "$label" >&2
    return 1
  fi

  for attempt in 1 2 3 4 5; do
    if launchctl bootstrap "gui/$UID" "$plist"; then
      return 0
    fi
    if launchd_service_state "$label"; then
      return 0
    else
      state=$?
    fi
    if [[ "$state" == "2" ]]; then
      printf '[install-local-services] ERROR: launchd state unknown label=%s\n' "$label" >&2
      return 1
    fi
    sleep 1
  done
  printf '[install-local-services] ERROR: launchd reload failed label=%s\n' "$label" >&2
  return 1
}

restore_market_install_preimage() {
  local index label path state
  [[ "$MODE" == "--confirm-market-runtime" ]] || return 0
  [[ -n "$market_preimage_dir" ]] || return 1

  for ((index=0; index < ${#market_preimage_paths[@]}; index++)); do
    path="${market_preimage_paths[$index]}"
    if [[ "${market_preimage_existed[$index]}" == "1" ]]; then
      [[ -f "$market_preimage_dir/$index" && ! -L "$market_preimage_dir/$index" ]] || return 1
      cp -p "$market_preimage_dir/$index" "$path" || return 1
    else
      rm -f "$path" || return 1
    fi
  done

  for ((index=0; index < ${#market_preimage_labels[@]}; index++)); do
    label="${market_preimage_labels[$index]}"
    if [[ "${market_preimage_loaded[$index]}" == "1" ]]; then
      path="$AGENT_DIR/${label}.plist"
      [[ -f "$path" && ! -L "$path" ]] || return 1
      reload_launch_agent "$label" "$path" || return 1
      launchctl enable "gui/$UID/$label" || return 1
      if [[ "$label" == "com.guiyi.quant-live" ]]; then
        launchctl kickstart -k "gui/$UID/$label" || return 1
      fi
    fi
  done

  for ((index=0; index < ${#market_preimage_paths[@]}; index++)); do
    path="${market_preimage_paths[$index]}"
    if [[ "${market_preimage_existed[$index]}" == "1" ]]; then
      [[ -f "$path" && ! -L "$path" ]] || return 1
      cmp -s "$market_preimage_dir/$index" "$path" || return 1
    elif [[ -e "$path" || -L "$path" ]]; then
      return 1
    fi
  done
  for ((index=0; index < ${#market_preimage_labels[@]}; index++)); do
    label="${market_preimage_labels[$index]}"
    if launchd_service_state "$label"; then
      state=1
    else
      case "$?" in
        1) state=0 ;;
        *) return 1 ;;
      esac
    fi
    [[ "$state" == "${market_preimage_loaded[$index]}" ]] || return 1
  done
  discard_market_install_preimage
}

prepare_market_install_preimage

if [[ "$MODE" != "--confirm-weekly-audit" ]]; then
  cp "$PROJECT_ROOT/scripts/ops/macos/run-local-service.sh" "$RUNTIME_DIR/run-local-service.sh"
  chmod 700 "$RUNTIME_DIR/run-local-service.sh"
  cp "$PROJECT_ROOT/scripts/ops/macos/rotate-local-service-logs.sh" "$RUNTIME_DIR/rotate-local-service-logs.sh"
  chmod 700 "$RUNTIME_DIR/rotate-local-service-logs.sh"
fi

write_runtime_activation_marker() {
  local marker="$1" temporary_marker marker_mode
  temporary_marker="$(mktemp "${marker}.tmp.XXXXXX")" || return 1
  if ! printf 'enabled\n' >"$temporary_marker"; then
    rm -f "$temporary_marker"
    return 1
  fi
  if ! chmod 600 "$temporary_marker"; then
    rm -f "$temporary_marker"
    return 1
  fi
  if ! mv -f "$temporary_marker" "$marker"; then
    rm -f "$temporary_marker"
    return 1
  fi
  marker_mode="$(stat -f '%Lp' "$marker" 2>/dev/null)" || return 1
  if [[ -L "$marker" || "$marker_mode" != "600" ]] \
    || ! cmp -s "$marker" <(printf 'enabled\n'); then
    return 1
  fi
}

write_market_runtime_activation_marker() {
  write_runtime_activation_marker "$MARKET_RUNTIME_MARKER"
}

write_alert_runtime_activation_marker() {
  write_runtime_activation_marker "$ALERT_RUNTIME_MARKER"
}

activation_marker=""
activation_marker_backup=""
activation_marker_existed=0

prepare_runtime_activation_marker() {
  local writer
  if [[ "$MODE" == "--confirm-market-runtime" ]]; then
    activation_marker="$MARKET_RUNTIME_MARKER"
    writer=write_market_runtime_activation_marker
  elif [[ "$MODE" == "--confirm-alert-runtime" ]]; then
    activation_marker="$ALERT_RUNTIME_MARKER"
    writer=write_alert_runtime_activation_marker
  else
    return 0
  fi

  if [[ -e "$activation_marker" ]]; then
    activation_marker_backup="$(mktemp "${activation_marker}.previous.XXXXXX")" || return 1
    if ! cp -p "$activation_marker" "$activation_marker_backup"; then
      rm -f "$activation_marker_backup"
      activation_marker_backup=""
      return 1
    fi
    activation_marker_existed=1
  fi
  if ! "$writer"; then
    restore_runtime_activation_marker || {
      printf '[install-local-services] ERROR: activation marker rollback failed\n' >&2
    }
    return 1
  fi
}

restore_runtime_activation_marker() {
  if [[ -z "$activation_marker" ]]; then
    return 0
  fi
  if [[ "$activation_marker_existed" == "1" ]]; then
    [[ -f "$activation_marker_backup" ]] || return 1
    if ! mv -f "$activation_marker_backup" "$activation_marker"; then
      return 1
    fi
    activation_marker_backup=""
  else
    rm -f "$activation_marker" || return 1
  fi
  if [[ -n "$activation_marker_backup" ]]; then
    rm -f "$activation_marker_backup" || return 1
    activation_marker_backup=""
  fi
}

discard_runtime_activation_marker_backup() {
  if [[ -n "$activation_marker_backup" ]]; then
    rm -f "$activation_marker_backup" || return 1
    activation_marker_backup=""
  fi
}

prepare_runtime_activation_marker

attempted_load_labels=()

load_selected_services() {
  local label source_plist target_plist
  for label in "${load_labels[@]}"; do
    source_plist="$RENDER_DIR/${label}.plist"
    target_plist="$AGENT_DIR/${label}.plist"
    cp "$source_plist" "$target_plist" || return 1
    attempted_load_labels+=("$label")
    reload_launch_agent "$label" "$target_plist" || return 1
    launchctl enable "gui/$UID/$label" || return 1
    if [[ "$MODE" == "--confirm-load" || "$label" == "com.guiyi.quant-live" || "$label" == "com.guiyi.quant-alert" ]]; then
      launchctl kickstart -k "gui/$UID/$label" || return 1
    fi
  done
}

stop_attempted_services() {
  local index label attempt state
  local failed=0
  for ((index=${#attempted_load_labels[@]} - 1; index >= 0; index--)); do
    label="${attempted_load_labels[$index]}"
    launchctl bootout "gui/$UID/$label" >/dev/null 2>&1 || true
    state=0
    for attempt in 1 2 3 4 5; do
      if launchd_service_state "$label"; then
        sleep 1
        continue
      else
        state=$?
      fi
      if [[ "$state" == "1" ]]; then
        break
      fi
      printf '[install-local-services] ERROR: cleanup state unknown label=%s\n' "$label" >&2
      failed=1
      break
    done
    if [[ "$state" == "0" ]]; then
      printf '[install-local-services] ERROR: failed-attempt bootout timed out label=%s\n' "$label" >&2
      failed=1
    fi
  done
  return "$failed"
}

if ! load_selected_services; then
  if ! stop_attempted_services; then
    printf '[install-local-services] ERROR: failed attempt remains loaded; activation marker retained\n' >&2
    exit 1
  fi
  if [[ "$MODE" == "--confirm-market-runtime" ]] && ! restore_market_install_preimage; then
    printf '[install-local-services] ERROR: market authority restore unknown; activation marker retained\n' >&2
    exit 1
  fi
  if ! restore_runtime_activation_marker; then
    printf '[install-local-services] ERROR: activation marker rollback failed\n' >&2
    exit 1
  fi
  if [[ "$MODE" == "--confirm-market-runtime" ]]; then
    printf '[install-local-services] ERROR: partial market install is blocked; previous market authority restored; separate preflight and install intent required\n' >&2
  fi
  exit 1
fi
discard_runtime_activation_marker_backup
discard_market_install_preimage

printf '[install-local-services] loaded=true mode=%s services=%s\n' "$MODE" "${#load_labels[@]}"
