#!/usr/bin/env bash
# Controlled, hash-bound preparation, publication, and annotated tagging.
# Never creates a GitHub Release or changes Runtime.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/engineering/release-flow.sh prepare --current-main-sha <sha> --expected-sha <sha> [--apply] [--json]
  scripts/engineering/release-flow.sh publish --previous-main-sha <sha> --expected-sha <sha> [--apply] [--json]
  scripts/engineering/release-flow.sh tag --expected-sha <sha> \
    --release-tag <runtime-tag> --release-message <message> \
    --rollback-sha <sha> --rollback-tag <runtime-tag> \
    --rollback-message <message> [--apply] [--json]

Default mode validates and prints an exact plan.  prepare only fast-forwards
the clean local main worktree after verifying remote main/develop.  publish
atomically publishes matching main/develop refs.  tag creates and atomically
publishes two annotated tags only after both release refs are exact.
EOF
}

fail() {
  echo "[REJECTED] $1" >&2
  exit 2
}

digest_text() {
  printf '%s' "$1" | shasum -a 256 | awk '{print $1}'
}

json_prepare_report() {
  local mode="$1"
  printf '{"action":"prepare","mode":"%s","status":"ok","bound_facts":{"current_main_sha":"%s","expected_sha":"%s","main_sha":"%s","develop_sha":"%s","remote_main_sha":"%s","remote_develop_sha":"%s"},"planned_commands":[["git","merge","--ff-only","%s"]]}\n' \
    "$mode" "$current_main_sha" "$expected_sha" "$main_sha" "$develop_sha" \
    "$remote_main" "$remote_develop" "$expected_sha"
}

json_publish_report() {
  local mode="$1"
  printf '{"action":"publish","mode":"%s","status":"ok","bound_facts":{"previous_main_sha":"%s","expected_sha":"%s","main_sha":"%s","develop_sha":"%s","remote_main_sha":"%s","remote_develop_sha":"%s"},"planned_commands":[["git","push","--atomic","origin","%s:refs/heads/main","%s:refs/heads/develop"]]}\n' \
    "$mode" "$previous_main_sha" "$expected_sha" "$main_sha" "$develop_sha" \
    "$remote_main" "$remote_develop" "$expected_sha" "$expected_sha"
}

json_tag_report() {
  local mode="$1"
  local status="$2"
  if [[ "$status" == "already_published" ]]; then
    printf '{"action":"tag","mode":"%s","status":"already_published","bound_facts":{"expected_sha":"%s","release_tag":"%s","release_message_sha256":"%s","rollback_sha":"%s","rollback_tag":"%s","rollback_message_sha256":"%s"},"planned_commands":[]}\n' \
      "$mode" "$expected_sha" "$release_tag" "$(digest_text "$release_message")" \
      "$rollback_sha" "$rollback_tag" "$(digest_text "$rollback_message")"
    return
  fi
  printf '{"action":"tag","mode":"%s","status":"ok","bound_facts":{"expected_sha":"%s","release_tag":"%s","release_message_sha256":"%s","rollback_sha":"%s","rollback_tag":"%s","rollback_message_sha256":"%s"},"planned_commands":[["git","tag","-a","%s","%s","-m","<approved-release-message>"],["git","tag","-a","%s","%s","-m","<approved-rollback-message>"],["git","push","--atomic","origin","refs/tags/%s","refs/tags/%s"]]}\n' \
    "$mode" "$expected_sha" "$release_tag" "$(digest_text "$release_message")" \
    "$rollback_sha" "$rollback_tag" "$(digest_text "$rollback_message")" \
    "$release_tag" "$expected_sha" "$rollback_tag" "$rollback_sha" \
    "$release_tag" "$rollback_tag"
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

read_remote_release_refs() {
  local output=""
  remote_main=""
  remote_develop=""
  output="$(git ls-remote --heads origin main develop)" || fail "remote release ref read failed"
  while IFS=$'\t' read -r sha ref; do
    case "$ref" in
      refs/heads/main) remote_main="$sha" ;;
      refs/heads/develop) remote_develop="$sha" ;;
    esac
  done <<< "$output"
}

require_safe_tag_name() {
  local value="$1"
  [[ "$value" =~ ^runtime-[0-9A-Za-z._-]+$ ]] || fail "tag names must use the runtime-* contract"
}

read_remote_tag() {
  local value="$1"
  local output=""
  remote_tag_object=""
  remote_tag_target=""
  output="$(git ls-remote --tags origin "refs/tags/${value}" "refs/tags/${value}^{}")" \
    || fail "remote tag read failed: ${value}"
  while IFS=$'\t' read -r sha ref; do
    case "$ref" in
      "refs/tags/${value}") remote_tag_object="$sha" ;;
      "refs/tags/${value}^{}") remote_tag_target="$sha" ;;
    esac
  done <<< "$output"
}

