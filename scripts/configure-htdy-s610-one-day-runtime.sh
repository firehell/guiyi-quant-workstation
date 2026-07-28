#!/usr/bin/env bash
set -euo pipefail

runtime_dir="${GUIYI_RUNTIME_DIR:-$HOME/Library/Application Support/GuiyiQuant}"
runtime_env="${GUIYI_RUNTIME_ENV:-$runtime_dir/project.env}"
mode="${1:-}"
shift || true

parent_packet=""
approval_hash=""
approval_c2_receipt=""
approval_c2_hash=""
approval_c2_signature=""
approved_signers=""
output_dir=""
while (($#)); do
  case "$1" in
    --parent-packet) parent_packet="${2:-}"; shift 2 ;;
    --approval-hash) approval_hash="${2:-}"; shift 2 ;;
    --approval-c2-receipt) approval_c2_receipt="${2:-}"; shift 2 ;;
    --approval-c2-hash) approval_c2_hash="${2:-}"; shift 2 ;;
    --approval-c2-signature) approval_c2_signature="${2:-}"; shift 2 ;;
    --approved-signers) approved_signers="${2:-}"; shift 2 ;;
    --output-dir) output_dir="${2:-}"; shift 2 ;;
    *) echo "[configure-s610-v5] unknown argument" >&2; exit 2 ;;
  esac
done

[[ "$mode" == "--enable" || "$mode" == "--disable" ]] || {
  echo "usage: $0 --enable <bindings> | --disable" >&2
  exit 2
}
[[ -f "$runtime_env" ]] || {
  echo "[configure-s610-v5] runtime env missing" >&2
  exit 78
}

if [[ "$mode" == "--enable" ]]; then
  [[ -f "$parent_packet" && -f "$approval_c2_receipt" && -f "$approval_c2_signature" && -f "$approved_signers" && -d "$output_dir" ]] || {
    echo "[configure-s610-v5] bound artifact unavailable" >&2
    exit 78
  }
  [[ "$approval_hash" =~ ^[0-9a-f]{64}$ && "$approval_c2_hash" =~ ^[0-9a-f]{64}$ ]] || {
    echo "[configure-s610-v5] approval hash invalid" >&2
    exit 78
  }
  signal_enabled=true
  required=true
  bounded=true
else
  [[ -z "$parent_packet$approval_hash$approval_c2_receipt$approval_c2_hash$approval_c2_signature$approved_signers$output_dir" ]] || {
    echo "[configure-s610-v5] disable accepts no bindings" >&2
    exit 2
  }
  signal_enabled=false
  required=false
  bounded=false
fi

quote() {
  local value="${1//\'/\'\\\'\'}"
  printf "'%s'" "$value"
}

parent_packet="$(quote "$parent_packet")"
approval_c2_receipt="$(quote "$approval_c2_receipt")"
approval_c2_signature="$(quote "$approval_c2_signature")"
approved_signers="$(quote "$approved_signers")"
output_dir="$(quote "$output_dir")"

temporary="$(mktemp "$runtime_dir/.project.env.s610-v5.XXXXXX")"
trap 'rm -f "$temporary"' EXIT
awk \
  -v signal="$signal_enabled" \
  -v required="$required" \
  -v bounded="$bounded" \
  -v packet="$parent_packet" \
  -v packet_hash="$approval_hash" \
  -v receipt="$approval_c2_receipt" \
  -v receipt_hash="$approval_c2_hash" \
  -v signature="$approval_c2_signature" \
  -v signers="$approved_signers" \
  -v output="$output_dir" '
  /^GUIYI_LIVE_RUNTIME_ENABLED=/ { print "GUIYI_LIVE_RUNTIME_ENABLED=true"; seen["runtime"]=1; next }
  /^GUIYI_LIVE_SIGNAL_EVENTS_ENABLED=/ { print "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED=" signal; seen["signal"]=1; next }
  /^GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_PACKET=/ { print "GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_PACKET=" packet; seen["packet"]=1; next }
  /^GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_HASH=/ { print "GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_HASH=" packet_hash; seen["packet_hash"]=1; next }
  /^GUIYI_HTDY_S610_REQUIRED=/ { print "GUIYI_HTDY_S610_REQUIRED=" required; seen["required"]=1; next }
  /^GUIYI_HTDY_S610_APPROVAL_C2_RECEIPT=/ { print "GUIYI_HTDY_S610_APPROVAL_C2_RECEIPT=" receipt; seen["receipt"]=1; next }
  /^GUIYI_HTDY_S610_APPROVAL_C2_HASH=/ { print "GUIYI_HTDY_S610_APPROVAL_C2_HASH=" receipt_hash; seen["receipt_hash"]=1; next }
  /^GUIYI_HTDY_S610_APPROVAL_C2_SIGNATURE=/ { print "GUIYI_HTDY_S610_APPROVAL_C2_SIGNATURE=" signature; seen["signature"]=1; next }
  /^GUIYI_HTDY_S610_APPROVED_SIGNERS=/ { print "GUIYI_HTDY_S610_APPROVED_SIGNERS=" signers; seen["signers"]=1; next }
  /^GUIYI_HTDY_S610_OUTPUT_DIR=/ { print "GUIYI_HTDY_S610_OUTPUT_DIR=" output; seen["output"]=1; next }
  /^GUIYI_HTDY_S610_BOUNDED_WECOM_ENABLED=/ { print "GUIYI_HTDY_S610_BOUNDED_WECOM_ENABLED=" bounded; seen["bounded"]=1; next }
  /^GUIYI_WECHAT_AUTOSEND_ENABLED=/ { print "GUIYI_WECHAT_AUTOSEND_ENABLED=false"; seen["autosend"]=1; next }
  { print }
  END {
    if (!seen["runtime"]) print "GUIYI_LIVE_RUNTIME_ENABLED=true"
    if (!seen["signal"]) print "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED=" signal
    if (!seen["packet"]) print "GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_PACKET=" packet
    if (!seen["packet_hash"]) print "GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_HASH=" packet_hash
    if (!seen["required"]) print "GUIYI_HTDY_S610_REQUIRED=" required
    if (!seen["receipt"]) print "GUIYI_HTDY_S610_APPROVAL_C2_RECEIPT=" receipt
    if (!seen["receipt_hash"]) print "GUIYI_HTDY_S610_APPROVAL_C2_HASH=" receipt_hash
    if (!seen["signature"]) print "GUIYI_HTDY_S610_APPROVAL_C2_SIGNATURE=" signature
    if (!seen["signers"]) print "GUIYI_HTDY_S610_APPROVED_SIGNERS=" signers
    if (!seen["output"]) print "GUIYI_HTDY_S610_OUTPUT_DIR=" output
    if (!seen["bounded"]) print "GUIYI_HTDY_S610_BOUNDED_WECOM_ENABLED=" bounded
    if (!seen["autosend"]) print "GUIYI_WECHAT_AUTOSEND_ENABLED=false"
  }
' "$runtime_env" >"$temporary"
chmod 600 "$temporary"
mv "$temporary" "$runtime_env"
trap - EXIT
echo "[configure-s610-v5] configured=true signal_events=$signal_enabled bounded=$bounded autosend=false"
