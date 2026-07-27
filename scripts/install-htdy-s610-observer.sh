#!/usr/bin/env bash
set -euo pipefail

project_root="${GUIYI_PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
template="$project_root/deploy/launchd/com.guiyi.quant-htdy-s610-observer.plist.template"
render_dir="${GUIYI_S610_RENDER_DIR:-$project_root/.run/launchd}"
runtime_dir="${GUIYI_RUNTIME_DIR:-$HOME/Library/Application Support/GuiyiQuant}"
runtime_env="${GUIYI_RUNTIME_ENV:-$runtime_dir/project.env}"
log_dir="${GUIYI_LOG_DIR:-$HOME/Library/Logs/GuiyiQuant}"
agent_dir="${GUIYI_LAUNCH_AGENT_DIR:-$HOME/Library/LaunchAgents}"
label="com.guiyi.quant-htdy-s610-observer"
mode="${1:---render-only}"
domain="gui/$UID"

case "$mode" in
  --render-only|--confirm-load|--bootout) ;;
  *) echo "usage: $0 [--render-only|--confirm-load|--bootout]" >&2; exit 2 ;;
esac

bootout_label() {
  launchctl bootout "$domain/$label" >/dev/null 2>&1 || true
}

if [[ "$mode" == "--bootout" ]]; then
  bootout_label
  if launchctl print "$domain/$label" >/dev/null 2>&1; then
    echo "[install-htdy-s610-observer] bootout verification failed" >&2
    exit 1
  fi
  echo "[install-htdy-s610-observer] bootout=true"
  exit 0
fi

[[ -f "$template" ]] || {
  echo "[install-htdy-s610-observer] template missing" >&2
  exit 78
}
[[ -f "$runtime_env" ]] || {
  echo "[install-htdy-s610-observer] runtime env missing" >&2
  exit 78
}

set -a
# shellcheck disable=SC1090
source "$runtime_env"
set +a

output_dir="${GUIYI_HTDY_S610_OUTPUT_DIR:-}"
parent_packet="${GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_PACKET:-}"
approval_hash="${GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_HASH:-}"
[[ "${GUIYI_LIVE_SIGNAL_EVENTS_ENABLED:-false}" == "true" ]] || {
  echo "[install-htdy-s610-observer] SignalEvent disabled" >&2
  exit 78
}
[[ "${GUIYI_WECHAT_AUTOSEND_ENABLED:-false}" == "false" ]] || {
  echo "[install-htdy-s610-observer] autosend must remain false" >&2
  exit 78
}
[[ -d "$output_dir" && -f "$parent_packet" ]] || {
  echo "[install-htdy-s610-observer] evidence binding unavailable" >&2
  exit 78
}
[[ "$approval_hash" =~ ^[0-9a-f]{64}$ ]] || {
  echo "[install-htdy-s610-observer] approval hash invalid" >&2
  exit 78
}

mkdir -p "$render_dir" "$log_dir"
chmod 700 "$log_dir"
sed \
  -e "s|__PROJECT_ROOT__|$project_root|g" \
  -e "s|__LOG_DIR__|$log_dir|g" \
  -e "s|__HOME__|$HOME|g" \
  -e "s|__S610_OUTPUT_DIR__|$output_dir|g" \
  -e "s|__S610_PARENT_PACKET__|$parent_packet|g" \
  -e "s|__S610_APPROVAL_HASH__|$approval_hash|g" \
  "$template" >"$render_dir/$label.plist"
plutil -lint "$render_dir/$label.plist" >/dev/null
echo "[install-htdy-s610-observer] rendered=true"
[[ "$mode" == "--confirm-load" ]] || exit 0

if [[ "$project_root" == /Volumes/* && "${GUIYI_ALLOW_EXTERNAL_VOLUME_LAUNCHD:-0}" != "1" ]]; then
  echo "[install-htdy-s610-observer] external volume permission not confirmed" >&2
  exit 3
fi
mkdir -p "$agent_dir"
target="$agent_dir/$label.plist"
cp "$render_dir/$label.plist" "$target"
bootout_label
launchctl bootstrap "$domain" "$target"
launchctl enable "$domain/$label"
launchctl kickstart -k "$domain/$label"
echo "[install-htdy-s610-observer] loaded=true label=$label"
