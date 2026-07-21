#!/usr/bin/env bash
set -euo pipefail

RUNTIME_DIR="${GUIYI_RUNTIME_DIR:-$HOME/Library/Application Support/GuiyiQuant}"
RUNTIME_ENV="${GUIYI_RUNTIME_ENV:-$RUNTIME_DIR/project.env}"
MODE="${1:-}"
shift || true

[[ "$MODE" == "--enable" ]] || {
  printf 'usage: %s --enable --approval-packet PATH --approval-hash SHA256\n' "$0" >&2
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
      printf '[configure-after-market-automation] unknown argument\n' >&2
      exit 2
      ;;
  esac
done

[[ -f "$RUNTIME_ENV" ]] || { printf '[configure-after-market-automation] runtime env missing\n' >&2; exit 78; }
[[ -f "$APPROVAL_PACKET" ]] || { printf '[configure-after-market-automation] approval packet unavailable\n' >&2; exit 78; }
[[ "$APPROVAL_HASH" =~ ^[0-9a-f]{64}$ ]] || { printf '[configure-after-market-automation] approval hash invalid\n' >&2; exit 78; }

temporary="$(mktemp "$RUNTIME_DIR/.project.env.s607.XXXXXX")"
trap 'rm -f "$temporary"' EXIT
awk -v packet="$APPROVAL_PACKET" -v hash="$APPROVAL_HASH" '
  BEGIN { enabled = 0; packet_seen = 0; hash_seen = 0 }
  /^GUIYI_AFTER_MARKET_AUTOMATION_ENABLED=/ {
    print "GUIYI_AFTER_MARKET_AUTOMATION_ENABLED=true"
    enabled = 1
    next
  }
  /^GUIYI_AFTER_MARKET_AUTOMATION_APPROVAL_PACKET=/ {
    print "GUIYI_AFTER_MARKET_AUTOMATION_APPROVAL_PACKET=" packet
    packet_seen = 1
    next
  }
  /^GUIYI_AFTER_MARKET_AUTOMATION_APPROVAL_HASH=/ {
    print "GUIYI_AFTER_MARKET_AUTOMATION_APPROVAL_HASH=" hash
    hash_seen = 1
    next
  }
  { print }
  END {
    if (!enabled) print "GUIYI_AFTER_MARKET_AUTOMATION_ENABLED=true"
    if (!packet_seen) print "GUIYI_AFTER_MARKET_AUTOMATION_APPROVAL_PACKET=" packet
    if (!hash_seen) print "GUIYI_AFTER_MARKET_AUTOMATION_APPROVAL_HASH=" hash
  }
' "$RUNTIME_ENV" >"$temporary"
chmod 600 "$temporary"
mv "$temporary" "$RUNTIME_ENV"
trap - EXIT
printf '[configure-after-market-automation] configured=true keys_updated=3\n'