existing_tag_matches() {
  local value="$1"
  local target="$2"
  local message="$3"
  local expected_remote_object="$4"
  local expected_remote_target="$5"
  local local_object=""
  git show-ref --verify --quiet "refs/tags/${value}" || return 1
  [[ "$(git cat-file -t "refs/tags/${value}" 2>/dev/null)" == "tag" ]] || return 1
  local_object="$(git rev-parse "refs/tags/${value}")"
  [[ "$local_object" == "$expected_remote_object" ]] || return 1
  [[ "$(git rev-parse "refs/tags/${value}^{}")" == "$target" ]] || return 1
  [[ "$expected_remote_target" == "$target" ]] || return 1
  [[ "$(git for-each-ref --format='%(contents)' "refs/tags/${value}")" == "$message" ]] || return 1
}

classify_tag_packet() {
  local release_remote_object=""
  local release_remote_target=""
  local rollback_remote_object=""
  local rollback_remote_target=""
  read_remote_tag "$release_tag"
  release_remote_object="$remote_tag_object"
  release_remote_target="$remote_tag_target"
  read_remote_tag "$rollback_tag"
  rollback_remote_object="$remote_tag_object"
  rollback_remote_target="$remote_tag_target"

  if ! git show-ref --verify --quiet "refs/tags/${release_tag}" \
    && ! git show-ref --verify --quiet "refs/tags/${rollback_tag}" \
    && [[ -z "$release_remote_object" && -z "$release_remote_target" \
      && -z "$rollback_remote_object" && -z "$rollback_remote_target" ]]; then
    tag_packet_state="absent"
    return
  fi

  if existing_tag_matches "$release_tag" "$expected_sha" "$release_message" \
      "$release_remote_object" "$release_remote_target" \
    && existing_tag_matches "$rollback_tag" "$rollback_sha" "$rollback_message" \
      "$rollback_remote_object" "$rollback_remote_target"; then
    tag_packet_state="exact"
    return
  fi
  fail "existing release tags do not match the approved packet"
}

