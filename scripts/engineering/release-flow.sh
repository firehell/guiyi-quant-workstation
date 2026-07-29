#!/usr/bin/env bash
# Controlled, hash-bound publication of the local main/develop pair.
# Never tags, creates a GitHub Release, or changes Runtime.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/engineering/release-flow.sh publish --expected-sha <40-lowercase-hex> [--apply] [--json]

Default mode validates and prints the exact atomic push plan.  --apply publishes
only when local main and develop both equal --expected-sha and their registered
worktrees are clean.
EOF
}

fail() {
  echo "[REJECTED] $1" >&2
  exit 2
}

json_report() {
  local mode="$1"
  local status="$2"
  local sha="$3"
  printf '{"action":"publish","mode":"%s","status":"%s","bound_facts":{"expected_sha":"%s","main_sha":"%s","develop_sha":"%s"},"planned_commands":[["git","push","--atomic","origin","%s:refs/heads/main","%s:refs/heads/develop"]]}\n' \
    "$mode" "$status" "$sha" "$main_sha" "$develop_sha" "$sha" "$sha"
}

worktree_for_branch() {
  local wanted="$1"
  local line=""
  local candidate=""
  while IFS= read -r line || [[ -n "$line" ]]; do
    case "$line" in
      "worktree "*) candidate="${line#worktree }" ;;
      "branch refs/heads/${wanted}")
        [[ -n "$candidate" ]] || return 1
        printf '%s\n' "$candidate"
        return 0
        ;;
    esac
  done < <(git worktree list --porcelain)
  return 1
}

require_clean_worktree() {
  local branch="$1"
  local path=""
  path="$(worktree_for_branch "$branch")" || fail "registered ${branch} worktree is required"
  [[ -d "$path" ]] || fail "registered ${branch} worktree path is unavailable"
  [[ -z "$(git -C "$path" status --porcelain)" ]] || fail "${branch} worktree is not clean"
}

[[ $# -ge 1 ]] || { usage >&2; exit 2; }
action="$1"
shift
[[ "$action" == "publish" ]] || fail "only the publish action is supported"

expected_sha=""
apply=false
json=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --expected-sha)
      [[ $# -ge 2 ]] || fail "--expected-sha requires a value"
      expected_sha="$2"
      shift 2
      ;;
    --apply)
      apply=true
      shift
      ;;
    --json)
      json=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *) fail "unsupported argument: $1" ;;
  esac
done

[[ "$expected_sha" =~ ^[0-9a-f]{40}$ ]] || fail "--expected-sha must be exactly 40 lowercase hexadecimal characters"
repo_root="$(git rev-parse --show-toplevel 2>/dev/null)" || fail "must run inside a Git repository"
cd "$repo_root"
[[ "$(git branch --show-current)" == "main" ]] || fail "publish must run from the main worktree"
[[ -z "$(git status --porcelain)" ]] || fail "main worktree is not clean"
git remote get-url --push origin >/dev/null 2>&1 || fail "origin push remote is unavailable"

main_sha="$(git rev-parse --verify 'main^{commit}' 2>/dev/null)" || fail "main is unavailable"
develop_sha="$(git rev-parse --verify 'develop^{commit}' 2>/dev/null)" || fail "develop is unavailable"
[[ "$main_sha" == "$expected_sha" ]] || fail "main does not match --expected-sha"
[[ "$develop_sha" == "$expected_sha" ]] || fail "develop does not match --expected-sha"
require_clean_worktree main
require_clean_worktree develop

if [[ "$apply" != true ]]; then
  if [[ "$json" == true ]]; then
    json_report "dry-run" "ok" "$expected_sha"
  else
    echo "[OK] dry-run bound_sha=${expected_sha}"
    echo "[PLAN] git push --atomic origin ${expected_sha}:refs/heads/main ${expected_sha}:refs/heads/develop"
  fi
  exit 0
fi

git push --atomic origin "${expected_sha}:refs/heads/main" "${expected_sha}:refs/heads/develop"
git branch --set-upstream-to=origin/develop develop >/dev/null

remote_main=""
remote_develop=""
while IFS=$'\t' read -r sha ref; do
  case "$ref" in
    refs/heads/main) remote_main="$sha" ;;
    refs/heads/develop) remote_develop="$sha" ;;
  esac
done < <(git ls-remote --heads origin main develop)
[[ "$remote_main" == "$expected_sha" ]] || fail "remote main does not match --expected-sha after publish"
[[ "$remote_develop" == "$expected_sha" ]] || fail "remote develop does not match --expected-sha after publish"

if [[ "$json" == true ]]; then
  json_report "apply" "ok" "$expected_sha"
else
  echo "[OK] published main and develop at ${expected_sha}"
fi
