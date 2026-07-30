#!/usr/bin/env bash
# Verify the immutable inputs to a business-specific Runtime Gate.
# This wrapper never modifies Runtime and never invokes a generic promotion.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  runtime-promotion.sh verify --runtime-root <detached-runtime> --expected-tag <annotated-tag> \
    --approval-packet <path> --approval-hash <sha256> [--json]
  runtime-promotion.sh promote --runtime-root <detached-runtime> --expected-tag <annotated-tag> \
    --approval-packet <path> --approval-hash <sha256> [--apply] [--json]

verify validates the exact tag, detached clean Runtime checkout, and packet hash.
promote is a handoff boundary: --apply is deliberately rejected because only a
business-specific, separately approved Runtime Gate may make a Runtime change.
EOF
}

fail() { echo "[REJECTED] $1" >&2; exit 2; }

[[ $# -gt 0 ]] || { usage >&2; exit 2; }
action="$1"
shift
[[ "$action" == "verify" || "$action" == "promote" ]] || fail "action must be verify or promote"

runtime_root=""
expected_tag=""
approval_packet=""
approval_hash=""
apply=false
json=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --runtime-root) runtime_root="${2:-}"; shift 2 ;;
    --expected-tag) expected_tag="${2:-}"; shift 2 ;;
    --approval-packet) approval_packet="${2:-}"; shift 2 ;;
    --approval-hash) approval_hash="${2:-}"; shift 2 ;;
    --apply) apply=true; shift ;;
    --json) json=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) fail "unsupported argument: $1" ;;
  esac
done

[[ -n "$runtime_root" && -n "$expected_tag" && -n "$approval_packet" && -n "$approval_hash" ]] || fail "runtime root, annotated tag, approval packet, and approval hash are required"
[[ "$approval_hash" =~ ^[0-9a-f]{64}$ ]] || fail "--approval-hash must be exactly 64 lowercase hexadecimal characters"
[[ -d "$runtime_root" ]] || fail "runtime root is unavailable"
[[ -f "$approval_packet" ]] || fail "approval packet is unavailable"
[[ "$action" != "verify" || "$apply" == false ]] || fail "verify does not accept --apply"

repo_root="$(git rev-parse --show-toplevel 2>/dev/null)" || fail "must run inside the release repository"
cd "$repo_root"
tag_object="$(git rev-parse --verify "${expected_tag}^{tag}" 2>/dev/null)" || fail "expected tag must exist and be annotated"
tag_commit="$(git rev-parse --verify "${expected_tag}^{commit}" 2>/dev/null)" || fail "expected tag does not resolve to a commit"
actual_packet_hash="$(shasum -a 256 "$approval_packet" | awk '{print $1}')"
[[ "$actual_packet_hash" == "$approval_hash" ]] || fail "approval packet hash does not match --approval-hash"
[[ "$(git -C "$runtime_root" rev-parse --is-inside-work-tree 2>/dev/null)" == "true" ]] || fail "runtime root is not a Git checkout"
if git -C "$runtime_root" symbolic-ref -q HEAD >/dev/null 2>&1; then
  fail "runtime checkout must be detached"
fi
runtime_sha="$(git -C "$runtime_root" rev-parse --verify HEAD 2>/dev/null)" || fail "runtime checkout has no HEAD"
[[ "$runtime_sha" == "$tag_commit" ]] || fail "runtime HEAD does not match expected annotated tag"
[[ -z "$(git -C "$runtime_root" status --porcelain)" ]] || fail "runtime checkout is not clean"

if [[ "$action" == "promote" && "$apply" == true ]]; then
  fail "generic Runtime promotion is forbidden; run the separately approved business-specific Gate"
fi

if [[ "$json" == true ]]; then
  python3 -c 'import json,sys; print(json.dumps({"schema_version":1,"tool":"scripts/engineering/runtime-promotion.sh","action":sys.argv[1],"mode":sys.argv[2],"status":"verified_manual_gate_required","bound_facts":{"expected_tag":sys.argv[3],"tag_object":sys.argv[4],"tag_commit":sys.argv[5],"runtime_head":sys.argv[6],"runtime_detached":True,"approval_packet_sha256":sys.argv[7]},"next_action":"Run only the separately approved business-specific Runtime Gate."},ensure_ascii=False))' "$action" "$([[ "$action" == "verify" ]] && echo verify || echo dry-run)" "$expected_tag" "$tag_object" "$tag_commit" "$runtime_sha" "$actual_packet_hash"
else
  echo "[OK] runtime inputs verified; manual business-specific Gate remains required"
fi
