#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMPLATE_DIR="$PROJECT_ROOT/deploy/launchd"
RENDER_DIR="$PROJECT_ROOT/.run/launchd"
AGENT_DIR="$HOME/Library/LaunchAgents"
RUNTIME_DIR="$HOME/Library/Application Support/GuiyiQuant"
LOG_DIR="$HOME/Library/Logs/GuiyiQuant"
MODE="${1:---render-only}"
base_labels=(com.guiyi.quant-api com.guiyi.quant-worker-backtests com.guiyi.quant-worker-signals com.guiyi.quant-web com.guiyi.quant-log-rotate)
optional_labels=(com.guiyi.quant-runtime-scheduler com.guiyi.quant-worker-notifications)
render_labels=("${base_labels[@]}" "${optional_labels[@]}")
load_labels=("${base_labels[@]}")

[[ "${GUIYI_LIVE_RUNTIME_ENABLED:-0}" =~ ^(1|true|yes|on)$ ]] && load_labels+=(com.guiyi.quant-runtime-scheduler)
[[ "${GUIYI_WECHAT_AUTOSEND_ENABLED:-0}" =~ ^(1|true|yes|on)$ ]] && load_labels+=(com.guiyi.quant-worker-notifications)

[[ "$MODE" == "--render-only" || "$MODE" == "--confirm-load" ]] || { printf 'usage: %s [--render-only|--confirm-load]\n' "$0" >&2; exit 2; }
mkdir -p "$RENDER_DIR" "$RUNTIME_DIR" "$LOG_DIR"
cp "$PROJECT_ROOT/scripts/run-local-service.sh" "$RUNTIME_DIR/run-local-service.sh"
chmod 700 "$RUNTIME_DIR/run-local-service.sh"
cp "$PROJECT_ROOT/scripts/rotate-local-service-logs.sh" "$RUNTIME_DIR/rotate-local-service-logs.sh"
chmod 700 "$RUNTIME_DIR/rotate-local-service-logs.sh"

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
[[ "$MODE" == "--confirm-load" ]] || exit 0

if [[ "$PROJECT_ROOT" == /Volumes/* && "${GUIYI_ALLOW_EXTERNAL_VOLUME_LAUNCHD:-0}" != "1" ]]; then
  printf '[install-local-services] ERROR: 项目位于外接卷；请先授予后台进程访问外接卷权限，再显式设置 GUIYI_ALLOW_EXTERNAL_VOLUME_LAUNCHD=1。\n' >&2
  exit 3
fi

mkdir -p "$AGENT_DIR"
for label in "${load_labels[@]}"; do
  source_plist="$RENDER_DIR/${label}.plist"
  target_plist="$AGENT_DIR/${label}.plist"
  cp "$source_plist" "$target_plist"
  launchctl bootout "gui/$UID/$label" >/dev/null 2>&1 || true
  launchctl bootstrap "gui/$UID" "$target_plist"
  launchctl enable "gui/$UID/$label"
  launchctl kickstart -k "gui/$UID/$label"
done
printf '[install-local-services] loaded=true services=%s\n' "${#load_labels[@]}"