[[ $# -ge 1 ]] || { usage >&2; exit 2; }
action="$1"
shift
[[ "$action" =~ ^(prepare|publish|tag)$ ]] || fail "supported actions are prepare, publish, and tag"

expected_sha=""
current_main_sha=""
previous_main_sha=""
release_tag=""
release_message=""
rollback_sha=""
rollback_tag=""
rollback_message=""
apply=false
json=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --expected-sha) [[ $# -ge 2 ]] || fail "--expected-sha requires a value"; expected_sha="$2"; shift 2 ;;
    --current-main-sha) [[ $# -ge 2 ]] || fail "--current-main-sha requires a value"; current_main_sha="$2"; shift 2 ;;
    --previous-main-sha) [[ $# -ge 2 ]] || fail "--previous-main-sha requires a value"; previous_main_sha="$2"; shift 2 ;;
    --release-tag) [[ $# -ge 2 ]] || fail "--release-tag requires a value"; release_tag="$2"; shift 2 ;;
    --release-message) [[ $# -ge 2 ]] || fail "--release-message requires a value"; release_message="$2"; shift 2 ;;
    --rollback-sha) [[ $# -ge 2 ]] || fail "--rollback-sha requires a value"; rollback_sha="$2"; shift 2 ;;
    --rollback-tag) [[ $# -ge 2 ]] || fail "--rollback-tag requires a value"; rollback_tag="$2"; shift 2 ;;
    --rollback-message) [[ $# -ge 2 ]] || fail "--rollback-message requires a value"; rollback_message="$2"; shift 2 ;;
    --apply) apply=true; shift ;;
    --json) json=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) fail "unsupported argument: $1" ;;
  esac
done

[[ "$expected_sha" =~ ^[0-9a-f]{40}$ ]] || fail "--expected-sha must be exactly 40 lowercase hexadecimal characters"
repo_root="$(git rev-parse --show-toplevel 2>/dev/null)" || fail "must run inside a Git repository"
cd "$repo_root"
[[ "$(git branch --show-current)" == "main" ]] || fail "release actions must run from the main worktree"
[[ -z "$(git status --porcelain)" ]] || fail "main worktree is not clean"
git remote get-url --push origin >/dev/null 2>&1 || fail "origin push remote is unavailable"

main_sha="$(git rev-parse --verify 'main^{commit}' 2>/dev/null)" || fail "main is unavailable"
develop_sha="$(git rev-parse --verify 'develop^{commit}' 2>/dev/null)" || fail "develop is unavailable"
require_clean_worktree main
require_clean_worktree develop

if [[ "$action" == "prepare" ]]; then
  [[ "$current_main_sha" =~ ^[0-9a-f]{40}$ ]] || fail "--current-main-sha must be exactly 40 lowercase hexadecimal characters"
  [[ "$main_sha" == "$current_main_sha" ]] || fail "main does not match --current-main-sha"
  [[ "$develop_sha" == "$expected_sha" ]] || fail "develop does not match --expected-sha"
  git merge-base --is-ancestor "$main_sha" "$expected_sha" || fail "expected release is not a fast-forward of main"
  read_remote_release_refs
  [[ "$remote_main" == "$current_main_sha" ]] || fail "remote main does not match --current-main-sha"
  [[ "$remote_develop" == "$expected_sha" ]] || fail "remote develop does not match --expected-sha"
  if [[ "$apply" != true ]]; then
    [[ "$json" == true ]] && json_prepare_report "dry-run" || echo "[PLAN] git merge --ff-only ${expected_sha}"
    exit 0
  fi
  if [[ "$json" == true ]]; then
    git merge --ff-only "$expected_sha" >/dev/null
  else
    git merge --ff-only "$expected_sha"
  fi
  main_sha="$(git rev-parse --verify 'main^{commit}')"
  [[ "$main_sha" == "$expected_sha" ]] || fail "main does not match --expected-sha after prepare"
  [[ "$json" == true ]] && json_prepare_report "apply" || echo "[OK] prepared local main at ${expected_sha}"
  exit 0
fi

[[ "$main_sha" == "$expected_sha" ]] || fail "main does not match --expected-sha"
[[ "$develop_sha" == "$expected_sha" ]] || fail "develop does not match --expected-sha"

if [[ "$action" == "publish" ]]; then
  [[ "$previous_main_sha" =~ ^[0-9a-f]{40}$ ]] || fail "--previous-main-sha must be exactly 40 lowercase hexadecimal characters"
  read_remote_release_refs
  [[ "$remote_main" == "$previous_main_sha" ]] || fail "remote main does not match --previous-main-sha"
  [[ "$remote_develop" == "$expected_sha" ]] || fail "remote develop does not match --expected-sha"
  if [[ "$apply" != true ]]; then
    [[ "$json" == true ]] && json_publish_report "dry-run" \
      || echo "[PLAN] git push --atomic origin ${expected_sha}:refs/heads/main ${expected_sha}:refs/heads/develop"
    exit 0
  fi
  git push --atomic origin "${expected_sha}:refs/heads/main" "${expected_sha}:refs/heads/develop"
  read_remote_release_refs
  [[ "$remote_main" == "$expected_sha" ]] || fail "remote main does not match --expected-sha after publish"
  [[ "$remote_develop" == "$expected_sha" ]] || fail "remote develop does not match --expected-sha after publish"
  [[ "$json" == true ]] && json_publish_report "apply" || echo "[OK] published main and develop at ${expected_sha}"
  exit 0
fi

[[ "$rollback_sha" =~ ^[0-9a-f]{40}$ ]] || fail "--rollback-sha must be exactly 40 lowercase hexadecimal characters"
require_safe_tag_name "$release_tag"
require_safe_tag_name "$rollback_tag"
[[ "$release_tag" != "$rollback_tag" ]] || fail "release and rollback tags must differ"
[[ -n "$release_message" && "$release_message" != *$'\n'* ]] || fail "--release-message must be one non-empty line"
[[ -n "$rollback_message" && "$rollback_message" != *$'\n'* ]] || fail "--rollback-message must be one non-empty line"
git cat-file -e "${expected_sha}^{commit}" 2>/dev/null || fail "expected release commit is unavailable"
git cat-file -e "${rollback_sha}^{commit}" 2>/dev/null || fail "rollback commit is unavailable"
read_remote_release_refs
[[ "$remote_main" == "$expected_sha" ]] || fail "remote main does not match --expected-sha"
[[ "$remote_develop" == "$expected_sha" ]] || fail "remote develop does not match --expected-sha"
classify_tag_packet
if [[ "$tag_packet_state" == "exact" ]]; then
  [[ "$json" == true ]] && json_tag_report "$(if [[ "$apply" == true ]]; then printf apply; else printf dry-run; fi)" "already_published" \
    || echo "[OK] approved annotated release and rollback tags are already published"
  exit 0
fi

if [[ "$apply" != true ]]; then
  [[ "$json" == true ]] && json_tag_report "dry-run" "ok" \
    || echo "[PLAN] create and atomically push annotated tags ${release_tag} ${rollback_tag}"
  exit 0
fi

git tag -a "$rollback_tag" "$rollback_sha" -m "$rollback_message"
if ! git tag -a "$release_tag" "$expected_sha" -m "$release_message"; then
  git tag -d "$rollback_tag" >/dev/null 2>&1 || true
  fail "failed to create release tag"
fi
if ! git push --atomic origin "refs/tags/${release_tag}" "refs/tags/${rollback_tag}"; then
  git tag -d "$release_tag" "$rollback_tag" >/dev/null 2>&1 || true
  fail "failed to atomically publish release tags"
fi

classify_tag_packet
[[ "$tag_packet_state" == "exact" ]] || fail "published release tags failed exact readback"
[[ "$json" == true ]] && json_tag_report "apply" "ok" || echo "[OK] published annotated release and rollback tags"
