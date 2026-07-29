#!/usr/bin/env bash
set -euo pipefail

runtime_dir="${GUIYI_RUNTIME_DIR:-$HOME/Library/Application Support/GuiyiQuant}"
runtime_env="${GUIYI_RUNTIME_ENV:-$runtime_dir/project.env}"
mode="${1:-}"
shift || true

request=""
receipt=""
receipt_hash=""
signature=""
signers=""
daily_child_root=""
while (($#)); do
  case "$1" in
    --approval-d-request) request="${2:-}"; shift 2 ;;
    --approval-d-receipt) receipt="${2:-}"; shift 2 ;;
    --approval-d-hash) receipt_hash="${2:-}"; shift 2 ;;
    --approval-d-signature) signature="${2:-}"; shift 2 ;;
    --approved-signers) signers="${2:-}"; shift 2 ;;
    --daily-child-root) daily_child_root="${2:-}"; shift 2 ;;
    *) echo "[configure-s610-long] unknown argument" >&2; exit 2 ;;
  esac
done

[[ "$mode" == "--arm" || "$mode" == "--activate" || "$mode" == "--disable" ]] || {
  echo "usage: $0 --arm <bindings> | --activate <bindings> | --disable" >&2
  exit 2
}
[[ -f "$runtime_env" ]] || {
  echo "[configure-s610-long] runtime env missing" >&2
  exit 78
}

if [[ "$mode" == "--arm" || "$mode" == "--activate" ]]; then
  [[ -f "$request" && -f "$receipt" && -f "$signature" && -f "$signers" && -d "$daily_child_root" ]] || {
    echo "[configure-s610-long] bound artifact unavailable" >&2
    exit 78
  }
  [[ "$receipt_hash" =~ ^[0-9a-f]{64}$ ]] || {
    echo "[configure-s610-long] approval D hash invalid" >&2
    exit 78
  }
  if [[ "$mode" == "--arm" ]]; then
    signal_enabled=false
    bounded=false
    phase=approval_d_armed
  else
    grep -Fxq "GUIYI_HTDY_S610_PHASE=approval_d_armed" "$runtime_env" \
      && grep -Fxq "GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_HASH=$receipt_hash" "$runtime_env" \
      && grep -Fxq "GUIYI_HTDY_S610_APPROVAL_D_RECEIPT='$receipt'" "$runtime_env" || {
      echo "[configure-s610-long] exact armed state missing" >&2
      exit 78
    }
    signal_enabled=true
    bounded=true
    phase=approval_d_activated
  fi
  required=true
else
  [[ -z "$request$receipt$receipt_hash$signature$signers$daily_child_root" ]] || {
    echo "[configure-s610-long] disable accepts no bindings" >&2
    exit 2
  }
  signal_enabled=false
  bounded=false
  required=false
  phase=disabled
fi

quote() {
  local value="${1//\'/\'\\\'\'}"
  printf "'%s'" "$value"
}

request_q="$(quote "$request")"
receipt_q="$(quote "$receipt")"
signature_q="$(quote "$signature")"
signers_q="$(quote "$signers")"
daily_child_root_q="$(quote "$daily_child_root")"

temporary="$(mktemp "$runtime_dir/.project.env.s610-long.XXXXXX")"
trap 'rm -f "$temporary"' EXIT
awk \
  -v signal="$signal_enabled" \
  -v bounded="$bounded" \
  -v required="$required" \
  -v packet="$request_q" \
  -v packet_hash="$receipt_hash" \
  -v receipt="$receipt_q" \
  -v signature="$signature_q" \
  -v signers="$signers_q" \
  -v child_root="$daily_child_root_q" \
  -v phase="$phase" '
  /^GUIYI_LIVE_RUNTIME_ENABLED=/ { print "GUIYI_LIVE_RUNTIME_ENABLED=true"; seen["runtime"]=1; next }
  /^GUIYI_LIVE_SIGNAL_EVENTS_ENABLED=/ { print "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED=" signal; seen["signal"]=1; next }
  /^GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_PACKET=/ { print "GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_PACKET=" packet; seen["packet"]=1; next }
  /^GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_HASH=/ { print "GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_HASH=" packet_hash; seen["packet_hash"]=1; next }
  /^GUIYI_HTDY_S610_REQUIRED=/ { print "GUIYI_HTDY_S610_REQUIRED=" required; seen["required"]=1; next }
  /^GUIYI_HTDY_S610_APPROVAL_D_RECEIPT=/ { print "GUIYI_HTDY_S610_APPROVAL_D_RECEIPT=" receipt; seen["receipt"]=1; next }
  /^GUIYI_HTDY_S610_APPROVAL_D_SIGNATURE=/ { print "GUIYI_HTDY_S610_APPROVAL_D_SIGNATURE=" signature; seen["signature"]=1; next }
  /^GUIYI_HTDY_S610_APPROVED_SIGNERS=/ { print "GUIYI_HTDY_S610_APPROVED_SIGNERS=" signers; seen["signers"]=1; next }
  /^GUIYI_HTDY_S610_DAILY_CHILD_ROOT=/ { print "GUIYI_HTDY_S610_DAILY_CHILD_ROOT=" child_root; seen["child_root"]=1; next }
  /^GUIYI_HTDY_S610_PHASE=/ { print "GUIYI_HTDY_S610_PHASE=" phase; seen["phase"]=1; next }
  /^GUIYI_HTDY_S610_BOUNDED_WECOM_ENABLED=/ { print "GUIYI_HTDY_S610_BOUNDED_WECOM_ENABLED=" bounded; seen["bounded"]=1; next }
  /^GUIYI_WECHAT_AUTOSEND_ENABLED=/ { print "GUIYI_WECHAT_AUTOSEND_ENABLED=false"; seen["autosend"]=1; next }
  { print }
  END {
    if (!seen["runtime"]) print "GUIYI_LIVE_RUNTIME_ENABLED=true"
    if (!seen["signal"]) print "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED=" signal
    if (!seen["packet"]) print "GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_PACKET=" packet
    if (!seen["packet_hash"]) print "GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_HASH=" packet_hash
    if (!seen["required"]) print "GUIYI_HTDY_S610_REQUIRED=" required
    if (!seen["receipt"]) print "GUIYI_HTDY_S610_APPROVAL_D_RECEIPT=" receipt
    if (!seen["signature"]) print "GUIYI_HTDY_S610_APPROVAL_D_SIGNATURE=" signature
    if (!seen["signers"]) print "GUIYI_HTDY_S610_APPROVED_SIGNERS=" signers
    if (!seen["child_root"]) print "GUIYI_HTDY_S610_DAILY_CHILD_ROOT=" child_root
    if (!seen["phase"]) print "GUIYI_HTDY_S610_PHASE=" phase
    if (!seen["bounded"]) print "GUIYI_HTDY_S610_BOUNDED_WECOM_ENABLED=" bounded
    if (!seen["autosend"]) print "GUIYI_WECHAT_AUTOSEND_ENABLED=false"
  }
' "$runtime_env" >"$temporary"
chmod 600 "$temporary"
mv "$temporary" "$runtime_env"
trap - EXIT
echo "[configure-s610-long] configured=true phase=$phase signal_events=$signal_enabled bounded=$bounded autosend=false"
