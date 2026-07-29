#!/usr/bin/env bash
set -euo pipefail

runtime_dir="${GUIYI_RUNTIME_DIR:-$HOME/Library/Application Support/GuiyiQuant}"
runtime_env="${GUIYI_RUNTIME_ENV:-$runtime_dir/project.env}"
mode="${1:-}"
shift || true

parent_packet=""
approval_hash=""
approval_c_bundle=""
approval_c_hash=""
approval_c_receipt=""
approval_c_signature=""
approval_c_approved_signers=""
output_dir=""
eod_packet=""
eod_hash=""
while (($#)); do
  case "$1" in
    --parent-packet) parent_packet="${2:-}"; shift 2 ;;
    --approval-hash) approval_hash="${2:-}"; shift 2 ;;
    --approval-c-bundle) approval_c_bundle="${2:-}"; shift 2 ;;
    --approval-c-hash) approval_c_hash="${2:-}"; shift 2 ;;
    --approval-c-receipt) approval_c_receipt="${2:-}"; shift 2 ;;
    --approval-c-signature) approval_c_signature="${2:-}"; shift 2 ;;
    --approval-c-approved-signers) approval_c_approved_signers="${2:-}"; shift 2 ;;
    --output-dir) output_dir="${2:-}"; shift 2 ;;
    --eod-packet) eod_packet="${2:-}"; shift 2 ;;
    --eod-hash) eod_hash="${2:-}"; shift 2 ;;
    *) echo "[configure-htdy-s610-runtime] unknown argument" >&2; exit 2 ;;
  esac
done

[[ "$mode" == "--enable" || "$mode" == "--disable" ]] || {
  echo "usage: $0 --enable <bindings> | --disable" >&2
  exit 2
}
[[ -f "$runtime_env" ]] || {
  echo "[configure-htdy-s610-runtime] runtime env missing" >&2
  exit 78
}

