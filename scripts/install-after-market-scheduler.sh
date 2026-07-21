#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${GUIYI_PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
TEMPLATE="$PROJECT_ROOT/deploy/launchd/com.guiyi.quant-after-market-scheduler.plist.template"
RENDER_DIR="${GUIYI_AFTER_MARKET_RENDER_DIR:-$PROJECT_ROOT/.run/launchd}"
RUNTIME_DIR="${GUIYI_RUNTIME_DIR:-$HOME/Library/Application Support/GuiyiQuant}"
RUNTIME_ENV="${GUIYI_RUNTIME_ENV:-$RUNTIME_DIR/project.env}"
LOG_DIR="${GUIYI_LOG_DIR:-$HOME/Library/Logs/GuiyiQuant}"
AGENT_DIR="${GUIYI_LAUNCH_AGENT_DIR:-$HOME/Library/LaunchAgents}"
LABEL="com.guiyi.quant-after-market-scheduler"
MODE="${1:---render-only}"
DOMAIN="gui/$UID"

[[ "$MODE" == "--render-only" || "$MODE" == "--confirm-load" || "$MODE" == "--bootout" || "$MODE" == "--disable" ]] || {
  printf 'usage: %s [--render-only|--confirm-load|--bootout|--disable]\n' "$0" >&2
  exit 2
}

bootout_label() {
  launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
}

disable_flag() {
  [[ -f "$RUNTIME_ENV" ]] || { printf '[install-after-market-scheduler] runtime env missing\n' >&2; exit 78; }
  local temporary
  temporary="$(mktemp "$RUNTIME_DIR/.project.env.s607.XXXXXX")"
  awk '
    BEGIN { replaced = 0 }
    /^GUIYI_AFTER_MARKET_AUTOMATION_ENABLED=/ {
      print "GUIYI_AFTER_MARKET_AUTOMATION_ENABLED=false"
      replaced = 1
      next
    }
    { print }
    END {
      if (!replaced) print "GUIYI_AFTER_MARKET_AUTOMATION_ENABLED=false"
    }
  ' "$RUNTIME_ENV" >"$temporary"
  chmod 600 "$temporary"
  mv "$temporary" "$RUNTIME_ENV"
}

if [[ "$MODE" == "--bootout" ]]; then
  bootout_label
  printf '[install-after-market-scheduler] bootout=true enabled_flag_unchanged=true\n'
  exit 0
fi

if [[ "$MODE" == "--disable" ]]; then
  bootout_label
  disable_flag
  printf '[install-after-market-scheduler] bootout=true automation_enabled=false\n'
  exit 0
fi

mkdir -p "$RENDER_DIR" "$RUNTIME_DIR" "$LOG_DIR"
chmod 700 "$RUNTIME_DIR" "$LOG_DIR"
cp "$PROJECT_ROOT/scripts/run-after-market-scheduler.sh" "$RUNTIME_DIR/run-after-market-scheduler.sh"
chmod 700 "$RUNTIME_DIR/run-after-market-scheduler.sh"
sed \
  -e "s|__PROJECT_ROOT__|$PROJECT_ROOT|g" \
  -e "s|__RUNTIME_DIR__|$RUNTIME_DIR|g" \
  -e "s|__LOG_DIR__|$LOG_DIR|g" \
  -e "s|__HOME__|$HOME|g" \
  "$TEMPLATE" >"$RENDER_DIR/$LABEL.plist"
plutil -lint "$RENDER_DIR/$LABEL.plist" >/dev/null
printf '[install-after-market-scheduler] rendered=%s\n' "$RENDER_DIR/$LABEL.plist"
[[ "$MODE" == "--confirm-load" ]] || exit 0

[[ -f "$RUNTIME_ENV" ]] || { printf '[install-after-market-scheduler] runtime env missing\n' >&2; exit 78; }
set -a
# shellcheck disable=SC1090
source "$RUNTIME_ENV"
set +a
[[ "${GUIYI_AFTER_MARKET_AUTOMATION_ENABLED:-0}" =~ ^(1|true|yes|on)$ ]] || { printf '[install-after-market-scheduler] automation disabled\n' >&2; exit 78; }
[[ -f "${GUIYI_AFTER_MARKET_AUTOMATION_APPROVAL_PACKET:-}" ]] || { printf '[install-after-market-scheduler] approval packet unavailable\n' >&2; exit 78; }
[[ "${GUIYI_AFTER_MARKET_AUTOMATION_APPROVAL_HASH:-}" =~ ^[0-9a-f]{64}$ ]] || { printf '[install-after-market-scheduler] approval hash invalid\n' >&2; exit 78; }
if [[ "$PROJECT_ROOT" == /Volumes/* && "${GUIYI_ALLOW_EXTERNAL_VOLUME_LAUNCHD:-0}" != "1" ]]; then
  printf '[install-after-market-scheduler] external volume permission not confirmed\n' >&2
  exit 3
fi

mkdir -p "$AGENT_DIR"
target="$AGENT_DIR/$LABEL.plist"
cp "$RENDER_DIR/$LABEL.plist" "$target"
bootout_label
launchctl bootstrap "$DOMAIN" "$target"
launchctl enable "$DOMAIN/$LABEL"
launchctl kickstart -k "$DOMAIN/$LABEL"
printf '[install-after-market-scheduler] loaded=true label=%s\n' "$LABEL"
