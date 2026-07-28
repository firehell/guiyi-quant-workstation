#!/usr/bin/env bash
set -euo pipefail

project_root="${GUIYI_PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
render_dir="${GUIYI_S610_RENDER_DIR:-$project_root/.run/launchd}"
runtime_dir="${GUIYI_RUNTIME_DIR:-$HOME/Library/Application Support/GuiyiQuant}"
runtime_env="${GUIYI_RUNTIME_ENV:-$runtime_dir/project.env}"
log_dir="${GUIYI_LOG_DIR:-$HOME/Library/Logs/GuiyiQuant}"
agent_dir="${GUIYI_LAUNCH_AGENT_DIR:-$HOME/Library/LaunchAgents}"
mode="${1:---render-only}"
domain="gui/$UID"
observer_label="com.guiyi.quant-htdy-s610-one-day-observer"
dispatcher_label="com.guiyi.quant-htdy-s610-one-day-dispatcher"

case "$mode" in
  --render-only|--confirm-load|--bootout) ;;
  *) echo "usage: $0 [--render-only|--confirm-load|--bootout]" >&2; exit 2 ;;
esac

bootout_label() {
  launchctl bootout "$domain/$1" >/dev/null 2>&1 || true
}

if [[ "$mode" == "--bootout" ]]; then
  bootout_label "$observer_label"
  bootout_label "$dispatcher_label"
  for label in "$observer_label" "$dispatcher_label"; do
    if launchctl print "$domain/$label" >/dev/null 2>&1; then
      echo "[install-s610-v5] bootout verification failed label=$label" >&2
      exit 1
    fi
  done
  echo "[install-s610-v5] bootout=true"
  exit 0
fi

[[ -f "$runtime_env" ]] || {
  echo "[install-s610-v5] runtime env missing" >&2
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
  echo "[install-s610-v5] SignalEvent disabled" >&2
  exit 78
}
[[ "${GUIYI_HTDY_S610_BOUNDED_WECOM_ENABLED:-false}" == "true" ]] || {
  echo "[install-s610-v5] bounded dispatcher disabled" >&2
  exit 78
}
[[ "${GUIYI_WECHAT_AUTOSEND_ENABLED:-false}" == "false" ]] || {
  echo "[install-s610-v5] global autosend must remain false" >&2
  exit 78
}
[[ -d "$output_dir" && -f "$parent_packet" ]] || {
  echo "[install-s610-v5] evidence binding unavailable" >&2
  exit 78
}
[[ "$approval_hash" =~ ^[0-9a-f]{64}$ ]] || {
  echo "[install-s610-v5] approval hash invalid" >&2
  exit 78
}

verify_identity() {
  local service="$1"
  local binding_key expected_identity_hash identity_path template_path
  local template_hash runner_path runner_hash source_template source_runner
  if [[ "$service" == "observer" ]]; then
    binding_key="observer"
  else
    binding_key="delivery"
  fi
  identity_path="$(plutil -extract "bindings.artifact_paths.${binding_key}_identity" raw -o - "$parent_packet")"
  expected_identity_hash="$(plutil -extract "bindings.${binding_key}_launchd_sha256" raw -o - "$parent_packet")"
  [[ -f "$identity_path" && "$(shasum -a 256 "$identity_path" | awk '{print $1}')" == "$expected_identity_hash" ]] || {
    echo "[install-s610-v5] identity binding drift service=$service" >&2
    exit 78
  }
  template_path="$(plutil -extract template_path raw -o - "$identity_path")"
  template_hash="$(plutil -extract template_sha256 raw -o - "$identity_path")"
  runner_path="$(plutil -extract runner_path raw -o - "$identity_path")"
  runner_hash="$(plutil -extract runner_sha256 raw -o - "$identity_path")"
  source_template="$project_root/deploy/launchd/com.guiyi.quant-htdy-s610-one-day-$service.plist.template"
  source_runner="$project_root/scripts/run-htdy-s610-one-day-$service.sh"
  [[ "${template_path##*/}" == "${source_template##*/}" && "${runner_path##*/}" == "${source_runner##*/}" ]] || {
    echo "[install-s610-v5] identity filename drift service=$service" >&2
    exit 78
  }
  [[ "$(shasum -a 256 "$source_template" | awk '{print $1}')" == "$template_hash" ]] || {
    echo "[install-s610-v5] template hash drift service=$service" >&2
    exit 78
  }
  [[ "$(shasum -a 256 "$source_runner" | awk '{print $1}')" == "$runner_hash" ]] || {
    echo "[install-s610-v5] runner hash drift service=$service" >&2
    exit 78
  }
}

mkdir -p "$render_dir" "$runtime_dir" "$log_dir"
chmod 700 "$log_dir"
for service in observer dispatcher; do
  template="$project_root/deploy/launchd/com.guiyi.quant-htdy-s610-one-day-$service.plist.template"
  source_runner="$project_root/scripts/run-htdy-s610-one-day-$service.sh"
  local_runner="$runtime_dir/run-htdy-s610-one-day-$service.sh"
  label="com.guiyi.quant-htdy-s610-one-day-$service"
  [[ -f "$template" && -f "$source_runner" ]] || {
    echo "[install-s610-v5] service artifact missing service=$service" >&2
    exit 78
  }
  verify_identity "$service"
  install -m 700 "$source_runner" "$local_runner"
  sed \
    -e "s|__PROJECT_ROOT__|$project_root|g" \
    -e "s|__OBSERVER_RUNNER__|$local_runner|g" \
    -e "s|__DISPATCHER_RUNNER__|$local_runner|g" \
    -e "s|__LOG_DIR__|$log_dir|g" \
    -e "s|__HOME__|$HOME|g" \
    -e "s|__S610_OUTPUT_DIR__|$output_dir|g" \
    -e "s|__S610_PARENT_PACKET__|$parent_packet|g" \
    -e "s|__S610_APPROVAL_HASH__|$approval_hash|g" \
    "$template" >"$render_dir/$label.plist"
  plutil -lint "$render_dir/$label.plist" >/dev/null
done
echo "[install-s610-v5] rendered=true"
[[ "$mode" == "--confirm-load" ]] || exit 0

if [[ "$project_root" == /Volumes/* && "${GUIYI_ALLOW_EXTERNAL_VOLUME_LAUNCHD:-0}" != "1" ]]; then
  echo "[install-s610-v5] external volume permission not confirmed" >&2
  exit 3
fi
mkdir -p "$agent_dir"
for label in "$observer_label" "$dispatcher_label"; do
  target="$agent_dir/$label.plist"
  cp "$render_dir/$label.plist" "$target"
  bootout_label "$label"
  launchctl bootstrap "$domain" "$target"
  launchctl enable "$domain/$label"
  launchctl kickstart -k "$domain/$label"
done
echo "[install-s610-v5] loaded=true observer=$observer_label dispatcher=$dispatcher_label"