if [[ "$mode" == "--enable" ]]; then
  [[ -f "$parent_packet" && -f "$approval_c_bundle" && -f "$approval_c_receipt" && -f "$approval_c_signature" && -f "$approval_c_approved_signers" && -d "$output_dir" && -f "$eod_packet" ]] || {
    echo "[configure-htdy-s610-runtime] bound artifact unavailable" >&2
    exit 78
  }
  [[ "$approval_hash" =~ ^[0-9a-f]{64}$ && "$approval_c_hash" =~ ^[0-9a-f]{64}$ && "$eod_hash" =~ ^[0-9a-f]{64}$ ]] || {
    echo "[configure-htdy-s610-runtime] approval hash invalid" >&2
    exit 78
  }
  signal_enabled="true"
  s610_required="true"
  after_market_enabled="true"
  parent_packet=${parent_packet//\'/\'\\\'\'}
  parent_packet="'$parent_packet'"
  approval_c_bundle=${approval_c_bundle//\'/\'\\\'\'}
  approval_c_bundle="'$approval_c_bundle'"
  approval_c_receipt=${approval_c_receipt//\'/\'\\\'\'}
  approval_c_receipt="'$approval_c_receipt'"
  approval_c_signature=${approval_c_signature//\'/\'\\\'\'}
  approval_c_signature="'$approval_c_signature'"
  approval_c_approved_signers=${approval_c_approved_signers//\'/\'\\\'\'}
  approval_c_approved_signers="'$approval_c_approved_signers'"
  output_dir=${output_dir//\'/\'\\\'\'}
  output_dir="'$output_dir'"
  eod_packet=${eod_packet//\'/\'\\\'\'}
  eod_packet="'$eod_packet'"
else
  [[ -z "$parent_packet$approval_hash$approval_c_bundle$approval_c_hash$approval_c_receipt$approval_c_signature$approval_c_approved_signers$output_dir$eod_packet$eod_hash" ]] || {
    echo "[configure-htdy-s610-runtime] disable accepts no bindings" >&2
    exit 2
  }
  signal_enabled="false"
  s610_required="false"
  after_market_enabled=""
fi

temporary="$(mktemp "$runtime_dir/.project.env.s610.XXXXXX")"
trap 'rm -f "$temporary"' EXIT
GUIYI_S610_PARENT="$parent_packet" \
GUIYI_S610_APPROVAL_C_BUNDLE="$approval_c_bundle" \
GUIYI_S610_APPROVAL_C_RECEIPT="$approval_c_receipt" \
GUIYI_S610_APPROVAL_C_SIGNATURE="$approval_c_signature" \
GUIYI_S610_APPROVED_SIGNERS="$approval_c_approved_signers" \
GUIYI_S610_OUTPUT="$output_dir" \
GUIYI_S610_EOD_PACKET="$eod_packet" \
awk \
  -v mode="$mode" \
  -v signal_enabled="$signal_enabled" \
  -v s610_required="$s610_required" \
  -v approval_hash="$approval_hash" \
  -v approval_c_hash="$approval_c_hash" \
  -v after_market_enabled="$after_market_enabled" \
  -v eod_hash="$eod_hash" '
  BEGIN {
    parent = ENVIRON["GUIYI_S610_PARENT"]
    approval_c_bundle = ENVIRON["GUIYI_S610_APPROVAL_C_BUNDLE"]
    approval_c_receipt = ENVIRON["GUIYI_S610_APPROVAL_C_RECEIPT"]
    approval_c_signature = ENVIRON["GUIYI_S610_APPROVAL_C_SIGNATURE"]
    approval_c_approved_signers = ENVIRON["GUIYI_S610_APPROVED_SIGNERS"]
    output = ENVIRON["GUIYI_S610_OUTPUT"]
    eod_packet = ENVIRON["GUIYI_S610_EOD_PACKET"]
  }
  /^GUIYI_LIVE_RUNTIME_ENABLED=/ { print "GUIYI_LIVE_RUNTIME_ENABLED=true"; seen["runtime"]=1; next }
  /^GUIYI_LIVE_SIGNAL_EVENTS_ENABLED=/ { print "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED=" signal_enabled; seen["signal"]=1; next }
  /^GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_PACKET=/ { print "GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_PACKET=" parent; seen["packet"]=1; next }
  /^GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_HASH=/ { print "GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_HASH=" approval_hash; seen["hash"]=1; next }
  /^GUIYI_HTDY_S610_REQUIRED=/ { print "GUIYI_HTDY_S610_REQUIRED=" s610_required; seen["required"]=1; next }
  /^GUIYI_HTDY_S610_APPROVAL_C_BUNDLE=/ { print "GUIYI_HTDY_S610_APPROVAL_C_BUNDLE=" approval_c_bundle; seen["approval_c_bundle"]=1; next }
  /^GUIYI_HTDY_S610_APPROVAL_C_HASH=/ { print "GUIYI_HTDY_S610_APPROVAL_C_HASH=" approval_c_hash; seen["approval_c_hash"]=1; next }
  /^GUIYI_HTDY_S610_APPROVAL_C_RECEIPT=/ { print "GUIYI_HTDY_S610_APPROVAL_C_RECEIPT=" approval_c_receipt; seen["approval_c_receipt"]=1; next }
  /^GUIYI_HTDY_S610_APPROVAL_C_SIGNATURE=/ { print "GUIYI_HTDY_S610_APPROVAL_C_SIGNATURE=" approval_c_signature; seen["approval_c_signature"]=1; next }
  /^GUIYI_HTDY_S610_APPROVED_SIGNERS=/ { print "GUIYI_HTDY_S610_APPROVED_SIGNERS=" approval_c_approved_signers; seen["approval_c_approved_signers"]=1; next }
  /^GUIYI_HTDY_S610_OUTPUT_DIR=/ { print "GUIYI_HTDY_S610_OUTPUT_DIR=" output; seen["output"]=1; next }
  /^GUIYI_WECHAT_AUTOSEND_ENABLED=/ { print "GUIYI_WECHAT_AUTOSEND_ENABLED=false"; seen["autosend"]=1; next }
  /^GUIYI_AFTER_MARKET_AUTOMATION_ENABLED=/ {
    if (mode == "--enable") print "GUIYI_AFTER_MARKET_AUTOMATION_ENABLED=true"
    else print
    seen["eod_enabled"]=1
    next
  }
  /^GUIYI_AFTER_MARKET_AUTOMATION_APPROVAL_PACKET=/ {
    if (mode == "--enable") print "GUIYI_AFTER_MARKET_AUTOMATION_APPROVAL_PACKET=" eod_packet
    else print
    seen["eod_packet"]=1
    next
  }
  /^GUIYI_AFTER_MARKET_AUTOMATION_APPROVAL_HASH=/ {
    if (mode == "--enable") print "GUIYI_AFTER_MARKET_AUTOMATION_APPROVAL_HASH=" eod_hash
    else print
    seen["eod_hash"]=1
    next
  }
  { print }
  END {
    if (!seen["runtime"]) print "GUIYI_LIVE_RUNTIME_ENABLED=true"
    if (!seen["signal"]) print "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED=" signal_enabled
    if (!seen["packet"]) print "GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_PACKET=" parent
    if (!seen["hash"]) print "GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_HASH=" approval_hash
    if (!seen["required"]) print "GUIYI_HTDY_S610_REQUIRED=" s610_required
    if (!seen["approval_c_bundle"]) print "GUIYI_HTDY_S610_APPROVAL_C_BUNDLE=" approval_c_bundle
    if (!seen["approval_c_hash"]) print "GUIYI_HTDY_S610_APPROVAL_C_HASH=" approval_c_hash
    if (!seen["approval_c_receipt"]) print "GUIYI_HTDY_S610_APPROVAL_C_RECEIPT=" approval_c_receipt
    if (!seen["approval_c_signature"]) print "GUIYI_HTDY_S610_APPROVAL_C_SIGNATURE=" approval_c_signature
    if (!seen["approval_c_approved_signers"]) print "GUIYI_HTDY_S610_APPROVED_SIGNERS=" approval_c_approved_signers
    if (!seen["output"]) print "GUIYI_HTDY_S610_OUTPUT_DIR=" output
    if (!seen["autosend"]) print "GUIYI_WECHAT_AUTOSEND_ENABLED=false"
    if (mode == "--enable" && !seen["eod_enabled"]) print "GUIYI_AFTER_MARKET_AUTOMATION_ENABLED=true"
    if (mode == "--enable" && !seen["eod_packet"]) print "GUIYI_AFTER_MARKET_AUTOMATION_APPROVAL_PACKET=" eod_packet
    if (mode == "--enable" && !seen["eod_hash"]) print "GUIYI_AFTER_MARKET_AUTOMATION_APPROVAL_HASH=" eod_hash
  }
' "$runtime_env" >"$temporary"
chmod 600 "$temporary"
mv "$temporary" "$runtime_env"
trap - EXIT
echo "[configure-htdy-s610-runtime] configured=true signal_events=$signal_enabled autosend=false"
