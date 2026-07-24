#!/usr/bin/env bash
set -euo pipefail

RUNTIME_DIR="${GUIYI_RUNTIME_DIR:-$HOME/Library/Application Support/GuiyiQuant}"
RUNTIME_ENV="${GUIYI_RUNTIME_ENV:-$RUNTIME_DIR/project.env}"
MODE="${1:-}"
shift || true

[[ "$MODE" == "--enable" || "$MODE" == "--disable" ]] || {
  printf 'usage: %s --enable --approval-packet PATH --approval-hash SHA256 | --disable\n' "$0" >&2
  exit 2
}

APPROVAL_PACKET=""
APPROVAL_HASH=""
while (($#)); do
  case "$1" in
    --approval-packet)
      [[ $# -ge 2 ]] || exit 2
      APPROVAL_PACKET="$2"
      shift 2
      ;;
    --approval-hash)
      [[ $# -ge 2 ]] || exit 2
      APPROVAL_HASH="$2"
      shift 2
      ;;
    *)
      printf '[configure-live-signal-events] unknown argument\n' >&2
      exit 2
      ;;
  esac
done

[[ -f "$RUNTIME_ENV" ]] || { printf '[configure-live-signal-events] runtime env missing\n' >&2; exit 78; }
if [[ "$MODE" == "--enable" ]]; then
  [[ -f "$APPROVAL_PACKET" ]] || { printf '[configure-live-signal-events] approval packet unavailable\n' >&2; exit 78; }
  [[ "$APPROVAL_HASH" =~ ^[0-9a-f]{64}$ ]] || { printf '[configure-live-signal-events] approval hash invalid\n' >&2; exit 78; }
  ENABLED_VALUE="true"
  printf -v APPROVAL_PACKET_ENV '%q' "$APPROVAL_PACKET"
else
  [[ -z "$APPROVAL_PACKET" && -z "$APPROVAL_HASH" ]] || {
    printf '[configure-live-signal-events] disable does not accept approval arguments\n' >&2
    exit 2
  }
  ENABLED_VALUE="false"
  APPROVAL_PACKET_ENV=""
fi

temporary="$(mktemp "$RUNTIME_DIR/.project.env.s608.XXXXXX")"
trap 'rm -f "$temporary"' EXIT
GUIYI_PACKET_ENV="$APPROVAL_PACKET_ENV" awk -v enabled_value="$ENABLED_VALUE" -v hash="$APPROVAL_HASH" '
  BEGIN { enabled = 0; packet_seen = 0; hash_seen = 0; packet = ENVIRON["GUIYI_PACKET_ENV"] }
  /^GUIYI_LIVE_SIGNAL_EVENTS_ENABLED=/ {
    print "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED=" enabled_value
    enabled = 1
    next
  }
  /^GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_PACKET=/ {
    print "GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_PACKET=" packet
    packet_seen = 1
    next
  }
  /^GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_HASH=/ {
    print "GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_HASH=" hash
    hash_seen = 1
    next
  }
  { print }
  END {
    if (!enabled) print "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED=" enabled_value
    if (!packet_seen) print "GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_PACKET=" packet
    if (!hash_seen) print "GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_HASH=" hash
  }
' "$RUNTIME_ENV" >"$temporary"
chmod 600 "$temporary"
mv "$temporary" "$RUNTIME_ENV"
trap - EXIT
printf '[configure-live-signal-events] configured=true enabled=%s keys_updated=3\n' "$ENABLED_VALUE"
