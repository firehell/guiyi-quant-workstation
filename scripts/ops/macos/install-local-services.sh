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
base_labels=(com.guiyi.quant-api com.guiyi.quant-web com.guiyi.quant-log-rotate)
market_runtime_labels=(com.guiyi.quant-live com.guiyi.quant-after-market)
alert_runtime_labels=(com.guiyi.quant-alert)
retired_labels=(
  com.guiyi.quant-web-recovery
  com.guiyi.quant-worker-signals
  com.guiyi.quant-worker-signals-recovery
  com.guiyi.quant-api-recovery-single
)
render_labels=("${base_labels[@]}" "${market_runtime_labels[@]}" "${alert_runtime_labels[@]}")
load_labels=("${base_labels[@]}")

[[ "$MODE" == "--render-only" || "$MODE" == "--confirm-load" || "$MODE" == "--confirm-market-runtime" || "$MODE" == "--confirm-alert-runtime" ]] || { printf 'usage: %s [--render-only|--confirm-load|--confirm-market-runtime|--confirm-alert-runtime]\n' "$0" >&2; exit 2; }
mkdir -p "$RENDER_DIR"

for label in "${render_labels[@]}"; do
  template="$TEMPLATE_DIR/${label}.plist.template"
  output="$RENDER_DIR/${label}.plist"
  sed \
    -e "s|__PROJECT_ROOT__|$PROJECT_ROOT|g" \
    -e "s|__RUNTIME_DIR__|$RUNTIME_DIR|g" \
    -e "s|__LOG_DIR__|$LOG_DIR|g" \
    -e "s|__HOME__|$HOME|g" \
    "$template" >"$output"
  plutil -lint "$output" >/dev/null
done

printf '[install-local-services] rendered=%s\n' "$RENDER_DIR"
[[ "$MODE" == "--render-only" ]] && exit 0

if [[ "$MODE" == "--confirm-market-runtime" ]]; then
  load_labels=("${market_runtime_labels[@]}")
elif [[ "$MODE" == "--confirm-alert-runtime" ]]; then
  load_labels=("${alert_runtime_labels[@]}")
fi

if [[ "$PROJECT_ROOT" == /Volumes/* && "${GUIYI_ALLOW_EXTERNAL_VOLUME_LAUNCHD:-0}" != "1" ]]; then
  printf '[install-local-services] ERROR: 项目位于外接卷；请先授予后台进程访问外接卷权限，再显式设置 GUIYI_ALLOW_EXTERNAL_VOLUME_LAUNCHD=1。\n' >&2
  exit 3
fi

mkdir -p "$AGENT_DIR" "$RUNTIME_DIR" "$LOG_DIR"
chmod 700 "$RUNTIME_DIR" "$LOG_DIR"
cp "$PROJECT_ROOT/scripts/ops/macos/run-local-service.sh" "$RUNTIME_DIR/run-local-service.sh"
chmod 700 "$RUNTIME_DIR/run-local-service.sh"
cp "$PROJECT_ROOT/scripts/ops/macos/rotate-local-service-logs.sh" "$RUNTIME_DIR/rotate-local-service-logs.sh"
chmod 700 "$RUNTIME_DIR/rotate-local-service-logs.sh"

reload_launch_agent() {
  local label="$1"
  local plist="$2"
  local attempt

  launchctl bootout "gui/$UID/$label" >/dev/null 2>&1 || true
  for attempt in 1 2 3 4 5; do
    if ! launchctl print "gui/$UID/$label" >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
  if launchctl print "gui/$UID/$label" >/dev/null 2>&1; then
    printf '[install-local-services] ERROR: launchd bootout timed out label=%s\n' "$label" >&2
    return 1
  fi

  for attempt in 1 2 3 4 5; do
    if launchctl bootstrap "gui/$UID" "$plist"; then
      return 0
    fi
    if launchctl print "gui/$UID/$label" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  printf '[install-local-services] ERROR: launchd reload failed label=%s\n' "$label" >&2
  return 1
}

retire_launch_agent() {
  local label="$1"
  local attempt

  launchctl bootout "gui/$UID/$label" >/dev/null 2>&1 || true
  for attempt in 1 2 3 4 5; do
    if ! launchctl print "gui/$UID/$label" >/dev/null 2>&1; then
      rm -f "$AGENT_DIR/${label}.plist"
      return 0
    fi
    sleep 1
  done
  printf '[install-local-services] ERROR: retired launchd bootout timed out label=%s\n' "$label" >&2
  return 1
}

write_market_runtime_activation_marker() {
  local temporary_marker
  temporary_marker="$(mktemp "${MARKET_RUNTIME_MARKER}.tmp.XXXXXX")"
  if ! printf 'enabled\n' >"$temporary_marker"; then
    rm -f "$temporary_marker"
    return 1
  fi
  chmod 600 "$temporary_marker"
  mv -f "$temporary_marker" "$MARKET_RUNTIME_MARKER"
}

write_alert_runtime_activation_marker() {
  local temporary_marker
  temporary_marker="$(mktemp "${ALERT_RUNTIME_MARKER}.tmp.XXXXXX")"
  if ! printf 'enabled\n' >"$temporary_marker"; then
    rm -f "$temporary_marker"
    return 1
  fi
  chmod 600 "$temporary_marker"
  mv -f "$temporary_marker" "$ALERT_RUNTIME_MARKER"
}

for label in "${retired_labels[@]}"; do
  retire_launch_agent "$label"
done

for label in "${load_labels[@]}"; do
  source_plist="$RENDER_DIR/${label}.plist"
  target_plist="$AGENT_DIR/${label}.plist"
  cp "$source_plist" "$target_plist"
  reload_launch_agent "$label" "$target_plist"
  launchctl enable "gui/$UID/$label"
  if [[ "$MODE" == "--confirm-load" || "$label" == "com.guiyi.quant-live" || "$label" == "com.guiyi.quant-alert" ]]; then
    launchctl kickstart -k "gui/$UID/$label"
  fi
done

if [[ "$MODE" == "--confirm-market-runtime" ]]; then
  write_market_runtime_activation_marker
elif [[ "$MODE" == "--confirm-alert-runtime" ]]; then
  write_alert_runtime_activation_marker
fi

printf '[install-local-services] loaded=true mode=%s services=%s\n' "$MODE" "${#load_labels[@]}"
